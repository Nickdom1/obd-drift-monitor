//! `decoderd` — the standalone decode binary.
//!
//! This same binary serves two roles: the target the Python equivalence harness
//! drives over a golden corpus, and the Telegraf `execd` processor in the
//! pipeline. Both speak JSON lines on stdin/stdout.
//!
//! # Wire format
//!
//! One JSON object per input line:
//! ```json
//! {"mode": "06", "hex": "4601010c0100000001f4"}
//! ```
//! `hex` is the full OBD response including the service byte. The binary emits one
//! JSON object per input line:
//! - mode 06 → `{"mode":"06","records":[<record>...]}`
//! - mode 01 → `{"mode":"01", ...pid fields}`
//! - on error → `{"error":"<message>"}`
//!
//! The wire DTOs live here (not in the `decode` library) so the library stays
//! dependency-free — the tiny-binary story. They mirror `decode::MonitorResult` /
//! `decode::PidValue` field-for-field.
//!
//! # execd note
//!
//! The schema above is the CLI / equivalence-harness form. Telegraf's `execd`
//! passes whole *metrics* (name/tags/fields/timestamp), not this bespoke request,
//! so the deployed path adds a `--telegraf` metric-JSON adapter over the same
//! `decode::*` core — built and verified at the Week 2 bench, not blind. Contract:
//! `docs/design/telegraf-execd.md`.

use std::io::{self, BufRead, Write};

use serde::{Deserialize, Serialize};

use decode::{parse_mode01, DecodeError, MonitorResult, PidValue};

/// A single request line.
#[derive(Debug, Deserialize)]
struct Request {
    mode: String,
    hex: String,
}

/// Mode 06 response envelope.
#[derive(Debug, Serialize)]
struct Mode06Response {
    mode: &'static str,
    records: Vec<MonitorDto>,
}

/// Wire form of a `MonitorResult` (field-for-field with `decode::MonitorResult`).
#[derive(Debug, Serialize)]
struct MonitorDto {
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

impl From<MonitorResult> for MonitorDto {
    fn from(r: MonitorResult) -> Self {
        MonitorDto {
            mid: r.mid,
            tid: r.tid,
            uasid: r.uasid,
            test_value_raw: r.test_value_raw,
            min_limit_raw: r.min_limit_raw,
            max_limit_raw: r.max_limit_raw,
            test_value: r.test_value,
            min_limit: r.min_limit,
            max_limit: r.max_limit,
            unit: r.unit,
            name: r.name,
            is_manufacturer_defined: r.is_manufacturer_defined,
            passed: r.passed,
        }
    }
}

/// Mode 01 response: envelope + the PID fields, flattened.
#[derive(Debug, Serialize)]
struct Mode01Response {
    mode: &'static str,
    pid: u8,
    value_raw: Vec<u8>,
    value: Option<f64>,
    unit: Option<String>,
    name: Option<String>,
}

impl Mode01Response {
    fn from_pid(p: PidValue) -> Self {
        Mode01Response {
            mode: "01",
            pid: p.pid,
            value_raw: p.value_raw,
            value: p.value,
            unit: p.unit,
            name: p.name,
        }
    }
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    error: String,
}

/// Decode a hex string into bytes, rejecting odd length / non-hex digits.
fn decode_hex(hex: &str) -> Result<Vec<u8>, String> {
    let hex = hex.trim();
    if !hex.len().is_multiple_of(2) {
        return Err(format!("hex string has odd length: {}", hex.len()));
    }
    (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).map_err(|e| format!("bad hex: {e}")))
        .collect()
}

/// Turn one request into a JSON response string.
fn handle(req: &Request) -> String {
    let bytes = match decode_hex(&req.hex) {
        Ok(b) => b,
        Err(e) => return to_json(&ErrorResponse { error: e }),
    };
    match req.mode.as_str() {
        "06" => match decode::decode_mode06(&bytes) {
            Ok(records) => to_json(&Mode06Response {
                mode: "06",
                records: records.into_iter().map(MonitorDto::from).collect(),
            }),
            Err(e) => decode_err(e),
        },
        "01" => match parse_mode01(&bytes) {
            Ok(p) => to_json(&Mode01Response::from_pid(p)),
            Err(e) => decode_err(e),
        },
        other => to_json(&ErrorResponse {
            error: format!("unknown mode: {other:?}"),
        }),
    }
}

fn decode_err(e: DecodeError) -> String {
    to_json(&ErrorResponse { error: e.to_string() })
}

fn to_json<T: Serialize>(v: &T) -> String {
    // Serializing our own owned DTOs to a String cannot fail in practice.
    serde_json::to_string(v).unwrap_or_else(|e| format!("{{\"error\":\"serialize: {e}\"}}"))
}

fn main() -> io::Result<()> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let response = match serde_json::from_str::<Request>(&line) {
            Ok(req) => handle(&req),
            Err(e) => to_json(&ErrorResponse {
                error: format!("bad request json: {e}"),
            }),
        };
        writeln!(out, "{response}")?;
    }
    Ok(())
}
