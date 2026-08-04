# CLAUDE.md — Agent Context and Conventions

This file provides context for AI agents (Claude, Copilot, Cursor, etc.) working on the OBD Drift Monitor project.

## Project Overview

**One-liner:** Your car grades its own health; this project keeps the report cards.

**What it does:** Captures OBD-II Mode 06 monitor test results from a 2018 Honda Accord, stores them as time series in Postgres, and tracks drift over time to catch sensor degradation before fault codes appear.

**Current phase:** Week 1 — decode library complete; pre-hardware, laptop-only work continues (still
awaiting the CANable/car for real fixtures + the Mode 06 kill-gate decision).

> **Active work: Rust decode conversion — Phases 1–5 done.** The shipped decoder is **Rust**
> (`pkgs/decode-rs/`), fixing a real Mode 06 framing bug (7-byte legacy vs correct 9-byte CAN records).
> Python is retained **only** as the equivalence/benchmark harness and oracle (python-OBD). Full plan
> and phase status: `docs/private/rust-conversion-plan.md`.
> **Done:** scaffold + Mode 06/01 decoders + bitmaps + UAS table; nixpkgs bump to nixos-26.05; old
> buggy Python decoder deleted; two-tier equivalence gate (hermetic `crates/decode/tests/golden.rs`
> plus `decoderd` driven over `golden/mode06.json` by `harness/test_equivalence.py`, cross-checked to
> the dev-only python-OBD oracle via `harness/regen_golden.py` in `nix develop .#regen`); criterion
> benchmark (`docs/design/benchmark.md`); gateway eval fixed so aggregate `nix flake check` is green;
> ADRs collapsed to a clean 0001/0002; **Phase 5** standalone `packages.decoder` + `overlays.default`
> (`nix build/run .#decoder`), execd contract pinned in `docs/design/telegraf-execd.md`.
> **Next (decode):** the `decoderd --telegraf` metric-JSON adapter, built + verified at the Week 2
> Mosquitto→Telegraf→Postgres bench (not blind). **Biggest laptop-doable work left overall:** the
> `tests/e2e.nix` multi-node VM replay test (iteration-2 Week 3). **Car-blocked:** real VIN-scrubbed
> fixtures, oracle validation, `decode_table.csv` rows, and the **Mode 06 kill-gate decision**.

## Build and Test Commands

```bash
# Enter the development environment
nix develop

# Rust decode library (shipped decoder) — run from pkgs/decode-rs/
cargo test            # unit + regression tests
cargo clippy --all-targets
cargo bench           # criterion (Phase 4+)

# Python harness (equivalence + benchmark oracle) — Phase 3+
pytest harness/

# Lint / format Python (harness)
ruff check harness/
ruff format harness/

# Build / run the standalone decoder package (no gateway coupling; runs decoderd)
nix build .#decoder && ./result/bin/decoderd   # or: nix run .#decoder
# Consumers can instead add overlays.default (exposes pkgs.obd-decoder).

# Seed / verify golden vectors against the python-OBD oracle (GPL, dev-only shell)
nix develop .#regen --command python harness/regen_golden.py

# Aggregate check (now green — the gateway placeholder gained a nominal root
# fileSystems entry so it evaluates; full hardware decoupling is still Phase 7):
nix flake check

# Individual flake checks (still useful for targeting one gate):
nix build .#checks.x86_64-linux.cargo-test
nix build .#checks.x86_64-linux.pytest
nix build .#checks.x86_64-linux.ruff-check
```

## Repository Structure

```
obd-drift-monitor/
├── docs/
│   ├── design/          # Living design documents (agents update these per findings)
│   │   ├── architecture.md
│   │   └── telegraf-execd.md    # execd wire contract + deferred --telegraf adapter
│   ├── private/         # personal strategy/planning notes — gitignored, not published
│   └── adr/             # Architecture Decision Records (numbered as written, immutable once published)
│       ├── 0001-collector-choice.md       # Telegraf for MQTT→Postgres
│       └── 0002-rust-decode-rewrite.md    # Rust decoder + python-OBD oracle strategy
├── pkgs/
│   ├── decode-rs/       # SHIPPED decoder — Rust (pure lib, no I/O)
│   │   ├── crates/decode/    # lib: mode06.rs (9-byte fix), mode01.rs, bitmap.rs, table.rs, types.rs
│   │   │   └── tests/golden.rs   # hermetic frozen-vector equivalence gate
│   │   ├── crates/decoderd/  # thin bin: JSON-lines stdin->stdout (== Telegraf execd processor)
│   │   ├── golden/mode06.json    # frozen oracle vectors (committed data)
│   │   ├── decode_table.csv      # mid,tid → name + covered_by_offtheshelf boundary
│   │   ├── package.nix           # callPackage-able derivation (packages.decoder + overlay)
│   │   └── Cargo.toml / rust-toolchain.toml
│   └── gateway/         # NixOS configuration for the ProDesk appliance (week 2+)
├── harness/             # Python (harness ONLY): test_equivalence.py (CI), regen_golden.py (dev)
├── fixtures/            # Real OBD captures, VIN-scrubbed (populated day 3+)
├── flake.nix            # Nix devShell + Rust/Python checks + gateway build
├── CLAUDE.md            # This file
├── README.md            # Public-facing project pitch
└── LICENSE              # MIT
```

