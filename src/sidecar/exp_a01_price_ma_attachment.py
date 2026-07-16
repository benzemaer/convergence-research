"""Pure in-memory raw metrics for the EXP-A01 sidecar exploration.

The implementation consumes canonical daily observations carrying continuous
research adjusted open and close prices.  It deliberately does not calculate
percentiles, scores, states, future labels, returns, or trading outcomes.
Formal DuckDB access belongs to the future runner gate and is not performed by
this module.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

TASK_ID = "EXP-A01"
METRIC_ENGINE_VERSION = "exp_a01_price_ma_attachment.v1"
MA_WINDOWS = (5, 10, 20, 30, 60)
A2_ROLLING_WINDOW = 20
A1_REQUIRED_OBSERVATIONS = 60
A2_REQUIRED_OBSERVATIONS = 79

A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
INDICATOR_IDS = (A1_ID, A2_ID, A2B_ID)

RAW_METRIC_NAMES = {
    A1_ID: "LogBodyCenterToMACloudCenter_5_60",
    A2_ID: "BodyCenterOutsideMACloudRate20_5_60",
    A2B_ID: "BodyToMACloudGapMean20_5_60",
}
REQUIRED_OBSERVATIONS = {
    A1_ID: A1_REQUIRED_OBSERVATIONS,
    A2_ID: A2_REQUIRED_OBSERVATIONS,
    A2B_ID: A2_REQUIRED_OBSERVATIONS,
}
VALIDITY_STATUSES = ("valid", "unknown", "blocked", "diagnostic_required")
REASON_CODES = (
    "valid_no_blocker",
    "window_insufficient",
    "missing_adjusted_open",
    "missing_adjusted_close",
    "missing_required_history",
    "nonpositive_adjusted_open",
    "nonpositive_adjusted_close",
    "nonpositive_MA",
    "adjustment_failure",
    "suspension_in_required_window",
    "listing_pause_in_required_window",
    "invalid_trading_status",
    "duplicate_security_date",
    "non_monotonic_security_date",
)
OUTPUT_FIELDS = (
    "security_id",
    "trading_date",
    "indicator_id",
    "raw_metric_name",
    "raw_value",
    "validity_status",
    "reason_codes",
    "input_window_start",
    "input_window_end",
    "required_observation_count",
    "actual_valid_observation_count",
    "metric_engine_version",
)

_VALID_TRADING_STATUSES = {"normal_trading", "limit_up", "limit_down"}
_SUSPENSION_STATUSES = {"suspended", "suspension", "halted"}
_LISTING_PAUSE_STATUSES = {"listing_pause", "listing_paused"}
_VALID_ADJUSTMENT_STATUSES = {
    "valid",
    "pass",
    "passed",
    "ok",
    "accepted",
    "verified",
    "resolved",
}
_VALID_ADJUSTMENT_METHODS = {
    "forward_adjusted",
    "backward_adjusted",
    "total_return_adjusted",
    "identity_no_adjustment",
}
_SEVERE_REASONS = {
    "adjustment_failure",
    "invalid_trading_status",
    "nonpositive_adjusted_open",
    "nonpositive_adjusted_close",
    "nonpositive_MA",
    "suspension_in_required_window",
    "listing_pause_in_required_window",
    "non_monotonic_security_date",
}


class InputContractError(ValueError):
    """Raised when an input violates the EXP-A01 row contract."""


@dataclass(frozen=True)
class _PriceRow:
    security_id: str
    trading_date: str
    adjusted_open: float | None
    adjusted_close: float | None
    row_reasons: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return self.security_id, self.trading_date

    @property
    def is_valid(self) -> bool:
        return not self.row_reasons


def compute_a01_metrics(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compute the three A01 raw metrics in deterministic key order.

    Every normalized observation produces one result per candidate.  A result
    with a non-``valid`` status always has ``raw_value=None``.  The calculation
    only reads the current observation and its trailing required window.
    """

    normalized = normalize_price_rows(rows)
    grouped: dict[str, list[_PriceRow]] = defaultdict(list)
    for row in normalized:
        grouped[row.security_id].append(row)

    output: list[dict[str, Any]] = []
    for security_id in sorted(grouped):
        security_rows = grouped[security_id]
        for index, current in enumerate(security_rows):
            output.extend(_compute_for_index(security_rows, index, current))
    return output


def build_raw_metric_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Explicit alias used by future sidecar orchestration code."""

    return compute_a01_metrics(rows)


def compute_metrics(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility alias for callers that use the shorter metric name."""

    return compute_a01_metrics(rows)


