"""Dev-only: seed / verify the standard-UASID golden vectors against python-OBD.

python-OBD (GPL-2.0) is the independent oracle for the *standard-UASID* subset of
the Mode 06 corpus. This script imports it (hence dev-shell / impure only — it is
never collected by pytest and never enters a ``nix flake check`` gate) and, for
every eligible golden case, recomputes the scaled values from python-OBD's own
``UAS_IDS`` scaling table, then compares against the committed ``expected``.

A case is *eligible* (oracle = ``python-obd``) only when python-OBD would fully
reproduce it: non-empty, every record a standard UASID (high bit clear), and no
``0xFFFF`` "not applicable" sentinel — python-OBD silently drops manufacturer
monitors and has no sentinel handling, so those stay ``authored-j1979`` (an
expected, documented divergence).

Usage (inside ``nix develop``)::

    python harness/regen_golden.py           # verify: report drift, exit nonzero on any
    python harness/regen_golden.py --write    # persist regenerated standard-UASID vectors

The frozen corpus is committed data; CI never runs this. Any drift between our
values and python-OBD's is an intentional finding to triage, not a silent update.
"""

import argparse
import json
import sys
from pathlib import Path

# python-OBD's canonical unit-and-scaling table: {uasid: callable(bytes) -> pint Quantity}.
from obd.UnitsAndScaling import UAS_IDS  # type: ignore[import-not-found]

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "pkgs" / "decode-rs" / "golden" / "mode06.json"
SENTINEL = 0xFFFF
EPS = 1e-9


def _eligible(records):
    """True when python-OBD would fully reproduce every record in this case."""
    if not records:
        return False
    for r in records:
        if r["uasid"] & 0x80:  # manufacturer-defined: python-OBD drops it
            return False
        if r["min_limit_raw"] == SENTINEL or r["max_limit_raw"] == SENTINEL:
            return False  # sentinel: python-OBD has no such handling
    return True


def _oracle_scale(uasid, raw):
    """Scale a 16-bit raw value through python-OBD's UAS table -> (value, unit)."""
    q = UAS_IDS[uasid](bytearray([(raw >> 8) & 0xFF, raw & 0xFF]))
    return float(q.magnitude), format(q.units, "~")


def _oracle_record(rec):
    """Rebuild the scaled fields of one record from the python-OBD oracle."""
    uasid = rec["uasid"]
    value, unit = _oracle_scale(uasid, rec["test_value_raw"])
    lo, _ = _oracle_scale(uasid, rec["min_limit_raw"])
    hi, _ = _oracle_scale(uasid, rec["max_limit_raw"])
    out = dict(rec)
    out["test_value"] = value
    out["min_limit"] = lo
    out["max_limit"] = hi
    out["unit"] = unit
    out["passed"] = lo <= value <= hi
    return out


def _drift(committed, regenerated):
    """Return a list of human-readable field drifts between two records."""
    diffs = []
    for key, new in regenerated.items():
        old = committed.get(key)
        if isinstance(new, float) or isinstance(old, float):
            if old is None or new is None or abs(float(old) - float(new)) > EPS:
                if old != new:
                    diffs.append(f"{key}: {old!r} -> {new!r}")
        elif old != new:
            diffs.append(f"{key}: {old!r} -> {new!r}")
    return diffs


def main(argv=None):
    parser = argparse.ArgumentParser(description="Seed/verify golden vectors vs python-OBD.")
    parser.add_argument("--write", action="store_true", help="persist regenerated vectors")
    opts = parser.parse_args(argv)

    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    total_drift = 0
    for case in doc["cases"]:
        records = case["expected"]["records"]
        if not _eligible(records):
            print(f"skip  {case['name']} (authored-j1979: manufacturer/sentinel/bitmap)")
            continue
        regenerated = [_oracle_record(r) for r in records]
        case_drift = [
            d
            for old, new in zip(records, regenerated)
            for d in _drift(old, new)
        ]
        if case_drift:
            total_drift += len(case_drift)
            print(f"DRIFT {case['name']}:")
            for d in case_drift:
                print(f"        {d}")
        else:
            print(f"ok    {case['name']} (python-obd)")
        if opts.write:
            case["expected"]["records"] = regenerated
            case["oracle"] = "python-obd"

    if opts.write:
        GOLDEN.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {GOLDEN.relative_to(REPO)}")

    if total_drift and not opts.write:
        print(f"\n{total_drift} field(s) diverge from python-OBD — triage as a finding.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
