from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "configs/d2/d2_acceptance_d3_handoff_blocking_report.v1.json"
SCHEMA_PATH = ROOT / "schemas/d2_acceptance_d3_handoff_blocking_report.schema.json"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2AcceptanceD3HandoffBlockingReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = load(REPORT_PATH)
        cls.schema = load(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_blocking_report_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.report)

    def test_report_records_no_real_data_actions(self) -> None:
        for key in [
            "real_data_read",
            "external_api_called",
            "raw_data_committed",
            "duckdb_written",
            "formal_ingestion_authorized",
            "d2_raw_price_materialized",
            "d2_adjusted_price_materialized",
            "d2_quality_flags_materialized",
            "d3_generated",
            "r0_generated",
            "pcvt_values_generated",
            "returns_or_labels_generated",
        ]:
            self.assertFalse(self.report[key])

    def test_report_blocking_reasons_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.report["blocking_reasons"]),
            {
                "formal_ingestion_not_authorized",
                "real_d2_raw_price_layer_not_materialized",
                "real_d2_adjusted_price_layer_not_materialized",
                "real_d2_quality_flags_not_materialized",
                "factor_as_of_time_coverage_not_verified",
                "revision_timestamp_coverage_not_verified",
                "source_terms_pending_for_formal_ingestion",
                "d3_generation_not_authorized_by_this_pr",
                "r0_generation_not_authorized_by_this_pr",
            },
        )
        self.assertEqual(
            self.report["recommended_next_task"],
            "D3-T01_daily_market_observations_contract",
        )

    def test_schema_rejects_any_real_data_or_generation_flag_true(self) -> None:
        for key in [
            "real_data_read",
            "external_api_called",
            "raw_data_committed",
            "duckdb_written",
            "formal_ingestion_authorized",
            "d2_raw_price_materialized",
            "d2_adjusted_price_materialized",
            "d2_quality_flags_materialized",
            "d3_generated",
            "r0_generated",
            "pcvt_values_generated",
            "returns_or_labels_generated",
        ]:
            changed = copy.deepcopy(self.report)
            changed[key] = True
            with self.assertRaises(ValidationError):
                self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
