"""
Test suite for Mode 06 parser.

Golden tests with hand-built synthetic CAN payloads per SAE J1979 structure.
"""

import pytest

from pkgs.decode.mode06 import MonitorResult, parse_mode06, parse_supported_mids


class TestMode06Parser:
    """Test Mode 06 response parsing."""

    def test_single_monitor_result(self):
        """Parse a single monitor result with known structure."""
        # Synthetic payload: MID 0x01, TID 0x01 (O2S11 Rich-to-Lean Threshold)
        # Test value: 0x0064 (100 decimal)
        # Min limit:  0x0000 (0)
        # Max limit:  0x00C8 (200)
        data = bytes(
            [
                0x46,  # Service 06 response (0x40 + 0x06)
                0x01,  # MID 0x01
                0x01,  # TID 0x01 (standardized, high bit clear)
                0x00,
                0x64,  # Test value = 100
                0x00,
                0x00,  # Min limit = 0
                0x00,
                0xC8,  # Max limit = 200
            ]
        )

        results = parse_mode06(data)

        assert len(results) == 1
        result = results[0]
        assert result.mid == 0x01
        assert result.tid == 0x01
        assert result.test_value_raw == 100
        assert result.min_limit_raw == 0
        assert result.max_limit_raw == 200
        assert result.is_manufacturer_defined is False
        assert result.passed is None  # no decode table applied yet

    def test_multiple_monitor_results(self):
        """Parse multiple monitor results in a single response."""
        # MID 0x01 with two TIDs
        data = bytes(
            [
                0x46,  # Service 06 response
                0x01,  # MID 0x01
                # First result: TID 0x01
                0x01,
                0x00,
                0x50,  # Test value = 80
                0x00,
                0x00,  # Min = 0
                0x00,
                0xC8,  # Max = 200
                # Second result: TID 0x02
                0x02,
                0x00,
                0xB4,  # Test value = 180
                0x00,
                0x00,  # Min = 0
                0x00,
                0xC8,  # Max = 200
            ]
        )

        results = parse_mode06(data)

        assert len(results) == 2
        assert results[0].tid == 0x01
        assert results[0].test_value_raw == 80
        assert results[1].tid == 0x02
        assert results[1].test_value_raw == 180

    def test_manufacturer_defined_tid(self):
        """Parse a manufacturer-defined test (UASID high bit set)."""
        # TID 0x85 (0x80 | 0x05) = manufacturer-defined
        data = bytes(
            [
                0x46,
                0x01,
                0x85,  # High bit set = manufacturer-defined
                0x01,
                0x00,  # Test value = 256
                0x00,
                0x00,  # Min = 0
                0xFF,
                0xFF,  # Max = 65535
            ]
        )

        results = parse_mode06(data)

        assert len(results) == 1
        result = results[0]
        assert result.tid == 0x85
        assert result.is_manufacturer_defined is True
        assert result.test_value_raw == 256

    def test_raw_values_preserved(self):
        """Parser preserves raw values even when value is outside limit range."""
        data = bytes(
            [
                0x46,
                0x01,
                0x01,
                0x00,
                0xFA,  # Test value = 250
                0x00,
                0x00,  # Min = 0
                0x00,
                0xC8,  # Max = 200
            ]
        )

        results = parse_mode06(data)

        assert len(results) == 1
        assert results[0].test_value_raw == 250
        assert results[0].min_limit_raw == 0
        assert results[0].max_limit_raw == 200
        assert results[0].passed is None  # pass/fail requires decode table

    def test_mid_from_different_monitor_group(self):
        """Parse result from a different MID group (catalyst monitoring)."""
        data = bytes(
            [
                0x46,
                0x21,  # MID 0x21 (Catalyst monitoring)
                0x0D,  # TID 0x0D
                0x00,
                0x0A,  # Test value = 10
                0x00,
                0x32,  # Min = 50
                0x00,
                0xC8,  # Max = 200
            ]
        )

        results = parse_mode06(data)

        assert len(results) == 1
        assert results[0].mid == 0x21
        assert results[0].tid == 0x0D
        assert results[0].test_value_raw == 10

    def test_invalid_limits_sentinel(self):
        """Parse a monitor with 0xFFFF sentinel (not applicable)."""
        # Some monitors use 0xFFFF to indicate "no limit"
        data = bytes(
            [
                0x46,
                0x01,
                0x01,
                0x00,
                0x64,  # Test value = 100
                0xFF,
                0xFF,  # Min = 0xFFFF (sentinel)
                0xFF,
                0xFF,  # Max = 0xFFFF (sentinel)
            ]
        )

        results = parse_mode06(data)

        assert len(results) == 1
        assert results[0].test_value_raw == 100
        assert results[0].min_limit_raw == 0xFFFF
        assert results[0].max_limit_raw == 0xFFFF
        assert results[0].passed is None  # pass/fail requires the decode table

    def test_supported_mids_query_response(self):
        """Parse a supported-MID bitmap response (MID 00, 20, etc.)."""
        # Response to "06 00" query (which MIDs 01-20 are supported)
        # Bitmap: first 3 bits set = MIDs 01, 02, 03 supported
        data = bytes(
            [
                0x46,
                0x00,  # Query MID
                0xE0,
                0x00,
                0x00,
                0x00,  # Bitmap: 11100000...
            ]
        )

        # Should return empty list (not parsed as monitor results)
        results = parse_mode06(data)
        assert len(results) == 0

    def test_malformed_response_too_short(self):
        """Reject response that's too short."""
        data = bytes([0x46])
        with pytest.raises(ValueError, match="too short"):
            parse_mode06(data)

    def test_malformed_response_wrong_service(self):
        """Reject response with wrong service byte."""
        data = bytes([0x41, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        with pytest.raises(ValueError, match="Not a Mode 06 response"):
            parse_mode06(data)

    def test_malformed_payload_not_multiple_of_seven(self):
        """Reject payload that's not a multiple of 7 bytes."""
        # 5 bytes after MID (should be 7, 14, 21, ...)
        data = bytes([0x46, 0x01, 0x01, 0x00, 0x64, 0x00, 0x00])
        with pytest.raises(ValueError, match="not a multiple of 7"):
            parse_mode06(data)

    def test_mid_out_of_range(self):
        """Reject invalid MID value."""
        # MonitorResult validation happens in __post_init__
        with pytest.raises(ValueError, match="MID out of range"):
            MonitorResult(
                mid=0x100,  # Out of range
                tid=0x01,
                test_value_raw=100,
                min_limit_raw=0,
                max_limit_raw=200,
            )

    def test_tid_out_of_range(self):
        """Reject invalid TID value."""
        with pytest.raises(ValueError, match="TID out of range"):
            MonitorResult(
                mid=0x01,
                tid=0x100,  # Out of range
                test_value_raw=100,
                min_limit_raw=0,
                max_limit_raw=200,
            )


class TestSupportedMidsParser:
    """Test supported-MID bitmap parsing."""

    def test_parse_supported_mids_query_00(self):
        """Parse response to MID 00 query (MIDs 01-20)."""
        # Bitmap: first 3 bits set
        data = bytes([0x46, 0x00, 0xE0, 0x00, 0x00, 0x00])
        supported = parse_supported_mids(data)
        assert supported == [1, 2, 3]

    def test_parse_supported_mids_query_20(self):
        """Parse response to MID 20 query (MIDs 21-40)."""
        # Bitmap: bits for MIDs 21, 24, 28
        # Bit 0 (MSB) = MID 21, bit 3 = MID 24, bit 7 = MID 28
        data = bytes([0x46, 0x20, 0x91, 0x00, 0x00, 0x00])
        # 0x91 = 10010001
        supported = parse_supported_mids(data)
        # Bit 0 -> MID 21, bit 3 -> MID 24, bit 7 -> MID 28
        assert 0x21 in supported
        assert 0x24 in supported
        assert 0x28 in supported

    def test_parse_supported_mids_all_supported(self):
        """Parse bitmap with all 32 MIDs supported."""
        data = bytes([0x46, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])
        supported = parse_supported_mids(data)
        assert len(supported) == 32
        assert supported == list(range(1, 33))

    def test_parse_supported_mids_none_supported(self):
        """Parse bitmap with no MIDs supported."""
        data = bytes([0x46, 0x00, 0x00, 0x00, 0x00, 0x00])
        supported = parse_supported_mids(data)
        assert supported == []

    def test_supported_mids_wrong_length(self):
        """Reject response with wrong length."""
        data = bytes([0x46, 0x00, 0xFF, 0xFF])
        with pytest.raises(ValueError, match="must be 6 bytes"):
            parse_supported_mids(data)

    def test_supported_mids_wrong_service(self):
        """Reject response with wrong service byte."""
        data = bytes([0x41, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])
        with pytest.raises(ValueError, match="Not a Mode 06 response"):
            parse_supported_mids(data)


class TestMonitorResultDataclass:
    """Test MonitorResult dataclass behavior."""

    def test_pass_fail_computation(self):
        """Verify pass/fail is computed correctly in __post_init__."""
        # Passing case
        result = MonitorResult(
            mid=0x01,
            tid=0x01,
            test_value_raw=100,
            min_limit_raw=50,
            max_limit_raw=150,
            test_value=100.0,
            min_limit=50.0,
            max_limit=150.0,
        )
        assert result.passed is True

        # Failing case (above max)
        result = MonitorResult(
            mid=0x01,
            tid=0x01,
            test_value_raw=200,
            min_limit_raw=50,
            max_limit_raw=150,
            test_value=200.0,
            min_limit=50.0,
            max_limit=150.0,
        )
        assert result.passed is False

        # Failing case (below min)
        result = MonitorResult(
            mid=0x01,
            tid=0x01,
            test_value_raw=10,
            min_limit_raw=50,
            max_limit_raw=150,
            test_value=10.0,
            min_limit=50.0,
            max_limit=150.0,
        )
        assert result.passed is False

    def test_pass_fail_none_when_scaled_values_missing(self):
        """If scaled values are None, passed should remain None."""
        result = MonitorResult(
            mid=0x01,
            tid=0x01,
            test_value_raw=100,
            min_limit_raw=50,
            max_limit_raw=150,
            # No scaled values provided
        )
        assert result.passed is None

    def test_manufacturer_defined_flag(self):
        """Verify is_manufacturer_defined flag is set correctly."""
        # Standard TID (high bit clear)
        result = MonitorResult(
            mid=0x01,
            tid=0x7F,
            test_value_raw=100,
            min_limit_raw=0,
            max_limit_raw=200,
        )
        assert result.is_manufacturer_defined is False

        # Manufacturer-defined TID (high bit set)
        result = MonitorResult(
            mid=0x01,
            tid=0x80,
            test_value_raw=100,
            min_limit_raw=0,
            max_limit_raw=200,
        )
        assert result.is_manufacturer_defined is True

        result = MonitorResult(
            mid=0x01,
            tid=0xFF,
            test_value_raw=100,
            min_limit_raw=0,
            max_limit_raw=200,
        )
        assert result.is_manufacturer_defined is True
