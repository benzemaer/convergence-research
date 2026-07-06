from __future__ import annotations

import hashlib
import unittest

from scripts.prepare_d2_t20_policy_evidence import (
    hash_document,
    prepare_manifest,
)


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str = "records") -> list[dict[str, object]]:
        if orient != "records":
            raise ValueError(orient)
        return self._rows


class FakeAdjFactorClient:
    def __init__(self, rows_by_ts_code: dict[str, list[dict[str, object]]]) -> None:
        self.rows_by_ts_code = rows_by_ts_code

    def adj_factor(self, *, ts_code: str, start_date: str, end_date: str) -> FakeFrame:
        rows = [
            row
            for row in self.rows_by_ts_code.get(ts_code, [])
            if start_date <= str(row["trade_date"]) <= end_date
        ]
        return FakeFrame(rows)


class D2T20PolicyEvidencePreparationTest(unittest.TestCase):
    def test_pdf_download_hashes_bytes(self) -> None:
        payload = b"%PDF synthetic"

        document = hash_document(
            {
                "url": "https://example.test/a.pdf",
                "hash_target": "pdf",
            },
            downloader=lambda _url: (payload, "application/pdf"),
        )

        self.assertEqual(document["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(document["evidence_status"], "hash_verified")
        self.assertEqual(document["hash_target"], "pdf")

    def test_html_fallback_hashes_normalized_visible_text(self) -> None:
        payload = b"<html><body><h1>A</h1> <p>B</p></body></html>"

        document = hash_document(
            {
                "url": "https://example.test/a.html",
                "hash_target": "html_or_text",
            },
            downloader=lambda _url: (payload, "text/html"),
        )

        self.assertEqual(document["sha256"], hashlib.sha256(b"A B").hexdigest())
        self.assertEqual(document["evidence_status"], "hash_verified")
        self.assertEqual(document["hash_target"], "html_or_text")

    def test_adj_factor_all_one_recommends_neutral_policy(self) -> None:
        manifest = {
            "listing_pause_intervals": [],
            "adj_factor_policy_evidence": [
                {
                    "ts_code": "688981.SH",
                    "query_start_date": "20200101",
                    "query_end_date": "20200103",
                }
            ],
        }
        client = FakeAdjFactorClient(
            {
                "688981.SH": [
                    {
                        "ts_code": "688981.SH",
                        "trade_date": "20200101",
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": "688981.SH",
                        "trade_date": "20200102",
                        "adj_factor": 1.0,
                    },
                ]
            }
        )

        resolved = prepare_manifest(manifest, client=client)
        row = resolved["adj_factor_policy_evidence"][0]

        self.assertEqual(row["recommended_policy"], "neutral_factor_1_policy_candidate")
        self.assertEqual(row["factor_intervals"][0]["effective_adj_factor"], 1.0)
        self.assertEqual(row["evidence_status"], "hash_verified")

    def test_adj_factor_non_one_recommends_factor_interval_policy(self) -> None:
        manifest = {
            "listing_pause_intervals": [],
            "adj_factor_policy_evidence": [
                {
                    "ts_code": "689009.SH",
                    "query_start_date": "20200101",
                    "query_end_date": "20200103",
                }
            ],
        }
        client = FakeAdjFactorClient(
            {
                "689009.SH": [
                    {
                        "ts_code": "689009.SH",
                        "trade_date": "20200101",
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": "689009.SH",
                        "trade_date": "20200102",
                        "adj_factor": 1.02,
                    },
                    {
                        "ts_code": "689009.SH",
                        "trade_date": "20200103",
                        "adj_factor": 1.02,
                    },
                ]
            }
        )

        resolved = prepare_manifest(manifest, client=client)
        row = resolved["adj_factor_policy_evidence"][0]

        self.assertEqual(row["recommended_policy"], "factor_interval_policy_candidate")
        self.assertEqual(len(row["factor_intervals"]), 2)
        self.assertEqual(row["factor_intervals"][1]["effective_adj_factor"], 1.02)
        self.assertEqual(row["evidence_status"], "hash_verified")


if __name__ == "__main__":
    unittest.main()
