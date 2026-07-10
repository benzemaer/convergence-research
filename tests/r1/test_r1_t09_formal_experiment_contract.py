from __future__ import annotations

import unittest

from src.r1.r1_t09_year_stability_concentration import (
    CONFIG_PATH,
    ROOT,
    _load_json,
    sha256_file,
)

RUN_DIR = ROOT / "data/generated/r1/r1_t09/R1-T09-20260710T1825Z"


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

    def test_author_package_remains_review_pending(self) -> None:
        package = _load_json(RUN_DIR / "r1_t09_result_package.json")
        self.assertEqual(package["status"], "author_analysis_complete")
        self.assertEqual(package["gate_status"]["scientific_review_status"], "pending")
        self.assertEqual(
            package["gate_status"]["review_phase"], "author_analysis_complete"
        )
        self.assertEqual(package["gate_status"]["anomaly_resolution_status"], "passed")
        self.assertFalse(package["downstream_gate_allowed"])
        self.assertFalse(package["gate_status"]["readme_gate_updated"])

    def test_engineering_and_author_validators_pass(self) -> None:
        engineering = _load_json(RUN_DIR / "r1_t09_engineering_validation_result.json")
        author = _load_json(
            RUN_DIR / "r1_t09_author_draft_package_validation_result.json"
        )
        self.assertEqual(engineering["validator_status"], "passed")
        self.assertEqual(engineering["reconciliation_mismatch_count"], 0)
        self.assertEqual(author["author_package_validator_status"], "passed")
        self.assertEqual(author["mode"], "author-draft")
        self.assertFalse(author["formal_task_completed"])
        self.assertFalse(author["downstream_gate_allowed"])
        self.assertEqual(author["errors"], [])
        self.assertEqual(
            author["result_package_sha256"],
            sha256_file(RUN_DIR / "r1_t09_result_package.json"),
        )

    def test_anomaly_scan_has_all_governance_checks(self) -> None:
        anomaly = _load_json(RUN_DIR / "r1_t09_anomaly_scan.json")
        governance = _load_json(
            ROOT / "configs/governance/r_formal_experiment_governance.v1.json"
        )
        self.assertEqual(
            set(anomaly["checks"]), set(governance["mandatory_anomaly_checks"])
        )
        self.assertEqual(anomaly["scan_status"], "passed")
        self.assertEqual(anomaly["blocking_anomalies"], [])
        self.assertEqual(anomaly["unresolved_questions"], [])


if __name__ == "__main__":
    unittest.main()
