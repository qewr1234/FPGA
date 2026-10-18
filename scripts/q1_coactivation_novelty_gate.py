"""OFFLINE Q1 novelty gate from physical trial_01.zip.

A: A fixed-channel-permutation coactivation-null test: independently permute the
rows of every channel's 3x3 NNZ count series. Each per-channel NNZ histogram is
identical, but cross-channel co-activation is altered.
B: A matched 401-evaluation greedy search on TRUE vs SHUFFLED calibration rows.
Both start from the same identity layout and use exactly the same optimizer seed.
Train on top half, score on bottom half of the SAME Set12 05 image.

WARNING: exploratory one-image SPATIAL holdout, not independent test images;
computed W4 cycle model only for null/optimizer results, NOT physical FPGA
measurement of shuffled data. The already measured 7.605% real FPGA figure
must not be confused with simulated outcomes here.

Run:
  python scripts/q1_coactivation_novelty_gate.py --trial-zip X:\trial_01.zip
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL = "dn_d10_c32_us_fx_qat"
FROZEN_ZIP = ROOT / "research/q1_codesign/artifacts/q1_bank_reordered_export_20261018.zip"
MULTI_MAP = ROOT / "research/q1_codesign/multistart_export_20261018.json"


def counts(q):
    if q.dtype != np.uint8 or q.shape != (32, 128, 128):
        raise ValueError("Expected uint8 32x128x128 hidden map")
    padded = np.pad(q != 0, ((0, 0), (1, 1), (1, 1)))
    z = np.zeros(q.shape, dtype=np.uint8)
    for y in range(3):
        for x in range(3):
            z += padded[:, y:y+128, x:x+128]
    return z.transpose(1, 2, 0)  # spatial row, spatial column, input channel


def check_group(group):
    g = np.asarray(group, dtype=np.int64)
    if g.shape != (32,) or not np.array_equal(np.bincount(g, minlength=4), [8,8,8,8]):
        raise ValueError("Expected balanced 4x8 channel-to-bank assignment")
    return g


def group_from_order(order):
    order = np.asarray(order, dtype=np.int64)
    if sorted(order.tolist()) != list(range(32)):
        raise ValueError("Invalid predecessor output-channel order")
    group = np.empty(32, dtype=np.int64)
    group[order] = np.arange(32) % 4
    return check_group(group)


def core_cycles(c, group):
    g = check_group(group)
    bank = np.stack([c[:,g == k].sum(axis=1, dtype=np.int16) for k in range(4)], axis=1)
    return int(np.maximum(73, 2*np.maximum(1, bank.max(axis=1))).sum(dtype=np.int64))


def scramble(c, rng):
    result = np.empty_like(c)
    for k in range(32):
        result[:,k] = c[rng.permutation(len(c)),k]
    return result


def greedy(table, seed, budget):
    # Exactly 1 initial objective + budget-1 candidate objectives.
    if budget < 2:
        raise ValueError("Budget must be >=2")
    rng = np.random.default_rng(seed)
    group = np.arange(32) % 4
    best = core_cycles(table,group)
    for _ in range(budget-1):
        a = int(rng.integers(0,32))
        options = np.flatnonzero(group != group[a])
        b = int(options[int(rng.integers(0,len(options)))])
        group[a],group[b] = group[b],group[a]
        candidate = core_cycles(table,group)
        if candidate < best: best = candidate
        else: group[a],group[b] = group[b],group[a]
    return group


def selftest():
    a = np.zeros((32,128,128), dtype=np.uint8)
    a[0,0,0] = 3
    x = counts(a).reshape(-1,32)
    assert x.shape == (16384,32)
    assert np.count_nonzero(x[:,0]) == 4
    g = np.arange(32)%4
    assert core_cycles(x,g) == 16384*73
    rng = np.random.default_rng(23)
    shuffled = scramble(x,rng)
    assert np.array_equal(np.sort(x,axis=0),np.sort(shuffled,axis=0))
    order = np.arange(32)[::-1]
    assert np.array_equal(np.bincount(group_from_order(order)), [8,8,8,8])
    assert np.array_equal(np.bincount(greedy(x,42,3)), [8,8,8,8])
    print("PASS offline: 3x3 NNZ, floor cost, balanced permutations, marginal-preserving shuffle")


def save_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial-zip",type=Path)
    parser.add_argument("--out",type=Path,default=ROOT/"build/q1_novelty_coactivation_gate")
    parser.add_argument("--null-draws",type=int,default=20)
    parser.add_argument("--budget",type=int,default=401)
    parser.add_argument("--seeds",default="10000,10001,10002,10003")
    parser.add_argument("--selftest",action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.trial_zip:
        parser.error("Provide physical trial_01.zip with --trial-zip")
    if args.out.exists():
        parser.error("Refusing overwrite: choose new --out")
    if args.null_draws<2 or args.budget<2:
        parser.error("null-draws>=2 and budget>=2 required")
    seeds = [int(s) for s in args.seeds.split(",")]
    if len(seeds)!=len(set(seeds)) or not seeds:
        parser.error("Use distinct optimizer seeds")
    with zipfile.ZipFile(args.trial_zip) as z:
        if z.testzip():
            raise ValueError("Physical trial ZIP has a CRC error")
        m = np.load(io.BytesIO(z.read("trial_01/rep_01/original/05_maps10.npz")),allow_pickle=False)
        report = json.loads(z.read("trial_01/rep_01/original/report.json"))
    if (report.get("emulated") is not False or report.get("model") != MODEL
            or report["images"][0]["image"] != "05.png"):
        raise ValueError("Expected actual Original W4 Set12 05 board capture")
    with zipfile.ZipFile(FROZEN_ZIP) as z:
        if z.testzip(): raise ValueError("Frozen zip CRC error")
        frozen = json.loads(z.read(MODEL + "/permutation_manifest.json"))["orders"]
    multi = {
        e["layer"]:check_group(e["group_of_original_channel"])
        for e in json.loads(MULTI_MAP.read_text(encoding="utf-8"))["layers"]
    }
    rng = np.random.default_rng(20261018)
    natural_sum = np.zeros(3,dtype=np.int64)
    null_sum = np.zeros((args.null_draws,3),dtype=np.int64)
    layer_rows, search_rows = [],[]
    seed_total = {s:dict(original=0,joint=0,marginal=0) for s in seeds}
    for idx in range(2,10):
        name=f"conv{idx}"
        tensor = counts(m[f"conv{idx-1}"])
        x = tensor.reshape(-1,32)
        groups = [np.arange(32)%4,
                  group_from_order(frozen[f"conv{idx-1}"]),
                  multi[name]]
        actual = np.asarray([core_cycles(x,g) for g in groups])
        natural_sum += actual
        sims = np.zeros((args.null_draws,3),dtype=np.int64)
        for k in range(args.null_draws):
            shuffled = scramble(x,rng)
            sims[k] = [core_cycles(shuffled,g) for g in groups]
        null_sum += sims
        actual_gain=100*(actual[0]-actual[2])/actual[0]
        sims_gain=100*(sims[:,0]-sims[:,2])/sims[:,0]
        layer_rows.append(dict(layer=name,actual_multi_pct=float(actual_gain),
                               scrambled_multi_mean_pct=float(sims_gain.mean()),
                               scrambled_q025_pct=float(np.quantile(sims_gain,.025)),
                               scrambled_q975_pct=float(np.quantile(sims_gain,.975)),
                               coactivation_gap_pp=float(actual_gain-sims_gain.mean())))
        # Intentional top-half vs bottom-half SPATIAL split, same image.
        # Training and scoring windows never overlap.
        top=tensor[:64].reshape(-1,32)
        bottom=tensor[64:].reshape(-1,32)
        ix=np.random.default_rng(45000+idx).choice(len(top),size=1024,replace=False)
        train=top[ix]
        marginal_train=scramble(train,np.random.default_rng(83000+idx))
        baseline=core_cycles(bottom,groups[0])
        for seed in seeds:
            joint=greedy(train,seed+20*idx,args.budget)
            independent=greedy(marginal_train,seed+20*idx,args.budget)
            jj=core_cycles(bottom,joint)
            mm=core_cycles(bottom,independent)
            seed_total[seed]["original"]+=baseline
            seed_total[seed]["joint"]+=jj
            seed_total[seed]["marginal"]+=mm
            search_rows.append(dict(layer=name,seed=seed,budget=args.budget,
                                    actual_calibration_windows=1024,eval_windows=8192,
                                    baseline_cycles=baseline,joint_cycles=jj,marginal_cycles=mm,
                                    joint_saved_pct=100*(baseline-jj)/baseline,
                                    marginal_saved_pct=100*(baseline-mm)/baseline))
        print(f"{name}: actual {actual_gain:.3f}%, marginal-shuffled null {sims_gain.mean():.3f}%",flush=True)
    actual_pct=100*(natural_sum[0]-natural_sum[2])/natural_sum[0]
    null_pct=100*(null_sum[:,0]-null_sum[:,2])/null_sum[:,0]
    seed_rows=[]
    for seed,data in seed_total.items():
        orig=data["original"]
        seed_rows.append(dict(seed=seed,budget=args.budget,
                              joint_saved_pct=100*(orig-data["joint"])/orig,
                              marginal_saved_pct=100*(orig-data["marginal"])/orig,
                              joint_minus_marginal_pp=100*(data["marginal"]-data["joint"])/orig))
    result=dict(
        status="EXPLORATORY_ONE_IMAGE_COACTIVATION_NOVELTY",
        source_trial_zip_sha256=hashlib.sha256(args.trial_zip.read_bytes()).hexdigest(),
        fixed_permutation=dict(observed_multi_conv2to9_pct=float(actual_pct),
                               shuffled_null_mean_pct=float(null_pct.mean()),
                               difference_pp=float(actual_pct-null_pct.mean()),
                               null_draws=args.null_draws),
        matched_budget_spatial=dict(objective_evaluations=args.budget,seeds=seeds,
                                    joint_avg_pct=float(np.mean([r["joint_saved_pct"] for r in seed_rows])),
                                    marginal_avg_pct=float(np.mean([r["marginal_saved_pct"] for r in seed_rows])),
                                    seed_rows=seed_rows),
        limits=["One Set12 05.png already tested on FPGA; this is exploratory, not independent BSD68 holdout.",
                "Randomized NNZ sequences were NOT rerun on FPGA; cost-model proxy only.",
                "Each channel's NNZ histogram preserved; each window's total may change.",
                "Top/bottom portions are spatially dependent. Do not infer dataset-level confidence intervals.",
                "Equal objective evaluation count, not necessarily equal runtime or universally optimal policies."],
        layer_rows=layer_rows)
    args.out.mkdir(parents=True)
    (args.out/"summary.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    save_csv(args.out/"null_layers.csv",layer_rows)
    save_csv(args.out/"matched_budget_spatial.csv",search_rows)
    save_csv(args.out/"matched_budget_seeds.csv",seed_rows)
    print(f"FIXED: {actual_pct:.4f}% real joint versus {null_pct.mean():.4f}% null")
    print(f"FIT: {result['matched_budget_spatial']['joint_avg_pct']:.4f}% joint versus "
          f"{result['matched_budget_spatial']['marginal_avg_pct']:.4f}% marginal")
    print("Saved:",args.out.resolve())


if __name__ == "__main__":
    main()
