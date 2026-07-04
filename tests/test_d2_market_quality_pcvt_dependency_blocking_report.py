from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "configs/d2/market_quality_pcvt_dependency_blocking_report.v1.json"
SCHEMA_PATH = (
    ROOT / "schemas/d2_market_quality_pcvt_dependency_blocking_report.schema.json"
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2MarketQualityPCVTDependencyBlockingReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = load(REPORT_PATH)
        cls.schema = load(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_blocking_report_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.report)

    def test_real_data_and_generation_flags_are_false(self) -> None:
        for key in [
            "real_data_read",
            "external_api_called",
            "raw_data_committed",
            "duckdb_written",
            "formal_ingestion_authorized",
            "d3_generated",
            "r0_indicator_generated",
            "pcvt_values_generated",
            "returns_or_labels_generated",
        ]:
            self.assertFalse(self.report[key])

    def test_schema_rejects_promoted_outputs(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "d3_generated",
            "r0_indicator_generated",
            "pcvt_values_generated",
            "returns_or_labels_generated",
        ]:
            changed = copy.deepcopy(self.report)
            changed[key] = True
            with self.assertRaises(ValidationError):
                self.validator.validate(changed)

    def test_readiness_summary_blocks_formal_generation(self) -> None:
        summary = self.report["pcvt_dependency_readiness_summary"]
        self.assertTrue(
            summary["price_based_indicators_exploration_ready_after_full_window_pull"]
        )
        self.assertTrue(
            summary[
                "amount_volume_indicators_partial_pending_unit_and_adjustment_policy"
            ]
        )
        self.assertFalse(summary["formal_pcvt_indicator_generation_authorized"])
        self.assertFalse(summary["r0_indicator_thresholds_defined"])
        self.assertTrue(summary["d3_handoff_required_before_r0"])


if __name__ == "__main__":
    unittest.main()
