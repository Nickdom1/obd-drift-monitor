# OBD Drift Monitor

**Your car grades its own health; this project keeps the report cards.**

Modern vehicles continuously run self-diagnostics on dozens of emissions- and powertrain-critical
sensors. The results — real measured values with pass/fail limits — are right there on the OBD-II
port, but every scan tool only shows you a **snapshot of right now**. This project stores those
results as a **time series**, so a sensor slowly wandering toward its limits over weeks and months
is visible as a *trend*, long before it trips a fault code.

*(Drift here means **sensor drift** — the emissions/powertrain kind — not the motorsport kind.)*

> Existing tools answer **"how is the car doing right now?"**
> OBD Drift Monitor answers **"how has this sensor changed over the last six months?"**

## How it works

The self-diagnostic results live in OBD-II **Mode 06** ("on-board monitor test results"). Readings
are captured at the **CAN-bus level** (a WiCAN / SocketCAN interface on the OBD-II port) rather than
through a consumer ELM327 scan-tool abstraction — which is part of why Mode 06, flaky on many
ELM327 clones, is reachable at all. Frames are decoded, stored in Postgres, and rendered as
value-vs-limit margin over time in Grafana.

```
CAN frame  →  WiCAN Pro ──MQTT/TLS──▶  Telegraf  →  decoderd (Rust)  →  PostgreSQL 16  →  Grafana
```

Decode runs on the gateway as a small native Rust binary (`decoderd`) — the *same* binary the tests
drive, deployed as the pipeline's Telegraf `execd` processor. The full topology (self-hosted overlay network, backups,
CI runner, public read-only dashboard) lives in the
[architecture doc](docs/design/architecture.md). No cloud, no subscriptions, offline-capable.

The car is the testbed, not the topic: the deliverable is a small, reproducible, well-tested
telemetry stack — a flake-defined NixOS appliance, validated end to end by a multi-node VM test.

## What's different

Mode 06 *readout* is well-covered ground — Torque Pro, OBD Auto Doctor, OBD Fusion, and python-OBD
all show MID/TID/value/limits/pass-fail. But they are all **snapshot-only, with no history**, and
they leave manufacturer-specific rows raw and unscaled. This project's contribution:

1. **Stores monitors as a per-vehicle time series** → drift is visible before a fault trips
2. **Documents the decode table** → the `covered_by_offtheshelf` column marks exactly where
   off-the-shelf coverage ends and manufacturer-specific rows begin
3. **Runs offline as an appliance** → no cloud, no subscriptions, reproducible Nix build
4. **Is validated end to end** → a multi-node QEMU test replays recorded telemetry and asserts it
   all the way through to the dashboard API

Drift *statistics* (EWMA/CUSUM/baselines) are explicitly out of scope for now — the panels show
value-vs-limit margin over time and a human reads the trend. Statistics are a possible later
extension once months of data have accumulated.

## Status

Pre-hardware; the decode library is complete and tested.

- ✅ **Rust decode library** for Mode 01 / Mode 06 (`pkgs/decode-rs/`), shipped as a small
  `decoderd` binary — rewritten from Python to fix a Mode 06 framing bug (7-byte legacy vs correct
  9-byte CAN records) and fill a gap no maintained Rust crate covers
  ([ADR 0002](docs/adr/0002-rust-decode-rewrite.md))
- ✅ **Equivalence harness** — frozen golden vectors gated hermetically (`cargo test`) and against
  the deployed `decoderd` binary (`pytest`), cross-checked to the python-OBD oracle
- ✅ **Benchmark** — ~30 M frames/s, ≈720× the python-OBD baseline on the golden corpus
  ([benchmark](docs/design/benchmark.md)); correctness first, speed is the measured bonus
- ✅ **Standalone Nix package** — `nix build .#decoder` / `nix run .#decoder` plus an overlay, so the
  decoder is consumable on its own without the gateway config
- ✅ **Pipeline chosen** — Telegraf for MQTT→Postgres ([ADR 0001](docs/adr/0001-collector-choice.md))
- ✅ Decode-table skeleton (`pkgs/decode-rs/decode_table.csv`)

What's next (gateway appliance, VIN-scrubbed trip fixtures + oracle validation, the end-to-end VM
test) is tracked in the [architecture doc](docs/design/architecture.md).

## Quick start

```bash
# Enter the dev environment (Rust + Python 3.13 + pytest + ruff + can-utils)
nix develop

# Decode library: unit/regression tests + the frozen-vector golden gate
cd pkgs/decode-rs && cargo test

# Equivalence harness: drive the decoderd binary over the golden corpus
pytest harness/

# Everything, as CI runs it
nix flake check
```

If you don't use Nix, see [docs/NIX-SETUP.md](docs/NIX-SETUP.md) for setup notes.

## Documentation

- **[Architecture](docs/design/architecture.md)** — full design, component decisions, data model,
  hardware bill-of-materials, testing strategy, security posture, and risks
- **[ADRs](docs/adr/)** — decision records
- **[Nix setup](docs/NIX-SETUP.md)** — dev-shell and flake usage

## License

MIT — see [LICENSE](LICENSE)
