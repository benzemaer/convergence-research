from __future__ import annotations

import unittest

import pandas as pd

from scripts.run_d2_t12_provider_remediation_probe import (
    TnskhdataProviderAdapter,
    TushareCompatibleProviderAdapter,
)


class FakeProClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def stock_basic(self, **kwargs):
        self.calls.append(("stock_basic", kwargs))
        return pd.DataFrame([{"ts_code": "000001.SZ", "name": "Ping An"}])

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        return pd.DataFrame([{"cal_date": "20260702", "is_open": 1}])

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260702",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                }
            ]
        )

    def daily_basic(self, **kwargs):
        self.calls.append(("daily_basic", kwargs))
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260702"}])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260702",
                    "up_limit": 11,
                    "down_limit": 9,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        return pd.DataFrame(
            [{"ts_code": "000001.SZ", "trade_date": "20260702", "adj_factor": 1.23}]
        )

    def suspend_d(self, **kwargs):
        self.calls.append(("suspend_d", kwargs))
        return pd.DataFrame(columns=["ts_code", "suspend_date"])

    def namechange(self, **kwargs):
        self.calls.append(("namechange", kwargs))
        return pd.DataFrame(
            [{"ts_code": "000001.SZ", "name": "ST sample", "start_date": "20260101"}]
        )


class D2T12TnskhdataProviderAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "2026-07-02",
                "universe_id": "CSI800_STATIC_2026_07",
                "time_segment_id": "RAW_10Y_TO_20260704",
            }
        ]

    def test_tnskhdata_adapter_uses_fake_pro_client_and_ts_code_mapping(self) -> None:
        client = FakeProClient()
        result = TnskhdataProviderAdapter(pro_client=client).probe(
            self.sample, {"TNSKHDATA_TOKEN": "fake-token"}
        )
        self.assertEqual(
            {call[0] for call in client.calls},
            {
                "stock_basic",
                "trade_cal",
                "daily",
                "daily_basic",
                "stk_limit",
                "adj_factor",
                "suspend_d",
                "namechange",
            },
        )
        daily_call = [call for call in client.calls if call[0] == "daily"][0]
        self.assertEqual(daily_call[1]["ts_code"], "000001.SZ")
        self.assertTrue(result["capability_matrix"])
        factor_row = result["factor_rows"][0]
        self.assertEqual(factor_row["adjustment_factor"], 1.23)
        self.assertIsNone(factor_row["factor_as_of_time"])
        self.assertIsNone(factor_row["adjustment_revision"])
        self.assertFalse(factor_row["point_in_time_eligible"])

    def test_tushare_adapter_shares_ts_code_mapping(self) -> None:
        client = FakeProClient()
        TushareCompatibleProviderAdapter(pro_client=client).probe(
            self.sample, {"TUSHARE_TOKEN": "fake-token"}
        )
        stk_limit_call = [call for call in client.calls if call[0] == "stk_limit"][0]
        self.assertEqual(stk_limit_call[1]["ts_code"], "000001.SZ")

    def test_stk_limit_does_not_auto_resolve_price_limit_status(self) -> None:
        result = TnskhdataProviderAdapter(pro_client=FakeProClient()).probe(
            self.sample, {"TNSKHDATA_TOKEN": "fake-token"}
        )
        rows = [row for row in result["status_rows"] if row["limit_up_price"] == 11]
        self.assertEqual(rows[0]["price_limit_status"], "unknown")

    def test_namechange_marks_st_as_derived_candidate(self) -> None:
        result = TnskhdataProviderAdapter(pro_client=FakeProClient()).probe(
            self.sample, {"TNSKHDATA_TOKEN": "fake-token"}
        )
        rows = [
            row for row in result["status_rows"] if row["st_status"] == "st_candidate"
        ]
        self.assertEqual(
            rows[0]["st_status_evidence_method"], "namechange_derived_candidate"
        )


if __name__ == "__main__":
    unittest.main()
