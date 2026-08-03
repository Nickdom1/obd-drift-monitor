//! Core data types shared by the Mode 01 and Mode 06 decoders.
//!
//! These mirror the Python `PidValue` / `MonitorResult` dataclasses, with one
//! deliberate correction baked into the type system: `MonitorResult` carries a
//! **separate `uasid`** field. The old Python parser folded TID and UASID into a
//! single byte, which is part of the framing bug this rewrite fixes. In the real
//! J1979 CAN layout the two are distinct bytes with distinct jobs:
//!   - `tid`   (Test ID)             -> selects the *name* of the test, via (MID, TID)
//!   - `uasid` (Unit And Scaling ID) -> selects the *scaling/unit*, via the UAS table
//!
//! Manufacturer-defined monitors are therefore identified by `uasid & 0x80`,
//! **not** `tid & 0x80`.

use std::fmt;

/// Errors that can occur while decoding a raw OBD-II response.
///
/// Hand-rolled (rather than pulling in `thiserror`) to keep the decode crate
/// dependency-free for the tiny-binary story. If dependencies land in Phase 2,
/// this can be revisited.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DecodeError {
    /// The response was shorter than the minimum for its mode.
    TooShort { got: usize, min: usize },
    /// The service/response byte did not match the expected positive-response code.
    WrongService { expected: u8, got: u8 },
    /// The payload length was not valid for the record structure (e.g. Mode 06
    /// records must be a multiple of 9 bytes).
    BadPayloadLength { len: usize, expected_multiple: usize },
    /// A field was out of its permitted range.
    OutOfRange { field: &'static str, value: u32 },
}

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DecodeError::TooShort { got, min } => {
                write!(f, "response too short: got {got} bytes, need at least {min}")
            }
            DecodeError::WrongService { expected, got } => {
                write!(f, "wrong service byte: expected {expected:#04x}, got {got:#04x}")
            }
            DecodeError::BadPayloadLength { len, expected_multiple } => write!(
                f,
                "payload length {len} is not a multiple of {expected_multiple}"
            ),
            DecodeError::OutOfRange { field, value } => {
                write!(f, "{field} out of range: {value:#x}")
            }
        }
    }
}

impl std::error::Error for DecodeError {}

/// A single Mode 01 (current data) PID reading.
#[derive(Debug, Clone, PartialEq)]
pub struct PidValue {
    /// PID number (0x00-0xFF).
    pub pid: u8,
    /// Raw payload bytes exactly as received (before scaling).
    pub value_raw: Vec<u8>,
    /// Scaled numeric value, if a scaling is known for this PID.
    pub value: Option<f64>,
    /// Unit string (e.g. "rpm", "km/h", "°C"), if known.
    pub unit: Option<String>,
    /// Human-readable name, if known.
    pub name: Option<String>,
}

/// A single Mode 06 (on-board monitor test) result — one 9-byte CAN record.
#[derive(Debug, Clone, PartialEq)]
pub struct MonitorResult {
    /// Monitor ID: which system was tested.
    pub mid: u8,
    /// Test ID: which specific test within the monitor (selects the name).
    pub tid: u8,
    /// Unit And Scaling ID: selects scaling + unit. High bit set => manufacturer-defined.
    pub uasid: u8,
    /// Raw 16-bit test value (big-endian), before scaling.
    pub test_value_raw: u16,
    /// Raw 16-bit min limit.
    pub min_limit_raw: u16,
    /// Raw 16-bit max limit.
    pub max_limit_raw: u16,
    /// Scaled test value, if the UASID scaling is known.
    pub test_value: Option<f64>,
    /// Scaled min limit.
    pub min_limit: Option<f64>,
    /// Scaled max limit.
    pub max_limit: Option<f64>,
    /// Unit string, if known.
    pub unit: Option<String>,
    /// Human-readable test name, if known.
    pub name: Option<String>,
    /// True when the UASID high bit (0x80) is set — a manufacturer-defined test
    /// with no standard scaling. These are the rows this project keeps raw.
    pub is_manufacturer_defined: bool,
    /// Pass/fail, computed only when scaled limits are known and applicable.
    pub passed: Option<bool>,
}

impl MonitorResult {
    /// Build a raw result straight from the wire, deriving `is_manufacturer_defined`
    /// from the UASID. Scaling/naming/pass-fail are filled later from the decode
    /// table (kept `None` here so raw-only records are represented honestly).
    pub fn from_raw(
        mid: u8,
        tid: u8,
        uasid: u8,
        test_value_raw: u16,
        min_limit_raw: u16,
        max_limit_raw: u16,
    ) -> Self {
        MonitorResult {
            mid,
            tid,
            uasid,
            test_value_raw,
            min_limit_raw,
            max_limit_raw,
            test_value: None,
            min_limit: None,
            max_limit: None,
            unit: None,
            name: None,
            is_manufacturer_defined: uasid & 0x80 != 0,
            passed: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manufacturer_bit_reads_uasid_not_tid() {
        // TID high bit set but UASID standard => NOT manufacturer-defined.
        let r = MonitorResult::from_raw(0x01, 0x85, 0x0C, 100, 0, 200);
        assert!(!r.is_manufacturer_defined);

        // UASID high bit set => manufacturer-defined, regardless of TID.
        let r = MonitorResult::from_raw(0x01, 0x01, 0x85, 100, 0, 200);
        assert!(r.is_manufacturer_defined);
    }

    #[test]
    fn error_display_is_readable() {
        let e = DecodeError::WrongService { expected: 0x46, got: 0x41 };
        assert_eq!(e.to_string(), "wrong service byte: expected 0x46, got 0x41");
    }
}