## Coding Conventions

### Python (harness ONLY — no shipped Python decoder)
- **Style:** PEP 8, enforced by `ruff`
- **Testing:** pytest; the harness lives in `harness/`
- **Type hints:** Encouraged but not required for week 1
- **Role:** Python survives only as the equivalence/benchmark harness. `test_equivalence.py` drives
  the `decoderd` binary over the frozen golden corpus (no `import obd`); `regen_golden.py` is the
  dev-only oracle path that imports python-OBD (GPL, `nix develop .#regen`) to seed/verify vectors.

### Rust (shipped decoder — `pkgs/decode-rs/`)
- **Philosophy:** pure functions, no I/O in `crates/decode/` (bytes → structured data).
- **Dependency:** `automotive_diag` (MIT/Apache) for canonical Mode 01 `DataPid`/standards enums,
  pinned `=0.1.28`, minimal features (obd2 only; runtime dep = `strum`), wrapped behind our own
  types to contain pre-1.0 churn. Mode 06 is built in a `service06`-shaped module for an upstream PR.
- **Testing:** `cargo test` unit + regression; equivalence via the Python harness + frozen golden vectors.

### Nix
- **Pinned inputs:** `nixpkgs` locked to **nixos-26.05** (rustc 1.95, Python 3.13) — bumped from the
  stale 24.05 pin during the Rust conversion.
- **Checks:** `flake.nix` defines checks that run on `nix flake check` — tests MUST pass before commits to main
- **Gateway config:** Lives in `nixosConfigurations.gateway` — flesh out when hardware arrives

### Git
- **Branch strategy:** Feature branches for non-trivial work, direct commits to main acceptable during week 1 solo recon
- **Commit messages:** Conventional Commits style preferred (`feat:`, `fix:`, `docs:`, `test:`)
- **Public from day 1:** No secrets, no VINs, no raw logs with identifying data

## Agent Workflow

### Design Documents Are Living
- `docs/design/architecture.md` is the **strategic anchor** — consult it before making architectural decisions
- Deeper strategy/planning context lives in `docs/private/` (gitignored, not published); agents may read `docs/private/iteration-2.md` for background but should keep public docs free of its contents
- Agents SHOULD update design docs when reconnaissance uncovers findings that change assumptions (e.g., "Mode 06 is sparse on this ECU" → update risks section)
- ADRs are **immutable once published** — capture decisions with rationale, don't edit retroactively. (Pre-release, before anyone relies on them, the set may still be renumbered to stay clean/contiguous.) Number as written, not by pre-reservation.

### Week 1 Priorities (in order)
1. **Repo bootstrap** — flake.nix, CLAUDE.md, README, directory structure ✅ (done)
2. **ADR 0001** — Telegraf vs OTel Collector for MQTT→Postgres (pure research, no code) ✅ (done)
3. **Decode library scaffold** — `parse_mode06()` and `parse_mode01()` with synthetic golden tests
4. **Decode table skeleton** — CSV with columns: `mid, tid, name, uasid, scale, offset, unit, source, covered_by_offtheshelf`
5. **Tutorial post #1 outline** — draft structure (fill in real numbers after day 3 car work)

### Testing Philosophy
- **Golden tests with synthetic payloads now** — hand-built CAN frames per SAE J1979 structure
- **Real fixtures replace synthetic on day 3** — when we have actual car data
- **Three oracles:**
  1. OBDLink SX USB (hardware, ELM327-based commercial firmware)
  2. OBD Auto Doctor or Torque Pro (independent consumer app)
  3. python-OBD source code (MIT-licensed, read as reference, not imported)
- **If all three agree and we disagree → our bug**

