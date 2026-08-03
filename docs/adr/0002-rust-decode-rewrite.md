# ADR 0002: Rewrite the Decode Library in Rust (python-OBD as Oracle Only)

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** Nick
**Context:** Week 1, pre-hardware reconnaissance

## Context

The project needs a decode library that turns raw OBD-II responses (Mode 06 monitor-test results,
Mode 01 current data, supported-PID/MID bitmaps) into structured readings for the time-series
pipeline. The philosophy is fixed regardless of language: **pure functions, no I/O** — bytes in,
structured data out; no sockets, files, or database in the decode unit.

An initial Python parser existed. Two findings during week-1 reconnaissance forced a language
decision rather than a straight continuation:

1. **The existing Python `parse_mode06` had a real framing bug.** It read a single Monitor ID
   (MID) from the response *header*, then sliced repeating **7-byte** `TID + value + min + max`
   records with the Test ID (TID) and Unit-And-Scaling ID (UASID) folded into one byte. Reading
   [python-OBD](https://github.com/brendan-w/python-OBD)'s `obd/decoders.py` (`parse_monitor_test`)
   against the SAE J1979 CAN layout showed the correct structure is a sequence of **9-byte**
   records — `MID · TID · UASID · value(2) · min(2) · max(2)`, big-endian, **MID repeated per
   record** — so one response can carry multiple MIDs. The old parser was wrong on both framing
   width and field structure; a rewrite is the fix, not an add-on.
2. **No maintained Rust crate decodes Mode 06.** A survey of crates.io / lib.rs / GitHub
   (`automotive_diag`, `ecu_diagnostics`, `obd2`, `obd`) found Mode 01 and service 09 coverage
   but **no Mode 06 / monitor-test decoder** anywhere. This is a genuine ecosystem gap.

Decode is low-level wire work — byte framing, big-endian fields, bitmaps, and ISO-TP reassembly
later. It is also the correctness- and performance-critical unit: it runs in the Telegraf `execd`
hot path (see [ADR 0001](0001-collector-choice.md)) on a low-power always-on appliance.

## Decision

**The shipped decoder is Rust** (`pkgs/decode-rs/`). Adopt the maintained
[`automotive_diag`](https://crates.io/crates/automotive_diag) crate (MIT/Apache) for the canonical
Mode 01 `DataPid` and standards enums, and build Mode 06 ourselves in a `service06`-shaped module
so it can be contributed upstream (the crate has no monitor module today).

**python-OBD is reference / oracle material only** — never shipped, forked as a dependency, or
imported into any shipped artifact or CI gate. Correctness is proven by **equivalence** against it,
not by "our own tests pass" (see *Oracle & equivalence strategy* below). There is no shipped Python
decoder; Python survives only as the equivalence/benchmark harness.

## Rationale

### Right tool for the wire-level job
- Zero-copy slicing, exact integer widths, and no interpreter overhead fit byte framing / bitmaps
  / (future) ISO-TP reassembly far better than Python.
- Memory safety over C/C++ for the same low-level niche.
- The output is a tiny, dependency-free native binary — the ideal Telegraf `execd` processor: no
  `pint`/`pyserial`, no interpreter, fast startup, small Nix closure. This also settles the
  Starlark-vs-execd question in [ADR 0001](0001-collector-choice.md): with a native binary, execd
  is unambiguously right.

### Correctness is provable and the fix is the point
- The rewrite *is* the bug fix. `MonitorResult` carries a **separate `uasid`** field, so
  manufacturer-defined monitors are identified by `uasid & 0x80` (not `tid & 0x80`), and
  scaling/naming key off the correct bytes. A regression test encodes a multi-MID / manufacturer
  response that the old 7-byte parser structurally cannot represent.

### Ecosystem contribution
- Building Mode 06 against `automotive_diag`'s conventions makes an upstream `service06` PR a real
  deliverable — a live Rust crate, unlike the dormant experimental Mode 06 in python-OBD. That is
  both the differentiator and a clean contribution story.

### Dependency discipline
- `automotive_diag` is pinned exact (`=0.1.28`), built with minimal features (`obd2` only, so the
  sole runtime dependency is `strum`), and **wrapped behind our own types** so any pre-1.0 churn
  is contained to a thin adapter layer. The `crates/decode/` library itself stays otherwise
  dependency-free to protect the tiny-binary story.

## Oracle & equivalence strategy

python-OBD is the independent oracle that makes "we fixed the framing bug" a *defensible* claim
rather than a self-consistent one. Its use is constrained by two facts:

- **License.** python-OBD is **GPL-2.0** (confirmed from its repository `LICENSE` file — it is
  sometimes mislabeled MIT in secondary sources). This repository is MIT, so shipping,
  forking-to-depend, or linking it would pull copyleft in.
- **Fit.** Its real value is an ELM327 serial layer our transport (WiCAN → MQTT / SocketCAN) does
  not use, and its Mode 06 decoder is self-described experimental, never validated on a vehicle.

So the oracle is **hybrid**, keeping the GPL code out of every shipped artifact and CI gate:

- **Frozen golden vectors** (`pkgs/decode-rs/golden/mode06.json`) are the enforced `nix flake
  check` equivalence gate. They are committed **data (facts)**, not python-OBD code — facts derived
  from an oracle are not a derivative work — so the gate stays GPL-clean, hermetic, reproducible.
  `crates/decode/tests/golden.rs` checks the library; `harness/test_equivalence.py` drives the
  deployed `decoderd` binary over the same corpus, both with no `import obd`.
- A **dev-only** script (`harness/regen_golden.py`, run in `nix develop .#regen`) imports python-OBD
  to regenerate and cross-check the standard-UASID vectors against the live oracle. The GPL
  dependency lives **exclusively** in that shell.

**Documented divergences are findings, not failures.** python-OBD silently drops any monitor whose
UASID is not in its standard `UAS_IDS` table — exactly the manufacturer/proprietary rows this
project keeps raw as its differentiator — and has no `0xFFFF` "not applicable" sentinel handling.
Equivalence is therefore scoped to the standard-UASID subset; those rows are expected, separately
asserted divergences (and candidate upstream fixes).

## Alternatives Considered

### Keep the Python parser (fix in place)
**Rejected.** It would fix the framing bug but forfeit the native-binary/execd fit, the
performance headroom, and the ecosystem-contribution angle — and it keeps interpreted code on the
appliance hot path. The bug made "continue as-is" untenable regardless.

### Go
**Acceptable but not chosen.** Fine for a small binary, but Rust wins on wire-level precision
(exact widths, zero-copy) and on the upstream-contribution target (`automotive_diag` is Rust).

### Elixir / BEAM
**Rejected for this unit.** BEAM is for the concurrent/distributed layer, not byte-crunching — the
fast decode path would end up a Rust NIF anyway, so start with Rust.

### Zero-dependency Rust (no `automotive_diag`)
**Rejected (kept as fallback).** A gated fit-spike confirmed `automotive_diag` models Mode 01
ergonomically and that a `service06` module slots into its conventions. A pure-definitions
dependency barely dents the binary size while enabling the upstream PR. Fall back to zero-dep only
if future churn proves costly.

### Ship / fork / depend on python-OBD
**Rejected.** GPL-2.0 into an MIT repo; wrong transport (ELM327); experimental, unvalidated Mode 06;
and forking inherits the exact class of framing bug we set out to fix. A clean-room Rust
implementation checked against python-OBD as an oracle is stronger on every axis.

## Consequences

### Positive
- Correct 9-byte Mode 06 framing, provably equivalent to an independent oracle over golden vectors.
- Project stays cleanly MIT; no copyleft in any shipped artifact or check.
- Small native `decoderd` binary that doubles as the equivalence-harness target **and** the
  Telegraf `execd` processor — tests exercise the exact deployed artifact.
- A concrete upstream contribution path (`service06` in `automotive_diag`).
- Measured throughput far above the interpreted baseline (see `docs/design/benchmark.md`) — a
  secondary benefit behind correctness.

### Negative
- Rust build tooling in the flake (toolchain, `buildRustPackage`) — heavier than a pure-Python
  package, mitigated by Nix pinning.
- `automotive_diag` is pre-1.0 (`0.1.x`) → churn risk, mitigated by the exact pin + wrapper types.
- Required a nixpkgs bump (24.05 → nixos-26.05) for the toolchain MSRV (rustc 1.84+).
- python-OBD is not in nixpkgs, so the `.#regen` shell packages it from PyPI (`fetchPypi` +
  `pythonRelaxDeps`); a small maintenance surface, isolated to the dev-only shell.
- Golden vectors must be regenerated (and divergences re-triaged) if the oracle or our
  understanding changes — an intentional, reviewed step, never a silent update.

## References

- python-OBD: [https://github.com/brendan-w/python-OBD](https://github.com/brendan-w/python-OBD)
  (GPL-2.0) — `obd/decoders.py` `monitor` / `parse_monitor_test`, `obd/UnitsAndScaling.py`.
- `automotive_diag`: [https://crates.io/crates/automotive_diag](https://crates.io/crates/automotive_diag)
- SAE J1979 (Mode 06 CAN record layout); ISO 15765-4 (ISO-TP).
- Corpus + harness: `pkgs/decode-rs/golden/mode06.json`, `harness/test_equivalence.py`,
  `harness/regen_golden.py`, `harness/bench_baseline.py`.
- Benchmark: `docs/design/benchmark.md`. Related: [ADR 0001](0001-collector-choice.md).

## Validation

`cargo test` (unit + the multi-MID/manufacturer regression) and the frozen-vector equivalence gate
are green in `nix flake check`; `harness/regen_golden.py` reproduces the committed standard-UASID
vectors against live python-OBD in the `.#regen` shell. Post-hardware (day 3+), real VIN-scrubbed
fixtures and the OBDLink SX / off-the-shelf oracles validate Mode 06 scaling against real vehicle
data.
