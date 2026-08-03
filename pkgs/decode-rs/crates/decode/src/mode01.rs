//! Mode 01 (current powertrain data) decoder.
//!
//! PID *identity* (name) comes from `automotive_diag`'s `DataPid` enum — the
//! canonical, maintained definition — which is how we dogfood the crate we also
//! contribute Mode 06 to. The *scaling* is standard J1979 arithmetic we apply
//! ourselves (the crate models identifiers, not value scaling).

use automotive_diag::obd2::DataPid;

use crate::types::{DecodeError, PidValue};

/// Positive-response service byte for Mode 01 (`0x40 + 0x01`).
pub const SERVICE_01_RESPONSE: u8 = 0x41;

/// Canonical name for a PID, via `automotive_diag::obd2::DataPid`.
fn pid_name(pid: u8) -> Option<String> {
    DataPid::from_repr(pid).map(|p| format!("{p:?}"))
}

/// Apply the standard J1979 scaling for the PIDs we care about. Returns the scaled
/// value and unit, or `None` for PIDs we don't scale (value stays raw).
fn scale(pid: u8, payload: &[u8]) -> Option<(f64, &'static str)> {
    let a = *payload.first()? as f64;
    match pid {
        0x05 => Some((a - 40.0, "°C")),                       // engine coolant temp
        0x0C => {
            let b = *payload.get(1)? as f64;
            Some(((a * 256.0 + b) / 4.0, "rpm")) // engine RPM
        }
        0x0D => Some((a, "km/h")),                            // vehicle speed
        0x0F => Some((a - 40.0, "°C")),                       // intake air temp
        0x10 => {
            let b = *payload.get(1)? as f64;
            Some(((a * 256.0 + b) / 100.0, "g/s")) // MAF air flow
        }
        0x11 => Some((a * 100.0 / 255.0, "%")),               // throttle position
        0x2F => Some((a * 100.0 / 255.0, "%")),               // fuel tank level
        0x46 => Some((a - 40.0, "°C")),                       // ambient air temp
        _ => None,
    }
}

/// Parse a Mode 01 response `[0x41, PID, <payload>...]` into a single [`PidValue`].
pub fn parse_mode01(data: &[u8]) -> Result<PidValue, DecodeError> {
    if data.len() < 2 {
        return Err(DecodeError::TooShort { got: data.len(), min: 2 });
    }
    if data[0] != SERVICE_01_RESPONSE {
        return Err(DecodeError::WrongService {
            expected: SERVICE_01_RESPONSE,
            got: data[0],
        });
    }
    let pid = data[1];
    let payload = &data[2..];
    let (value, unit) = match scale(pid, payload) {
        Some((v, u)) => (Some(v), Some(u.to_string())),
        None => (None, None),
    };
    Ok(PidValue {
        pid,
        value_raw: payload.to_vec(),
        value,
        unit,
        name: pid_name(pid),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engine_rpm_scaled_and_named() {
        // 0x1F40 = 8000; /4 = 2000 rpm.
        let r = parse_mode01(&[0x41, 0x0C, 0x1F, 0x40]).unwrap();
        assert_eq!(r.value, Some(2000.0));
        assert_eq!(r.unit.as_deref(), Some("rpm"));
        assert_eq!(r.name.as_deref(), Some("EngineSpeed")); // from automotive_diag
    }

    #[test]
    fn coolant_temp_offset() {
        let r = parse_mode01(&[0x41, 0x05, 0x82]).unwrap(); // 130 - 40 = 90
        assert_eq!(r.value, Some(90.0));
        assert_eq!(r.name.as_deref(), Some("EngineCoolantTemp"));
    }

    #[test]
    fn unknown_pid_kept_raw() {
        let r = parse_mode01(&[0x41, 0x99, 0x12, 0x34]).unwrap();
        assert_eq!(r.value, None);
        assert_eq!(r.value_raw, vec![0x12, 0x34]);
    }

    #[test]
    fn rejects_wrong_service() {
        assert!(matches!(
            parse_mode01(&[0x46, 0x0C]),
            Err(DecodeError::WrongService { .. })
        ));
    }
}
