from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    ROOT / "configs/d2/candidate_market_snapshot_probe_execution_report.v1.json"
)
SCHEMA_PATH = (
    ROOT / "schemas/d2_candidate_market_snapshot_probe_execution_report.schema.json"
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(collect_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(collect_keys(item))
        return keys
    return set()


class D2CandidateMarketSnapshotProbeExecutionReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = load(REPORT_PATH)
        cls.schema = load(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_report_matches_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.report)

    def test_report_commits_no_formal_or_row_level_artifacts(self) -> None:
        for key in [
            "raw_snapshot_committed",
            "data_external_committed",
            "duckdb_written",
            "official_dataset_materialized",
            "formal_ingestion_authorized",
            "d1_raw_market_prices_generated",
            "d2_adjusted_market_prices_generated",
            "d3_daily_observations_generated",
            "run_manifest_created",
            "dataset_manifest_created",
            "source_snapshot_manifest_created",
        ]:
            self.assertFalse(self.report[key])
        self.assertTrue(self.report["redacted_report_only"])
        prohibited = {
            "raw_rows",
            "qfq_rows",
            "hfq_rows",
            "price_rows",
            "vendor_payload",
            "raw_response_body",
        }
        self.assertFalse(prohibited & collect_keys(self.report))

    def test_schema_rejects_row_level_price_payload(self) -> None:
        changed = copy.deepcopy(self.report)
        changed["raw_rows"] = [{"security_id": "CN.SSE.600519", "raw_close": 1.0}]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_report_is_redacted_execution_and_exploration_only(self) -> None:
        self.assertEqual(self.report["execution_status"], "executed_small_sample")
        self.assertEqual(self.report["research_use_tier"], "exploration_only")
        self.assertGreater(self.report["raw_response_sha256_count"], 0)
        self.assertGreater(self.report["source_snapshot_id_count"], 0)
        self.assertTrue(self.report["raw_snapshot_written_local"])
        self.assertEqual(self.report["raw_ohlcv_coverage"], "pass")
        self.assertEqual(self.report["qfq_coverage"], "pass")
        self.assertEqual(self.report["hfq_coverage"], "pass")
        self.assertEqual(self.report["implied_qfq_factor_check"]["status"], "pass")
        self.assertGreater(self.report["implied_qfq_factor_check"]["checked_count"], 0)
        self.assertEqual(self.report["implied_hfq_factor_check"]["status"], "pass")
        self.assertGreater(self.report["implied_hfq_factor_check"]["checked_count"], 0)
        self.assertEqual(
            self.report["recommended_next_decision"],
            "review_redacted_probe_metrics_only",
        )


if __name__ == "__main__":
    unittest.main()
