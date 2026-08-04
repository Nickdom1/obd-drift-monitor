{
  description = "OBD Drift Monitor - Vehicle telemetry gateway and time-series monitor tracking";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        # Python env for the equivalence + benchmark harness. Pure stdlib + pytest;
        # python-OBD is deliberately NOT here (see regenPythonEnv below).
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          pytest
          pytest-cov
        ]);

        # The Rust decoder, built + unit/golden-tested once. Defined in
        # pkgs/decode-rs/package.nix (a callPackage-able derivation) so the exported
        # `packages.decoder`, the `overlays.default`, and the `cargo-test` check all
        # share ONE definition. buildRustPackage runs `cargo test` (incl. the frozen-
        # vector golden gate) in its check phase and installs the `decoderd` binary;
        # the same derivation is also fed to the pytest check so the harness drives
        # the exact deployed artifact.
        decoderPkg = pkgs.callPackage ./pkgs/decode-rs/package.nix { };

        # python-OBD (GPL-2.0) — the independent oracle for regen_golden.py only.
        # DEV-ONLY: it lives exclusively in the `regen` dev shell, never in any
        # `nix flake check` gate or shipped package, so the copyleft oracle stays
        # out of the CI path and the artifact (the frozen vectors are data/facts).
        # Not in nixpkgs, so packaged here from PyPI; deps (pint, pyserial) are.
        python-obd = pkgs.python3Packages.buildPythonPackage rec {
          pname = "obd";
          version = "0.7.2";
          format = "setuptools";
          src = pkgs.fetchPypi {
            inherit pname version;
            hash = "sha256-INOMne09qtHor/qz/zZ6cHiNTymsd6t6rN3GptKkPWE=";
          };
          propagatedBuildInputs = with pkgs.python3Packages; [ pint pyserial ];
          pythonRelaxDeps = [ "pint" "pyserial" ];
          doCheck = false;
          meta.license = pkgs.lib.licenses.gpl2Only;
        };

        # Python env that additionally carries the GPL oracle for the regen shell.
        regenPythonEnv = pkgs.python3.withPackages (ps: [ ps.pytest python-obd ]);

      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # Python environment with test tooling (equivalence + benchmark harness)
            pythonEnv

            # Rust toolchain for the decode crate (lib + decoderd bin)
            cargo
            rustc
            clippy
            rustfmt

            # CAN utilities for bench work
            can-utils

            # Linting and formatting
            ruff

            # Git for version control
            git

            # Firmware flashing for the CANable (candleLight/DFU)
            dfu-util
          ];

          shellHook = ''
            echo "🚗 OBD Drift Monitor development environment"
            echo ""
            echo "Available commands:"
            echo "  cargo test          - Rust decode tests + frozen-vector golden gate (pkgs/decode-rs)"
            echo "  pytest harness/     - Drive decoderd over the golden corpus (build decoderd first)"
            echo "  ruff check harness/ - Lint the Python harness"
            echo "  nix flake check     - Run all checks (gate on individual checks; see CLAUDE.md)"
            echo ""
            echo "Oracle regen (GPL python-OBD, dev-only shell):"
            echo "  nix develop .#regen --command python harness/regen_golden.py"
            echo ""
            echo "CAN utilities (for hardware work):"
            echo "  candump, cansend, isotpsend, isotprecv"
            echo ""
            echo "Status: Week 1 - awaiting hardware, building decode library"
            echo ""
          '';
        };

        # Dev-only shell carrying python-OBD (GPL-2.0) for seeding/verifying the
        # golden vectors against the oracle. Isolated from the default shell so the
        # copyleft dependency never touches the mainline dev flow or the checks.
        devShells.regen = pkgs.mkShell {
          buildInputs = with pkgs; [ regenPythonEnv cargo rustc git ];
          shellHook = ''
            echo "🔬 regen shell — python-OBD oracle available (GPL-2.0, dev-only)"
            echo "  python harness/regen_golden.py          # verify golden vs python-OBD"
            echo "  python harness/regen_golden.py --write   # persist regenerated vectors"
          '';
        };

        # Standalone decoder package: `nix build .#decoder` / `nix run .#decoder`
        # (runs decoderd via meta.mainProgram) with no gateway/host coupling — the
        # independently-consumable proof. Same derivation as `checks.cargo-test`.
        packages.decoder = decoderPkg;
        packages.default = decoderPkg;

        # Checks run by 'nix flake check'. The aggregate now goes green: the gateway
        # placeholder gained a nominal root fileSystems entry so it evaluates. Full
        # gateway/hardware decoupling is still Phase 7; this is just the eval fix.
        checks = {
          # Rust decode crate: unit tests + the hermetic frozen-vector golden gate.
          cargo-test = decoderPkg;

          # Equivalence over the deployed artifact: drive the real decoderd binary
          # across the golden corpus and assert its JSON matches the frozen expected.
          pytest = pkgs.stdenv.mkDerivation {
            name = "obd-drift-monitor-pytest";
            src = ./.;

            nativeBuildInputs = [ pythonEnv decoderPkg ];

            buildPhase = ''
              export DECODERD=${decoderPkg}/bin/decoderd
              pytest harness/ --verbose
            '';

            installPhase = ''
              mkdir -p $out
              echo "Equivalence tests passed" > $out/result
            '';
          };

          ruff-check = pkgs.stdenv.mkDerivation {
            name = "obd-drift-monitor-ruff";
            src = ./.;

            nativeBuildInputs = [ pkgs.ruff ];

            buildPhase = ''
              ruff check harness/
            '';

            installPhase = ''
              mkdir -p $out
              echo "Ruff checks passed" > $out/result
            '';
          };
        };
      }
    ) // {
      # Overlay so a consumer can pull just the decoder into their own nixpkgs
      # (e.g. `pkgs.obd-decoder`) without adopting the gateway/host config — the
      # loosely-coupled, independently-consumable piece. Shares package.nix with
      # the per-system `packages.decoder` output above.
      overlays.default = final: _prev: {
        obd-decoder = final.callPackage ./pkgs/decode-rs/package.nix { };
      };

      # NixOS configuration for the gateway appliance
      # (ProDesk G4 target - to be populated in week 2+)
      nixosConfigurations.gateway = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          # Hardware configuration will be generated on the physical box
          # For now, just a placeholder structure
          ({ pkgs, ... }: {
            system.stateVersion = "26.05";

            # Placeholder root filesystem so the config *evaluates* (a NixOS system
            # needs a root fileSystems entry to build its toplevel). This is not real
            # hardware detail — it is replaced by a generated hardware-configuration.nix
            # when the appliance (ProDesk, or an interim laptop) is flashed. Its only
            # job today is to keep the aggregate `nix flake check` green.
            fileSystems."/" = {
              device = "/dev/disk/by-label/nixos";
              fsType = "ext4";
            };

            # Minimal base - flesh out when hardware arrives
            boot.loader.systemd-boot.enable = true;
            boot.loader.efi.canTouchEfiVariables = true;

            networking.hostName = "obd-gateway";
            networking.useDHCP = true;

            # Services to be configured:
            # - telegraf (MQTT consumer → Postgres writer)
            # - postgresql 16 (native range partitioning, no Timescale)
            # - grafana
            # - mosquitto (optional local broker for testing)

            services.openssh.enable = true;

            environment.systemPackages = with pkgs; [
              vim
              htop
              tmux
            ];

            # Placeholder user
            users.users.obd = {
              isNormalUser = true;
              extraGroups = [ "wheel" ];
              # SSH keys to be added
            };
          })
        ];
      };
    };
}
