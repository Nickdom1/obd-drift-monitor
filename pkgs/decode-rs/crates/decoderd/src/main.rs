//! `decoderd` — the standalone decode binary.
//!
//! This same binary serves two roles: the target the Python equivalence harness
//! drives over a golden corpus, and the Telegraf `execd` processor in the
//! pipeline. Both speak JSON lines on stdin/stdout.
//!
//! Phase 1 is a scaffold stub: it links the `decode` library and exits cleanly so
//! the workspace builds. The JSON-lines loop is implemented in Phase 5, once the
//! decoders (Phase 2) exist.

fn main() {
    // Smoke-exercise the real decode path so the binary links the library end to
    // end. The JSON-lines stdin/stdout loop (the actual execd processor) lands in
    // Phase 5, once serde is wired in.
    let sample = [0x46u8, 0x01, 0x01, 0x0C, 0x01, 0x00, 0x00, 0x00, 0x01, 0xF4];
    match decode::decode_mode06(&sample) {
        Ok(results) => eprintln!("decoderd: scaffold decoded {} record(s)", results.len()),
        Err(e) => eprintln!("decoderd: decode error: {e}"),
    }
}
