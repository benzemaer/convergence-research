from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs/d2/tnskhdata_tushare_hithink_provider_remediation_contract.v1.json"
)
SCHEMA = (
    ROOT
    / "schemas/d2_tnskhdata_tushare_hithink_provider_remediation_contract.schema.json"
)


class D2T12ProviderRemediationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema)

    def test_contract_passes_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)

    def test_authorizations_remain_false(self) -> None:
        for key in [
            "formal_source_acceptance_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "manifest_creation_authorized",
            "data_version_release_authorized",
            "d3_generation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertIs(self.contract[key], False)

    def test_required_targets_and_providers_are_fixed(self) -> None:
        targets = set(self.contract["primary_remediation_targets"])
        self.assertIn("tnskhdata_provider_probe", targets)
        self.assertIn("hithink_rest_provider_probe", targets)
        priorities = {
            item["source_id"]: item["priority"]
            for item in self.contract["provider_priority"]
        }
        modes = {
            item["source_id"]: item["mode"]
            for item in self.contract["provider_priority"]
        }
        self.assertEqual(priorities["tnskhdata"], 0)
        self.assertEqual(priorities["baostock"], 1)
        self.assertEqual(priorities["tushare"], 2)
        self.assertEqual(priorities["hithink_financial_api"], 3)
        self.assertEqual(modes["tnskhdata"], "primary_candidate_source")
        self.assertEqual(modes["hithink_financial_api"], "diagnostic_probe_only")
        decision = self.contract["source_decision"]
        self.assertEqual(
            decision["hithink_raw_source_path"],
            "deprecated_for_d1_d2_candidate_materialization_after_D2-T12",
        )
        self.assertEqual(
            decision["tnskhdata_raw_factor_status_path"], "primary_candidate_source"
        )

    def test_schema_rejects_removed_tnskhdata_or_d3_unlock(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["primary_remediation_targets"].remove("tnskhdata_provider_probe")
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["d3_generation_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_token_policy_requires_explicit_tnskhdata_fallback(self) -> None:
        policy = self.contract["tnskhdata_token_policy"]
        self.assertEqual(policy["primary_env_key"], "TNSKHDATA_TOKEN")
        self.assertEqual(policy["fallback_env_key"], "TUSHARE_TOKEN")
        self.assertTrue(policy["fallback_requires_explicit_cli_flag"])


if __name__ == "__main__":
    unittest.main()
