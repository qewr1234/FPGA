"""Safety unit tests: completed-result reuse, partial-run preservation, fresh output."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from q1_novelty_bsd68_launcher import (
    BUDGET, MODEL, MODES, OPTIMIZER_SEEDS,
    select_output, validate_complete,
)


def create_completed(directory: Path, mode: str):
    spec=MODES[mode]
    directory.mkdir(parents=True, exist_ok=False)
    summary=dict(
        status="OFFLINE_BSD68_CYCLE_MODEL_PROXY_NOT_FPGA_MEASUREMENT",
        independent_clean_images=spec["images"],
        sigmas=spec["sigmas"],noise_seeds=spec["seeds"],
        optimizer_seeds=OPTIMIZER_SEEDS,budget_per_method_per_layer=BUDGET,
        joint_saved_pct=8.7,marginal_saved_pct=3.9,
        joint_minus_marginal_pp=4.8,
    )
    (directory/"summary.json").write_text(json.dumps(summary),encoding="utf-8")
    groups=dict(model=MODEL,budget=BUDGET,groups={str(k):{} for k in OPTIMIZER_SEEDS})
    (directory/"groups.json").write_text(json.dumps(groups),encoding="utf-8")
    with (directory/"per_condition.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["image","sigma","noise_seed","optimizer_seed",
                                       "identity_cycles","joint_saved_pct","marginal_saved_pct"])
        w.writeheader()
        for ix in range(spec["images"]):
            for sigma in spec["sigmas"]:
                for seed in spec["seeds"]:
                    for optimizer in OPTIMIZER_SEEDS:
                        w.writerow(dict(image=f"image{ix:03}.png",sigma=sigma,noise_seed=seed,
                                        optimizer_seed=optimizer,identity_cycles=1000,
                                        joint_saved_pct=8.7,marginal_saved_pct=3.9))


class LauncherSafetyTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)

    def test_empty_root_uses_base(self):
        action,path,summary,occupied=select_output(self.root,"smoke")
        self.assertEqual(action,"run")
        self.assertEqual(path.name,"q1_novelty_bsd68_smoke")
        self.assertEqual(occupied,[])
        self.assertIsNone(summary)

    def test_partial_stays_unmodified_and_selects_suffix(self):
        base=self.root/"q1_novelty_bsd68_full"
        base.mkdir()
        (base/"progress.json").write_text('{"completed_rows": 100}',encoding="utf-8")
        action,path,summary,occupied=select_output(self.root,"full")
        self.assertEqual(action,"run")
        self.assertEqual(path.name,"q1_novelty_bsd68_full_02")
        self.assertIn(base,occupied)
        self.assertEqual(json.loads((base/"progress.json").read_text())["completed_rows"],100)

    def test_completed_smoke_reused_unless_forced(self):
        base=self.root/"q1_novelty_bsd68_smoke"
        create_completed(base,"smoke")
        ok,why,_=validate_complete(base,"smoke")
        self.assertTrue(ok,why)
        action,path,summary,_=select_output(self.root,"smoke")
        self.assertEqual(action,"reuse")
        self.assertEqual(path,base)
        self.assertEqual(summary["joint_minus_marginal_pp"],4.8)
        action,path,summary,_=select_output(self.root,"smoke",new=True)
        self.assertEqual(action,"run")
        self.assertEqual(path.name,"q1_novelty_bsd68_smoke_02")

    def test_completed_full_reused(self):
        base=self.root/"q1_novelty_bsd68_full"
        create_completed(base,"full")
        ok,why,_=validate_complete(base,"full")
        self.assertTrue(ok,why)
        action,path,_,_=select_output(self.root,"full")
        self.assertEqual((action,path),("reuse",base))

    def test_incomplete_csv_rejected_and_alt_complete_reused(self):
        base=self.root/"q1_novelty_bsd68_smoke"
        create_completed(base,"smoke")
        (base/"per_condition.csv").write_text("image,sigma,noise_seed,optimizer_seed\n",encoding="utf-8")
        ok,_,_=validate_complete(base,"smoke")
        self.assertFalse(ok)
        other=self.root/"q1_novelty_bsd68_smoke_02"
        create_completed(other,"smoke")
        action,path,_,_=select_output(self.root,"smoke")
        self.assertEqual((action,path),("reuse",other))

    def test_wrong_config_does_not_count_as_complete(self):
        base=self.root/"q1_novelty_bsd68_smoke"
        create_completed(base,"smoke")
        info=json.loads((base/"summary.json").read_text(encoding="utf-8"))
        info["sigmas"]=[50]
        (base/"summary.json").write_text(json.dumps(info),encoding="utf-8")
        ok,reason,_=validate_complete(base,"smoke")
        self.assertFalse(ok)
        self.assertIn("config",reason)
        action,path,_,_=select_output(self.root,"smoke")
        self.assertEqual((action,path.name),("run","q1_novelty_bsd68_smoke_02"))


if __name__=="__main__":
    unittest.main()
