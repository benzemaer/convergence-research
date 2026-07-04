from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/raw_ohlcv_source_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d2_raw_ohlcv_source_contract.schema.json"
TASK_PATH = ROOT / "docs/tasks/D2-T01_价格来源与raw_OHLCV探针契约.md"
TASK_INDEX_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2RawOhlcvSourceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_json(SCHEMA_PATH)
        self.contract = load_json(CONTRACT_PATH)
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    def validate_changed(self, changed: dict) -> None:
        self.validator.validate(changed)

    def assert_invalid(self, changed: dict) -> None:
        with self.assertRaises(ValidationError):
            self.validate_changed(changed)

    def test_contract_matches_schema(self) -> None:
        self.validate_changed(self.contract)

    def test_contract_identity_and_target_table_are_fixed(self) -> None:
        self.assertEqual(self.contract["task_id"], "D2-T01")
        self.assertEqual(
            self.contract["contract_id"],
            "D2_RAW_OHLCV_SOURCE_CONTRACT_V1",
        )
        self.assertEqual(self.contract["target_table"], "d1.raw_market_prices")
        self.assertEqual(
            self.contract["contract_status"],
            "draft_for_g1_review",
        )

    def test_required_raw_fields_match_d1_raw_market_prices(self) -> None:
        field_names = {
            field["field_name"] for field in self.contract["required_raw_fields"]
        }
        self.assertEqual(
            field_names,
            {
                "data_version",
                "universe_id",
                "time_segment_id",
                "security_id",
                "trading_date",
                "raw_open",
                "raw_high",
                "raw_low",
                "raw_close",
                "volume",
                "amount",
                "trading_status",
                "price_limit_status",
                "source_registry_id",
                "source_snapshot_id",
                "observed_at",
                "run_id",
            },
        )
        self.assertTrue(
            all(
                field["nullable"] is False
                for field in self.contract["required_raw_fields"]
            )
        )

    def test_allowed_sources_are_candidate_only_and_formal_ingestion_blocked(
        self,
    ) -> None:
        source = self.contract["source_registry_requirements"]
        self.assertEqual(
            set(source["allowed_source_registry_ids"]),
            {"HITHINK_FINANCIAL_API", "BAOSTOCK"},
        )
        self.assertEqual(
            set(source["candidate_only_source_registry_ids"]),
            {"HITHINK_FINANCIAL_API", "BAOSTOCK"},
        )
        self.assertIn("CSINDEX_OFFICIAL", source["prohibited_source_registry_ids"])
        self.assertIn("A_STOCK_DATA_RECON", source["prohibited_source_registry_ids"])
        self.assertIn(
            "PUBLIC_A_SHARE_ENDPOINTS_REVIEW_BUCKET",
            source["prohibited_source_registry_ids"],
        )
        self.assertFalse(source["formal_ingestion_authorized"])
        self.assertFalse(
            self.contract["readiness_scope"]["formal_ingestion_authorized"]
        )
        self.assertFalse(
            self.contract["readiness_scope"]["full_market_collection_authorized"]
        )
        self.assertFalse(self.contract["readiness_scope"]["duckdb_write_authorized"])

    def test_wrong_or_promoted_source_boundaries_are_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["source_registry_requirements"]["formal_ingestion_authorized"] = True
        self.assert_invalid(changed)

        changed = copy.deepcopy(self.contract)
        changed["source_registry_requirements"]["allowed_source_registry_ids"].append(
            "CSINDEX_OFFICIAL"
        )
        self.assert_invalid(changed)

        changed = copy.deepcopy(self.contract)
        changed["source_registry_requirements"][
            "candidate_only_source_registry_ids"
        ].remove("BAOSTOCK")
        self.assert_invalid(changed)

    def test_snapshot_hash_manifest_observed_at_as_of_and_revision_gates_are_required(
        self,
    ) -> None:
        snapshot = self.contract["source_snapshot_requirements"]
        self.assertTrue(snapshot["raw_snapshot_required"])
        self.assertTrue(snapshot["sha256_required"])
        self.assertTrue(snapshot["source_snapshot_id_required"])
        self.assertTrue(snapshot["source_snapshot_manifest_required_before_ingestion"])

        manifest = self.contract["manifest_requirements"]
        self.assertTrue(manifest["dataset_manifest_required_before_validated"])
        self.assertTrue(manifest["run_manifest_required_for_any_probe_run"])
        self.assertTrue(manifest["no_manifest_generated_by_this_contract"])

        self.assertTrue(self.contract["observed_at_rule"]["required"])
        self.assertTrue(
            self.contract["as_of_policy"]["vendor_revision_behavior_required"]
        )
        self.assertTrue(
            self.contract["revision_policy"]["repeated_snapshot_comparison_required"]
        )

    def test_missing_readiness_gates_are_rejected_by_schema(self) -> None:
        for section, key in [
            ("source_snapshot_requirements", "sha256_required"),
            ("observed_at_rule", "required"),
            ("as_of_policy", "policy"),
            ("revision_policy", "policy"),
        ]:
            changed = copy.deepcopy(self.contract)
            del changed[section][key]
            self.assert_invalid(changed)

    def test_blocking_conditions_cover_readiness_failures(self) -> None:
        blockers = set(self.contract["blocking_conditions"])
        for blocker in {
            "source_terms_pending_for_formal_ingestion",
            "missing_raw_snapshot",
            "missing_sha256",
            "missing_observed_at",
            "as_of_policy_unknown",
            "revision_policy_unknown",
            "repeated_snapshot_comparison_missing",
            "full_market_collection_attempted_in_d2_t01",
            "duckdb_write_attempted_in_d2_t01",
            "data_artifact_generated_in_d2_t01",
        }:
            self.assertIn(blocker, blockers)

    def test_no_data_artifact_boundary_is_explicit(self) -> None:
        exclusions = set(self.contract["implementation_exclusions"])
        for exclusion in {
            "no_external_api_call",
            "no_local_marketdb_read",
            "no_tdx_day_file_read",
            "no_market_data_collection",
            "no_source_snapshot_generation",
            "no_run_manifest_generation",
            "no_dataset_manifest_generation",
            "no_source_snapshot_manifest_generation",
            "no_duckdb_write",
            "no_committed_duckdb_file",
            "no_d1_raw_market_prices_entity_data",
            "no_d2_adjusted_market_prices_entity_data",
            "no_d3_daily_market_observations",
            "no_pcvt_state_event_label_return_or_backtest",
        }:
            self.assertIn(exclusion, exclusions)

    def test_invalid_artifact_authorization_is_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["readiness_scope"]["data_artifact_generation_authorized"] = True
        self.assert_invalid(changed)

        changed = copy.deepcopy(self.contract)
        changed["implementation_exclusions"].remove("no_duckdb_write")
        self.assert_invalid(changed)

    def test_task_doc_and_index_do_not_claim_completion_or_data_execution(self) -> None:
        task = TASK_PATH.read_text(encoding="utf-8")
        index = TASK_INDEX_PATH.read_text(encoding="utf-8")

        self.assertIn("## 状态", task)
        self.assertIn("planned", task)
        self.assertIn("configs/d2/raw_ohlcv_source_contract.v1.json", task)
        self.assertIn("不调用任何外部 API", task)
        self.assertIn("不生成 D1/D2 DuckDB 实体数据", task)
        self.assertIn("D2-T01` 价格来源与 raw OHLCV 探针契约：planned", index)
        self.assertNotIn("D2-T01` 价格来源与 raw OHLCV 探针契约：completed", index)
        self.assertNotIn("D2-T01` 价格来源与 raw OHLCV 探针契约：completed", task)


if __name__ == "__main__":
    unittest.main()
