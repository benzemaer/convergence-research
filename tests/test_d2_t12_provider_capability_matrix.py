from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_d2_t12_provider_remediation_probe import run_provider_remediation_probe

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs/d2/tnskhdata_tushare_hithink_provider_remediation_contract.v1.json"
)


class FakeAdapter:
    provider_id = "fake_provider"

    def __init__(self) -> None:
        self.called = False

    def probe(self, sample_rows, credentials):
        self.called = True
        return {
            "provider_id": self.provider_id,
            "capability_matrix": [
                {
                    "provider_id": self.provider_id,
                    "api_name": "fake_api",
                    "probe_status": "field_missing",
                    "rows_requested": len(sample_rows),
                    "rows_returned": 1,
                    "fields_returned": ["adjustment_factor"],
                    "required_fields_covered": ["adjustment_factor"],
                    "required_fields_missing": [
                        "factor_as_of_time",
                        "adjustment_revision",
                    ],
                    "error_code_category": None,
                    "error_message_redacted": None,
                }
            ],
            "status_rows": [],
            "factor_rows": [
                {
                    **sample_rows[0],
                    "provider_id": self.provider_id,
                    "adjustment_factor": 1.0,
                    "factor_as_of_time": None,
                    "adjustment_revision": None,
                    "adjustment_factor_direction": (
                        "provider_adj_factor_no_asof_revision"
                    ),
                    "point_in_time_eligible": False,
                }
            ],
        }


class D2T12ProviderCapabilityMatrixTest(unittest.TestCase):
    def test_runner_outputs_aggregate_reports_without_row_level_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            candidate = tmp / "candidate.json"
            candidate.write_text(
                json.dumps(
                    [
                        {
                            "security_id": "XSHE.000001",
                            "trading_date": "2026-07-02",
                            "universe_id": "CSI800_STATIC_2026_07",
                            "time_segment_id": "RAW_10Y_TO_20260704",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            adapter = FakeAdapter()
            result = run_provider_remediation_probe(
                contract=json.loads(CONTRACT.read_text(encoding="utf-8")),
                candidate_universe_path=candidate,
                output_dir=tmp / "out",
                credentials={},
                adapters=[adapter],
            )
            self.assertTrue(adapter.called)
            self.assertTrue(result["no_row_level_payload_returned"])
            gate = result["redacted_summary"]["gate"]
            self.assertFalse(gate["duckdb_written"])
            self.assertFalse(gate["data_version_published"])
            self.assertFalse(gate["d3_rows_generated"])
            self.assertFalse(gate["pcvt_values_generated"])
            self.assertFalse(gate["r0_state_generated"])
            self.assertEqual(
                gate["d3_handoff_decision"], "d3_candidate_generation_blocked"
            )
            serialized = json.dumps(result, ensure_ascii=False)
            self.assertNotIn("vendor_payload", serialized)
            self.assertNotIn("raw_rows", serialized)

    def test_unmapped_security_does_not_call_provider_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            candidate = tmp / "candidate.json"
            candidate.write_text(
                json.dumps(
                    [
                        {
                            "security_id": "BAD.CODE",
                            "trading_date": "2026-07-02",
                            "universe_id": "CSI800_STATIC_2026_07",
                            "time_segment_id": "RAW_10Y_TO_20260704",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            adapter = FakeAdapter()
            result = run_provider_remediation_probe(
                contract=json.loads(CONTRACT.read_text(encoding="utf-8")),
                candidate_universe_path=candidate,
                output_dir=tmp / "out",
                credentials={},
                adapters=[adapter],
            )
            self.assertFalse(adapter.called)
            self.assertEqual(
                result["redacted_summary"]["gate"]["mapped_probe_row_count"], 0
            )
            self.assertEqual(
                result["redacted_summary"]["mapping"][
                    "query_skipped_for_unmapped_count"
                ],
                1,
            )


if __name__ == "__main__":
    unittest.main()
