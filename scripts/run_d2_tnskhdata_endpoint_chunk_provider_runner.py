"""D2-T17 endpoint-aware tnskhdata provider runner.

This script reuses the D2-T16 provider runner primitives while changing only the
task planning layer and generated D2-T17 file names. It must not change D2-T16
defaults or D2-T16 output naming.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (  # noqa: E402
    DEFAULT_END_DATE,
    DEFAULT_SECURITY_UNIVERSE,
    DEFAULT_START_DATE,
    DuckDBStagingWriter,
    SecurityMajorFetchTask,
    _date_yyyymmdd,
    _task_hash,
    _utc_now,
    _write_json,
    ensure_allowed_output_dir,
    load_security_universe,
    make_date_chunks,
    run_quality_reports,
    write_hash_summary,
)
from scripts.run_d2_tnskhdata_security_major_provider_runner import (  # noqa: E402
    BLOCKING_LEDGER_STATUSES,
    ENDPOINTS,
    STOCK_BASIC_LIST_STATUSES,
    AdaptiveRequestLimiter,
    D2T16LedgerEntry,
    ProgressReporter,
    _prepare_reference_tables,
    _write_jsonl,
    _write_task_ledger,
    create_tnskhdata_client,
    fetch_task_with_retry,
    filter_tasks_for_runner_resume,
    summarize_provider_errors,
    write_reference_tables,
)

DEFAULT_OUTPUT_DIR = (
    ROOT / "data/generated/d2/d2_t17_tnskhdata_endpoint_chunk_candidate"
)
DEFAULT_ENDPOINT_CHUNK_POLICY = {
    "daily": "3year",
    "adj_factor": "5year",
    "stk_limit": "3year",
    "stock_st": "full-range",
    "suspend_d": "full-range",
}
CHUNK_POLICIES = ("month", "year", "2year", "3year", "5year", "full-range")
FRESH_RUN_PATTERNS = (
    "d2_t15_tnskhdata_staging.duckdb*",
    "d2_t15_*.csv",
    "d2_t15_*.json",
    "d2_t17_*.json",
    "d2_t17_*.jsonl",
)


class D2T17EndpointChunkRunnerError(ValueError):
    """Raised when D2-T17 endpoint-aware chunk runner gates fail."""


def parse_endpoint_chunk_policy(value: str | None) -> dict[str, str]:
    policy = dict(DEFAULT_ENDPOINT_CHUNK_POLICY)
    if not value:
        return policy
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise D2T17EndpointChunkRunnerError(
                f"invalid endpoint chunk policy item: {item}"
            )
        endpoint, chunk_policy = [part.strip() for part in item.split("=", 1)]
        if endpoint not in ENDPOINTS:
            raise D2T17EndpointChunkRunnerError(f"unsupported endpoint: {endpoint}")
        if chunk_policy not in CHUNK_POLICIES:
            raise D2T17EndpointChunkRunnerError(
                f"unsupported chunk policy for {endpoint}: {chunk_policy}"
            )
        policy[endpoint] = chunk_policy
    return policy


def serialize_endpoint_chunk_policy(policy: dict[str, str]) -> str:
    return ",".join(f"{endpoint}={policy[endpoint]}" for endpoint in ENDPOINTS)


def make_endpoint_date_chunks(
    start_date: str, end_date: str, chunk_policy: str
) -> list[tuple[str, str]]:
    if chunk_policy in {"month", "year", "full-range"}:
        return make_date_chunks(start_date, end_date, chunk_policy)
    years_per_chunk = {"2year": 2, "3year": 3, "5year": 5}[chunk_policy]
    start_date = _date_yyyymmdd(start_date)
    end_date = _date_yyyymmdd(end_date)
    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    chunks: list[tuple[str, str]] = []
    year = start_year
    while year <= end_year:
        chunk_end_year = min(end_year, year + years_per_chunk - 1)
        chunk_start = max(start_date, f"{year}0101")
        chunk_end = min(end_date, f"{chunk_end_year}1231")
        chunks.append((chunk_start, chunk_end))
        year = chunk_end_year + 1
    return chunks


def build_endpoint_aware_fetch_plan(
    securities: list[dict[str, str]],
    *,
    endpoints: tuple[str, ...] = ENDPOINTS,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    endpoint_chunk_policy: dict[str, str] | None = None,
) -> list[SecurityMajorFetchTask]:
    policy = dict(endpoint_chunk_policy or DEFAULT_ENDPOINT_CHUNK_POLICY)
    normalized_policy = serialize_endpoint_chunk_policy(policy)
    unsupported = sorted(set(endpoints) - set(ENDPOINTS))
    if unsupported:
        raise D2T17EndpointChunkRunnerError(f"unsupported endpoints: {unsupported}")
    tasks: list[SecurityMajorFetchTask] = []
    for security in securities:
        ts_code = security["ts_code"]
        for endpoint in endpoints:
            policy_name = policy[endpoint]
            for chunk_start, chunk_end in make_endpoint_date_chunks(
                start_date, end_date, policy_name
            ):
                param_variant = "ts_code_start_end"
                payload = {
                    "endpoint": endpoint,
                    "ts_code": ts_code,
                    "start_date": chunk_start,
                    "end_date": chunk_end,
                    "param_variant": param_variant,
                    "endpoint_chunk_policy": f"{endpoint}={policy_name}",
                    "endpoint_chunk_policy_config": normalized_policy,
                }
                digest = _task_hash(payload)
                tasks.append(
                    SecurityMajorFetchTask(
                        task_id=(
                            f"{endpoint}:{policy_name}:{ts_code}:"
                            f"{chunk_start}:{chunk_end}:{digest[:8]}"
                        ),
                        endpoint=endpoint,
                        ts_code=ts_code,
                        start_date=chunk_start,
                        end_date=chunk_end,
                        param_variant=param_variant,
                        task_hash=digest,
                    )
                )
    return tasks


def endpoint_task_counts(tasks: list[SecurityMajorFetchTask]) -> dict[str, int]:
    return {
        endpoint: sum(1 for task in tasks if task.endpoint == endpoint)
        for endpoint in ENDPOINTS
    }


def endpoint_chunk_counts(tasks: list[SecurityMajorFetchTask]) -> dict[str, int]:
    by_endpoint_security: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for task in tasks:
        key = (task.endpoint, task.ts_code)
        by_endpoint_security.setdefault(key, set()).add(
            (task.start_date, task.end_date)
        )
    return {
        endpoint: max(
            (
                len(chunks)
                for (task_endpoint, _), chunks in by_endpoint_security.items()
                if task_endpoint == endpoint
            ),
            default=0,
        )
        for endpoint in ENDPOINTS
    }


def clean_fresh_output_dir(output_dir: Path) -> list[str]:
    ensure_allowed_output_dir(output_dir)
    if not output_dir.exists():
        return []
    removed: list[str] = []
    for pattern in FRESH_RUN_PATTERNS:
        for path in output_dir.glob(pattern):
            if path.is_file():
                path.unlink()
                removed.append(path.name)
    return sorted(removed)


def _parse_endpoints(value: str) -> tuple[str, ...]:
    endpoints = tuple(part.strip() for part in value.split(",") if part.strip())
    if not endpoints:
        raise argparse.ArgumentTypeError("at least one endpoint is required")
    unsupported = sorted(set(endpoints) - set(ENDPOINTS))
    if unsupported:
        raise argparse.ArgumentTypeError(f"unsupported endpoints: {unsupported}")
    return endpoints


def _reference_task_count() -> int:
    return 1 + len(STOCK_BASIC_LIST_STATUSES)


def run_endpoint_chunk_provider_runner(
    *,
    client: Any | None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    security_universe: Path = DEFAULT_SECURITY_UNIVERSE,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    endpoints: tuple[str, ...] = ENDPOINTS,
    endpoint_chunk_policy: dict[str, str] | None = None,
    full: bool = False,
    sample_securities: int | None = None,
    resume: bool = False,
    retry_failed_only: bool = False,
    dry_run_plan: bool = False,
    no_remote_fetch: bool = False,
    max_workers: int = 4,
    progress_interval_seconds: float = 60.0,
    progress_every_tasks: int = 50,
    rate_limit_sleep_seconds: float = 1.0,
    retry_max_attempts: int = 3,
    retry_backoff_seconds: float = 5.0,
    retry_jitter_ratio: float = 0.2,
    initial_requests_per_minute: int = 200,
    max_requests_per_minute: int = 500,
    min_requests_per_minute: int = 100,
    rate_increase_per_minute: int = 100,
    rate_decrease_factor: float = 0.5,
    stop_after_tasks: int | None = None,
    fresh: bool = False,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if fresh and resume:
        raise D2T17EndpointChunkRunnerError(
            "--fresh and --resume cannot be used together"
        )
    if fresh and retry_failed_only:
        raise D2T17EndpointChunkRunnerError(
            "--fresh and --retry-failed-only cannot be used together"
        )
    policy = dict(endpoint_chunk_policy or DEFAULT_ENDPOINT_CHUNK_POLICY)
    ensure_allowed_output_dir(output_dir)
    fresh_removed_files = clean_fresh_output_dir(output_dir) if fresh else []
    output_dir.mkdir(parents=True, exist_ok=True)
    start_date = _date_yyyymmdd(start_date)
    end_date = _date_yyyymmdd(end_date)
    run_id = f"D2-T17-{_utc_now().replace(':', '').replace('-', '')}"
    universe = load_security_universe(security_universe, limit=sample_securities)
    tasks = build_endpoint_aware_fetch_plan(
        universe.securities,
        endpoints=endpoints,
        start_date=start_date,
        end_date=end_date,
        endpoint_chunk_policy=policy,
    )
    if stop_after_tasks is not None:
        tasks = tasks[:stop_after_tasks]

    fetch_plan_path = output_dir / "d2_t17_fetch_plan.jsonl"
    ledger_path = output_dir / "d2_t17_fetch_ledger.jsonl"
    progress_path = output_dir / "d2_t17_progress_status.json"
    db_path = output_dir / "d2_t15_tnskhdata_staging.duckdb"
    _write_jsonl(fetch_plan_path, (asdict(task) for task in tasks), append=False)

    limiter = AdaptiveRequestLimiter(
        initial_requests_per_minute=initial_requests_per_minute,
        max_requests_per_minute=max_requests_per_minute,
        min_requests_per_minute=min_requests_per_minute,
        rate_increase_per_minute=rate_increase_per_minute,
        rate_decrease_factor=rate_decrease_factor,
        sleeper=sleeper,
    )

    summary_base = {
        "run_id": run_id,
        "task_id": "D2-T17",
        "endpoint_task_counts": endpoint_task_counts(tasks),
        "endpoint_chunk_policy": {endpoint: policy[endpoint] for endpoint in ENDPOINTS},
        "endpoint_chunk_counts": endpoint_chunk_counts(tasks),
        "total_task_count": len(tasks),
        "configured_security_count": universe.metrics["configured_security_count"],
        "mapped_security_count": universe.metrics["mapped_security_count"],
        "unmapped_security_count": universe.metrics["unmapped_security_count"],
    }
    if dry_run_plan:
        report = {
            **summary_base,
            "remote_provider_called": False,
            "fresh": fresh,
            "fresh_removed_files": fresh_removed_files,
            "output_dir_is_d2_t17_isolated": True,
            "limiter": limiter.snapshot(),
        }
        _write_json(output_dir / "d2_t17_run_summary.json", report)
        write_hash_summary(output_dir)
        return report

    if no_remote_fetch:
        quality_result = run_quality_reports(output_dir, db_path)
        report = {
            **summary_base,
            "remote_provider_called": False,
            "quality": quality_result["quality"],
            "acceptance": quality_result["acceptance"],
        }
        _write_json(output_dir / "d2_t17_run_summary.json", report)
        write_hash_summary(output_dir)
        return report

    if client is None:
        raise D2T17EndpointChunkRunnerError(
            "client is required unless dry-run is enabled"
        )

    tasks_to_run, skipped_entries = filter_tasks_for_runner_resume(
        tasks,
        ledger_path,
        resume=resume,
        retry_failed_only=retry_failed_only,
    )
    if retry_failed_only and not tasks_to_run:
        report = {
            **summary_base,
            "remote_provider_called": False,
            "retry_failed_only_noop": True,
            "reference_fetch_skipped": True,
            "duckdb_staging_rewritten": False,
            "executed_task_count": 0,
        }
        _write_json(output_dir / "d2_t17_run_summary.json", report)
        return report

    max_workers = max(1, max_workers)
    writer = DuckDBStagingWriter(db_path)
    all_entries: list[D2T16LedgerEntry] = []
    reference_task_count = _reference_task_count()
    reporter = ProgressReporter(
        path=progress_path,
        run_id=run_id,
        total_task_count=reference_task_count + len(tasks_to_run),
        total_tasks_original=len(tasks),
        skipped_resume_count=len(skipped_entries),
        executed_task_count=len(tasks_to_run),
        reference_task_count=reference_task_count,
        main_task_count=len(tasks_to_run),
        progress_interval_seconds=progress_interval_seconds,
        progress_every_tasks=max(1, progress_every_tasks),
    )
    try:
        _prepare_reference_tables(writer)
        writer.write_security_universe(universe.securities)
        writer.write_security_mapping_diagnostics(universe.mapping_diagnostics)
        reference_counts = write_reference_tables(
            client=client,
            writer=writer,
            securities=universe.securities,
            start_date=start_date,
            end_date=end_date,
            limiter=limiter,
            run_id=run_id,
            ledger_path=ledger_path,
            reporter=reporter,
        )
        if skipped_entries:
            _write_jsonl(
                ledger_path,
                (asdict(entry) for entry in skipped_entries),
                append=True,
            )
            all_entries.extend(skipped_entries)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(
                    fetch_task_with_retry,
                    client=client,
                    task=task,
                    run_id=run_id,
                    chunk_policy=policy[task.endpoint],
                    limiter=limiter,
                    full_mode=full,
                    retry_max_attempts=retry_max_attempts,
                    retry_backoff_seconds=retry_backoff_seconds,
                    retry_jitter_ratio=retry_jitter_ratio,
                    rate_limit_sleep_seconds=rate_limit_sleep_seconds,
                    sleeper=sleeper,
                    worker_id=f"worker-{index % max_workers}",
                )
                for index, task in enumerate(tasks_to_run)
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                entry = result.ledger
                if result.rows:
                    writer.write_endpoint_task_rows(
                        result.task.endpoint, result.task, result.rows
                    )
                _write_task_ledger(writer, entry)
                _write_jsonl(ledger_path, [asdict(entry)], append=True)
                all_entries.append(entry)
                reporter.record(entry, limiter.snapshot())
    except KeyboardInterrupt:
        reporter.set_status("interrupted", limiter.snapshot())
        raise
    except Exception:
        reporter.set_status("failed", limiter.snapshot())
        raise
    finally:
        writer.close()

    quality_result = run_quality_reports(output_dir, db_path)
    provider_errors = summarize_provider_errors(all_entries)
    _write_json(output_dir / "d2_t17_provider_error_summary.json", provider_errors)
    acceptance = quality_result["acceptance"]
    handoff = quality_result["handoff"]
    blocking_fetch_status_count = sum(
        1 for entry in all_entries if entry.status in BLOCKING_LEDGER_STATUSES
    )
    if blocking_fetch_status_count:
        acceptance["d2_acceptance_decision"] = (
            "blocked_pending_provider_fetch_completion"
        )
        acceptance.setdefault("quality_blockers", []).append(
            "d2_t17_fetch_failure_count"
        )
        handoff["d3_handoff_decision"] = "d3_candidate_generation_blocked"
        _write_json(
            output_dir / "d2_t15_d2_acceptance_candidate_report.json", acceptance
        )
        _write_json(output_dir / "d2_t15_d3_handoff_candidate_report.json", handoff)
        write_hash_summary(output_dir)
    reporter.set_status(
        "completed_with_failures" if blocking_fetch_status_count else "completed",
        limiter.snapshot(),
    )
    report = {
        **summary_base,
        "remote_provider_called": True,
        "full": full,
        "executed_task_count": len(tasks_to_run),
        "reference_task_count": reference_task_count,
        "skipped_resume_count": len(skipped_entries),
        "fresh": fresh,
        "fresh_removed_files": fresh_removed_files,
        "reference_counts": reference_counts,
        "blocking_fetch_status_count": blocking_fetch_status_count,
        "quality": quality_result["quality"],
        "acceptance": acceptance,
        "handoff": handoff,
        "limiter": limiter.snapshot(),
    }
    _write_json(output_dir / "d2_t17_run_summary.json", report)
    write_hash_summary(output_dir)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--security-universe", default=DEFAULT_SECURITY_UNIVERSE, type=Path
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--sample-securities", type=int)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--max-workers", default=4, type=int)
    parser.add_argument(
        "--endpoint-chunk-policy",
        default=serialize_endpoint_chunk_policy(DEFAULT_ENDPOINT_CHUNK_POLICY),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed-only", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--no-remote-fetch", action="store_true")
    parser.add_argument("--progress-interval-seconds", default=60.0, type=float)
    parser.add_argument("--progress-every-tasks", default=50, type=int)
    parser.add_argument("--rate-limit-sleep-seconds", default=1.0, type=float)
    parser.add_argument("--retry-max-attempts", default=3, type=int)
    parser.add_argument("--retry-backoff-seconds", default=5.0, type=float)
    parser.add_argument("--retry-jitter-ratio", default=0.2, type=float)
    parser.add_argument("--stop-after-tasks", type=int)
    parser.add_argument(
        "--endpoints", default=",".join(ENDPOINTS), type=_parse_endpoints
    )
    parser.add_argument("--initial-requests-per-minute", default=200, type=int)
    parser.add_argument("--max-requests-per-minute", default=500, type=int)
    parser.add_argument("--min-requests-per-minute", default=100, type=int)
    parser.add_argument("--rate-increase-per-minute", default=100, type=int)
    parser.add_argument("--rate-decrease-factor", default=0.5, type=float)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    policy = parse_endpoint_chunk_policy(args.endpoint_chunk_policy)
    client = None
    if not args.dry_run_plan and not args.no_remote_fetch:
        client = create_tnskhdata_client(args.env_file)
    report = run_endpoint_chunk_provider_runner(
        client=client,
        output_dir=args.output_dir,
        security_universe=args.security_universe,
        start_date=args.start_date,
        end_date=args.end_date,
        endpoints=args.endpoints,
        endpoint_chunk_policy=policy,
        full=args.full,
        sample_securities=args.sample_securities,
        resume=args.resume,
        retry_failed_only=args.retry_failed_only,
        dry_run_plan=args.dry_run_plan,
        no_remote_fetch=args.no_remote_fetch,
        max_workers=args.max_workers,
        progress_interval_seconds=args.progress_interval_seconds,
        progress_every_tasks=args.progress_every_tasks,
        rate_limit_sleep_seconds=args.rate_limit_sleep_seconds,
        retry_max_attempts=args.retry_max_attempts,
        retry_backoff_seconds=args.retry_backoff_seconds,
        retry_jitter_ratio=args.retry_jitter_ratio,
        initial_requests_per_minute=args.initial_requests_per_minute,
        max_requests_per_minute=args.max_requests_per_minute,
        min_requests_per_minute=args.min_requests_per_minute,
        rate_increase_per_minute=args.rate_increase_per_minute,
        rate_decrease_factor=args.rate_decrease_factor,
        stop_after_tasks=args.stop_after_tasks,
        fresh=args.fresh,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
