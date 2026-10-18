"""One-command Q1 FPGA paper experiment BATTERY, with provenance and safety.

Example (GPU/CPU and PHYSICAL FPGA, prompts once for the same proven board):
  python scripts/q1_all_experiments.py --stage all --xsdb "C:/Vivado/2026.1/Vivado/bin/xsdb.bat"

GPU ONLY:
  python scripts/q1_all_experiments.py --stage gpu

BOARD ONLY (on FPGA PC; existing canary & same physical board):
  python scripts/q1_all_experiments.py --stage fpga --xsdb "C:/Vivado/2026.1/Vivado/bin/xsdb.bat"

PLAN ONLY (no network, GPU, board or output mutation):
  python scripts/q1_all_experiments.py --stage plan

DEFAULT physical images: Set12 04,06,07,08,09,10,11,12 (never calibration 01-03
or previously published 05). Each image = 3 repetitions x 3 methods x 10
convolutions, so the full default is 72 model runs / 720 layer executions.
Command will take significant time; GPU studies can also take hours.
Use --images 04.png,06.png,08.png for a shorter first physical campaign.

Safety:
 * DO NOT assert success unless the script exits 0 and each report validates.
 * Never overwrites previous data or bitstream/export/checkpoint.
 * Existing complete GPU results are reused; resumable software scripts may
   use their own existing directories only when configurations match.
 * Physical trial only reused after its exact bitstream SHA, run reports,
   input image and A/B/C result structure have been checked.
 * New real FPGA flashing requires SAME board/cabling and interactive consent.
 * No synthetic 'ideal' results, predicted speedup renamed as physical, nor
   unimplemented second-CNN/E2E stage counted as complete.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from q1_novelty_bsd68_launcher import select_output, validate_complete

CORE_SHA = "11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6"
DEFAULT_IMAGES = ("04.png","06.png","07.png","08.png","09.png","10.png","11.png","12.png")
APPROVAL = "SAME_PHYSICAL_BOARD_W4_CANARY_VERIFIED"
FPGA_RUNS = ROOT / "build" / "q1_bank_fpga_triplet"
BATCH_ROOT = ROOT / "build" / "q1_all_experiments"
CANARY = ROOT / "build" / "q1_existing_w4_canary" / "canary_01" / "canary.json"
BUILD = ROOT / "build" / "zed_v4_p16_t4_w4_1792234898"
FROZEN = ROOT / "build" / "q1_reviewer_bank" / "report.json"


def new_dir(base: Path) -> Path:
    for i in range(1,1001):
        candidate = base if i == 1 else base.with_name(base.name + f"_{i:02}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("No free run directory within 1000 candidate names")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def valid_gpu_summary(kind: str, path: Path) -> bool:
    data = read_json(path / "summary.json")
    if not isinstance(data,dict) or data.get("complete") is not True:
        return False
    if kind == "controls":
        return (data.get("dataset") == "BSD68"
                and data.get("expected_image_method_rows") == 68*9*9
                and data.get("completed_image_method_rows") == 68*9*9
                and (path/"method_config.json").is_file()
                and (path/"per_condition.csv").is_file()
                and (data.get("experiment_config") or {}).get("random_count") == 20
                and (data.get("experiment_config") or {}).get("max_images") == 0)
    if kind == "fair":
        return (data.get("expected_image_conditions") == 68*9
                and data.get("actual_image_conditions") == 68*9
                and data.get("budget_is_total_cost_evaluations_including_initialization") is True
                and data.get("optimisation_budgets") == [400,800,2000]
                and data.get("optimisation_seeds") == [42,101,202,303,404]
                and (path/"run_config.json").is_file()
                and (path/"method_summary.csv").is_file())
    if kind == "mechanism":
        return (data.get("expected_image_conditions") == 68*9
                and data.get("image_conditions") == 68*9
                and (path/"run_config.json").is_file()
                and (path/"per_image_layer.csv").is_file())
    return False


def select_gpu_output(kind: str, folder: str):
    base=ROOT/"build"/folder
    # Look through prior completed outputs too (no accidental rerun).
    for i in range(1,101):
        p = base if i == 1 else base.with_name(base.name + f"_{i:02}")
        if p.is_dir() and valid_gpu_summary(kind,p):
            return "reuse",p
    # Resume only original project's built-in resumable layout, when an existing
    # config is present; let its own strict config assertion reject mismatch.
    if base.is_dir() and (base/"run_config.json" if kind!="controls" else base/"method_config.json").is_file():
        return "resume",base
    return "run",new_dir(base)


def checked_physical(trial: Path, image: str):
    """Reuses only exact model/image + SHA + 3x3x10 physical board records."""
    summ=read_json(trial/"triplet_summary.json")
    if not isinstance(summ,dict):
        return None
    if (summ.get("status")!="PHYSICAL_3WAY_W4_CORE_CYCLE_COMPARISON"
            or summ.get("physical_bitstream_sha256")!=CORE_SHA
            or summ.get("replicates")!=3 or summ.get("fclk_mhz")!=50.0
            or len(summ.get("repeat_rows",[]))!=3):
        return None
    from q1_board_ab_compare import load,check_img
    for i,entry in enumerate(summ["repeat_rows"],1):
        if entry.get("rep")!=i:
            return None
        rep = trial/f"rep_{i:02}"
        for model, field in [("original","baseline"),("frozen","frozen"),("multistart","multistart")]:
            report=rep/model/"report.json"
            try:
                rr=load(report)
                row=check_img(rr,report)
            except (ValueError,OSError,KeyError,TypeError):
                return None
            if (rr.get("model")!="dn_d10_c32_us_fx_qat"
                    or rr.get("sigma")!=25 or rr.get("set")!="Set12"
                    or row.get("image")!=image
                    or not all(layer.get("core_id")==["0x4d410303"]
                               and layer.get("fclk_mhz")==[50.0] for layer in row["layers"])):
                return None
            if (entry.get(field) != sum(int(t["cycles"]) for t in row["layers"])
                    or entry.get("in_stall",{}).get(model) != sum(int(t["in_stall"]) for t in row["layers"])
                    or entry.get("out_stall",{}).get(model) != sum(int(t["out_stall"]) for t in row["layers"])):
                return None
        # Independent final PNG byte equality; QAT oracle pass by itself
        # does not prove the permuted models have the same intended image.
        stem=Path(image).stem
        pngs=[rep/model/f"{stem}_denoised.png" for model in ("original","frozen","multistart")]
        if not all(p.is_file() for p in pngs):
            return None
        if len({hashlib.sha256(p.read_bytes()).digest() for p in pngs}) != 1:
            return None
        for pair in ("original_vs_frozen.json","original_vs_multistart.json","frozen_vs_multistart.json"):
            c=read_json(rep/pair)
            if not isinstance(c,dict) or c.get("status")!="PHYSICAL_W4_CORE_CYCLE_COMPARISON" or c.get("bit_exact_mismatches")!=0:
                return None
    return summ


def find_physical_reusable(image: str):
    if not FPGA_RUNS.is_dir():
        return None
    for trial in sorted(FPGA_RUNS.iterdir()):
        if not trial.is_dir():
            continue
        # Do not confuse the 05.png published run with other image trials.
        result=checked_physical(trial,image)
        if result is not None:
            return trial,result
    return None


def next_physical_id(image: str):
    root=FPGA_RUNS/("q1all_set12_"+image.split(".")[0])
    directory=new_dir(root)
    return directory.name


def parse_images(raw: str):
    names=tuple(x.strip() for x in raw.split(",") if x.strip())
    if not names or len(names)!=len(set(names)):
        raise ValueError("Empty or duplicated physical image names")
    accepted={f"{i:02}.png" for i in range(4,13)} - {"05.png"}
    if any(name not in accepted for name in names):
        raise ValueError("Only untouched Set12 04,06,07,08,09,10,11,12 are supported")
    return names


def verify_board(xsdb: Path):
    if not xsdb.is_file():
        raise RuntimeError("Explicit XSDB path not found: "+str(xsdb))
    bit=BUILD/"system_wrapper.bit"
    if not bit.is_file():
        raise RuntimeError("W4 bitstream missing: "+str(bit))
    sha=hashlib.sha256(bit.read_bytes()).hexdigest()
    if sha!=CORE_SHA:
        raise RuntimeError("Refusing to reprogram: W4 .bit SHA differs from successful physical canary")
    from q1_fpga_triplet import verify_existing_w4_canary
    verification=verify_existing_w4_canary(CANARY,BUILD)
    if verification != sha:
        raise RuntimeError("Canary verification mismatch")
    return sha


def run_logged(command,log: Path):
    log.parent.mkdir(parents=True,exist_ok=True)
    print("\nRUN:",subprocess.list2cmdline([str(v) for v in command]),flush=True)
    with log.open("w",encoding="utf-8") as f:
        f.write("Command: "+subprocess.list2cmdline([str(v) for v in command])+"\n")
        proc=subprocess.Popen([str(x) for x in command],cwd=str(ROOT),
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              encoding="utf-8",errors="replace",bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line,end="",flush=True)
            f.write(line)
        code=proc.wait()
        f.write(f"\nExit code: {code}\n")
    if code:
        raise RuntimeError("Experiment exited with code "+str(code)+"; inspect "+str(log))


def experiment_plan(stage,images):
    print("=== Q1 comprehensive paper experiment plan ===")
    if stage in ("plan","gpu","all"):
        print("GPU 1: previously completed joint-vs-marginal BSD68 68x3x3x4 (reuse if valid)")
        print("GPU 2: 20 random / density-sort / greedy / anneal / multi-start / risk controls")
        print("GPU 3: same-budget Greedy/Anneal/Multi-start across 5 seeds")
        print("GPU 4: max-bank/floor-bound and relaxed oracle headroom across BSD68")
        print("GPU controls: W1 and dense only ANALYTICAL unless a separate physical run is built")
    if stage in ("plan","fpga","all"):
        print(f"PHYSICAL: {len(images)} unused Set12 images × 3 repetitions × 3 methods = {len(images)*9} executions")
        print("Images:",",".join(images))
        print("Each physical trial programs the SAME W4 50MHz core and verifies 10 Conv oracle results")
    print("BLOCKED: 2nd CNN real model permutation+bitexact export requires model-specific development")
    print("BLOCKED: independent PS+DDR+PL end-to-end timing/energy requires additional driver/instrumentation")
    print("No result is assumed positive; failures are preserved.")


def write_status(dest, results, stage):
    dest.mkdir(parents=True,exist_ok=True)
    (dest/"status.json").write_text(json.dumps(dict(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        requested_stage=stage,
        stages=results,
        additional_required=[
            "Second CNN quantized parameter-preserving export, formal oracle and physical tests",
            "End-to-end PS+DDR+PL timing instrumentation (not represented by core cycles)",
            "Optional physical W1/dense negative-control runs on a verified design",
        ],
        success_is_not_assumed=True),indent=2,ensure_ascii=False)+"\n",encoding="utf-8")


def aggregate_physical(output: Path, observations):
    if not observations:
        return
    fields=["image","run_id","repetitions","physical_original_cycles",
            "physical_frozen_cycles","physical_multistart_cycles",
            "frozen_saved_pct","multistart_saved_pct",
            "frozen_conv2to9_saved_pct","multistart_conv2to9_saved_pct",
            "bitstream_sha256","status"]
    rows=[]
    for name,run,report in observations:
        repeats=report["repeat_rows"]
        # Cycle-based weighting prevents spurious arithmetic mean of per-run percentages.
        totals={k:sum(int(row[k]) for row in repeats) for k in ("baseline","frozen","multistart")}
        rows.append(dict(
            image=name,run_id=run,repetitions=len(repeats),
            physical_original_cycles=totals["baseline"],
            physical_frozen_cycles=totals["frozen"],
            physical_multistart_cycles=totals["multistart"],
            frozen_saved_pct=100*(totals["baseline"]-totals["frozen"])/totals["baseline"],
            multistart_saved_pct=100*(totals["baseline"]-totals["multistart"])/totals["baseline"],
            frozen_conv2to9_saved_pct=report["frozen_conv2to9_pct_saved"],
            multistart_conv2to9_saved_pct=report["multistart_conv2to9_pct_saved"],
            bitstream_sha256=report["physical_bitstream_sha256"],status="MEASURED_FPGA_W4_CORE_ONLY"))
    with (output/"physical_per_image.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    total=sum(row["physical_original_cycles"] for row in rows)
    multi=sum(row["physical_multistart_cycles"] for row in rows)
    image_values=[r["multistart_saved_pct"] for r in rows]
    recap=dict(
        physical_images=len(rows),physical_repetitions_per_image=3,
        total_original_cycles=total,total_multistart_cycles=multi,
        pooled_multistart_saved_pct=100*(total-multi)/total,
        image_mean_saved_pct=sum(image_values)/len(image_values),
        min_saved_pct=min(image_values),max_saved_pct=max(image_values),
        physical_scope="W4 PL core cycles including DMA stalls; not E2E or power",
        clean_image_n=len(rows),not_independent_repetitions=3,
        rows=rows)
    (output/"physical_summary.json").write_text(json.dumps(recap,indent=2)+"\n",encoding="utf-8")



def package_evidence(output: Path, stages) -> Path:
    """Small, auditable one-file bundle: no images, huge NPZ, bitstream or weights.

    Reports remain on the experiment PC; this ZIP is a *summary evidence bundle*,
    not a full archival replacement for raw board data.
    """
    dest=output/"Q1_EVIDENCE_BUNDLE.zip"
    if dest.exists():
        raise RuntimeError("Refusing to overwrite existing evidence bundle")
    picks={}
    for filename in ("status.json","physical_per_image.csv","physical_summary.json"):
        path=output/filename
        if path.is_file():
            picks[filename]=path
    for name in ("joint_marginal_bsd68","controls","fair","mechanism"):
        entry=stages.get(name)
        if not entry or entry.get("status") not in ("COMPLETED","VERIFIED_REUSED"):
            continue
        d=Path(entry["directory"])
        for filename in ("summary.json","per_condition.csv","per_image.csv",
                         "method_summary.csv","fair_paired.csv","per_image_layer.csv",
                         "groups.json","run_config.json","method_config.json"):
            p=d/filename
            if p.is_file():
                picks["gpu/"+name+"/"+filename]=p
    for stage,entry in stages.items():
        if not stage.startswith("fpga_") or entry.get("status") not in ("COMPLETED","VERIFIED_REUSED"):
            continue
        d=Path(entry["directory"])
        runid=d.name
        for filename in ("triplet_summary.json","triplet_summary.md"):
            p=d/filename
            if p.is_file():
                picks["physical/"+runid+"/"+filename]=p
        for rep in range(1,4):
            for name in ("original","frozen","multistart"):
                p=d/f"rep_{rep:02}"/name/"report.json"
                if p.is_file():
                    picks["physical/"+runid+f"/rep_{rep:02}/"+name+"/report.json"]=p
            for filename in ("original_vs_frozen.json","original_vs_multistart.json",
                             "frozen_vs_multistart.json"):
                p=d/f"rep_{rep:02}"/filename
                if p.is_file():
                    picks["physical/"+runid+f"/rep_{rep:02}/"+filename]=p
    manifest=dict(
        purpose="Portable Q1 experiment SUMMARY evidence bundle, not full raw data archive",
        created_utc=datetime.now(timezone.utc).isoformat(),
        source_paper_stages=list(stages),
        includes_full_feature_maps=False,
        includes_bitstream_or_model_weights=False,
        model_estimates_are_not_fpga_measurements=True,
        members={},
    )
    with zipfile.ZipFile(dest,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for arcname,p in sorted(picks.items()):
            if p.stat().st_size > 80*1024*1024:
                # Large intermediate artifacts should be preserved at their
                # original locations, not silently used as evidence.
                manifest["members"][arcname]=dict(included=False,
                                    reason="larger than 80 MiB",source=str(p))
                continue
            data=p.read_bytes()
            z.writestr(arcname,data)
            manifest["members"][arcname]=dict(
                included=True,sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data),source=str(p))
        z.writestr("evidence_manifest.json",json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
    with zipfile.ZipFile(dest) as z:
        bad=z.testzip()
        if bad is not None:
            raise RuntimeError("Evidence bundle failed ZIP CRC verification: "+bad)
    print("ONE FILE TO SHARE:",dest,flush=True)
    return dest



def ensure_frozen_calibration_report():
    """Rehydrate ONLY historical Frozen channel groups, never refit on BSD68."""
    from q1_fpga_bank_ab import verify_archive
    verify_archive()   # checks published archive SHA256SUMS and exact permutation orders
    frozen_manifest=ROOT/"research"/"q1_codesign"/"bank_export_perm.json"
    spec=read_json(frozen_manifest)
    if not isinstance(spec,dict) or spec.get("model")!="dn_d10_c32_us_fx_qat":
        raise RuntimeError("Malformed published Frozen permutation definitions")
    orders=spec.get("orders")
    if not isinstance(orders,dict) or set(orders)!={f"conv{i}" for i in range(1,9)}:
        raise RuntimeError("Frozen published manifest must have 8 exact predecessor orders")
    layers=[]
    for li in range(1,9):
        order=orders[f"conv{li}"]
        if len(order)!=32 or sorted(order)!=list(range(32)):
            raise RuntimeError("Published Frozen permutation is not a valid 32-channel order")
        group=[None]*32
        for j,ch in enumerate(order):
            group[ch]=j%4
        if [group.count(i) for i in range(4)]!=[8]*4:
            raise RuntimeError("Published Frozen bank groups are not balanced")
        layers.append(dict(layer=f"conv{li+1}",original_channel_order=order,
                           group_of_original_channel=group))
    if FROZEN.is_file():
        current=read_json(FROZEN)
        if (not isinstance(current,dict) or current.get("model")!="dn_d10_c32_us_fx_qat"
                or not isinstance(current.get("layers"),list)):
            raise RuntimeError("Existing Frozen calibration report is corrupt; refusing overwrite")
        existing={t["layer"]:t for t in current["layers"]}
        if set(existing)!={t["layer"] for t in layers}:
            raise RuntimeError("Existing Frozen layer list incompatible with published mapping")
        for t in layers:
            actual=existing[t["layer"]]
            if (actual.get("group_of_original_channel")!=t["group_of_original_channel"]
                    or actual.get("original_channel_order")!=t["original_channel_order"]):
                raise RuntimeError("Existing Frozen report differs from published, bit-exact FPGA-approved mapping")
        print("PASS original Frozen calibration report matches published verified artifact",flush=True)
    else:
        # The original source script may not have been run on this particular
        # PC, even though all weights/perm groups are already in GitHub.
        # Recreate its minimal immutable mapping record, NO new search or score.
        FROZEN.parent.mkdir(parents=True,exist_ok=True)
        obj=dict(model="dn_d10_c32_us_fx_qat",data_set="Set12",
                 calib_images=["01.png"],layers=layers,
                 source="RECONSTRUCTED_EXACT_HISTORICAL_FROZEN_PERMUTATION_FROM_VERIFIED_ARCHIVE",
                 caveat="Only historical bank assignments reconstructed. No model training/search/performance estimated by this file.")
        FROZEN.write_text(json.dumps(obj,indent=2)+"\n",encoding="utf-8")
        print("PASS historical Frozen bank groups restored without refitting:",FROZEN,flush=True)
    return FROZEN


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage",choices=("plan","gpu","fpga","all"),default="plan")
    ap.add_argument("--xsdb",type=Path,default=None)
    ap.add_argument("--images",default=",".join(DEFAULT_IMAGES),
                    help="Comma-separated unseen Set12 image names, excluding calibration 01/02/03 and earlier 05")
    ap.add_argument("--batch-id",default="campaign")
    args=ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}",args.batch_id):
        ap.error("Unsafe batch-id")
    try:
        images=parse_images(args.images)
    except ValueError as exc:
        ap.error(str(exc))
    experiment_plan(args.stage,images)
    if args.stage=="plan":
        return 0
    if args.stage in ("all","fpga"):
        if args.xsdb is None:
            ap.error("PHYSICAL FPGA requires --xsdb and interactive operator verification; try --stage gpu")
        try:
            sha=verify_board(args.xsdb.resolve())
        except (RuntimeError,ValueError,OSError) as exc:
            ap.error(str(exc))
        # Fail fast on invalid hardware inputs, but defer physical operator
        # approval until JUST BEFORE programming (GPU stages can take hours).
        print("FPGA preflight: canary/.bit SHA256 verified. Operator approval will be requested just before hardware execution.",flush=True)
    output=new_dir(BATCH_ROOT/args.batch_id)
    output.mkdir(parents=True,exist_ok=False)
    print("AUDIT DIRECTORY:",output)
    stages={}
    write_status(output,stages,args.stage)
    try:
        if args.stage in ("all","gpu"):
            ensure_frozen_calibration_report()
            action,folder,_,_=select_output(ROOT/"build","full",False)
            if action=="reuse":
                stages["joint_marginal_bsd68"]=dict(status="VERIFIED_REUSED",directory=str(folder))
            else:
                run_logged([sys.executable,"-u",ROOT/"scripts"/"q1_novelty_bsd68_launcher.py","full"],
                           output/"logs"/"joint_marginal.log")
                action,folder,_,_=select_output(ROOT/"build","full",False)
                if action!="reuse":
                    raise RuntimeError("Joint/marginal full study did not create a verified complete result")
                stages["joint_marginal_bsd68"]=dict(status="COMPLETED",directory=str(folder))
            write_status(output,stages,args.stage)
            tasks=[
                ("controls","q1_gpu_deadline_full","q1_gpu_deadline_suite.py"),
                ("fair","q1_gpu_fair_budget","q1_fair_budget.py"),
                ("mechanism","q1_gpu_bank_mechanism","q1_bank_mechanism.py"),
            ]
            for kind,dirname,script in tasks:
                choice,p=select_gpu_output(kind,dirname)
                if choice=="reuse":
                    print("REUSE validated GPU result:",p,flush=True)
                    stages[kind]=dict(status="VERIFIED_REUSED",directory=str(p))
                else:
                    run_logged([sys.executable,"-u",ROOT/"scripts"/script,"--out",p],
                               output/"logs"/f"{kind}.log")
                    if not valid_gpu_summary(kind,p):
                        raise RuntimeError("GPU suite did not finish full BSD68 coverage: "+str(p))
                    stages[kind]=dict(status="COMPLETED",directory=str(p))
                write_status(output,stages,args.stage)
        if args.stage in ("all","fpga"):
            # GPU preparation may have taken hours; re-check SHA and require
            # a fresh, interactive confirmation right before actual flashing.
            sha=verify_board(args.xsdb.resolve())
            print("\nWARNING: THIS WILL REPROGRAM YOUR CONNECTED FPGA.",flush=True)
            print("Keep the EXACT previously canary-verified physical board and cabling.",flush=True)
            print("Verified bitstream SHA256:",sha,flush=True)
            print("Physical CNN runs:",len(images)*9,flush=True)
            if not sys.stdin.isatty():
                raise RuntimeError("Refusing noninteractive physical FPGA programming")
            consent=input("Type SAME_PHYSICAL_BOARD_W4_CANARY_VERIFIED to approve: ").strip()
            if consent!=APPROVAL:
                raise RuntimeError("Operator did not approve physical FPGA programming")
            observed=[]
            for image in images:
                found=find_physical_reusable(image)
                if found:
                    trial,summary=found
                    print("REUSE verified PHYSICAL board trial:",trial,flush=True)
                    state="VERIFIED_REUSED"
                else:
                    runid=next_physical_id(image)
                    print("NEW physical 3x3 trial:",image,"->",runid,flush=True)
                    run_logged([sys.executable,"-u",ROOT/"scripts"/"q1_fpga_triplet.py",
                                "--execute","--board-verified",APPROVAL,
                                "--existing-w4-canary",CANARY,
                                "--xsdb",args.xsdb.resolve(),"--build",BUILD,
                                "--run-id",runid,"--repeats","3",
                                "--image",image,"--fclk","50"],
                               output/"logs"/f"set12_{image.split('.')[0]}.log")
                    trial=FPGA_RUNS/runid
                    summary=checked_physical(trial,image)
                    if summary is None:
                        raise RuntimeError("Physical output failed post-run raw report validation: "+str(trial))
                    state="COMPLETED"
                stages["fpga_"+image]=dict(status=state,directory=str(trial),
                                          frozen_saved_pct=summary["frozen_total_pct_saved"],
                                          multistart_saved_pct=summary["multistart_total_pct_saved"])
                observed.append((image,trial.name,summary))
                aggregate_physical(output,observed)
                write_status(output,stages,args.stage)
        stages["second_cnn"]=dict(status="NOT_IMPLEMENTED",
                    reason="This workflow has no validated 64ch/other-topology channel permutation/export + FPGA test")
        stages["e2e"]=dict(status="NOT_IMPLEMENTED",
                    reason="No PS-DDR-PL total latency/energy instrumentation integrated")
        write_status(output,stages,args.stage)
        package_evidence(output,stages)
        print("BATCH FINISHED, completed supported stages. Additional development gates remain.")
        print("AUDIT:",output/"status.json")
        return 0
    except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as exc:
        stages["campaign_failure"]=dict(status="FAILED",reason=str(exc))
        write_status(output,stages,args.stage)
        try:
            package_evidence(output,stages)
        except (OSError,ValueError,RuntimeError) as packaging_error:
            print("Partial evidence bundle was not created:",packaging_error,file=sys.stderr)
        print("STOPPED SAFELY:",exc,file=sys.stderr,flush=True)
        print("Earlier completed results kept intact; audit:",output/"status.json",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
