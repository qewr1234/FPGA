"""Compare two W=4 FPGA board reports (original vs channel-permuted model).

No hardware access; refuse incompatible comparisons.
Usage:
    python scripts/q1_board_ab_compare.py \
        --baseline build/q1_bank_board_baseline/report.json \
        --permuted build/q1_bank_board_permuted/report.json
"""
import argparse
import json
from pathlib import Path


def load(path):
    obj=json.loads(path.read_text(encoding="utf-8"))
    if obj.get("emulated") is not False:
        raise ValueError(f"{path}: not a physical board run")
    if obj.get("activations_per_cycle")!=4 or obj.get("mode_seq")!=1:
        raise ValueError(f"{path}: W=4, sparse mode=1 required")
    if obj.get("mismatches")!=0:
        raise ValueError(f"{path}: top-level mismatches")
    return obj


def check_img(report,path):
    images=report.get("images",[])
    if len(images)!=1:
        raise ValueError(f"{path}: exactly one image is required")
    row=images[0]
    if row.get("start_layer")!=1:
        raise ValueError(f"{path}: resumed layers cannot be compared here")
    if not row.get("layers") or len(row["layers"])!=10:
        raise ValueError(f"{path}: expected 10 layers")
    for layer in row["layers"]:
        if layer.get("emulated") or layer.get("mismatches")!=0:
            raise ValueError(f"{path}: {layer['name']} not an exact board run")
        if layer.get("in_stall") is None or layer.get("out_stall") is None:
            raise ValueError(f"{path}: missing stall counters on {layer['name']}")
        ids=[int(v,16) for v in layer.get("core_id",[])]
        if not ids or any(not(id_ & (1<<9)) for id_ in ids):
            raise ValueError(f"{path}: {layer['name']} is not the W=4 bitstream")
        if not layer.get("fclk_mhz"):
            raise ValueError(f"{path}: {layer['name']} missing clock")
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--permuted",type=Path,required=True)
    p.add_argument("--out",type=Path,default=Path("build/q1_bank_board_ab_compare.json"))
    a=p.parse_args()
    if a.baseline.resolve()==a.permuted.resolve():
        p.error("Cannot compare the same report file")
    base,new=load(a.baseline),load(a.permuted)
    x,y=check_img(base,a.baseline),check_img(new,a.permuted)
    fields=("model","set","sigma","mode_seq","activations_per_cycle")
    for field in fields:
        if base.get(field)!=new.get(field):
            raise ValueError(f"{field}: {base.get(field)!r} vs {new.get(field)!r}")
    for field in ("image","width","height","start_layer"):
        if x.get(field)!=y.get(field):
            raise ValueError(f"{field}: {x.get(field)!r} vs {y.get(field)!r}")
    if abs(x["psnr_denoised"]-y["psnr_denoised"])>1e-9:
        raise ValueError("Denosing PSNR changed. Check bank reorder bit exactness.")
    rows=[]
    for o,n in zip(x["layers"],y["layers"]):
        for key in ("name","K","COUT","windows","taps_streamed"):
            if o[key]!=n[key]:
                raise ValueError(f"{key} mismatch: {o.get(key)} vs {n.get(key)}")
        if o["core_id"]!=n["core_id"] or o["fclk_mhz"]!=n["fclk_mhz"]:
            raise ValueError(f"{o['name']}: bitstream core ID or fclk not equal")
        ov=int(o["cycles"]);nv=int(n["cycles"])
        rows.append(dict(
            layer=o["name"],baseline_cycles=ov,permuted_cycles=nv,
            cycle_saved=ov-nv,pct_saved=100*(ov-nv)/ov,
            baseline_in_stall=o["in_stall"],permuted_in_stall=n["in_stall"],
            baseline_out_stall=o["out_stall"],permuted_out_stall=n["out_stall"]))
    oc=sum(r["baseline_cycles"] for r in rows)
    nc=sum(r["permuted_cycles"] for r in rows)
    inner=[r for r in rows if r["layer"] in {f"conv{i}" for i in range(2,10)}]
    inner_old=sum(r["baseline_cycles"] for r in inner)
    inner_new=sum(r["permuted_cycles"] for r in inner)
    result=dict(
        status="PHYSICAL_W4_CORE_CYCLE_COMPARISON", model=base["model"],
        image=x["image"],sigma=base["sigma"],fclk_mhz=x["layers"][0]["fclk_mhz"],
        core_id=x["layers"][0]["core_id"],bit_exact_mismatches=0,
        baseline_cycles=oc,permuted_cycles=nc,
        total_saved_cycles=oc-nc,total_pct_saved=100*(oc-nc)/oc,
        conv2to9_saved_cycles=inner_old-inner_new,
        conv2to9_pct_saved=100*(inner_old-inner_new)/inner_old,
        layers=rows,
        warning=("Measures PL core cycles including DMA stalls as recorded; "
                 "not whole-device wall-clock latency, PS overhead or power. "
                 "Single-run results need repetition to establish variance."))
    for r in rows:
        print(f"{r['layer']:7s} base={r['baseline_cycles']:10,d} "
              f"perm={r['permuted_cycles']:10,d} "
              f"saved={r['cycle_saved']:+10,d} ({r['pct_saved']:+.3f}%) "
              f"in_stall={r['baseline_in_stall']}/{r['permuted_in_stall']}")
    print(f"\nTOTAL baseline={oc:,}, reordered={nc:,} ({result['total_pct_saved']:+.3f}% saved)")
    print(f"Conv2-9 cycle reduction: {result['conv2to9_pct_saved']:.3f}%")
    if oc<=nc:
        print("NO PERFORMANCE GAIN: board cycles did not improve. Do not claim acceleration.")
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print("Results:",a.out.resolve())


if __name__=="__main__":
    main()
