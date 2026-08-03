//! Frozen-vector equivalence gate (hermetic).
//!
//! Loads the committed golden corpus (`golden/mode06.json`) and asserts the
//! library decodes each frame to its frozen `expected`. This is the enforced
//! `nix flake check` equivalence gate — it needs no python-OBD (the vectors are
//! data, not code), so it stays GPL-clean and reproducible.
//!
//! Float fields are compared with a tolerance: the golden values are produced by
//! an independent oracle (python-OBD's `pint` arithmetic, via the dev-only regen
//! script) and are never bit-identical to our `f64` scaling.

use std::path::PathBuf;

use serde::Deserialize;

use decode::decode_mode06;

/// Relative tolerance is unnecessary here — J1979 scalings are small decimals, so
/// an absolute epsilon well below any real resolution is both safe and strict.
const EPS: f64 = 1e-9;

#[derive(Debug, Deserialize)]
struct GoldenFile {
    cases: Vec<Case>,
}

#[derive(Debug, Deserialize)]
struct Case {
    name: String,
    hex: String,
    expected: Expected,
}

#[derive(Debug, Deserialize)]
struct Expected {
    records: Vec<ExpectedRecord>,
}

#[derive(Debug, Deserialize)]
struct ExpectedRecord {
    mid: u8,
    tid: u8,
    uasid: u8,
    test_value_raw: u16,
    min_limit_raw: u16,
    max_limit_raw: u16,
    test_value: Option<f64>,
    min_limit: Option<f64>,
    max_limit: Option<f64>,
    unit: Option<String>,
    name: Option<String>,
    is_manufacturer_defined: bool,
    passed: Option<bool>,
}

fn golden_path() -> PathBuf {
    // CARGO_MANIFEST_DIR = crates/decode; the corpus lives at the workspace's golden/.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../golden/mode06.json")
}

fn decode_hex(hex: &str) -> Vec<u8> {
    let hex = hex.trim();
    assert!(hex.len().is_multiple_of(2), "odd-length hex: {hex}");
    (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).expect("valid hex"))
        .collect()
}

fn approx_eq(a: Option<f64>, b: Option<f64>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(x), Some(y)) => (x - y).abs() <= EPS,
        _ => false,
    }
}

#[test]
fn golden_vectors_match() {
    let raw = std::fs::read_to_string(golden_path()).expect("read golden/mode06.json");
    let file: GoldenFile = serde_json::from_str(&raw).expect("parse golden JSON");
    assert!(!file.cases.is_empty(), "golden corpus is empty");

    for case in &file.cases {
        let bytes = decode_hex(&case.hex);
        let got = decode_mode06(&bytes)
            .unwrap_or_else(|e| panic!("[{}] decode error: {e}", case.name));

        assert_eq!(
            got.len(),
            case.expected.records.len(),
            "[{}] record count",
            case.name
        );

        for (i, (g, e)) in got.iter().zip(&case.expected.records).enumerate() {
            let ctx = format!("[{}] record {i}", case.name);
            assert_eq!(g.mid, e.mid, "{ctx} mid");
            assert_eq!(g.tid, e.tid, "{ctx} tid");
            assert_eq!(g.uasid, e.uasid, "{ctx} uasid");
            assert_eq!(g.test_value_raw, e.test_value_raw, "{ctx} test_value_raw");
            assert_eq!(g.min_limit_raw, e.min_limit_raw, "{ctx} min_limit_raw");
            assert_eq!(g.max_limit_raw, e.max_limit_raw, "{ctx} max_limit_raw");
            assert!(approx_eq(g.test_value, e.test_value), "{ctx} test_value");
            assert!(approx_eq(g.min_limit, e.min_limit), "{ctx} min_limit");
            assert!(approx_eq(g.max_limit, e.max_limit), "{ctx} max_limit");
            assert_eq!(g.unit, e.unit, "{ctx} unit");
            assert_eq!(g.name, e.name, "{ctx} name");
            assert_eq!(
                g.is_manufacturer_defined, e.is_manufacturer_defined,
                "{ctx} is_manufacturer_defined"
            );
            assert_eq!(g.passed, e.passed, "{ctx} passed");
        }
    }
}
