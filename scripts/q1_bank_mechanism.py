"""Mechanism audit: WHY channel-bank rearrangement saves modeled core cycles.

Compute original/frozen/multistart W4 sparse core cycle estimates on each
3x3 activation window, and attribute the changes to bottlenecked windows.

Reports:
- issue-bound vs feed/output-floor-bound windows, per layer and sigma,
- bank maximum nonzero tap counts by layout,
- unattainable per-window relaxed oracle bound (split taps optimally),
- measured *model* headroom; no FPGA, PS, DDR or JTAG timing.

The relaxed oracle deliberately ignores static channel grouping and cannot be
deployed. It is an optimistic analytical bound, not a new scheduler.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))
from common import QMAX_A,load_set,test_noise
from run_denoise import load_layers
from q1_reviewer_bank import create_runner

MODEL="dn_d10_c32_us_fx_qat"
SRC=ROOT/"denoise"/"export"/MODEL
FROZEN=ROOT/"build"/"q1_reviewer_bank"/"report.json"
MULTI=ROOT/"research"/"q1_codesign"/"multistart_export_20261018.json"
FIELDS=["sigma","noise_seed","image","layer","windows","K","COUT","feed_or_output_floor",
        "identity_cycles","frozen_cycles","multi_cycles","relaxed_oracle_lower_cycles",
        "identity_floor_bound_windows","frozen_floor_bound_windows","multi_floor_bound_windows",
        "identity_mean_max_bank","frozen_mean_max_bank","multi_mean_max_bank",
        "identity_mean_nonzero_taps","frozen_potential_saved_pct","multi_potential_saved_pct"]


def groups_from_reports():
    fixed=json.loads(FROZEN.read_text(encoding="utf-8"))
    multi=json.loads(MULTI.read_text(encoding="utf-8"))
    if fixed["model"]!=MODEL or multi["model"]!=MODEL:
        raise ValueError("Wrong QAT model")
    d={}
    for name,report in (("frozen",fixed),("multi",multi)):
        d[name]={entry["layer"]:np.asarray(entry["group_of_original_channel"],dtype=np.int64)
                 for entry in report["layers"]}
        for layer,g in d[name].items():
            if len(g)!=32 or sorted(np.bincount(g,minlength=4).tolist())!=[8]*4:
                raise AssertionError(f"Invalid grouping {name} {layer}")
    if set(d["frozen"])!=set(d["multi"]) or set(d["frozen"])!={f"conv{i}" for i in range(2,10)}:
        raise ValueError("Mismatch of target conv2-9 layers")
    return d


def cost_and_banks(count,cout,k,group):
    n=count.shape[1]
    banks=np.stack([count[:,group==i].sum(axis=1,dtype=np.int32) for i in range(4)],axis=1)
    maxbank=banks.max(axis=1)
    floor=max((k+3)//4+1,cout)
    issue=((cout+15)//16)*np.maximum(1,maxbank)
    cost=np.maximum(issue,floor)
    bound=(issue<=floor)
    return cost,maxbank,bound


def evaluate_image(counts,layers,groups,sigma,noise_seed,image):
    rows=[]
    for l in layers:
        lname=l["name"]
        if lname not in counts:continue
        data=counts[lname]
        k=int(l["K"]);cout=int(l["COUT"])
        n=data.shape[1]
        identity=np.arange(n)%4
        floor=max((k+3)//4+1,cout)
        costs={}
        maxbanks={}
        floors={}
        for variant,g in (("identity",identity),("frozen",groups["frozen"][lname]),("multi",groups["multi"][lname])):
            cost,maximum,floor_bound=cost_and_banks(data,cout,k,g)
            costs[variant]=int(np.sum(cost,dtype=np.int64))
            maxbanks[variant]=float(maximum.mean())
            floors[variant]=int(floor_bound.sum())
        # Lower bound optimistically reassigns individual taps separately,
        # even between input channels, FOR EACH WINDOW (NOT a deployable layout).
        total=data.sum(axis=1,dtype=np.int32)
        relaxed=np.maximum(floor,((cout+15)//16)*np.maximum(1,(total+3)//4))
        lower=int(relaxed.sum(dtype=np.int64))
        if lower>min(costs.values()):
            raise AssertionError("Non-deployable relaxed bound violated")
        ref=costs["identity"]
        rows.append(dict(
            sigma=sigma,noise_seed=noise_seed,image=image,layer=lname,windows=len(data),K=k,
            COUT=cout,feed_or_output_floor=floor,
            identity_cycles=ref,frozen_cycles=costs["frozen"],multi_cycles=costs["multi"],
            relaxed_oracle_lower_cycles=lower,
            identity_floor_bound_windows=floors["identity"],
            frozen_floor_bound_windows=floors["frozen"],
            multi_floor_bound_windows=floors["multi"],
            identity_mean_max_bank=round(maxbanks["identity"],6),
            frozen_mean_max_bank=round(maxbanks["frozen"],6),
            multi_mean_max_bank=round(maxbanks["multi"],6),
            identity_mean_nonzero_taps=round(float(total.mean()),6),
            frozen_potential_saved_pct=round(100*(ref-costs["frozen"])/ref,6),
            multi_potential_saved_pct=round(100*(ref-costs["multi"])/ref,6)
        ))
    if len(rows)!=8:raise AssertionError(f"Expected eight modeled conv layers, got {len(rows)}")
    return rows


def completed(path):
    if not path.is_file():return set()
    grouped=defaultdict(set)
    with path.open("r",newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k=(int(r["sigma"]),int(r["noise_seed"]),r["image"])
            lname=r["layer"]
            if lname in grouped[k]:raise AssertionError(f"Duplicate layer {k}/{lname}")
            grouped[k].add(lname)
    for k,v in grouped.items():
        if v!={f"conv{i}" for i in range(2,10)}:
            raise AssertionError(f"Incomplete image group {k}. Repair CSV before restarting.")
    return set(grouped)


def summarize(args):
    csvpath=args.out/"per_image_layer.csv"
    if not csvpath.exists():return
    groups=defaultdict(list)
    unique=set()
    with csvpath.open("r",newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            groups[(int(row["sigma"]),row["layer"])].append(row)
            unique.add((int(row["sigma"]),int(row["noise_seed"]),row["image"]))
    rows=[]
    for (sigma,layer),entries in sorted(groups.items()):
        n=sum(int(x["windows"]) for x in entries)
        ref=sum(int(x["identity_cycles"]) for x in entries)
        fr=sum(int(x["frozen_cycles"]) for x in entries)
        mu=sum(int(x["multi_cycles"]) for x in entries)
        ideal=sum(int(x["relaxed_oracle_lower_cycles"]) for x in entries)
        rows.append(dict(
            sigma=sigma,layer=layer,image_conditions=len(entries),windows=n,
            baseline_cycles=ref,
            frozen_estimated_reduction_pct=round(100*(ref-fr)/ref,6),
            multistart_estimated_reduction_pct=round(100*(ref-mu)/ref,6),
            relaxed_max_possible_reduction_pct=round(100*(ref-ideal)/ref,6),
            baseline_floor_limited_window_pct=round(
                100*sum(int(x["identity_floor_bound_windows"]) for x in entries)/n,6),
            frozen_floor_limited_window_pct=round(
                100*sum(int(x["frozen_floor_bound_windows"]) for x in entries)/n,6),
            multistart_floor_limited_window_pct=round(
                100*sum(int(x["multi_floor_bound_windows"]) for x in entries)/n,6),
            original_mean_max_bank=round(sum(float(x["identity_mean_max_bank"])*int(x["windows"])
                                             for x in entries)/n,6),
            frozen_mean_max_bank=round(sum(float(x["frozen_mean_max_bank"])*int(x["windows"])
                                           for x in entries)/n,6),
            multistart_mean_max_bank=round(sum(float(x["multi_mean_max_bank"])*int(x["windows"])
                                               for x in entries)/n,6)
        ))
    with (args.out/"sigma_layer_bottlenecks.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    expected=(args.max_images or 68)*9
    result=dict(
        complete=len(unique)==expected,
        image_conditions=len(unique),
        expected_image_conditions=expected,
        layer_condition_groups=len(rows),
        core_model="W4 sparse analytical window coefficients; not physical FPGA",
        data=rows,
        ceiling_note=("Relaxed oracle bound allows per-window tap reassignment across banks; "
                      "it is infeasible for fixed channel mapping and gives an optimistic headroom bound."),
        claim_limits=[
            "No physical bitstream/core ID, DMA stall, PS/DDR, wall-clock, end-to-end or energy measurements.",
            "All 9 noise-realization/strength conditions share the same 68 BSD68 images.",
            "Frozen and multistart use previously fixed mappings; no evaluation-time optimization.",
            "Floor-dominated windows have no opportunity to benefit from channel permutation.",
            "The optimistic bound is a mathematical relaxation, not an implementable FPGA scheduler."
        ])
    (args.out/"summary.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print("Mechanism audit complete:",result["complete"],"conditions",len(unique),
          "report",args.out/"summary.json",flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sigmas",default="15,25,50")
    ap.add_argument("--seeds",default="0,1,2")
    ap.add_argument("--max-images",type=int,default=0)
    ap.add_argument("--device",choices=["auto","cpu","cuda"],default="auto")
    ap.add_argument("--out",type=Path,default=ROOT/"build"/"q1_gpu_bank_mechanism")
    args=ap.parse_args()
    sigmas=[int(s) for s in args.sigmas.split(",") if s.strip()]
    seeds=[int(s) for s in args.seeds.split(",") if s.strip()]
    if sigmas!=[15,25,50] or seeds!=[0,1,2]:
        ap.error("Controlled sigma/noise-seed protocol requires 15,25,50 and 0,1,2")
    if args.max_images<0 or args.max_images>68:ap.error("max-images must be 0..68")
    groups=groups_from_reports()
    args.out.mkdir(parents=True,exist_ok=True)
    conf=dict(model=MODEL,sigmas=sigmas,seeds=seeds,
              max_images=args.max_images,
              frozen_sha256=hashlib.sha256(FROZEN.read_bytes()).hexdigest(),
              multistart_sha256=hashlib.sha256(MULTI.read_bytes()).hexdigest())
    cf=args.out/"run_config.json"
    if cf.is_file() and json.loads(cf.read_text(encoding="utf-8"))!=conf:
        ap.error("Cannot resume with changed settings or mappings; choose another --out")
    cf.write_text(json.dumps(conf,indent=2)+"\n",encoding="utf-8")
    from torch import cuda,no_grad
    device=("cuda" if cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if device=="cuda" and not cuda.is_available():ap.error("CUDA unavailable")
    manifest,layers=load_layers(SRC)
    if len(layers)!=10:raise AssertionError("Unexpected CNN layer count")
    run=create_runner(layers,device)
    data=load_set("BSD68")
    if len(data)!=68:raise ValueError("BSD68 68 images needed")
    path=args.out/"per_image_layer.csv"
    done=completed(path)
    for sigma in sigmas:
        for seed in seeds:
            for i,(name,clean,noisy) in enumerate(test_noise(data,sigma,seed=seed)):
                if args.max_images and i>=args.max_images: break
                if (sigma,seed,name) in done:continue
                q=np.rint(noisy*QMAX_A).astype(np.uint8)
                with no_grad(): counts,_=run(q)
                records=evaluate_image(counts,layers,groups,sigma,seed,name)
                with path.open("a",newline="",encoding="utf-8") as f:
                    writer=csv.DictWriter(f,fieldnames=FIELDS)
                    if f.tell()==0:writer.writeheader()
                    writer.writerows(records)
                print(f"{name} sigma={sigma} seed={seed}: bank bottleneck/floor analysed",flush=True)
    summarize(args)


if __name__=="__main__":
    main()
