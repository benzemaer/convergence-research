from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import duckdb

from scripts.run_d2_tnskhdata_security_major_provider_runner import (
    AdaptiveRequestLimiter,
    D2T16LedgerEntry,
    D2T16ProviderRunnerError,
    build_runner_fetch_plan,
    fetch_task_with_retry,
    filter_tasks_for_runner_resume,
    run_provider_runner,
)


class FakeTnskhdataClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def trade_cal(self, **params):
        self.calls.append(("trade_cal", params))
        return [{"cal_date": params["start_date"], "is_open": "1"}]

    def stock_basic(self, **params):
        self.calls.append(("stock_basic", params))
        if "ts_code" in params:
            raise AssertionError("stock_basic must not be called per ts_code")
        return [
            {
                "ts_code": "000001.SZ",
                "list_date": "20000101",
                "delist_date": "",
            },
            {
                "ts_code": "999999.SZ",
                "list_date": "20000101",
                "delist_date": "",
            },
        ]

    def daily(self, **params):
        self.calls.append(("daily", params))
        return [
            {
                "ts_code": params["ts_code"],
                "trade_date": params.get("start_date") or params.get("trade_date"),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "pre_close": 9.8,
                "vol": 1000,
                "amount": 10000,
            }
        ]

    def adj_factor(self, **params):
        self.calls.append(("adj_factor", params))
        return [
            {
                "ts_code": params["ts_code"],
                "trade_date": params["start_date"],
                "adj_factor": 1.0,
            }
        ]

    def stock_st(self, **params):
        self.calls.append(("stock_st", params))
        return [
            {
                "ts_code": params["ts_code"],
                "ann_date": params["start_date"],
                "name_type": "normal",
            }
        ]

    def suspend_d(self, **params):
        self.calls.append(("suspend_d", params))
        return [
            {
                "ts_code": params["ts_code"],
                "trade_date": params.get("start_date") or params.get("trade_date"),
                "suspend_type": "S",
            }
        ]

    def stk_limit(self, **params):
        self.calls.append(("stk_limit", params))
        if "ts_code" in params:
            raise TypeError("unexpected argument ts_code")
        return [
            {
                "ts_code": "000001.SZ",
                "trade_date": params["start_date"],
                "up_limit": 11,
                "down_limit": 9,
                "pre_close": 10,
            },
            {
                "ts_code": "999999.SZ",
                "trade_date": params["start_date"],
                "up_limit": 99,
                "down_limit": 1,
            },
        ]


class BadDailyClient(FakeTnskhdataClient):
    def daily(self, **params):
        self.calls.append(("daily", params))
        return [
            {
                "ts_code": params["ts_code"],
                "trade_date": params["start_date"],
                "high": 11,
                "low": 9,
                "close": 10,
            }
        ]


class TradeCalNoExchangeClient(FakeTnskhdataClient):
    def trade_cal(self, start_date, end_date):
        self.calls.append(
            ("trade_cal", {"start_date": start_date, "end_date": end_date})
        )
        return [{"cal_date": start_date, "is_open": "1"}]


