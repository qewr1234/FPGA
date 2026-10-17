"""Verify a finished multi-start greedy QAT export and publish its local ZIP.

Must be run AFTER:
  1. The original 612-condition GPU sweep was completed.
  2. scripts/q1_reviewer_export.py exported actual INT8 parameters.
  3. scripts/q1_gpu_bitexact_stress.py completed all 720 cases, 0 pixel diffs.

No optimization, no CNN training and no physical FPGA access.
The ZIP is written locally, never automatically pushed to Github.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
MODEL="dn_d10_c32_us_fx_qat"
SWEEP=ROOT/"build"/"q1_gpu_deadline_full"
DEFAULT_MODEL=ROOT/"build"/"q1_multistart_export"/MODEL
DEFAULT_STRESS=ROOT/"build"/"q1_gpu_multistart_bitexact_stress"/"summary.json"
DEFAULT_ZIP=ROOT/"build"/"q1_multistart_verified_export_20261018.zip"
ORIGINAL=ROOT/"denoise"/"export"/MODEL


def assert_equal(given,reference,message):
    if given!=reference:raise AssertionError(f"{message}: expected {reference!r}, got {given!r}")


def export_digest(folder):
    h=hashlib.sha256()
    for p in sorted(folder.glob("conv*_config.bin")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    h.update((folder/"manifest.json").read_bytes())
    return h.hexdigest()


def load_json(p):
    if not p.is_file():raise FileNotFoundError(f"Missing {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def validate_mapping():
    conf=load_json(SWEEP/"method_config.json")
    report=load_json(SWEEP/"export_multistart_greedy.json")
    summary=load_json(SWEEP/"summary.json")
    assert_equal(summary.get("complete"),True,"Full GPU sweep not complete")
    assert_equal(summary.get("completed_image_method_rows"),5508,"Full sweep row count")
    assert_equal(report.get("model"),MODEL,"Export model")
    by_group=conf["group_assignments"]["multistart_greedy"]
    expected_names={f"conv{i}" for i in range(2,10)}
    assert_equal(set(by_group),expected_names,"Calibrated layer assignments")
    assert_equal(set(x["layer"] for x in report["layers"]),expected_names,"Export report layers")
    if conf["experiment_config"]!=summary["experiment_config"]:
        raise AssertionError("Mismatch between optimizer config and summary")
    for entry in report["layers"]:
        name=entry["layer"]
        group=[int(n) for n in entry["group_of_original_channel"]]
        order=[int(n) for n in entry["original_channel_order"]]
        assert_equal(group,by_group[name],f"{name}: group assignment")
        if len(group)!=32 or sorted(group)!=sorted([0,1,2,3]*8):
            raise AssertionError(f"{name}: invalid balanced bank group")
        if sorted(order)!=list(range(32)) or len(order)!=32:
            raise AssertionError(f"{name}: invalid permutation order")
        if [group[i] for i in order]!=[i%4 for i in range(32)]:
            raise AssertionError(f"{name}: order and grouping conflict")
    return report,summary


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate",type=Path,default=DEFAULT_MODEL)
    ap.add_argument("--stress",type=Path,default=DEFAULT_STRESS)
    ap.add_argument("--out",type=Path,default=DEFAULT_ZIP)
    a=ap.parse_args()
    report,summary=validate_mapping()
    candidate=a.candidate.resolve()
    original=ORIGINAL.resolve()
    if candidate==original:raise AssertionError("Original model cannot be replaced")
    if not candidate.is_dir():raise FileNotFoundError(f"No exported INT8 candidate: {candidate}")
    if not (candidate/"bitexact_report.json").is_file():
        raise FileNotFoundError("Missing initial 2-image full INT8 CPU verification")
    two=load_json(candidate/"bitexact_report.json")
    if two.get("status")!="PASS_CPU_FULL_IMAGE_ONLY" or any(r.get("mismatches") for r in two["images"]):
        raise AssertionError("Initial CPU full image INT8 verification did not pass")
    stress=load_json(a.stress)
    assert_equal(stress.get("experiment_complete"),True,"720-condition bit exact stress")
    assert_equal(stress.get("images_conditions_checked"),720,"Expected stress image conditions")
    assert_equal(stress.get("total_mismatched_pixels"),0,"Pixels must not change")
    cfg=stress["config"]
    assert_equal(cfg["candidate_sha256"],export_digest(candidate),"Candidate export not same as stress run")
    assert_equal(cfg["original_sha256"],export_digest(original),"Original export not same as stress run")
    assert_equal(cfg["sets"],["BSD68","Set12"],"Stress datasets")
    assert_equal(cfg["sigmas"],[15,25,50],"Stress sigmas")
    assert_equal(cfg["seeds"],[0,1,2],"Stress RNG seeds")
    assert_equal(cfg["max_images"],0,"Stress must be full-size")
    perms=load_json(candidate/"permutation_manifest.json")["orders"]
    if set(perms)!={f"conv{i}" for i in range(1,9)}:
        raise AssertionError("Physical INT8 exporter did not reorder 8 hidden maps")
    for ent in report["layers"]:
        producer="conv"+str(int(ent["layer"][4:])-1)
        assert_equal(perms[producer],ent["original_channel_order"],
                     f"{producer} output order differs from optimizer")
    needed=("manifest.json","int_eval.json","permutation_manifest.json",
            "bitexact_report.json")+tuple(f"conv{i}_config.bin" for i in range(1,11))
    for name in needed:
        if not (candidate/name).is_file():
            raise FileNotFoundError(f"Candidate missing {name}")
    score=next(x for x in summary["overall"] if x["method"]=="multistart_greedy")
    provenance=dict(
        status="PASS_CPU_GPU_FULL_IMAGE_EXACTNESS_720",
        model=MODEL,
        method="multistart_greedy",
        source_model=f"denoise/export/{MODEL}",
        calibration="Set12 01/02/03 sigma25 seed0/1",
        recorded_gpu_core_coefficient_reduction_pct=score["estimated_cycle_reduction_pct"],
        reported_interval=score["image_cluster_bootstrap_ci95_pct"],
        experimental_reference_only="W4 sparse Conv2-9 cycle coefficient, no FPGA measurement",
        candidate_export_sha256=cfg["candidate_sha256"],
        original_export_sha256=cfg["original_sha256"],
        stress_complete=stress["experiment_complete"],
        stress_image_conditions=stress["images_conditions_checked"],
        stress_mismatches=stress["total_mismatched_pixels"],
        description="Paper experiment candidate; avoid overwriting the frozen_01 original or existing board reports.")
    a.out.parent.mkdir(parents=True,exist_ok=True)
    (candidate/"q1_multistart_provenance.json").write_text(
        json.dumps(provenance,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with zipfile.ZipFile(a.out,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as zipout:
        for name in needed+("q1_multistart_provenance.json",):
            zipout.write(candidate/name,arcname=f"{MODEL}/{name}")
    with zipfile.ZipFile(a.out) as check:
        if check.testzip() is not None:raise AssertionError("ZIP CRC error")
        if len(check.namelist())!=len(needed)+1:raise AssertionError("ZIP members count wrong")
    print("PASS: multistart optimizer report equals calibration map, exported weights "
          "match exact 720-case stress test; previous model left untouched")
    print(f"Output ZIP: {a.out.resolve()} ({a.out.stat().st_size:,} bytes)")
    print("ZIP SHA256:",hashlib.sha256(a.out.read_bytes()).hexdigest())
    print("To publish this EXACT learned permutation to GitHub, share "
          "build/q1_gpu_deadline_full/export_multistart_greedy.json.")
    print("No actual FPGA acceleration or novelty demonstrated.")


if __name__=="__main__":
    main()
