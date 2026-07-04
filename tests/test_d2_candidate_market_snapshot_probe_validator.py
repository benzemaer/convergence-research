from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.validate_d2_candidate_market_snapshot_probe import (
    CandidateMarketSnapshotProbeValidationError,
    validate_candidate_probe_rows,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/candidate_market_snapshot_probe_contract.v1.json"
ALIGNMENT_PATH = ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
SCRIPT_PATH = ROOT / "scripts/validate_d2_candidate_market_snapshot_probe.py"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2CandidateMarketSnapshotProbeValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(CONTRACT_PATH)
        cls.alignment = load(ALIGNMENT_PATH)
        security_id = cls.alignment["rows"][0]["security_id"]
        cls.good_row = {
            "probe_id": "SYNTHETIC_D2_T06_PROBE",
            "source_registry_id": "BAOSTOCK",
            "publisher_or_vendor": "BaoStock synthetic",
            "endpoint_or_export_name": "synthetic_k_data",
            "endpoint_version": "v1",
            "request_parameters": "synthetic-only",
            "security_id": security_id,
            "trading_date": "2026-06-12",
            "retrieved_at": "2026-06-12T16:00:00+08:00",
            "observed_at": "2026-06-12T16:00:00+08:00",
            "source_snapshot_id": "SYNTHETIC_D2_T06_SOURCE_SNAPSHOT",
            "raw_response_sha256": "a" * 64,
            "row_count": 1,
            "has_raw_ohlcv": True,
            "has_qfq_ohlc": True,
            "has_hfq_ohlc": True,
            "has_vendor_adjustment_factor": False,
            "has_factor_as_of_time": False,
            "has_revision_timestamp": False,
            "raw_close": 10.0,
            "qfq_close": 11.0,
            "hfq_close": 12.0,
            "vendor_adjustment_factor": None,
            "implied_qfq_factor": 1.1,
            "implied_hfq_factor": 1.2,
            "history_revision_class": "final_revised_history",
            "research_use_tier": "exploration_only",
            "blocking_reason": "candidate_implied_factor",
        }

    def validate(self, rows: list[dict[str, object]]) -> None:
        validate_candidate_probe_rows(rows, self.contract, self.alignment)

    def assert_bad(self, row: dict[str, object]) -> None:
        with self.assertRaises(CandidateMarketSnapshotProbeValidationError):
            self.validate([row])

    def test_synthetic_final_revised_exploration_row_passes(self) -> None:
        self.validate([copy.deepcopy(self.good_row)])

    def test_missing_required_field_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        del row["raw_response_sha256"]
        self.assert_bad(row)

    def test_extra_field_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["extra_field"] = "bad"
        self.assert_bad(row)

    def test_prohibited_source_fails(self) -> None:
        for source_id in [
            "CSINDEX_OFFICIAL",
            "A_STOCK_DATA_RECON",
            "PUBLIC_A_SHARE_ENDPOINTS_REVIEW_BUCKET",
        ]:
            row = copy.deepcopy(self.good_row)
            row["source_registry_id"] = source_id
            with self.subTest(source_id=source_id):
                self.assert_bad(row)

    def test_non_membership_security_id_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["security_id"] = "CN.SSE.999999"
        self.assert_bad(row)

    def test_missing_snapshot_time_or_hash_fails(self) -> None:
        for field in [
            "retrieved_at",
            "observed_at",
            "source_snapshot_id",
            "raw_response_sha256",
        ]:
            row = copy.deepcopy(self.good_row)
            row[field] = ""
            with self.subTest(field=field):
                self.assert_bad(row)

    def test_raw_close_nonpositive_with_implied_factor_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["raw_close"] = 0
        self.assert_bad(row)

    def test_implied_factor_inconsistency_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["implied_qfq_factor"] = 1.11
        self.assert_bad(row)
        row = copy.deepcopy(self.good_row)
        row["implied_hfq_factor"] = 1.21
        self.assert_bad(row)

    def test_point_in_time_candidate_without_asof_revision_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["history_revision_class"] = "point_in_time_candidate"
        self.assert_bad(row)

    def test_formal_candidate_without_complete_evidence_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["research_use_tier"] = "formal_candidate_after_review"
        self.assert_bad(row)

    def test_qfq_hfq_as_raw_fact_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["blocking_reason"] = "qfq_or_hfq_marked_as_raw_trading_fact"
        self.assert_bad(row)

    def test_future_label_event_fields_fail(self) -> None:
        for field in [
            "future_return",
            "label",
            "event_type",
            "pcvt_state",
            "gap_attribution",
        ]:
            row = copy.deepcopy(self.good_row)
            row[field] = "bad"
            with self.subTest(field=field):
                self.assert_bad(row)

    def test_validator_source_has_no_external_access_logic(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
        for forbidden in [
            "requests",
            "urllib",
            "duckdb",
            "data/external",
            "marketdb",
            ".day",
        ]:
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
