//! Criterion benchmark: Mode 06 decode throughput over the frozen golden corpus.
//!
//! Measures the pure decode path — [`decode::decode_mode06`] (framing + standard
//! J1979 scaling) — with no I/O in the timed loop. The corpus (frames + expected
//! outputs) is the same committed data the equivalence gate uses
//! (`tests/golden.rs`), so the benchmark and the correctness test exercise an
//! identical set of inputs.
//!
//! Reported as `Throughput::Elements(n_frames)` → criterion prints frames/sec, the
//! honest secondary metric behind "correctness first". The python-OBD baseline for
//! the same corpus is captured separately by `harness/bench_baseline.py`.
//!
//! Run: `cargo bench` (dev shell). Bench targets are not built by `cargo test`, so
//! the `cargo-test` Nix check stays lean and criterion never compiles there.

use std::hint::black_box;
use std::path::PathBuf;

use criterion::{criterion_group, criterion_main, Criterion, Throughput};
use serde::Deserialize;

use decode::decode_mode06;

#[derive(Deserialize)]
struct GoldenFile {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    hex: String,
}

/// Load the corpus and pre-decode every frame's hex to bytes — done once, outside
/// the measured loop, so the benchmark times only decode work.
fn corpus_frames() -> Vec<Vec<u8>> {
    // CARGO_MANIFEST_DIR = crates/decode; the corpus lives at the workspace's golden/.
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../golden/mode06.json");
    let raw = std::fs::read_to_string(&path).expect("read golden/mode06.json");
    let file: GoldenFile = serde_json::from_str(&raw).expect("parse golden JSON");
    file.cases.iter().map(|c| hex_to_bytes(&c.hex)).collect()
}

fn hex_to_bytes(hex: &str) -> Vec<u8> {
    let hex = hex.trim();
    (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).expect("valid hex"))
        .collect()
}

fn bench_mode06(c: &mut Criterion) {
    let frames = corpus_frames();

    let mut group = c.benchmark_group("mode06");
    // One "element" = one decoded Mode 06 response frame, so criterion reports
    // frames/sec across the whole corpus per iteration.
    group.throughput(Throughput::Elements(frames.len() as u64));
    group.bench_function("decode_corpus", |b| {
        b.iter(|| {
            for frame in &frames {
                let records = decode_mode06(black_box(frame)).expect("golden frames decode");
                black_box(records);
            }
        });
    });
    group.finish();
}

criterion_group!(benches, bench_mode06);
criterion_main!(benches);
