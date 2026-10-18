"""Safe Windows launcher for Q1 joint-vs-marginal BSD68 experiment.

- Reuse an already complete and config-matching output (no wasted GPU rerun).
- Leave all earlier directories untouched, including interrupted experiments.
- If needed select an unused _02/_03/... output directory automatically.
- Opt into a fresh rerun even if complete: --new.
- NO FPGA/JTAG/XSDB operations.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "dn_d10_c32_us_fx_qat"
OPTIMIZER_SEEDS = [13, 42, 127, 612]
BUDGET = 401
MODES = {
    "smoke": dict(images=2, sigmas=[25], seeds=[0],
                  arguments=["--max-images", "2", "--sigma", "25", "--noise-seeds", "0"]),
    "full": dict(images=68, sigmas=[15, 25, 50], seeds=[0, 1, 2], arguments=[]),
}


def validate_complete(directory: Path, mode: str) -> tuple[bool, str, dict | None]:
    """Treat existing output as complete only after exact config and CSV coverage checks."""
    spec = MODES[mode]
    files = ("summary.json", "groups.json", "per_condition.csv")
    if any(not (directory / name).is_file() for name in files):
        return False, "Missing one or more completion files", None
    try:
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        groups = json.loads((directory / "groups.json").read_text(encoding="utf-8"))
        if (summary.get("status") != "OFFLINE_BSD68_CYCLE_MODEL_PROXY_NOT_FPGA_MEASUREMENT"
                or summary.get("independent_clean_images") != spec["images"]
                or summary.get("sigmas") != spec["sigmas"]
                or summary.get("noise_seeds") != spec["seeds"]
                or summary.get("optimizer_seeds") != OPTIMIZER_SEEDS
                or summary.get("budget_per_method_per_layer") != BUDGET):
            return False, "Summary config/status mismatch", None
        if (groups.get("model") != MODEL or groups.get("budget") != BUDGET
                or sorted(groups.get("groups", {}).keys()) != sorted(map(str, OPTIMIZER_SEEDS))):
            return False, "Optimizer group manifest mismatch", None
        expected = spec["images"] * len(spec["sigmas"]) * len(spec["seeds"]) * len(OPTIMIZER_SEEDS)
        seen = set()
        images = set()
        with (directory / "per_condition.csv").open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key = (row["image"], int(row["sigma"]), int(row["noise_seed"]),
                       int(row["optimizer_seed"]))
                if key in seen:
                    return False, "Duplicate evaluation row", None
                if (key[1] not in spec["sigmas"] or key[2] not in spec["seeds"]
                        or key[3] not in OPTIMIZER_SEEDS
                        or not math.isfinite(float(row["joint_saved_pct"]))
                        or not math.isfinite(float(row["marginal_saved_pct"]))
                        or int(row["identity_cycles"]) <= 0):
                    return False, "Invalid evaluation row", None
                seen.add(key)
                images.add(key[0])
        if len(seen) != expected or len(images) != spec["images"]:
            return False, f"Incomplete evaluated conditions: {len(seen)}/{expected}", None
        if any(sum(k[0] == image for k in seen) != expected // spec["images"] for image in images):
            return False, "Unequal coverage across clean images", None
        return True, f"Complete: {len(images)} clean images and {len(seen)} scored conditions", summary
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as ex:
        return False, "Invalid completion records: " + str(ex), None


def select_output(root: Path, mode: str, new: bool = False):
    base = root / ("q1_novelty_bsd68_" + mode)
    first_free = None
    occupied = []
    for n in range(1, 1001):
        path = base if n == 1 else base.with_name(base.name + f"_{n:02}")
        if not path.exists():
            if first_free is None:
                first_free = path
            continue
        occupied.append(path)
        if not new:
            ok, reason, summary = validate_complete(path, mode)
            if ok:
                return "reuse", path, summary, occupied
    if first_free is None:
        raise RuntimeError("No unused output names among 1000 candidates")
    return "run", first_free, None, occupied


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=tuple(MODES), nargs="?", default="smoke")
    ap.add_argument("--new", action="store_true",
                    help="force a new unique experiment, even if an old run completed")
    ap.add_argument("--output-root", type=Path, default=ROOT / "build",
                    help="parent of q1_novelty_bsd68_smoke/full run directories")
    args = ap.parse_args()
    action, out, summary, occupied = select_output(args.output_root, args.mode, args.new)
    if action == "reuse":
        print(f"COMPLETE EXISTING EXPERIMENT: {out}", flush=True)
        print("Existing summary was checked against requested settings and expected CSV coverage.", flush=True)
        print(f"Joint savings: {summary['joint_saved_pct']:.5f}%; "
              f"marginal-only: {summary['marginal_saved_pct']:.5f}%; "
              f"joint advantage: {summary['joint_minus_marginal_pp']:+.5f} pp", flush=True)
        print("No GPU rerun needed; no data overwritten.", flush=True)
        print("If you explicitly want a fresh run: add 'new' to the CMD command.", flush=True)
        return 0
    if occupied:
        print("Existing output paths preserved (never deleted or overwritten):", flush=True)
        for path in occupied:
            ok, reason, _ = validate_complete(path, args.mode)
            print(" -", path, "—", reason, flush=True)
    print("NEW OUTPUT:", out, flush=True)
    print("Running OFFLINE only: no FPGA/JTAG connection.", flush=True)
    command = [
        sys.executable, "-u", str(ROOT / "scripts" / "q1_novelty_bsd68_holdout.py"),
        *MODES[args.mode]["arguments"], "--out", str(out),
    ]
    code = subprocess.run(command, cwd=ROOT, check=False).returncode
    if code:
        print("Experiment did not complete. Previous output dirs remain untouched.", flush=True)
        print("Inspect:", out, flush=True)
        return code
    ok, reason, _ = validate_complete(out, args.mode)
    if not ok:
        print("ERROR: Subprocess exited normally but output is incomplete:", reason, flush=True)
        return 1
    print("PASS validated run:", out, flush=True)
    for name in ("summary.json", "per_condition.csv", "groups.json"):
        print("Saved:", out / name, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