class D2T16ProviderRunnerTest(unittest.TestCase):
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

    def task(self, endpoint: str):
        securities = [
            {
                "security_id": "CN.SZSE.000001",
                "ts_code": "000001.SZ",
                "universe_id": "u",
                "time_segment_id": "t",
            }
        ]
        return build_runner_fetch_plan(
            securities,
            endpoints=(endpoint,),
            start_date="20260105",
            end_date="20260105",
            chunk_policy="full-range",
        )[0]

    def fast_limiter(self) -> AdaptiveRequestLimiter:
        return AdaptiveRequestLimiter(
            initial_requests_per_minute=600000,
            max_requests_per_minute=600000,
            min_requests_per_minute=100,
            sleeper=lambda _: None,
        )

    def test_dry_run_plan_reports_no_remote_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            report = run_provider_runner(
                client=None,
                output_dir=output_dir,
                security_universe=self.write_universe(root),
                start_date="20260105",
                end_date="20260105",
                dry_run_plan=True,
                chunk_policy="full-range",
            )

            self.assertFalse(report["remote_provider_called"])
            self.assertEqual(report["task_count"], 5)
            self.assertTrue((output_dir / "d2_t16_fetch_plan.jsonl").exists())
            self.assertFalse((output_dir / "d2_t15_tnskhdata_staging.duckdb").exists())

    def test_fake_client_run_writes_duckdb_and_reuses_quality_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            client = FakeTnskhdataClient()

            stdout = StringIO()
            with redirect_stdout(stdout):
                report = run_provider_runner(
                    client=client,
                    output_dir=output_dir,
                    security_universe=self.write_universe(root),
                    start_date="20260105",
                    end_date="20260105",
                    chunk_policy="full-range",
                    max_workers=4,
                    progress_every_tasks=1,
                    initial_requests_per_minute=600000,
                    max_requests_per_minute=600000,
                    sleeper=lambda _: None,
                )

            self.assertTrue(report["remote_provider_called"])
            self.assertEqual(report["executed_task_count"], 5)
            self.assertEqual(report["reference_task_count"], 5)
            self.assertEqual(report["blocking_fetch_status_count"], 0)
            db_path = output_dir / "d2_t15_tnskhdata_staging.duckdb"
            conn = duckdb.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute("SELECT count(*) FROM staging_daily_raw").fetchone()[
                        0
                    ],
                    1,
                )
                self.assertEqual(
                    conn.execute("SELECT count(*) FROM staging_stk_limit").fetchone()[
                        0
                    ],
                    1,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT count(*) FROM staging_fetch_ledger"
                    ).fetchone()[0],
                    10,
                )
                self.assertEqual(
                    conn.execute("SELECT count(*) FROM staging_stock_basic").fetchone()[
                        0
                    ],
                    1,
                )
            finally:
                conn.close()
            progress_path = output_dir / "d2_t16_progress_status.json"
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertTrue(progress_path.exists())
            self.assertFalse((output_dir / "d2_t16_progress_status.json.tmp").exists())
            self.assertEqual(progress["status"], "completed")
            self.assertEqual(progress["reference_task_count"], 5)
            self.assertEqual(progress["main_task_count"], 5)
            stdout_lines = [line for line in stdout.getvalue().splitlines() if line]
            self.assertTrue(stdout_lines)
            self.assertNotIn("TOKEN", stdout.getvalue())
            json.loads(stdout_lines[-1])
            self.assertIn(
                (
                    "trade_cal",
                    {
                        "exchange": "",
                        "start_date": "20260105",
                        "end_date": "20260105",
                    },
                ),
                client.calls,
            )
            stock_basic_calls = [
                params for endpoint, params in client.calls if endpoint == "stock_basic"
            ]
            self.assertEqual(
                [params["list_status"] for params in stock_basic_calls],
                ["L", "D", "P", "G"],
            )
            self.assertTrue(
                all("ts_code" not in params for params in stock_basic_calls)
            )

    def test_trade_cal_falls_back_when_exchange_param_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            client = TradeCalNoExchangeClient()

            run_provider_runner(
                client=client,
                output_dir=output_dir,
                security_universe=self.write_universe(root),
                start_date="20260105",
                end_date="20260105",
                chunk_policy="full-range",
                max_workers=1,
                progress_every_tasks=1,
                initial_requests_per_minute=600000,
                max_requests_per_minute=600000,
                sleeper=lambda _: None,
            )

            ledger_rows = [
                json.loads(line)
                for line in (output_dir / "d2_t16_fetch_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            trade_cal_entries = [
                row for row in ledger_rows if row["endpoint"] == "trade_cal"
            ]
            self.assertEqual(trade_cal_entries[0]["status"], "succeeded_after_fallback")
            self.assertEqual(
                trade_cal_entries[0]["param_variant"], "start_end_fallback"
            )

    def test_stk_limit_fallback_filters_unrelated_rows(self) -> None:
        result = fetch_task_with_retry(
            client=FakeTnskhdataClient(),
            task=self.task("stk_limit"),
            run_id="run",
            chunk_policy="full-range",
            limiter=self.fast_limiter(),
            full_mode=True,
            retry_max_attempts=3,
            retry_backoff_seconds=0,
            retry_jitter_ratio=0,
            rate_limit_sleep_seconds=0,
            sleeper=lambda _: None,
            worker_id="worker-0",
        )

        self.assertEqual(result.ledger.status, "succeeded_after_fallback")
        self.assertEqual(result.ledger.accepted_row_count, 1)
        self.assertEqual(result.ledger.filtered_out_row_count, 1)
        self.assertEqual(result.rows[0]["ts_code"], "000001.SZ")

    def test_suspend_d_normalizes_trade_date_to_suspend_date(self) -> None:
        result = fetch_task_with_retry(
            client=FakeTnskhdataClient(),
            task=self.task("suspend_d"),
            run_id="run",
            chunk_policy="full-range",
            limiter=self.fast_limiter(),
            full_mode=False,
            retry_max_attempts=3,
            retry_backoff_seconds=0,
            retry_jitter_ratio=0,
            rate_limit_sleep_seconds=0,
            sleeper=lambda _: None,
            worker_id="worker-0",
        )

        self.assertEqual(result.ledger.status, "succeeded")
        self.assertEqual(result.rows[0]["suspend_date"], "20260105")

    def test_data_validation_error_does_not_return_bad_rows(self) -> None:
        result = fetch_task_with_retry(
            client=BadDailyClient(),
            task=self.task("daily"),
            run_id="run",
            chunk_policy="full-range",
            limiter=self.fast_limiter(),
            full_mode=True,
            retry_max_attempts=3,
            retry_backoff_seconds=0,
            retry_jitter_ratio=0,
            rate_limit_sleep_seconds=0,
            sleeper=lambda _: None,
            worker_id="worker-0",
        )

        self.assertEqual(result.ledger.status, "data_validation_error")
        self.assertEqual(result.rows, [])
        self.assertIn("missing=open", result.ledger.error_message_redacted or "")

    def test_resume_and_retry_failed_only_use_task_hash_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_path = Path(tmpdir) / "d2_t16_fetch_ledger.jsonl"
            tasks = [self.task("daily"), self.task("adj_factor")]
            entries = [
                D2T16LedgerEntry(
                    run_id="old",
                    task_id=tasks[0].task_id,
                    task_hash=tasks[0].task_hash,
                    endpoint=tasks[0].endpoint,
                    ts_code=tasks[0].ts_code,
                    start_date=tasks[0].start_date,
                    end_date=tasks[0].end_date,
                    chunk_policy="full-range",
                    param_variant=tasks[0].param_variant,
                    status="succeeded",
                    attempt_count=1,
                    row_count=1,
                    accepted_row_count=1,
                    filtered_out_row_count=0,
                    error_category=None,
                    error_message_redacted=None,
                    started_at="2026-01-01T00:00:00Z",
                    completed_at="2026-01-01T00:00:01Z",
                    elapsed_seconds=1,
                    worker_id="worker-0",
                ),
                D2T16LedgerEntry(
                    run_id="old",
                    task_id=tasks[1].task_id,
                    task_hash=tasks[1].task_hash,
                    endpoint=tasks[1].endpoint,
                    ts_code=tasks[1].ts_code,
                    start_date=tasks[1].start_date,
                    end_date=tasks[1].end_date,
                    chunk_policy="full-range",
                    param_variant=tasks[1].param_variant,
                    status="timeout",
                    attempt_count=3,
                    row_count=0,
                    accepted_row_count=0,
                    filtered_out_row_count=0,
                    error_category="timeout",
                    error_message_redacted="TimeoutError",
                    started_at="2026-01-01T00:00:00Z",
                    completed_at="2026-01-01T00:00:01Z",
                    elapsed_seconds=1,
                    worker_id="worker-1",
                ),
            ]
            ledger_path.write_text(
                "".join(json.dumps(entry.__dict__) + "\n" for entry in entries),
                encoding="utf-8",
            )

            remaining, skipped = filter_tasks_for_runner_resume(
                tasks,
                ledger_path,
                resume=True,
                retry_failed_only=False,
            )
            retry_only, retry_skipped = filter_tasks_for_runner_resume(
                tasks,
                ledger_path,
                resume=False,
                retry_failed_only=True,
            )

            self.assertEqual([task.endpoint for task in remaining], ["adj_factor"])
            self.assertEqual(len(skipped), 1)
            self.assertEqual([task.endpoint for task in retry_only], ["adj_factor"])
            self.assertEqual(retry_skipped, [])

    def test_endpoint_task_write_is_idempotent_after_ledger_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            universe = self.write_universe(root)
            for _ in range(2):
                run_provider_runner(
                    client=FakeTnskhdataClient(),
                    output_dir=output_dir,
                    security_universe=universe,
                    start_date="20260105",
                    end_date="20260105",
                    endpoints=("daily",),
                    chunk_policy="full-range",
                    max_workers=1,
                    progress_every_tasks=1,
                    initial_requests_per_minute=600000,
                    max_requests_per_minute=600000,
                    sleeper=lambda _: None,
                )
                (output_dir / "d2_t16_fetch_ledger.jsonl").unlink(missing_ok=True)

            conn = duckdb.connect(str(output_dir / "d2_t15_tnskhdata_staging.duckdb"))
            try:
                self.assertEqual(
                    conn.execute("SELECT count(*) FROM staging_daily_raw").fetchone()[
                        0
                    ],
                    1,
                )
                self.assertEqual(
                    conn.execute(
                        """
                        SELECT count(*)
                        FROM (
                          SELECT ts_code, trade_date
                          FROM staging_daily_raw
                          GROUP BY 1, 2
                          HAVING count(*) > 1
                        )
                        """
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()

    def test_fresh_cleans_allowed_generated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            output_dir.mkdir()
            for name in (
                "d2_t15_tnskhdata_staging.duckdb",
                "d2_t16_fetch_ledger.jsonl",
                "d2_t15_duckdb_quality_report.json",
            ):
                (output_dir / name).write_text("old", encoding="utf-8")
            (output_dir / "keep.txt").write_text("keep", encoding="utf-8")

            report = run_provider_runner(
                client=None,
                output_dir=output_dir,
                security_universe=self.write_universe(root),
                start_date="20260105",
                end_date="20260105",
                dry_run_plan=True,
                fresh=True,
            )

            self.assertIn(
                "d2_t15_tnskhdata_staging.duckdb", report["fresh_removed_files"]
            )
            self.assertFalse((output_dir / "d2_t15_tnskhdata_staging.duckdb").exists())
            self.assertFalse((output_dir / "d2_t16_fetch_ledger.jsonl").exists())
            self.assertTrue((output_dir / "keep.txt").exists())

    def test_fresh_and_resume_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(D2T16ProviderRunnerError):
                run_provider_runner(
                    client=None,
                    output_dir=root / "out",
                    security_universe=self.write_universe(root),
                    dry_run_plan=True,
                    fresh=True,
                    resume=True,
                )

    def test_retry_failed_only_noop_skips_reference_and_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "out"
            output_dir.mkdir()
            universe = self.write_universe(root)
            task = self.task("daily")
            entry = D2T16LedgerEntry(
                run_id="old",
                task_id=task.task_id,
                task_hash=task.task_hash,
                endpoint=task.endpoint,
                ts_code=task.ts_code,
                start_date=task.start_date,
                end_date=task.end_date,
                chunk_policy="full-range",
                param_variant=task.param_variant,
                status="succeeded",
                attempt_count=1,
                row_count=1,
                accepted_row_count=1,
                filtered_out_row_count=0,
                error_category=None,
                error_message_redacted=None,
                started_at="2026-01-01T00:00:00Z",
                completed_at="2026-01-01T00:00:01Z",
                elapsed_seconds=1,
                worker_id="worker-0",
            )
            (output_dir / "d2_t16_fetch_ledger.jsonl").write_text(
                json.dumps(entry.__dict__) + "\n",
                encoding="utf-8",
            )
            client = FakeTnskhdataClient()

            report = run_provider_runner(
                client=client,
                output_dir=output_dir,
                security_universe=universe,
                start_date="20260105",
                end_date="20260105",
                endpoints=("daily",),
                chunk_policy="full-range",
                retry_failed_only=True,
            )

            self.assertTrue(report["retry_failed_only_noop"])
            self.assertEqual(client.calls, [])
            self.assertFalse((output_dir / "d2_t15_tnskhdata_staging.duckdb").exists())

    def test_task_doc_separates_smoke_and_full_output_dirs(self) -> None:
        doc = Path("docs/tasks/D2-T16_security_major_provider_runner.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("d2_t15_tnskhdata_security_major_candidate_smoke", doc)
        self.assertIn("d2_t15_tnskhdata_security_major_candidate", doc)
        self.assertIn("--fresh", doc)
        self.assertIn("--resume", doc)
        self.assertIn("D3 rows", doc)
        self.assertIn("PCVT", doc)
        self.assertIn("labels", doc)
        self.assertIn("backtest", doc)

    def test_adaptive_limiter_decreases_on_rate_limit_and_increases_on_healthy_window(
        self,
    ) -> None:
        now = 0.0

        def clock() -> float:
            return now

        limiter = AdaptiveRequestLimiter(
            initial_requests_per_minute=200,
            max_requests_per_minute=500,
            min_requests_per_minute=100,
            rate_increase_per_minute=100,
            rate_decrease_factor=0.5,
            window_seconds=60,
            clock=clock,
            sleeper=lambda _: None,
        )

        limiter.record_result("rate_limit")
        self.assertEqual(limiter.snapshot()["current_requests_per_minute"], 100)
        now = 61.0
        limiter.record_result(None)
        self.assertEqual(limiter.snapshot()["current_requests_per_minute"], 200)

    def test_readme_advances_to_d2_t16_and_keeps_d3_r0_blocked(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn("current_stage: D2", readme)
        self.assertIn("current_task: D2-T16", readme)
        self.assertIn("next_planned_task: D3-T07", readme)
        self.assertIn(
            "D2-T15` 按证券主轴的 DuckDB 候选物化骨架与质量门禁：completed via PR #47",
            readme,
        )
        self.assertIn(
            "D2-T16` 按证券主轴的 tnskhdata 远程拉取 runner："
            "in_progress via current PR",
            readme,
        )
        self.assertIn("D3-T07 remains blocked unless D2-T16 handoff", readme)
        self.assertIn("R0 remains blocked", readme)


if __name__ == "__main__":
    unittest.main()
