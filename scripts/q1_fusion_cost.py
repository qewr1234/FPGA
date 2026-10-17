"""Analytical two-layer tile-fusion screen for FPGA denoising.

This program reads an exported model manifest and estimates *candidate*
memory footprints, stream-volume proxies, and duplicated MAC work. It never
programs a board. It never predicts speedups, FPGA FPS, timing or power.

Hypothesized hardware has an on-chip 3x3 window generator, per-channel
bit-exact requantization, local input/intermediate buffers and shared MAC
core. None of these features is claimed to be present in the current RTL.
"""
import argparse
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (ROOT / "denoise" / "export" /
                    "dn_d10_c32_us_fx_qat" / "manifest.json")


def ceil_div(a, b):
    return (a + b - 1) // b


def tiles(h, w, side):
    for y0 in range(0, h, side):
        for x0 in range(0, w, side):
            yield (y0, min(h, y0 + side), x0, min(w, x0 + side))


def area_with_halo(y0, y1, x0, x1, h, w, halo):
    ya, yb = max(0, y0-halo), min(h, y1+halo)
    xa, xb = max(0, x0-halo), min(w, x1+halo)
    return max(0, yb-ya) * max(0, xb-xa)


def validate_pair(a, b):
    if b.get("inputs") != [a.get("name")]:
        raise ValueError(f"Not adjacent dependent layers: {a['name']} -> {b['name']}")
    for layer in (a,b):
        if any(int(layer.get(k, -1)) != v
               for k,v in (("kh",3),("kw",3),("stride",1),("dilation",1))):
            raise ValueError(f"{layer['name']}: only 3x3 stride=1 dilation=1 supported")
    if a.get("post") != "none":
        raise ValueError(f"{a['name']}: unsupported intermediate op {a.get('post')}")
    cin = int(a["K"])//9
    cmid = int(a["COUT"])
    if int(a["K"]) != 9*cin or int(b["K"]) != 9*cmid:
        raise ValueError(f"{a['name']}->{b['name']}: unexpected channel geometry")
    if "requant" not in a:
        raise ValueError(f"{a['name']}: missing integer requant factors")
    return cin, cmid, int(b["COUT"])


def evaluate_pair(a, b, h, w, side, baseline_bram, reserve_bram,
                  total_bram, safety_factor, buffer_sets):
    cin, cmid, cout = validate_pair(a,b)
    n = h*w
    ka, kb = int(a["K"]), int(b["K"])
    baseline_input_bytes = n * (ceil_div(ka,4)*4 + ceil_div(kb,4)*4)
    baseline_acc_bytes = n*4*(cmid+cout)
    baseline_external_bytes = baseline_input_bytes + baseline_acc_bytes
    # A is computed at each tile's output plus one output-position halo,
    # because B uses A at y +/- 1, x +/- 1. Out-of-image A is zero padding.
    a_windows = 0
    a_input_bytes = 0
    for y0,y1,x0,x1 in tiles(h,w,side):
        a_windows += area_with_halo(y0,y1,x0,x1,h,w,1)
        a_input_bytes += cin * area_with_halo(y0,y1,x0,x1,h,w,2)
    fused_acc_bytes = n*cout*4  # Only B's INT32 output is returned to DDR.
    proposed_external_bytes = a_input_bytes + fused_acc_bytes
    baseline_macs = n * (ka*cmid + kb*cout)
    proposed_macs = a_windows*ka*cmid + n*kb*cout
    # Conservative full-tile staging budget, not a place-and-route guarantee.
    # A's input tile needs a radius-2 halo, and stage A's uint8 output a
    # radius-1 halo. INT32 A values must be requantized *on chip* as produced.
    maxth, maxtw = min(h,side), min(w,side)
    in_buf = (maxth+4)*(maxtw+4)*cin
    mid_buf = (maxth+2)*(maxtw+2)*cmid
    raw_buffer_bytes = in_buf + mid_buf
    projected_buffer_bytes = math.ceil(raw_buffer_bytes*safety_factor)*buffer_sets
    # 1 RAMB36 = 36,864 bits = 4,608 bytes, theoretical capacity only.
    projected_bram36 = ceil_div(projected_buffer_bytes,4608)
    left_after = total_bram - baseline_bram - reserve_bram - projected_bram36
    fits = left_after >= 0
    return dict(
        pair=a["name"]+"+"+b["name"],tile=side,tiles=ceil_div(h,side)*ceil_div(w,side),
        fmap_h=h,fmap_w=w,cin=cin,cmid=cmid,cout=cout,
        baseline_input_bytes=baseline_input_bytes,
        baseline_acc_bytes=baseline_acc_bytes,
        baseline_external_bytes=baseline_external_bytes,
        proposed_input_bytes=a_input_bytes,
        proposed_acc_bytes=fused_acc_bytes,
        proposed_external_bytes=proposed_external_bytes,
        external_stream_reduction_pct=round(100*(1-proposed_external_bytes/baseline_external_bytes),3),
        proposed_input_to_baseline_input_ratio=round(a_input_bytes/baseline_input_bytes,6),
        baseline_macs=baseline_macs,
        proposed_macs=proposed_macs,
        extra_mac_pct=round(100*(proposed_macs/baseline_macs-1),4),
        stage_a_extra_windows=a_windows-n,
        tile_input_buffer_bytes=in_buf,
        tile_intermediate_buffer_bytes=mid_buf,
        buffer_bytes_raw=raw_buffer_bytes,
        buffer_bytes_with_overhead=projected_buffer_bytes,
        extra_bram36_equiv=projected_bram36,
        available_bram36_equiv=round(total_bram-baseline_bram-reserve_bram,3),
        bram_headroom_after_reserve=round(left_after,3),
        bram_proxy_fit=fits)


