"""Q1 REAL INDEPENDENT-IMAGE novelty gate (offline GPU/CPU, NO FPGA).

Train two equal-budget channel-to-bank mapping objectives on Set12 01-03 at
sigma25, noise seeds 0 and 1:
  JOINT: window-wise true co-activation workload counts.
  MARGINAL: independently shuffle the windows within each input channel,
            preserving its entire 3x3 NNZ histogram but removing alignment.
Both use identical greedy objective evaluations and optimizer seeds.
Evaluate both frozen candidate mappings on BSD68 for sigma15/25/50, seeds0/1/2
without fitting on BSD68. The resulting scores are a core-cycle ANALYTICAL
MODEL proxy, never measured FPGA speedup or full-network wall latency.

Default may entail many GPU forwards. For smoke:
  python scripts/q1_novelty_bsd68_holdout.py --max-images 2 --sigma 25 --noise-seeds 0 --out build/q1_novelty_holdout_smoke

Full:
  python scripts/q1_novelty_bsd68_holdout.py --out build/q1_novelty_holdout_full

The whole experiment writes to a fresh output folder; existing champions and
prior experiments are never overwritten.
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
MODEL="dn_d10_c32_us_fx_qat"
LAYERS=[f"conv{i}" for i in range(2,10)]
sys.path.insert(0,str(ROOT/"denoise"))
sys.path.insert(0,str(ROOT/"scripts"))


def scramble(table,seed):
    rng=np.random.default_rng(seed)
    result=np.empty_like(table)
    for ch in range(table.shape[1]):
        result[:,ch]=table[rng.permutation(len(table)),ch]
    return result


def check_balanced(group):
    g=np.asarray(group,dtype=np.int64)
    return (g.shape==(32,) and
            np.array_equal(np.bincount(g,minlength=4),np.array([8,8,8,8])))


def nested_image_bootstrap(rows,draws=2000,seed=20261018):
    """Paired bootstrap over 68 unique clean images, not 612 repeated noise tests."""
    imgs=sorted({r["image"] for r in rows})
    by_image={}
    for name in imgs:
        rs=[r for r in rows if r["image"]==name]
        identity=sum(r["identity_cycles"] for r in rs)
        joint=sum(r["joint_cycles"] for r in rs)
        marginal=sum(r["marginal_cycles"] for r in rs)
        by_image[name]=(identity,joint,marginal)
    a=np.array([by_image[k] for k in imgs],dtype=np.float64)
    rng=np.random.default_rng(seed)
    boot=[]
    for _ in range(draws):
        sampled=a[rng.integers(0,len(a),size=len(a))].sum(axis=0)
        boot.append(100*(sampled[2]-sampled[1])/sampled[0])
    raw=a.sum(axis=0)
    return dict(clean_image_count=len(imgs),
                joint_saved_pct=100*(raw[0]-raw[1])/raw[0],
                marginal_saved_pct=100*(raw[0]-raw[2])/raw[0],
                joint_minus_marginal_pp=100*(raw[2]-raw[1])/raw[0],
                image_cluster_bootstrap95_pp=list(map(float,np.percentile(boot,[2.5,97.5]))),
                image_level_joint_wins=sum(v[1]<v[2] for v in by_image.values()),
                bootstrap_draws=draws)


def save_csv(path,rows):
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",type=Path,default=ROOT/"build/q1_novelty_holdout_full")
    ap.add_argument("--device",choices=("auto","cuda","cpu"),default="auto")
    ap.add_argument("--budget",type=int,default=401)
    ap.add_argument("--optimizer-seeds",default="13,42,127,612")
    ap.add_argument("--calib-windows",type=int,default=2048)
    ap.add_argument("--sigma",default="15,25,50")
    ap.add_argument("--noise-seeds",default="0,1,2")
    ap.add_argument("--max-images",type=int,default=0,help="Debug only; 0 means full BSD68 68 clean images")
    ap.add_argument("--selftest",action="store_true")
    a=ap.parse_args()
    if a.selftest:
        q=np.tile(np.arange(16,dtype=np.uint8),(32,1)).T
        z=scramble(q,19)
        assert np.array_equal(np.sort(q,axis=0),np.sort(z,axis=0))
        assert check_balanced(np.arange(32)%4)
        print("PASS marginal permutation and balanced bank assignment")
        return
    if a.out.exists():ap.error("Refusing to overwrite existing experiment output")
    if a.budget<2 or a.calib_windows<64 or a.max_images<0 or a.max_images>68:
        ap.error("Invalid budget/calib-windows/max-images")
    optim_seeds=[int(s) for s in a.optimizer_seeds.split(",")]
    sigmas=[int(s) for s in a.sigma.split(",")]
    noise_seeds=[int(s) for s in a.noise_seeds.split(",")]
    if (not optim_seeds or len(set(optim_seeds))!=len(optim_seeds)
            or not noise_seeds or len(set(noise_seeds))!=len(noise_seeds)
            or not sigmas or len(set(sigmas))!=len(sigmas)
            or any(s<=0 for s in sigmas)):
        ap.error("Invalid or duplicated seed/sigma selections")
    # imports done after selftest so CI needs NumPy only.
    from common import QMAX_A,load_set,test_noise
    from run_denoise import load_layers
    from q1_reviewer_bank import create_runner,fit_group,cycles
    import torch
    device=("cuda" if torch.cuda.is_available() else "cpu") if a.device=="auto" else a.device
    if device=="cuda" and not torch.cuda.is_available():ap.error("CUDA not available")
    man,layers=load_layers(ROOT/"denoise/export"/MODEL)
    layer_cfg={v["name"]:v for v in layers}
    run=create_runner(layers,device)
    calibration=defaultdict(list)
    for ns in (0,1):
        for image,clean,noisy in test_noise(load_set("Set12"),25,seed=ns):
            if image not in {"01.png","02.png","03.png"}:continue
            q=np.rint(noisy*QMAX_A).astype(np.uint8)
            with torch.no_grad(): feature_counts,_=run(q)
            for lname,rows in feature_counts.items():
                calibration[lname].append(rows)
            print("CALIB",image,"seed",ns,flush=True)
    groups={}
    for lname in LAYERS:
        full=np.concatenate(calibration[lname],axis=0)
        sample=np.random.default_rng(45+int(lname[4:])).choice(
            len(full),size=min(a.calib_windows,len(full)),replace=False)
        train=full[sample]
        marginal_train=scramble(train,83000+int(lname[4:]))
        layer=layer_cfg[lname]
        for os in optim_seeds:
            seed=os+20*int(lname[4:])
            g_joint,_=fit_group(train,layer["COUT"],layer["K"],seed,a.budget-1)
            g_marg,_=fit_group(marginal_train,layer["COUT"],layer["K"],seed,a.budget-1)
            if not check_balanced(g_joint) or not check_balanced(g_marg):
                raise ValueError("Unbalanced optimizer solution")
            groups.setdefault(str(os),{})[lname]=dict(joint=g_joint.tolist(),marginal=g_marg.tolist())
        print("FIT",lname,len(train),"windows",a.budget,"objective evaluations per method",flush=True)
    a.out.mkdir(parents=True)
    (a.out/"groups.json").write_text(json.dumps(
        dict(methods=["joint","marginal"],calibration=["Set12 01-03 sigma25 seeds0/1"],
             model=MODEL,budget=a.budget,groups=groups),indent=2)+"\n",encoding="utf-8")
    scores=[]
    images=load_set("BSD68")
    if len(images)!=68:raise ValueError("Expected 68 independent BSD68 clean images")
    images=images[:a.max_images] if a.max_images else images
    for sigma in sigmas:
        for ns in noise_seeds:
            # Noise generated deterministically for all 68 images even during smoke,
            # so selected image's noise is independent of --max-images.
            for image,clean,noisy in test_noise(load_set("BSD68"),sigma,seed=ns):
                if image not in {n for n, _ in images}:continue
                q=np.rint(noisy*QMAX_A).astype(np.uint8)
                with torch.no_grad(): activation,_=run(q)
                for os in optim_seeds:
                    old=jcost=mcost=0
                    for lname in LAYERS:
                        tab=activation[lname];l=layer_cfg[lname]
                        original=np.arange(32,dtype=np.int64)%4
                        g=groups[str(os)][lname]
                        old+=int(cycles(tab,l["COUT"],l["K"],original).sum())
                        jcost+=int(cycles(tab,l["COUT"],l["K"],np.array(g["joint"])).sum())
                        mcost+=int(cycles(tab,l["COUT"],l["K"],np.array(g["marginal"])).sum())
                    scores.append(dict(image=image,sigma=sigma,noise_seed=ns,optimizer_seed=os,
                                       identity_cycles=old,joint_cycles=jcost,marginal_cycles=mcost,
                                       joint_saved_pct=100*(old-jcost)/old,
                                       marginal_saved_pct=100*(old-mcost)/old,
                                       joint_minus_marginal_pp=100*(mcost-jcost)/old))
                print("EVAL",image,"sigma",sigma,"seed",ns,flush=True)
                with (a.out/"progress.json").open("w",encoding="utf-8") as f:
                    json.dump(dict(completed_rows=len(scores),latest_image=image,
                                   sigma=sigma,noise_seed=ns),f,indent=2)
    save_csv(a.out/"per_condition.csv",scores)
    result=nested_image_bootstrap(scores)
    result.update(dict(
        status="OFFLINE_BSD68_CYCLE_MODEL_PROXY_NOT_FPGA_MEASUREMENT",
        calibration_dataset="Set12/01-03",
        evaluation_dataset="BSD68",
        independent_clean_images=len(images),
        sigmas=sigmas,noise_seeds=noise_seeds,
        optimizer_seeds=optim_seeds,budget_per_method_per_layer=a.budget,
        caveats=[
            "Only analytical Conv2–9 W4 core cycles, not actual FPGA or end-to-end measurements.",
            "Image bootstrap holds optimization seeds fixed; it does not quantify seed-to-seed algorithm variability.",
            "Original quantized model may have been selected using BSD68 before permutation experiments.",
            "Evaluation set was never used to optimize or choose permutations in this run.",
            "If --max-images is nonzero, numbers are DEBUG only and not a 68-image study."
        ]))
    (a.out/"summary.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print("COMPLETE: joint-vs-marginal",result["joint_minus_marginal_pp"],
          "pp; clean images",len(images))
    print("Results",a.out)


if __name__=="__main__":
    main()
