"""D2-T16 security-major tnskhdata remote provider runner.

The runner fetches candidate D2 rows through an injected or configured tnskhdata
client, writes only ignored candidate DuckDB staging outputs, and then reuses the
D2-T15 quality gate. Tests use fake clients; CI must not call the remote provider.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
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
    FetchLedgerEntry,
    SecurityMajorFetchTask,
    _classify_error,
    _date_yyyymmdd,
    _frame_records,
    _redact_error,
    _task_hash,
    _utc_now,
    _write_json,
    ensure_allowed_output_dir,
    load_security_universe,
    make_date_chunks,
    run_quality_reports,
    write_hash_summary,
)

DEFAULT_OUTPUT_DIR = (
    ROOT / "data/generated/d2/d2_t15_tnskhdata_security_major_candidate"
)
ENDPOINTS = ("daily", "adj_factor", "stock_st", "suspend_d", "stk_limit")
STOCK_BASIC_LIST_STATUSES = ("L", "D", "P", "G")
COMPLETED_LEDGER_STATUSES = {
    "succeeded",
    "succeeded_after_fallback",
    "empty_resolved",
    "unsupported_param_variant",
}
RETRYABLE_LEDGER_STATUSES = {
    "rate_limit",
    "timeout",
    "provider_error",
    "failed",
    "data_validation_error",
}
BLOCKING_LEDGER_STATUSES = RETRYABLE_LEDGER_STATUSES
FRESH_RUN_PATTERNS = (
    "d2_t15_tnskhdata_staging.duckdb*",
    "d2_t15_*.csv",
    "d2_t15_*.json",
    "d2_t16_*.json",
    "d2_t16_*.jsonl",
)


class D2T16ProviderRunnerError(ValueError):
    """Raised when D2-T16 provider runner gates fail."""


class DataValidationError(ValueError):
    """Raised when provider rows cannot be safely staged."""


@dataclass(frozen=True)
class ProviderCallVariant:
    param_variant: str
    params: dict[str, str]


@dataclass(frozen=True)
class D2T16LedgerEntry:
    run_id: str
    task_id: str
    task_hash: str
    endpoint: str
    ts_code: str
    start_date: str
    end_date: str
    chunk_policy: str
    param_variant: str
    status: str
    attempt_count: int
    row_count: int
    accepted_row_count: int
    filtered_out_row_count: int
    error_category: str | None
    error_message_redacted: str | None
    started_at: str
    completed_at: str
    elapsed_seconds: float
    worker_id: str
    retry_after_seconds_optional: float | None = None


@dataclass(frozen=True)
class ProviderFetchResult:
    task: SecurityMajorFetchTask
    rows: list[dict[str, Any]]
    ledger: D2T16LedgerEntry


@dataclass
class ProgressState:
    run_id: str
    total_task_count: int
    total_tasks_original: int
    skipped_resume_count: int
    executed_task_count: int
    reference_task_count: int
    main_task_count: int
    status: str = "running"
    completed_task_count: int = 0
    succeeded_task_count: int = 0
    failed_task_count: int = 0
    accepted_row_count: int = 0
    filtered_out_row_count: int = 0
    last_task_id: str | None = None
    last_error_category: str | None = None


class AdaptiveRequestLimiter:
    """Thread-safe adaptive request-per-minute limiter shared by all workers."""

    def __init__(
        self,
        *,
        initial_requests_per_minute: int = 200,
        max_requests_per_minute: int = 500,
        min_requests_per_minute: int = 100,
        rate_increase_per_minute: int = 100,
        rate_decrease_factor: float = 0.5,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_requests_per_minute <= 0:
            raise D2T16ProviderRunnerError("min requests per minute must be positive")
        if max_requests_per_minute < min_requests_per_minute:
            raise D2T16ProviderRunnerError(
                "max requests per minute must be greater than or equal to min"
            )
        initial = max(
            min_requests_per_minute,
            min(initial_requests_per_minute, max_requests_per_minute),
        )
        self._current_requests_per_minute = initial
        self._max_requests_per_minute = max_requests_per_minute
        self._min_requests_per_minute = min_requests_per_minute
        self._rate_increase_per_minute = rate_increase_per_minute
        self._rate_decrease_factor = rate_decrease_factor
        self._window_seconds = window_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._next_allowed_at = clock()
        self._window_started_at = clock()
        self._window_failure_count = 0

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                wait_seconds = max(0.0, self._next_allowed_at - now)
                if wait_seconds == 0:
                    interval = 60.0 / float(self._current_requests_per_minute)
                    self._next_allowed_at = now + interval
                    return
            self._sleeper(min(wait_seconds, 1.0))

    def record_result(self, error_category: str | None) -> None:
        with self._lock:
            now = self._clock()
            if error_category in {"rate_limit", "timeout", "provider_error"}:
                decreased = int(
                    self._current_requests_per_minute * self._rate_decrease_factor
                )
                self._current_requests_per_minute = max(
                    self._min_requests_per_minute, decreased
                )
                self._window_started_at = now
                self._window_failure_count = 0
                return
            if error_category:
                return
            if now - self._window_started_at >= self._window_seconds:
                if self._window_failure_count == 0:
                    self._current_requests_per_minute = min(
                        self._max_requests_per_minute,
                        self._current_requests_per_minute
                        + self._rate_increase_per_minute,
                    )
                self._window_started_at = now
                self._window_failure_count = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "current_requests_per_minute": self._current_requests_per_minute,
                "max_requests_per_minute": self._max_requests_per_minute,
                "min_requests_per_minute": self._min_requests_per_minute,
                "rate_increase_per_minute": self._rate_increase_per_minute,
                "rate_decrease_factor": self._rate_decrease_factor,
            }


class ProgressReporter:
    def __init__(
        self,
        *,
        path: Path,
        run_id: str,
        total_task_count: int,
        total_tasks_original: int,
        skipped_resume_count: int,
        executed_task_count: int,
        reference_task_count: int,
        main_task_count: int,
        progress_interval_seconds: float,
        progress_every_tasks: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = path
        self.state = ProgressState(
            run_id=run_id,
            total_task_count=total_task_count,
            total_tasks_original=total_tasks_original,
            skipped_resume_count=skipped_resume_count,
            executed_task_count=executed_task_count,
            reference_task_count=reference_task_count,
            main_task_count=main_task_count,
        )
        self.progress_interval_seconds = progress_interval_seconds
        self.progress_every_tasks = progress_every_tasks
        self.clock = clock
        self._last_write_at = clock()

    def record(
        self, ledger: D2T16LedgerEntry, limiter_snapshot: dict[str, Any]
    ) -> None:
        self.state.completed_task_count += 1
        if ledger.status in COMPLETED_LEDGER_STATUSES:
            self.state.succeeded_task_count += 1
        else:
            self.state.failed_task_count += 1
        self.state.accepted_row_count += ledger.accepted_row_count
        self.state.filtered_out_row_count += ledger.filtered_out_row_count
        self.state.last_task_id = ledger.task_id
        self.state.last_error_category = ledger.error_category
        should_write = (
            self.state.completed_task_count == self.state.total_task_count
            or self.state.completed_task_count % self.progress_every_tasks == 0
            or self.clock() - self._last_write_at >= self.progress_interval_seconds
        )
        if should_write:
            self.write(limiter_snapshot)

    def set_status(self, status: str, limiter_snapshot: dict[str, Any]) -> None:
        self.state.status = status
        self.write(limiter_snapshot)

    def write(self, limiter_snapshot: dict[str, Any]) -> None:
        payload = {
            **asdict(self.state),
            "updated_at": _utc_now(),
            "limiter": limiter_snapshot,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)
        self._last_write_at = self.clock()
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]], *, append: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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


def build_runner_fetch_plan(
    securities: list[dict[str, str]],
    *,
    endpoints: tuple[str, ...] = ENDPOINTS,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    chunk_policy: str = "year",
) -> list[SecurityMajorFetchTask]:
    unsupported = sorted(set(endpoints) - set(ENDPOINTS))
    if unsupported:
        raise D2T16ProviderRunnerError(f"unsupported endpoints: {unsupported}")
    tasks: list[SecurityMajorFetchTask] = []
    for security in securities:
        ts_code = security["ts_code"]
        for endpoint in endpoints:
            for chunk_start, chunk_end in make_date_chunks(
                start_date, end_date, chunk_policy
            ):
                payload = {
                    "endpoint": endpoint,
                    "ts_code": ts_code,
                    "start_date": chunk_start,
                    "end_date": chunk_end,
                    "param_variant": "ts_code_start_end",
                }
                digest = _task_hash(payload)
                tasks.append(
                    SecurityMajorFetchTask(
                        task_id=(
                            f"{endpoint}:{ts_code}:{chunk_start}:"
                            f"{chunk_end}:{digest[:8]}"
                        ),
                        endpoint=endpoint,
                        ts_code=ts_code,
                        start_date=chunk_start,
                        end_date=chunk_end,
                        param_variant="ts_code_start_end",
                        task_hash=digest,
                    )
                )
    return tasks


def load_runner_ledger(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for entry in _read_jsonl(path):
        task_id = str(entry.get("task_id", ""))
        if task_id:
            latest[task_id] = entry
    return latest


def filter_tasks_for_runner_resume(
    tasks: list[SecurityMajorFetchTask],
    ledger_path: Path,
    *,
    resume: bool,
    retry_failed_only: bool,
) -> tuple[list[SecurityMajorFetchTask], list[D2T16LedgerEntry]]:
    latest = load_runner_ledger(ledger_path)
    skipped: list[D2T16LedgerEntry] = []
    if retry_failed_only:
        return [
            task
            for task in tasks
            if latest.get(task.task_id, {}).get("task_hash") == task.task_hash
            and latest.get(task.task_id, {}).get("status") in RETRYABLE_LEDGER_STATUSES
        ], skipped
    if not resume:
        return tasks, skipped
    remaining: list[SecurityMajorFetchTask] = []
    for task in tasks:
        entry = latest.get(task.task_id, {})
        if (
            entry.get("task_hash") == task.task_hash
            and entry.get("status") in COMPLETED_LEDGER_STATUSES
        ):
            skipped.append(
                _ledger_entry(
                    run_id="resume-skip",
                    task=task,
                    chunk_policy="unknown",
                    param_variant=task.param_variant,
                    status="skipped_resume",
                    attempt_count=0,
                    row_count=0,
                    accepted_row_count=0,
                    filtered_out_row_count=0,
                    error_category=None,
                    error_message_redacted=None,
                    started_at=_utc_now(),
                    elapsed_seconds=0.0,
                    worker_id="main",
                )
            )
            continue
        remaining.append(task)
    return remaining, skipped


def provider_call_variants(
    task: SecurityMajorFetchTask, *, full_mode: bool
) -> list[ProviderCallVariant]:
    range_variant = ProviderCallVariant(
        param_variant="ts_code_start_end",
        params={
            "ts_code": task.ts_code,
            "start_date": task.start_date,
            "end_date": task.end_date,
        },
    )
    if task.endpoint == "daily":
        variants = [range_variant]
        if not full_mode:
            variants.append(
                ProviderCallVariant(
                    param_variant="ts_code_trade_date_smoke_fallback",
                    params={"ts_code": task.ts_code, "trade_date": task.start_date},
                )
            )
        return variants
    if task.endpoint == "adj_factor":
        return [range_variant]
    if task.endpoint == "stock_st":
        return [
            range_variant,
            ProviderCallVariant(
                param_variant="date_range_fallback_filtered_to_ts_code",
                params={
                    "start_date": task.start_date,
                    "end_date": task.end_date,
                },
            ),
        ]
    if task.endpoint == "suspend_d":
        variants = [range_variant]
        if not full_mode:
            variants.extend(
                [
                    ProviderCallVariant(
                        param_variant="ts_code_suspend_date_smoke_fallback",
                        params={
                            "ts_code": task.ts_code,
                            "suspend_date": task.start_date,
                        },
                    ),
                    ProviderCallVariant(
                        param_variant="ts_code_trade_date_smoke_fallback",
                        params={
                            "ts_code": task.ts_code,
                            "trade_date": task.start_date,
                        },
                    ),
                ]
            )
        return variants
    if task.endpoint == "stk_limit":
        return [
            range_variant,
            ProviderCallVariant(
                param_variant="date_range_fallback_filtered_to_ts_code",
                params={"start_date": task.start_date, "end_date": task.end_date},
            ),
        ]
    raise D2T16ProviderRunnerError(f"unsupported endpoint: {task.endpoint}")


def _date_field(endpoint: str, row: dict[str, Any]) -> str:
    if endpoint == "suspend_d":
        return _date_yyyymmdd(row.get("suspend_date") or row.get("trade_date"))
    return _date_yyyymmdd(row.get("trade_date") or row.get("ann_date"))


def _required_fields(endpoint: str) -> tuple[str, ...]:
    fields = {
        "daily": ("ts_code", "trade_date", "open", "high", "low", "close"),
        "adj_factor": ("ts_code", "trade_date", "adj_factor"),
        "stock_st": ("ts_code",),
        "suspend_d": ("ts_code", "suspend_type"),
        "stk_limit": ("ts_code", "trade_date", "up_limit", "down_limit"),
    }
    return fields[endpoint]


def _normalize_row(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    if endpoint == "suspend_d":
        normalized["suspend_date"] = _date_yyyymmdd(
            normalized.get("suspend_date") or normalized.get("trade_date")
        )
    if endpoint == "stock_st":
        normalized["trade_date"] = _date_yyyymmdd(
            normalized.get("trade_date") or normalized.get("ann_date")
        )
        normalized["st_status"] = str(
            normalized.get("st_status") or normalized.get("name_type") or ""
        )
    return normalized


def validate_and_filter_rows(
    endpoint: str, rows: list[dict[str, Any]], task: SecurityMajorFetchTask
) -> tuple[list[dict[str, Any]], int]:
    accepted: list[dict[str, Any]] = []
    filtered_out = 0
    missing_errors: list[str] = []
    for row in rows:
        normalized = _normalize_row(endpoint, row)
        row_ts_code = str(normalized.get("ts_code") or "")
        row_date = _date_field(endpoint, normalized)
        if (
            row_ts_code != task.ts_code
            or not row_date
            or row_date < task.start_date
            or row_date > task.end_date
        ):
            filtered_out += 1
            continue
        missing = [
            field
            for field in _required_fields(endpoint)
            if normalized.get(field) in (None, "")
        ]
        if endpoint == "suspend_d" and not normalized.get("suspend_date"):
            missing.append("suspend_date_or_trade_date")
        if endpoint == "stock_st" and not normalized.get("trade_date"):
            missing.append("trade_date_or_ann_date")
        if missing:
            missing_errors.append(
                f"{endpoint}:{task.ts_code}:{row_date}:missing={','.join(missing)}"
            )
            continue
        accepted.append(normalized)
    if missing_errors:
        raise DataValidationError("; ".join(missing_errors[:5]))
    return accepted, filtered_out


def _ledger_entry(
    *,
    run_id: str,
    task: SecurityMajorFetchTask,
    chunk_policy: str,
    param_variant: str,
    status: str,
    attempt_count: int,
    row_count: int,
    accepted_row_count: int,
    filtered_out_row_count: int,
    error_category: str | None,
    error_message_redacted: str | None,
    started_at: str,
    elapsed_seconds: float,
    worker_id: str,
    retry_after_seconds_optional: float | None = None,
) -> D2T16LedgerEntry:
    return D2T16LedgerEntry(
        run_id=run_id,
        task_id=task.task_id,
        task_hash=task.task_hash,
        endpoint=task.endpoint,
        ts_code=task.ts_code,
        start_date=task.start_date,
        end_date=task.end_date,
        chunk_policy=chunk_policy,
        param_variant=param_variant,
        status=status,
        attempt_count=attempt_count,
        row_count=row_count,
        accepted_row_count=accepted_row_count,
        filtered_out_row_count=filtered_out_row_count,
        error_category=error_category,
        error_message_redacted=error_message_redacted,
        started_at=started_at,
        completed_at=_utc_now(),
        elapsed_seconds=round(elapsed_seconds, 3),
        worker_id=worker_id,
        retry_after_seconds_optional=retry_after_seconds_optional,
    )


def _to_d2_t15_ledger(entry: D2T16LedgerEntry) -> FetchLedgerEntry:
    return FetchLedgerEntry(
        task_id=entry.task_id,
        endpoint=entry.endpoint,
        ts_code=entry.ts_code,
        start_date=entry.start_date,
        end_date=entry.end_date,
        param_variant=entry.param_variant,
        task_hash=entry.task_hash,
        status=entry.status,
        attempt_count=entry.attempt_count,
        row_count=entry.row_count,
        accepted_row_count=entry.accepted_row_count,
        error_category=entry.error_category,
        error_message_redacted=entry.error_message_redacted,
        started_at=entry.started_at,
        completed_at=entry.completed_at,
        elapsed_seconds=entry.elapsed_seconds,
    )


def _reference_task(
    *, endpoint: str, start_date: str, end_date: str, param_variant: str
) -> SecurityMajorFetchTask:
    payload = {
        "endpoint": endpoint,
        "ts_code": "__reference__",
        "start_date": start_date,
        "end_date": end_date,
        "param_variant": param_variant,
    }
    digest = _task_hash(payload)
    return SecurityMajorFetchTask(
        task_id=f"reference:{endpoint}:{param_variant}:{digest[:8]}",
        endpoint=endpoint,
        ts_code="__reference__",
        start_date=start_date,
        end_date=end_date,
        param_variant=param_variant,
        task_hash=digest,
    )


def _write_task_ledger(writer: DuckDBStagingWriter, entry: D2T16LedgerEntry) -> None:
    writer.conn.execute(
        "DELETE FROM staging_fetch_ledger WHERE task_id = ? AND task_hash = ?",
        [entry.task_id, entry.task_hash],
    )
    writer.write_ledger([_to_d2_t15_ledger(entry)])


def fetch_task_with_retry(
    *,
    client: Any,
    task: SecurityMajorFetchTask,
    run_id: str,
    chunk_policy: str,
    limiter: AdaptiveRequestLimiter,
    full_mode: bool,
    retry_max_attempts: int,
    retry_backoff_seconds: float,
    retry_jitter_ratio: float,
    rate_limit_sleep_seconds: float,
    sleeper: Callable[[float], None] = time.sleep,
    worker_id: str = "worker",
) -> ProviderFetchResult:
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    method = getattr(client, task.endpoint)
    attempt_count = 0
    unsupported_seen = False
    variants = provider_call_variants(task, full_mode=full_mode)
    last_error: Exception | None = None
    last_category: str | None = None
    last_variant = task.param_variant

    for variant_index, variant in enumerate(variants):
        variant_attempt = 0
        while variant_attempt < retry_max_attempts:
            variant_attempt += 1
            attempt_count += 1
            last_variant = variant.param_variant
            limiter.acquire()
            try:
                payload = method(**variant.params)
                rows = _frame_records(payload)
                accepted, filtered_out = validate_and_filter_rows(
                    task.endpoint, rows, task
                )
                status = "succeeded" if accepted else "empty_resolved"
                if unsupported_seen and accepted:
                    status = "succeeded_after_fallback"
                limiter.record_result(None)
                return ProviderFetchResult(
                    task=task,
                    rows=accepted,
                    ledger=_ledger_entry(
                        run_id=run_id,
                        task=task,
                        chunk_policy=chunk_policy,
                        param_variant=variant.param_variant,
                        status=status,
                        attempt_count=attempt_count,
                        row_count=len(rows),
                        accepted_row_count=len(accepted),
                        filtered_out_row_count=filtered_out,
                        error_category=None,
                        error_message_redacted=None,
                        started_at=started_at,
                        elapsed_seconds=time.monotonic() - started_monotonic,
                        worker_id=worker_id,
                    ),
                )
            except DataValidationError as exc:
                last_error = exc
                last_category = "data_validation_error"
                limiter.record_result(last_category)
                return ProviderFetchResult(
                    task=task,
                    rows=[],
                    ledger=_ledger_entry(
                        run_id=run_id,
                        task=task,
                        chunk_policy=chunk_policy,
                        param_variant=variant.param_variant,
                        status="data_validation_error",
                        attempt_count=attempt_count,
                        row_count=0,
                        accepted_row_count=0,
                        filtered_out_row_count=0,
                        error_category=last_category,
                        error_message_redacted=_redact_error(exc),
                        started_at=started_at,
                        elapsed_seconds=time.monotonic() - started_monotonic,
                        worker_id=worker_id,
                    ),
                )
            except Exception as exc:  # pragma: no cover - exercised by tests by type
                last_error = exc
                last_category = _classify_error(exc)
                limiter.record_result(last_category)
                if (
                    last_category == "unsupported_param_variant"
                    and variant_index + 1 < len(variants)
                ):
                    unsupported_seen = True
                    break
                if (
                    last_category in {"rate_limit", "timeout", "provider_error"}
                    and variant_attempt < retry_max_attempts
                ):
                    retry_after = max(
                        rate_limit_sleep_seconds,
                        retry_backoff_seconds * (2 ** (variant_attempt - 1)),
                    )
                    jitter = retry_after * retry_jitter_ratio
                    sleeper(retry_after + random.uniform(0, jitter))
                    continue
                return ProviderFetchResult(
                    task=task,
                    rows=[],
                    ledger=_ledger_entry(
                        run_id=run_id,
                        task=task,
                        chunk_policy=chunk_policy,
                        param_variant=variant.param_variant,
                        status=last_category or "failed",
                        attempt_count=attempt_count,
                        row_count=0,
                        accepted_row_count=0,
                        filtered_out_row_count=0,
                        error_category=last_category or "failed",
                        error_message_redacted=_redact_error(exc),
                        started_at=started_at,
                        elapsed_seconds=time.monotonic() - started_monotonic,
                        worker_id=worker_id,
                        retry_after_seconds_optional=retry_after
                        if "retry_after" in locals()
                        else None,
                    ),
                )

    return ProviderFetchResult(
        task=task,
        rows=[],
        ledger=_ledger_entry(
            run_id=run_id,
            task=task,
            chunk_policy=chunk_policy,
            param_variant=last_variant,
            status=last_category or "failed",
            attempt_count=attempt_count,
            row_count=0,
            accepted_row_count=0,
            filtered_out_row_count=0,
            error_category=last_category or "failed",
            error_message_redacted=_redact_error(last_error) if last_error else None,
            started_at=started_at,
            elapsed_seconds=time.monotonic() - started_monotonic,
            worker_id=worker_id,
        ),
    )


def fetch_reference_with_ledger(
    *,
    client: Any,
    task: SecurityMajorFetchTask,
    run_id: str,
    variants: list[ProviderCallVariant],
    limiter: AdaptiveRequestLimiter,
    worker_id: str = "reference",
) -> tuple[list[dict[str, Any]], D2T16LedgerEntry]:
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    method = getattr(client, task.endpoint)
    attempt_count = 0
    unsupported_seen = False
    last_error: Exception | None = None
    last_category: str | None = None
    last_variant = variants[0].param_variant
    for variant_index, variant in enumerate(variants):
        attempt_count += 1
        last_variant = variant.param_variant
        limiter.acquire()
        try:
            rows = _frame_records(method(**variant.params))
            status = "succeeded" if rows else "empty_resolved"
            if unsupported_seen and rows:
                status = "succeeded_after_fallback"
            limiter.record_result(None)
            return rows, _ledger_entry(
                run_id=run_id,
                task=task,
                chunk_policy="reference",
                param_variant=variant.param_variant,
                status=status,
                attempt_count=attempt_count,
                row_count=len(rows),
                accepted_row_count=len(rows),
                filtered_out_row_count=0,
                error_category=None,
                error_message_redacted=None,
                started_at=started_at,
                elapsed_seconds=time.monotonic() - started_monotonic,
                worker_id=worker_id,
            )
        except Exception as exc:
            last_error = exc
            last_category = _classify_error(exc)
            limiter.record_result(last_category)
            if last_category == "unsupported_param_variant" and variant_index + 1 < len(
                variants
            ):
                unsupported_seen = True
                continue
            break
    return [], _ledger_entry(
        run_id=run_id,
        task=task,
        chunk_policy="reference",
        param_variant=last_variant,
        status=last_category or "failed",
        attempt_count=attempt_count,
        row_count=0,
        accepted_row_count=0,
        filtered_out_row_count=0,
        error_category=last_category or "failed",
        error_message_redacted=_redact_error(last_error) if last_error else None,
        started_at=started_at,
        elapsed_seconds=time.monotonic() - started_monotonic,
        worker_id=worker_id,
    )


def _write_reference_ledger(
    *,
    entry: D2T16LedgerEntry,
    writer: DuckDBStagingWriter,
    ledger_path: Path,
    reporter: ProgressReporter,
    limiter: AdaptiveRequestLimiter,
) -> None:
    _write_task_ledger(writer, entry)
    _write_jsonl(ledger_path, [asdict(entry)], append=True)
    reporter.record(entry, limiter.snapshot())


def _prepare_reference_tables(writer: DuckDBStagingWriter) -> None:
    for table in (
        "staging_security_universe",
        "staging_security_mapping_diagnostics",
        "staging_trade_calendar",
        "staging_stock_basic",
    ):
        writer.conn.execute(f"DELETE FROM {table}")


def _filter_stock_basic_rows(
    rows: list[dict[str, Any]], securities: list[dict[str, str]]
) -> list[dict[str, Any]]:
    universe_ts_codes = {security["ts_code"] for security in securities}
    filtered: dict[str, dict[str, Any]] = {}
    for row in rows:
        ts_code = str(row.get("ts_code") or "")
        if ts_code in universe_ts_codes and ts_code not in filtered:
            filtered[ts_code] = row
    return list(filtered.values())


def write_reference_tables(
    *,
    client: Any,
    writer: DuckDBStagingWriter,
    securities: list[dict[str, str]],
    start_date: str,
    end_date: str,
    limiter: AdaptiveRequestLimiter,
    run_id: str,
    ledger_path: Path,
    reporter: ProgressReporter,
) -> dict[str, int]:
    trade_cal_task = _reference_task(
        endpoint="trade_cal",
        start_date=start_date,
        end_date=end_date,
        param_variant="exchange_start_end",
    )
    trade_calendar_rows, trade_cal_ledger = fetch_reference_with_ledger(
        client=client,
        task=trade_cal_task,
        run_id=run_id,
        variants=[
            ProviderCallVariant(
                param_variant="exchange_start_end",
                params={
                    "exchange": "",
                    "start_date": start_date,
                    "end_date": end_date,
                },
            ),
            ProviderCallVariant(
                param_variant="start_end_fallback",
                params={"start_date": start_date, "end_date": end_date},
            ),
        ],
        limiter=limiter,
    )
    _write_reference_ledger(
        entry=trade_cal_ledger,
        writer=writer,
        ledger_path=ledger_path,
        reporter=reporter,
        limiter=limiter,
    )
    if trade_calendar_rows:
        writer.write_trade_calendar(trade_calendar_rows)
    else:
        raise D2T16ProviderRunnerError(
            "trade_cal returned no rows; refusing empty D2 quality date domain"
        )

    stock_basic_rows: list[dict[str, Any]] = []
    for list_status in STOCK_BASIC_LIST_STATUSES:
        task = _reference_task(
            endpoint="stock_basic",
            start_date=start_date,
            end_date=end_date,
            param_variant=f"exchange_list_status_{list_status}",
        )
        rows, ledger = fetch_reference_with_ledger(
            client=client,
            task=task,
            run_id=run_id,
            variants=[
                ProviderCallVariant(
                    param_variant=f"exchange_list_status_{list_status}",
                    params={"exchange": "", "list_status": list_status},
                )
            ],
            limiter=limiter,
        )
        _write_reference_ledger(
            entry=ledger,
            writer=writer,
            ledger_path=ledger_path,
            reporter=reporter,
            limiter=limiter,
        )
        if ledger.status not in COMPLETED_LEDGER_STATUSES:
            raise D2T16ProviderRunnerError(
                f"stock_basic reference fetch failed for list_status={list_status}"
            )
        stock_basic_rows.extend(rows)
    stock_basic_rows = _filter_stock_basic_rows(stock_basic_rows, securities)
    if stock_basic_rows:
        writer.write_stock_basic(stock_basic_rows)
    else:
        raise D2T16ProviderRunnerError(
            "stock_basic returned no rows; refusing unverified listed-open domain"
        )
    return {
        "trade_calendar_row_count": len(trade_calendar_rows),
        "stock_basic_row_count": len(stock_basic_rows),
    }


def _load_env_file(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def create_tnskhdata_client(env_file: Path | None) -> Any:
    _load_env_file(env_file)
    token = os.environ.get("TNSKHDATA_TOKEN") or os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise D2T16ProviderRunnerError("TNSKHDATA_TOKEN or TUSHARE_TOKEN is required")
    module = __import__("tnskhdata")
    if hasattr(module, "pro_api"):
        return module.pro_api(token)
    if hasattr(module, "Client"):
        return module.Client(token)
    raise D2T16ProviderRunnerError("tnskhdata client factory not found")


def run_provider_runner(
    *,
    client: Any | None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    security_universe: Path = DEFAULT_SECURITY_UNIVERSE,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    endpoints: tuple[str, ...] = ENDPOINTS,
    full: bool = False,
    sample_securities: int | None = None,
    chunk_policy: str = "year",
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
        raise D2T16ProviderRunnerError("--fresh and --resume cannot be used together")
    if fresh and retry_failed_only:
        raise D2T16ProviderRunnerError(
            "--fresh and --retry-failed-only cannot be used together"
        )
    ensure_allowed_output_dir(output_dir)
    fresh_removed_files = clean_fresh_output_dir(output_dir) if fresh else []
    output_dir.mkdir(parents=True, exist_ok=True)
    start_date = _date_yyyymmdd(start_date)
    end_date = _date_yyyymmdd(end_date)
    run_id = f"D2-T16-{_utc_now().replace(':', '').replace('-', '')}"
    universe = load_security_universe(security_universe, limit=sample_securities)
    tasks = build_runner_fetch_plan(
        universe.securities,
        endpoints=endpoints,
        start_date=start_date,
        end_date=end_date,
        chunk_policy=chunk_policy,
    )
    if stop_after_tasks is not None:
        tasks = tasks[:stop_after_tasks]

    fetch_plan_path = output_dir / "d2_t16_fetch_plan.jsonl"
    ledger_path = output_dir / "d2_t16_fetch_ledger.jsonl"
    progress_path = output_dir / "d2_t16_progress_status.json"
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

    if dry_run_plan:
        report = {
            "run_id": run_id,
            "task_id": "D2-T16",
            "task_count": len(tasks),
            "remote_provider_called": False,
            "configured_security_count": universe.metrics["configured_security_count"],
            "mapped_security_count": universe.metrics["mapped_security_count"],
            "unmapped_security_count": universe.metrics["unmapped_security_count"],
            "endpoints": list(endpoints),
            "fresh": fresh,
            "fresh_removed_files": fresh_removed_files,
            "limiter": limiter.snapshot(),
        }
        _write_json(output_dir / "d2_t16_run_summary.json", report)
        write_hash_summary(output_dir)
        return report

    if no_remote_fetch:
        quality_result = run_quality_reports(output_dir, db_path)
        report = {
            "run_id": run_id,
            "task_id": "D2-T16",
            "remote_provider_called": False,
            "quality": quality_result["quality"],
            "acceptance": quality_result["acceptance"],
        }
        _write_json(output_dir / "d2_t16_run_summary.json", report)
        write_hash_summary(output_dir)
        return report

    if client is None:
        raise D2T16ProviderRunnerError("client is required unless dry-run is enabled")

    tasks_to_run, skipped_entries = filter_tasks_for_runner_resume(
        tasks,
        ledger_path,
        resume=resume,
        retry_failed_only=retry_failed_only,
    )
    if retry_failed_only and not tasks_to_run:
        report = {
            "run_id": run_id,
            "task_id": "D2-T16",
            "remote_provider_called": False,
            "retry_failed_only_noop": True,
            "reference_fetch_skipped": True,
            "duckdb_staging_rewritten": False,
            "task_count": len(tasks),
            "executed_task_count": 0,
            "configured_security_count": universe.metrics["configured_security_count"],
            "mapped_security_count": universe.metrics["mapped_security_count"],
            "unmapped_security_count": universe.metrics["unmapped_security_count"],
        }
        _write_json(output_dir / "d2_t16_run_summary.json", report)
        return report

    max_workers = max(1, max_workers)
    writer = DuckDBStagingWriter(db_path)
    all_entries: list[D2T16LedgerEntry] = []
    reference_task_count = 1 + len(STOCK_BASIC_LIST_STATUSES)
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
                    chunk_policy=chunk_policy,
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
    _write_json(output_dir / "d2_t16_provider_error_summary.json", provider_errors)
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
            "d2_t16_fetch_failure_count"
        )
        handoff["d3_handoff_decision"] = "d3_candidate_generation_blocked"
        _write_json(
            output_dir / "d2_t15_d2_acceptance_candidate_report.json", acceptance
        )
        _write_json(output_dir / "d2_t15_d3_handoff_candidate_report.json", handoff)
        write_hash_summary(output_dir)
    final_progress_status = (
        "completed_with_failures" if blocking_fetch_status_count else "completed"
    )
    reporter.set_status(final_progress_status, limiter.snapshot())
    report = {
        "run_id": run_id,
        "task_id": "D2-T16",
        "remote_provider_called": True,
        "full": full,
        "task_count": len(tasks),
        "executed_task_count": len(tasks_to_run),
        "reference_task_count": reference_task_count,
        "skipped_resume_count": len(skipped_entries),
        "fresh": fresh,
        "fresh_removed_files": fresh_removed_files,
        "configured_security_count": universe.metrics["configured_security_count"],
        "mapped_security_count": universe.metrics["mapped_security_count"],
        "unmapped_security_count": universe.metrics["unmapped_security_count"],
        "reference_counts": reference_counts,
        "blocking_fetch_status_count": blocking_fetch_status_count,
        "quality": quality_result["quality"],
        "acceptance": acceptance,
        "handoff": handoff,
        "limiter": limiter.snapshot(),
    }
    _write_json(output_dir / "d2_t16_run_summary.json", report)
    write_hash_summary(output_dir)
    return report


def summarize_provider_errors(entries: list[D2T16LedgerEntry]) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    for entry in entries:
        if entry.error_category:
            by_category[entry.error_category] = (
                by_category.get(entry.error_category, 0) + 1
            )
    return {
        "task_id": "D2-T16",
        "error_count": sum(by_category.values()),
        "by_error_category": by_category,
    }


def _parse_endpoints(value: str) -> tuple[str, ...]:
    endpoints = tuple(part.strip() for part in value.split(",") if part.strip())
    if not endpoints:
        raise argparse.ArgumentTypeError("at least one endpoint is required")
    unsupported = sorted(set(endpoints) - set(ENDPOINTS))
    if unsupported:
        raise argparse.ArgumentTypeError(f"unsupported endpoints: {unsupported}")
    return endpoints


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
        "--chunk-policy",
        default="year",
        choices=("full-range", "year", "month"),
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
    client = None
    if not args.dry_run_plan and not args.no_remote_fetch:
        client = create_tnskhdata_client(args.env_file)
    report = run_provider_runner(
        client=client,
        output_dir=args.output_dir,
        security_universe=args.security_universe,
        start_date=args.start_date,
        end_date=args.end_date,
        endpoints=args.endpoints,
        full=args.full,
        sample_securities=args.sample_securities,
        chunk_policy=args.chunk_policy,
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
