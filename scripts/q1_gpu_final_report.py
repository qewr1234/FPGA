"""Aggregate actual GPU/FPGA report files into a conservative research memo.
Never invents results: absent or incomplete experiments are marked explicitly.
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"build"
OUT=BUILD/"q1_gpu_deadline_final"


def read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def fmt(value):
    if isinstance(value,(int,float)): return f"{value:.3f}"
    return "N/A"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    hold=read(BUILD/"q1_reviewer_holdout"/"report.json")
    bit=read(BUILD/"q1_reviewer_bitexact_holdout"/"report.json")
    full=read(BUILD/"q1_gpu_deadline_full"/"summary.json")
    stress=read(BUILD/"q1_gpu_bitexact_stress"/"summary.json")
    arch={
        "64-channel QAT":read(BUILD/"q1_gpu_architectures"/"dn_d10_c64_us_es_qat"/"summary.json"),
        "maxout QAT":read(BUILD/"q1_gpu_architectures"/"dn_d10_c32_us_mo_fx_qat"/"summary.json"),
    }
    paper=[
        "# 2026-10-18 GPU research evidence audit",
        "",
        "All numbers below come from actual report JSON files. No invented results.",
        "CUDA speed or modeled PL cycle reductions are NOT measured FPGA acceleration.",
        "",
        "## Frozen bank permutation initial evidence",
        "",
        f"- Holdout: {'available' if hold else 'missing'}",
        f"- Original-versus-reordered pixel equality: {'available' if bit else 'missing'}",
    ]
    if hold:
        paper.extend([
            f"- BSD68 images: {hold.get('image_count')}; improved: {hold.get('per_image_positive')}",
            f"- Conv2-9 modeled window coefficient reduction: {fmt(hold.get('estimated_layer_cycle_reduction_pct'))}%",
            f"- Descriptive image-bootstrap CI: {hold.get('descriptive_image_bootstrap_ci95_pct')}",
        ])
    if bit:
        paper.append(f"- Output mismatches on {bit.get('images_checked')} images: {bit.get('pixel_mismatches')}")
    paper.extend(["","## Optimizer baselines and multiple noise realizations",""])
    if full:
        paper.append(f"- Complete: {full.get('complete')} "
                     f"({full.get('completed_image_method_rows')}/{full.get('expected_image_method_rows')} rows)")
        paper.extend(["","| Method | Modeled saved cycles (%) | Cluster bootstrap interval (%) |",
                      "|---|---:|---|"])
        for r in full.get("overall",[]):
            paper.append(f"| {r['method']} | {fmt(r.get('estimated_cycle_reduction_pct'))} | "
                         f"{r.get('image_cluster_bootstrap_ci95_pct')} |")
        paper.extend(["","### Per noise sigma and seed","",
                      "| Sigma | Seed | Method | Images | Reduction (%) |",
                      "|---:|---:|---|---:|---:|"])
        for r in full.get("per_condition",[]):
            paper.append(f"| {r['sigma']} | {r['seed']} | {r['method']} | "
                         f"{r['images']} | {fmt(r.get('estimated_core_coeff_cycle_gain_pct'))} |")
    else:
        paper.append("- No full GPU baseline sweep report available.")
    paper.extend(["","## Transfer to other QAT CNNs",""])
    for name,r in arch.items():
        if not r:
            paper.append(f"- {name}: missing")
            continue
        paper.append(f"- {name}: complete={r.get('complete')} "
                     f"({r.get('num_image_condition_rows')}/{r.get('expected_image_condition_rows')})")
        for m,stats in r.get("methods",{}).items():
            paper.append(f"  - {m}: {fmt(stats.get('estimated_cycle_reduction_pct'))}% modeled")
    paper.extend(["","## Multi-sigma multi-seed output equivalence",""])
    if stress:
        paper.append(f"- Complete: {stress.get('experiment_complete')}, "
                     f"conditions={stress.get('images_conditions_checked')}/"
                     f"{stress.get('images_conditions_expected')}, "
                     f"pixel mismatches={stress.get('total_mismatched_pixels')}")
    else: paper.append("- Extended bit-exact stress: missing")
    paper.extend(["","## Physical FPGA gate",""])
    measured=list((BUILD/"q1_bank_fpga_runs").glob("*/pair_*/comparison.json"))
    if measured:
        for p in sorted(measured):
            r=read(p)
            paper.append(f"- {p.relative_to(ROOT)}: measured W4 core-cycle saving "
                         f"{fmt(r.get('total_pct_saved'))}%")
    else: paper.append("- NO physical reordered FPGA A/B run reported.")
    paper.extend([
        "",
        "## Strict scientific limitations",
        "",
        "1. All GPU percentages are W4 core cycle model coefficients for Conv2-9, not FPGA throughput.",
        "2. Different AWGN draws are not independent models; image-cluster bootstrap is descriptive.",
        "3. Full GPU model transfer to maxout is virtual only; a bit-exact maxout export is not established.",
        "4. Set12 01/02/03 calibration is not a separate Train400 calibration split.",
        "5. No new hardware-aware channel permutation novelty is proven by these experiments.",
        "6. Evaluate PSNR, PL cycles, DDR and PS end-to-end metrics only when actually measured.",
        "",
    ])
    target=OUT/"EVIDENCE_REPORT_KO.md"
    target.write_text("\n".join(paper),encoding="utf-8")
    state=dict(
        initial_holdout=bool(hold),initial_bitexact=bool(bit),
        main_gpu_sweep_complete=bool(full and full.get("complete")),
        stress_bitexact_complete=bool(stress and stress.get("experiment_complete")),
        c64_transfer_complete=bool(arch["64-channel QAT"] and arch["64-channel QAT"].get("complete")),
        maxout_transfer_complete=bool(arch["maxout QAT"] and arch["maxout QAT"].get("complete")),
        physical_fpga_ab_count=len(measured),
    )
    (OUT/"experiment_status.json").write_text(
        json.dumps(state,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(state,indent=2))
    print("Report:",target.resolve())


if __name__=="__main__":
    main()
