//! Mode 06 (on-board monitoring test results) decoder — ISO 15765-4 CAN.
//!
//! # The framing fix
//!
//! This is the corrected implementation. The old Python parser read a single MID
//! from the response *header* and then sliced repeating **7-byte** `TID + value +
//! min + max` records with TID and UASID folded into one byte. That is wrong on
//! both counts. Verified against the python-OBD oracle (`obd/decoders.py`
//! `parse_monitor_test`) and SAE J1979, the correct CAN layout is a sequence of
//! **9-byte** records, each carrying its own MID:
//!
//! ```text
//! [0x46] [ MID · TID · UASID · value(2) · min(2) · max(2) ] [ MID · TID · ... ] ...
//!         └──────────────── one 9-byte record, big-endian ───────────────┘
//! ```
//!
//! Only the service byte (`0x46`) is a header; everything after it is 9-byte
//! records. A single response can therefore carry multiple MIDs.
//!
//! # Upstream shape
//!
//! `automotive_diag` has no Mode 06 / service06 module. This raw framing decoder is
//! deliberately kept free of our proprietary scaling table so it can be contributed
//! upstream as a `service06` module; scaling/naming live in [`crate::table`].

use crate::types::{DecodeError, MonitorResult};

/// Positive-response service byte for Mode 06 (`0x40 + 0x06`).
pub const SERVICE_06_RESPONSE: u8 = 0x46;

/// One monitor test result is exactly 9 bytes on CAN.
pub const RECORD_LEN: usize = 9;

/// Query MIDs whose response is a supported-MID bitmap, not test records.
/// Real monitors never use these values as a MID, so seeing one as the first
/// record byte unambiguously marks a bitmap response.
const BITMAP_QUERY_MIDS: [u8; 8] = [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0];

/// Parse a Mode 06 monitor-results response into raw [`MonitorResult`]s.
///
/// Scaling, units, names, and pass/fail are left unset (`None`) here; apply
/// [`crate::table::apply_scaling`] afterwards to fill them from the decode table.
///
/// A supported-MID *bitmap* response (`[0x46, <query_mid>, <4-byte bitmap>]`)
/// returns an empty vec — use [`crate::bitmap::parse_supported_mids`] to decode it.
pub fn parse_mode06(data: &[u8]) -> Result<Vec<MonitorResult>, DecodeError> {
    if data.len() < 2 {
        return Err(DecodeError::TooShort { got: data.len(), min: 2 });
    }
    if data[0] != SERVICE_06_RESPONSE {
        return Err(DecodeError::WrongService {
            expected: SERVICE_06_RESPONSE,
            got: data[0],
        });
    }

    // Strip only the mode byte. Everything after it is 9-byte records; the MID is
    // the first byte of each record (not a shared header).
    let records = &data[1..];

    // Supported-MID bitmap response: query MID followed by a 4-byte bitmap.
    if records.len() == 5 && BITMAP_QUERY_MIDS.contains(&records[0]) {
        return Ok(Vec::new());
    }

    if !records.len().is_multiple_of(RECORD_LEN) {
        return Err(DecodeError::BadPayloadLength {
            len: records.len(),
            expected_multiple: RECORD_LEN,
        });
    }

    let mut out = Vec::with_capacity(records.len() / RECORD_LEN);
    for chunk in records.chunks_exact(RECORD_LEN) {
        let mid = chunk[0];
        let tid = chunk[1];
        let uasid = chunk[2];
        let test_value_raw = u16::from_be_bytes([chunk[3], chunk[4]]);
        let min_limit_raw = u16::from_be_bytes([chunk[5], chunk[6]]);
        let max_limit_raw = u16::from_be_bytes([chunk[7], chunk[8]]);
        out.push(MonitorResult::from_raw(
            mid,
            tid,
            uasid,
            test_value_raw,
            min_limit_raw,
            max_limit_raw,
        ));
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a 9-byte record for test fixtures.
    fn record(mid: u8, tid: u8, uasid: u8, val: u16, min: u16, max: u16) -> Vec<u8> {
        let mut v = vec![mid, tid, uasid];
        v.extend_from_slice(&val.to_be_bytes());
        v.extend_from_slice(&min.to_be_bytes());
        v.extend_from_slice(&max.to_be_bytes());
        v
    }

    #[test]
    fn single_record_9_byte_framing() {
        // MID 0x01, TID 0x01, UASID 0x0C (0.01 V), value 256, min 0, max 500.
        let mut data = vec![SERVICE_06_RESPONSE];
        data.extend(record(0x01, 0x01, 0x0C, 256, 0, 500));
        let r = parse_mode06(&data).unwrap();
        assert_eq!(r.len(), 1);
        assert_eq!(r[0].mid, 0x01);
        assert_eq!(r[0].tid, 0x01);
        assert_eq!(r[0].uasid, 0x0C);
        assert_eq!(r[0].test_value_raw, 256);
        assert_eq!(r[0].max_limit_raw, 500);
        assert!(!r[0].is_manufacturer_defined);
    }

    #[test]
    fn regression_multi_mid_and_manufacturer_uasid() {
        // Two records with DIFFERENT MIDs in one response — impossible to represent
        // under the old header-MID + 7-byte framing, and the core reason for the
        // rewrite. Second record has a manufacturer UASID (high bit set).
        let mut data = vec![SERVICE_06_RESPONSE];
        data.extend(record(0x01, 0x01, 0x0C, 100, 0, 200));
        data.extend(record(0x21, 0x85, 0x85, 300, 0, 400));
        let r = parse_mode06(&data).unwrap();
        assert_eq!(r.len(), 2);
        assert_eq!(r[0].mid, 0x01);
        assert_eq!(r[1].mid, 0x21, "second record must carry its own MID");
        assert_eq!(r[1].uasid, 0x85);
        assert!(r[1].is_manufacturer_defined, "UASID 0x85 => manufacturer-defined");
        // Old parser would have mis-framed these 18 bytes as ~2.57 seven-byte records.
    }

    #[test]
    fn supported_mid_bitmap_returns_empty() {
        // [0x46, 0x00, <4-byte bitmap>] is a supported-MID bitmap, not results.
        let data = vec![SERVICE_06_RESPONSE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF];
        assert!(parse_mode06(&data).unwrap().is_empty());
    }

    #[test]
    fn rejects_wrong_service_and_bad_length() {
        assert!(matches!(
            parse_mode06(&[0x41, 0x01]),
            Err(DecodeError::WrongService { .. })
        ));
        // 10 bytes after service is not a multiple of 9.
        let mut data = vec![SERVICE_06_RESPONSE];
        data.extend(std::iter::repeat_n(0u8, 10));
        assert!(matches!(
            parse_mode06(&data),
            Err(DecodeError::BadPayloadLength { .. })
        ));
    }
}
