# OBD Drift Monitor

**Your car grades its own health; this project keeps the report cards.**

*Drift* here means **sensor drift** — an emissions or powertrain sensor slowly wandering out
of its reference range over weeks and months — **not** the motorsport kind. Readings are
captured at the **CAN-bus level** (a WiCAN / SocketCAN interface wired to the OBD-II port),
so we work with raw frames rather than a consumer ELM327 scan-tool abstraction — which is
part of why Mode 06 (flaky on many ELM327 clones) is reachable at all.

Modern vehicles continuously run self-diagnostics on dozens of emissions-critical
sensors. These "Monitor Test Results" (OBD-II Mode 06) expose real values, min/max
limits, and pass/fail status — but existing scan tools only show snapshots. This project
stores monitor results as a **time series** in Postgres and renders value-vs-limit margin
over time, so drift is visible as a trend rather than caught only when a fault code
finally trips.

The car is the testbed, not the topic. The deliverable is a small, reproducible,
well-tested telemetry stack: a flake-defined NixOS appliance that takes CAN frames off a
2018 Honda Accord, decodes them, stores them, and dashboards them — validated end to end
by a multi-node VM test.

## Status: Week 1

**Current phase:** Pre-hardware reconnaissance and decode-library development.

- ✅ Architecture accepted (`docs/design/architecture.md`)
- ✅ ADR 0003 accepted — Telegraf for the MQTT→Postgres pipeline (`docs/adr/0003-collector-choice.md`)
- ✅ **Rust** decode library for Mode 01 / Mode 06 (`pkgs/decode-rs/`), shipped as a small
  `decoderd` binary — rewritten from Python to fix a Mode 06 framing bug (7-byte legacy vs correct
  9-byte CAN records) and fill a gap no maintained Rust crate covers
- ✅ Equivalence harness: frozen golden vectors gated hermetically (`cargo test`) and against the
  deployed `decoderd` binary (`pytest`), cross-checked to the python-OBD oracle
- ✅ Decode-table skeleton (`pkgs/decode-rs/decode_table.csv`)
- ⏳ Benchmark + Nix-packaged decoder + repo/hardware decoupling (Phases 4–7)
- ⏳ Hardware on order (CANable Pro, WiCAN Pro, OBDLink SX, ProDesk mini)
- ⏳ First VIN-scrubbed trip fixtures (arrive with the car work)

## Architecture (summary)

```
┌─ 2018 Accord ──────────┐
│  OBD-II (Mode 01/06)   │      home WiFi        ┌─ Gateway: ProDesk mini, NixOS ─────────┐
│  WiCAN Pro (ESP32-S3)  │ ──── MQTT/TLS ──────▶ │ mosquitto → telegraf → postgresql 16   │
│  · polls / bridges     │                       │                        │               │
│  · SD buffer offline   │                       │                    grafana ◀───────────┘
└────────────────────────┘                       │ gitlab-runner (KVM) · wal-g/rclone     │
                                                  └────────────────┬───────────────────────┘
                                                       overlay net (outbound only)
                                                  ┌────────────────┴───────────────┐
                                                  │ small VPS: overlay lighthouse,  │
                                                  │ nginx → public read-only Grafana│
                                                  └─────────────────────────────────┘
```

Decode runs on the gateway (not the ESP32) so it can be iterated without a firmware flash.
Telegraf consumes MQTT and decodes via `decoderd` — the same Rust binary the tests drive, run as
an `execd` processor — then writes to a hand-tuned PostgreSQL 16 (native range partitioning + BRIN
— **no Timescale**; the data volume doesn't warrant an extension). Grafana reads Postgres locally; the VPS stores no telemetry
and only reverse-proxies a read-only dashboard over the overlay network.

See [docs/design/architecture.md](docs/design/architecture.md) for the full design,
component-decision table, data model, testing strategy, and risks.

## What's different

Mode 06 *readout* is well-covered ground — Torque Pro, OBD Auto Doctor, OBD Fusion, and
python-OBD all show MID/TID/value/limits/pass-fail. But they are all **snapshot-only, with
no history**, and they leave manufacturer-specific rows raw and unscaled. This project's
contribution:

1. **Stores monitors as a per-vehicle time series** → drift is visible before a fault trips
2. **Documents the decode table** → the `covered_by_offtheshelf` column marks exactly where
   off-the-shelf coverage ends and manufacturer-specific rows begin
3. **Runs offline as an appliance** → no cloud, no subscriptions, reproducible Nix build
4. **Is validated end to end** → a multi-node QEMU test replays recorded telemetry and
   asserts it all the way through to the dashboard API

Drift *statistics* (EWMA/CUSUM/baselines) are explicitly out of MVP scope — the panels show
value-vs-limit margin over time and a human reads the trend. Statistics are a possible
later extension once months of data have accumulated.

## Repository structure

```
obd-drift-monitor/
├── docs/
│   ├── design/          # architecture.md — the technical anchor
│   └── adr/             # Architecture Decision Records (immutable once written)
├── pkgs/
│   └── decode-rs/       # pure Rust decode library (no I/O) + decoderd bin + golden vectors
│                        # + decode_table.csv; execd processor for Telegraf
├── harness/             # Python (harness only): equivalence gate + python-OBD oracle regen
├── fixtures/            # real OBD captures, VIN-scrubbed (populated once hardware lands)
├── flake.nix            # Nix devShell + Rust/Python checks + gateway config
├── CLAUDE.md            # agent context and conventions
└── LICENSE              # MIT
```

## Quick start

```bash
# Enter the dev environment (Rust + Python 3.13 + pytest + ruff + can-utils)
nix develop

# Decode library: unit/regression tests + the frozen-vector golden gate
cd pkgs/decode-rs && cargo test

# Equivalence harness: drive the decoderd binary over the golden corpus
pytest harness/

# Lint the harness
ruff check harness/

# Individual CI checks (the aggregate `nix flake check` stays red on the
# gateway placeholder until Phase 7 — gate on these meanwhile):
nix build .#checks.x86_64-linux.cargo-test
nix build .#checks.x86_64-linux.pytest
nix build .#checks.x86_64-linux.ruff-check
```

If you don't use Nix, see [docs/NIX-SETUP.md](docs/NIX-SETUP.md) for setup notes.

## Hardware (Week 1 bill of materials)

| Component | Purpose | ~Cost |
|-----------|---------|-------|
| WiCAN Pro | In-vehicle ESP32-S3 CAN→MQTT gateway | $90 |
| CANable Pro (isolated) | USB-to-CAN bench tool | $60 |
| OBDLink SX USB | Oracle — verify our decode against commercial firmware | $30 |
| HP EliteDesk/ProDesk 800 G4 Mini | Gateway appliance (used) | $110 |
| OBD2 1-to-2 splitter | Bench testing with oracle + CANable simultaneously | $12 |

**Total:** ~$300 + battery maintainer + high-endurance microSD

## Target vehicle

**2018 Honda Accord** (primary test platform). The architecture is vehicle-agnostic; the
decode table starts Accord-specific and expands as more vehicles are captured.

## Documentation

- **[Architecture](docs/design/architecture.md):** full design, component decisions, data
  model, testing strategy, security posture, and risks
- **[Nix setup](docs/NIX-SETUP.md):** dev-shell and flake usage
- **ADRs:** decision records in [docs/adr/](docs/adr/)

## License

MIT — see [LICENSE](LICENSE)
