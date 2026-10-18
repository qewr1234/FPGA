"""SAFE FPGA W=4 three-way A/B/C: Original, Frozen_01, Multi-start.

Default is PREFLIGHT ONLY: validates both released GitHub model archives,
permutation metadata and the multi-start GPU-proven candidate SHA256 without
accessing Vivado, JTAG, PS DDR or any physical FPGA.

An actual board run requires ALL of:
 --execute --board-verified SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED
 --xsdb <EXPLICIT_PATH> --build <VERIFIED_SMART_ZYNQ_SL_W4_DIRECTORY>
The user must independently confirm actual PS7 DDR/MIO/board timing/pinout.
NEVER assume a ZedBoard bitstream works on the Smart ZYNQ SL.

3+ repetitions; identical approved W4 core, image and input noise seed.
Compares physical 10-layer core cycles including recorded stalls, not E2E
wall-clock video-in/video-out or measured power.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from q1_fpga_bank_ab import verify_archive as verify_frozen
from q1_board_ab_compare import load as load_board,check_img

MODEL="dn_d10_c32_us_fx_qat"
APPROVAL="SMART_ZYNQ_SL_PS_DDR_MIO_VERIFIED"
CANARY_APPROVAL="SAME_PHYSICAL_BOARD_W4_CANARY_VERIFIED"
SOURCE=ROOT/"denoise"/"export"/MODEL
FROZEN=ROOT/"build"/"q1_reviewer_export"/MODEL
MULTI=ROOT/"build"/"q1_multistart_export"/MODEL
MULTI_ZIP=ROOT/"research"/"q1_codesign"/"artifacts"/"q1_multistart_verified_export_20261018.zip"
MULTI_MAP=ROOT/"research"/"q1_codesign"/"multistart_export_20261018.json"
MULTI_STRESS=ROOT/"research"/"q1_codesign"/"multistart_bitexact_summary_20261018.json"


def digest(folder):
    h=hashlib.sha256()
    files=sorted(folder.glob("conv*_config.bin"))
    if len(files)!=10:raise ValueError(f"{folder}: expected ten conv configs")
    for p in files:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    h.update((folder/"manifest.json").read_bytes())
    return h.hexdigest()


def preflight():
    verify_frozen()
    if not MULTI_ZIP.is_file():raise ValueError(
        f"Multi-start ZIP missing: {MULTI_ZIP} — git pull origin main")
    stress=json.loads(MULTI_STRESS.read_text(encoding="utf-8"))
    if not stress.get("experiment_complete") or stress.get("total_mismatched_pixels")!=0 or stress.get("images_conditions_checked")!=720:
        raise ValueError("Multi-start stress-test report does not prove 720/720 pixel equality")
    calibrated=json.loads(MULTI_MAP.read_text(encoding="utf-8"))
    expected_orders={"conv"+str(int(l["layer"][4:])-1):l["original_channel_order"]
                     for l in calibrated["layers"]}
    with zipfile.ZipFile(MULTI_ZIP) as z:
        bad=z.testzip()
        if bad:raise ValueError(f"Multi-start archive CRC mismatch: {bad}")
        prefix=MODEL+"/"
        required={prefix+"manifest.json",prefix+"int_eval.json",
                  prefix+"permutation_manifest.json"}
        required|={prefix+f"conv{i}_config.bin" for i in range(1,11)}
        if not required.issubset(z.namelist()):
            raise ValueError("Multi-start ZIP missing required files")
        if any(not item.startswith(prefix) for item in z.namelist()):
            raise ValueError("Unsafe ZIP member path")
        if len(set(z.namelist()))!=len(z.namelist()):
            raise ValueError("Duplicate ZIP member")
        archived_orders=json.loads(z.read(prefix+"permutation_manifest.json"))["orders"]
        if archived_orders!=expected_orders:
            raise ValueError("Multi-start ZIP orders differ from uploaded optimizer map")
        if MULTI.exists():
            if digest(MULTI)!=stress["config"]["candidate_sha256"]:
                raise ValueError(f"Existing Multi-start candidate differs from GPU proof: {MULTI}. "
                                 "Move stale candidate aside; do NOT overwrite.")
            for n in ("manifest.json","int_eval.json"):
                if json.loads((MULTI/n).read_text(encoding="utf-8"))!=json.loads(z.read(prefix+n)):
                    raise ValueError(f"Existing Multi-start {n} inference metadata differs")
            # Files built on different PCs record different source absolute paths;
            # only the permutation mapping is semantically meaningful here.
            if json.loads((MULTI/"permutation_manifest.json").read_text(encoding="utf-8")).get("orders")!=expected_orders:
                raise ValueError("Existing Multi-start permutation mapping differs")
            for i in range(1,11):
                n=f"conv{i}_config.bin"
                if (MULTI/n).read_bytes()!=z.read(prefix+n):
                    raise ValueError(f"Existing Multi-start weights differ: {n}")
            print("PASS: previously installed Multi-start verified against GitHub ZIP")
        else:
            MULTI.mkdir(parents=True,exist_ok=False)
            for n in z.namelist():
                if n.endswith("/"):continue
                dst=MULTI/n[len(prefix):]
                # Archive permits only flat filenames, not nested traversal.
                if "/" in n[len(prefix):] or "\\" in n[len(prefix):]:
                    raise ValueError("Unsafe nested file in archive")
                dst.write_bytes(z.read(n))
            print("Installed Multi-start directly from verified GitHub ZIP")
    final=digest(MULTI)
    if final!=stress["config"]["candidate_sha256"]:
        raise ValueError("Multi-start SHA256 mismatch with completed 720-case output equivalence")
    if json.loads((SOURCE/"manifest.json").read_text(encoding="utf-8"))["model"]!=MODEL:
        raise ValueError("Original model metadata mismatch")
    print("PASS: Original + Frozen + Multi-start model preflight")
    print("Multi-start export SHA256:",final)
    print("All three models are kept separate. NO FPGA/JTAG/DDR access has occurred.")


def verify_existing_w4_canary(canary_path, build):
    """A real original-only run on the exact .bit, NOT an inferred board name."""
    rec = json.loads(canary_path.read_text(encoding="utf-8"))
    if rec.get("status") != "PHYSICAL_ORIGINAL_W4_CANARY_PASS":
        raise ValueError("Existing W4 .bit requires successful physical canary")
    if rec.get("physical_board_test_performed") is not True:
        raise ValueError("Canary does not attest physical FPGA testing")
    if Path(rec.get("build_path", "")).resolve() != build.resolve():
        raise ValueError("Canary refers to a different .bit build directory")
    actual = hashlib.sha256((build / "system_wrapper.bit").read_bytes()).hexdigest()
    if rec.get("bitstream_sha256") != actual:
        raise ValueError("Current .bit SHA256 differs from physical canary")
    if (rec.get("core_id") != "0x4d410303"
            or rec.get("fclk_mhz") != 50.0
            or rec.get("bitexact_mismatches") != 0
            or rec.get("model") != MODEL
            or rec.get("image") != "05.png"
            or rec.get("sigma") != 25
            or rec.get("mode") != 1
            or rec.get("historical_baseline_cycles") != 13289042):
        raise ValueError("Physical canary model/clock/core/baseline does not match")
    if not isinstance(rec.get("delta_pct"), (int, float)) or abs(rec["delta_pct"]) > 2:
        raise ValueError("Physical original-only canary exceeds 2% cycle drift")
    return actual


def board_one(label,directory,build,xsdb,image,clock):
    path={"original":SOURCE,"frozen":FROZEN,"multistart":MULTI}[label]
    cmd=[
        sys.executable,str(ROOT/"scripts"/"run_denoise.py"),
        "--model",MODEL,"--xsdb",str(xsdb),"--build",str(build),
        "--w4","--mode","1","--fclk",str(clock),
        "--set","Set12","--images",image,"--tile","65536",
        "--out",str(directory),"--board-dir",str(directory)+"_io"]
    if label!="original":cmd+=["--export-dir",str(path)]
    print(f"Physical FPGA run: {label}, {directory}",flush=True)
    subprocess.run(cmd,cwd=str(ROOT),check=True)
    report=directory/"report.json"
    if not report.is_file():raise RuntimeError(f"Missing physical board report: {report}")
    return report


def compare_one(root,ref,new,output):
    cmd=[
        sys.executable,str(ROOT/"scripts"/"q1_board_ab_compare.py"),
        "--baseline",str(ref),"--permuted",str(new),
        "--out",str(output)]
    subprocess.run(cmd,cwd=str(ROOT),check=True)
    return json.loads(output.read_text(encoding="utf-8"))


def summarize(out,results,clock):
    if not results:raise ValueError("No board measurements")
    lines=[
        "# Actual physical FPGA W4 core cycle A/B/C measurements",
        "",
        "All three models use the same physical W4 core bitstream, clock and image.",
        "These totals include measured PL core cycles and recorded stalls; they are",
        "NOT complete video processing end-to-end latency and NOT energy measurements.",
        "",
        "| Rep | Original cycles | Frozen cycles | Multi-start cycles | Frozen saved (%) | Multi-start saved (%) |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    def saved(x,y): return 100*(x-y)/x
    summary=[]
    for r in results:
        o,f,m=(r["cycles"][k] for k in ("original","frozen","multistart"))
        lines.append(f"| {r['rep']} | {o:,} | {f:,} | {m:,} | {saved(o,f):+.5f} | {saved(o,m):+.5f} |")
        summary.append(dict(rep=r["rep"],baseline=o,frozen=f,multistart=m,
                            frozen_saved_pct=saved(o,f),
                            multistart_saved_pct=saved(o,m),
                            multi_vs_frozen_pct=saved(f,m)))
    def agg(label):
        orig=sum(r["cycles"]["original"] for r in results)
        other=sum(r["cycles"][label] for r in results)
        return 100*(orig-other)/orig
    res=dict(status="PHYSICAL_3WAY_W4_CORE_CYCLE_COMPARISON",
             fclk_mhz=clock,replicates=len(results),
             frozen_total_pct_saved=agg("frozen"),
             multistart_total_pct_saved=agg("multistart"),
             repeat_rows=summary,
             caveats=[
                 "True physical core cycles with the specified bitstream; only useful with validated Smart ZYNQ SL PS DDR/MIO.",
                 "Not a measurement of PS im2col, JTAG setup, host postprocessing, end-to-end video latency, or power.",
                 "Per-run counter includes DMA stalls; report raw stall counters separately.",
                 "Measurement is for Set12 one image and noise seed0, not all 612 GPU conditions.",
                 "Do not compare full 10-layer measured savings against Conv2-9 modeled estimates as if denominators match."
             ])
    lines+=["",f"**Measured Frozen full-core saving**: {res['frozen_total_pct_saved']:+.5f}%.",
            f"**Measured Multi-start full-core saving**: {res['multistart_total_pct_saved']:+.5f}%.",
            "Interpret only after validating all per-layer board oracle checks.",
            ""]
    (out/"triplet_summary.json").write_text(json.dumps(res,indent=2)+"\n",encoding="utf-8")
    (out/"triplet_summary.md").write_text("\n".join(lines),encoding="utf-8")
    return res


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute",action="store_true")
    ap.add_argument("--board-verified",default="")
    ap.add_argument("--xsdb",type=Path)
    ap.add_argument("--build",type=Path)
    ap.add_argument("--existing-w4-canary",type=Path,default=None,
                    help="physical Original-only canary for the exact existing zed_v W4 build")
    ap.add_argument("--image",default="05.png")
    ap.add_argument("--fclk",type=float,default=50.0)
    ap.add_argument("--run-id",default="trial_01")
    ap.add_argument("--repeats",type=int,default=3)
    a=ap.parse_args()
    preflight()
    if not a.execute:
        print("PREFLIGHT COMPLETE: board was NOT accessed or programmed.")
        return
    # A successful same-.bit physical Original canary is evidence of operation
    # on the user's tested board, not vendor-certified Smart ZYNQ SL PS wiring.
    # Do not require the user to assert an unverified manufacturer preset.
    required_approval = CANARY_APPROVAL if a.existing_w4_canary is not None else APPROVAL
    if a.board_verified != required_approval:
        ap.error("Explicit physical board acknowledgement required: " + required_approval)
    if not a.xsdb or not a.build:
        ap.error("--xsdb and --build must be explicitly specified")
    xsdb=a.xsdb.resolve();build=a.build.resolve()
    if not xsdb.is_file() or not (build/"system_wrapper.bit").is_file():
        ap.error("Explicit xsdb path or approved W4 build/system_wrapper.bit missing")
    legacy = any(word in str(build).lower() for word in ("zed_v","zedboard"))
    bitstream_sha256 = hashlib.sha256((build / "system_wrapper.bit").read_bytes()).hexdigest()
    if legacy:
        if a.existing_w4_canary is None:
            ap.error("Legacy-named W4 requires a verified physical original-only "
                     "canary on the exact bitstream; refusing untested use")
        try:
            verified_sha = verify_existing_w4_canary(a.existing_w4_canary.resolve(),build)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            ap.error("Legacy W4 canary verification failed: " + str(exc))
        if verified_sha != bitstream_sha256:
            ap.error("Canary and current .bit SHA differ")
        print("Legacy-named build permitted ONLY after passed physical W4 canary:",
              a.existing_w4_canary.resolve())
    elif a.existing_w4_canary is not None:
        ap.error("Existing-W4 canary option is only for explicitly audited legacy build")

    if not 3<=a.repeats<=9:ap.error("Use 3-9 physical A/B/C repetitions")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}",a.run_id):
        ap.error("Unsafe run-id")
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.png",a.image):
        ap.error("Image filename must be a single PNG")
    if a.fclk!=50:ap.error("Use controlled 50 MHz clock")
    out=ROOT/"build"/"q1_bank_fpga_triplet"/a.run_id
    if out.exists():ap.error(f"Refusing to overwrite existing physical board trial: {out}")
    measurements=[]
    for rep in range(1,a.repeats+1):
        d=out/f"rep_{rep:02}"
        # Change run order across repetitions to reduce environmental confounding.
        order=(["original","frozen","multistart"] if rep%2 else
               ["multistart","frozen","original"])
        reports={}
        for name in order:
            reports[name]=board_one(name,d/name,build,xsdb,a.image,a.fclk)
        comp={}
        comp["frozen"]=compare_one(d,reports["original"],reports["frozen"],d/"original_vs_frozen.json")
        comp["multistart"]=compare_one(d,reports["original"],reports["multistart"],d/"original_vs_multistart.json")
        comp["multi_vs_frozen"]=compare_one(d,reports["frozen"],reports["multistart"],d/"frozen_vs_multistart.json")
        cycles={}
        for name,path in reports.items():
            rr=load_board(path)
            data=check_img(rr,path)
            cycles[name]=sum(int(z["cycles"]) for z in data["layers"])
        measurements.append(dict(rep=rep,run_order=order,cycles=cycles))
    summary=summarize(out,measurements,a.fclk)
    summary["physical_bitstream_sha256"]=bitstream_sha256
    summary["build_path"]=str(build)
    summary["original_only_canary"]=str(a.existing_w4_canary.resolve()) if legacy else None
    (out/"triplet_summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    print("PHYSICAL FPGA 3-WAY COMPLETE:",out/"triplet_summary.md")
    print("Measured Frozen full-network PL core cycles saved:",summary["frozen_total_pct_saved"])
    print("Measured Multi-start full-network PL core cycles saved:",summary["multistart_total_pct_saved"])


if __name__=="__main__":
    main()
