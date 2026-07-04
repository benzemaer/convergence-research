from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "configs/d2/candidate_market_snapshot_probe_execution_plan.v1.json"
SCHEMA_PATH = (
    ROOT / "schemas/d2_candidate_market_snapshot_probe_execution_plan.schema.json"
)
MEMBERSHIP_PATH = ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
GITIGNORE_PATH = ROOT / ".gitignore"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2CandidateMarketSnapshotProbeExecutionPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = load(PLAN_PATH)
        cls.schema = load(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_plan_matches_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.plan)

    def test_plan_is_baostock_only_and_blocks_formal_outputs(self) -> None:
        self.assertEqual(self.plan["candidate_sources"], ["BAOSTOCK"])
        self.assertFalse(self.plan["hithink_execution_authorized"])
        for key in [
            "formal_ingestion_authorized",
            "official_dataset_materialization_authorized",
            "duckdb_write_authorized",
            "raw_data_commit_authorized",
            "row_level_price_commit_authorized",
        ]:
            self.assertFalse(self.plan[key])
        self.assertEqual(self.plan["default_mode"], "dry_run")

    def test_schema_rejects_promoted_authorization_or_missing_baostock(self) -> None:
        changed = copy.deepcopy(self.plan)
        changed["formal_ingestion_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.plan)
        changed["candidate_sources"] = []
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_schema_rejects_non_dry_run_default_or_row_level_commit(self) -> None:
        changed = copy.deepcopy(self.plan)
        del changed["default_mode"]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.plan)
        changed["default_mode"] = "execute"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.plan)
        changed["row_level_price_commit_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_sample_ids_are_capped_and_present_in_membership_alignment(self) -> None:
        self.assertLessEqual(len(self.plan["sample_security_ids"]), 3)
        membership = load(MEMBERSHIP_PATH)
        member_ids = {row["security_id"] for row in membership["rows"]}
        self.assertTrue(set(self.plan["sample_security_ids"]).issubset(member_ids))

    def test_raw_probe_root_is_ignored(self) -> None:
        gitignore = GITIGNORE_PATH.read_text(encoding="utf-8")
        self.assertIn("data/raw/", gitignore)
        self.assertTrue(str(self.plan["raw_output_root"]).startswith("data/raw/"))


if __name__ == "__main__":
    unittest.main()
