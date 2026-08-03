"""Equivalence gate over the deployed artifact.

Drives the real ``decoderd`` binary (the same one that runs as the Telegraf
``execd`` processor) over the frozen golden corpus and asserts its JSON output
matches the committed ``expected``. This is the deployed-artifact half of the
two-tier gate; the hermetic half is ``crates/decode/tests/golden.rs``.

No ``import obd`` here — the corpus is frozen data, so this stays GPL-clean and
hermetic. Seeding/verifying the corpus against python-OBD lives in the dev-only
``regen_golden.py``.

Locating ``decoderd`` (in order): ``$DECODERD`` env var, then ``decoderd`` on
``PATH`` (how the Nix ``pytest`` check finds it), then a ``cargo run`` fallback
for the dev shell.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "pkgs" / "decode-rs" / "golden" / "mode06.json"
CARGO_MANIFEST = REPO / "pkgs" / "decode-rs" / "Cargo.toml"

# Absolute tolerance for scaled float fields: J1979 scalings are small decimals,
# and an independent oracle (python-OBD's pint arithmetic) is never bit-identical
# to our f64. Well below any real sensor resolution.
EPS = 1e-9

# Fields compared exactly (ints / strings / bools) vs with tolerance (scaled floats).
EXACT_FIELDS = (
    "mid",
    "tid",
    "uasid",
    "test_value_raw",
    "min_limit_raw",
    "max_limit_raw",
    "unit",
    "name",
    "is_manufacturer_defined",
    "passed",
)
FLOAT_FIELDS = ("test_value", "min_limit", "max_limit")


def _decoderd_cmd():
    override = os.environ.get("DECODERD")
    if override:
        return [override]
    found = shutil.which("decoderd")
    if found:
        return [found]
    return ["cargo", "run", "-q", "-p", "decoderd", "--manifest-path", str(CARGO_MANIFEST)]


def _load_cases():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


CASES = _load_cases()


@pytest.fixture(scope="module")
def decoded():
    """Stream every golden frame through one decoderd process (execd-style)."""
    stdin = "".join(
        json.dumps({"mode": "06", "hex": c["hex"]}) + "\n" for c in CASES
    )
    proc = subprocess.run(
        _decoderd_cmd(),
        input=stdin,
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert proc.returncode == 0, f"decoderd failed (rc={proc.returncode}): {proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == len(CASES), (
        f"expected {len(CASES)} output lines, got {len(lines)}: {proc.stdout!r}"
    )
    return [json.loads(ln) for ln in lines]


def _approx(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= EPS


def _compare_record(got, exp, ctx):
    for key in EXACT_FIELDS:
        assert got[key] == exp[key], f"{ctx} {key}: {got[key]!r} != {exp[key]!r}"
    for key in FLOAT_FIELDS:
        assert _approx(got[key], exp[key]), f"{ctx} {key}: {got[key]!r} != {exp[key]!r}"


@pytest.mark.parametrize("idx", range(len(CASES)), ids=[c["name"] for c in CASES])
def test_decoderd_matches_golden(decoded, idx):
    case = CASES[idx]
    got = decoded[idx]
    assert got.get("mode") == "06", f"{case['name']}: unexpected response {got!r}"
    exp_records = case["expected"]["records"]
    got_records = got["records"]
    assert len(got_records) == len(exp_records), (
        f"{case['name']}: record count {len(got_records)} != {len(exp_records)}"
    )
    for i, (g, e) in enumerate(zip(got_records, exp_records)):
        _compare_record(g, e, f"{case['name']} record {i}")
