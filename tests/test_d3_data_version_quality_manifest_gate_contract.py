from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/data_version_quality_manifest_gate_contract.v1.json"
SCHEMA_PATH = (
    ROOT / "schemas/d3_data_version_quality_manifest_gate_contract.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D3DataVersionQualityManifestGateContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.contract)
        self.assertFalse(self.schema["additionalProperties"])

    def test_contract_binds_d3_t01_through_t05(self) -> None:
        self.assertEqual(
            self.contract["canonical_ref_table"], "d3.daily_market_observations"
        )
        self.assertEqual(
            self.contract["value_layer_object"], "d3.daily_market_observation_values"
        )
        self.assertEqual(
            self.contract["component_lineage_contract"],
            "D3_COMPONENT_LINEAGE_NO_BYPASS_CONTRACT_V1",
        )
        self.assertEqual(
            self.contract["quality_readiness_contract"],
            "D3_QUALITY_READINESS_CONTRACT_V1",
        )
        self.assertEqual(
            self.contract["synthetic_build_contract"],
            "D3_SYNTHETIC_DAILY_OBSERVATION_BUILD_CONTRACT_V1",
        )

    def test_no_formal_release_authorized(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "ddl_authorized",
            "real_data_materialization_authorized",
            "manifest_creation_authorized",
            "data_version_release_authorized",
            "pcvt_indicator_calculation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertFalse(self.contract[key])
        self.assertTrue(self.contract["synthetic_test_only"])

    def test_release_vocabularies_and_decision_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["release_gate_status_vocabulary"]),
            {
                "not_evaluated",
                "passed",
                "failed",
                "blocked",
                "waived_for_exploration_only",
                "not_applicable",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["release_decision_vocabulary"]),
            {
                "release_allowed",
                "release_blocked",
                "exploration_only_allowed",
                "formal_release_blocked",
            },
        )
        self.assertEqual(
            self.contract["current_formal_release_decision"],
            "formal_release_blocked",
        )

    def test_data_version_manifest_and_quality_report_fields_are_complete(self) -> None:
        self.assertIn("sha256", self.contract["data_version_fields"])
        self.assertIn("candidate_manifest_ref", self.contract["data_version_fields"])
        self.assertIn("source_snapshot_refs", self.contract["manifest_fields"])
        self.assertIn("run_refs", self.contract["manifest_fields"])
        self.assertIn("contract_refs", self.contract["manifest_fields"])
        self.assertIn(
            "quality_domain_summaries", self.contract["quality_report_fields"]
        )
        self.assertIn(
            "pcvt_input_readiness_summary", self.contract["quality_report_fields"]
        )
        self.assertGreaterEqual(
            set(self.contract["quality_domains_required"]),
            {
                "raw_ohlcv_integrity",
                "continuous_ohlc_integrity",
                "raw_vs_continuous_reconciliation",
                "amount_volume_unit_validation",
                "daily_vwap_range_validation",
                "trading_constraint_diagnostics",
                "mechanical_gap_attribution",
                "window_validity",
                "pcvt_input_readiness",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["pcvt_readiness_indicators_required"]),
            {
                "P1_NATR14",
                "P2_LogRange20",
                "C1_LogMASpread_5_60",
                "C2_AdjVWAPSpread_5_60",
                "T1_ER20",
                "T2_AbsTrendT20",
                "V1_VolShrink20_60",
                "V2_AmountLevel20Pct",
            },
        )

    def test_release_gate_checklist_and_current_blocks_are_complete(self) -> None:
        gate_ids = {gate["gate_id"] for gate in self.contract["release_gates"]}
        self.assertGreaterEqual(
            gate_ids,
            {
                "d2_formal_materialization_gate",
                "source_authorization_gate",
                "factor_as_of_time_coverage_gate",
                "revision_timestamp_coverage_gate",
                "canonical_contract_gate",
                "value_layer_contract_gate",
                "component_lineage_gate",
                "no_bypass_gate",
                "quality_readiness_gate",
                "manifest_completeness_gate",
                "quality_report_completeness_gate",
                "row_count_reconciliation_gate",
                "hash_integrity_gate",
                "prohibited_field_absence_gate",
                "forbidden_path_absence_gate",
                "r0_locked_until_release_gate",
            },
        )
        self.assertEqual(
            self.contract["current_blocking_gates"],
            {
                "d2_formal_materialization_gate": "blocked",
                "source_authorization_gate": "blocked",
                "factor_as_of_time_coverage_gate": "blocked",
                "revision_timestamp_coverage_gate": "blocked",
                "formal_d3_generation_gate": "blocked",
                "r0_release_gate": "blocked",
            },
        )

    def test_prohibited_fields_and_forbidden_path_policy_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["prohibited_fields"]),
            {
                "pcvt_value",
                "pcvt_score",
                "pcvt_state",
                "future_return",
                "label",
                "backtest_signal",
                "portfolio_return",
                "vendor_payload",
                "raw_rows",
                "qfq_rows",
                "hfq_rows",
            },
        )
        policy = self.contract["forbidden_path_policy"]
        self.assertTrue(policy["reject_payload_path_before_open"])
        self.assertTrue(policy["reject_payload_content_paths"])
        self.assertFalse(policy["duckdb_connection_authorized"])
        self.assertFalse(policy["external_api_call_authorized"])
        self.assertFalse(policy["manifest_write_authorized"])
        self.assertGreaterEqual(
            set(policy["forbidden_patterns"]),
            {"data/raw", "data/external", "MarketDB", ".duckdb", ".day"},
        )

    def test_readme_advances_to_d3_t06_and_preserves_stage_boundaries(self) -> None:
        self.assertIn("current_stage: D3", self.readme)
        self.assertIn("current_task: D3-T06", self.readme)
        self.assertIn("next_planned_task: D3-T07", self.readme)
        for snippet in [
            "D3-T01` `daily_market_observations` 语义与字段契约：completed via PR #35",
            "D3-T02` D3 标准数值观测 view/table 契约：completed via PR #36",
            "D3-T03` 组件引用、source lineage 与 no-bypass 校验器："
            "completed via PR #37",
            "D3-T04` 基础质量指标与 PCVT input readiness 契约：completed via PR #38",
            "D3-T05` 标准日频观测合成构建与最小集成测试：completed via PR #39",
            "D3-T06` `data_version`、quality report 与 manifest 发布门禁：in_progress",
            "D3-T08` D3 阶段验收与 R0 交接契约：planned",
        ]:
            self.assertIn(snippet, self.readme)
        self.assertIn("blocked pending D2 formal materialization", self.readme)


if __name__ == "__main__":
    unittest.main()
