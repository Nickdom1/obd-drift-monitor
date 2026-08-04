# Architecture

**Status:** accepted direction, pre-build

A flake-defined NixOS telemetry appliance: CAN frames come off a 2018 Honda Accord,
through an edge collector, into a tuned PostgreSQL and a Grafana dashboard, validated by
a multi-node VM integration test and a CI pipeline that builds, tests, and ships the
whole thing. The car is the testbed, not the topic — the deliverable is a small,
reproducible, well-tested telemetry stack.

This document is the technical anchor. Decisions with alternatives get an ADR in
`docs/adr/`.

---

## 1. Scope

**In scope (MVP):**
- A NixOS gateway appliance built from a flake: broker, pipeline, database, dashboards.
- A pure **Rust** decode library for OBD-II Mode 01 / Mode 06 (`pkgs/decode-rs/`), shipped as a
  small native binary (`decoderd`) reused by the pipeline's decode step (Telegraf `execd`) and
  proven correct by a Python equivalence harness against the python-OBD oracle. (The decoder was
  rewritten from Python to Rust to fix a Mode 06 framing bug and fill a real Rust-ecosystem gap —
  see [ADR 0002](../adr/0002-rust-decode-rewrite.md). Python is retained only as the harness.)
- A multi-node QEMU integration test: recorded telemetry replayed in, asserted through
  to the dashboard API.
- Storage of Mode 06 monitor results as a **time series** — the piece existing tools
  don't do (see §6).

**Out of scope (MVP):**
- Drift statistics (EWMA/CUSUM/binned baselines). Grafana panels show value-vs-limit
  margin over time; a human reads the trend. Statistics are a possible later extension.
- A community monitor-ID registry.
- Any hand-rolled ingest daemon. The pipeline is a configured stock collector; the only
  custom code is the decode library.
- Seeded physical faults. The integration test replays recorded and synthetic data.

---

## 2. Architecture

```
  ┌─ 2018 Accord ────────────┐
  │  OBD-II (Mode 01/06)     │
  │  WiCAN Pro (ESP32-S3)    │     home WiFi       ┌─ Gateway: ProDesk mini, NixOS ────────────┐
  │  · polls / bridges       │ ──── MQTT/TLS ────▶ │ mosquitto → telegraf      → postgresql 16 │
  │  · SD buffer offline     │                     │                   │           │          │
  └──────────────────────────┘                     │               grafana ◀───────┘          │
                                                    │ gitlab-runner (KVM) · OCI registry       │
                                                    │ wal-g + rclone timers ──▶ object storage  │
                                                    └───────────────┬──────────────────────────┘
                                                          overlay net (outbound only)
                                                    ┌───────────────┴────────────────┐
                                                    │ small VPS                      │
                                                    │ overlay lighthouse             │
                                                    │ nginx → public read-only       │
                                                    │        Grafana over overlay IP │
                                                    └────────────────────────────────┘
```

**Data flow:** the WiCAN polls Mode 01/06 on a schedule (or bridges raw responses) and
publishes to Mosquitto on the gateway. Telegraf (`services.telegraf`) consumes from the
broker (`mqtt_consumer`, QoS 1), runs decode as an in-pipeline processor backed by the
decode table, and writes rows via its native PostgreSQL output. Grafana reads Postgres
locally. The VPS stores no telemetry; it terminates TLS and reverse-proxies dashboard
traffic over the overlay network. Raw logs and WAL backups flow to object storage on
timers.

Decode runs on the gateway, not the ESP32 — it's iterated on frequently and shouldn't sit
behind a firmware-flash cycle.

### Component decisions

ADRs are a log, numbered as written — not pre-reserved. A decision that warrants a record but
hasn't been made/written yet is marked *planned*; it gets the next free number when it lands.

