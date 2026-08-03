"""Dev-only: python-OBD Mode 06 decode throughput baseline for the write-up.

This is the *correct-vs-correct* benchmark baseline: it times python-OBD's own
``monitor()`` decoder (GPL-2.0 oracle) over the exact same frozen golden corpus
the Rust criterion bench uses (``benches/decode.rs``), so the two frames/sec
numbers compare on identical input. The old buggy 7-byte Python parser is deleted,
so python-OBD (the 9-byte oracle) is the only honest Python baseline.

Because it imports ``obd`` it is dev-shell / impure only (never collected by
pytest, never in a ``nix flake check`` gate)::

    nix develop .#regen --command python harness/bench_baseline.py

Note on scope: python-OBD's ``monitor()`` accepts every corpus frame without error
but *internally drops* the rows this project keeps raw — manufacturer UASIDs
(``uasid & 0x80``) and the ``0xFFFF`` sentinel — and truncates the supported-MID
bitmap frame to empty. Those frames therefore do slightly *less* work in python-OBD
than in our decoder, so the measured Rust lead is a conservative floor. We still
time the full corpus (not a filtered subset) so both benches see identical bytes.
"""

import json
import timeit
from pathlib import Path

# python-OBD's real Mode 06 decode path (its ``monitor`` decoder loops 9-byte
# records through ``parse_monitor_test`` + the ``UAS_IDS`` scaling table).
from obd.decoders import monitor  # type: ignore[import-not-found]

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "pkgs" / "decode-rs" / "golden" / "mode06.json"
ITERATIONS = 200_000


class _Msg:
    """Minimal stand-in for python-OBD's ``Message``: ``monitor()`` only reads
    ``.data`` (the full response bytes, including the 0x46 service byte)."""

    __slots__ = ("data",)

    def __init__(self, data: bytearray) -> None:
        self.data = data


def _frames() -> list[list[_Msg]]:
    """Pre-build one ``[Message]`` argument per corpus frame, outside the timed
    loop, so only decode work is measured."""
    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return [[_Msg(bytearray.fromhex(case["hex"]))] for case in doc["cases"]]


def main() -> int:
    frames = _frames()
    n_frames = len(frames)

    def decode_corpus() -> None:
        for messages in frames:
            monitor(messages)

    total_s = timeit.timeit(decode_corpus, number=ITERATIONS)
    per_iter_s = total_s / ITERATIONS
    per_frame_us = per_iter_s / n_frames * 1e6
    frames_per_s = n_frames / per_iter_s

    print(f"python-OBD monitor() baseline over {n_frames} golden frames")
    print(f"  iterations   : {ITERATIONS:,}")
    print(f"  per corpus   : {per_iter_s * 1e6:8.3f} us")
    print(f"  per frame    : {per_frame_us:8.4f} us")
    print(f"  throughput   : {frames_per_s / 1e6:8.4f} M frames/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
