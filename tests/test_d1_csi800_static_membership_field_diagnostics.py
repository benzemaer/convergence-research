from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_csi800_static_membership_field_diagnostics.schema.json"
CONFIG_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_diagnostics.v1.json"
)
CONTRACT_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"

ROW_LEVEL_FIELDS = (
    "member_rows",
    "members",
    "constituents",
    "rows",
    "tickers",
    "source_symbols",
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D1CSI800StaticMembershipFieldDiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.contract = load(CONTRACT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_field_diagnostics_schema_and_config_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_diagnostics_align_with_d1_t04_contract(self) -> None:
        universe = self.contract["universe"]
        evidence = self.contract["source_evidence"]
        self.assertEqual(self.config["universe_id"], universe["universe_id"])
        self.assertEqual(self.config["index_code"], universe["index_code"])
        self.assertEqual(
            self.config["source_snapshot_id"],
            evidence["source_snapshot_id"],
        )
        self.assertEqual(
            self.config["raw_evidence_path"], evidence["raw_evidence_path"]
        )
        self.assertEqual(
            self.config["raw_evidence_sha256_expected"],
            evidence["raw_evidence_sha256"],
        )
        self.assertEqual(
            self.config["raw_evidence_sha256_actual"],
            evidence["raw_evidence_sha256"],
        )
        self.assertEqual(
            self.config["expected_member_count"],
            universe["expected_member_count"],
        )

    def test_real_diagnostics_capture_aggregate_field_state(self) -> None:
        self.assertEqual(self.config["diagnostics_status"], "field_aliases_required")
        self.assertEqual(self.config["member_count_observed"], 800)
        self.assertEqual(self.config["observed_column_count"], 9)
        self.assertEqual(
            self.config["missing_required_fields"],
            ["security_id_mapping_reference"],
        )
        summary = self.config["required_field_match_summary"]
        self.assertTrue(summary["source_symbol"])
        self.assertTrue(summary["ticker"])
        self.assertTrue(summary["exchange"])
        self.assertFalse(summary["security_id_mapping_reference"])
        aliases = self.config["candidate_aliases_by_required_field"]
        self.assertIn("成份券代码Constituent Code", aliases["source_symbol"])
        self.assertIn("成份券代码Constituent Code", aliases["ticker"])
        self.assertIn("交易所Exchange", aliases["exchange"])
        self.assertEqual(aliases["security_id_mapping_reference"], [])

    def test_no_artifact_or_materialization_flags_are_false(self) -> None:
        for field in (
            "row_level_detail_included",
            "raw_bytes_committed",
            "member_rows_committed",
            "duckdb_written",
            "run_manifest_created",
            "dataset_manifest_created",
            "materialization_authorized",
            "member_rows_materialized",
        ):
            with self.subTest(field=field):
                self.assertFalse(self.config[field])
        self.assertEqual(
            self.config["downstream_decision"],
            "materialization_remains_blocked",
        )

    def test_row_level_fields_are_rejected(self) -> None:
        for field in ROW_LEVEL_FIELDS:
            changed = deepcopy(self.config)
            changed[field] = []
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_artifact_or_materialization_flags_true_are_rejected(self) -> None:
        for field in (
            "row_level_detail_included",
            "raw_bytes_committed",
            "member_rows_committed",
            "duckdb_written",
            "materialization_authorized",
            "member_rows_materialized",
        ):
            changed = deepcopy(self.config)
            changed[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)


if __name__ == "__main__":
    unittest.main()
