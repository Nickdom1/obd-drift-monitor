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

        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          pytest
          pytest-cov
          # Decode library dependencies
          # (none yet - pure stdlib for now)
        ]);

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
            echo "  pytest              - Run tests"
            echo "  pytest --cov=pkgs   - Run tests with coverage"
            echo "  ruff check .        - Lint Python code"
            echo "  ruff format .       - Format Python code"
            echo "  cargo test          - Run Rust decode tests (in pkgs/decode-rs)"
            echo "  nix flake check     - Run all checks"
            echo ""
            echo "CAN utilities (for hardware work):"
            echo "  candump, cansend, isotpsend, isotprecv"
            echo ""
            echo "Status: Week 1 - awaiting hardware, building decode library"
            echo ""
          '';
        };

        # Checks run by 'nix flake check'
        checks = {
          pytest = pkgs.stdenv.mkDerivation {
            name = "obd-drift-monitor-pytest";
            src = ./.;

            buildInputs = [ pythonEnv ];

            buildPhase = ''
              # Set up Python path to find our packages
              export PYTHONPATH=$src:$PYTHONPATH

              # Run pytest
              pytest pkgs/ --verbose
            '';

            installPhase = ''
              mkdir -p $out
              echo "Tests passed" > $out/result
            '';
          };

          ruff-check = pkgs.stdenv.mkDerivation {
            name = "obd-drift-monitor-ruff";
            src = ./.;

            buildInputs = [ pkgs.ruff ];

            buildPhase = ''
              ruff check pkgs/
            '';

            installPhase = ''
              mkdir -p $out
              echo "Ruff checks passed" > $out/result
            '';
          };

          # Rust decode crate: buildRustPackage runs `cargo test` in its check
          # phase, so this builds the workspace and gates on the unit tests.
          cargo-test = pkgs.rustPlatform.buildRustPackage {
            pname = "obd-decode-rs";
            version = "0.1.0";
            src = ./pkgs/decode-rs;
            cargoLock.lockFile = ./pkgs/decode-rs/Cargo.lock;
          };
        };

        # Package for the decode library (standalone)
        packages.decode = pkgs.python3Packages.buildPythonPackage {
          pname = "obd-decode";
          version = "0.1.0";
          src = ./pkgs/decode;

          propagatedBuildInputs = [ ];

          checkInputs = with pkgs.python3Packages; [ pytest ];
          checkPhase = ''
            pytest
          '';

          meta = with pkgs.lib; {
            description = "OBD-II Mode 01 and Mode 06 decoder library";
            license = licenses.mit;
          };
        };
      }
    ) // {
      # NixOS configuration for the gateway appliance
      # (ProDesk G4 target - to be populated in week 2+)
      nixosConfigurations.gateway = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          # Hardware configuration will be generated on the physical box
          # For now, just a placeholder structure
          ({ pkgs, ... }: {
            system.stateVersion = "24.05";

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
