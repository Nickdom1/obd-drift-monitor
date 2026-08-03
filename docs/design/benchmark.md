# Decode Benchmark — Rust vs python-OBD (Mode 06)

**Status:** living note. Numbers below are from the **synthetic golden corpus** on a
development laptop — a floor for "does the rewrite pay off," not a field measurement.
Real-fixture numbers land post-hardware (day 3+).

## Why this exists

The Rust rewrite's headline is **correctness first** — it fixes the 7-byte vs 9-byte Mode 06
framing bug (see [ADR 0002](../adr/0002-rust-decode-rewrite.md)). Throughput is the honest
*secondary* result: a native, dependency-free decoder in the Telegraf `execd` hot path should
also be dramatically faster than an interpreted one. This note records the measurement so the
write-up can quote it without overclaiming.

The baseline is **python-OBD's own `monitor()` decoder** — the same GPL-2.0 code we use as the
equivalence oracle. The old buggy 7-byte Python parser is deleted, so this is a
**correct-vs-correct** comparison (9-byte framing on both sides), not a strawman against known-
broken code.

## Method

- **Corpus:** the 7 frozen frames in
  [`pkgs/decode-rs/golden/mode06.json`](../../pkgs/decode-rs/golden/mode06.json) — the exact set
  the equivalence gate and the criterion bench share. Both benches decode the *identical* bytes.
- **Rust:** `cargo bench` (criterion 0.5), release profile (`opt-level=3`, LTO, strip). Bench:
  [`crates/decode/benches/decode.rs`](../../pkgs/decode-rs/crates/decode/benches/decode.rs) —
  times `decode::decode_mode06` (framing + standard J1979 scaling) over the whole corpus per
  iteration; hex→bytes conversion and corpus load are outside the timed loop.
- **python-OBD:** `harness/bench_baseline.py` (dev-only, `nix develop .#regen`) — times
  `obd.decoders.monitor()` over the same 7 frames with `timeit` (200 000 iterations).
- **Machine:** AMD Ryzen 3 4300U, rustc 1.95.0, Python 3.13.14, nixpkgs `nixos-26.05`.

**Scope caveat (favors python-OBD):** python-OBD's `monitor()` accepts every frame but
*internally drops* the rows this project keeps raw — manufacturer UASIDs (`uasid & 0x80`), the
`0xFFFF` "not applicable" sentinel — and truncates the supported-MID bitmap frame to empty. So
on 3 of the 7 frames it does *less* work than our decoder (which retains those rows). The
measured Rust lead is therefore a **conservative floor**.

## Results

| Decoder | Per corpus (7 frames) | Per frame | Throughput |
|---|---|---|---|
| Rust `decode_mode06` | **229.8 ns** | ~32.8 ns | **30.46 M frames/s** |
| python-OBD `monitor()` | 166.3 µs | ~23.76 µs | 0.0421 M frames/s |

**Rust is ≈ 720× faster** over this corpus (166.3 µs ÷ 229.8 ns ≈ 724×) — and that is the
conservative reading, since python-OBD skips work on the manufacturer/sentinel/bitmap frames.

## Honest framing for the write-up

- Lead with the **bug fix and the equivalence proof**; the speed is a bonus, not the pitch.
- The ~700× figure is a **microbenchmark on 7 synthetic frames** on one laptop. It reflects
  interpreter overhead + `pint` Quantity construction in python-OBD vs zero-alloc integer work in
  Rust — real, but not a claim about end-to-end pipeline latency (which is dominated by MQTT,
  ISO-TP, and Postgres, not decode).
- Re-run over real VIN-scrubbed fixtures once hardware is in hand; update this table then.

## Reproduce

```bash
nix develop            --command bash -c 'cd pkgs/decode-rs && cargo bench'
nix develop .#regen    --command python harness/bench_baseline.py
```
