"""Deadline GPU research suite: fixed and newly calibrated channel-bank scheduling.

Primary evidence remains the frozen Set12-01 calibration + BSD68 68/68 result.
New competitors are calibrated ONLY on Set12 01/02/03, never on BSD68.
Runs all BSD68 images at multiple AWGN sigma and seed values, compares:
  identity, frozen_01, density_sort, greedy, anneal, multistart_greedy,
  risk_aware_greedy, 20 fixed random balanced bank assignments.
Computes paired image-cluster bootstrap intervals, detailed per-condition
summaries, and produces export-ready manifests for all deterministic methods.

Uses the REAL INT8 QAT CNN inference and activation maps. NO FPGA/DDR timing,
RTL, QAT retraining or externally verified methodological novelty is claimed.

Default workload: 3 sigmas x 3 noise realizations x 68 BSD68 images.
Run time depends on RTX 4060 Ti performance. Interrupt/restart is resumable.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))
from common import QMAX_A, load_set, psnr, test_noise
from run_denoise import load_layers
from q1_reviewer_bank import create_runner, cycles

MODEL="dn_d10_c32_us_fx_qat"
DETERMINISTIC=["identity","frozen_01","density_sort","greedy",
               "anneal","multistart_greedy","risk_aware_greedy"]
METHODS=DETERMINISTIC+["random_mean","random_best_reference"]
# DO NOT interpret random_best_reference as a deployable strategy: it selects
# by evaluation data and is reported only as an optimistic negative control.
COLS=["dataset","sigma","noise_seed","image","psnr_db",
      "method","baseline_cycles","method_cycles","saved_cycles",
      "saved_pct","layers","pixel_mismatch_frozen"]


def parse_ints(s):
    vals=tuple(int(i.strip()) for i in s.split(",") if i.strip())
    if not vals or any(i<0 for i in vals) or len(set(vals))!=len(vals):
        raise ValueError("seed lists must be distinct nonnegative integers")
    return vals


def parse_sigmas(s):
    vals=tuple(int(i.strip()) for i in s.split(",") if i.strip())
    if not vals or any(i<=0 for i in vals) or len(set(vals))!=len(vals):
        raise ValueError("sigma values must be distinct positive integers")
    return vals


def balanced_random(n, seed):
    rng=np.random.default_rng(seed)
    perm=rng.permutation(n)
    group=np.empty(n,dtype=np.int64)
    group[perm]=np.arange(n)%4
    return group


def grouped_loss(c, cout, k, group, mode="mean"):
    predicted=cycles(c,cout,k,group)
    x=float(predicted.mean())
    if mode=="risk":
        x+=0.25*float(np.quantile(predicted,0.90))
    return x


def optimize(c,cout,k,seed,steps,start=None,anneal=False,mode="mean"):
    rng=np.random.default_rng(seed)
    n=c.shape[1]
    g=(np.arange(n)%4 if start is None else start).astype(np.int64,copy=True)
    if np.bincount(g,minlength=4).tolist()!=[n//4]*4:
        raise AssertionError("invalid initial 4-bank grouping")
    current=grouped_loss(c,cout,k,g,mode)
    best_g=g.copy()
    best=current
    for i in range(steps):
        p=int(rng.integers(n))
        q_candidates=np.flatnonzero(g!=g[p])
        q=int(q_candidates[int(rng.integers(len(q_candidates)))])
        g[p],g[q]=g[q],g[p]
        proposed=grouped_loss(c,cout,k,g,mode)
        delta=proposed-current
        temp=2.0*(0.01/2.0)**(i/max(1,steps-1))
        allow=(delta < -1e-10 or (anneal and rng.random()<math.exp(-max(0,delta)/temp)))
        if allow:
            current=proposed
            if current<best-1e-10:
                best=current
                best_g=g.copy()
        else:
            g[p],g[q]=g[q],g[p]
    return best_g,float(best)


def load_or_fit(args,man,layers,runner):
    target=Path(args.out)/"method_config.json"
    if target.exists():
        data=json.loads(target.read_text(encoding="utf-8"))
        if data.get("experiment_config")!=args.config:
            raise ValueError("Existing method_config.json has different settings. "
                             "Use a new --out for a different experiment.")
        print("Loaded existing frozen method selections; no re-optimization.",flush=True)
        return {
            name:{layer:np.asarray(group,dtype=np.int64)
                  for layer,group in per_layer.items()}
            for name,per_layer in data["group_assignments"].items()
        }

    frozen=json.loads(Path(args.frozen).read_text(encoding="utf-8"))
    if frozen["model"]!=MODEL or len(frozen["layers"])!=8:
        raise ValueError("Expected first experiment report with eight frozen layers")
    fixed={}
    for L in frozen["layers"]:
        g=np.asarray(L["group_of_original_channel"],dtype=np.int64)
        if len(g)!=32 or sorted(np.bincount(g,minlength=4).tolist())!=[8]*4:
            raise ValueError(f"Bad fixed channel mapping: {L['layer']}")
        fixed[L["layer"]]=g
    if set(fixed)!={f"conv{i}" for i in range(2,10)}:
        raise ValueError("Missing frozen layer")
    set12=test_noise(load_set("Set12"),25,seed=0)
    want=set(x.strip() for x in args.calib_images.split(",") if x.strip())
    if not want or not want.issubset({x[0] for x in set12}):
        raise ValueError("Calibration images must exist in Set12")
    samples={}
    import torch
    for seed in args.calib_seeds:
        for name,clean,noisy in test_noise(load_set("Set12"),25,seed=seed):
            if name not in want: continue
            q=np.rint(noisy*QMAX_A).astype(np.uint8)
            with torch.no_grad():
                counts,out=runner(q)
            for layer,table in counts.items():
                rng=np.random.default_rng(seed*1000+int(layer[4:]))
                ix=rng.choice(len(table),size=min(args.calib_windows,len(table)),replace=False)
                samples.setdefault(layer,[]).append(table[ix])
            print(f"Calibrated activation tables: {name} noise_seed={seed}",flush=True)
    groups={name:{} for name in DETERMINISTIC}
    groups["random_reference"]={}
    rngseed=args.seed
    rows=[]
    for j,L in enumerate(layers):
        name=L["name"]
        if name not in fixed: continue
        c=np.concatenate(samples[name],axis=0).astype(np.uint8)
        n=c.shape[1]
        identity=np.arange(n)%4
        density=np.empty(n,dtype=np.int64)
        rank=np.argsort(-c.mean(axis=0),kind="stable")
        density[rank]=np.arange(n)%4
        greed,v_g=optimize(c,L["COUT"],L["K"],rngseed+100+j,args.greedy_steps)
        anneal,v_a=optimize(c,L["COUT"],L["K"],rngseed+200+j,args.anneal_steps,anneal=True)
        mult=greed.copy()
        v_m=v_g
        for rep in range(args.restarts):
            init=balanced_random(n,rngseed+300+100*j+rep)
            candidate,val=optimize(c,L["COUT"],L["K"],
                                   rngseed+400+100*j+rep,args.greedy_steps,start=init)
            if val<v_m:
                mult,v_m=candidate,val
        risk,v_r=optimize(c,L["COUT"],L["K"],rngseed+600+j,
                          args.greedy_steps,mode="risk")
        sets={
            "identity":identity,"frozen_01":fixed[name],"density_sort":density,
            "greedy":greed,"anneal":anneal,"multistart_greedy":mult,
            "risk_aware_greedy":risk
        }
        for m,g in sets.items():
            groups[m][name]=g.copy()
            rows.append(dict(layer=name,method=m,
                             calib_cost=round(grouped_loss(c,L["COUT"],L["K"],g),6),
                             calib_windows=int(len(c))))
        # Negative-control layouts are chosen without accessing evaluation.
        groups["random_reference"][name]=[
            balanced_random(n,rngseed+10000+100*j+i) for i in range(args.random_count)]
        print(f"{name} calibrated: identity={grouped_loss(c,L['COUT'],L['K'],identity):.3f}, "
              f"frozen={grouped_loss(c,L['COUT'],L['K'],fixed[name]):.3f}, "
              f"greedy={v_g:.3f}, anneal={v_a:.3f}, multi={v_m:.3f}",flush=True)
    dest=Path(args.out)
    dest.mkdir(parents=True,exist_ok=True)
    with (dest/"calibration.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader();w.writerows(rows)
    payload={"experiment_config":args.config,"model":MODEL,
             "calibration":"Set12 fixed images only; BSD68 never used to select any model",
             "group_assignments":{
                 m:{layer:(values if m=="random_reference" else g.tolist())
                    for layer,g in maps.items()
                    for values in ([list(x.tolist() for x in g)] if m=="random_reference" else [None])}
                 for m,maps in groups.items()
             }}
    (dest/"method_config.json").write_text(
        json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    for method in DETERMINISTIC:
        if method=="identity": continue
        report={
            "model":MODEL,"source":"calibrated_set12_only",
            "layers":[{"layer":name,
                       "group_of_original_channel":groups[method][name].tolist(),
                       "original_channel_order":make_order(groups[method][name]).tolist()}
                      for name in sorted(fixed,key=lambda n:int(n[4:]))]
        }
        (dest/f"export_{method}.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return groups


def make_order(group):
    rows=[list(np.flatnonzero(group==b)) for b in range(4)]
    return np.asarray([rows[b][i] for i in range(len(rows[0])) for b in range(4)],
                      dtype=np.int64)


def read_existing(path):
    found=set()
    if path.exists():
        with path.open("r",newline="",encoding="utf-8") as f:
            for row in csv.DictReader(f):
                found.add((row["dataset"],int(row["sigma"]),int(row["noise_seed"]),row["image"],row["method"]))
    return found


def evaluate(args,man,layers,runner,groups):
    data=load_set(args.dataset)
    outfile=Path(args.out)/"per_image_methods.csv"
    existing=read_existing(outfile)
    wrote=0
    import torch
    from contextlib import nullcontext
    for sigma in args.sigmas:
        for seed in args.seeds:
            noisy_set=test_noise(data,sigma,seed=seed)
            for image_index,(name,clean,noisy) in enumerate(noisy_set):
                if args.max_images and image_index>=args.max_images: break
                complete=all((args.dataset,sigma,seed,name,m) in existing for m in METHODS)
                if complete: continue
                q=np.rint(noisy*QMAX_A).astype(np.uint8)
                with torch.no_grad():
                    counts,out=runner(q)
                value=float(psnr(clean,out.astype(np.float32)/255.0))
                cost={method:0 for method in METHODS}
                per_layer={}
                random_n=args.random_count
                rcycles=np.zeros(random_n,dtype=np.int64)
                baseline=0
                for L in layers:
                    layer=L["name"]
                    if layer not in groups["identity"]:continue
                    c=counts[layer]
                    vals={}
                    for method in DETERMINISTIC:
                        vals[method]=int(cycles(c,L["COUT"],L["K"],groups[method][layer]).sum())
                        cost[method]+=vals[method]
                    baseline+=vals["identity"]
                    for j,group in enumerate(groups["random_reference"][layer]):
                        rcycles[j]+=int(cycles(c,L["COUT"],L["K"],group).sum())
                    per_layer[layer]=vals
                cost["random_mean"]=float(np.mean(rcycles))
                cost["random_best_reference"]=float(np.min(rcycles))
                if baseline<=0:raise AssertionError("Missing core window data")
                rows=[]
                for method in METHODS:
                    if (args.dataset,sigma,seed,name,method) in existing:continue
                    mcost=cost[method]
                    rows.append(dict(dataset=args.dataset,sigma=sigma,noise_seed=seed,
                                     image=name,psnr_db=round(value,8),method=method,
                                     baseline_cycles=baseline,method_cycles=round(mcost,5),
                                     saved_cycles=round(baseline-mcost,5),
                                     saved_pct=round(100*(baseline-mcost)/baseline,6),
                                     layers=len(per_layer),pixel_mismatch_frozen="not_evaluated"))
                with outfile.open("a",newline="",encoding="utf-8") as f:
                    writer=csv.DictWriter(f,fieldnames=COLS)
                    if f.tell()==0:writer.writeheader()
                    writer.writerows(rows)
                wrote+=1
                print(f"{args.dataset} sigma={sigma:2} seed={seed} {name}: "
                      f"frozen={100*(baseline-cost['frozen_01'])/baseline:+.2f}% "
                      f"anneal={100*(baseline-cost['anneal'])/baseline:+.2f}% "
                      f"multi={100*(baseline-cost['multistart_greedy'])/baseline:+.2f}% "
                      f"PSNR={value:.3f}dB",flush=True)
    print(f"Completed {wrote} new image-condition samples; results: {outfile}",flush=True)


def summarize(args):
    file=Path(args.out)/"per_image_methods.csv"
    rows=list(csv.DictReader(file.open("r",newline="",encoding="utf-8")))
    expected_count=(args.max_images if args.max_images else (68 if args.dataset=="BSD68" else 12))
    expected=expected_count*len(args.seeds)*len(args.sigmas)*len(METHODS)
    if len(rows)!=expected:
        print(f"WARNING: results incomplete: expected {expected}, found {len(rows)}. Resume!",flush=True)
    groups={}
    for row in rows:
        key=(int(row["sigma"]),int(row["noise_seed"]),row["method"])
        groups.setdefault(key,[]).append(row)
    summaries=[]
    for (sigma,seed,method),rr in sorted(groups.items()):
        base=sum(float(r["baseline_cycles"]) for r in rr)
        opt=sum(float(r["method_cycles"]) for r in rr)
        gain=100*(base-opt)/base if base else 0.
        summaries.append(dict(sigma=sigma,seed=seed,method=method,images=len(rr),
                              mean_psnr_db=round(np.mean([float(r["psnr_db"]) for r in rr]),6),
                              estimated_core_coeff_cycle_gain_pct=round(gain,6),
                              improved=sum(float(r["saved_cycles"])>0 for r in rr),
                              worsened=sum(float(r["saved_cycles"])<0 for r in rr)))
    final=[]
    if args.dataset=="BSD68":
        for method in METHODS:
            mine=[r for r in rows if r["method"]==method]
            if not mine:continue
            imagedata={}
            for r in mine:
                name=r["image"]
                a,b=imagedata.get(name,(0.,0.))
                imagedata[name]=(a+float(r["baseline_cycles"]),b+float(r["method_cycles"]))
            # Cluster bootstrap by image across all noise conditions.
            arr=np.asarray(list(imagedata.values()),dtype=np.float64)
            frac=100*(arr[:,0].sum()-arr[:,1].sum())/arr[:,0].sum()
            if len(arr)>=2:
                rng=np.random.default_rng(20261018)
                boots=[]
                for _ in range(2000):
                    ix=rng.integers(0,len(arr),size=len(arr))
                    boots.append(100*(arr[ix,0].sum()-arr[ix,1].sum())/arr[ix,0].sum())
                ci=np.percentile(boots,[2.5,97.5]).tolist()
            else:ci=[None,None]
            final.append(dict(method=method,images=len(imagedata),
                              estimated_cycle_reduction_pct=round(float(frac),6),
                              image_cluster_bootstrap_ci95_pct=[round(float(x),5) if x is not None else None for x in ci]))
    report=dict(
        experiment_config=args.config,
        dataset=args.dataset,
        completed_image_method_rows=len(rows),
        expected_image_method_rows=expected,
        complete=bool(len(rows)==expected),
        per_condition=summaries,
        overall=final,
        analytical_controls={
            "W1_same_CNN_channel_permutation_saved_pct":0.0,
            "W4_dense_mode_channel_permutation_saved_pct":0.0,
            "explanation":"Identical K,COUT,windows and all-zero independent load/dense issue counts: channel mapping cannot improve W1 or dense-mode compute costs in this core. These are analytical controls, NOT bitstream measurements."
        },
        key_limitations=[
            "Only W4 sparse core window-cycle coefficients for Conv2-9; no DDR, DMA, PS, fill/drain or hardware/latency measurement.",
            "Calibration is Set12 01/02/03 and seed0,1 at sigma25 only; BSD68 never used to choose method.",
            "The preexisting frozen_01 uses Set12 01 seed0; all other methods are separately calibrated.",
            "The original CNN has been developed using known datasets; BSD68 is separate from permutation selection, not necessarily unvisited by overall model development.",
            "Data σ15/50 use the SAME QAT model trained at σ25; PSNR is not calibrated against original σ25 int_eval.",
            "random_best_reference takes test-set best per image and is an INVALID deployable strategy, included only as a diagnostic upper bound.",
            "Repeated seeds/images are correlated; intervals resample image identities across conditions, not all training randomness.",
            "Novelty versus sparsity-bank-channel permutation methods has NOT been established."
        ])
    out=Path(args.out)
    (out/"summary.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with (out/"per_condition.csv").open("w",newline="",encoding="utf-8") as f:
        if summaries:
            wr=csv.DictWriter(f,fieldnames=list(summaries[0]))
            wr.writeheader();wr.writerows(summaries)
    print("\n=== FULL GPU-SCREEN SUMMARY (core proxy only) ===",flush=True)
    for entry in final:
        print(f"{entry['method']:23s} {entry['estimated_cycle_reduction_pct']:+8.3f}% "
              f"CI95={entry['image_cluster_bootstrap_ci95_pct']}",flush=True)
    print(f"COMPLETE={report['complete']} | {len(rows)}/{expected} method-image rows")
    print(f"SUMMARY: {out/'summary.json'}",flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",default=MODEL)
    ap.add_argument("--dataset",choices=("BSD68","Set12"),default="BSD68")
    ap.add_argument("--sigmas",default="15,25,50")
    ap.add_argument("--seeds",default="0,1,2")
    ap.add_argument("--calib-seeds",default="0,1")
    ap.add_argument("--calib-images",default="01.png,02.png,03.png")
    ap.add_argument("--calib-windows",type=int,default=1024)
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--greedy-steps",type=int,default=400)
    ap.add_argument("--anneal-steps",type=int,default=1000)
    ap.add_argument("--restarts",type=int,default=4)
    ap.add_argument("--random-count",type=int,default=20)
    ap.add_argument("--device",choices=("auto","cuda","cpu"),default="auto")
    ap.add_argument("--max-images",type=int,default=0,
                    help="testing/debug only: evaluate only first N images; use new --out")
    ap.add_argument("--frozen",type=Path,default=ROOT/"build"/"q1_reviewer_bank"/"report.json")
    ap.add_argument("--out",type=Path,default=ROOT/"build"/"q1_gpu_deadline_full")
    ap.add_argument("--summary-only",action="store_true",help="no GPU; regenerate summary from rows")
    args=ap.parse_args()
    if args.model!=MODEL:ap.error("This suite is audited only for the exact 32-channel QAT ReLU CNN")
    if args.dataset!="BSD68" and set(args.calib_images.split(",")) & {f"{i:02}.png" for i in range(1,13)}:
        ap.error("Calibration and evaluation must be disjoint. Use BSD68.")
    if min(args.greedy_steps,args.anneal_steps,args.restarts,args.random_count,args.calib_windows)<1:
        ap.error("All optimization settings must be positive")
    if args.max_images<0:ap.error("--max-images must be >=0")
    args.sigmas=parse_sigmas(args.sigmas)
    args.seeds=parse_ints(args.seeds)
    args.calib_seeds=parse_ints(args.calib_seeds)
    args.out=Path(args.out)
    args.out.mkdir(parents=True,exist_ok=True)
    perm_source=Path(args.frozen)
    if not perm_source.exists():
        ap.error(f"Frozen report missing: {perm_source}. Run RUN_GPU_Q1_REVIEW.cmd first.")
    meta_path=ROOT/"denoise"/"export"/MODEL/"manifest.json"
    args.config=dict(model=args.model,dataset=args.dataset,sigmas=args.sigmas,
                     seeds=args.seeds,calib_seeds=args.calib_seeds,
                     calib_images=args.calib_images,calib_windows=args.calib_windows,
                     seed=args.seed,greedy_steps=args.greedy_steps,anneal_steps=args.anneal_steps,
                     restarts=args.restarts,random_count=args.random_count,
                     max_images=args.max_images,
                     model_sha256=hashlib.sha256(meta_path.read_bytes()).hexdigest(),
                     frozen_sha256=hashlib.sha256(perm_source.read_bytes()).hexdigest())
    if args.summary_only:
        config_file=args.out/"method_config.json"
        if not config_file.is_file() or json.loads(config_file.read_text(encoding="utf-8"))["experiment_config"]!=args.config:
            ap.error("No matching method_config.json for summary-only")
        summarize(args)
        return
    import torch
    dev=("cuda" if torch.cuda.is_available() else "cpu") if args.device=="auto" else args.device
    if dev=="cuda" and not torch.cuda.is_available():ap.error("CUDA unavailable")
    man,layers=load_layers(ROOT/"denoise"/"export"/MODEL)
    if len(layers)!=10 or not man.get("qat") or not man.get("graph") or any(L["post"]!="none" for L in layers):
        ap.error("Unexpected CNN, stopping rather than assuming validity")
    torch.backends.cudnn.benchmark=False
    print(f"GPU suite started. Device={dev} torch={torch.__version__}; "
          f"total image conditions={len(args.sigmas)*len(args.seeds)*68}",flush=True)
    print("Original model, existing frozen permutation, calibration methods and BSD68 "
          "evaluation all use separate files; no original weights overwritten.",flush=True)
    runner=create_runner(layers,dev)
    groups=load_or_fit(args,man,layers,runner)
    evaluate(args,man,layers,runner,groups)
    summarize(args)
    print("DONE: THIS IS A GPU CORE-COST MODEL ANALYSIS, NOT FPGA SPEEDUP.",flush=True)


if __name__=="__main__":
    main()
