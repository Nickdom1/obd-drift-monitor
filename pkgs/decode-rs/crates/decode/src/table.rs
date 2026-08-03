//! Decode table: UASID → scaling/units, plus application to [`MonitorResult`]s.
//!
//! Scaling is keyed by the **UASID** (Unit And Scaling ID), per SAE J1979 —
//! independent of which monitor/test produced the value. The values below are the
//! standardized J1979 UAS definitions (`source = J1979-summary`); they are numeric
//! facts, independently transcribed and cross-checked by the equivalence harness
//! against the python-OBD oracle (never copied as GPL expression).
//!
//! Manufacturer-defined UASIDs (high bit `0x80` set) are intentionally *not* in
//! this table: they have no standard scaling, so their records stay raw — which is
//! exactly the proprietary-monitor data this project keeps and the off-the-shelf
//! tools drop.

use crate::types::MonitorResult;

/// A standardized unit-and-scaling definition: `value = raw * scale + offset`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Uas {
    pub scale: f64,
    pub offset: f64,
    pub unit: &'static str,
}

const fn uas(scale: f64, offset: f64, unit: &'static str) -> Uas {
    Uas { scale, offset, unit }
}

/// Look up the standard scaling for a UASID, or `None` for manufacturer-defined /
/// unknown IDs (which are kept raw).
pub fn lookup_uas(uasid: u8) -> Option<Uas> {
    // Standard J1979 UAS IDs (0x01..=0x31 covered here; extends as fixtures need).
    let u = match uasid {
        0x01 => uas(1.0, 0.0, "count"),
        0x02 => uas(0.1, 0.0, "count"),
        0x03 => uas(0.01, 0.0, "count"),
        0x04 => uas(0.001, 0.0, "count"),
        0x05 => uas(0.000_030_5, 0.0, "count"),
        0x06 => uas(0.000_305, 0.0, "count"),
        0x07 => uas(0.25, 0.0, "rpm"),
        0x08 => uas(0.01, 0.0, "km/h"),
        0x09 => uas(1.0, 0.0, "km/h"),
        0x0A => uas(0.122, 0.0, "mV"),
        0x0B => uas(0.001, 0.0, "V"),
        0x0C => uas(0.01, 0.0, "V"),
        0x0D => uas(0.003_906_25, 0.0, "mA"),
        0x0E => uas(0.001, 0.0, "A"),
        0x0F => uas(0.01, 0.0, "A"),
        0x10 => uas(1.0, 0.0, "ms"),
        0x11 => uas(100.0, 0.0, "ms"),
        0x12 => uas(1.0, 0.0, "s"),
        0x13 => uas(1.0, 0.0, "mOhm"),
        0x14 => uas(1.0, 0.0, "Ohm"),
        0x15 => uas(1.0, 0.0, "kOhm"),
        0x16 => uas(0.1, -40.0, "°C"),
        0x17 => uas(0.01, 0.0, "kPa"),
        0x18 => uas(0.0117, 0.0, "kPa"),
        0x19 => uas(0.079, 0.0, "kPa"),
        0x1A => uas(1.0, 0.0, "kPa"),
        0x1B => uas(10.0, 0.0, "kPa"),
        0x1C => uas(0.01, 0.0, "°"),
        0x1D => uas(0.5, 0.0, "°"),
        0x1E => uas(0.000_030_5, 0.0, "ratio"),
        0x1F => uas(0.05, 0.0, "ratio"),
        0x20 => uas(0.003_906_25, 0.0, "ratio"),
        0x21 => uas(1.0, 0.0, "mHz"),
        0x22 => uas(1.0, 0.0, "Hz"),
        0x23 => uas(1.0, 0.0, "kHz"),
        0x24 => uas(1.0, 0.0, "count"),
        0x25 => uas(1.0, 0.0, "km"),
        0x26 => uas(0.1, 0.0, "mV/ms"),
        0x27 => uas(0.01, 0.0, "g/s"),
        0x28 => uas(1.0, 0.0, "g/s"),
        0x29 => uas(0.25, 0.0, "Pa/s"),
        0x2A => uas(0.001, 0.0, "kg/h"),
        0x2B => uas(1.0, 0.0, "count"),
        0x2C => uas(0.01, 0.0, "g"),
        0x2D => uas(0.01, 0.0, "mg"),
        0x2F => uas(0.01, 0.0, "%"),
        0x30 => uas(0.001_526, 0.0, "%"),
        0x31 => uas(0.001, 0.0, "L"),
        _ => return None,
    };
    Some(u)
}

/// Fill scaled `test_value`/`min_limit`/`max_limit`, `unit`, and `passed` on a
/// result whose UASID has a standard scaling. Manufacturer/unknown UASIDs are left
/// raw (all scaled fields stay `None`).
///
/// Pass/fail is computed only when scaling is known and neither limit is the
/// `0xFFFF` "not applicable" sentinel — a deliberate refinement over python-OBD,
/// which has no sentinel handling (documented as an expected oracle divergence).
pub fn apply_scaling(result: &mut MonitorResult) {
    let Some(u) = lookup_uas(result.uasid) else {
        return;
    };
    let scale = |raw: u16| raw as f64 * u.scale + u.offset;
    result.test_value = Some(scale(result.test_value_raw));
    result.min_limit = Some(scale(result.min_limit_raw));
    result.max_limit = Some(scale(result.max_limit_raw));
    result.unit = Some(u.unit.to_string());

    const NOT_APPLICABLE: u16 = 0xFFFF;
    if result.min_limit_raw == NOT_APPLICABLE || result.max_limit_raw == NOT_APPLICABLE {
        result.passed = None;
    } else if let (Some(t), Some(lo), Some(hi)) =
        (result.test_value, result.min_limit, result.max_limit)
    {
        result.passed = Some(lo <= t && t <= hi);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scales_voltage_and_computes_pass() {
        // UASID 0x0C = 0.01 V/count. value 256 -> 2.56 V, within [0, 5.0].
        let mut r = MonitorResult::from_raw(0x01, 0x01, 0x0C, 256, 0, 500);
        apply_scaling(&mut r);
        assert_eq!(r.test_value, Some(2.56));
        assert_eq!(r.max_limit, Some(5.0));
        assert_eq!(r.unit.as_deref(), Some("V"));
        assert_eq!(r.passed, Some(true));
    }

    #[test]
    fn temperature_offset() {
        // UASID 0x16 = 0.1 °C, offset -40. raw 600 -> 20.0 °C.
        let mut r = MonitorResult::from_raw(0x01, 0x01, 0x16, 600, 0, 1000);
        apply_scaling(&mut r);
        assert_eq!(r.test_value, Some(20.0));
    }

    #[test]
    fn manufacturer_uasid_left_raw() {
        let mut r = MonitorResult::from_raw(0x01, 0x85, 0x85, 100, 0, 200);
        apply_scaling(&mut r);
        assert_eq!(r.test_value, None);
        assert_eq!(r.unit, None);
        assert_eq!(r.passed, None);
    }

    #[test]
    fn sentinel_limit_yields_none_pass() {
        let mut r = MonitorResult::from_raw(0x01, 0x01, 0x0C, 256, 0, 0xFFFF);
        apply_scaling(&mut r);
        assert!(r.test_value.is_some());
        assert_eq!(r.passed, None, "0xFFFF max is 'not applicable'");
    }
}
