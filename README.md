# OBD Drift Monitor

**Your car grades its own health; this project keeps the report cards.**

Modern vehicles continuously run self-diagnostics on dozens of emissions-critical
sensors. These "Monitor Test Results" (OBD-II Mode 06) expose real values, min/max
limits, and pass/fail status — but existing scan tools only show snapshots. This project
stores monitor results as a **time series** in Postgres and renders value-vs-limit margin
over time, so degradation is visible as a trend rather than caught only when a fault code
finally trips.

The car is the testbed, not the topic. The deliverable is a small, reproducible,
well-tested telemetry stack: a flake-defined NixOS appliance that takes CAN frames off a
2018 Honda Accord, decodes them, stores them, and dashboards them — validated end to end
by a multi-node VM test.

## Status: Week 1

**Current phase:** Pre-hardware reconnaissance and decode-library development.

- ✅ Architecture accepted (`docs/design/architecture.md`)
- ✅ Pure-Python decode library for Mode 01 / Mode 06 with golden tests (45 passing)
- ✅ Decode-table skeleton (`pkgs/decode/decode_table.csv`)
- 🚧 ADR 0003 (collector choice) — in progress
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
Telegraf consumes MQTT, decodes via the shared decode library, and writes to a hand-tuned
PostgreSQL 16 (native range partitioning + BRIN — **no Timescale**; the data volume
doesn't warrant an extension). Grafana reads Postgres locally; the VPS stores no telemetry
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
│   └── decode/          # pure Python decode library (no I/O) + decode_table.csv + tests
├── fixtures/            # real OBD captures, VIN-scrubbed (populated once hardware lands)
├── flake.nix            # Nix devShell + decode package + checks + gateway config
├── CLAUDE.md            # agent context and conventions
└── LICENSE              # MIT
```

## Quick start

```bash
# Enter the dev environment (Python 3.11 + pytest + ruff + can-utils)
nix develop

# Run the decode-library tests
pytest

# Lint
ruff check pkgs/

# Run everything the CI gate runs (tests + lints)
nix flake check
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
