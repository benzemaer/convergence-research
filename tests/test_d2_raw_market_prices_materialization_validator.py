from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.validate_d2_raw_market_prices_materialization import (
    RawMarketPriceValidationError,
    validate_raw_market_price_rows,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/raw_market_prices_materialization_contract.v1.json"
ALIGNMENT_PATH = ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
SCRIPT_PATH = ROOT / "scripts/validate_d2_raw_market_prices_materialization.py"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2RawMarketPricesMaterializationValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(CONTRACT_PATH)
        cls.alignment = load(ALIGNMENT_PATH)
        security_id = cls.alignment["rows"][0]["security_id"]
        cls.good_row = {
            "data_version": cls.contract["data_version"],
            "universe_id": cls.contract["universe_id"],
            "time_segment_id": cls.contract["time_segment_id"],
            "security_id": security_id,
            "trading_date": "2026-06-12",
            "raw_open": 10.0,
            "raw_high": 11.0,
            "raw_low": 9.5,
            "raw_close": 10.5,
            "volume": 1000,
            "amount": 10500.0,
            "trading_status": "unknown",
            "price_limit_status": "unknown",
            "source_registry_id": "BAOSTOCK",
            "source_snapshot_id": "SYNTHETIC_SOURCE_SNAPSHOT",
            "observed_at": "2026-06-12T16:30:00+08:00",
            "run_id": "SYNTHETIC_D2_T03_VALIDATOR_RUN",
        }

    def validate(self, rows: list[dict[str, object]]) -> None:
        validate_raw_market_price_rows(rows, self.contract, self.alignment)

    def assert_bad(self, row: dict[str, object]) -> None:
        with self.assertRaises(RawMarketPriceValidationError):
            self.validate([row])

    def test_synthetic_valid_rows_pass(self) -> None:
        self.validate([copy.deepcopy(self.good_row)])

    def test_missing_required_field_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        del row["raw_close"]
        self.assert_bad(row)

    def test_extra_or_adjusted_fields_fail(self) -> None:
        for field in [
            "ticker",
            "exchange",
            "source_symbol",
            "adj_close",
            "adjustment_factor",
            "gap_attribution",
        ]:
            row = copy.deepcopy(self.good_row)
            row[field] = "bad"
            with self.subTest(field=field):
                self.assert_bad(row)

    def test_prohibited_sources_fail(self) -> None:
        for source_id in ["CSINDEX_OFFICIAL", "A_STOCK_DATA_RECON"]:
            row = copy.deepcopy(self.good_row)
            row["source_registry_id"] = source_id
            with self.subTest(source_id=source_id):
                self.assert_bad(row)

    def test_ohlc_order_errors_fail(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["raw_high"] = 9.0
        self.assert_bad(row)
        row = copy.deepcopy(self.good_row)
        row["raw_low"] = 12.0
        self.assert_bad(row)

    def test_negative_volume_or_amount_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["volume"] = -1
        self.assert_bad(row)
        row = copy.deepcopy(self.good_row)
        row["amount"] = -1.0
        self.assert_bad(row)

    def test_observed_at_missing_or_equal_trading_date_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["observed_at"] = ""
        self.assert_bad(row)
        row = copy.deepcopy(self.good_row)
        row["observed_at"] = row["trading_date"]
        self.assert_bad(row)

    def test_security_id_outside_membership_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        row["security_id"] = "CN.SSE.999999"
        self.assert_bad(row)

    def test_duplicate_primary_key_fails(self) -> None:
        row = copy.deepcopy(self.good_row)
        with self.assertRaises(RawMarketPriceValidationError):
            self.validate([row, copy.deepcopy(row)])

    def test_silent_status_conversions_fail(self) -> None:
        for field, value in [
            ("trading_status", False),
            ("trading_status", "active"),
            ("price_limit_status", False),
            ("price_limit_status", "not_at_limit"),
        ]:
            row = copy.deepcopy(self.good_row)
            row[field] = value
            with self.subTest(field=field, value=value):
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
