from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.validate_d2_continuous_price_construction import (
    ContinuousPriceConstructionValidationError,
    validate_continuous_price_rows,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/continuous_price_construction_contract.v1.json"
ALIGNMENT_PATH = ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
SCRIPT_PATH = ROOT / "scripts/validate_d2_continuous_price_construction.py"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2ContinuousPriceConstructionValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(CONTRACT_PATH)
        cls.alignment = load(ALIGNMENT_PATH)
        security_id = cls.alignment["rows"][0]["security_id"]
        cls.cutoffs = {"2026-06-12": "2026-06-12T16:30:00+08:00"}
        cls.identity_row = {
            "data_version": cls.contract["data_version"],
            "universe_id": cls.contract["universe_id"],
            "time_segment_id": cls.contract["time_segment_id"],
            "security_id": security_id,
            "trading_date": "2026-06-12",
            "adj_open": 10.0,
            "adj_high": 11.0,
            "adj_low": 9.5,
            "adj_close": 10.5,
            "adjustment_factor": 1.0,
            "adjustment_method": "identity_no_adjustment",
            "factor_as_of_time": "2026-06-12T16:00:00+08:00",
            "corporate_action_flag": "known_no_action",
            "adjustment_revision": "candidate",
            "source_registry_id": "HITHINK_FINANCIAL_API",
            "source_snapshot_id": "SYNTHETIC_CONTINUOUS_SOURCE_SNAPSHOT",
            "run_id": "SYNTHETIC_D2_T05_VALIDATOR_RUN",
            "raw_open": 10.0,
            "raw_high": 11.0,
            "raw_low": 9.5,
            "raw_close": 10.5,
            "volume": 1000,
            "amount": 10500.0,
            "trading_status": "unknown",
            "price_limit_status": "unknown",
            "raw_source_snapshot_id": "SYNTHETIC_RAW_SOURCE_SNAPSHOT",
            "raw_observed_at": "2026-06-12T15:30:00+08:00",
            "factor_source_snapshot_id": "SYNTHETIC_FACTOR_SOURCE_SNAPSHOT",
        }
        cls.factor_row = copy.deepcopy(cls.identity_row)
        cls.factor_row.update(
            {
                "adj_open": 12.0,
                "adj_high": 13.2,
                "adj_low": 11.4,
                "adj_close": 12.6,
                "adjustment_factor": 1.2,
                "adjustment_method": "forward_adjusted",
                "corporate_action_flag": "known_action",
                "adjustment_revision": "v1",
            }
        )

    def validate(self, rows: list[dict[str, object]]) -> None:
        validate_continuous_price_rows(
            rows, self.contract, self.alignment, self.cutoffs
        )

    def assert_bad(self, row: dict[str, object]) -> None:
        with self.assertRaises(ContinuousPriceConstructionValidationError):
            self.validate([row])

    def test_synthetic_identity_rows_pass(self) -> None:
        self.validate([copy.deepcopy(self.identity_row)])

    def test_synthetic_multiplicative_factor_rows_pass(self) -> None:
        self.validate([copy.deepcopy(self.factor_row)])

    def test_missing_required_field_fails(self) -> None:
        row = copy.deepcopy(self.identity_row)
        del row["adj_close"]
        self.assert_bad(row)

    def test_extra_fields_fail(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["extra_field"] = "bad"
        self.assert_bad(row)

    def test_nonpositive_adjustment_factor_fails(self) -> None:
        for value in [0, -1.0]:
            row = copy.deepcopy(self.identity_row)
            row["adjustment_factor"] = value
            with self.subTest(value=value):
                self.assert_bad(row)

    def test_adjusted_ohlc_order_errors_fail(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["adj_high"] = 9.0
        self.assert_bad(row)
        row = copy.deepcopy(self.identity_row)
        row["adj_low"] = 12.0
        self.assert_bad(row)

    def test_missing_or_future_factor_as_of_time_fails(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["factor_as_of_time"] = ""
        self.assert_bad(row)
        row = copy.deepcopy(self.identity_row)
        row["factor_as_of_time"] = "2026-06-12T16:31:00+08:00"
        self.assert_bad(row)

    def test_identity_factor_must_equal_one(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["adjustment_factor"] = 1.1
        self.assert_bad(row)

    def test_identity_adjusted_prices_must_equal_raw_prices(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["adj_close"] = 10.6
        self.assert_bad(row)

    def test_multiplicative_adjusted_prices_must_match_factor(self) -> None:
        row = copy.deepcopy(self.factor_row)
        row["adj_close"] = 12.7
        self.assert_bad(row)

    def test_reverse_check_must_recover_raw_prices(self) -> None:
        row = copy.deepcopy(self.factor_row)
        row["raw_close"] = 10.4
        self.assert_bad(row)

    def test_unknown_method_or_revision_fails(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["adjustment_method"] = "unknown"
        self.assert_bad(row)
        row = copy.deepcopy(self.identity_row)
        row["adjustment_revision"] = "unknown"
        self.assert_bad(row)

    def test_bad_method_or_revision_fails(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["adjustment_method"] = "bad_method"
        self.assert_bad(row)
        row = copy.deepcopy(self.identity_row)
        row["adjustment_revision"] = "bad_revision"
        self.assert_bad(row)

    def test_prohibited_source_registry_ids_fail(self) -> None:
        for source_id in [
            "CSINDEX_OFFICIAL",
            "A_STOCK_DATA_RECON",
            "PUBLIC_A_SHARE_ENDPOINTS_REVIEW_BUCKET",
        ]:
            row = copy.deepcopy(self.identity_row)
            row["source_registry_id"] = source_id
            with self.subTest(source_id=source_id):
                self.assert_bad(row)

    def test_baostock_formal_adjusted_price_marker_fails(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["candidate_source_boundary"][
            "baostock_formal_adjusted_price_source_allowed"
        ] = True
        row = copy.deepcopy(self.identity_row)
        row["source_registry_id"] = "BAOSTOCK"
        with self.assertRaises(ContinuousPriceConstructionValidationError):
            validate_continuous_price_rows(
                [row], contract, self.alignment, self.cutoffs
            )

    def test_corporate_action_flag_silent_false_values_fail(self) -> None:
        for value in [False, 0, "false", "0", ""]:
            row = copy.deepcopy(self.identity_row)
            row["corporate_action_flag"] = value
            with self.subTest(value=value):
                self.assert_bad(row)

    def test_security_id_outside_membership_fails(self) -> None:
        row = copy.deepcopy(self.identity_row)
        row["security_id"] = "CN.SSE.999999"
        self.assert_bad(row)

    def test_duplicate_primary_key_fails(self) -> None:
        row = copy.deepcopy(self.identity_row)
        with self.assertRaises(ContinuousPriceConstructionValidationError):
            self.validate([row, copy.deepcopy(row)])

    def test_gap_label_future_fields_fail(self) -> None:
        for field in [
            "raw_gap",
            "adjusted_gap",
            "gap_attribution",
            "future_return",
            "label",
            "event_type",
            "pcvt_state",
            "formal_ingestion_authorized",
        ]:
            row = copy.deepcopy(self.identity_row)
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
