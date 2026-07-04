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

    def test_generation_flags_stay_false(self) -> None:
        self.assertFalse(self.contract["duckdb_write_authorized"])
        self.assertFalse(self.contract["d3_generation_authorized"])
        self.assertFalse(self.contract["r0_state_generation_authorized"])

    def test_schema_rejects_d3_unlock_or_missing_artifact_name(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["d3_generation_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["output_artifact_names"].remove("tnskhdata_quality_report.json")
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
