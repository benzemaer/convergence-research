from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from scripts.materialize_d2_tnskhdata_candidate_evidence import (
    build_synthetic_tnskhdata_evidence,
    materialize_tnskhdata_candidate_evidence,
)


class D2T12TnskhdataDailyRebuildTest(unittest.TestCase):
    def _row(self) -> dict[str, object]:
        return {
            "security_id": "XSHE.000001",
            "trading_date": "20260702",
            "stock_basic": {"list_date": "20200101", "list_status": "L"},
            "trade_cal": {"is_open": 1},
            "daily": {"open": 10, "high": 11, "low": 9.5, "close": 11},
            "stk_limit": {"up_limit": 11, "down_limit": 9},
            "stock_st": None,
            "suspend_d": None,
            "adj_factor": {"adj_factor": 1.2},
        }

    def test_synthetic_daily_rebuild_generates_status_factor_and_adjusted_rows(
        self,
    ) -> None:
        evidence = build_synthetic_tnskhdata_evidence([self._row()])
        self.assertEqual(
            evidence["source_status"][0]["trading_status"], "normal_trading"
        )
        self.assertEqual(
            evidence["source_status"][0]["price_limit_status"],
            "limit_up_touched_or_closed",
        )
        self.assertEqual(
            evidence["factor_evidence"][0]["point_in_time_eligibility_class"],
            "source_level_asof_snapshot_revision",
        )
        self.assertEqual(evidence["adjusted_price"][0]["hfq_close"], 13.2)
        self.assertEqual(
            evidence["adjusted_price"][0]["qfq_anchor_policy"],
            "explicit_end_date_anchor_required",
        )

    def test_materializer_writes_only_ignored_outputs_without_secret_or_formal_unlock(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate.json"
            env_file = root / ".env.local"
            output_dir = root / "data/generated/d2/d2_t12_tnskhdata_candidate_evidence"
            candidate.write_text(
                json.dumps({"rows": [self._row()]}, ensure_ascii=False),
                encoding="utf-8",
            )
            env_file.write_text("TNSKHDATA_TOKEN=secret-value\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                report = materialize_tnskhdata_candidate_evidence(
                    candidate_universe=candidate,
                    env_file=env_file,
                    start_date="20260702",
                    end_date="20260702",
                    output_dir=output_dir,
                )
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn("secret-value", combined)
            self.assertFalse(report["duckdb_written"])
            self.assertFalse(report["data_version_published"])
            self.assertFalse(report["d3_rows_generated"])
            self.assertFalse(report["r0_state_generated"])
            self.assertTrue(
                (output_dir / "tnskhdata_candidate_file_hash_summary.json").exists()
            )
            reconciliation = json.loads(
                (output_dir / "tnskhdata_reconciliation_report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                reconciliation["qfq_anchor_policy"], "explicit_end_date_anchor_required"
            )


if __name__ == "__main__":
    unittest.main()
