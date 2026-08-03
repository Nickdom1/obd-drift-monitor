# Nix Setup Guide

The project is a Nix flake. Everything — dev shell, checks, and the gateway config — is
defined in `flake.nix`. The shipped decoder is Rust (`pkgs/decode-rs/`); Python survives
only as the equivalence/benchmark harness (`harness/`).

## Quick start

```bash
# Enter the development shell
nix develop

# Decode library: unit/regression tests + the frozen-vector golden gate
cd pkgs/decode-rs && cargo test

# Equivalence harness: drive the decoderd binary over the golden corpus
pytest harness/

# Lint the harness
ruff check harness/

# Individual CI checks (see note below — the aggregate is red on the gateway placeholder)
nix build .#checks.x86_64-linux.cargo-test
nix build .#checks.x86_64-linux.pytest
nix build .#checks.x86_64-linux.ruff-check
```

> **Note:** aggregate `nix flake check` stays **red** until Phase 7 fixes the gateway
> placeholder (it has no root `fileSystems`). Gate on the three individual checks meanwhile.

## What the flake provides

1. **Dev shell** (`nix develop`)
   - Rust toolchain (`cargo`, `rustc`, `clippy`, `rustfmt`) for the decode crate
   - Python 3.13 with `pytest` and `pytest-cov` (harness)
   - `ruff` for linting and formatting
   - `can-utils` (`candump`, `cansend`, `isotpsend`, `isotprecv`) for bench work
   - `dfu-util` for flashing CANable firmware, `git`

2. **Regen dev shell** (`nix develop .#regen`)
   - Adds **python-OBD** (GPL-2.0, dev-only oracle) for `harness/regen_golden.py`
   - Isolated from the default shell and every check so the copyleft dep never enters CI

3. **Checks** (individual: `nix build .#checks.x86_64-linux.<name>`)
   - `cargo-test` — builds the workspace + `decoderd`, runs Rust unit/regression tests and
     the hermetic `tests/golden.rs` frozen-vector gate
   - `pytest` — drives the built `decoderd` over the golden corpus (`harness/`)
   - `ruff-check` — lints `harness/`

4. **NixOS configuration** (`nixosConfigurations.gateway`)
   - Placeholder for the ProDesk appliance; fleshed out when hardware arrives
   (Telegraf, PostgreSQL 16, Grafana, Mosquitto)

## Running tests

```bash
nix develop

cd pkgs/decode-rs && cargo test          # Rust unit + regression + golden gate
cargo clippy --all-targets               # lint the Rust
cd .. && pytest harness/ -v              # equivalence over the decoderd binary
```

## Building the decoder

```bash
# A standalone `packages.decoder` output + overlay lands in Phase 5. For now the
# decoder is built (and tested) by the cargo-test check, or directly:
cd pkgs/decode-rs && cargo build --release   # binary at target/release/decoderd
```

## Gateway configuration (Week 2+)

```bash
# Build the gateway configuration
nix build .#nixosConfigurations.gateway.config.system.build.toplevel

# Deploy to the physical box
nixos-rebuild switch --flake .#gateway --target-host obd@gateway.local
```

Will install Telegraf (MQTT → Postgres), PostgreSQL 16 (native range partitioning, no
Timescale), Grafana, and the decode logic.

## Tips

```bash
nix flake update                 # update flake.lock to latest nixpkgs
nix-collect-garbage -d           # clean up old builds
nix develop --pure               # dev shell with no impure environment
```

## Troubleshooting

### "experimental Nix feature 'flakes' is disabled"

Enable flakes:

```bash
mkdir -p ~/.config/nix
echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf
```

Or on NixOS, in `configuration.nix`:

```nix
{
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
}
```

### Tests pass in `nix develop` but fail in `nix flake check`

The check environment is more isolated. Ensure no hardcoded absolute paths, no
dependencies on files outside the flake, and that all test data lives in the repository.

## References

- Nix Flakes: https://nixos.wiki/wiki/Flakes
- nix.dev: https://nix.dev/
- NixOS Options Search: https://search.nixos.org/options
- `CLAUDE.md` — agent workflow and conventions
