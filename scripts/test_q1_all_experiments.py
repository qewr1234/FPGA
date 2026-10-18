"""No-board unit tests for safe Q1 paper experiment orchestrator."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from q1_all_experiments import (
    DEFAULT_IMAGES, aggregate_physical, checked_physical, new_dir,
    parse_images, select_gpu_output, valid_gpu_summary,
)


class Q1CampaignSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_default_holdout_excludes_selection_and_published_example(self):
        self.assertEqual(len(DEFAULT_IMAGES),8)
        self.assertNotIn("05.png",DEFAULT_IMAGES)
        self.assertNotIn("01.png",DEFAULT_IMAGES)
        self.assertEqual(parse_images("04.png,06.png"),("04.png","06.png"))
        for value in ("01.png","05.png","06.png,06.png","04.png,../06.png",""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_images(value)

    def test_never_overwrite_trial(self):
        base=self.root/"q1all_set12_04"
        base.mkdir()
        (base/"user_log.txt").write_text("valuable raw board data",encoding="utf-8")
        pick=new_dir(base)
        self.assertEqual(pick.name,"q1all_set12_04_02")
        self.assertFalse(pick.exists())
        self.assertEqual((base/"user_log.txt").read_text(),"valuable raw board data")

    def test_no_raw_physical_data_means_not_verified(self):
        folder=self.root/"q1all_set12_04"
        folder.mkdir()
        (folder/"triplet_summary.json").write_text(json.dumps(dict(
            status="PHYSICAL_3WAY_W4_CORE_CYCLE_COMPARISON",
            physical_bitstream_sha256="11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6",
            replicates=3, fclk_mhz=50.0,repeat_rows=[
                dict(rep=i,baseline=100,frozen=90,multistart=80) for i in (1,2,3)
            ])),encoding="utf-8")
        self.assertIsNone(checked_physical(folder,"04.png"))

    def test_gpu_marked_complete_only_with_protocol_evidence(self):
        folder=self.root/"q1_gpu_deadline_full"
        folder.mkdir()
        obj=dict(complete=True,dataset="BSD68",
                 expected_image_method_rows=68*9*9,
                 completed_image_method_rows=68*9*9,
                 experiment_config=dict(random_count=20,max_images=0))
        (folder/"summary.json").write_text(json.dumps(obj),encoding="utf-8")
        self.assertFalse(valid_gpu_summary("controls",folder))
        (folder/"method_config.json").write_text("{}",encoding="utf-8")
        (folder/"per_condition.csv").write_text("headers\n",encoding="utf-8")
        self.assertTrue(valid_gpu_summary("controls",folder))
        obj["complete"]=False
        (folder/"summary.json").write_text(json.dumps(obj),encoding="utf-8")
        self.assertFalse(valid_gpu_summary("controls",folder))

    def test_aggregate_uses_pooled_weighted_physical_cycles(self):
        out=self.root/"report"
        out.mkdir()
        def summary(orig,changed):
            return dict(
                repeat_rows=[dict(baseline=orig,frozen=orig,multistart=changed) for _ in range(3)],
                frozen_conv2to9_pct_saved=0.0,
                multistart_conv2to9_pct_saved=5.0,
                physical_bitstream_sha256="11641ab391846baeb27b006440bd4b9ec19d53da9fbf8b2742bf9f9291f247a6")
        aggregate_physical(out, [
            ("04.png","q1all_set12_04",summary(100,90)),
            ("06.png","q1all_set12_06",summary(1000,800)),
        ])
        x=json.loads((out/"physical_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(x["physical_images"],2)
        self.assertAlmostEqual(x["pooled_multistart_saved_pct"],100*210/1100)
        self.assertEqual(x["clean_image_n"],2)
        self.assertTrue((out/"physical_per_image.csv").exists())


if __name__ == "__main__":
    unittest.main()
