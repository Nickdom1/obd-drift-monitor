# Nix Setup Guide

The project is a Nix flake. Everything — dev shell, checks, the decode package, and the
gateway config — is defined in `flake.nix`.

## Quick start

```bash
# Enter the development shell
nix develop

# Run the decode-library tests
pytest

# Lint
ruff check pkgs/

# Run everything the CI gate runs (tests + lints)
nix flake check
```

## What the flake provides

1. **Dev shell** (`nix develop`)
   - Python 3.11 with `pytest` and `pytest-cov`
   - `ruff` for linting and formatting
   - `can-utils` (`candump`, `cansend`, `isotpsend`, `isotprecv`) for bench work
   - `dfu-util` for flashing CANable firmware
   - `git`

2. **Checks** (`nix flake check`)
   - Runs pytest over `pkgs/`
   - Runs ruff over `pkgs/`

3. **Packages**
   - `decode` — the standalone Python decode library (`nix build .#decode`)

4. **NixOS configuration** (`nixosConfigurations.gateway`)
   - Placeholder for the ProDesk appliance; fleshed out when hardware arrives
   (Telegraf, PostgreSQL 16, Grafana, Mosquitto)

## Running tests

```bash
nix develop

pytest                                   # all tests
pytest --cov=pkgs --cov-report=html      # with coverage
pytest pkgs/decode/tests/test_mode06.py -v   # a single file
```

## Building the decode package

```bash
nix build .#decode      # result symlink appears at ./result
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
