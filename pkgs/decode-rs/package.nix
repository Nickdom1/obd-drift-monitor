# The shipped OBD decoder, as a standalone `callPackage`-able derivation. Kept
# here (not inline in flake.nix) so the per-system `packages.decoder` output and
# the `overlays.default` share ONE definition. buildRustPackage runs `cargo test`
# (incl. the frozen-vector golden gate) in its check phase and installs `decoderd`.
#
# This is the decoupling proof: a consumer can `nix build .#decoder` or add the
# overlay to pull just the decoder, with no dependency on the gateway/host config.
{ rustPlatform, lib }:

rustPlatform.buildRustPackage {
  pname = "obd-decoder";
  version = "0.1.0";

  # `./.` is pkgs/decode-rs — the whole Rust workspace (decode lib + decoderd bin).
  src = ./.;
  cargoLock.lockFile = ./Cargo.lock;

  meta = {
    description = "OBD-II Mode 06/01 decoder — decoderd JSON-lines binary (Telegraf execd processor)";
    homepage = "https://github.com/Nickdom1/obd-drift-monitor";
    license = lib.licenses.mit; # matches the workspace Cargo.toml + repo LICENSE
    mainProgram = "decoderd"; # so `nix run .#decoder` runs the decoderd binary
  };
}
