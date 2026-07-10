from __future__ import annotations

import unittest

from src.r1.r1_t09_year_stability_concentration import CONFIG_PATH, ROOT, _load_json


class R1T09FormalExperimentContractTest(unittest.TestCase):
    def test_author_draft_readme_gate_remains_closed(self) -> None:
        text = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("current_task: R1-T09 年份稳定性与状态集中度检查", text)
        self.assertIn("R1-T10_allowed_to_start: false", text)
        self.assertIn("R2_allowed_to_start: false", text)

    def test_config_freezes_year_and_interval_semantics(self) -> None:
        config = _load_json(CONFIG_PATH)
        self.assertEqual(config["years"]["definition"], "YEAR(trading_date)")
        self.assertEqual(
            config["years"]["interval_assignment"], "YEAR(confirmation_date)"
        )
        self.assertEqual(config["years"]["partial_years"], [2026])
        self.assertEqual(config["status_rules"]["single_year_majority_threshold"], 0.5)

    def test_t08_final_gate_is_bound(self) -> None:
        config = _load_json(CONFIG_PATH)
        package = config["upstream_final_packages"]["R1-T08"]
        self.assertEqual(package["run_id"], "R1-T08-20260710T1629Z")
        self.assertTrue((ROOT / package["final_gate_path"]).exists())


if __name__ == "__main__":
    unittest.main()
