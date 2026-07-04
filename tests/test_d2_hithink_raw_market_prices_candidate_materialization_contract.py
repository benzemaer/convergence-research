from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "configs/d2/hithink_raw_market_prices_candidate_materialization_contract.v1.json"
)
SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "d2_hithink_raw_market_prices_candidate_materialization_contract.schema.json"
)


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2HiThinkRawMarketPricesCandidateMaterializationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_contract_json_passes_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)
        self.assertFalse(self.schema["additionalProperties"])

    def test_required_target_fields_are_exact(self) -> None:
        self.assertEqual(
            set(self.contract["required_target_fields"]),
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
        self.assertEqual(len(self.contract["required_target_fields"]), 17)

    def test_fallback_repair_sources_are_prioritized(self) -> None:
        priorities = {
            item["source_id"]: item["priority"]
            for item in self.contract["fallback_repair_policy"]["fallback_sources"]
        }
        self.assertEqual(priorities, {"baostock": 1, "tushare": 2})

    def test_release_decisions_and_authorizations_remain_blocked(self) -> None:
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
            self.assertFalse(self.contract[key])
        self.assertEqual(
            self.contract["stage_2_release_decisions"]["raw_materialization_decision"],
            "raw_materialization_plan_only_not_authorized",
        )

    def test_schema_rejects_missing_target_field_or_extra_ticker(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["required_target_fields"].remove("observed_at")
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["required_target_fields"][-1] = "ticker"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_schema_rejects_authorized_materialization(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["real_data_materialization_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_schema_rejects_missing_blocker_or_bad_fallback_source(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["blocking_conditions"].remove("observed_at_not_verified")
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["fallback_repair_policy"]["fallback_sources"][0]["source_id"] = (
            "a-stock-data"
        )
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
