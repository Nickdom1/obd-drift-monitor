"""
Mode 01 (Current Powertrain Diagnostic Data) Parser

Parses ISO 15765-4 CAN responses for OBD-II Service 01.

Structure per SAE J1979:
- Request: [01 PID]
- Response: [41 PID <data bytes>]
  Where 41 = 0x40 + 0x01 (positive response to service 01)

Data length and scaling vary by PID. Common examples:
- PID 00: Supported PIDs 01-20 (4 bytes, bitmap)
- PID 0C: Engine RPM (2 bytes, scale = value/4)
- PID 0D: Vehicle speed (1 byte, km/h)
- PID 05: Coolant temperature (1 byte, °C = value - 40)
- PID 0F: Intake air temperature (1 byte, °C = value - 40)

This module parses the common standard PIDs listed in PID_DEFINITIONS. A PID
not in that table is returned with its raw payload bytes and no scaled value.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PidValue:
    """
    Represents a single Mode 01 PID value.

    Attributes:
        pid: Parameter ID (0x00-0xFF)
        value_raw: Raw bytes from ECU response
        value: Scaled numeric value (if applicable)
        unit: Unit string (e.g., "rpm", "km/h", "°C")
        name: Human-readable parameter name
    """

    pid: int
    value_raw: bytes
    value: Optional[float] = None
    unit: Optional[str] = None
    name: Optional[str] = None

    def __post_init__(self):
        """Validate PID range."""
        if not (0 <= self.pid <= 0xFF):
            raise ValueError(f"PID out of range: {self.pid:#04x}")


# J1979 standard PID scalings. Each entry is (name, unit, expected_len, scaling_func),
# where scaling_func maps the payload bytes to a numeric value (None for bitmaps).
# Whether a given ECU actually reports a PID is discovered at runtime via parse_supported_pids().
PID_DEFINITIONS = {
    0x00: ("Supported PIDs 01-20", "bitmap", 4, None),
    0x05: ("Engine coolant temperature", "°C", 1, lambda x: x[0] - 40),
    0x0C: ("Engine RPM", "rpm", 2, lambda x: ((x[0] << 8) | x[1]) / 4.0),
    0x0D: ("Vehicle speed", "km/h", 1, lambda x: x[0]),
    0x0F: ("Intake air temperature", "°C", 1, lambda x: x[0] - 40),
    0x10: ("MAF air flow rate", "g/s", 2, lambda x: ((x[0] << 8) | x[1]) / 100.0),
    0x11: ("Throttle position", "%", 1, lambda x: x[0] * 100.0 / 255.0),
    0x20: ("Supported PIDs 21-40", "bitmap", 4, None),
    0x2F: ("Fuel tank level", "%", 1, lambda x: x[0] * 100.0 / 255.0),
    0x40: ("Supported PIDs 41-60", "bitmap", 4, None),
    0x46: ("Ambient air temperature", "°C", 1, lambda x: x[0] - 40),
    0x60: ("Supported PIDs 61-80", "bitmap", 4, None),
    0x80: ("Supported PIDs 81-A0", "bitmap", 4, None),
    0xA0: ("Supported PIDs A1-C0", "bitmap", 4, None),
    0xC0: ("Supported PIDs C1-E0", "bitmap", 4, None),
}


def parse_mode01(data: bytes) -> List[PidValue]:
    """
    Parse a Mode 01 response into PidValue objects.

    Args:
        data: Raw CAN response bytes, starting with service byte
              Expected format: [41 PID <data bytes>]

    Returns:
        List containing a single PidValue (Mode 01 returns one PID per response)

    Raises:
        ValueError: If data is malformed or doesn't match Mode 01 structure

    Examples:
        >>> # Engine RPM = 2000 (raw value 8000, scaled by /4)
        >>> data = bytes([0x41, 0x0C, 0x1F, 0x40])
        >>> results = parse_mode01(data)
        >>> len(results)
        1
        >>> results[0].pid
        12
        >>> results[0].value
        2000.0
        >>> results[0].unit
        'rpm'

        >>> # Vehicle speed = 65 km/h
        >>> data = bytes([0x41, 0x0D, 0x41])
        >>> results = parse_mode01(data)
        >>> results[0].value
        65.0
    """
    if len(data) < 3:
        raise ValueError(f"Mode 01 response too short: {len(data)} bytes")

    service = data[0]
    if service != 0x41:
        raise ValueError(f"Not a Mode 01 response: service byte {service:#04x}")

    pid = data[1]
    payload = data[2:]

    # Look up PID definition
    pid_def = PID_DEFINITIONS.get(pid)

    if pid_def:
        name, unit, expected_len, scaling_func = pid_def

        if len(payload) != expected_len:
            raise ValueError(
                f"PID {pid:#04x} expected {expected_len} bytes, got {len(payload)}"
            )

        # Apply scaling if function provided
        if scaling_func:
            try:
                value = scaling_func(payload)
            except Exception as e:
                raise ValueError(f"Failed to scale PID {pid:#04x}: {e}")
        else:
            # No scaling (e.g., bitmaps)
            value = None

        result = PidValue(pid=pid, value_raw=payload, value=value, unit=unit, name=name)
    else:
        # Unknown PID: no scaling definition, so no scaled value or unit—just the raw bytes.
        result = PidValue(
            pid=pid,
            value_raw=payload,
            value=None,
            unit=None,
            name=f"PID_{pid:02X}",
        )

    return [result]


def parse_supported_pids(data: bytes) -> List[int]:
    """
    Parse a Mode 01 supported-PID bitmap response.

    Args:
        data: Response to "01 00", "01 20", etc.
              Format: [41 <query_pid> <4-byte bitmap>]

    Returns:
        List of supported PID values (e.g., [0x01, 0x05, 0x0C, ...])

    Examples:
        >>> # PIDs 01, 05, 0C supported (bits 0, 4, 11 set)
        >>> # Bitmap: 0x90100000 = 10010000 00010000 00000000 00000000
        >>> data = bytes([0x41, 0x00, 0x90, 0x10, 0x00, 0x00])
        >>> parse_supported_pids(data)
        [1, 5, 12]
    """
    if len(data) != 6:
        raise ValueError(f"Supported PID response must be 6 bytes, got {len(data)}")

    if data[0] != 0x41:
        raise ValueError(f"Not a Mode 01 response: {data[0]:#04x}")

    query_pid = data[1]
    bitmap_bytes = data[2:6]

    # Convert 4 bytes to 32-bit integer (big-endian)
    bitmap = int.from_bytes(bitmap_bytes, byteorder="big")

    supported = []
    for bit_pos in range(32):
        if bitmap & (1 << (31 - bit_pos)):
            # PID = query_pid + bit_position + 1
            supported.append(query_pid + bit_pos + 1)

    return supported
