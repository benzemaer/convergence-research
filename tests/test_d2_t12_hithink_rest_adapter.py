from __future__ import annotations

import json
import unittest

from scripts.run_d2_t12_provider_remediation_probe import HiThinkRestProviderAdapter


class FakeHttpClient:
    def __init__(self, code=0) -> None:
        self.code = code
        self.calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def get_json(self, url, headers, params):
        self.calls.append((url, headers, params))
        return {
            "code": self.code,
            "data": [{"date": "2026-07-02", "open": 1, "close": 1}],
        }


class D2T12HiThinkRestAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "2026-07-02",
                "universe_id": "CSI800_STATIC_2026_07",
                "time_segment_id": "RAW_10Y_TO_20260704",
            }
        ]

    def test_hithink_rest_uses_x_api_key_header_without_printing_key(self) -> None:
        client = FakeHttpClient()
        result = HiThinkRestProviderAdapter(
            base_url="https://example.test", http_client=client
        ).probe(self.sample, {"HITHINK_API_KEY": "fake-hithink-key"})
        self.assertTrue(client.calls)
        self.assertEqual(client.calls[0][1]["X-api-key"], "fake-hithink-key")
        self.assertEqual(client.calls[0][2]["thscode"], "000001.SZ")
        self.assertNotIn("fake-hithink-key", json.dumps(result, ensure_ascii=False))

    def test_hithink_business_code_nonzero_is_probe_failed(self) -> None:
        result = HiThinkRestProviderAdapter(http_client=FakeHttpClient(code=403)).probe(
            self.sample, {"HITHINK_API_KEY": "fake-hithink-key"}
        )
        statuses = {row["probe_status"] for row in result["capability_matrix"]}
        self.assertEqual(statuses, {"provider_probe_failed"})
        self.assertIn(
            "business_code_403",
            {row["error_code_category"] for row in result["capability_matrix"]},
        )

    def test_missing_hithink_key_is_failed_not_unavailable_placeholder(self) -> None:
        result = HiThinkRestProviderAdapter(http_client=FakeHttpClient()).probe(
            self.sample, {}
        )
        self.assertEqual(
            result["capability_matrix"][0]["probe_status"], "provider_probe_failed"
        )
        self.assertEqual(
            result["capability_matrix"][0]["error_code_category"],
            "hithink_api_key_missing",
        )


if __name__ == "__main__":
    unittest.main()
