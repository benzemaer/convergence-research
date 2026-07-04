from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT_SCHEMA_PATH = (
    ROOT / "schemas/d2_csi800_static_membership_alignment.schema.json"
)
REPORT_SCHEMA_PATH = (
    ROOT / "schemas/d2_csi800_static_membership_alignment_report.schema.json"
)
ALIGNMENT_PATH = ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
REPORT_PATH = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment_report.v1.json"
)
D1_REFERENCE_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_reference.v1.json"
)

EXPECTED_ROW_FIELDS = {
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
}
PROHIBITED_ROW_FIELDS = {
    "ticker",
    "exchange",
    "source_symbol",
    "weight",
    "raw_open",
    "raw_close",
    "adj_close",
    "corporate_action",
    "adjustment_factor",
    "gap_attribution",
}


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2CSI800StaticMembershipAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.alignment_schema = load(ALIGNMENT_SCHEMA_PATH)
        cls.report_schema = load(REPORT_SCHEMA_PATH)
        cls.alignment = load(ALIGNMENT_PATH)
        cls.report = load(REPORT_PATH)
        cls.d1_reference = load(D1_REFERENCE_PATH)
        cls.alignment_validator = Draft202012Validator(cls.alignment_schema)
        cls.report_validator = Draft202012Validator(cls.report_schema)

    def test_alignment_and_report_match_schemas(self) -> None:
        Draft202012Validator.check_schema(self.alignment_schema)
        Draft202012Validator.check_schema(self.report_schema)
        self.alignment_validator.validate(self.alignment)
        self.report_validator.validate(self.report)

    def test_alignment_rows_are_exactly_800_required_field_rows(self) -> None:
        rows = self.alignment["rows"]
        self.assertEqual(len(rows), 800)
        self.assertEqual(self.alignment["member_count"], 800)
        for row in rows:
            self.assertEqual(set(row), EXPECTED_ROW_FIELDS)
            self.assertFalse(PROHIBITED_ROW_FIELDS & set(row))

    def test_primary_key_and_security_id_sets_are_exact(self) -> None:
        rows = self.alignment["rows"]
        primary_keys = {
            (
                row["data_version"],
                row["universe_id"],
                row["security_id"],
                row["index_code"],
                row["membership_effective_date"],
            )
            for row in rows
        }
        self.assertEqual(len(primary_keys), 800)
        alignment_security_ids = {row["security_id"] for row in rows}
        reference_security_ids = {
            member["security_id"] for member in self.d1_reference["members"]
        }
        self.assertEqual(alignment_security_ids, reference_security_ids)

    def test_alignment_constants_are_static_cohort_only(self) -> None:
        for row in self.alignment["rows"]:
            self.assertEqual(row["source_registry_id"], "CSINDEX_OFFICIAL")
            self.assertEqual(row["membership_mode"], "static_cohort")
            self.assertEqual(row["membership_effective_date"], "2026-06-12")
            self.assertEqual(row["index_code"], "000906")
            self.assertEqual(
                row["membership_source"],
                "D1_T04_CSI800_STATIC_2026_06_MEMBERSHIP_REFERENCE_V1",
            )
        self.assertFalse(self.alignment["historical_membership_claim_attempted"])

    def test_report_records_clean_aggregate_counts_and_no_artifacts(self) -> None:
        self.assertEqual(self.report["alignment_status"], "completed")
        self.assertEqual(self.report["member_count_expected"], 800)
        self.assertEqual(self.report["member_count_observed"], 800)
        self.assertEqual(self.report["unique_security_id_count"], 800)
        self.assertEqual(self.report["duplicate_primary_key_count"], 0)
        self.assertEqual(self.report["missing_required_field_count"], 0)
        self.assertEqual(self.report["non_csindex_source_count"], 0)
        self.assertFalse(self.report["historical_membership_claim_attempted"])
        self.assertFalse(self.report["raw_evidence_read"])
        self.assertFalse(self.report["data_external_read"])
        self.assertFalse(self.report["duckdb_written"])
        self.assertFalse(self.report["market_data_generated"])
        self.assertFalse(self.report["run_manifest_created"])
        self.assertFalse(self.report["dataset_manifest_created"])
        self.assertEqual(self.report["next_task"], "D2-T03")

    def test_schema_rejects_extra_fields_and_non_static_claims(self) -> None:
        changed = copy.deepcopy(self.alignment)
        changed["rows"][0]["ticker"] = "000001"
        with self.assertRaises(ValidationError):
            self.alignment_validator.validate(changed)

        changed = copy.deepcopy(self.alignment)
        changed["rows"][0]["source_registry_id"] = "BAOSTOCK"
        with self.assertRaises(ValidationError):
            self.alignment_validator.validate(changed)

        changed = copy.deepcopy(self.alignment)
        changed["historical_membership_claim_attempted"] = True
        with self.assertRaises(ValidationError):
            self.alignment_validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