| Component | Choice | Rationale | ADR |
|---|---|---|---|
| Pipeline | Telegraf: `mqtt_consumer` in, decode via the `decoderd` `execd` processor, `outputs.postgresql` out | Configure an existing collector rather than hand-roll one; a native Rust binary makes `execd` the clear choice over Starlark (wire contract + deferred `--telegraf` adapter: [telegraf-execd.md](telegraf-execd.md)) | [0001](../adr/0001-collector-choice.md) |
| Decode library | Pure **Rust** (`decode-rs`), shipped as `decoderd`; python-OBD as oracle only | Fixes a Mode 06 framing bug, fills a Rust-ecosystem gap, native `execd` fit; proven by equivalence against a GPL-clean frozen oracle | [0002](../adr/0002-rust-decode-rewrite.md) |
| Edge collector | WiCAN Pro | ESP32-S3, CAN transceiver, <1 mA sleep, SD buffering, MQTT — an edge device with no firmware work on the critical path | planned |
| Gateway | Used HP ProDesk/EliteDesk mini (i5-8500T-class, 16 GB, NVMe) | x86_64 + KVM in one box: appliance, CI runner, and VM-test host | planned |
| Broker | Mosquitto (`services.mosquitto`) | Stock nixpkgs; TLS + auth declaratively | — |
| Database | PostgreSQL 16, native range partitioning, **no Timescale** | Hand-tuned partitions + BRIN + autovacuum/WAL settings; the data volume doesn't warrant an extension | planned |
| Dashboards | Grafana (`services.grafana`), datasources + dashboards provisioned from JSON in-repo | Dashboards-as-code | — |
| Overlay | Self-hosted overlay network (self-hosted CA, group firewall rules in Nix) | No third-party control plane; zero inbound ports at home | planned |
| CI | Hosted git project + self-hosted KVM `gitlab-runner` on the gateway | A self-hosted runner keeps VM tests in the pipeline without a heavy CI install | planned |
| Cloud archive | Object storage: rclone timer for raw logs, WAL-G for base backups + WAL | Lifecycle tiering; cost at this volume is negligible | — |
| Deploys | deploy-rs from CI (manual gate) | Config-as-code, push-button | — |

### Repo layout (target)

```
flake.nix                     # devShell, packages, nixosConfigurations, checks
hosts/gateway/                # the appliance
hosts/vps/                    # lighthouse + nginx
modules/{pipeline,telemetry-db,dashboards,overlay,...}/
pkgs/decode-rs/               # pure Rust decode library + decoderd bin (execd processor) + Nix pkg
harness/                      # Python equivalence + benchmark harness (oracle: python-OBD)
tests/e2e.nix                 # the multi-node VM test
tests/fixtures/               # recorded trips (small ones in-repo)
dashboards/*.json
docs/design/architecture.md   # this file
docs/adr/*.md
CLAUDE.md
```

### Hardware (bill of materials)

Target vehicle: **2018 Honda Accord** (the architecture is vehicle-agnostic; the decode table
starts Accord-specific and expands as more vehicles are captured).

| Component | Purpose | ~Cost |
|---|---|---|
| WiCAN Pro | In-vehicle ESP32-S3 CAN→MQTT gateway | $90 |
| CANable Pro (isolated) | USB-to-CAN bench tool | $60 |
| OBDLink SX USB | Oracle — verify decode against commercial ELM327 firmware | $30 |
| HP ProDesk/EliteDesk 800 G4 Mini | Gateway appliance (used) | $110 |
| OBD2 1-to-2 splitter | Bench testing with oracle + CANable simultaneously | $12 |

**Total:** ~$300, plus a battery maintainer (for key-on-engine-off polling) and a high-endurance
microSD (WiCAN offline buffer).

---

## 3. Data model and Postgres plan

Schema (v0):

- `frames(ts, source, mode, raw)` — the raw MQTT payload / ISO-TP response **as received,
  before decode fan-out**, stored for *every* frame regardless of decode success.
  Range-partitioned monthly on `ts`, BRIN index on `ts`. This is the decoder's audit trail:
  it lets a corrected decoder **re-decode history** instead of losing it. It is deliberately
  *not* the same as `samples.raw` (which is per already-decoded row) or `decode_log` (failures
  only) — those don't help when a decode *succeeds but is wrong*. We shipped exactly that class
  of bug once (the 7- vs 9-byte Mode 06 framing), so at v0 — a decoder that has never seen a
  real car — the archive is cheap insurance against having to discard a season of captures.
- `trips(trip_id, vin, started_at, ended_at, source)` — trip boundaries derived in SQL
  from timestamp gaps (a view/matview), keeping the pipeline stateless.
- `samples(ts, trip_id, mode, mid_or_pid, tid, value, unit, limit_lo, limit_hi, raw)` —
  one row per decoded monitor/PID reading, produced by re-reading `frames`. **Range-partitioned
  monthly on `ts`**, BRIN index on `ts`, btree on `(mid_or_pid, ts)`.
- `decode_log(...)` — decode failures with the `raw` hex retained, so the decode table
  can be improved retroactively.

Tuning that gets documented, not just applied: `shared_buffers` / `effective_cache_size`
for a 16 GB box, `wal_compression`, checkpoint spacing, per-table autovacuum for
append-only partitions, fillfactor, `pg_stat_statements` on from day one. Backups: WAL-G
base backup weekly + continuous WAL to object storage; a restore drill is part of the
exit criteria (a backup that's never been restored isn't a backup).

