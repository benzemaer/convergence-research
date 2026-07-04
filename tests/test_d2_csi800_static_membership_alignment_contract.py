from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "schemas/d2_csi800_static_membership_alignment_contract.schema.json"
)
CONTRACT_PATH = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment_contract.v1.json"
)
README_PATH = ROOT / "docs/tasks/README.md"
TASK_PATH = ROOT / "docs/tasks/D2-T02_成员对齐层物化.md"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2CSI800StaticMembershipAlignmentContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.contract = load(CONTRACT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_schema_and_contract_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.contract)

    def test_contract_identity_and_dependencies_are_fixed(self) -> None:
        self.assertEqual(self.contract["task_id"], "D2-T02")
        self.assertEqual(
            self.contract["contract_id"],
            "D2_CSI800_STATIC_2026_06_MEMBERSHIP_ALIGNMENT_CONTRACT_V1",
        )
        self.assertEqual(self.contract["contract_status"], "accepted")
        self.assertEqual(self.contract["target_table"], "d2.membership_alignment")
        self.assertEqual(self.contract["source_registry_id"], "CSINDEX_OFFICIAL")
        self.assertIn(
            "D2_RAW_OHLCV_SOURCE_CONTRACT_V1",
            self.contract["depends_on"],
        )
        self.assertIn("DR-001", self.contract["depends_on"])

    def test_required_fields_and_primary_key_match_d0_contract(self) -> None:
        self.assertEqual(
            self.contract["required_fields"],
            [
                "data_version",
                "universe_id",
                "time_segment_id",
                "security_id",
                "index_code",
                "membership_effective_date",
                "membership_mode",
                "membership_source",
                "source_registry_id",
                "source_snapshot_id",
                "run_id",
            ],
        )
        self.assertEqual(
            self.contract["primary_key"],
            [
                "data_version",
                "universe_id",
                "security_id",
                "index_code",
                "membership_effective_date",
            ],
        )

    def test_static_cohort_boundaries_block_market_data_and_history_claims(
        self,
    ) -> None:
        boundary = self.contract["source_boundary"]
        self.assertFalse(boundary["historical_membership_claim_allowed"])
        self.assertFalse(boundary["market_price_source_allowed"])
        self.assertFalse(boundary["corporate_action_source_allowed"])
        self.assertFalse(boundary["trading_status_source_allowed"])
        self.assertFalse(boundary["raw_evidence_read_allowed"])
        self.assertFalse(boundary["data_external_read_allowed"])

    def test_schema_rejects_promoted_or_wrong_boundaries(self) -> None:
        changes = [
            ("source_registry_id", "BAOSTOCK"),
            ("membership_mode", "historical_point_in_time"),
            ("membership_effective_date", "2016-01-01"),
            ("contract_status", "draft_for_g1_review"),
        ]
        for key, value in changes:
            changed = copy.deepcopy(self.contract)
            changed[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["source_boundary"]["market_price_source_allowed"] = True
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_implementation_exclusions_cover_forbidden_work(self) -> None:
        exclusions = set(self.contract["implementation_exclusions"])
        for expected in {
            "no_raw_evidence_read",
            "no_data_external_read",
            "no_external_api_call",
            "no_marketdb_read",
            "no_tdx_day_file_read",
            "no_market_data_collection",
            "no_duckdb_write",
            "no_run_manifest_generation",
            "no_dataset_manifest_generation",
            "no_source_snapshot_manifest_generation",
            "no_raw_price_generation",
            "no_adjusted_price_generation",
            "no_gap_attribution",
            "no_pcvt_state_event_label_return_or_backtest",
        }:
            self.assertIn(expected, exclusions)

    def test_task_index_is_advanced_without_starting_d2_t03(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        task_doc = TASK_PATH.read_text(encoding="utf-8")
        self.assertIn("current_task: D3-T06", readme)
        self.assertIn("next_planned_task: D3-T07", readme)
        self.assertIn("D2-T02` 成员对齐层物化：completed via PR #26", readme)
        self.assertIn("D2-T03` 原始行情价格落账：planned", readme)
        self.assertIn("completed via PR #26", task_doc)
        self.assertIn("不采集行情", task_doc)
        self.assertIn("不写 DuckDB", task_doc)


if __name__ == "__main__":
    unittest.main()
