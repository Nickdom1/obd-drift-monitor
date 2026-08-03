"""
Mode 06 (On-Board Monitoring Test Results) Parser

Parses ISO 15765-4 CAN responses for OBD-II Service 06.

Structure per SAE J1979:
- Each monitor result consists of:
  - MID (Monitor ID): 1 byte
  - TID/UASID (Test ID / Unit and Scaling ID): 1 byte
  - Test Value: 2 bytes (big-endian)
  - Min Limit: 2 bytes (big-endian)
  - Max Limit: 2 bytes (big-endian)
  - Total: 7 bytes per result

UASID notes:
- High bit (0x80) set = manufacturer-defined test
- Low 7 bits encode both unit and scaling per J1979 table
- Scaling applied to all three values (test, min, max)

Response to Mode 06 request (e.g., "06 01" for MID 01):
  [46 01 <7-byte result 1> <7-byte result 2> ...]
  Where 46 = 0x40 + 0x06 (positive response to service 06)
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MonitorResult:
    """
    Represents a single Mode 06 monitor test result.

    Attributes:
        mid: Monitor ID (0x00-0xFF)
        tid: Test ID (0x00-0x7F) or UASID with high bit set
        test_value_raw: Raw test value from ECU (unscaled)
        min_limit_raw: Raw minimum limit (unscaled)
        max_limit_raw: Raw maximum limit (unscaled)
        test_value: Scaled test value (if scaling known, else None)
        min_limit: Scaled min limit (if scaling known, else None)
        max_limit: Scaled max limit (if scaling known, else None)
        unit: Unit string (e.g., "V", "°C", "counts") if known
        name: Human-readable test name (from decode table)
        is_manufacturer_defined: True if UASID high bit set
        passed: True if min <= test <= max, False otherwise, None if limits invalid
    """

    mid: int
    tid: int
    test_value_raw: int
    min_limit_raw: int
    max_limit_raw: int
    test_value: Optional[float] = None
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    unit: Optional[str] = None
    name: Optional[str] = None
    is_manufacturer_defined: bool = False
    passed: Optional[bool] = None

    def __post_init__(self):
        """Validate ranges and compute pass/fail if limits are valid."""
        if not (0 <= self.mid <= 0xFF):
            raise ValueError(f"MID out of range: {self.mid:#04x}")
        if not (0 <= self.tid <= 0xFF):
            raise ValueError(f"TID out of range: {self.tid:#04x}")

        # Check if manufacturer-defined
        self.is_manufacturer_defined = bool(self.tid & 0x80)

        # Compute pass/fail if scaled values available
        if (
            self.test_value is not None
            and self.min_limit is not None
            and self.max_limit is not None
        ):
            # Some monitors use 0xFFFF as "not applicable" sentinel
            if self.min_limit_raw == 0xFFFF or self.max_limit_raw == 0xFFFF:
                self.passed = None
            else:
                self.passed = self.min_limit <= self.test_value <= self.max_limit


def parse_mode06(data: bytes) -> List[MonitorResult]:
    """
    Parse a Mode 06 response into MonitorResult objects.

    Args:
        data: Raw CAN response bytes, starting with service byte
              Expected format: [46 MID <7-byte result>*]
              OR for supported MID query: [46 00 <supported bitmap>]

    Returns:
        List of MonitorResult objects (empty if response is supported-MID bitmap)

    Raises:
        ValueError: If data is malformed or doesn't match Mode 06 structure

    Examples:
        >>> # Supported MID query response (bitmap, not parsed as results)
        >>> parse_mode06(bytes([0x46, 0x00, 0xFF, 0xFF, 0xFF, 0xFF]))
        []

        >>> # Single monitor result (synthetic)
        >>> data = bytes([0x46, 0x01, 0x85, 0x00, 0x64, 0x00, 0x00, 0x00, 0xC8])
        >>> results = parse_mode06(data)
        >>> len(results)
        1
        >>> results[0].mid
        1
        >>> hex(results[0].tid)
        '0x85'
        >>> results[0].test_value_raw
        100
    """
    if len(data) < 2:
        raise ValueError(f"Mode 06 response too short: {len(data)} bytes")

    service = data[0]
    if service != 0x46:
        raise ValueError(f"Not a Mode 06 response: service byte {service:#04x}")

    mid = data[1]
    payload = data[2:]

    # Special case: supported MID query (MID 00, 20, 40, etc.)
    # Response is 4-byte bitmap, not test results
    if mid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0):
        if len(payload) == 4:
            # This is a supported-MID bitmap—don't parse as results
            return []
        # If payload is not 4 bytes, fall through and try parsing as results

    # Each result is 7 bytes: TID (1) + value (2) + min (2) + max (2)
    if len(payload) % 7 != 0:
        raise ValueError(
            f"Mode 06 payload length {len(payload)} not a multiple of 7 "
            f"(MID {mid:#04x})"
        )

    results = []
    for i in range(0, len(payload), 7):
        chunk = payload[i : i + 7]

        tid = chunk[0]
        test_value_raw = (chunk[1] << 8) | chunk[2]
        min_limit_raw = (chunk[3] << 8) | chunk[4]
        max_limit_raw = (chunk[5] << 8) | chunk[6]

        # Scaling and naming require a decode-table lookup; the parser emits raw values only.
        result = MonitorResult(
            mid=mid,
            tid=tid,
            test_value_raw=test_value_raw,
            min_limit_raw=min_limit_raw,
            max_limit_raw=max_limit_raw,
        )

        results.append(result)

    return results


def parse_supported_mids(data: bytes) -> List[int]:
    """
    Parse a Mode 06 supported-MID bitmap response.

    Args:
        data: Response to "06 00", "06 20", etc.
              Format: [46 <query_mid> <4-byte bitmap>]

    Returns:
        List of supported MID values (e.g., [0x01, 0x02, 0x05, ...])

    Examples:
        >>> # MIDs 01, 02, 03 supported (first 3 bits set)
        >>> parse_supported_mids(bytes([0x46, 0x00, 0xE0, 0x00, 0x00, 0x00]))
        [1, 2, 3]
    """
    if len(data) != 6:
        raise ValueError(f"Supported MID response must be 6 bytes, got {len(data)}")

    if data[0] != 0x46:
        raise ValueError(f"Not a Mode 06 response: {data[0]:#04x}")

    query_mid = data[1]
    bitmap_bytes = data[2:6]

    # Convert 4 bytes to 32-bit integer (big-endian)
    bitmap = int.from_bytes(bitmap_bytes, byteorder="big")

    supported = []
    for bit_pos in range(32):
        if bitmap & (1 << (31 - bit_pos)):
            # MID = query_mid + bit_position + 1
            # (bit 0 represents query_mid + 1, bit 1 represents query_mid + 2, etc.)
            supported.append(query_mid + bit_pos + 1)

    return supported