**Volume reality:** Mode 06 yields roughly one sample per monitor per trip; even with
Mode 01 snapshots this is kilobytes per trip. Partitioning and BRIN are how you'd build
it at scale, and the write-up says plainly that the data volume doesn't require them.

---

## 4. Testing strategy

**Unit/decode tests:** the decode library is exercised against recorded fixtures — every
MID observed in week 1 gets at least one golden-value test (`nix flake check`). Decode
throughput is tracked by a criterion benchmark against a python-OBD baseline — see
[benchmark.md](benchmark.md) (correctness first; speed is a measured secondary).

**End-to-end test (`tests/e2e.nix`)** — telemetry in, rendered dashboard out:

- **Nodes:** `device` (replays a recorded trip's MQTT publishes on schedule, with jitter),
  `gateway` (the real appliance config, minus hardware-specific modules).
- **Assertions, in order:** broker up and authenticated → Telegraf connects and consumes
  → expected row counts and specific decoded values land in Postgres → Grafana datasource
  health green → a Grafana API query over the dashboard's exact panel query returns the
  replayed series.
- **Failure scenarios:** broker restart mid-replay (no data loss); collector restart
  (QoS 1 + persistent session redelivers; duplicates absorbed by `ON CONFLICT` on natural
  keys); delayed replay burst (simulates SD backfill after an offline stretch; ordering
  and trip attribution survive).

The overlay pair (lighthouse + node handshake) gets its own small two-node test rather
than bloating the E2E.

---

## 5. Security posture

- Zero inbound ports at home: the gateway dials out to the lighthouse; WiCAN→broker is
  LAN-only with TLS + per-device credentials.
- The VPS exposes only 443 (nginx) and the overlay port; Grafana is reachable exclusively
  over the overlay; the public view is an anonymous read-only org.
- Overlay firewall groups (`infra`, `admin`) with rules expressed in Nix.
- sops-nix for every secret (MQTT creds, overlay keys, Grafana admin, storage tokens); no
  secret is ever committed unencrypted — `git log` is the audit.
- systemd hardening via overrides on the Telegraf unit (`DynamicUser`, `ProtectSystem`,
  `SystemCallFilter`, `IPAddressAllow/Deny`).

---

## 6. Risks, carried honestly

**Mode 06 data rate is thin.** Results update roughly once per trip when enable
conditions are met; code clears reset them and substitute values appear for ~2 drive
cycles. This is why the MVP claim is infrastructure — acquisition, transport, storage,
visualization, testing, shipping — not statistics. Trend panels over months of
accumulating data are the payoff that arrives on its own schedule. The **week-1 kill
gate** is load-bearing: if this Accord's Mode 06 coverage is sparse, the decode table
narrows to Mode 01 PIDs and nothing else in the architecture changes.

**WiCAN Mode 06 capability is unverified.** Its STN-based interpreter should accept raw
Mode 06 requests via custom polling; if it can't, the fallback is Mode 01 polling from the
WiCAN plus periodic Mode 06 capture sessions with the CANable, batch-imported. Resolved
in week 2, day one.

**Collector fit is assumed, not proven.** Telegraf covers both ends on paper; if the
decode-as-processor path fights back (Starlark limits, execd friction), the contained
fallback is a thin bridge script owning only decode — an ADR-documented retreat, not a
drift back to a daemon.

**One box, many jobs.** Gateway = appliance + CI runner. Acceptable at n=1 and disclosed
in the write-up; the flake separates the roles into modules so they *could* split across
hosts.

### Prior art (why Mode 06 as a time series is the differentiator)

Mode 06 *readout* is well-covered ground: Torque Pro, OBD Fusion, OBD Auto Doctor, OBDwiz
all show MID/TID/value/limits/pass-fail, and python-OBD has named monitor commands. But
all of them are **snapshot-only, with no history**, and they leave manufacturer-specific
rows raw/unscaled ("consult the service book"). No tool found stores Mode 06 as a
per-vehicle **time series**. That trending — plus, optionally, the proprietary rows — is
the unclaimed ground. The decode table carries a `covered_by_offtheshelf` column to mark
exactly that boundary.

---

## 7. Working method

- **Living design, accumulating ADRs.** This document is kept true as the build proceeds;
  decisions with alternatives are captured in `docs/adr/`, numbered as written, and immutable
  once published (pre-release, the set may still be renumbered to stay clean).
- **Cadence:** public repo, small commits, and a short tutorial-style post as each piece
  lands (the Mode 06 dump script, the pipeline config, the VM replay test).
