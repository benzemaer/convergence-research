from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs/d2/tnskhdata_full_materialization_acceptance_contract.v1.json"
)
SCHEMA = (
    ROOT / "schemas/d2_tnskhdata_full_materialization_acceptance_contract.schema.json"
)


class D2T13TnskhdataFullMaterializationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema)

    def test_contract_passes_schema_and_uses_dr001_dates(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)
        self.assertEqual(self.contract["primary_source"], "tnskhdata")
        self.assertEqual(self.contract["start_date"], "20160101")
        self.assertEqual(self.contract["end_date"], "20260630")
        self.assertEqual(self.contract["canonical_fetch_date_domain"], "calendar")
        self.assertEqual(self.contract["date_domain_source"], "DR-001")
        self.assertTrue(self.contract["closed_calendar_interval"])
        self.assertFalse(
            self.contract["d2_t09_candidate_raw_market_prices_defines_date_domain"]
        )

    def test_generation_flags_stay_false(self) -> None:
        self.assertFalse(self.contract["duckdb_write_authorized"])
        self.assertFalse(self.contract["formal_duckdb_write_authorized"])
        self.assertTrue(self.contract["local_staging_write_authorized"])
        self.assertTrue(self.contract["local_staging_store_authorized"])
        self.assertFalse(self.contract["d3_generation_authorized"])
        self.assertFalse(self.contract["r0_state_generation_authorized"])
        self.assertEqual(self.contract["initial_requests_per_minute"], 200)
        self.assertEqual(self.contract["max_requests_per_minute"], 500)
        self.assertTrue(self.contract["parallel_provider_fetch_authorized"])
        self.assertTrue(self.contract["adaptive_rate_limit_authorized"])

    def test_schema_rejects_d3_unlock_or_missing_artifact_name(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["d3_generation_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["output_artifact_names"].remove("tnskhdata_quality_report.json")
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["output_artifact_names"].remove(
            "tnskhdata_unexpected_empty_primary_repair_report.json"
        )
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["formal_duckdb_write_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["max_requests_per_minute"] = 1000
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_schema_rejects_candidate_price_artifact_as_date_domain(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["date_domain_source"] = "D2_T09_candidate_raw_market_prices"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["canonical_fetch_date_domain"] = "candidate"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["d2_t09_candidate_raw_market_prices_defines_date_domain"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
