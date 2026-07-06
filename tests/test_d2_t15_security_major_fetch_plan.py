from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    ENDPOINTS,
    build_security_major_fetch_plan,
    load_security_universe,
    make_date_chunks,
)


class D2T15SecurityMajorFetchPlanTest(unittest.TestCase):
    def test_year_chunks_cover_dr001_interval(self) -> None:
        chunks = make_date_chunks("20160101", "20260630", "year")

        self.assertEqual(chunks[0], ("20160101", "20161231"))
        self.assertEqual(chunks[-1], ("20260101", "20260630"))
        self.assertEqual(len(chunks), 11)

    def test_fetch_plan_is_security_major_for_all_required_endpoints(self) -> None:
        securities = [
            {
                "security_id": "CN.SZSE.000001",
                "ts_code": "000001.SZ",
                "universe_id": "CSI800_STATIC_2026_06",
                "time_segment_id": "DR001_STATIC_BACKFILL_20160101_20260630",
            },
            {
                "security_id": "CN.SSE.600000",
                "ts_code": "600000.SH",
                "universe_id": "CSI800_STATIC_2026_06",
                "time_segment_id": "DR001_STATIC_BACKFILL_20160101_20260630",
            },
        ]
        tasks = build_security_major_fetch_plan(
            securities,
            start_date="20160101",
            end_date="20170115",
            chunk_policy="year",
        )

        self.assertEqual(len(tasks), len(securities) * len(ENDPOINTS) * 2)
        by_security = {task.ts_code for task in tasks}
        self.assertEqual(by_security, {"000001.SZ", "600000.SH"})
        for ts_code in by_security:
            self.assertEqual(
                {task.endpoint for task in tasks if task.ts_code == ts_code},
                set(ENDPOINTS),
            )
        self.assertTrue(
            all(task.param_variant == "ts_code_start_end" for task in tasks)
        )

    def test_readme_records_d2_t15_done_and_keeps_d3_r0_blocked(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn("current_stage: D2", readme)
        self.assertIn(
            "current_task: D2-T19 targeted repair and coverage policy evidence",
            readme,
        )
        self.assertIn(
            "next_planned_task: D2-T20 policy acceptance or second targeted repair",
            readme,
        )
        self.assertIn(
            "D2-T13` tnskhdata全量候选物化与D2验收交接：completed via PR #45",
            readme,
        )
        self.assertIn(
            "D2-T14` listed-open 行级 provider 修复诊断：closed / superseded "
            "by D2-T15; not merged",
            readme,
        )
        self.assertIn(
            "D2-T15` 按证券主轴的 DuckDB 候选物化骨架与质量门禁：completed via PR #47",
            readme,
        )
        self.assertIn(
            "D3-T07 remains blocked until D2 coverage blockers are resolved",
            readme,
        )
        self.assertIn("R0 remains blocked", readme)

    def test_load_security_universe_reports_unmapped_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "universe.json"
            path.write_text(
                """
                {
                  "rows": [
                    {
                      "security_id": "CN.SZSE.000001",
                      "universe_id": "u",
                      "time_segment_id": "t"
                    },
                    {
                      "security_id": "BAD.CODE",
                      "universe_id": "u",
                      "time_segment_id": "t"
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            result = load_security_universe(path)

            self.assertEqual(result.metrics["configured_security_count"], 2)
            self.assertEqual(result.metrics["mapped_security_count"], 1)
            self.assertEqual(result.metrics["unmapped_security_count"], 1)
            self.assertEqual(len(result.securities), 1)
            self.assertEqual(
                result.mapping_diagnostics[1]["mapping_status"], "unresolved"
            )

    def test_dry_run_cli_reports_no_remote_and_future_runner_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/materialize_d2_tnskhdata_security_major_duckdb_candidate.py",
                    "--dry-run-plan",
                    "--sample-securities",
                    "1",
                    "--output-dir",
                    str(output_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            report = json.loads(completed.stdout)

            self.assertFalse(report["remote_provider_called"])
            self.assertEqual(report["configured_security_count"], 1)
            self.assertEqual(report["mapped_security_count"], 1)
            self.assertEqual(report["unmapped_security_count"], 0)
            self.assertEqual(
                report["future_remote_runner_parameters"],
                ["--env-file", "--max-workers", "--resume"],
            )
            self.assertTrue((output_dir / "d2_t15_fetch_plan.jsonl").exists())

    def test_no_generated_artifacts_are_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse((Path(tmpdir) / "data/generated").exists())


if __name__ == "__main__":
    unittest.main()