### Decode Table Coverage Column
`covered_by_offtheshelf` ∈ {`named+scaled`, `raw-only`, `absent`}

This column **draws the boundary** between solved problems (what Torque/OBD Auto Doctor already do) and this project's contribution (longitudinal trending + documenting the gap). Week 1 day 2 fills this via oracle passes.

## Key Constraints

### Never Do This
- **Clear DTCs** — Maryland VEIP inspection fails on not-ready monitors; clearing codes also resets Mode 06 results
- **Poll while driving alone** — first moving captures are listen-only or with a passenger running the laptop
- **Commit raw logs with VINs** — service 09 responses embed VIN; scrub before commit
- **Transmit on first contact** — always `listen-only on` when bringing up a new CAN interface

### Always Do This
- **Battery maintainer during KOEO** — key-on-engine-off polling kills a 12V battery in under an hour
- **Multimeter parasitic draw check** — before anything stays plugged into OBD port overnight (pin 16 = unswitched battery)
- **Consult the oracle** — when ISO-TP behaves strangely, verify against OBDLink SX before assuming the car is wrong
- **Tests green before merge** — `nix flake check` must pass

## Data Flow (from architecture.md §2)

```
┌─────────────┐
│  Accord ECU │  Broadcast CAN + responds to Mode 01/06 requests
└──────┬──────┘
       │
┌──────▼──────────┐
│  WiCAN Pro      │  Polls ECU, publishes MQTT (JSON payloads, raw hex)
│  (in-vehicle)   │  Deep-sleep between polls (<1mA), WiFi to home AP
└──────┬──────────┘
       │ MQTT (QoS 1, TLS)
┌──────▼──────────────────┐
│  Gateway (ProDesk)      │
│  ┌──────────────────┐   │
│  │ Telegraf         │   │  MQTT consumer → decoderd (execd) decode → Postgres
│  │ (mqtt_consumer)  │   │
│  └────┬─────────────┘   │
│       │                 │
│  ┌────▼─────────────┐   │
│  │ PostgreSQL 16    │   │  Range-partitioned monthly on ts, BRIN index
│  │ (no Timescale)   │   │
│  └────┬─────────────┘   │
│       │                 │
│  ┌────▼─────────────┐   │
│  │ Grafana          │   │  Dashboards: value vs limits over time
│  └──────────────────┘   │
└─────────────────────────┘
```

**No cloud, no subscriptions, offline-capable.**

## Hardware Status (Week 1)

| Item | Status | ETA |
|------|--------|-----|
| CANable Pro (isolated) | On order | TBD |
| WiCAN Pro | On order | ~2 weeks |
| OBDLink SX USB | On order | TBD |
| OBD2 splitter | On order | TBD |
| ProDesk G4 Mini | On order (eBay) | TBD |
| Battery maintainer | On order | TBD |
| High-endurance microSD | On order | TBD |

**Until hardware arrives:** All work is laptop-only (ADRs, decode library with synthetic tests, tutorial outlines).

## Open Questions

Consult `docs/design/architecture.md` §6 (Risks) for the live list. As of week 1 start:

1. **How rich is Mode 06 on this ECU?** (kill-gate question, answered day 4)
2. **Can WiCAN's polling engine issue Mode 06 or only Mode 01?** (answered when WiCAN arrives, bench test only)
3. **Proprietary UASIDs:** Do Honda-specific monitors (UASID high bit set) follow a discoverable pattern? (month 2 work if Mode 06 is rich)

## References

- **SAE J1979:** OBD-II diagnostic standard (paywalled; we use public summaries + oracles for verification)
- **ISO 15765-4:** CAN transport for OBD (ISO-TP)
- **python-OBD:** [https://github.com/brendan-w/python-obd](https://github.com/brendan-w/python-obd) — MIT-licensed, reference for Mode 06 structure
- **Design doc:** `docs/design/architecture.md` — read this first for strategic context

## Exit Criteria (Week 1)

- [x] All hardware ordered day 0; gateway box ordered
- [x] Public repo: flake + devShell + CLAUDE.md + design docs + ADRs (0001 pipeline, 0002 Rust decode; hardware ADRs follow when the gear is evaluated)
- [x] Decode table with golden tests green in `nix flake check`
- [ ] 5+ trip fixtures, VIN-scrubbed, committed — *car-blocked*
- [ ] Kill-gate memo written: Mode 06 rich / narrowed to Mode 01 — *car-blocked*
- [ ] Tutorial post #1 published

---

**Last updated:** Week 1 — Rust decode conversion Phases 1–5 complete (`nix flake check` green)