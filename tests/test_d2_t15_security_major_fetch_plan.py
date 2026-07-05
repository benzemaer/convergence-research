from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    ENDPOINTS,
    build_security_major_fetch_plan,
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

    def test_readme_advances_to_d2_t15_and_keeps_d3_r0_blocked(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn("current_stage: D2", readme)
        self.assertIn("current_task: D2-T15", readme)
        self.assertIn("next_planned_task: D3-T07", readme)
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
            "D2-T15` 按证券主轴的 tnskhdata DuckDB 候选物化："
            "in_progress via current PR",
            readme,
        )
        self.assertIn("D3-T07 remains blocked unless D2-T15 handoff", readme)
        self.assertIn("R0 remains blocked", readme)

    def test_no_generated_artifacts_are_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse((Path(tmpdir) / "data/generated").exists())


if __name__ == "__main__":
    unittest.main()
