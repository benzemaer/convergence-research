from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "docs/tasks/README.md"


class FormalExperimentGovernanceContractTest(unittest.TestCase):
    def test_governance_config_matches_schema_and_freezes_required_statuses(
        self,
    ) -> None:
        schema = json.loads(
            (
                ROOT / "schemas/governance/r_formal_experiment_governance.schema.json"
            ).read_text(encoding="utf-8")
        )
        config = json.loads(
            (
                ROOT / "configs/governance/r_formal_experiment_governance.v1.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
        self.assertEqual(
            config["status_enums"]["scientific_review_status"],
            ["pending", "passed", "needs_revision", "blocked"],
        )
        self.assertIn("all_zero_check", config["mandatory_anomaly_checks"])
        self.assertTrue(
            config["scientific_review_independence_policy"][
                "reviewer_identity_must_differ_from_implementation_actor"
            ]
        )

    def test_required_templates_exist(self) -> None:
        for path in [
            "docs/templates/R_FORMAL_EXPERIMENT_TASK_TEMPLATE.md",
            "docs/templates/R_FORMAL_EXPERIMENT_RESULT_ANALYSIS_TEMPLATE.md",
            "docs/templates/R_FORMAL_EXPERIMENT_SCIENTIFIC_REVIEW_TEMPLATE.md",
            "docs/templates/R_FORMAL_EXPERIMENT_EVIDENCE_TEMPLATE.md",
            ".github/PULL_REQUEST_TEMPLATE/formal_experiment.md",
        ]:
            self.assertTrue((ROOT / path).exists(), path)

    def test_script_wrapper_is_thin(self) -> None:
        wrapper = (
            ROOT / "scripts/governance/validate_r_formal_experiment_package.py"
        ).read_text(encoding="utf-8")
        self.assertIn("r_formal_experiment_package_validator_cli", wrapper)
        self.assertNotIn("json.load", wrapper)
        self.assertNotIn("Draft202012Validator", wrapper)

    def test_current_task_pointer_advances_after_r1_t06_final_gate(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("current_stage: R1", text)
        self.assertIn(
            "current_task: R1-T07 P 首入锚定的固定滞后结构关系",
            text,
        )
        self.assertIn(
            "next_planned_task: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型",
            text,
        )
        self.assertIn("R1-T04 completed via PR #80", text)
        self.assertIn("R1-T05 completed via PR #81", text)
        self.assertIn("R1-T06 completed via PR #82", text)
        self.assertIn("R1-T05_allowed_to_start: true", text)
        self.assertIn("R1-T06_allowed_to_start: true", text)
        self.assertIn("R1-T07_allowed_to_start: true", text)
        self.assertIn("R1-T08_allowed_to_start: false", text)
        self.assertIn("R2_allowed_to_start: false", text)

    def test_readme_records_cross_stage_governance_without_advancing_task(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("## 跨阶段研究治理", text)
        self.assertIn("GOV-T01", text)
        self.assertIn("GOV task 不改变 current_stage/current_task", text)
        self.assertIn("draft PR #77 is superseded", text)


if __name__ == "__main__":
    unittest.main()
