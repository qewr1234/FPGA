"""Reproduce real W4 board bank-mechanism results from a triplet rep_01.zip.

OFFLINE ONLY. Never connects to Vivado/JTAG/FPGA. Requires numpy.
Input ZIP is read-only, raw binary files are NOT uploaded to GitHub.

Usage:
  python scripts/q1_physical_mechanism_replay.py ^
    --triplet build/q1_bank_fpga_triplet/trial_01/triplet_summary.json ^
    --zip C:/path/to/rep_01.zip ^
    --out build/q1_physical_mechanism_replay/trial_01
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("original", "frozen", "multistart")
CORE_ID = "0x4d410303"
BASELINE_MODEL = "dn_d10_c32_us_fx_qat"
EXPECTED_BITSTREAM_SHA256 = "11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def im2col_3x3(q: np.ndarray) -> np.ndarray:
    if q.ndim != 3 or q.dtype != np.uint8:
        raise ValueError("Expected uint8 activation tensor (C,H,W)")
    c, h, w = q.shape
    padded = np.zeros((c, h + 2, w + 2), dtype=np.uint8)
    padded[:, 1:h + 1, 1:w + 1] = q
    taps = np.stack([padded[:, ky:ky + h, kx:kx + w]
                     for ky in range(3) for kx in range(3)], axis=0)
    return np.ascontiguousarray(taps.transpose(2, 3, 0, 1).reshape(h * w, 9 * c))


def window_cost(x: np.ndarray, cout: int) -> tuple[int, float, float]:
    n, k = x.shape
    if k % 4:
        raise ValueError("This W4 case expects K divisible by 4")
    banks = np.stack([np.count_nonzero(x[:, b::4], axis=1) for b in range(4)], axis=1)
    maximum = np.max(banks, axis=1)
    floor = max(k // 4 + 1, cout)
    issue = ((cout + 15) // 16) * np.maximum(1, maximum)
    cycles = np.maximum(floor, issue)
    return int(cycles.sum()), float(np.mean(maximum)), float(np.mean(issue <= floor) * 100)


def channel_multiset(q: np.ndarray) -> Counter[str]:
    return Counter(sha256_bytes(np.ascontiguousarray(ch).tobytes()) for ch in q)


def read_rep(z: zipfile.ZipFile, prefix: str, label: str):
    base = prefix + "/" + label + "/"
    report = json.loads(z.read(base + "report.json").decode("utf-8"))
    if (report.get("emulated") is not False or report.get("model") != BASELINE_MODEL
            or report.get("set") != "Set12" or report.get("sigma") != 25
            or report.get("activations_per_cycle") != 4 or report.get("mode_seq") != 1
            or report.get("mismatches") != 0):
        raise ValueError(label + ": not the expected physical W4 sparse report")
    images = report["images"]
    if len(images) != 1 or images[0].get("image") != "05.png":
        raise ValueError(label + ": expected Set12 05.png")
    layers = images[0]["layers"]
    if [x["name"] for x in layers] != [f"conv{i}" for i in range(1, 11)]:
        raise ValueError(label + ": expected 10 ordered Conv layers")
    for l in layers:
        if (l.get("emulated") is not False or l.get("mismatches") != 0
                or l.get("core_id") != [CORE_ID] or l.get("fclk_mhz") != [50.0]):
            raise ValueError(label + ": invalid physical layer check " + l["name"])
    npz = np.load(io.BytesIO(z.read(base + "05_maps10.npz")), allow_pickle=False)
    arrays = {name: npz[name] for name in npz.files}
    if set(arrays) != {"image", *(f"conv{i}" for i in range(1, 10))}:
        raise ValueError(label + ": invalid saved hidden activation map keys")
    png_hashes = {
        name: sha256_bytes(z.read(base + name))
        for name in ("05_clean.png", "05_noisy.png", "05_denoised.png")
    }
    return report, arrays, png_hashes


def analyze(summary_path: Path, zip_path: Path):
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (summary.get("status") != "PHYSICAL_3WAY_W4_CORE_CYCLE_COMPARISON"
            or summary.get("fclk_mhz") != 50.0
            or summary.get("physical_bitstream_sha256") != EXPECTED_BITSTREAM_SHA256):
        raise ValueError("Unexpected physical triplet metadata")
    if summary.get("replicates") != 3 or len(summary.get("repeat_rows", [])) != 3:
        raise ValueError("Expected three physical summary repetitions")
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad is not None:
            raise ValueError("ZIP CRC mismatch: " + bad)
        names = z.namelist()
        if any(name.startswith("/") or ".." in Path(name).parts or "\\" in name for name in names):
            raise ValueError("Unsafe ZIP entry path")
        matches = sorted(set(n.split("/")[0] for n in names if n.endswith("original/report.json")))
        # Strictly use the passed first physical replicate (same as summary repeat_rows[0]).
        prefix = "rep_01"
        if prefix not in matches:
            raise ValueError("rep_01 original report missing")
        reports, maps, pngs = {}, {}, {}
        for model in MODELS:
            reports[model], maps[model], pngs[model] = read_rep(z, prefix, model)
        for key in ("05_clean.png", "05_noisy.png", "05_denoised.png"):
            if len({pngs[model][key] for model in MODELS}) != 1:
                raise ValueError("Different PNG output/input for " + key)
        for i in range(1, 10):
            key = f"conv{i}"
            orig = channel_multiset(maps["original"][key])
            for model in MODELS[1:]:
                if channel_multiset(maps[model][key]) != orig:
                    raise ValueError("Hidden activation non-permutation: " + model + "/" + key)
        per_layer = []
        totals = {model: dict(predicted=0, physical=0, inner_predicted=0, inner_physical=0)
                  for model in MODELS}
        for model in MODELS:
            layers = reports[model]["images"][0]["layers"]
            for i, layer in enumerate(layers, 1):
                q = maps[model]["image"] if i == 1 else maps[model][f"conv{i-1}"]
                if i == 10:
                    q = np.concatenate([q, maps[model]["image"]], axis=0)
                x = im2col_3x3(q)
                if (x.shape != (layer["windows"], layer["K"])
                        or abs(float(np.mean(x != 0)) - layer["nonzero_fraction"]) > 1e-12):
                    raise ValueError(model + ": reconstructed im2col disagrees with FPGA driver " + layer["name"])
                predicted, mean_max, floor_pct = window_cost(x, int(layer["COUT"]))
                observed = int(layer["cycles"])
                per_layer.append(dict(model=model, layer=layer["name"], predicted_cycles=predicted,
                                      measured_cycles=observed, residual_cycles=observed-predicted,
                                      avg_max_bank_nnz=round(mean_max, 6),
                                      floor_limited_window_pct=round(floor_pct, 6),
                                      input_nnz_fraction=layer["nonzero_fraction"],
                                      in_stall=int(layer["in_stall"]),
                                      out_stall=int(layer["out_stall"])))
                totals[model]["predicted"] += predicted
                totals[model]["physical"] += observed
                if 2 <= i <= 9:
                    totals[model]["inner_predicted"] += predicted
                    totals[model]["inner_physical"] += observed
            if totals[model]["physical"] != summary["repeat_rows"][0][
                    "baseline" if model == "original" else model]:
                raise ValueError("rep_01 physical sum differs from triplet summary: " + model)
        for row in summary["repeat_rows"]:
            for model, key in (("original","baseline"),("frozen","frozen"),("multistart","multistart")):
                if row["in_stall"][model] < 0 or row["out_stall"][model] < 0:
                    raise ValueError("Negative DMA stall counts")
                if model == "original" and row[key] <= 0:
                    raise ValueError("Invalid physical original baseline")
                if row.get("conv2to9_" + model) != totals[model]["inner_physical"]:
                    raise ValueError("Physical Conv2–9 differed across repeats; inspect full raw logs")
        old_pred = totals["original"]["predicted"]
        new_pred = totals["multistart"]["predicted"]
        old_real = totals["original"]["physical"]
        new_real = totals["multistart"]["physical"]
        return dict(
            status="OFFLINE_PHYSICAL_W4_MECHANISM_MATCH",
            bitstream_sha256=summary["physical_bitstream_sha256"],
            input="Set12 05.png, sigma25, seed0",
            rep_01_zip_sha256=sha256_bytes(zip_path.read_bytes()),
            triplet_summary_sha256=sha256_bytes(summary_path.read_bytes()),
            raw_zip_member_crc="PASS",
            png_byte_identical_across_three_models=True,
            hidden_featuremaps_channel_permutation_equivalent_9_of_9=True,
            first_rep_physical_layer_oracle_passes=30,
            repeat_summary_rows=3,
            repeats_2_and_3_raw_zip_provided=False,
            models=totals,
            modeled_saved_cycles=old_pred-new_pred,
            physical_saved_cycles=old_real-new_real,
            savings_delta_cycles=(old_real-new_real)-(old_pred-new_pred),
            layer_rows=per_layer,
            claim_limits=[
                "Three repeats of same image; not three independent input observations.",
                "Only rep_01 raw logs were provided for independent verification.",
                "Measured core cycles, not PS end-to-end or energy.",
                "A/B/C optimizer fairness and other networks are still separate research questions.",
            ],
        )


def selftest():
    a = np.zeros((4, 4, 4), dtype=np.uint8)
    a[0, 0, 0] = 7
    x = im2col_3x3(a)
    assert x.shape == (16, 36)
    assert int(np.count_nonzero(x[0])) == 1
    pred, mb, fl = window_cost(x, 32)
    assert pred == 32 * 16
    assert fl == 100.0
    q = np.arange(3*2*2, dtype=np.uint8).reshape(3,2,2)
    assert channel_multiset(q) == channel_multiset(q[[2,0,1]])
    assert channel_multiset(q) != channel_multiset(q+1)
    print("PASS: offline 3x3 im2col, W4 cycle floor, channel-permutation signatures")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--triplet", type=Path)
    ap.add_argument("--zip", type=Path)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "build" / "q1_physical_mechanism_replay" / "trial_01")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    if a.triplet is None or a.zip is None:
        ap.error("--triplet and --zip required")
    if a.out.exists():
        ap.error("Refusing to overwrite existing mechanism audit output")
    result = analyze(a.triplet, a.zip)
    a.out.mkdir(parents=True)
    (a.out / "audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with (a.out / "layers.csv").open("w", newline="", encoding="utf-8") as f:
        rows = result["layer_rows"]
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    text = [
        "# Offline analysis of physical W4 channel-permutation mechanism", "",
        "Actual physical 50MHz core cycles, NOT PS end-to-end latency.",
        "Using captured 3x3 activations from rep_01, with bank load max NNZ.", "",
        "| Model | Predicted cycles | Physical cycles | Residual |",
        "|---|---:|---:|---:|",
    ]
    for model, d in result["models"].items():
        text.append(f"| {model} | {d['predicted']:,} | {d['physical']:,} | {d['physical']-d['predicted']:+,} |")
    text += ["",
             f"Predicted reduction: **{result['modeled_saved_cycles']:,} cycles**.",
             f"Measured reduction: **{result['physical_saved_cycles']:,} cycles**.",
             f"Residual difference in predicted vs measured reduction: **{result['savings_delta_cycles']:+,} cycles**.",
             "Intermediate uint8 channel multisets and final PNG bytes are identical after channel permutation.",
             "This audit independently verifies rep_01 only; repeats 2/3 have summary values, not raw logs.",
             ""]
    (a.out / "audit.md").write_text("\n".join(text), encoding="utf-8")
    print("PASS: physical-vs-model savings delta cycles", result["savings_delta_cycles"])
    for name in ("audit.json","audit.md","layers.csv"):
        print("Saved:", a.out / name)


if __name__ == "__main__":
    main()
