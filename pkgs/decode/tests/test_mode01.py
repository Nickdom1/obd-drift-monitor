"""
Test suite for Mode 01 parser.

Golden tests with hand-built synthetic CAN payloads per SAE J1979 structure.
"""

import pytest

from pkgs.decode.mode01 import PidValue, parse_mode01, parse_supported_pids


class TestMode01Parser:
    """Test Mode 01 response parsing."""

    def test_engine_rpm(self):
        """Parse engine RPM (PID 0x0C)."""
        # RPM = 2000, raw value = 2000 * 4 = 8000 = 0x1F40
        data = bytes(
            [
                0x41,  # Service 01 response (0x40 + 0x01)
                0x0C,  # PID 0x0C (Engine RPM)
                0x1F,
                0x40,  # 8000 / 4 = 2000 RPM
            ]
        )

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x0C
        assert result.value == 2000.0
        assert result.unit == "rpm"
        assert result.name == "Engine RPM"

    def test_vehicle_speed(self):
        """Parse vehicle speed (PID 0x0D)."""
        # Speed = 65 km/h (direct value, no scaling)
        data = bytes(
            [
                0x41,
                0x0D,  # PID 0x0D (Vehicle speed)
                0x41,  # 65 decimal
            ]
        )

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x0D
        assert result.value == 65.0
        assert result.unit == "km/h"
        assert result.name == "Vehicle speed"

    def test_coolant_temperature(self):
        """Parse engine coolant temperature (PID 0x05)."""
        # Temp = 90°C, raw value = 90 + 40 = 130 = 0x82
        data = bytes(
            [
                0x41,
                0x05,  # PID 0x05 (Coolant temp)
                0x82,  # 130 - 40 = 90°C
            ]
        )

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x05
        assert result.value == 90.0
        assert result.unit == "°C"
        assert result.name == "Engine coolant temperature"

    def test_coolant_temperature_negative(self):
        """Parse engine coolant temperature below 0°C."""
        # Temp = -10°C, raw value = -10 + 40 = 30 = 0x1E
        data = bytes([0x41, 0x05, 0x1E])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.value == -10.0

    def test_intake_air_temperature(self):
        """Parse intake air temperature (PID 0x0F)."""
        # Temp = 25°C, raw value = 25 + 40 = 65 = 0x41
        data = bytes([0x41, 0x0F, 0x41])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x0F
        assert result.value == 25.0
        assert result.unit == "°C"

    def test_maf_air_flow_rate(self):
        """Parse MAF air flow rate (PID 0x10)."""
        # Flow = 15.5 g/s, raw value = 15.5 * 100 = 1550 = 0x060E
        data = bytes([0x41, 0x10, 0x06, 0x0E])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x10
        assert result.value == 15.5
        assert result.unit == "g/s"

    def test_throttle_position(self):
        """Parse throttle position (PID 0x11)."""
        # Throttle = 50%, raw value = 50 * 255 / 100 = 127.5 ≈ 128 = 0x80
        data = bytes([0x41, 0x11, 0x80])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x11
        assert abs(result.value - 50.196) < 0.01  # 128 * 100 / 255 ≈ 50.196%
        assert result.unit == "%"

    def test_fuel_tank_level(self):
        """Parse fuel tank level (PID 0x2F)."""
        # Fuel = 75%, raw value = 75 * 255 / 100 ≈ 191 = 0xBF
        data = bytes([0x41, 0x2F, 0xBF])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x2F
        assert abs(result.value - 74.902) < 0.01  # 191 * 100 / 255
        assert result.unit == "%"

    def test_ambient_air_temperature(self):
        """Parse ambient air temperature (PID 0x46)."""
        # Temp = 20°C, raw value = 20 + 40 = 60 = 0x3C
        data = bytes([0x41, 0x46, 0x3C])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x46
        assert result.value == 20.0
        assert result.unit == "°C"

    def test_supported_pids_query_response(self):
        """Parse supported PIDs bitmap response (PID 00, 20, etc.)."""
        # Response to "01 00" query
        # No scaling for bitmap—should return None for value
        data = bytes([0x41, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x00
        assert result.value is None  # Bitmaps have no scaled value
        assert result.unit == "bitmap"
        assert len(result.value_raw) == 4

    def test_unknown_pid(self):
        """Parse an unknown PID (not in PID_DEFINITIONS)."""
        # PID 0x99 is not defined
        data = bytes([0x41, 0x99, 0x12, 0x34])

        results = parse_mode01(data)

        assert len(results) == 1
        result = results[0]
        assert result.pid == 0x99
        assert result.value is None
        assert result.unit is None
        assert result.name == "PID_99"
        assert result.value_raw == bytes([0x12, 0x34])

    def test_malformed_response_too_short(self):
        """Reject response that's too short."""
        data = bytes([0x41])
        with pytest.raises(ValueError, match="too short"):
            parse_mode01(data)

    def test_malformed_response_wrong_service(self):
        """Reject response with wrong service byte."""
        data = bytes([0x46, 0x0C, 0x1F, 0x40])
        with pytest.raises(ValueError, match="Not a Mode 01 response"):
            parse_mode01(data)

    def test_malformed_response_wrong_payload_length(self):
        """Reject response with wrong payload length for known PID."""
        # PID 0x0C expects 2 bytes, but only 1 provided
        data = bytes([0x41, 0x0C, 0x1F])
        with pytest.raises(ValueError, match="expected 2 bytes, got 1"):
            parse_mode01(data)

    def test_pid_out_of_range(self):
        """Reject invalid PID value."""
        with pytest.raises(ValueError, match="PID out of range"):
            PidValue(pid=0x100, value_raw=bytes([0x00]))


class TestSupportedPidsParser:
    """Test supported-PID bitmap parsing."""

    def test_parse_supported_pids_query_00(self):
        """Parse response to PID 00 query (PIDs 01-20)."""
        # Bitmap: 0x90100000 = 10010000 00010000 00000000 00000000
        # Bit 0 (MSB) = PID 01, bit 3 = PID 04, bit 11 = PID 12
        data = bytes([0x41, 0x00, 0x90, 0x10, 0x00, 0x00])

        supported = parse_supported_pids(data)

        assert 0x01 in supported  # Bit 0
        assert 0x04 in supported  # Bit 3
        assert 0x0C in supported  # Bit 11

    def test_parse_supported_pids_query_20(self):
        """Parse response to PID 20 query (PIDs 21-40)."""
        # First bit set = PID 21
        data = bytes([0x41, 0x20, 0x80, 0x00, 0x00, 0x00])

        supported = parse_supported_pids(data)

        assert 0x21 in supported

    def test_parse_supported_pids_all_supported(self):
        """Parse bitmap with all 32 PIDs supported."""
        data = bytes([0x41, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])

        supported = parse_supported_pids(data)

        assert len(supported) == 32
        assert supported == list(range(1, 33))

    def test_parse_supported_pids_none_supported(self):
        """Parse bitmap with no PIDs supported."""
        data = bytes([0x41, 0x00, 0x00, 0x00, 0x00, 0x00])

        supported = parse_supported_pids(data)

        assert supported == []

    def test_parse_supported_pids_specific_pattern(self):
        """Parse a specific bitmap pattern."""
        # PID 00 query with bitmap 0xBE1FA813
        # This represents a realistic pattern of supported PIDs
        data = bytes([0x41, 0x00, 0xBE, 0x1F, 0xA8, 0x13])

        supported = parse_supported_pids(data)

        # Should include these PIDs (based on set bits)
        assert 0x01 in supported  # Bit 0
        assert 0x03 in supported  # Bit 2
        assert 0x04 in supported  # Bit 3
        assert 0x05 in supported  # Bit 4
        assert 0x06 in supported  # Bit 5
        assert 0x07 in supported  # Bit 6
        # Should not include PID 0x02 (bit 1 not set)
        assert 0x02 not in supported

    def test_supported_pids_wrong_length(self):
        """Reject response with wrong length."""
        data = bytes([0x41, 0x00, 0xFF, 0xFF])
        with pytest.raises(ValueError, match="must be 6 bytes"):
            parse_supported_pids(data)

    def test_supported_pids_wrong_service(self):
        """Reject response with wrong service byte."""
        data = bytes([0x46, 0x00, 0xFF, 0xFF, 0xFF, 0xFF])
        with pytest.raises(ValueError, match="Not a Mode 01 response"):
            parse_supported_pids(data)


class TestPidValueDataclass:
    """Test PidValue dataclass behavior."""

    def test_pid_validation(self):
        """Verify PID range validation in __post_init__."""
        # Valid PID
        result = PidValue(pid=0x00, value_raw=bytes([0x00]))
        assert result.pid == 0x00

        result = PidValue(pid=0xFF, value_raw=bytes([0x00]))
        assert result.pid == 0xFF

        # Invalid PID (out of range)
        with pytest.raises(ValueError, match="PID out of range"):
            PidValue(pid=-1, value_raw=bytes([0x00]))

        with pytest.raises(ValueError, match="PID out of range"):
            PidValue(pid=0x100, value_raw=bytes([0x00]))

    def test_optional_fields(self):
        """Verify optional fields default to None."""
        result = PidValue(pid=0x99, value_raw=bytes([0x12, 0x34]))

        assert result.value is None
        assert result.unit is None
        assert result.name is None
