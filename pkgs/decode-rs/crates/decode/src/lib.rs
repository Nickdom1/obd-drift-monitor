//! Pure OBD-II decode library.
//!
//! Bytes in, structured data out — no sockets, files, or databases. Two consumers
//! use this crate: the `decoderd` binary (which is both the equivalence-harness
//! target and the Telegraf `execd` processor) and the criterion benchmark.
//!
//! Layout:
//! - [`types`]  — shared `MonitorResult` / `PidValue` / `DecodeError`.
//! - [`mode06`] — the corrected 9-byte Mode 06 framing (upstream `service06` shape).
//! - [`mode01`] — Mode 01 PIDs, named via `automotive_diag::obd2::DataPid`.
//! - [`bitmap`] — supported-PID / supported-MID bitmaps.
//! - [`table`]  — standard J1979 UAS scaling applied to Mode 06 results.

pub mod bitmap;
pub mod mode01;
pub mod mode06;
pub mod table;
pub mod types;

pub use bitmap::{parse_supported_mids, parse_supported_pids};
pub use mode01::parse_mode01;
pub use mode06::parse_mode06;
pub use table::apply_scaling;
pub use types::{DecodeError, MonitorResult, PidValue};

/// Convenience: parse a Mode 06 response and apply standard scaling in one step.
/// Manufacturer/unknown UASIDs remain raw.
pub fn decode_mode06(data: &[u8]) -> Result<Vec<MonitorResult>, DecodeError> {
    let mut results = parse_mode06(data)?;
    for r in &mut results {
        apply_scaling(r);
    }
    Ok(results)
}
