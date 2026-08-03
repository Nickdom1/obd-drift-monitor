//! Supported-PID / supported-MID bitmap decoders.
//!
//! Both Mode 01 (`0x41`) and Mode 06 (`0x46`) answer a "what do you support?"
//! query with a 4-byte big-endian bitmap: `[service, query_base, b0, b1, b2, b3]`.
//! Bit 0 (MSB of the 32-bit value) means `query_base + 1` is supported, bit 1 means
//! `query_base + 2`, and so on.

use crate::types::DecodeError;

fn parse_bitmap(data: &[u8], expected_service: u8) -> Result<Vec<u8>, DecodeError> {
    if data.len() != 6 {
        return Err(DecodeError::BadPayloadLength { len: data.len(), expected_multiple: 6 });
    }
    if data[0] != expected_service {
        return Err(DecodeError::WrongService { expected: expected_service, got: data[0] });
    }
    let base = data[1];
    let bitmap = u32::from_be_bytes([data[2], data[3], data[4], data[5]]);
    let mut supported = Vec::new();
    for bit in 0..32u8 {
        if bitmap & (1 << (31 - bit)) != 0 {
            supported.push(base + bit + 1);
        }
    }
    Ok(supported)
}

/// Decode a Mode 01 supported-PID bitmap response.
pub fn parse_supported_pids(data: &[u8]) -> Result<Vec<u8>, DecodeError> {
    parse_bitmap(data, super::mode01::SERVICE_01_RESPONSE)
}

/// Decode a Mode 06 supported-MID bitmap response.
pub fn parse_supported_mids(data: &[u8]) -> Result<Vec<u8>, DecodeError> {
    parse_bitmap(data, super::mode06::SERVICE_06_RESPONSE)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_three_mids_supported() {
        // 0xE0 = 1110_0000 => MIDs base+1, base+2, base+3.
        let r = parse_supported_mids(&[0x46, 0x00, 0xE0, 0x00, 0x00, 0x00]).unwrap();
        assert_eq!(r, vec![1, 2, 3]);
    }

    #[test]
    fn pid_bitmap_with_base_offset() {
        // Query base 0x20 => results offset by 0x20.
        let r = parse_supported_pids(&[0x41, 0x20, 0x80, 0x00, 0x00, 0x01]).unwrap();
        assert_eq!(r, vec![0x21, 0x40]);
    }

    #[test]
    fn rejects_bad_length_and_service() {
        assert!(matches!(
            parse_supported_mids(&[0x46, 0x00, 0xFF]),
            Err(DecodeError::BadPayloadLength { .. })
        ));
        assert!(matches!(
            parse_supported_pids(&[0x46, 0x00, 0, 0, 0, 0]),
            Err(DecodeError::WrongService { .. })
        ));
    }
}