def layer_geometry(man, raw_h, raw_w):
    if man.get("unshuffle", False) or int(man.get("pad_to",1)) == 2:
        h, w = ceil_div(raw_h,2), ceil_div(raw_w,2)
    else:
        h, w = raw_h, raw_w
    result = {}
    # Intended for the documented chain graph with 3x3 same-size layers.
    for layer in man["layers"]:
        if any(int(layer.get(k,-1)) != v
               for k,v in (("kh",3),("kw",3),("stride",1),("dilation",1))):
            raise ValueError("Only simple 3x3 same-resolution networks supported")
        result[layer["name"]] = (h,w)
        if layer.get("post") == "shuffle2":
            raise ValueError("Shuffle graph not supported by the first screening model")
    return result


def parse_sides(s):
    try:
        values = sorted(set(int(x.strip()) for x in s.split(",") if x.strip()))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))
    if not values or any(x<4 for x in values):
        raise argparse.ArgumentTypeError("tiles must be integer sides >=4")
    return values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest",type=Path,default=DEFAULT_MANIFEST)
    ap.add_argument("--image-size",default="256x256",help="Raw image HxW")
    ap.add_argument("--pairs",default="conv2:conv3,conv4:conv5,conv6:conv7,conv8:conv9")
    ap.add_argument("--tiles",type=parse_sides,default=parse_sides("16,24,32,40,48,56,64,80,96"))
    ap.add_argument("--baseline-ramb36",type=int,default=68)
    ap.add_argument("--baseline-ramb18",type=int,default=6)
    ap.add_argument("--total-ramb36",type=int,default=140)
    ap.add_argument("--reserve-bram36",type=int,default=16)
    ap.add_argument("--buffer-safety-factor",type=float,default=1.25)
    ap.add_argument("--buffer-sets",type=int,choices=(1,2),default=1)
    ap.add_argument("--out",type=Path,default=ROOT/"build"/"q1_fusion_screen")
    args=ap.parse_args()
    try:
        h,w=(int(t) for t in args.image_size.lower().split("x"))
    except (ValueError,AttributeError):
        ap.error("--image-size must be HxW e.g. 256x256")
    if h<1 or w<1 or args.buffer_safety_factor<1 or args.reserve_bram36<0:
        ap.error("invalid size, reserve or safety factor")
    if min(args.baseline_ramb36,args.baseline_ramb18,args.total_ramb36)<0:
        ap.error("BRAM counts must be nonnegative")
    man=json.loads(args.manifest.read_text(encoding="utf-8"))
    by_name={l["name"]:l for l in man["layers"]}
    geom=layer_geometry(man,h,w)
    baseline_bram=args.baseline_ramb36 + args.baseline_ramb18/2
    pairs=[]
    for part in args.pairs.split(","):
        try:
            a,b=(x.strip() for x in part.split(":"))
            pairs.append((by_name[a],by_name[b]))
        except (ValueError,KeyError) as exc:
            ap.error(f"Invalid pair '{part}': {exc}")
    rows=[]
    for a,b in pairs:
        ha,wa=geom[a["name"]];hb,wb=geom[b["name"]]
        if (ha,wa)!=(hb,wb):
            raise ValueError("Different spatial scales cannot be paired")
        for side in args.tiles:
            rows.append(evaluate_pair(a,b,ha,wa,side,baseline_bram,
                    args.reserve_bram36,args.total_ramb36,
                    args.buffer_safety_factor,args.buffer_sets))
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/"candidates.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    summary=[]
    for a,b in pairs:
        name=a["name"]+"+"+b["name"]
        valid=[r for r in rows if r["pair"]==name and r["bram_proxy_fit"]]
        # Pareto of estimated traffic and MAC count, not FPS.
        frontier=[r for r in valid if not any(
            (v["proposed_external_bytes"]<=r["proposed_external_bytes"]
             and v["proposed_macs"]<=r["proposed_macs"]
             and (v["proposed_external_bytes"]<r["proposed_external_bytes"]
                  or v["proposed_macs"]<r["proposed_macs"]))
            for v in valid)]
        summary.append(dict(pair=name,candidates_fitting_proxy=len(valid),
            pareto_tiles=[r["tile"] for r in frontier],
            min_stream_bytes_tile=(min(valid,key=lambda r:r["proposed_external_bytes"])["tile"]
                                   if valid else None)))
    limitations=[
        "Not RTL, not a measured speedup, not a JTAG/DMA/PS/PL benchmark.",
        "Baseline external bytes are logical uncompressed W=4 input and INT32 output streams. "
        "Proposed bytes assume new on-chip window generation, immediate bit-exact "
        "per-channel requantization and elimination of A's DDR accumulator transfer.",
        "Neither new hardware block has been built. Existing shared MAC may serialize "
        "stage A and B; compute time can grow due to tiled halo duplication.",
        "Capacity is ideal RAMB36-equivalent bytes times a safety factor; ignores "
        "BRAM bank port constraints, address logic, place-and-route congestion, "
        "clock closure, weight buffering, arbitration and full AXI overhead.",
        "No model quality gain is claimed. Identical integer outputs must be "
        "proved, first in host oracle and later on FPGA.",
        "Original ZedBoard resource use is not automatically reproducible on "
        "the user's Smart ZYNQ SL PS/DDR preset."
    ]
    report=dict(model=man.get("model"),source_manifest=str(args.manifest),
        raw_image_hw=[h,w],tiles=args.tiles, pairs=summary,
        resource_assumptions=dict(
            xc7z020_ramb36_equivalents=args.total_ramb36,
            baseline_ramb36=args.baseline_ramb36,
            baseline_ramb18=args.baseline_ramb18,
            original_bram36_equivalents=baseline_bram,
            reserved_bram36=args.reserve_bram36,
            buffer_sets=args.buffer_sets,
            buffer_safety_factor=args.buffer_safety_factor),
        limitations=limitations,all_results_file="candidates.csv")
    (args.out/"summary.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"MODEL {man.get('model')} raw {h}x{w}; fmap {geom[pairs[0][0]['name']]}")
    print("Baseline BRAM36 equiv %.1f / %d, reserve %d; buffers x%d, safety x%.2f" %
          (baseline_bram,args.total_ramb36,args.reserve_bram36,
           args.buffer_sets,args.buffer_safety_factor))
    for s in summary:
        print("\n"+s["pair"]+": "+str(s["candidates_fitting_proxy"])+" possible BRAM-proxy fits;"
              " Pareto tiles="+str(s["pareto_tiles"]))
        for r in rows:
            if r["pair"]!=s["pair"]: continue
            print("  T=%-3d %-5s stream reduction=%.1f%% extra MAC=%.2f%% extra BRAM36=%d" %
                  (r["tile"],"FIT" if r["bram_proxy_fit"] else "NOFIT",
                   r["external_stream_reduction_pct"],r["extra_mac_pct"],
                   r["extra_bram36_equiv"]))
    print("\nSaved:",args.out.resolve())
    print("ANALYTICAL PROXIES ONLY. No FPGA latency/power measured.")


if __name__=="__main__":
    main()
