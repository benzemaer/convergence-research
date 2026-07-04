from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import (
    build_candidate_outputs,
    build_fetch_plan,
)


class D2T13TnskhdataMaterializerRulesTest(unittest.TestCase):
    def _plan(self):
        rows = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260630",
                "universe_id": "u",
                "time_segment_id": "t",
            }
        ]
        return build_fetch_plan(
            rows, full=True, sample_securities=None, sample_dates_per_security=None
        )

    def _evidence(self):
        return {
            "stock_basic": [
                {"ts_code": "000001.SZ", "list_date": "20100101", "delist_date": ""}
            ],
            "trade_cal": [{"cal_date": "20260630", "is_open": 1}],
            "daily": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 11,
                    "pre_close": 10,
                    "vol": 100,
                    "amount": 200,
                }
            ],
            "stk_limit": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "up_limit": 11,
                    "down_limit": 9,
                }
            ],
            "adj_factor": [
                {"ts_code": "000001.SZ", "trade_date": "20260630", "adj_factor": 1.2}
            ],
            "stock_st": [{"ts_code": "000001.SZ", "trade_date": "20260630"}],
            "suspend_d": [],
            "_metrics": [
                {"provider_error_count": 0, "rate_limit_count": 0, "request_count": 1}
            ],
        }

    def test_units_status_factor_and_adjusted_price_rules(self) -> None:
        outputs = build_candidate_outputs(
            self._plan(),
            self._evidence(),
            source_snapshot_id="snapshot-1",
            artifact_sha256="hash-1",
        )
        raw = outputs["raw"][0]
        self.assertEqual(raw["volume_lot"], 100)
        self.assertEqual(raw["volume_shares"], 10000)
        self.assertEqual(raw["amount_thousand_yuan"], 200)
        self.assertEqual(raw["amount_yuan"], 200000)

        status = outputs["source_status"][0]
        self.assertEqual(status["trading_status"], "normal_trading")
        self.assertEqual(status["suspension_status"], "not_suspended")
        self.assertEqual(status["st_status"], "st")
        self.assertEqual(status["price_limit_status"], "limit_up_touched_or_closed")

        factor = outputs["factor_evidence"][0]
        self.assertEqual(factor["adjustment_factor"], 1.2)
        self.assertEqual(factor["factor_as_of_time"], "20260630 09:20:00 Asia/Shanghai")
        self.assertEqual(factor["adjustment_revision"], "snapshot-1")
        self.assertFalse(factor["strict_provider_row_level_revision_eligible"])

        adjusted = outputs["adjusted_price"][0]
        self.assertEqual(adjusted["hfq_close"], 13.2)
        self.assertEqual(adjusted["qfq_close"], 11)
        self.assertEqual(adjusted["qfq_anchor_policy"], "explicit_end_date_anchor")


if __name__ == "__main__":
    unittest.main()
