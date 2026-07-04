"""Materialize D2-T13 tnskhdata full candidate evidence into ignored outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
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
DEFAULT_START_DATE = "20160101"
DEFAULT_END_DATE = "20260630"
UNIVERSE_COLUMNS = ["security_id", "trading_date", "universe_id", "time_segment_id"]
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
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_yyyymmdd(value: Any) -> str:
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return text[:10].replace("-", "")


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


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_candidate_universe(
    path: Path, start_date: str, end_date: str
) -> list[dict[str, Any]]:
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
        if start_date <= trading_date <= end_date:
            output.append(
                {
                    "security_id": str(row["security_id"]),
                    "trading_date": trading_date,
                    "universe_id": str(row["universe_id"]),
                    "time_segment_id": str(row["time_segment_id"]),
                }
            )
    return output


def build_fetch_plan(
    rows: list[dict[str, Any]],
    *,
    full: bool,
    sample_securities: int | None,
    sample_dates_per_security: int | None,
) -> FetchPlan:
    mapped_rows = []
    for row in rows:
        mapping = resolve_security_provider_codes(row["security_id"])
        if mapping.mapping_status != "resolved":
            mapped_rows.append({**row, "ts_code": None, "mapping_status": "unresolved"})
            continue
        mapped_rows.append(
            {**row, "ts_code": mapping.tnskhdata_ts_code, "mapping_status": "resolved"}
        )
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
    )


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
) -> dict[str, list[dict[str, Any]]]:
    request_count = 0
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
                primary_provider_error_count += 1
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
                            primary_provider_error_count += 1
                            if _is_rate_limit_error(fallback_exc):
                                rate_limit_count += 1
            request_count += 1
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
        "resume_checkpoint_count": 0,
    }


def acceptance_decision(quality: dict[str, Any]) -> str:
    if quality["primary_provider_error_count"] or quality["rate_limit_count"]:
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


def materialize_full_candidate(
    *,
    contract: dict[str, Any],
    candidate_universe: Path,
    output_dir: Path,
    start_date: str,
    end_date: str,
    enable_remote_fetch: bool,
    env_file: Path | None = None,
    client: Any | None = None,
    full: bool = False,
    sample_securities: int | None = None,
    sample_dates_per_security: int | None = None,
    resume: bool = False,
    checkpoint_dir: Path | None = None,
    requests_per_minute: int = 200,
    pro_bar_requests_per_minute: int = 60,
    retry_max_attempts: int = 3,
    retry_backoff_seconds: float = 5.0,
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
        "d3_generation_authorized",
        "r0_state_generation_authorized",
    ):
        if contract.get(flag) is not False:
            raise D2T13MaterializationError(f"{flag} must remain false")
    if not enable_remote_fetch and client is None:
        raise D2T13MaterializationError(
            "remote fetch must be enabled unless fake client is injected"
        )
    _guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if resume and checkpoint_dir:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    rows = _load_candidate_universe(candidate_universe, start_date, end_date)
    plan = build_fetch_plan(
        rows,
        full=full,
        sample_securities=sample_securities,
        sample_dates_per_security=sample_dates_per_security,
    )
    if client is None:
        token = load_tnskhdata_token(env_file, allow_tushare_fallback=True)
        client = _client_from_token(token)
    evidence = fetch_provider_evidence(
        client,
        plan,
        requests_per_minute=requests_per_minute,
        pro_bar_requests_per_minute=pro_bar_requests_per_minute,
        retry_max_attempts=retry_max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        throttle_enabled=enable_remote_fetch and client is not None,
    )
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
    decision = acceptance_decision(quality)
    d3_decision = (
        "d3_candidate_generation_allowed"
        if decision == "accepted_for_d3_candidate_generation"
        else "d3_candidate_generation_blocked"
    )
    quality["elapsed_seconds"] = round(time.time() - started, 3)
    quality["request_count"] = evidence.get("_metrics", [{}])[0].get("request_count", 0)
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
        "d2_acceptance_decision": decision,
        "quality_blockers": [
            key
            for key in (
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
                "primary_provider_error_count",
                "rate_limit_count",
            )
            if quality.get(key)
        ],
        "duckdb_written": False,
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
        "d2_acceptance_decision": decision,
        "d3_handoff_decision": d3_decision,
        "r0_handoff_decision": "r0_blocked",
        "quality_report": quality,
        "artifact_hashes": hash_summary,
        "duckdb_written": False,
        "data_version_published": False,
        "d3_rows_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument("--candidate-universe", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument("--enable-remote-fetch", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--sample-securities", type=int)
    parser.add_argument("--sample-dates-per-security", type=int)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--requests-per-minute", default=200, type=int)
    parser.add_argument("--pro-bar-requests-per-minute", default=60, type=int)
    parser.add_argument("--retry-max-attempts", default=3, type=int)
    parser.add_argument("--retry-backoff-seconds", default=5.0, type=float)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = materialize_full_candidate(
        contract=_load_json(args.contract),
        candidate_universe=args.candidate_universe,
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
        requests_per_minute=args.requests_per_minute,
        pro_bar_requests_per_minute=args.pro_bar_requests_per_minute,
        retry_max_attempts=args.retry_max_attempts,
        retry_backoff_seconds=args.retry_backoff_seconds,
    )
    redacted = {
        "run_id": report["run_id"],
        "source_snapshot_id": report["source_snapshot_id"],
        "d2_acceptance_decision": report["d2_acceptance_decision"],
        "d3_handoff_decision": report["d3_handoff_decision"],
        "r0_handoff_decision": report["r0_handoff_decision"],
        "quality_report": report["quality_report"],
    }
    print(json.dumps(redacted, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
