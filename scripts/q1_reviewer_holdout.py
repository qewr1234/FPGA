"""Frozen bank-permutation evaluation on BSD68: no tuning on test images.

Depends on the exploratory selector q1_reviewer_bank.py and existing
denoise/export/<model> (original integer model). No FPGA or Vivado.

This is a fixed *core-cycle proxy* evaluation, not a measured board speedup.
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))
from common import QMAX_A,load_set,psnr,test_noise
from run_denoise import load_layers
from q1_reviewer_bank import create_runner,cycles


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",default="dn_d10_c32_us_fx_qat")
    ap.add_argument("--report",type=Path,default=ROOT/"build"/"q1_reviewer_bank"/"report.json")
    ap.add_argument("--set",default="BSD68",choices=("BSD68","Set12"))
    ap.add_argument("--device",default="auto",choices=("auto","cpu","cuda"))
    ap.add_argument("--out",type=Path,default=ROOT/"build"/"q1_reviewer_holdout")
    args=ap.parse_args()
    frozen=json.loads(args.report.read_text(encoding="utf-8"))
    src=ROOT/"denoise"/"export"/args.model
    man,layers=load_layers(src)
    if frozen["model"]!=args.model:
        ap.error("Report model differs from requested model")
    if args.set==frozen["data_set"]:
        overlap=set(frozen["calib_images"]) & {n for n,_,_ in test_noise(load_set(args.set),man["sigma"],seed=0)}
        if overlap:
            ap.error("HOLDOUT INVALID: set includes the calibration images "+str(sorted(overlap)))
    import torch
    dev=("cuda" if torch.cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if dev=="cuda" and not torch.cuda.is_available():ap.error("CUDA is unavailable")
    run=create_runner(layers,dev)
    by_name={l["layer"]:l for l in frozen["layers"]}
    for l in frozen["layers"]:
        g=np.asarray(l["group_of_original_channel"],dtype=np.int64)
        order=np.asarray(l["original_channel_order"],dtype=np.int64)
        if len(g)!=32 or len(order)!=32 or sorted(order.tolist())!=list(range(32)):
            raise AssertionError(f"{l['layer']}: bad frozen permutation")
        if not np.array_equal(g[order],np.arange(32)%4):
            raise AssertionError(f"{l['layer']}: channel order/group inconsistency")
        if not np.array_equal(np.bincount(g,minlength=4),np.full(4,8)):
            raise AssertionError(f"{l['layer']}: unbalanced bank group capacity")

    int_eval=json.loads((src/"int_eval.json").read_text(encoding="utf-8"))
    tests=test_noise(load_set(args.set),man["sigma"],seed=0)
    expected_len=68 if args.set=="BSD68" else 12
    if len(tests)!=expected_len:
        raise AssertionError(f"{args.set}: expected {expected_len} images, found {len(tests)}")
    rows=[]
    for name,clean,noisy in tests:
        q=np.rint(noisy*QMAX_A).astype(np.uint8)
        counts,out=run(q)
        measured_psnr=float(psnr(clean,out.astype(np.float32)/255.0))
        original_psnr=float(int_eval[args.set]["per_image"][name])
        if abs(measured_psnr-original_psnr)>1e-5:
            raise AssertionError(f"{name}: integer oracle PSNR drift {measured_psnr-original_psnr}")
        old_total=new_total=0
        for layer in layers:
            lname=layer["name"]
            if lname not in by_name: continue
            count=counts[lname]
            row=by_name[lname]
            old_group=np.arange(count.shape[1])%4
            new_group=np.asarray(row["group_of_original_channel"],dtype=np.int64)
            orig=int(cycles(count,layer["COUT"],layer["K"],old_group).sum())
            prop=int(cycles(count,layer["COUT"],layer["K"],new_group).sum())
            old_total+=orig;new_total+=prop
        rows.append(dict(
            image=name,psnr_db=round(measured_psnr,7),
            identity_cycles=old_total,optimized_cycles=new_total,
            saved_cycles=old_total-new_total,
            saved_pct=round(100*(old_total-new_total)/old_total,6)))
        print(f"{name}: {rows[-1]['saved_pct']:+.3f}% fewer W=4 core-cycle coefficients "
              f"({rows[-1]['saved_cycles']:,} saved); PSNR={measured_psnr:.5f} dB",flush=True)
    base=sum(r["identity_cycles"] for r in rows)
    opt=sum(r["optimized_cycles"] for r in rows)
    savings=np.asarray([r["saved_cycles"] for r in rows],dtype=np.float64)
    baseline=np.asarray([r["identity_cycles"] for r in rows],dtype=np.float64)
    rng=np.random.default_rng(20261018)
    # Paired image bootstrap, estimates across-image sampling variability only.
    boot=[]
    for _ in range(2000):
        ind=rng.integers(0,len(rows),size=len(rows))
        boot.append(100*savings[ind].sum()/baseline[ind].sum())
    ci=np.percentile(boot,[2.5,97.5])
    out=dict(
        status="FIXED_PERMUTATION_NO_RETUNING",model=args.model,
        training_report=str(args.report),data_set=args.set,
        image_count=len(rows),noise_seed=0,sigma=man["sigma"],
        frozen_training_images=frozen["calib_images"],
        identity_layer_cycles=base,optimized_layer_cycles=opt,
        estimated_layer_cycle_reduction_pct=round(100*(base-opt)/base,6),
        per_image_positive=int(sum(r["saved_cycles"]>0 for r in rows)),
        per_image_zero=int(sum(r["saved_cycles"]==0 for r in rows)),
        per_image_negative=int(sum(r["saved_cycles"]<0 for r in rows)),
        descriptive_image_bootstrap_ci95_pct=[round(float(x),4) for x in ci],
        warnings=[
            "Core window-coefficient model only; layer fill/drain, CPU, DMA, DDR, "
            "board clocks and genuine end-to-end latency are not included.",
            "Calibration permutation was frozen from prior Set12 01.png."
            " No permutation fitting uses BSD68 samples.",
            "Historical Denoising model itself may have been tuned against BSD68;"
            " thus this is independent of permutation selection, not necessarily "
            "independent of all model-selection decisions.",
            "PSNR checked against original integer evaluation to within 1e-5 dB;"
            " full pixel-level equivalence on all images needs separate oracle runs.",
            "Bootstrap CI describes variation across the available test images,"
            " not multiple random seeds or a formal population guarantee."
        ],rows_file="per_image.csv")
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/"per_image.csv").open("w",newline="",encoding="utf-8") as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
        wr.writeheader();wr.writerows(rows)
    (args.out/"report.json").write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",
                                          encoding="utf-8")
    print("\n=== HOLDOUT SUMMARY ===")
    print(f"Images: {len(rows)}; improved: {out['per_image_positive']} | "
          f"unchanged: {out['per_image_zero']} | worsened: {out['per_image_negative']}")
    print("Frozen arrangement: %.4f%% cycle reduction; image-bootstrap CI 95%% [%.3f, %.3f]" %
          (out["estimated_layer_cycle_reduction_pct"],ci[0],ci[1]))
    print("Result:",(args.out/"report.json").resolve())
    print("NO actual FPGA speedup or Q1-level novelty has been demonstrated.")


if __name__=="__main__":
    main()