def normalize_price_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[_PriceRow, ...]:
    """Normalize rows without mutating input mappings and reject duplicate keys."""

    normalized: list[_PriceRow] = []
    seen: set[tuple[str, str]] = set()
    previous_by_security: dict[str, str] = {}
    non_monotonic_securities: set[str] = set()

    for row_like in rows:
        if not isinstance(row_like, Mapping):
            raise InputContractError("each input row must be a mapping")
        security_id = _required_text(
            _first_present(row_like, "security_id", "ts_code"),
            "security_id",
        )
        trading_date = _canonical_date_text(
            _first_present(row_like, "trading_date", "trade_date")
        )
        key = (security_id, trading_date)
        if key in seen:
            raise InputContractError(f"duplicate_security_date: {key}")
        seen.add(key)

        previous = previous_by_security.get(security_id)
        if previous is not None and trading_date < previous:
            non_monotonic_securities.add(security_id)
        previous_by_security[security_id] = trading_date

        adjusted_open = _optional_float(
            _first_present(row_like, "adjusted_open", "adj_open")
        )
        adjusted_close = _optional_float(
            _first_present(row_like, "adjusted_close", "adj_close")
        )
        reasons = _row_reason_codes(
            row_like,
            adjusted_open=adjusted_open,
            adjusted_close=adjusted_close,
        )
        normalized.append(
            _PriceRow(
                security_id=security_id,
                trading_date=trading_date,
                adjusted_open=adjusted_open,
                adjusted_close=adjusted_close,
                row_reasons=tuple(reasons),
            )
        )

    normalized.sort(key=lambda row: row.key)
    if non_monotonic_securities:
        normalized = [
            replace(
                row,
                row_reasons=_ordered_reasons(
                    (*row.row_reasons, "non_monotonic_security_date")
                    if row.security_id in non_monotonic_securities
                    else row.row_reasons
                ),
            )
            for row in normalized
        ]
    return tuple(normalized)


