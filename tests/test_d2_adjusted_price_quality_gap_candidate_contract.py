from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "configs/d2/adjusted_price_quality_gap_candidate_contract.v1.json"
)
SCHEMA_PATH = (
    ROOT / "schemas/d2_adjusted_price_quality_gap_candidate_contract.schema.json"
)


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2AdjustedPriceQualityGapCandidateContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(CONTRACT_PATH)
        self.schema = load_json(SCHEMA_PATH)
        Draft202012Validator.check_schema(self.schema)

    def validate(self, payload: dict[str, object]) -> None:
        Draft202012Validator(self.schema).validate(payload)

    def test_contract_json_passes_schema(self) -> None:
        self.validate(self.contract)
        self.assertEqual(
            self.contract["contract_id"],
            "D2_ADJUSTED_PRICE_QUALITY_GAP_CANDIDATE_CONTRACT_V1",
        )
        self.assertEqual(self.contract["task_id"], "D2-T10")

    def test_authorization_boundary_is_candidate_only(self) -> None:
        for key in [
            "formal_source_acceptance_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_data_materialization_authorized",
            "manifest_creation_authorized",
            "data_version_release_authorized",
            "d3_generation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertIs(self.contract[key], False)
        self.assertIs(self.contract["local_candidate_artifact_write_authorized"], True)

    def test_target_artifacts_and_dependency_gates_are_fixed(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["target_artifacts"]),
            {
                "d2.adjusted_market_prices_candidate",
                "d2.market_price_quality_flags_candidate",
                "d2.mechanical_gap_attribution_candidate",
                "d2.trading_constraint_readiness_candidate",
                "d2.raw_adjusted_reconciliation_candidate",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["depends_on"]),
            {
                "D2_FORMAL_SOURCE_REGISTRY_CONTRACT_V1",
                "D2_HITHINK_RAW_OHLCV_PROBE_CONTRACT_V1",
                "D2_HITHINK_RAW_MARKET_PRICES_CANDIDATE_MATERIALIZATION_CONTRACT_V1",
                "D2_HITHINK_RAW_MARKET_PRICES_CANDIDATE_ARTIFACT_CONTRACT_V1",
                "D2_ACCEPTANCE_D3_HANDOFF_CONTRACT_V1",
                "D2_MARKET_QUALITY_PCVT_DEPENDENCY_CONTRACT_V1",
                "D3_DATA_VERSION_QUALITY_MANIFEST_GATE_CONTRACT_V1",
            },
        )

    def test_row_schemas_and_blocking_rules_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["adjusted_price_row_schema"]),
            {"adj_open", "adj_close", "factor_as_of_time", "adjustment_revision"},
        )
        self.assertGreaterEqual(
            set(self.contract["quality_flags_row_schema"]),
            {
                "trading_status_readiness",
                "price_limit_status_readiness",
                "suspension_status_readiness",
                "st_status_readiness",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["mechanical_gap_row_schema"]),
            {
                "raw_gap_ratio",
                "adj_gap_ratio",
                "mechanical_gap_candidate_flag",
                "gap_attribution_status",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["trading_constraint_readiness_fields"]),
            {
                "trading_status_unknown_count",
                "price_limit_status_unknown_count",
                "readiness_blocking_reasons",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["blocking_rules"]),
            {
                "factor_as_of_time_missing",
                "adjustment_revision_missing",
                "trading_status_unknown_blocks_d2_acceptance",
                "price_limit_status_unknown_blocks_d2_acceptance",
                "missing_adjustment_event_gap_unknown",
            },
        )

    def test_schema_rejects_removed_core_adjusted_field(self) -> None:
        payload = copy.deepcopy(self.contract)
        payload["adjusted_price_row_schema"].remove("adj_close")
        with self.assertRaises(Exception):
            self.validate(payload)

    def test_schema_rejects_enabled_formal_authorization(self) -> None:
        payload = copy.deepcopy(self.contract)
        payload["data_version_release_authorized"] = True
        with self.assertRaises(Exception):
            self.validate(payload)

    def test_schema_rejects_removed_required_blocker(self) -> None:
        payload = copy.deepcopy(self.contract)
        payload["blocking_rules"].remove("factor_as_of_time_missing")
        with self.assertRaises(Exception):
            self.validate(payload)


if __name__ == "__main__":
    unittest.main()
