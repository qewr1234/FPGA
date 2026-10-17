"""Paired image-cluster statistics for completed bank-permutation GPU sweep.

Input:  build/q1_gpu_deadline_full/per_image_methods.csv
        9 methods x 68 BSD68 images x 3 noise sigmas x 3 noise seeds.

Output: paired_tests.csv, paired_tests.json, paper_table.md,
        and optionally method_comparison.png if matplotlib is installed.

This analyzes the SAME images across methods and resamples images as clusters.
It is descriptive for the historical BSD68 corpus, not evidence of independent
model-selection / FPGA runtime / statistical generality beyond those images.

Works on RTX GPU PC but does not run the network again.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_INPUT=ROOT/"build"/"q1_gpu_deadline_full"/"per_image_methods.csv"
DEFAULT_OUT=ROOT/"build"/"q1_gpu_deadline_final"
METHODS=(
    "identity","frozen_01","density_sort","greedy","anneal",
    "multistart_greedy","risk_aware_greedy","random_mean",
    "random_best_reference"
)
COMPARISONS=(
    ("multistart_greedy","frozen_01"),
    ("multistart_greedy","density_sort"),
    ("multistart_greedy","greedy"),
    ("multistart_greedy","anneal"),
    ("multistart_greedy","risk_aware_greedy"),
    ("frozen_01","density_sort"),
    ("anneal","greedy"),
)


def get_data(path, allow_partial=False):
    if not path.is_file():
        raise FileNotFoundError(f"Missing GPU results CSV: {path}")
    groups=defaultdict(dict)
    with path.open("r",newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key=(row["dataset"],int(row["sigma"]),int(row["noise_seed"]),row["image"])
            meth=row["method"]
            if meth not in METHODS:raise AssertionError(f"Unknown method {meth}")
            if meth in groups[key]:raise AssertionError(f"Duplicate method for {key}: {meth}")
            groups[key][meth]={
                "base":float(row["baseline_cycles"]),
                "cost":float(row["method_cycles"]),
                "psnr":float(row["psnr_db"]),
            }
    if not groups:
        raise AssertionError("Empty experiment CSV")
    if not allow_partial and len(groups)!=612:
        raise AssertionError(f"Need all 68x3x3=612 conditions; found {len(groups)}")
    for key, methods in groups.items():
        if set(methods)!=set(METHODS):
            raise AssertionError(f"Some methods missing for {key}: {set(METHODS)-set(methods)}")
        bases=[methods[m]["base"] for m in METHODS]
        if max(bases)-min(bases)>0.01:
            raise AssertionError(f"Different reference cycles in same image-condition {key}")
        values=[methods[m]["psnr"] for m in METHODS]
        if max(values)-min(values)>1e-7:
            raise AssertionError(f"Inconsistent PSNR across methods {key}")
        if methods["identity"]["cost"]!=methods["identity"]["base"]:
            raise AssertionError(f"Identity cost differs from baseline {key}")
    return groups


def aggregate(groups,method,sigma=None):
    selected=[v for k,v in groups.items() if sigma is None or k[1]==sigma]
    base=sum(v["identity"]["base"] for v in selected)
    cost=sum(v[method]["cost"] for v in selected)
    return 100*(base-cost)/base if base else float("nan")


def compare(groups,a,b,sigma,n_boot,seed):
    # Image-cluster bootstrap: all conditions for each image resampled together.
    per_image=defaultdict(lambda:np.zeros(3,dtype=np.float64))
    for key,values in groups.items():
        if sigma is not None and key[1]!=sigma:continue
        img=key[3]
        per_image[img][0]+=values["identity"]["base"]
        per_image[img][1]+=values[a]["cost"]
        per_image[img][2]+=values[b]["cost"]
    arr=np.stack([per_image[k] for k in sorted(per_image)])
    total=arr.sum(0)
    # Percent-point benefit of method a over b: same denominator.
    estimated=100*(total[2]-total[1])/total[0]
    rng=np.random.default_rng(seed)
    idx=rng.integers(0,len(arr),size=(n_boot,len(arr)))
    samples=arr[idx].sum(axis=1)
    boot=100*(samples[:,2]-samples[:,1])/samples[:,0]
    ci=np.quantile(boot,[0.025,0.975])
    per_image_positive=int(np.count_nonzero(arr[:,2]>arr[:,1]))
    per_image_negative=int(np.count_nonzero(arr[:,2]<arr[:,1]))
    per_image_ties=int(np.count_nonzero(arr[:,2]==arr[:,1]))
    # Exact binomial sign-tail using scipy if present; otherwise omit.
    sign_p=None
    try:
        from scipy.stats import binomtest
        ns=per_image_positive+per_image_negative
        if ns:sign_p=float(binomtest(per_image_positive,ns,0.5,alternative="two-sided").pvalue)
    except ImportError:
        pass
    return dict(
        sigma="ALL" if sigma is None else sigma,
        method_a=a,method_b=b,image_clusters=len(arr),
        image_conditions=sum(1 for k in groups if sigma is None or k[1]==sigma),
        gain_a_pct=round(aggregate(groups,a,sigma),6),
        gain_b_pct=round(aggregate(groups,b,sigma),6),
        paired_gain_pp=round(float(estimated),6),
        paired_bootstrap_ci95_pp=[round(float(x),6) for x in ci],
        positive_images=per_image_positive,negative_images=per_image_negative,
        tied_images=per_image_ties,
        exploratory_two_sided_image_sign_test_p=sign_p,
    )


def chart(methods,out):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig,ax=plt.subplots(figsize=(9,4.8))
        names=[m for m in METHODS if m in methods and m!="random_best_reference"]
        vals=[methods[m] for m in names]
        ax.barh(names,vals)
        ax.axvline(0,linewidth=0.8)
        ax.set_xlabel("Estimated W4 Sparse Conv2-9 core coefficient reduction (%)")
        ax.set_title("Original vs frozen and calibrated bank-group strategies")
        ax.invert_yaxis()
        ax.grid(axis="x",alpha=.2)
        fig.tight_layout()
        fig.savefig(out/"method_comparison.png",dpi=180)
        plt.close(fig)
        return True
    except ImportError:
        return False


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",type=Path,default=DEFAULT_INPUT)
    ap.add_argument("--out",type=Path,default=DEFAULT_OUT)
    ap.add_argument("--bootstrap",type=int,default=4000)
    ap.add_argument("--allow-partial",action="store_true")
    args=ap.parse_args()
    if args.bootstrap<100:ap.error("--bootstrap must be >=100")
    groups=get_data(args.input,args.allow_partial)
    sigmas=sorted({key[1] for key in groups})
    if not args.allow_partial and sigmas!=[15,25,50]:
        raise AssertionError("Expected sigma=[15,25,50]")
    records=[]
    for si,sigma in enumerate([None]+sigmas):
        for ci,(a,b) in enumerate(COMPARISONS):
            records.append(compare(groups,a,b,sigma,args.bootstrap,
                                   seed=20261018+100*si+ci))
    pooled={m:round(aggregate(groups,m),6) for m in METHODS}
    args.out.mkdir(parents=True,exist_ok=True)
    data=dict(
        data_source=str(args.input),complete=not args.allow_partial,
        image_conditions=len(groups),methods=pooled,paired_comparisons=records,
        limitations=[
            "Cluster bootstrap resamples image identities, preserving all noise conditions; not a formal external-population confidence interval.",
            "Comparisons are exploratory and multiple comparisons have not been family-wise corrected.",
            "Exploratory sign-test p-values are descriptive and do not prove algorithmic novelty.",
            "These are estimated core coefficients, NOT FPGA execution times.",
            "random_best_reference is an oracle chosen by test-image costs and is NOT a deployable method.",
            "BSD68 images are disjoint from permutation calibration, but not necessarily from original CNN architecture development."
        ])
    (args.out/"paired_tests.json").write_text(
        json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"
    )
    with (args.out/"paired_tests.csv").open("w",newline="",encoding="utf-8") as f:
        headers=["sigma","method_a","method_b","image_clusters","image_conditions",
                 "gain_a_pct","gain_b_pct","paired_gain_pp",
                 "ci_low_pp","ci_high_pp","positive_images",
                 "negative_images","tied_images",
                 "exploratory_two_sided_image_sign_test_p"]
        w=csv.DictWriter(f,fieldnames=headers);w.writeheader()
        for r in records:
            w.writerow({**r,
                        "ci_low_pp":r["paired_bootstrap_ci95_pp"][0],
                        "ci_high_pp":r["paired_bootstrap_ci95_pp"][1],
                        **{"paired_bootstrap_ci95_pp":None}} if False else {
                            **{k:v for k,v in r.items() if k!="paired_bootstrap_ci95_pp"},
                            "ci_low_pp":r["paired_bootstrap_ci95_pp"][0],
                            "ci_high_pp":r["paired_bootstrap_ci95_pp"][1]
                        })
    lines=[
        "# Paired GPU bank permutation method comparison",
        "",
        "BSD68 | fixed calibration images Set12 01/02/03 | W4 sparse conv2-9 **modeled coefficients**.",
        "This is NOT measured FPGA acceleration.",
        "",
        "| Method | Estimated pooled reduction (%) |",
        "|---|---:|",
    ]
    for m,v in sorted(pooled.items(),key=lambda x:-x[1]):
        lines.append(f"| {m} | {v:.3f} |")
    lines+=["","## Paired image-cluster differences (percentage points)","",
            "| Sigma | Method A | Method B | Δ(A-B) pp | 95% image bootstrap CI | Images A>B |",
            "|---|---|---|---:|---|---:|"]
    for r in records:
        lines.append(
            f"| {r['sigma']} | {r['method_a']} | {r['method_b']} | "
            f"{r['paired_gain_pp']:+.4f} | "
            f"[{r['paired_bootstrap_ci95_pp'][0]:+.4f}, {r['paired_bootstrap_ci95_pp'][1]:+.4f}] | "
            f"{r['positive_images']}/{r['image_clusters']} |"
        )
    lines+=["",
            "**Interpretation:** A positive paired gain means A used fewer predicted cycles than B on the same image/noise conditions.",
            "No multiplicity correction or independent external test set; values are descriptive.",
            "No physical FPGA/JTAG/DDR/timing measurements were performed.",
            ""]
    (args.out/"PAIRED_STATS.md").write_text("\n".join(lines),encoding="utf-8")
    print(f"Completed {len(groups)} image-condition groups x {len(METHODS)} methods")
    for r in records:
        if r["sigma"]=="ALL":
            print(f"{r['method_a']:20s} vs {r['method_b']:20s} "
                  f"paired gain {r['paired_gain_pp']:+.3f} pp, "
                  f"CI95 {r['paired_bootstrap_ci95_pp']}")
    print("PNG generated:",chart(pooled,args.out))
    print("Files:",(args.out/"paired_tests.json").resolve(),
          (args.out/"PAIRED_STATS.md").resolve(),sep="\n  ")


if __name__=="__main__":
    main()
