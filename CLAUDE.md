# CLAUDE.md — Agent Context and Conventions

This file provides context for AI agents (Claude, Copilot, Cursor, etc.) working on the OBD Drift Monitor project.

## Project Overview

**One-liner:** Your car grades its own health; this project keeps the report cards.

**What it does:** Captures OBD-II Mode 06 monitor test results from a 2018 Honda Accord, stores them as time series in Postgres, and tracks drift over time to catch sensor degradation before fault codes appear.

**Current phase:** Week 1 — decode library development and hardware reconnaissance (pre-hardware, laptop-only work).

> **Active work: Rust decode conversion (in progress).** The shipped decoder is being rewritten in
> **Rust** (`pkgs/decode-rs/`), fixing a real Mode 06 framing bug (7-byte legacy vs correct 9-byte
> CAN records). Python is retained **only** as the equivalence/benchmark harness and oracle
> (python-OBD). See `docs/private/rust-conversion-plan.md` for the full plan and phase status.
> Phases 1–2 (scaffold + decoders) and the nixpkgs bump are done; Phase 3 (equivalence harness +
> frozen golden vectors) is next and begins by deleting the old buggy Python decoder in `pkgs/decode/`.

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
ruff check .
ruff format .

# Individual flake checks (aggregate `nix flake check` is red until Phase 7 fixes
# the gateway placeholder — gate on the individual checks meanwhile):
nix build .#checks.x86_64-linux.cargo-test
nix build .#checks.x86_64-linux.pytest
nix build .#checks.x86_64-linux.ruff-check
```

## Repository Structure

```
obd-drift-monitor/
├── docs/
│   ├── design/          # Living design documents (agents update these per findings)
│   │   └── architecture.md
│   ├── private/         # personal strategy/planning notes — gitignored, not published
│   └── adr/             # Architecture Decision Records (numbered, immutable once written)
│       └── 0003-collector-choice.md (coming)
├── pkgs/
│   ├── decode-rs/       # SHIPPED decoder — Rust (pure lib, no I/O)
│   │   ├── crates/decode/    # lib: mode06.rs (9-byte fix), mode01.rs, bitmap.rs, table.rs, types.rs
│   │   ├── crates/decoderd/  # thin bin: JSON-lines stdin->stdout (== Telegraf execd processor)
│   │   └── Cargo.toml / rust-toolchain.toml
│   ├── decode/          # OLD Python decoder — buggy 7-byte framing, TO BE DELETED in Phase 3
│   └── gateway/         # NixOS configuration for the ProDesk appliance (week 2+)
├── harness/             # Python: equivalence + benchmark oracle (survives here only; Phase 3)
├── fixtures/            # Real OBD captures, VIN-scrubbed (populated day 3+)
├── flake.nix            # Nix devShell + Rust/Python checks + gateway build
├── CLAUDE.md            # This file
├── README.md            # Public-facing project pitch
└── LICENSE              # MIT
```

## Coding Conventions

### Python
- **Style:** PEP 8, enforced by `ruff`
- **Testing:** pytest with fixtures in `tests/` subdirectories
- **Type hints:** Encouraged but not required for week 1
- **Decode library philosophy:** Pure functions, no I/O. Parse bytes → return structured data. Never touch sockets, files, or databases inside `pkgs/decode/`.

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
- ADRs are **immutable once written** — capture decisions with rationale, don't edit retroactively

### Week 1 Priorities (in order)
1. **Repo bootstrap** — flake.nix, CLAUDE.md, README, directory structure ✅ (done)
2. **ADR 0003** — Telegraf vs OTel Collector for MQTT→Postgres (pure research, no code)
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
│  │ Telegraf         │   │  MQTT consumer → Starlark decode → Postgres
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

- [ ] All hardware ordered day 0; gateway box ordered
- [ ] Public repo: flake + devShell + CLAUDE.md + design docs + ADRs 0001–0003
- [ ] Decode table with golden tests green in `nix flake check`
- [ ] 5+ trip fixtures, VIN-scrubbed, committed
- [ ] Kill-gate memo written: Mode 06 rich / narrowed to Mode 01
- [ ] Tutorial post #1 published

---

**Last updated:** Week 1 (repo bootstrap)