def _compute_for_index(
    rows: list[_PriceRow],
    index: int,
    current: _PriceRow,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for indicator_id in INDICATOR_IDS:
        required = REQUIRED_OBSERVATIONS[indicator_id]
        start = max(0, index - required + 1)
        window = rows[start : index + 1]
        reasons: list[str] = []
        if len(window) < required:
            reasons.extend(("window_insufficient", "missing_required_history"))
        for row in window:
            reasons.extend(row.row_reasons)

        raw_value: float | None = None
        if not reasons:
            try:
                if indicator_id == A1_ID:
                    body, _cloud_low, _cloud_high, cloud_center = _cloud_point(
                        rows, index
                    )
                    raw_value = abs(body - cloud_center)
                else:
                    points = [
                        _cloud_point(rows, point_index)
                        for point_index in range(
                            index - A2_ROLLING_WINDOW + 1, index + 1
                        )
                    ]
                    if indicator_id == A2_ID:
                        outside_values = [
                            1.0 if _is_outside(body, cloud_low, cloud_high) else 0.0
                            for body, cloud_low, cloud_high, _center in points
                        ]
                        raw_value = sum(outside_values) / len(outside_values)
                    else:
                        gaps = [
                            _body_cloud_gap(
                                body, cloud_low, cloud_high, rows, point_index
                            )
                            for point_index, (
                                body,
                                cloud_low,
                                cloud_high,
                                _center,
                            ) in zip(
                                range(
                                    index - A2_ROLLING_WINDOW + 1,
                                    index + 1,
                                ),
                                points,
                                strict=True,
                            )
                        ]
                        raw_value = sum(gaps) / len(gaps)
            except (ArithmeticError, ValueError):
                reasons.append("nonpositive_MA")

        reasons = _ordered_reasons(reasons)
        if reasons or raw_value is None or not math.isfinite(raw_value):
            if not reasons:
                reasons = ["nonpositive_MA"]
            raw_value = None
            status = _status_for_reasons(reasons)
        else:
            if raw_value < 0.0:
                raw_value = None
                reasons = ["nonpositive_MA"]
                status = "blocked"
            elif indicator_id == A2_ID and not 0.0 <= raw_value <= 1.0:
                raw_value = None
                reasons = ["nonpositive_MA"]
                status = "blocked"
            else:
                status = "valid"
                reasons = ["valid_no_blocker"]

        results.append(
            _result_row(
                current=current,
                indicator_id=indicator_id,
                raw_value=raw_value,
                validity_status=status,
                reason_codes=reasons,
                input_window_start=window[0].trading_date if window else None,
                input_window_end=current.trading_date,
                required_observation_count=required,
                actual_valid_observation_count=sum(row.is_valid for row in window),
            )
        )
    return results


def _cloud_point(
    rows: list[_PriceRow], index: int
) -> tuple[float, float, float, float]:
    current = rows[index]
    if not current.is_valid:
        raise ValueError("invalid current observation")
    if current.adjusted_open is None or current.adjusted_close is None:
        raise ValueError("missing current adjusted price")
    body = (math.log(current.adjusted_open) + math.log(current.adjusted_close)) / 2.0
    log_mas = []
    for window_size in MA_WINDOWS:
        window = rows[index - window_size + 1 : index + 1]
        if len(window) != window_size or any(not row.is_valid for row in window):
            raise ValueError("invalid moving-average window")
        closes = [row.adjusted_close for row in window]
        if any(value is None or value <= 0.0 for value in closes):
            raise ValueError("nonpositive moving-average input")
        moving_average = sum(closes) / window_size
        if not math.isfinite(moving_average) or moving_average <= 0.0:
            raise ValueError("nonpositive moving average")
        log_mas.append(math.log(moving_average))
    return body, min(log_mas), max(log_mas), sum(log_mas) / len(log_mas)


def _is_outside(body: float, cloud_low: float, cloud_high: float) -> bool:
    return body < cloud_low or body > cloud_high


def _body_cloud_gap(
    body: float,
    cloud_low: float,
    cloud_high: float,
    rows: list[_PriceRow],
    index: int,
) -> float:
    current = rows[index]
    if current.adjusted_open is None or current.adjusted_close is None:
        raise ValueError("missing body endpoint")
    body_low = min(math.log(current.adjusted_open), math.log(current.adjusted_close))
    body_high = max(math.log(current.adjusted_open), math.log(current.adjusted_close))
    if body_high < cloud_low:
        return cloud_low - body_high
    if body_low > cloud_high:
        return body_low - cloud_high
    return 0.0


def _row_reason_codes(
    row: Mapping[str, Any],
    *,
    adjusted_open: float | None,
    adjusted_close: float | None,
) -> list[str]:
    reasons: list[str] = []
    if adjusted_open is None:
        reasons.append("missing_adjusted_open")
    elif adjusted_open <= 0.0:
        reasons.append("nonpositive_adjusted_open")
    if adjusted_close is None:
        reasons.append("missing_adjusted_close")
    elif adjusted_close <= 0.0:
        reasons.append("nonpositive_adjusted_close")

    status_value = row.get("trading_status")
    status = str(status_value).strip().lower() if status_value is not None else ""
    if status in _SUSPENSION_STATUSES or _truthy(row.get("is_suspended")):
        reasons.append("suspension_in_required_window")
    elif status in _LISTING_PAUSE_STATUSES or _truthy(row.get("is_listing_pause")):
        reasons.append("listing_pause_in_required_window")
    elif status not in _VALID_TRADING_STATUSES:
        reasons.append("invalid_trading_status")

    if _truthy(row.get("adjustment_failure")):
        reasons.append("adjustment_failure")
    for field_name in (
        "adjustment_factor_status",
        "adjustment_status",
        "continuous_ohlc_integrity_status",
    ):
        if field_name in row and row[field_name] is not None:
            value = str(row[field_name]).strip().lower()
            if value not in _VALID_ADJUSTMENT_STATUSES:
                reasons.append("adjustment_failure")
    if "adjustment_method" in row and row["adjustment_method"] is not None:
        method = str(row["adjustment_method"]).strip().lower()
        if method not in _VALID_ADJUSTMENT_METHODS:
            reasons.append("adjustment_failure")
    if "adjustment_factor" in row and row["adjustment_factor"] is not None:
        factor = _optional_float(row["adjustment_factor"])
        if factor is None or factor <= 0.0:
            reasons.append("adjustment_failure")
    if "factor_as_of_time" in row and row["factor_as_of_time"] is None:
        reasons.append("adjustment_failure")

    for field_name in ("daily_status", "observation_status"):
        value = row.get(field_name)
        if value is not None and str(value).strip().lower() in {
            "missing",
            "no_observation",
        }:
            reasons.append("missing_required_history")
    if _truthy(row.get("missing_observation")):
        reasons.append("missing_required_history")
    return _ordered_reasons(reasons)


def _result_row(
    *,
    current: _PriceRow,
    indicator_id: str,
    raw_value: float | None,
    validity_status: str,
    reason_codes: list[str],
    input_window_start: str | None,
    input_window_end: str,
    required_observation_count: int,
    actual_valid_observation_count: int,
) -> dict[str, Any]:
    if validity_status not in VALIDITY_STATUSES:
        raise AssertionError(f"invalid status: {validity_status}")
    if validity_status != "valid" and raw_value is not None:
        raise AssertionError("invalid result cannot carry a raw value")
    return {
        "security_id": current.security_id,
        "trading_date": current.trading_date,
        "indicator_id": indicator_id,
        "raw_metric_name": RAW_METRIC_NAMES[indicator_id],
        "raw_value": raw_value,
        "validity_status": validity_status,
        "reason_codes": list(reason_codes),
        "input_window_start": input_window_start,
        "input_window_end": input_window_end,
        "required_observation_count": required_observation_count,
        "actual_valid_observation_count": actual_valid_observation_count,
        "metric_engine_version": METRIC_ENGINE_VERSION,
    }


def _status_for_reasons(reasons: list[str]) -> str:
    if any(reason in _SEVERE_REASONS for reason in reasons):
        return "blocked"
    return "unknown"


def _ordered_reasons(reasons: Iterable[str]) -> list[str]:
    unique = {str(reason) for reason in reasons if str(reason)}
    order = {reason: index for index, reason in enumerate(REASON_CODES)}
    return sorted(unique, key=lambda reason: (order.get(reason, len(order)), reason))


def _first_present(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _required_text(value: Any, field_name: str) -> str:
    if value is None or not str(value).strip():
        raise InputContractError(f"missing {field_name}")
    return str(value).strip()


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _canonical_date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise InputContractError(f"invalid trading_date type: {type(value).__name__}")
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise InputContractError(f"invalid trading_date: {value!r}")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False
