"""Materialize D2-T13 tnskhdata full candidate evidence into ignored outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.resolve_security_provider_codes import resolve_security_provider_codes  # noqa: E402,I001
from scripts.run_d2_t12_provider_remediation_probe import (  # noqa: E402,I001
    build_adj_factor_snapshot_revision,
    classify_st_status,
    classify_suspension_status,
    classify_trading_status,
    derive_price_limit_status,
)

DEFAULT_CONTRACT = (
    ROOT / "configs/d2/tnskhdata_full_materialization_acceptance_contract.v1.json"
)
DEFAULT_OUTPUT_DIR = ROOT / "data/generated/d2/d2_t13_tnskhdata_full_candidate"
DEFAULT_SECURITY_UNIVERSE = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
)
DEFAULT_START_DATE = "20160101"
DEFAULT_END_DATE = "20260630"
UNIVERSE_COLUMNS = ["security_id", "trading_date", "universe_id", "time_segment_id"]
SECURITY_UNIVERSE_COLUMNS = ["security_id", "universe_id", "time_segment_id"]
OUTPUT_NAMES = [
    "tnskhdata_stock_basic_candidate.jsonl",
    "tnskhdata_trade_calendar_candidate.jsonl",
    "tnskhdata_daily_raw_candidate.jsonl",
    "tnskhdata_stk_limit_candidate.jsonl",
    "tnskhdata_adj_factor_candidate.jsonl",
    "tnskhdata_stock_st_candidate.jsonl",
    "tnskhdata_suspend_candidate.jsonl",
    "tnskhdata_source_status_candidate.jsonl",
    "tnskhdata_factor_evidence_candidate.jsonl",
    "tnskhdata_adjusted_price_candidate.jsonl",
    "tnskhdata_fetch_verification_report.json",
    "tnskhdata_date_domain_audit_report.json",
    "tnskhdata_quality_report.json",
    "tnskhdata_reconciliation_report.json",
    "tnskhdata_d2_acceptance_candidate_report.json",
    "tnskhdata_d3_handoff_candidate_report.json",
    "tnskhdata_candidate_file_hash_summary.json",
]
FORBIDDEN_OUTPUT_TOKENS = ("data/raw", "data/external", "marketdb", ".duckdb", ".day")


class D2T13MaterializationError(ValueError):
    """Raised when D2-T13 candidate materialization gates fail."""


@dataclass(frozen=True)
class FetchPlan:
    rows: list[dict[str, Any]]
    ts_codes: list[str]
    trade_dates: list[str]
    mode: str
    fetch_date_domain: str = "calendar"


@dataclass(frozen=True)
class FetchTask:
    task_id: str
    endpoint: str
    params: dict[str, Any]
    trade_date: str | None = None


@dataclass
class FetchTaskResult:
    task: FetchTask
    status: str
    rows: list[dict[str, Any]]
    attempt_count: int
    error_category: str | None = None
    error_message_redacted: str | None = None
    sha256: str | None = None
    artifact_partition_path: str | None = None


class AdaptiveRateGovernor:
    def __init__(
        self,
        *,
        initial_requests_per_minute: int = 200,
        max_requests_per_minute: int = 500,
        rate_increase_per_minute: int = 100,
        rate_decrease_factor: float = 0.5,
        min_requests_per_minute: int = 100,
        enabled: bool = True,
    ) -> None:
        self.current_rpm = initial_requests_per_minute
        self.max_rpm = max_requests_per_minute
        self.increase = rate_increase_per_minute
        self.decrease_factor = rate_decrease_factor
        self.min_rpm = min_requests_per_minute
        self.enabled = enabled
        self.lock = threading.Lock()
        self.next_allowed_at = 0.0
        self.minute_index = 0
        self.rate_increase_events = 0
        self.rate_decrease_events = 0
        self.history: list[dict[str, Any]] = []

    def acquire(self) -> None:
        if not self.enabled:
            return
        with self.lock:
            interval = 60.0 / self.current_rpm if self.current_rpm > 0 else 0.0
            now = time.monotonic()
            wait_seconds = max(0.0, self.next_allowed_at - now)
            self.next_allowed_at = max(now, self.next_allowed_at) + interval
        if wait_seconds:
            time.sleep(wait_seconds)

    def record_minute(
        self,
        *,
        successful_requests: int,
        failed_requests: int,
        rate_limit_count: int,
        timeout_count: int,
        provider_error_count: int,
    ) -> dict[str, Any]:
        with self.lock:
            backoff_events = 0
            if rate_limit_count or timeout_count or provider_error_count:
                self.current_rpm = max(
                    self.min_rpm, int(self.current_rpm * self.decrease_factor)
                )
                self.rate_decrease_events += 1
                backoff_events = 1
            elif successful_requests:
                new_rpm = min(self.max_rpm, self.current_rpm + self.increase)
                if new_rpm != self.current_rpm:
                    self.rate_increase_events += 1
                self.current_rpm = new_rpm
            entry = {
                "minute_index": self.minute_index,
                "current_rpm": self.current_rpm,
                "successful_requests": successful_requests,
                "failed_requests": failed_requests,
                "rate_limit_count": rate_limit_count,
                "timeout_count": timeout_count,
                "provider_error_count": provider_error_count,
                "backoff_events": backoff_events,
            }
            self.minute_index += 1
            self.history.append(entry)
            return entry

    def state(self) -> dict[str, Any]:
        return {
            "current_rpm": self.current_rpm,
            "rate_increase_events": self.rate_increase_events,
            "rate_decrease_events": self.rate_decrease_events,
            "history": self.history,
        }


class RequestThrottle:
    def __init__(self, requests_per_minute: int, enabled: bool) -> None:
        self.enabled = enabled
        self.interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self.next_allowed_at = 0.0

    def wait(self) -> None:
        if not self.enabled or self.interval <= 0:
            return
        now = time.monotonic()
        if now < self.next_allowed_at:
            time.sleep(self.next_allowed_at - now)
        self.next_allowed_at = time.monotonic() + self.interval


def _empty_checkpoint() -> dict[str, Any]:
    return {
        "completed_trade_dates": [],
        "failed_trade_dates": [],
        "retry_counts": {},
        "provider_error_categories": {},
        "last_successful_trade_date": None,
        "request_count": 0,
        "rate_limit_count": 0,
    }


def _checkpoint_path(checkpoint_dir: Path | None) -> Path | None:
    return (
        None
        if checkpoint_dir is None
        else checkpoint_dir / "tnskhdata_fetch_checkpoint.json"
    )


def _load_checkpoint(checkpoint_dir: Path | None, resume: bool) -> dict[str, Any]:
    path = _checkpoint_path(checkpoint_dir)
    if not resume or path is None or not path.exists():
        return _empty_checkpoint()
    payload = _load_json(path)
    checkpoint = _empty_checkpoint()
    checkpoint.update(payload if isinstance(payload, dict) else {})
    return checkpoint


def _write_checkpoint(checkpoint_dir: Path | None, checkpoint: dict[str, Any]) -> None:
    path = _checkpoint_path(checkpoint_dir)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, checkpoint)


def _is_rate_limit_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "rate" in text or "limit" in text or "频" in text


def _call_with_retry(
    fn: Any,
    *,
    throttle: RequestThrottle,
    retry_max_attempts: int,
    retry_backoff_seconds: float,
) -> list[dict[str, Any]]:
    attempts = max(1, retry_max_attempts)
    for attempt in range(attempts):
        throttle.wait()
        try:
            return _frame_records(fn())
        except Exception:
            if attempt == attempts - 1:
                raise
            if retry_backoff_seconds > 0 and throttle.enabled:
                time.sleep(retry_backoff_seconds)
    return []


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_rows(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows
        ).encode("utf-8")
    ).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _date_yyyymmdd(value: Any) -> str:
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return text[:10].replace("-", "")


def _calendar_dates(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(_date_yyyymmdd(start_date), "%Y%m%d").date()
    end = datetime.strptime(_date_yyyymmdd(end_date), "%Y%m%d").date()
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def load_tnskhdata_token(env_file: Path | None, allow_tushare_fallback: bool) -> str:
    values = _read_env_file(env_file)
    token = os.environ.get("TNSKHDATA_TOKEN") or values.get("TNSKHDATA_TOKEN", "")
    if not token and allow_tushare_fallback:
        token = os.environ.get("TUSHARE_TOKEN") or values.get("TUSHARE_TOKEN", "")
    return token


def _guard_output_dir(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if any(token in normalized for token in FORBIDDEN_OUTPUT_TOKENS):
        raise D2T13MaterializationError(f"forbidden output dir: {path}")


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "empty") and frame.empty:
        return []
    if hasattr(frame, "to_dict"):
        return [dict(row) for row in frame.to_dict("records")]
    if isinstance(frame, list):
        return [dict(row) for row in frame if isinstance(row, dict)]
    return []


def classify_provider_error(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if _is_rate_limit_error(exc) or "429" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "permission" in text or "denied" in text or "auth" in text:
        return "permission_denied"
    if "schema" in text or "field" in text or "column" in text:
        return "schema_missing"
    if "network" in text or "connection" in text or "reset" in text:
        return "network_error"
    return "unknown_provider_error"


def _redact_error(exc: Exception) -> str:
    text = str(exc)
    for key in ("token", "apikey", "api_key", "secret"):
        text = text.replace(key, "[redacted-key]")
    return text[:160]


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_candidate_universe(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".parquet":
        import pandas as pd

        frame = pd.read_parquet(path, columns=UNIVERSE_COLUMNS)
        rows = [dict(row) for row in frame.to_dict("records")]
    else:
        payload = _load_json(path)
        rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    output = []
    for row in rows:
        if any(field not in row for field in UNIVERSE_COLUMNS):
            raise D2T13MaterializationError("candidate universe row missing fields")
        trading_date = _date_yyyymmdd(row["trading_date"])
        output.append(
            {
                "security_id": str(row["security_id"]),
                "trading_date": trading_date,
                "universe_id": str(row["universe_id"]),
                "time_segment_id": str(row["time_segment_id"]),
            }
        )
    return output


def _load_security_universe(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".parquet":
        import pandas as pd

        frame = pd.read_parquet(path, columns=SECURITY_UNIVERSE_COLUMNS)
        rows = [dict(row) for row in frame.to_dict("records")]
    else:
        payload = _load_json(path)
        rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if any(field not in row for field in SECURITY_UNIVERSE_COLUMNS):
            raise D2T13MaterializationError("security universe row missing fields")
        security_id = str(row["security_id"])
        if security_id in seen:
            continue
        seen.add(security_id)
        output.append(
            {
                "security_id": security_id,
                "universe_id": str(row["universe_id"]),
                "time_segment_id": str(row["time_segment_id"]),
            }
        )
    return output


def _candidate_price_artifact_audit(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "candidate_price_artifact_provided": False,
            "candidate_price_artifact_date_min": None,
            "candidate_price_artifact_date_max": None,
            "candidate_price_artifact_superseded": True,
            "candidate_price_artifact_date_domain_ignored": True,
        }
    if path.suffix.lower() == ".parquet":
        import pandas as pd

        frame = pd.read_parquet(path, columns=UNIVERSE_COLUMNS)
        dates = frame["trading_date"].map(_date_yyyymmdd)
        row_count = int(len(frame))
        security_count = int(frame["security_id"].nunique())
        date_min = min(dates, default=None)
        date_max = max(dates, default=None)
    else:
        rows = _load_candidate_universe(path)
        dates = [row["trading_date"] for row in rows]
        row_count = len(rows)
        security_count = len({row["security_id"] for row in rows})
        date_min = min(dates, default=None)
        date_max = max(dates, default=None)
    return {
        "candidate_price_artifact_provided": True,
        "candidate_price_artifact_path_redacted": (
            "data/generated/d2/d2_t09_candidate_raw_market_prices/"
            "candidate_raw_market_prices.parquet"
            if "d2_t09_candidate_raw_market_prices" in str(path).lower()
            else path.name
        ),
        "candidate_price_artifact_date_min": date_min,
        "candidate_price_artifact_date_max": date_max,
        "candidate_price_artifact_superseded": True,
        "candidate_price_artifact_date_domain_ignored": True,
        "candidate_price_artifact_security_count": security_count,
        "candidate_price_artifact_row_count": row_count,
    }


def build_date_domain_audit_report(
    *,
    contract: dict[str, Any],
    security_universe_path: Path,
    candidate_price_artifact: Path | None,
    fetch_date_domain: str,
) -> dict[str, Any]:
    candidate_audit = _candidate_price_artifact_audit(candidate_price_artifact)
    return {
        "dr001_start_date": contract["start_date"],
        "dr001_end_date": contract["end_date"],
        "canonical_fetch_date_domain": "calendar",
        "date_domain_source": "DR-001",
        "requested_fetch_date_domain": fetch_date_domain,
        "security_universe_source": (
            "CSI800_STATIC_2026_06 membership / security mapping"
        ),
        "security_universe_path": str(security_universe_path).replace("\\", "/"),
        "d2_t09_candidate_raw_market_prices_is_superseded_diagnostic_input_only": True,
        (
            "d2_t09_candidate_raw_market_prices_must_not_define_canonical_fetch_domain"
        ): True,
        **candidate_audit,
    }


def build_fetch_plan(
    rows: list[dict[str, Any]],
    *,
    full: bool,
    sample_securities: int | None,
    sample_dates_per_security: int | None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    fetch_date_domain: str = "candidate",
    trade_cal_open_dates: list[str] | None = None,
) -> FetchPlan:
    if fetch_date_domain not in {"calendar", "candidate", "trade-cal-open"}:
        raise D2T13MaterializationError("unsupported fetch_date_domain")
    if fetch_date_domain == "calendar":
        trade_dates = _calendar_dates(start_date, end_date)
    elif fetch_date_domain == "candidate":
        trade_dates = sorted({_date_yyyymmdd(row["trading_date"]) for row in rows})
    else:
        if trade_cal_open_dates is None:
            raise D2T13MaterializationError(
                "trade-cal-open fetch_date_domain requires explicit open dates"
            )
        trade_dates = sorted({_date_yyyymmdd(date) for date in trade_cal_open_dates})
    security_rows: list[dict[str, Any]] = []
    seen_security_ids: set[str] = set()
    for row in rows:
        base = {
            "security_id": str(row["security_id"]),
            "universe_id": str(row["universe_id"]),
            "time_segment_id": str(row["time_segment_id"]),
        }
        if base["security_id"] in seen_security_ids:
            continue
        seen_security_ids.add(base["security_id"])
        security_rows.append(base)
    mapped_securities: list[dict[str, Any]] = []
    for row in security_rows:
        mapping = resolve_security_provider_codes(row["security_id"])
        if mapping.mapping_status != "resolved":
            mapped_securities.append(
                {**row, "ts_code": None, "mapping_status": "unresolved"}
            )
            continue
        mapped_securities.append(
            {**row, "ts_code": mapping.tnskhdata_ts_code, "mapping_status": "resolved"}
        )
    mapped_rows = [
        {**security, "trading_date": trade_date}
        for security in mapped_securities
        for trade_date in trade_dates
    ]
    if not full:
        by_security: dict[str, list[dict[str, Any]]] = {}
        for row in mapped_rows:
            by_security.setdefault(row["security_id"], []).append(row)
        selected = sorted(by_security)[: sample_securities or 20]
        sampled = []
        for security_id in selected:
            dates = sorted(
                by_security[security_id], key=lambda item: item["trading_date"]
            )
            sampled.extend(dates[-(sample_dates_per_security or 5) :])
        mapped_rows = sampled
    return FetchPlan(
        rows=mapped_rows,
        ts_codes=sorted({row["ts_code"] for row in mapped_rows if row.get("ts_code")}),
        trade_dates=sorted({row["trading_date"] for row in mapped_rows}),
        mode="full" if full else "sample",
        fetch_date_domain=fetch_date_domain,
    )


def build_endpoint_tasks(plan: FetchPlan) -> list[FetchTask]:
    tasks = [
        FetchTask(
            task_id=f"stock_basic:{status}",
            endpoint="stock_basic",
            params={"exchange": "", "list_status": status},
        )
        for status in ("L", "D", "P", "G")
    ]
    start_date = min(plan.trade_dates) if plan.trade_dates else DEFAULT_START_DATE
    end_date = max(plan.trade_dates) if plan.trade_dates else DEFAULT_END_DATE
    tasks.append(
        FetchTask(
            task_id=f"trade_cal:{start_date}:{end_date}",
            endpoint="trade_cal",
            params={"exchange": "", "start_date": start_date, "end_date": end_date},
        )
    )
    for trade_date in plan.trade_dates:
        for endpoint in ("daily", "stk_limit", "adj_factor", "stock_st", "suspend_d"):
            tasks.append(
                FetchTask(
                    task_id=f"{endpoint}:{trade_date}",
                    endpoint=endpoint,
                    params={"trade_date": trade_date},
                    trade_date=trade_date,
                )
            )
    return tasks


class PartitionedJsonlStagingWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.Lock()

    def partition_path(self, task: FetchTask) -> Path:
        suffix = task.trade_date or str(task.params.get("list_status") or "range")
        return self.root / "partitions" / task.endpoint / f"{suffix}.jsonl"

    def write(self, task: FetchTask, rows: list[dict[str, Any]]) -> tuple[str, str]:
        path = self.partition_path(task)
        with self.lock:
            _write_jsonl(path, rows)
            digest = _sha256_file(path)
        return str(path), digest

    def iter_endpoint(self, endpoint: str):
        endpoint_dir = self.root / "partitions" / endpoint
        if not endpoint_dir.exists():
            return
        for path in sorted(endpoint_dir.glob("*.jsonl")):
            yield from _read_jsonl(path)

    def count_endpoint_partitions(self, endpoint: str) -> int:
        endpoint_dir = self.root / "partitions" / endpoint
        if not endpoint_dir.exists():
            return 0
        return len(list(endpoint_dir.glob("*.jsonl")))


def _ledger_path(checkpoint_dir: Path | None) -> Path | None:
    return None if checkpoint_dir is None else checkpoint_dir / "fetch_ledger.jsonl"


def _load_ledger(checkpoint_dir: Path | None) -> dict[str, dict[str, Any]]:
    path = _ledger_path(checkpoint_dir)
    if path is None or not path.exists():
        return {}
    return {row["task_id"]: row for row in _read_jsonl(path) if row.get("task_id")}


def _legacy_checkpoint_path(checkpoint_dir: Path | None) -> Path | None:
    return (
        None
        if checkpoint_dir is None
        else checkpoint_dir / "tnskhdata_fetch_checkpoint.json"
    )


def _migrate_legacy_checkpoint(
    checkpoint_dir: Path | None, tasks: list[FetchTask]
) -> dict[str, dict[str, Any]]:
    path = _legacy_checkpoint_path(checkpoint_dir)
    if path is None or not path.exists():
        return {}
    legacy = _load_json(path)
    completed = set(legacy.get("completed_trade_dates", []))
    failed = set(legacy.get("failed_trade_dates", []))
    migrated: dict[str, dict[str, Any]] = {}
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for task in tasks:
        if task.trade_date in completed:
            migrated[task.task_id] = {
                "task_id": task.task_id,
                "endpoint": task.endpoint,
                "trade_date": task.trade_date,
                "status": "legacy_succeeded",
                "attempt_count": 0,
                "last_attempt_at": now,
                "last_error_category": None,
                "last_error_message_redacted": None,
                "row_count": None,
                "artifact_partition_path": None,
                "sha256": None,
                "started_at": now,
                "completed_at": now,
                "legacy_checkpoint_migrated": True,
            }
        elif task.trade_date in failed:
            migrated[task.task_id] = {
                "task_id": task.task_id,
                "endpoint": task.endpoint,
                "trade_date": task.trade_date,
                "status": "failed",
                "attempt_count": 0,
                "last_attempt_at": now,
                "last_error_category": "legacy_failed_trade_date",
                "last_error_message_redacted": "legacy checkpoint failed date",
                "row_count": 0,
                "artifact_partition_path": None,
                "sha256": None,
                "started_at": now,
                "completed_at": None,
                "legacy_checkpoint_migrated": True,
            }
    return migrated


def _write_ledger(checkpoint_dir: Path | None, rows: list[dict[str, Any]]) -> None:
    path = _ledger_path(checkpoint_dir)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(path, rows)


def _task_ledger_row(result: FetchTaskResult) -> dict[str, Any]:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return {
        "task_id": result.task.task_id,
        "endpoint": result.task.endpoint,
        "trade_date": result.task.trade_date,
        "status": result.status,
        "attempt_count": result.attempt_count,
        "last_attempt_at": now,
        "last_error_category": result.error_category,
        "last_error_message_redacted": result.error_message_redacted,
        "row_count": len(result.rows),
        "artifact_partition_path": result.artifact_partition_path,
        "sha256": result.sha256,
        "started_at": now,
        "completed_at": now if result.status in {"succeeded", "failed"} else None,
    }


def _call_task_with_retry(
    client: Any,
    task: FetchTask,
    *,
    governor: AdaptiveRateGovernor,
    retry_max_attempts: int,
    retry_backoff_seconds: float,
) -> FetchTaskResult:
    method = getattr(client, task.endpoint)
    last_exc: Exception | None = None
    for attempt in range(1, max(1, retry_max_attempts) + 1):
        governor.acquire()
        try:
            rows = _frame_records(method(**task.params))
            status = "succeeded"
            return FetchTaskResult(task, status, rows, attempt)
        except Exception as exc:
            last_exc = exc
            category = classify_provider_error(exc)
            if category in {"permission_denied", "schema_missing"}:
                break
            if retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds)
    assert last_exc is not None
    return FetchTaskResult(
        task=task,
        status="failed",
        rows=[],
        attempt_count=max(1, retry_max_attempts),
        error_category=classify_provider_error(last_exc),
        error_message_redacted=_redact_error(last_exc),
    )


def _flush_fetch_progress(
    *,
    checkpoint_dir: Path | None,
    ledger_rows: list[dict[str, Any]],
    governor: AdaptiveRateGovernor,
) -> None:
    if checkpoint_dir is None:
        return
    _write_ledger(checkpoint_dir, ledger_rows)
    succeeded = sum(
        1 for row in ledger_rows if row["status"] in {"succeeded", "legacy_succeeded"}
    )
    failed = sum(1 for row in ledger_rows if row["status"] == "failed")
    rate_limit = sum(
        1 for row in ledger_rows if row.get("last_error_category") == "rate_limit"
    )
    timeout = sum(
        1 for row in ledger_rows if row.get("last_error_category") == "timeout"
    )
    provider_errors = sum(
        1
        for row in ledger_rows
        if row.get("last_error_category")
        and row.get("last_error_category") not in {"rate_limit", "timeout"}
    )
    governor.record_minute(
        successful_requests=succeeded,
        failed_requests=failed,
        rate_limit_count=rate_limit,
        timeout_count=timeout,
        provider_error_count=provider_errors,
    )
    _write_json(checkpoint_dir / "rate_governor_state.json", governor.state())
    _write_json(
        checkpoint_dir / "quality_progress_summary.json",
        {
            "succeeded_task_count": succeeded,
            "failed_task_count": failed,
            "rate_limit_count": rate_limit,
            "timeout_count": timeout,
            "provider_error_count": provider_errors,
        },
    )
    _write_json(
        checkpoint_dir / "partial_hash_manifest.json",
        {row["task_id"]: row["sha256"] for row in ledger_rows if row.get("sha256")},
    )


def fetch_provider_evidence_parallel(
    client: Any,
    plan: FetchPlan,
    *,
    output_dir: Path,
    checkpoint_dir: Path | None,
    resume: bool,
    max_workers: int = 7,
    initial_requests_per_minute: int = 200,
    max_requests_per_minute: int = 500,
    rate_increase_per_minute: int = 100,
    rate_decrease_factor: float = 0.5,
    retry_max_attempts: int = 5,
    retry_backoff_seconds: float = 10.0,
    flush_interval_seconds: int = 60,
    repair_failed_only: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    writer = PartitionedJsonlStagingWriter(output_dir)
    governor = AdaptiveRateGovernor(
        initial_requests_per_minute=initial_requests_per_minute,
        max_requests_per_minute=max_requests_per_minute,
        rate_increase_per_minute=rate_increase_per_minute,
        rate_decrease_factor=rate_decrease_factor,
    )
    all_tasks = build_endpoint_tasks(plan)
    existing = _load_ledger(checkpoint_dir) if resume else {}
    if resume and not existing:
        existing = _migrate_legacy_checkpoint(checkpoint_dir, all_tasks)
    resumable_statuses = {"succeeded", "legacy_succeeded"}
    if repair_failed_only:
        failed_dates = {
            row.get("trade_date")
            for row in existing.values()
            if row.get("status") == "failed" and row.get("trade_date")
        }
        tasks = [
            task
            for task in all_tasks
            if task.trade_date in failed_dates
            and task.endpoint
            in {"daily", "stk_limit", "adj_factor", "stock_st", "suspend_d"}
        ]
    else:
        tasks = [
            task
            for task in all_tasks
            if existing.get(task.task_id, {}).get("status") not in resumable_statuses
        ]
    ledger_rows = [
        row for row in existing.values() if row.get("status") in resumable_statuses
    ]
    last_flush = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
    try:
        futures = {
            executor.submit(
                _call_task_with_retry,
                client,
                task,
                governor=governor,
                retry_max_attempts=retry_max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
            ): task
            for task in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            if result.status == "succeeded":
                path, digest = writer.write(result.task, result.rows)
                result.artifact_partition_path = path
                result.sha256 = digest
            ledger_rows = [
                row for row in ledger_rows if row["task_id"] != result.task.task_id
            ]
            ledger_rows.append(_task_ledger_row(result))
            if time.monotonic() - last_flush >= flush_interval_seconds:
                _flush_fetch_progress(
                    checkpoint_dir=checkpoint_dir,
                    ledger_rows=ledger_rows,
                    governor=governor,
                )
                last_flush = time.monotonic()
    except KeyboardInterrupt:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        _flush_fetch_progress(
            checkpoint_dir=checkpoint_dir, ledger_rows=ledger_rows, governor=governor
        )
        raise D2T13MaterializationError("interrupted; checkpoint flushed")
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    _flush_fetch_progress(
        checkpoint_dir=checkpoint_dir, ledger_rows=ledger_rows, governor=governor
    )
    failed = [row for row in ledger_rows if row["status"] == "failed"]
    succeeded_count = sum(
        1 for row in ledger_rows if row["status"] in {"succeeded", "legacy_succeeded"}
    )
    evidence = {
        "stock_basic": [],
        "trade_cal": [],
        "daily": [],
        "stk_limit": [],
        "adj_factor": [],
        "stock_st": [],
        "suspend_d": [],
        "pro_bar_qfq": [],
        "pro_bar_hfq": [],
        "_metrics": [
            {
                "request_count": sum(
                    row.get("attempt_count", 0)
                    for row in ledger_rows
                    if row.get("status") != "legacy_succeeded"
                ),
                "successful_request_count": succeeded_count,
                "failed_request_count": len(failed),
                "primary_provider_error_count": len(failed),
                "reconciliation_provider_error_count": 0,
                "pro_bar_reconciliation_status": "not_reached_full_run_incomplete"
                if failed
                else "passed_or_not_requested",
                "pro_bar_reconciliation_warning_count": 0,
                "rate_limit_count": sum(
                    1
                    for row in failed
                    if row.get("last_error_category") == "rate_limit"
                ),
                "timeout_count": sum(
                    1 for row in failed if row.get("last_error_category") == "timeout"
                ),
                "retry_count": sum(
                    max(0, row.get("attempt_count", 1) - 1) for row in ledger_rows
                ),
                "resume_checkpoint_count": sum(
                    1
                    for row in ledger_rows
                    if row["status"] in {"succeeded", "legacy_succeeded"}
                ),
                "all_tasks_completed": not failed
                and len(ledger_rows) == len(all_tasks)
                and all(row["status"] == "succeeded" for row in ledger_rows),
                "legacy_succeeded_task_count": sum(
                    1 for row in ledger_rows if row["status"] == "legacy_succeeded"
                ),
                "endpoint_task_counts": {
                    endpoint: sum(1 for task in all_tasks if task.endpoint == endpoint)
                    for endpoint in (
                        "stock_basic",
                        "trade_cal",
                        "daily",
                        "stk_limit",
                        "adj_factor",
                        "stock_st",
                        "suspend_d",
                    )
                },
                "failed_task_counts": {
                    endpoint: sum(1 for row in failed if row["endpoint"] == endpoint)
                    for endpoint in (
                        "stock_basic",
                        "trade_cal",
                        "daily",
                        "stk_limit",
                        "adj_factor",
                        "stock_st",
                        "suspend_d",
                    )
                },
                "final_requests_per_minute": governor.current_rpm,
                "rate_increase_events": governor.rate_increase_events,
                "rate_decrease_events": governor.rate_decrease_events,
            }
        ],
    }
    return evidence


def _client_from_token(token: str) -> Any:
    if not token:
        raise D2T13MaterializationError("TNSKHDATA_TOKEN missing")
    module = __import__("tnskhdata")
    return module.pro_api(token)


def fetch_provider_evidence(
    client: Any,
    plan: FetchPlan,
    *,
    requests_per_minute: int = 200,
    pro_bar_requests_per_minute: int = 60,
    retry_max_attempts: int = 3,
    retry_backoff_seconds: float = 5.0,
    throttle_enabled: bool = False,
    resume: bool = False,
    checkpoint_dir: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    checkpoint = _load_checkpoint(checkpoint_dir, resume)
    request_count = int(checkpoint.get("request_count", 0)) if resume else 0
    completed_trade_dates = set(checkpoint.get("completed_trade_dates", []))
    failed_trade_dates = set(checkpoint.get("failed_trade_dates", []))
    retry_counts = dict(checkpoint.get("retry_counts", {}))
    provider_error_categories = dict(checkpoint.get("provider_error_categories", {}))
    primary_throttle = RequestThrottle(requests_per_minute, enabled=throttle_enabled)
    pro_bar_throttle = RequestThrottle(
        pro_bar_requests_per_minute, enabled=throttle_enabled
    )
    stock_basic = []
    for status in ("L", "D", "P", "G"):
        stock_basic.extend(
            _call_with_retry(
                lambda status=status: client.stock_basic(
                    exchange="", list_status=status
                ),
                throttle=primary_throttle,
                retry_max_attempts=retry_max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
            )
        )
        request_count += 1
    start_date = min(plan.trade_dates) if plan.trade_dates else DEFAULT_START_DATE
    end_date = max(plan.trade_dates) if plan.trade_dates else DEFAULT_END_DATE
    trade_cal = _call_with_retry(
        lambda: client.trade_cal(exchange="", start_date=start_date, end_date=end_date),
        throttle=primary_throttle,
        retry_max_attempts=retry_max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    request_count += 1
    daily: list[dict[str, Any]] = []
    stk_limit: list[dict[str, Any]] = []
    adj_factor: list[dict[str, Any]] = []
    stock_st: list[dict[str, Any]] = []
    suspend_d: list[dict[str, Any]] = []
    primary_provider_error_count = 0
    reconciliation_provider_error_count = 0
    pro_bar_reconciliation_warning_count = 0
    rate_limit_count = 0
    for trade_date in plan.trade_dates:
        if resume and trade_date in completed_trade_dates:
            continue
        date_failed = False
        for name, method in (
            ("daily", lambda: client.daily(trade_date=trade_date)),
            ("stk_limit", lambda: client.stk_limit(trade_date=trade_date)),
            ("adj_factor", lambda: client.adj_factor(trade_date=trade_date)),
            ("stock_st", lambda: client.stock_st(trade_date=trade_date)),
            ("suspend_d", lambda: client.suspend_d(trade_date=trade_date)),
        ):
            try:
                rows = _call_with_retry(
                    method,
                    throttle=primary_throttle,
                    retry_max_attempts=retry_max_attempts,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
                if name == "daily":
                    daily.extend(rows)
                elif name == "stk_limit":
                    stk_limit.extend(rows)
                elif name == "adj_factor":
                    adj_factor.extend(rows)
                elif name == "stock_st":
                    stock_st.extend(rows)
                else:
                    suspend_d.extend(rows)
            except Exception as exc:
                date_failed = True
                primary_provider_error_count += 1
                retry_counts[f"{trade_date}:{name}"] = retry_max_attempts
                provider_error_categories[name] = (
                    provider_error_categories.get(name, 0) + 1
                )
                if _is_rate_limit_error(exc):
                    rate_limit_count += 1
                if name == "adj_factor":
                    for ts_code in plan.ts_codes:
                        try:
                            adj_factor.extend(
                                _call_with_retry(
                                    lambda ts_code=ts_code: client.adj_factor(
                                        ts_code=ts_code,
                                        start_date=start_date,
                                        end_date=end_date,
                                    ),
                                    throttle=primary_throttle,
                                    retry_max_attempts=retry_max_attempts,
                                    retry_backoff_seconds=retry_backoff_seconds,
                                )
                            )
                            request_count += 1
                        except Exception as fallback_exc:
                            date_failed = True
                            primary_provider_error_count += 1
                            retry_counts[f"{trade_date}:adj_factor_ts_code"] = (
                                retry_max_attempts
                            )
                            provider_error_categories["adj_factor"] = (
                                provider_error_categories.get("adj_factor", 0) + 1
                            )
                            if _is_rate_limit_error(fallback_exc):
                                rate_limit_count += 1
            request_count += 1
        if date_failed:
            failed_trade_dates.add(trade_date)
        else:
            completed_trade_dates.add(trade_date)
            failed_trade_dates.discard(trade_date)
            checkpoint["last_successful_trade_date"] = trade_date
        checkpoint.update(
            {
                "completed_trade_dates": sorted(completed_trade_dates),
                "failed_trade_dates": sorted(failed_trade_dates),
                "retry_counts": retry_counts,
                "provider_error_categories": provider_error_categories,
                "request_count": request_count,
                "rate_limit_count": rate_limit_count,
            }
        )
        _write_checkpoint(checkpoint_dir, checkpoint)
    pro_bar_qfq: list[dict[str, Any]] = []
    pro_bar_hfq: list[dict[str, Any]] = []
    for ts_code in plan.ts_codes[: min(5, len(plan.ts_codes))]:
        pro_bar = getattr(client, "pro_bar", None)
        if pro_bar is None:
            continue
        try:
            pro_bar_qfq.extend(
                _call_with_retry(
                    lambda ts_code=ts_code: pro_bar(
                        ts_code=ts_code,
                        adj="qfq",
                        start_date=start_date,
                        end_date=end_date,
                    ),
                    throttle=pro_bar_throttle,
                    retry_max_attempts=retry_max_attempts,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
            )
            pro_bar_hfq.extend(
                _call_with_retry(
                    lambda ts_code=ts_code: pro_bar(
                        ts_code=ts_code,
                        adj="hfq",
                        start_date=start_date,
                        end_date=end_date,
                    ),
                    throttle=pro_bar_throttle,
                    retry_max_attempts=retry_max_attempts,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
            )
            request_count += 2
        except Exception as exc:
            reconciliation_provider_error_count += 1
            pro_bar_reconciliation_warning_count += 1
            if _is_rate_limit_error(exc):
                rate_limit_count += 1
    return {
        "stock_basic": stock_basic,
        "trade_cal": trade_cal,
        "daily": daily,
        "stk_limit": stk_limit,
        "adj_factor": adj_factor,
        "stock_st": stock_st,
        "suspend_d": suspend_d,
        "pro_bar_qfq": pro_bar_qfq,
        "pro_bar_hfq": pro_bar_hfq,
        "_metrics": [
            {
                "request_count": request_count,
                "primary_provider_error_count": primary_provider_error_count,
                "reconciliation_provider_error_count": (
                    reconciliation_provider_error_count
                ),
                "pro_bar_reconciliation_status": "failed_non_blocking"
                if pro_bar_reconciliation_warning_count
                else "passed_or_not_requested",
                "pro_bar_reconciliation_warning_count": (
                    pro_bar_reconciliation_warning_count
                ),
                "rate_limit_count": rate_limit_count,
                "resume_checkpoint_count": len(completed_trade_dates),
            }
        ],
    }


def _by_ts_code(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("ts_code")): row for row in rows if row.get("ts_code")}


def _by_ts_date(
    rows: list[dict[str, Any]], date_field: str = "trade_date"
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("ts_code")), _date_yyyymmdd(row.get(date_field))): row
        for row in rows
        if row.get("ts_code") and row.get(date_field)
    }


def _raw_daily(row: dict[str, Any], daily: dict[str, Any]) -> dict[str, Any]:
    volume_lot = _to_float(daily.get("vol"))
    amount_thousand = _to_float(daily.get("amount"))
    return {
        **row,
        "source_registry_id": "tnskhdata",
        "raw_open": _to_float(daily.get("open")),
        "raw_high": _to_float(daily.get("high")),
        "raw_low": _to_float(daily.get("low")),
        "raw_close": _to_float(daily.get("close")),
        "pre_close": _to_float(daily.get("pre_close")),
        "volume_lot": volume_lot,
        "volume_shares": None if volume_lot is None else volume_lot * 100,
        "amount_thousand_yuan": amount_thousand,
        "amount_yuan": None if amount_thousand is None else amount_thousand * 1000,
    }


def build_candidate_outputs(
    plan: FetchPlan,
    evidence: dict[str, list[dict[str, Any]]],
    *,
    source_snapshot_id: str,
    artifact_sha256: str,
) -> dict[str, Any]:
    stock_basic_by_code = _by_ts_code(evidence["stock_basic"])
    trade_cal_by_date = {
        _date_yyyymmdd(row.get("cal_date")): row for row in evidence["trade_cal"]
    }
    daily_by_key = _by_ts_date(evidence["daily"])
    stk_limit_by_key = _by_ts_date(evidence["stk_limit"])
    adj_factor_by_key = _by_ts_date(evidence["adj_factor"])
    stock_st_by_key = _by_ts_date(evidence["stock_st"])
    suspend_by_key = _by_ts_date(evidence["suspend_d"])
    raw_rows: list[dict[str, Any]] = []
    source_status_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    for row in plan.rows:
        ts_code = row.get("ts_code")
        key = (str(ts_code), row["trading_date"])
        stock_basic = stock_basic_by_code.get(str(ts_code), {})
        trade_cal = trade_cal_by_date.get(row["trading_date"], {})
        daily = daily_by_key.get(key)
        stk_limit = stk_limit_by_key.get(key)
        adj_factor = adj_factor_by_key.get(key)
        stock_st = stock_st_by_key.get(key)
        suspend = suspend_by_key.get(key)
        if daily:
            raw_rows.append(_raw_daily(row, daily))
        trading_status = classify_trading_status(
            trading_date=row["trading_date"],
            stock_basic=stock_basic,
            trade_cal=trade_cal,
            daily_row=daily,
            suspend_row=suspend,
        )
        source_status_rows.append(
            {
                **row,
                "source_registry_id": "tnskhdata",
                "trading_status": trading_status,
                "suspension_status": classify_suspension_status(
                    trading_status=trading_status,
                    daily_row=daily,
                    suspend_row=suspend,
                ),
                **classify_st_status(
                    trading_status=trading_status, stock_st_row=stock_st
                ),
                **derive_price_limit_status(
                    trading_status=trading_status,
                    daily_row=daily,
                    stk_limit_row=stk_limit,
                ),
                "limit_price_source": "tnskhdata_stk_limit" if stk_limit else None,
                "is_trading_day": str(trade_cal.get("is_open")) == "1",
                "trading_calendar_status": "open"
                if str(trade_cal.get("is_open")) == "1"
                else "closed"
                if trade_cal
                else "missing",
            }
        )
        factor = build_adj_factor_snapshot_revision(
            trading_date=row["trading_date"],
            adj_factor_row=adj_factor or {},
            source_snapshot_id=source_snapshot_id,
            artifact_sha256=artifact_sha256,
        )
        factor_rows.append(
            {
                **row,
                "source_registry_id": "tnskhdata",
                "adjustment_factor_source": "tnskhdata_adj_factor"
                if adj_factor
                else None,
                **factor,
            }
        )
        factor_value = factor.get("adjustment_factor")
        if daily and factor_value is not None:
            anchor = factor_value
            adjusted_rows.append(
                {
                    **row,
                    "source_registry_id": "tnskhdata",
                    "hfq_open": _to_float(daily.get("open")) * factor_value,
                    "hfq_high": _to_float(daily.get("high")) * factor_value,
                    "hfq_low": _to_float(daily.get("low")) * factor_value,
                    "hfq_close": _to_float(daily.get("close")) * factor_value,
                    "qfq_open": _to_float(daily.get("open")) * factor_value / anchor,
                    "qfq_high": _to_float(daily.get("high")) * factor_value / anchor,
                    "qfq_low": _to_float(daily.get("low")) * factor_value / anchor,
                    "qfq_close": _to_float(daily.get("close")) * factor_value / anchor,
                    "qfq_anchor_trade_date": row["trading_date"],
                    "qfq_anchor_adj_factor": anchor,
                    "qfq_anchor_policy": "explicit_end_date_anchor",
                }
            )
    return {
        "raw": raw_rows,
        "source_status": source_status_rows,
        "factor_evidence": factor_rows,
        "adjusted_price": adjusted_rows,
    }


def build_quality_report(
    plan: FetchPlan,
    outputs: dict[str, list[dict[str, Any]]],
    evidence: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    rows = plan.rows
    source_status = outputs["source_status"]
    factor = outputs["factor_evidence"]
    raw = outputs["raw"]
    duplicate_keys = len(rows) - len(
        {(r["security_id"], r["trading_date"]) for r in rows}
    )
    null_ohlc = sum(
        1
        for row in raw
        if any(
            row.get(field) is None
            for field in ("raw_open", "raw_high", "raw_low", "raw_close")
        )
    )
    non_positive = sum(
        1
        for row in raw
        if any(
            (row.get(field) or 0) <= 0
            for field in ("raw_open", "raw_high", "raw_low", "raw_close")
        )
    )
    high_low = sum(
        1
        for row in raw
        if row.get("raw_high") is not None
        and row.get("raw_low") is not None
        and row["raw_high"] < row["raw_low"]
    )
    metrics = evidence.get("_metrics", [{}])[0]
    unresolved = {"unknown", "unresolved", "provider_empty_or_unclassified", None, ""}
    return {
        "run_mode": plan.mode,
        "sample_mode": plan.mode != "full",
        "fetch_date_domain": plan.fetch_date_domain,
        "date_domain_source": "DR-001"
        if plan.fetch_date_domain == "calendar"
        else (
            "D2_T09_candidate_raw_market_prices"
            if plan.fetch_date_domain == "candidate"
            else "trade_cal_open"
        ),
        "candidate_price_artifact_date_domain_ignored": True,
        "candidate_universe_row_count": len(rows),
        "mapped_row_count": sum(
            1 for row in rows if row.get("mapping_status") == "resolved"
        ),
        "unmapped_row_count": sum(
            1 for row in rows if row.get("mapping_status") != "resolved"
        ),
        "daily_raw_row_count": len(raw),
        "source_status_row_count": len(source_status),
        "factor_evidence_row_count": len(factor),
        "adjusted_price_row_count": len(outputs["adjusted_price"]),
        "security_count": len({row["security_id"] for row in rows}),
        "trading_date_min": min((row["trading_date"] for row in rows), default=None),
        "trading_date_max": max((row["trading_date"] for row in rows), default=None),
        "missing_daily_count": len(rows) - len(raw),
        "missing_stk_limit_count": max(0, len(rows) - len(evidence["stk_limit"])),
        "missing_adj_factor_count": sum(
            1 for row in factor if row["adjustment_factor_status"] != "resolved"
        ),
        "missing_trade_cal_count": max(
            0, len({row["trading_date"] for row in rows}) - len(evidence["trade_cal"])
        ),
        "missing_stock_basic_count": max(
            0, len({row.get("ts_code") for row in rows}) - len(evidence["stock_basic"])
        ),
        "missing_stock_st_count": max(0, len(rows) - len(evidence["stock_st"])),
        "missing_suspend_count": max(0, len(rows) - len(evidence["suspend_d"])),
        "unresolved_trading_status_count": sum(
            1 for row in source_status if row["trading_status"] in unresolved
        ),
        "unresolved_suspension_status_count": sum(
            1 for row in source_status if row["suspension_status"] in unresolved
        ),
        "unresolved_st_status_count": sum(
            1 for row in source_status if row["st_status"] in unresolved
        ),
        "unresolved_price_limit_status_count": sum(
            1 for row in source_status if row["price_limit_status"] in unresolved
        ),
        "unresolved_adjustment_factor_count": sum(
            1 for row in factor if row["adjustment_factor_status"] != "resolved"
        ),
        "amount_unit_status": "unknown"
        if any(row.get("amount_thousand_yuan") is None for row in raw)
        else "resolved_thousand_yuan",
        "volume_unit_status": "unknown"
        if any(row.get("volume_lot") is None for row in raw)
        else "resolved_lot",
        "duplicate_key_count": duplicate_keys,
        "null_ohlc_count": null_ohlc,
        "non_positive_price_count": non_positive,
        "high_low_violation_count": high_low,
        "primary_provider_error_count": metrics.get("primary_provider_error_count", 0),
        "reconciliation_provider_error_count": metrics.get(
            "reconciliation_provider_error_count", 0
        ),
        "pro_bar_reconciliation_status": metrics.get(
            "pro_bar_reconciliation_status", "passed_or_not_requested"
        ),
        "pro_bar_reconciliation_warning_count": metrics.get(
            "pro_bar_reconciliation_warning_count", 0
        ),
        "rate_limit_count": metrics.get("rate_limit_count", 0),
        "timeout_count": metrics.get("timeout_count", 0),
        "retry_count": metrics.get("retry_count", 0),
        "successful_request_count": metrics.get("successful_request_count", 0),
        "failed_request_count": metrics.get("failed_request_count", 0),
        "all_tasks_completed": metrics.get("all_tasks_completed", True),
        "endpoint_task_counts": metrics.get("endpoint_task_counts", {}),
        "failed_task_counts": metrics.get("failed_task_counts", {}),
        "final_requests_per_minute": metrics.get("final_requests_per_minute"),
        "rate_increase_events": metrics.get("rate_increase_events", 0),
        "rate_decrease_events": metrics.get("rate_decrease_events", 0),
        "resume_checkpoint_count": metrics.get("resume_checkpoint_count", 0),
    }


def acceptance_decision(quality: dict[str, Any]) -> str:
    if quality.get("run_mode") != "full" or quality.get("sample_mode") is not False:
        return "blocked_pending_tnskhdata_full_materialization_run"
    if quality.get("fetch_date_domain", "calendar") != "calendar":
        return "blocked_pending_tnskhdata_full_materialization_run"
    if quality.get("date_domain_source", "DR-001") != "DR-001":
        return "blocked_pending_tnskhdata_full_materialization_run"
    if quality.get("fetch_stage_only") is True:
        return "blocked_pending_tnskhdata_full_materialization_run"
    if quality.get("fetch_completeness_decision", "complete") != "complete":
        return "blocked_pending_provider_coverage"
    if quality.get("provider_coverage_decision", "complete") != "complete":
        return "blocked_pending_provider_coverage"
    if quality.get("unexpected_empty_primary_partition_count", 0):
        return "blocked_pending_provider_coverage"
    if quality.get("partition_malformed_count", 0) or quality.get(
        "partition_missing_count", 0
    ):
        return "blocked_pending_provider_coverage"
    if quality.get("artifact_hashes_complete") is False:
        return "blocked_pending_reconciliation"
    if not quality.get("all_tasks_completed", True):
        return "blocked_pending_provider_coverage"
    if (
        quality["primary_provider_error_count"]
        or quality.get(
            "unrecovered_rate_limit_count", quality.get("rate_limit_count", 0)
        )
        or quality.get("unrecovered_timeout_count", quality.get("timeout_count", 0))
    ):
        return "blocked_pending_provider_coverage"
    if (
        quality["duplicate_key_count"]
        or quality["null_ohlc_count"]
        or quality["non_positive_price_count"]
        or quality["high_low_violation_count"]
        or quality["amount_unit_status"] != "resolved_thousand_yuan"
        or quality["volume_unit_status"] != "resolved_lot"
    ):
        return "blocked_pending_quality_resolution"
    coverage_fields = [
        "missing_daily_count",
        "unresolved_trading_status_count",
        "unresolved_suspension_status_count",
        "unresolved_st_status_count",
        "unresolved_price_limit_status_count",
        "unresolved_adjustment_factor_count",
    ]
    if any(quality[field] for field in coverage_fields):
        return "blocked_pending_provider_coverage"
    if quality["adjusted_price_row_count"] < quality["daily_raw_row_count"]:
        return "blocked_pending_reconciliation"
    return "accepted_for_d3_candidate_generation"


def sample_acceptance_decision(quality: dict[str, Any]) -> str | None:
    if quality.get("run_mode") == "full":
        return None
    blocked = acceptance_decision({**quality, "run_mode": "full", "sample_mode": False})
    if blocked == "accepted_for_d3_candidate_generation":
        return "accepted_for_sample_candidate_generation"
    return blocked.replace("blocked_pending_", "sample_blocked_pending_", 1)


def build_fetch_stage_quality_report(
    plan: FetchPlan, evidence: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    metrics = evidence.get("_metrics", [{}])[0]
    return {
        "run_mode": plan.mode,
        "sample_mode": plan.mode != "full",
        "fetch_date_domain": plan.fetch_date_domain,
        "date_domain_source": "DR-001"
        if plan.fetch_date_domain == "calendar"
        else (
            "D2_T09_candidate_raw_market_prices"
            if plan.fetch_date_domain == "candidate"
            else "trade_cal_open"
        ),
        "candidate_price_artifact_date_domain_ignored": True,
        "fetch_stage_only": True,
        "candidate_universe_row_count": len(plan.rows),
        "mapped_row_count": sum(
            1 for row in plan.rows if row.get("mapping_status") == "resolved"
        ),
        "unmapped_row_count": sum(
            1 for row in plan.rows if row.get("mapping_status") != "resolved"
        ),
        "security_count": len({row["security_id"] for row in plan.rows}),
        "trading_date_min": min(
            (row["trading_date"] for row in plan.rows), default=None
        ),
        "trading_date_max": max(
            (row["trading_date"] for row in plan.rows), default=None
        ),
        "daily_raw_row_count": None,
        "source_status_row_count": None,
        "factor_evidence_row_count": None,
        "adjusted_price_row_count": None,
        "missing_daily_count": None,
        "missing_stk_limit_count": None,
        "missing_adj_factor_count": None,
        "missing_trade_cal_count": None,
        "missing_stock_basic_count": None,
        "missing_stock_st_count": None,
        "missing_suspend_count": None,
        "unresolved_trading_status_count": None,
        "unresolved_suspension_status_count": None,
        "unresolved_st_status_count": None,
        "unresolved_price_limit_status_count": None,
        "unresolved_adjustment_factor_count": None,
        "amount_unit_status": "not_evaluated_fetch_stage_only",
        "volume_unit_status": "not_evaluated_fetch_stage_only",
        "duplicate_key_count": None,
        "null_ohlc_count": None,
        "non_positive_price_count": None,
        "high_low_violation_count": None,
        "primary_provider_error_count": metrics.get("primary_provider_error_count", 0),
        "reconciliation_provider_error_count": metrics.get(
            "reconciliation_provider_error_count", 0
        ),
        "pro_bar_reconciliation_status": metrics.get(
            "pro_bar_reconciliation_status", "not_reached_fetch_stage_only"
        ),
        "pro_bar_reconciliation_warning_count": metrics.get(
            "pro_bar_reconciliation_warning_count", 0
        ),
        "rate_limit_count": metrics.get("rate_limit_count", 0),
        "timeout_count": metrics.get("timeout_count", 0),
        "retry_count": metrics.get("retry_count", 0),
        "request_count": metrics.get("request_count", 0),
        "successful_request_count": metrics.get("successful_request_count", 0),
        "failed_request_count": metrics.get("failed_request_count", 0),
        "all_tasks_completed": metrics.get("all_tasks_completed", False),
        "legacy_succeeded_task_count": metrics.get("legacy_succeeded_task_count", 0),
        "endpoint_task_counts": metrics.get("endpoint_task_counts", {}),
        "failed_task_counts": metrics.get("failed_task_counts", {}),
        "resume_checkpoint_count": metrics.get("resume_checkpoint_count", 0),
        "artifact_hashes_complete": False,
    }


def _partition_file(output_dir: Path, endpoint: str, suffix: str) -> Path:
    return output_dir / "partitions" / endpoint / f"{suffix}.jsonl"


def _valid_jsonl_file(path: Path) -> bool:
    try:
        _read_jsonl(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return True


def _read_partition_status(
    output_dir: Path,
    endpoint: str,
    suffix: str,
    *,
    open_dates: set[str],
    closed_dates: set[str],
) -> dict[str, Any]:
    path = _partition_file(output_dir, endpoint, suffix)
    if not path.exists():
        return {
            "endpoint": endpoint,
            "suffix": suffix,
            "path": str(path),
            "status": "partition_missing",
            "row_count": None,
            "sha256": None,
        }
    try:
        rows = _read_jsonl(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {
            "endpoint": endpoint,
            "suffix": suffix,
            "path": str(path),
            "status": "partition_malformed",
            "row_count": None,
            "sha256": None,
        }
    if not all(isinstance(row, dict) for row in rows):
        return {
            "endpoint": endpoint,
            "suffix": suffix,
            "path": str(path),
            "status": "partition_malformed",
            "row_count": None,
            "sha256": None,
        }
    row_count = len(rows)
    if row_count > 0:
        status = "succeeded_non_empty"
    elif endpoint in {"stock_st", "suspend_d"}:
        status = "allowed_empty"
    elif suffix in closed_dates:
        status = "expected_empty"
    elif suffix in open_dates and endpoint in {"daily", "stk_limit", "adj_factor"}:
        status = "unexpected_empty_primary"
    else:
        status = "provider_empty"
    return {
        "endpoint": endpoint,
        "suffix": suffix,
        "path": str(path),
        "status": status,
        "row_count": row_count,
        "sha256": _sha256_file(path),
    }


def verify_partitioned_fetch_completeness(
    plan: FetchPlan, output_dir: Path
) -> dict[str, Any]:
    expected_dates = set(plan.trade_dates)
    trade_cal_path = _partition_file(output_dir, "trade_cal", "range")
    trade_cal_rows = _read_jsonl(trade_cal_path) if trade_cal_path.exists() else []
    open_dates = {
        _date_yyyymmdd(row.get("cal_date"))
        for row in trade_cal_rows
        if str(row.get("is_open")) == "1"
    }
    closed_dates = {
        _date_yyyymmdd(row.get("cal_date"))
        for row in trade_cal_rows
        if str(row.get("is_open")) == "0"
    }
    partition_statuses: list[dict[str, Any]] = []
    endpoint_counts: dict[str, int] = {}
    endpoint_hashes: dict[str, dict[str, str]] = {}
    date_endpoints = ("daily", "stk_limit", "adj_factor", "stock_st", "suspend_d")
    for endpoint in date_endpoints:
        endpoint_hashes[endpoint] = {}
        count = 0
        for trade_date in sorted(expected_dates):
            status = _read_partition_status(
                output_dir,
                endpoint,
                trade_date,
                open_dates=open_dates,
                closed_dates=closed_dates,
            )
            partition_statuses.append(status)
            if status["status"] != "partition_missing":
                count += 1
            if status["sha256"]:
                endpoint_hashes[endpoint][trade_date] = status["sha256"]
        endpoint_counts[endpoint] = count
    missing = [
        row["path"]
        for row in partition_statuses
        if row["status"] == "partition_missing"
    ]
    malformed = [
        row["path"]
        for row in partition_statuses
        if row["status"] == "partition_malformed"
    ]
    unexpected_empty_primary = [
        row["path"]
        for row in partition_statuses
        if row["status"] == "unexpected_empty_primary"
    ]
    provider_empty = [
        row["path"] for row in partition_statuses if row["status"] == "provider_empty"
    ]
    expected_empty = [
        row["path"] for row in partition_statuses if row["status"] == "expected_empty"
    ]
    allowed_empty = [
        row["path"] for row in partition_statuses if row["status"] == "allowed_empty"
    ]
    succeeded_non_empty = [
        row["path"]
        for row in partition_statuses
        if row["status"] == "succeeded_non_empty"
    ]
    for status in ("L", "D", "P", "G"):
        path = _partition_file(output_dir, "stock_basic", status)
        if not path.exists():
            missing.append(str(path))
        elif not _valid_jsonl_file(path):
            malformed.append(str(path))
    if not trade_cal_path.exists():
        missing.append(str(trade_cal_path))
    elif not _valid_jsonl_file(trade_cal_path):
        malformed.append(str(trade_cal_path))
    fetch_decision = "complete" if not missing and not malformed else "incomplete"
    coverage_decision = (
        "complete"
        if fetch_decision == "complete" and not unexpected_empty_primary
        else "blocked_pending_provider_coverage"
    )
    return {
        "run_mode": plan.mode,
        "sample_mode": plan.mode != "full",
        "fetch_date_domain": plan.fetch_date_domain,
        "expected_trade_date_count": len(expected_dates),
        "endpoint_partition_counts": endpoint_counts,
        "partition_statuses": partition_statuses,
        "missing_partitions": missing,
        "malformed_partitions": malformed,
        "partition_missing_count": len(missing),
        "partition_malformed_count": len(malformed),
        "provider_empty_partitions": provider_empty,
        "expected_empty_partitions": expected_empty,
        "allowed_empty_partitions": allowed_empty,
        "unexpected_empty_primary_partitions": unexpected_empty_primary,
        "succeeded_non_empty_partitions": succeeded_non_empty,
        "provider_empty_count": len(provider_empty),
        "expected_empty_count": len(expected_empty),
        "allowed_empty_count": len(allowed_empty),
        "unexpected_empty_primary_partition_count": len(unexpected_empty_primary),
        "succeeded_non_empty_count": len(succeeded_non_empty),
        "partition_sha256": endpoint_hashes,
        "fetch_completeness_decision": fetch_decision,
        "provider_coverage_decision": coverage_decision,
    }


def _rows_by_date(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["trading_date"], []).append(row)
    return grouped


def _truncate_candidate_artifacts(output_dir: Path) -> None:
    for name in OUTPUT_NAMES:
        if name.endswith(".jsonl"):
            path = output_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")


def _copy_small_partition_artifacts(
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stock_basic: list[dict[str, Any]] = []
    for status in ("L", "D", "P", "G"):
        stock_basic.extend(
            _read_jsonl(_partition_file(output_dir, "stock_basic", status))
        )
    trade_cal = _read_jsonl(_partition_file(output_dir, "trade_cal", "range"))
    _write_jsonl(output_dir / "tnskhdata_stock_basic_candidate.jsonl", stock_basic)
    _write_jsonl(output_dir / "tnskhdata_trade_calendar_candidate.jsonl", trade_cal)
    return stock_basic, trade_cal


def assemble_partitioned_artifacts(
    plan: FetchPlan, output_dir: Path, verification: dict[str, Any]
) -> dict[str, Any]:
    if verification["fetch_completeness_decision"] != "complete":
        raise D2T13MaterializationError("fetch partitions incomplete")
    _truncate_candidate_artifacts(output_dir)
    stock_basic, trade_cal = _copy_small_partition_artifacts(output_dir)
    rows_by_date = _rows_by_date(plan.rows)
    source_snapshot_id = (
        f"tnskhdata_d2_t13_{plan.trade_dates[0]}_{plan.trade_dates[-1]}_full"
    )
    artifact_sha256 = hashlib.sha256(
        json.dumps(
            {
                "source_snapshot_id": source_snapshot_id,
                "row_count": len(plan.rows),
                "trade_dates": plan.trade_dates,
                "ts_code_count": len(plan.ts_codes),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    counters = {
        "candidate_universe_row_count": len(plan.rows),
        "mapped_row_count": sum(
            1 for row in plan.rows if row.get("mapping_status") == "resolved"
        ),
        "unmapped_row_count": sum(
            1 for row in plan.rows if row.get("mapping_status") != "resolved"
        ),
        "daily_raw_row_count": 0,
        "source_status_row_count": 0,
        "factor_evidence_row_count": 0,
        "adjusted_price_row_count": 0,
        "missing_daily_count": 0,
        "missing_stk_limit_count": 0,
        "missing_adj_factor_count": 0,
        "missing_trade_cal_count": 0,
        "missing_stock_basic_count": 0,
        "missing_stock_st_count": 0,
        "missing_suspend_count": 0,
        "unresolved_trading_status_count": 0,
        "unresolved_suspension_status_count": 0,
        "unresolved_st_status_count": 0,
        "unresolved_price_limit_status_count": 0,
        "unresolved_adjustment_factor_count": 0,
        "duplicate_key_count": len(plan.rows)
        - len({(row["security_id"], row["trading_date"]) for row in plan.rows}),
        "null_ohlc_count": 0,
        "non_positive_price_count": 0,
        "high_low_violation_count": 0,
        "amount_null_count": 0,
        "volume_null_count": 0,
    }
    unresolved = {"unknown", "unresolved", "provider_empty_or_unclassified", None, ""}
    for trade_date in plan.trade_dates:
        date_plan = FetchPlan(
            rows=rows_by_date.get(trade_date, []),
            ts_codes=plan.ts_codes,
            trade_dates=[trade_date],
            mode=plan.mode,
        )
        evidence = {
            "stock_basic": stock_basic,
            "trade_cal": trade_cal,
            "daily": _read_jsonl(_partition_file(output_dir, "daily", trade_date)),
            "stk_limit": _read_jsonl(
                _partition_file(output_dir, "stk_limit", trade_date)
            ),
            "adj_factor": _read_jsonl(
                _partition_file(output_dir, "adj_factor", trade_date)
            ),
            "stock_st": _read_jsonl(
                _partition_file(output_dir, "stock_st", trade_date)
            ),
            "suspend_d": _read_jsonl(
                _partition_file(output_dir, "suspend_d", trade_date)
            ),
            "_metrics": [{"primary_provider_error_count": 0, "rate_limit_count": 0}],
        }
        _append_jsonl(
            output_dir / "tnskhdata_stk_limit_candidate.jsonl", evidence["stk_limit"]
        )
        _append_jsonl(
            output_dir / "tnskhdata_adj_factor_candidate.jsonl", evidence["adj_factor"]
        )
        _append_jsonl(
            output_dir / "tnskhdata_stock_st_candidate.jsonl", evidence["stock_st"]
        )
        _append_jsonl(
            output_dir / "tnskhdata_suspend_candidate.jsonl", evidence["suspend_d"]
        )
        outputs = build_candidate_outputs(
            date_plan,
            evidence,
            source_snapshot_id=source_snapshot_id,
            artifact_sha256=artifact_sha256,
        )
        _append_jsonl(
            output_dir / "tnskhdata_daily_raw_candidate.jsonl", outputs["raw"]
        )
        _append_jsonl(
            output_dir / "tnskhdata_source_status_candidate.jsonl",
            outputs["source_status"],
        )
        _append_jsonl(
            output_dir / "tnskhdata_factor_evidence_candidate.jsonl",
            outputs["factor_evidence"],
        )
        _append_jsonl(
            output_dir / "tnskhdata_adjusted_price_candidate.jsonl",
            outputs["adjusted_price"],
        )
        counters["daily_raw_row_count"] += len(outputs["raw"])
        counters["source_status_row_count"] += len(outputs["source_status"])
        counters["factor_evidence_row_count"] += len(outputs["factor_evidence"])
        counters["adjusted_price_row_count"] += len(outputs["adjusted_price"])
        counters["missing_daily_count"] += len(date_plan.rows) - len(outputs["raw"])
        counters["missing_adj_factor_count"] += sum(
            1
            for row in outputs["factor_evidence"]
            if row["adjustment_factor_status"] != "resolved"
        )
        counters["missing_trade_cal_count"] += (
            0
            if any(
                _date_yyyymmdd(row.get("cal_date")) == trade_date for row in trade_cal
            )
            else 1
        )
        counters["unresolved_trading_status_count"] += sum(
            1 for row in outputs["source_status"] if row["trading_status"] in unresolved
        )
        counters["unresolved_suspension_status_count"] += sum(
            1
            for row in outputs["source_status"]
            if row["suspension_status"] in unresolved
        )
        counters["unresolved_st_status_count"] += sum(
            1 for row in outputs["source_status"] if row["st_status"] in unresolved
        )
        counters["unresolved_price_limit_status_count"] += sum(
            1
            for row in outputs["source_status"]
            if row["price_limit_status"] in unresolved
        )
        counters["unresolved_adjustment_factor_count"] += sum(
            1
            for row in outputs["factor_evidence"]
            if row["adjustment_factor_status"] != "resolved"
        )
        for row in outputs["raw"]:
            if any(
                row.get(field) is None
                for field in ("raw_open", "raw_high", "raw_low", "raw_close")
            ):
                counters["null_ohlc_count"] += 1
            if any(
                (row.get(field) or 0) <= 0
                for field in ("raw_open", "raw_high", "raw_low", "raw_close")
            ):
                counters["non_positive_price_count"] += 1
            if (
                row.get("raw_high") is not None
                and row.get("raw_low") is not None
                and row["raw_high"] < row["raw_low"]
            ):
                counters["high_low_violation_count"] += 1
            if row.get("amount_thousand_yuan") is None:
                counters["amount_null_count"] += 1
            if row.get("volume_lot") is None:
                counters["volume_null_count"] += 1
    return {
        "run_mode": plan.mode,
        "sample_mode": plan.mode != "full",
        "fetch_date_domain": plan.fetch_date_domain,
        "date_domain_source": "DR-001"
        if plan.fetch_date_domain == "calendar"
        else (
            "D2_T09_candidate_raw_market_prices"
            if plan.fetch_date_domain == "candidate"
            else "trade_cal_open"
        ),
        "candidate_price_artifact_date_domain_ignored": True,
        "fetch_stage_only": False,
        "fetch_completeness_decision": verification["fetch_completeness_decision"],
        "provider_coverage_decision": verification["provider_coverage_decision"],
        "unexpected_empty_primary_partition_count": verification[
            "unexpected_empty_primary_partition_count"
        ],
        "partition_malformed_count": verification["partition_malformed_count"],
        "partition_missing_count": verification["partition_missing_count"],
        "all_tasks_completed": verification["fetch_completeness_decision"]
        == "complete",
        "artifact_hashes_complete": False,
        "security_count": len({row["security_id"] for row in plan.rows}),
        "trading_date_min": min(plan.trade_dates, default=None),
        "trading_date_max": max(plan.trade_dates, default=None),
        "amount_unit_status": "unknown"
        if counters["amount_null_count"]
        else "resolved_thousand_yuan",
        "volume_unit_status": "unknown"
        if counters["volume_null_count"]
        else "resolved_lot",
        "primary_provider_error_count": 0,
        "historical_rate_limit_count": 0,
        "unrecovered_rate_limit_count": 0,
        "historical_timeout_count": 0,
        "unrecovered_timeout_count": 0,
        "rate_limit_count": 0,
        "timeout_count": 0,
        **counters,
    }


def finalize_partitioned_reports(
    plan: FetchPlan,
    output_dir: Path,
    verification: dict[str, Any],
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if quality is None:
        quality_path = output_dir / "tnskhdata_quality_report.json"
        if (
            quality_path.exists()
            and verification["fetch_completeness_decision"] == "complete"
        ):
            quality = _load_json(quality_path)
        else:
            quality = {
                "run_mode": plan.mode,
                "sample_mode": plan.mode != "full",
                "fetch_date_domain": plan.fetch_date_domain,
                "date_domain_source": "DR-001"
                if plan.fetch_date_domain == "calendar"
                else (
                    "D2_T09_candidate_raw_market_prices"
                    if plan.fetch_date_domain == "candidate"
                    else "trade_cal_open"
                ),
                "candidate_price_artifact_date_domain_ignored": True,
                "fetch_stage_only": False,
                "fetch_completeness_decision": verification[
                    "fetch_completeness_decision"
                ],
                "provider_coverage_decision": verification[
                    "provider_coverage_decision"
                ],
                "unexpected_empty_primary_partition_count": verification[
                    "unexpected_empty_primary_partition_count"
                ],
                "partition_malformed_count": verification["partition_malformed_count"],
                "partition_missing_count": verification["partition_missing_count"],
                "all_tasks_completed": False,
                "artifact_hashes_complete": False,
                "candidate_universe_row_count": len(plan.rows),
                "mapped_row_count": sum(
                    1 for row in plan.rows if row.get("mapping_status") == "resolved"
                ),
                "unmapped_row_count": sum(
                    1 for row in plan.rows if row.get("mapping_status") != "resolved"
                ),
                "daily_raw_row_count": None,
                "source_status_row_count": None,
                "factor_evidence_row_count": None,
                "adjusted_price_row_count": None,
                "security_count": len({row["security_id"] for row in plan.rows}),
                "trading_date_min": min(plan.trade_dates, default=None),
                "trading_date_max": max(plan.trade_dates, default=None),
                "missing_daily_count": None,
                "unresolved_trading_status_count": None,
                "unresolved_suspension_status_count": None,
                "unresolved_st_status_count": None,
                "unresolved_price_limit_status_count": None,
                "unresolved_adjustment_factor_count": None,
                "amount_unit_status": "not_evaluated_fetch_incomplete",
                "volume_unit_status": "not_evaluated_fetch_incomplete",
                "duplicate_key_count": None,
                "null_ohlc_count": None,
                "non_positive_price_count": None,
                "high_low_violation_count": None,
                "primary_provider_error_count": 0,
                "historical_rate_limit_count": 0,
                "unrecovered_rate_limit_count": 0,
                "historical_timeout_count": 0,
                "unrecovered_timeout_count": 0,
                "rate_limit_count": 0,
                "timeout_count": 0,
            }
    quality.update(
        {
            "fetch_date_domain": plan.fetch_date_domain,
            "date_domain_source": "DR-001"
            if plan.fetch_date_domain == "calendar"
            else (
                "D2_T09_candidate_raw_market_prices"
                if plan.fetch_date_domain == "candidate"
                else "trade_cal_open"
            ),
            "candidate_price_artifact_date_domain_ignored": True,
            "fetch_completeness_decision": verification["fetch_completeness_decision"],
            "provider_coverage_decision": verification["provider_coverage_decision"],
            "unexpected_empty_primary_partition_count": verification[
                "unexpected_empty_primary_partition_count"
            ],
            "partition_malformed_count": verification["partition_malformed_count"],
            "partition_missing_count": verification["partition_missing_count"],
            "all_tasks_completed": verification["fetch_completeness_decision"]
            == "complete",
        }
    )
    if quality.get("daily_raw_row_count") is None:
        quality["primary_provider_error_count"] = 0
    _write_json(output_dir / "tnskhdata_fetch_verification_report.json", verification)
    source_snapshot_id = (
        f"tnskhdata_d2_t13_{plan.trade_dates[0]}_{plan.trade_dates[-1]}_full"
    )
    _write_json(
        output_dir / "tnskhdata_reconciliation_report.json",
        {
            "pro_bar_usage": "reconciliation_only",
            "pro_bar_reconciliation_status": "not_requested_finalize_only",
            "source_snapshot_id": source_snapshot_id,
        },
    )
    pre_decision_expected = {
        name
        for name in OUTPUT_NAMES
        if name
        not in {
            "tnskhdata_candidate_file_hash_summary.json",
            "tnskhdata_d2_acceptance_candidate_report.json",
            "tnskhdata_d3_handoff_candidate_report.json",
        }
    }
    quality["artifact_hashes_complete"] = (
        verification["fetch_completeness_decision"] == "complete"
        and quality.get("daily_raw_row_count") is not None
        and all((output_dir / name).exists() for name in pre_decision_expected)
    )
    if quality.get("daily_raw_row_count") is None:
        quality["amount_unit_status"] = "not_evaluated_assembly_not_run"
        quality["volume_unit_status"] = "not_evaluated_assembly_not_run"
    decision = acceptance_decision(
        {
            **quality,
            "rate_limit_count": quality.get("unrecovered_rate_limit_count", 0),
            "timeout_count": quality.get("unrecovered_timeout_count", 0),
        }
    )
    d3_decision = (
        "d3_candidate_generation_allowed"
        if decision == "accepted_for_d3_candidate_generation"
        else "d3_candidate_generation_blocked"
    )
    _write_json(output_dir / "tnskhdata_quality_report.json", quality)
    _write_json(
        output_dir / "tnskhdata_d2_acceptance_candidate_report.json",
        {
            "run_id": source_snapshot_id,
            "run_mode": "full",
            "sample_mode": False,
            "d2_acceptance_decision": decision,
            "quality_blockers": [
                key
                for key in (
                    "fetch_completeness_decision",
                    "provider_coverage_decision",
                    "unexpected_empty_primary_partition_count",
                    "partition_malformed_count",
                    "partition_missing_count",
                    "unmapped_row_count",
                    "missing_daily_count",
                    "unresolved_trading_status_count",
                    "unresolved_suspension_status_count",
                    "unresolved_st_status_count",
                    "unresolved_price_limit_status_count",
                    "unresolved_adjustment_factor_count",
                    "duplicate_key_count",
                    "null_ohlc_count",
                    "non_positive_price_count",
                    "high_low_violation_count",
                    "unrecovered_rate_limit_count",
                    "unrecovered_timeout_count",
                )
                if quality.get(key)
                and quality.get(key)
                not in {"complete", "resolved_thousand_yuan", "resolved_lot"}
            ],
            "duckdb_written": False,
            "formal_duckdb_write_authorized": False,
            "data_version_published": False,
            "d3_generation_authorized": False,
            "r0_state_generation_authorized": False,
        },
    )
    _write_json(
        output_dir / "tnskhdata_d3_handoff_candidate_report.json",
        {
            "d3_handoff_decision": d3_decision,
            "d3_generation_authorized": False,
            "d3_rows_generated": False,
            "r0_state_generation_authorized": False,
            "r0_state_generated": False,
        },
    )
    hash_summary = {
        name: {
            "sha256": _sha256_file(output_dir / name),
            "size_bytes": (output_dir / name).stat().st_size,
        }
        for name in OUTPUT_NAMES
        if name != "tnskhdata_candidate_file_hash_summary.json"
        and (output_dir / name).exists()
    }
    _write_json(output_dir / "tnskhdata_candidate_file_hash_summary.json", hash_summary)
    return {
        "d2_acceptance_decision": decision,
        "d3_handoff_decision": d3_decision,
        "quality_report": quality,
        "artifact_hashes": hash_summary,
    }


def materialize_full_candidate(
    *,
    contract: dict[str, Any],
    output_dir: Path,
    start_date: str,
    end_date: str,
    enable_remote_fetch: bool,
    security_universe: Path | None = None,
    candidate_universe: Path | None = None,
    candidate_price_artifact: Path | None = None,
    env_file: Path | None = None,
    client: Any | None = None,
    full: bool = False,
    sample_securities: int | None = None,
    sample_dates_per_security: int | None = None,
    resume: bool = False,
    checkpoint_dir: Path | None = None,
    staging_store: Path | None = None,
    staging_format: str = "partitioned-jsonl",
    flush_interval_seconds: int = 60,
    worker_mode: str = "serial",
    max_workers: int = 7,
    initial_requests_per_minute: int = 200,
    max_requests_per_minute: int = 500,
    rate_increase_per_minute: int = 100,
    rate_decrease_factor: float = 0.5,
    requests_per_minute: int = 200,
    pro_bar_requests_per_minute: int = 60,
    retry_max_attempts: int = 3,
    retry_backoff_seconds: float = 5.0,
    request_timeout_seconds: int = 60,
    pro_bar_sample_securities: int = 20,
    require_pro_bar_reconciliation: bool = False,
    repair_failed_only: bool = False,
    verify_fetch_only: bool = False,
    assemble_only: bool = False,
    finalize_only: bool = False,
    no_remote_fetch: bool = False,
    fetch_date_domain: str = "calendar",
) -> dict[str, Any]:
    started = time.time()
    if (
        contract.get("contract_id")
        != "D2_TNSKHDATA_FULL_MATERIALIZATION_ACCEPTANCE_CONTRACT_V1"
    ):
        raise D2T13MaterializationError("wrong D2-T13 contract")
    if contract.get("primary_source") != "tnskhdata":
        raise D2T13MaterializationError("primary_source must be tnskhdata")
    for flag in (
        "duckdb_write_authorized",
        "formal_duckdb_write_authorized",
        "d3_generation_authorized",
        "r0_state_generation_authorized",
    ):
        if contract.get(flag) is not False:
            raise D2T13MaterializationError(f"{flag} must remain false")
    if contract.get("local_staging_write_authorized") is not True:
        raise D2T13MaterializationError("local staging write must be authorized")
    local_only_mode = (
        verify_fetch_only or assemble_only or finalize_only or no_remote_fetch
    )
    if not enable_remote_fetch and client is None and not local_only_mode:
        raise D2T13MaterializationError(
            "remote fetch must be enabled unless fake client is injected"
        )
    _guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if resume and checkpoint_dir:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    effective_security_universe = security_universe or candidate_universe
    if effective_security_universe is None:
        effective_security_universe = DEFAULT_SECURITY_UNIVERSE
    diagnostic_candidate = candidate_price_artifact or (
        candidate_universe
        if candidate_universe != effective_security_universe
        else None
    )
    date_domain_audit = build_date_domain_audit_report(
        contract=contract,
        security_universe_path=effective_security_universe,
        candidate_price_artifact=diagnostic_candidate,
        fetch_date_domain=fetch_date_domain,
    )
    _write_json(
        output_dir / "tnskhdata_date_domain_audit_report.json", date_domain_audit
    )
    rows = _load_security_universe(effective_security_universe)
    trade_cal_open_dates = None
    if fetch_date_domain == "trade-cal-open":
        trade_cal_path = _partition_file(output_dir, "trade_cal", "range")
        if not trade_cal_path.exists():
            raise D2T13MaterializationError(
                "trade-cal-open fetch_date_domain requires pre-fetched trade_cal"
            )
        trade_cal_open_dates = [
            _date_yyyymmdd(row.get("cal_date"))
            for row in _read_jsonl(trade_cal_path)
            if str(row.get("is_open")) == "1"
        ]
    plan = build_fetch_plan(
        rows,
        full=full,
        sample_securities=sample_securities,
        sample_dates_per_security=sample_dates_per_security,
        start_date=start_date,
        end_date=end_date,
        fetch_date_domain=fetch_date_domain,
        trade_cal_open_dates=trade_cal_open_dates,
    )
    if no_remote_fetch or verify_fetch_only or assemble_only or finalize_only:
        verification = verify_partitioned_fetch_completeness(plan, output_dir)
        verification["date_domain_audit_report"] = date_domain_audit
        _write_json(
            output_dir / "tnskhdata_fetch_verification_report.json", verification
        )
        quality = None
        if assemble_only and verification["fetch_completeness_decision"] == "complete":
            quality = assemble_partitioned_artifacts(plan, output_dir, verification)
            _write_json(output_dir / "tnskhdata_quality_report.json", quality)
        finalized = None
        if finalize_only:
            finalized = finalize_partitioned_reports(
                plan, output_dir, verification, quality
            )
        decision = (
            finalized["d2_acceptance_decision"]
            if finalized
            else "blocked_pending_provider_coverage"
            if verification["fetch_completeness_decision"] != "complete"
            or verification["provider_coverage_decision"] != "complete"
            else "blocked_pending_reconciliation"
        )
        d3_decision = (
            finalized["d3_handoff_decision"]
            if finalized
            else "d3_candidate_generation_blocked"
        )
        source_snapshot_id = f"tnskhdata_d2_t13_{start_date}_{end_date}_{plan.mode}"
        return {
            "run_id": source_snapshot_id,
            "source_snapshot_id": source_snapshot_id,
            "run_mode": plan.mode,
            "sample_mode": plan.mode != "full",
            "sample_acceptance_decision": None,
            "d2_acceptance_decision": decision,
            "d3_handoff_decision": d3_decision,
            "r0_handoff_decision": "r0_blocked",
            "quality_report": finalized["quality_report"] if finalized else quality,
            "fetch_verification_report": verification,
            "date_domain_audit_report": date_domain_audit,
            "artifact_hashes": finalized["artifact_hashes"] if finalized else {},
            "duckdb_written": False,
            "data_version_published": False,
            "d3_rows_generated": False,
            "pcvt_values_generated": False,
            "r0_state_generated": False,
        }
    if client is None:
        token = load_tnskhdata_token(env_file, allow_tushare_fallback=True)
        client = _client_from_token(token)
    if staging_format not in {"partitioned-jsonl", "duckdb"}:
        raise D2T13MaterializationError("unsupported staging format")
    if full and worker_mode == "endpoint":
        evidence = fetch_provider_evidence_parallel(
            client,
            plan,
            output_dir=output_dir if staging_store is None else staging_store.parent,
            checkpoint_dir=checkpoint_dir,
            resume=resume,
            max_workers=max_workers,
            initial_requests_per_minute=initial_requests_per_minute,
            max_requests_per_minute=max_requests_per_minute,
            rate_increase_per_minute=rate_increase_per_minute,
            rate_decrease_factor=rate_decrease_factor,
            retry_max_attempts=retry_max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            flush_interval_seconds=flush_interval_seconds,
            repair_failed_only=repair_failed_only,
        )
    else:
        evidence = fetch_provider_evidence(
            client,
            plan,
            requests_per_minute=requests_per_minute,
            pro_bar_requests_per_minute=pro_bar_requests_per_minute,
            retry_max_attempts=retry_max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            throttle_enabled=enable_remote_fetch and client is not None,
            resume=resume,
            checkpoint_dir=checkpoint_dir,
        )
    if full and worker_mode == "endpoint":
        quality = build_fetch_stage_quality_report(plan, evidence)
        quality["elapsed_seconds"] = round(time.time() - started, 3)
        quality["staging_store_type"] = staging_format
        quality["staging_store_path_redacted"] = (
            "data/generated/d2/d2_t13_tnskhdata_full_candidate/**"
            if staging_store
            else None
        )
        quality["worker_mode"] = worker_mode
        quality["max_workers"] = max_workers
        quality["initial_requests_per_minute"] = initial_requests_per_minute
        quality["max_requests_per_minute"] = max_requests_per_minute
        quality["request_timeout_seconds"] = request_timeout_seconds
        quality["repair_failed_only"] = repair_failed_only
        source_snapshot_id = f"tnskhdata_d2_t13_{start_date}_{end_date}_{plan.mode}"
        decision = "blocked_pending_tnskhdata_full_materialization_run"
        if quality["failed_request_count"]:
            decision = "blocked_pending_provider_coverage"
        d3_decision = "d3_candidate_generation_blocked"
        d2_report = {
            "run_id": source_snapshot_id,
            "source_snapshot_id": source_snapshot_id,
            "run_mode": plan.mode,
            "sample_mode": False,
            "sample_acceptance_decision": None,
            "d2_acceptance_decision": decision,
            "quality_blockers": ["full_artifact_assembly_not_complete"],
            "duckdb_written": False,
            "formal_duckdb_write_authorized": False,
            "local_staging_write_authorized": True,
            "data_version_published": False,
            "d3_generation_authorized": False,
            "r0_state_generation_authorized": False,
        }
        d3_report = {
            "d3_handoff_decision": d3_decision,
            "d3_generation_authorized": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }
        _write_json(output_dir / "tnskhdata_quality_report.json", quality)
        _write_json(
            output_dir / "tnskhdata_d2_acceptance_candidate_report.json", d2_report
        )
        _write_json(
            output_dir / "tnskhdata_d3_handoff_candidate_report.json", d3_report
        )
        return {
            "run_id": source_snapshot_id,
            "source_snapshot_id": source_snapshot_id,
            "run_mode": plan.mode,
            "sample_mode": False,
            "sample_acceptance_decision": None,
            "d2_acceptance_decision": decision,
            "d3_handoff_decision": d3_decision,
            "r0_handoff_decision": "r0_blocked",
            "quality_report": quality,
            "artifact_hashes": {},
            "duckdb_written": False,
            "data_version_published": False,
            "d3_rows_generated": False,
            "pcvt_values_generated": False,
            "r0_state_generated": False,
        }
    source_snapshot_id = f"tnskhdata_d2_t13_{start_date}_{end_date}_{plan.mode}"
    artifact_sha256 = hashlib.sha256(
        json.dumps(
            {
                "source_snapshot_id": source_snapshot_id,
                "row_count": len(plan.rows),
                "trade_dates": plan.trade_dates,
                "ts_code_count": len(plan.ts_codes),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    outputs = build_candidate_outputs(
        plan,
        evidence,
        source_snapshot_id=source_snapshot_id,
        artifact_sha256=artifact_sha256,
    )
    write_sets = {
        "tnskhdata_stock_basic_candidate.jsonl": evidence["stock_basic"],
        "tnskhdata_trade_calendar_candidate.jsonl": evidence["trade_cal"],
        "tnskhdata_daily_raw_candidate.jsonl": outputs["raw"],
        "tnskhdata_stk_limit_candidate.jsonl": evidence["stk_limit"],
        "tnskhdata_adj_factor_candidate.jsonl": evidence["adj_factor"],
        "tnskhdata_stock_st_candidate.jsonl": evidence["stock_st"],
        "tnskhdata_suspend_candidate.jsonl": evidence["suspend_d"],
        "tnskhdata_source_status_candidate.jsonl": outputs["source_status"],
        "tnskhdata_factor_evidence_candidate.jsonl": outputs["factor_evidence"],
        "tnskhdata_adjusted_price_candidate.jsonl": outputs["adjusted_price"],
    }
    for name, payload in write_sets.items():
        _write_jsonl(output_dir / name, payload)
    quality = build_quality_report(plan, outputs, evidence)
    sample_decision = sample_acceptance_decision(quality)
    decision = acceptance_decision(quality)
    d3_decision = (
        "d3_candidate_generation_allowed"
        if decision == "accepted_for_d3_candidate_generation"
        else "d3_candidate_generation_blocked"
    )
    quality["elapsed_seconds"] = round(time.time() - started, 3)
    quality["request_count"] = evidence.get("_metrics", [{}])[0].get("request_count", 0)
    quality["staging_store_type"] = staging_format
    quality["staging_store_path_redacted"] = (
        "data/generated/d2/d2_t13_tnskhdata_full_candidate/**"
        if staging_store
        else None
    )
    quality["worker_mode"] = worker_mode
    quality["max_workers"] = max_workers
    quality["initial_requests_per_minute"] = initial_requests_per_minute
    quality["max_requests_per_minute"] = max_requests_per_minute
    quality["request_timeout_seconds"] = request_timeout_seconds
    quality["pro_bar_sample_securities"] = pro_bar_sample_securities
    quality["require_pro_bar_reconciliation"] = require_pro_bar_reconciliation
    reconciliation = {
        "daily_raw_source": "tnskhdata daily",
        "adjustment_factor_source": "tnskhdata adj_factor",
        "hfq_formula": "raw_price * adj_factor",
        "qfq_formula": "raw_price * adj_factor / anchor_adj_factor",
        "qfq_anchor_policy": "explicit_end_date_anchor",
        "pro_bar_usage": "reconciliation_only",
        "pro_bar_reconciliation_status": quality["pro_bar_reconciliation_status"],
        "pro_bar_reconciliation_warning_count": quality[
            "pro_bar_reconciliation_warning_count"
        ],
        "amount_unit": "thousand_yuan",
        "volume_unit": "lot",
        "source_snapshot_id": source_snapshot_id,
        "artifact_sha256": artifact_sha256,
    }
    d2_report = {
        "run_id": source_snapshot_id,
        "source_snapshot_id": source_snapshot_id,
        "artifact_sha256": artifact_sha256,
        "run_mode": plan.mode,
        "sample_mode": plan.mode != "full",
        "sample_acceptance_decision": sample_decision,
        "d2_acceptance_decision": decision,
        "quality_blockers": [
            key
            for key in (
                "unmapped_row_count",
                "provider_coverage_decision",
                "unexpected_empty_primary_partition_count",
                "partition_malformed_count",
                "partition_missing_count",
                "missing_daily_count",
                "unresolved_trading_status_count",
                "unresolved_suspension_status_count",
                "unresolved_st_status_count",
                "unresolved_price_limit_status_count",
                "unresolved_adjustment_factor_count",
                "duplicate_key_count",
                "null_ohlc_count",
                "non_positive_price_count",
                "high_low_violation_count",
                "primary_provider_error_count",
                "rate_limit_count",
            )
            if quality.get(key)
        ],
        "duckdb_written": False,
        "formal_duckdb_write_authorized": False,
        "local_staging_write_authorized": True,
        "data_version_published": False,
        "d3_generation_authorized": False,
        "r0_state_generation_authorized": False,
    }
    d3_report = {
        "d3_handoff_decision": d3_decision,
        "d3_generation_authorized": False,
        "d3_rows_generated": False,
        "r0_state_generated": False,
    }
    _write_json(output_dir / "tnskhdata_quality_report.json", quality)
    _write_json(output_dir / "tnskhdata_reconciliation_report.json", reconciliation)
    _write_json(output_dir / "tnskhdata_d2_acceptance_candidate_report.json", d2_report)
    _write_json(output_dir / "tnskhdata_d3_handoff_candidate_report.json", d3_report)
    _write_json(
        output_dir / "tnskhdata_fetch_verification_report.json",
        {
            "verification_mode": "execution_metrics",
            "fetch_completeness_decision": "complete"
            if quality.get("all_tasks_completed", True)
            else "incomplete",
            "provider_coverage_decision": "complete"
            if quality.get("all_tasks_completed", True)
            else "blocked_pending_provider_coverage",
            "date_domain_audit_report": date_domain_audit,
            "expected_trade_date_count": len(plan.trade_dates),
            "expected_date_endpoint_partition_count": len(plan.trade_dates) * 5,
            "partition_missing_count": 0,
            "partition_malformed_count": 0,
            "unexpected_empty_primary_partition_count": 0,
            "provider_empty_count": 0,
            "expected_empty_count": 0,
            "allowed_empty_count": 0,
            "endpoint_partition_counts": quality.get("endpoint_task_counts", {}),
            "all_tasks_completed": quality.get("all_tasks_completed", True),
            "failed_task_counts": quality.get("failed_task_counts", {}),
            "notes": [
                "Report derived from current execution metrics; partition-only "
                "verification is produced by --verify-fetch-only."
            ],
        },
    )
    hash_summary = {
        name: {
            "sha256": _sha256_file(output_dir / name),
            "size_bytes": (output_dir / name).stat().st_size,
        }
        for name in OUTPUT_NAMES
        if name != "tnskhdata_candidate_file_hash_summary.json"
    }
    _write_json(output_dir / "tnskhdata_candidate_file_hash_summary.json", hash_summary)
    return {
        "run_id": source_snapshot_id,
        "source_snapshot_id": source_snapshot_id,
        "run_mode": plan.mode,
        "sample_mode": plan.mode != "full",
        "sample_acceptance_decision": sample_decision,
        "d2_acceptance_decision": decision,
        "d3_handoff_decision": d3_decision,
        "r0_handoff_decision": "r0_blocked",
        "quality_report": quality,
        "artifact_hashes": hash_summary,
        "date_domain_audit_report": date_domain_audit,
        "duckdb_written": False,
        "data_version_published": False,
        "d3_rows_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument(
        "--security-universe", default=DEFAULT_SECURITY_UNIVERSE, type=Path
    )
    parser.add_argument("--candidate-universe", type=Path)
    parser.add_argument("--candidate-price-artifact", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument("--enable-remote-fetch", action="store_true")
    parser.add_argument("--no-remote-fetch", action="store_true")
    parser.add_argument("--verify-fetch-only", action="store_true")
    parser.add_argument("--assemble-only", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument(
        "--fetch-date-domain",
        default="calendar",
        choices=("calendar", "candidate", "trade-cal-open"),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--repair-failed-only", action="store_true")
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--staging-store", type=Path)
    parser.add_argument(
        "--staging-format",
        default="partitioned-jsonl",
        choices=("partitioned-jsonl", "duckdb"),
    )
    parser.add_argument("--flush-interval-seconds", default=60, type=int)
    parser.add_argument(
        "--worker-mode", default="serial", choices=("serial", "endpoint")
    )
    parser.add_argument("--max-workers", default=7, type=int)
    parser.add_argument("--sample-securities", type=int)
    parser.add_argument("--sample-dates-per-security", type=int)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--initial-requests-per-minute", default=200, type=int)
    parser.add_argument("--max-requests-per-minute", default=500, type=int)
    parser.add_argument("--rate-increase-per-minute", default=100, type=int)
    parser.add_argument("--rate-decrease-factor", default=0.5, type=float)
    parser.add_argument("--requests-per-minute", default=200, type=int)
    parser.add_argument("--pro-bar-requests-per-minute", default=60, type=int)
    parser.add_argument("--retry-max-attempts", default=5, type=int)
    parser.add_argument("--retry-backoff-seconds", default=10.0, type=float)
    parser.add_argument("--request-timeout-seconds", default=60, type=int)
    parser.add_argument("--pro-bar-sample-securities", default=20, type=int)
    parser.add_argument("--require-pro-bar-reconciliation", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = materialize_full_candidate(
        contract=_load_json(args.contract),
        security_universe=args.security_universe,
        candidate_universe=args.candidate_universe,
        candidate_price_artifact=args.candidate_price_artifact,
        env_file=args.env_file,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        enable_remote_fetch=args.enable_remote_fetch,
        full=args.full,
        sample_securities=args.sample_securities,
        sample_dates_per_security=args.sample_dates_per_security,
        resume=args.resume,
        checkpoint_dir=args.checkpoint_dir,
        staging_store=args.staging_store,
        staging_format=args.staging_format,
        flush_interval_seconds=args.flush_interval_seconds,
        worker_mode=args.worker_mode,
        max_workers=args.max_workers,
        initial_requests_per_minute=args.initial_requests_per_minute,
        max_requests_per_minute=args.max_requests_per_minute,
        rate_increase_per_minute=args.rate_increase_per_minute,
        rate_decrease_factor=args.rate_decrease_factor,
        requests_per_minute=args.requests_per_minute,
        pro_bar_requests_per_minute=args.pro_bar_requests_per_minute,
        retry_max_attempts=args.retry_max_attempts,
        retry_backoff_seconds=args.retry_backoff_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        pro_bar_sample_securities=args.pro_bar_sample_securities,
        require_pro_bar_reconciliation=args.require_pro_bar_reconciliation,
        repair_failed_only=args.repair_failed_only,
        verify_fetch_only=args.verify_fetch_only,
        assemble_only=args.assemble_only,
        finalize_only=args.finalize_only,
        no_remote_fetch=args.no_remote_fetch,
        fetch_date_domain=args.fetch_date_domain,
    )
    redacted = {
        "run_id": report["run_id"],
        "source_snapshot_id": report["source_snapshot_id"],
        "run_mode": report["run_mode"],
        "sample_mode": report["sample_mode"],
        "sample_acceptance_decision": report["sample_acceptance_decision"],
        "d2_acceptance_decision": report["d2_acceptance_decision"],
        "d3_handoff_decision": report["d3_handoff_decision"],
        "r0_handoff_decision": report["r0_handoff_decision"],
        "quality_report": report["quality_report"],
    }
    print(json.dumps(redacted, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
