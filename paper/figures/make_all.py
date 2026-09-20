"""Regenerate every figure. Run from this directory:  python make_all.py

Each figure is written twice: <name>.pdf to place in the paper, and <name>.png at
600 dpi for slides and the poster. Every number they draw comes from data.py, so
a figure cannot drift away from the measurement it is reporting.
"""
import runpy
import sys
from pathlib import Path

FIGURES = [
    "fig1_architectures.py",
    "fig2_iso_multiplier.py",
    "fig3_overlap_timeline.py",
    "fig4_iso_tradeoff.py",
    "fig5_hw_validation.py",
    "fig6_verification_flow.py",
]

here = Path(__file__).parent
sys.path.insert(0, str(here))

failed = []
for name in FIGURES:
    print(name)
    try:
        runpy.run_path(str(here / name), run_name="__main__")
    except Exception as exc:                      # keep going, report at the end
        print(f"  FAILED: {exc}")
        failed.append(name)

print()
if failed:
    print(f"{len(failed)} figure(s) failed: {', '.join(failed)}")
    sys.exit(1)
print(f"all {len(FIGURES)} figures written.")
