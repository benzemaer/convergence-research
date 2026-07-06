from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_d2_tnskhdata_endpoint_chunk_provider_runner import (
    DEFAULT_ENDPOINT_CHUNK_POLICY,
    build_endpoint_aware_fetch_plan,
    endpoint_chunk_counts,
    endpoint_task_counts,
    parse_endpoint_chunk_policy,
    run_endpoint_chunk_provider_runner,
)


class D2T17EndpointChunkRunnerTest(unittest.TestCase):
    def securities(self) -> list[dict[str, str]]:
        return [
            {
                "security_id": "CN.SZSE.000001",
                "ts_code": "000001.SZ",
                "universe_id": "CSI800_STATIC_2026_06",
                "time_segment_id": "DR001_STATIC_BACKFILL_20160101_20260630",
            }
        ]

    def write_universe(self, root: Path) -> Path:
        path = root / "universe.json"
        path.write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "security_id": "CN.SZSE.000001",
                            "universe_id": "CSI800_STATIC_2026_06",
                            "time_segment_id": (
                                "DR001_STATIC_BACKFILL_20160101_20260630"
                            ),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_default_endpoint_chunk_counts(self) -> None:
        tasks = build_endpoint_aware_fetch_plan(
            self.securities(),
            start_date="20160101",
            end_date="20260630",
            endpoint_chunk_policy=DEFAULT_ENDPOINT_CHUNK_POLICY,
        )
        chunk_counts = endpoint_chunk_counts(tasks)

        self.assertEqual(chunk_counts["stock_st"], 1)
        self.assertEqual(chunk_counts["suspend_d"], 1)
        self.assertEqual(chunk_counts["adj_factor"], 3)
        self.assertEqual(chunk_counts["daily"], 4)
        self.assertEqual(chunk_counts["stk_limit"], 4)

    def test_custom_daily_year_generates_eleven_chunks(self) -> None:
        policy = parse_endpoint_chunk_policy(
            "daily=year,adj_factor=5year,stk_limit=year,"
            "stock_st=full-range,suspend_d=full-range"
        )
        tasks = build_endpoint_aware_fetch_plan(
            self.securities(),
            endpoints=("daily",),
            start_date="20160101",
            end_date="20260630",
            endpoint_chunk_policy=policy,
        )

        self.assertEqual(len(tasks), 11)
        self.assertEqual(tasks[0].start_date, "20160101")
        self.assertEqual(tasks[-1].end_date, "20260630")

    def test_task_hash_changes_with_endpoint_chunk_policy(self) -> None:
        default_task = build_endpoint_aware_fetch_plan(
            self.securities(),
            endpoints=("daily",),
            start_date="20160101",
            end_date="20260630",
            endpoint_chunk_policy=DEFAULT_ENDPOINT_CHUNK_POLICY,
        )[0]
        year_task = build_endpoint_aware_fetch_plan(
            self.securities(),
            endpoints=("daily",),
            start_date="20160101",
            end_date="20260630",
            endpoint_chunk_policy=parse_endpoint_chunk_policy("daily=year"),
        )[0]

        self.assertNotEqual(default_task.task_hash, year_task.task_hash)
        self.assertIn("3year", default_task.task_id)
        self.assertIn("year", year_task.task_id)

    def test_dry_run_summary_includes_endpoint_counts_and_t17_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "t17"

            report = run_endpoint_chunk_provider_runner(
                client=None,
                output_dir=output_dir,
                security_universe=self.write_universe(root),
                start_date="20160101",
                end_date="20260630",
                dry_run_plan=True,
            )

            self.assertFalse(report["remote_provider_called"])
            self.assertEqual(report["endpoint_chunk_counts"]["stock_st"], 1)
            self.assertEqual(report["endpoint_chunk_counts"]["suspend_d"], 1)
            self.assertEqual(report["endpoint_chunk_counts"]["adj_factor"], 3)
            self.assertIn("endpoint_task_counts", report)
            self.assertEqual(
                report["total_task_count"],
                sum(report["endpoint_task_counts"].values()),
            )
            self.assertTrue((output_dir / "d2_t17_fetch_plan.jsonl").exists())
            self.assertTrue((output_dir / "d2_t17_run_summary.json").exists())
            self.assertFalse((output_dir / "d2_t16_fetch_plan.jsonl").exists())

    def test_different_output_dirs_do_not_mix_t17_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            universe = self.write_universe(root)
            first = root / "first"
            second = root / "second"

            run_endpoint_chunk_provider_runner(
                client=None,
                output_dir=first,
                security_universe=universe,
                start_date="20260101",
                end_date="20260630",
                dry_run_plan=True,
            )
            run_endpoint_chunk_provider_runner(
                client=None,
                output_dir=second,
                security_universe=universe,
                start_date="20260101",
                end_date="20260630",
                dry_run_plan=True,
            )

            self.assertTrue((first / "d2_t17_fetch_plan.jsonl").exists())
            self.assertTrue((second / "d2_t17_fetch_plan.jsonl").exists())
            self.assertFalse((first / "d2_t17_progress_status.json").exists())
            self.assertFalse((second / "d2_t17_progress_status.json").exists())
            self.assertNotEqual(first, second)

    def test_endpoint_task_counts_match_plan(self) -> None:
        tasks = build_endpoint_aware_fetch_plan(
            self.securities(),
            start_date="20160101",
            end_date="20260630",
            endpoint_chunk_policy=DEFAULT_ENDPOINT_CHUNK_POLICY,
        )

        self.assertEqual(endpoint_task_counts(tasks)["stock_st"], 1)
        self.assertEqual(endpoint_task_counts(tasks)["suspend_d"], 1)
        self.assertEqual(endpoint_task_counts(tasks)["adj_factor"], 3)

    def test_task_doc_keeps_d3_r0_and_research_outputs_blocked(self) -> None:
        doc = Path("docs/tasks/D2-T17_endpoint_aware_runner_chunks.md").read_text(
            encoding="utf-8"
        )
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn(
            "current_task: D2-T18 provider coverage blocker diagnostics",
            readme,
        )
        self.assertIn(
            "D3-T07 remains blocked until D2 coverage blockers are resolved",
            readme,
        )
        for token in (
            "D3 rows",
            "PCVT",
            "labels",
            "returns",
            "backtest",
            "portfolio",
        ):
            self.assertIn(token, doc)


if __name__ == "__main__":
    unittest.main()
