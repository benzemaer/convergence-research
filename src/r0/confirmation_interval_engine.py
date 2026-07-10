from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

VALID = "valid"
UNKNOWN = "unknown"
DIAGNOSTIC_REQUIRED = "diagnostic_required"
BLOCKED = "blocked"

CONFIRMATION_ENGINE_VERSION = "r0_t07_confirmation_streak_interval.v1"
CONFIRMATION_K_VALUES = (2, 3, 5)
BASELINE_CONFIRMATION_K = 3
STATE_FIELD_BY_NAME = {
    "S_P": "S_P_raw",
    "S_PC": "S_PC_raw",
    "S_PCT": "S_PCT_raw",
    "S_PCVT": "S_PCVT_raw",
}
STATE_VALIDITY_FIELD_BY_NAME = {
    "S_P": "S_P_validity_status",
    "S_PC": "S_PC_validity_status",
    "S_PCT": "S_PCT_validity_status",
    "S_PCVT": "S_PCVT_validity_status",
}
STATE_REASON_FIELD_BY_NAME = {
    "S_P": "S_P_reason_codes",
    "S_PC": "S_PC_reason_codes",
    "S_PCT": "S_PCT_reason_codes",
    "S_PCVT": "S_PCVT_reason_codes",
}
STATE_ORDER = {
    state_name: index for index, state_name in enumerate(STATE_FIELD_BY_NAME)
}

FORBIDDEN_OUTPUT_FIELDS = {
    "future_label",
    "future_labels",
    "future_return",
    "future_returns",
    "breakout_direction",
    "backtest",
    "portfolio",
    "formal_data_version",
    "manifest",
}
PROHIBITED_SOURCES = (
    "d1.raw_market_prices",
    "d2.adjusted_market_prices",
    "d2.market_price_quality_flags",
    "d2.membership_alignment",
    "d3.generated",
    "data/raw",
    "data/external",
    "data/generated",
    "MarketDB",
    ".day",
)
ALLOWED_LINEAGE_SOURCES = {
    "synthetic_in_memory_daily_states",
    "r0_t06_weak_dimension_nested_state",
}


@dataclass(frozen=True)
class DailyConfirmationResult:
    security_id: str
    trading_date: str
    percentile_window_W: int
    q: float
    weak_delta: float
    confirmation_k: int
    state_name: str
    raw_state: bool | None
    raw_streak: int | None
    raw_streak_start_date: str | None
    confirmed_state: bool | None
    confirmation_start_date: str | None
    confirmation_date: str | None
    validity_status: str
    reason_codes: tuple[str, ...]
    confirmation_engine_version: str = field(default=CONFIRMATION_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "percentile_window_W": self.percentile_window_W,
            "q": self.q,
            "weak_delta": self.weak_delta,
            "confirmation_k": self.confirmation_k,
            "state_name": self.state_name,
            "raw_state": self.raw_state,
            "raw_streak": self.raw_streak,
            "raw_streak_start_date": self.raw_streak_start_date,
            "confirmed_state": self.confirmed_state,
            "confirmation_start_date": self.confirmation_start_date,
            "confirmation_date": self.confirmation_date,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "confirmation_engine_version": self.confirmation_engine_version,
        }


@dataclass(frozen=True)
class ConfirmedIntervalResult:
    security_id: str
    percentile_window_W: int
    q: float
    weak_delta: float
    confirmation_k: int
    state_name: str
    interval_id: str
    raw_start_date: str
    confirmation_date: str
    confirmed_start_date: str
    interval_end_date: str | None
    last_observed_date: str
    duration_raw_days: int
    duration_confirmed_days: int
    is_open_interval: bool
    termination_reason: str
    validity_status: str
    reason_codes: tuple[str, ...]
    confirmation_engine_version: str = field(default=CONFIRMATION_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "percentile_window_W": self.percentile_window_W,
            "q": self.q,
            "weak_delta": self.weak_delta,
            "confirmation_k": self.confirmation_k,
            "state_name": self.state_name,
            "interval_id": self.interval_id,
            "raw_start_date": self.raw_start_date,
            "confirmation_date": self.confirmation_date,
            "confirmed_start_date": self.confirmed_start_date,
            "interval_end_date": self.interval_end_date,
            "last_observed_date": self.last_observed_date,
            "duration_raw_days": self.duration_raw_days,
            "duration_confirmed_days": self.duration_confirmed_days,
            "is_open_interval": self.is_open_interval,
            "termination_reason": self.termination_reason,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "confirmation_engine_version": self.confirmation_engine_version,
        }


def compute_daily_confirmations(
    nested_daily_states: Sequence[Mapping[str, Any] | Any],
    confirmation_k_values: Sequence[int] = CONFIRMATION_K_VALUES,
) -> tuple[DailyConfirmationResult, ...]:
    k_values = _normalise_k_values(confirmation_k_values)
    grouped: dict[tuple[str, int, float, float, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for row_like in nested_daily_states:
        row = _normalise_row(row_like)
        for state_name in STATE_FIELD_BY_NAME:
            grouped[_confirmation_group_key(row, state_name)].append(row)

    results: list[DailyConfirmationResult] = []
    for key, rows in sorted(grouped.items()):
        sorted_rows = sorted(rows, key=_row_sort_key)
        current_streak_dates: list[str] = []
        for row in sorted_rows:
            state_name = key[-1]
            invariant_ok = _nested_raw_invariant_ok(row)
            raw_state = _raw_state(row, state_name) if invariant_ok else None
            non_ready = _non_ready_status(row, state_name, raw_state, invariant_ok)
            if raw_state is True and non_ready is None:
                current_streak_dates.append(str(row["trading_date"]))
            elif raw_state is False and non_ready is None:
                current_streak_dates = []
            else:
                current_streak_dates = []

            for k in k_values:
                results.append(
                    _daily_confirmation_for_row(
                        row=row,
                        state_name=state_name,
                        raw_state=raw_state,
                        current_streak_dates=current_streak_dates,
                        confirmation_k=k,
                        non_ready=non_ready,
                        invariant_ok=invariant_ok,
                    )
                )
    return tuple(sorted(results, key=_daily_confirmation_sort_key))


def compute_confirmed_intervals(
    daily_confirmations: Sequence[DailyConfirmationResult | Mapping[str, Any]],
) -> tuple[ConfirmedIntervalResult, ...]:
    grouped: dict[tuple[str, int, float, float, int, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for item in daily_confirmations:
        row = item.as_dict() if hasattr(item, "as_dict") else dict(item)
        grouped[_interval_group_key(row)].append(row)

    intervals: list[ConfirmedIntervalResult] = []
    for key, rows in sorted(grouped.items()):
        intervals.extend(_intervals_for_group(key, sorted(rows, key=_row_sort_key)))
    return tuple(sorted(intervals, key=_interval_sort_key))


def assert_no_forbidden_confirmation_outputs(
    payload: Mapping[str, Any],
) -> DailyConfirmationResult:
    reasons = [
        "forbidden_output_field"
        for key in _walk_keys(payload)
        if key in FORBIDDEN_OUTPUT_FIELDS
    ]
    if reasons:
        return _guard_result(BLOCKED, reasons)
    return _guard_result(VALID, ("valid_no_blocker",))


def check_confirmation_lineage(
    lineage: Mapping[str, Any] | Sequence[str],
) -> DailyConfirmationResult:
    sources = _lineage_sources(lineage)
    if not sources:
        return _guard_result(UNKNOWN, ("confirmation_lineage_missing",))
    if any(_is_prohibited_source(source) for source in sources):
        return _guard_result(BLOCKED, ("direct_real_data_source_forbidden",))
    if not any(source in ALLOWED_LINEAGE_SOURCES for source in sources):
        return _guard_result(UNKNOWN, ("confirmation_lineage_missing",))
    return _guard_result(VALID, ("valid_no_blocker",))


def _daily_confirmation_for_row(
    row: Mapping[str, Any],
    state_name: str,
    raw_state: bool | None,
    current_streak_dates: Sequence[str],
    confirmation_k: int,
    non_ready: str | None,
    invariant_ok: bool,
) -> DailyConfirmationResult:
    if non_ready is not None:
        reasons = _state_reasons(row, state_name)
        if not invariant_ok:
            reasons = ("nested_raw_state_invariant_violation", *reasons)
        return _daily_result(
            row=row,
            state_name=state_name,
            confirmation_k=confirmation_k,
            raw_state=raw_state,
            raw_streak=None,
            raw_streak_start_date=None,
            confirmed_state=None,
            confirmation_start_date=None,
            confirmation_date=None,
            status=non_ready,
            reasons=reasons,
        )

    if raw_state is False:
        return _daily_result(
            row=row,
            state_name=state_name,
            confirmation_k=confirmation_k,
            raw_state=False,
            raw_streak=0,
            raw_streak_start_date=None,
            confirmed_state=False,
            confirmation_start_date=None,
            confirmation_date=None,
            status=VALID,
            reasons=("valid_no_blocker",),
        )

    raw_streak = len(current_streak_dates)
    confirmed = raw_streak >= confirmation_k
    confirmation_date = current_streak_dates[confirmation_k - 1] if confirmed else None
    return _daily_result(
        row=row,
        state_name=state_name,
        confirmation_k=confirmation_k,
        raw_state=True,
        raw_streak=raw_streak,
        raw_streak_start_date=current_streak_dates[0],
        confirmed_state=confirmed,
        confirmation_start_date=current_streak_dates[0] if confirmed else None,
        confirmation_date=confirmation_date,
        status=VALID,
        reasons=("valid_no_blocker",),
    )


def _intervals_for_group(
    key: tuple[str, int, float, float, int, str],
    rows: Sequence[Mapping[str, Any]],
) -> list[ConfirmedIntervalResult]:
    intervals: list[ConfirmedIntervalResult] = []
    active: dict[str, Any] | None = None
    sequence = 0
    current_raw_segment_dates: list[str] = []
    for row in rows:
        if row.get("raw_state") is True and row.get("validity_status") == VALID:
            true_date = str(row["trading_date"])
            current_raw_segment_dates.append(true_date)
            if row.get("confirmed_state") is True and active is None:
                sequence += 1
                confirmation_date = str(row["confirmation_date"])
                active = {
                    "raw_start_date": str(row["raw_streak_start_date"]),
                    "confirmation_date": confirmation_date,
                    "confirmed_start_date": confirmation_date,
                    "last_true_date": true_date,
                    "raw_segment_dates": tuple(current_raw_segment_dates),
                    "confirmed_segment_dates": _dates_from_confirmation(
                        current_raw_segment_dates, confirmation_date
                    ),
                }
            elif active is not None:
                active["last_true_date"] = true_date
                active["raw_segment_dates"] = tuple(current_raw_segment_dates)
                active["confirmed_segment_dates"] = _dates_from_confirmation(
                    current_raw_segment_dates, str(active["confirmation_date"])
                )
            continue

        if active is not None:
            intervals.append(
                _closed_interval(
                    key=key,
                    active=active,
                    sequence=sequence,
                    termination_row=row,
                )
            )
            active = None
        current_raw_segment_dates = []

    if active is not None:
        intervals.append(
            _open_interval(
                key=key,
                active=active,
                sequence=sequence,
            )
        )
    return intervals


def _closed_interval(
    key: tuple[str, int, float, float, int, str],
    active: Mapping[str, Any],
    sequence: int,
    termination_row: Mapping[str, Any],
) -> ConfirmedIntervalResult:
    security_id, window, q, weak_delta, confirmation_k, state_name = key
    termination_reason = _termination_reason(termination_row)
    raw_start_date = str(active["raw_start_date"])
    confirmation_date = str(active["confirmation_date"])
    end_date = str(active["last_true_date"])
    raw_segment_dates = tuple(active["raw_segment_dates"])
    confirmed_segment_dates = tuple(active["confirmed_segment_dates"])
    return ConfirmedIntervalResult(
        security_id=security_id,
        percentile_window_W=window,
        q=q,
        weak_delta=weak_delta,
        confirmation_k=confirmation_k,
        state_name=state_name,
        interval_id=_interval_id(key, sequence, confirmation_date),
        raw_start_date=raw_start_date,
        confirmation_date=confirmation_date,
        confirmed_start_date=str(active["confirmed_start_date"]),
        interval_end_date=end_date,
        last_observed_date=str(termination_row["trading_date"]),
        duration_raw_days=len(raw_segment_dates),
        duration_confirmed_days=len(confirmed_segment_dates),
        is_open_interval=False,
        termination_reason=termination_reason,
        validity_status=VALID,
        reason_codes=("valid_no_blocker",),
    )


def _open_interval(
    key: tuple[str, int, float, float, int, str],
    active: Mapping[str, Any],
    sequence: int,
) -> ConfirmedIntervalResult:
    security_id, window, q, weak_delta, confirmation_k, state_name = key
    raw_start_date = str(active["raw_start_date"])
    confirmation_date = str(active["confirmation_date"])
    last_true_date = str(active["last_true_date"])
    raw_segment_dates = tuple(active["raw_segment_dates"])
    confirmed_segment_dates = tuple(active["confirmed_segment_dates"])
    return ConfirmedIntervalResult(
        security_id=security_id,
        percentile_window_W=window,
        q=q,
        weak_delta=weak_delta,
        confirmation_k=confirmation_k,
        state_name=state_name,
        interval_id=_interval_id(key, sequence, confirmation_date),
        raw_start_date=raw_start_date,
        confirmation_date=confirmation_date,
        confirmed_start_date=str(active["confirmed_start_date"]),
        interval_end_date=None,
        last_observed_date=last_true_date,
        duration_raw_days=len(raw_segment_dates),
        duration_confirmed_days=len(confirmed_segment_dates),
        is_open_interval=True,
        termination_reason="end_of_input_open",
        validity_status=VALID,
        reason_codes=("valid_no_blocker",),
    )


def _daily_result(
    row: Mapping[str, Any],
    state_name: str,
    confirmation_k: int,
    raw_state: bool | None,
    raw_streak: int | None,
    raw_streak_start_date: str | None,
    confirmed_state: bool | None,
    confirmation_start_date: str | None,
    confirmation_date: str | None,
    status: str,
    reasons: Sequence[str],
) -> DailyConfirmationResult:
    return DailyConfirmationResult(
        security_id=str(row.get("security_id", "")),
        trading_date=str(row.get("trading_date", "")),
        percentile_window_W=int(row.get("percentile_window_W", 0)),
        q=float(row.get("q", 0.0)),
        weak_delta=float(row.get("weak_delta", 0.0)),
        confirmation_k=confirmation_k,
        state_name=state_name,
        raw_state=raw_state,
        raw_streak=raw_streak,
        raw_streak_start_date=raw_streak_start_date,
        confirmed_state=confirmed_state,
        confirmation_start_date=confirmation_start_date,
        confirmation_date=confirmation_date,
        validity_status=status,
        reason_codes=_unique_reasons(reasons),
    )


def _guard_result(status: str, reasons: Sequence[str]) -> DailyConfirmationResult:
    return DailyConfirmationResult(
        security_id="",
        trading_date="",
        percentile_window_W=0,
        q=0.0,
        weak_delta=0.0,
        confirmation_k=BASELINE_CONFIRMATION_K,
        state_name="r0_t07_guard",
        raw_state=None,
        raw_streak=None,
        raw_streak_start_date=None,
        confirmed_state=None,
        confirmation_start_date=None,
        confirmation_date=None,
        validity_status=status,
        reason_codes=_unique_reasons(reasons),
    )


def _raw_state(row: Mapping[str, Any], state_name: str) -> bool | None:
    value = row.get(STATE_FIELD_BY_NAME[state_name])
    return value if isinstance(value, bool) else None


def _non_ready_status(
    row: Mapping[str, Any],
    state_name: str,
    raw_state: bool | None,
    invariant_ok: bool,
) -> str | None:
    if not invariant_ok:
        return BLOCKED
    status = _state_validity_status(row, state_name)
    if status != VALID:
        return _propagated_status(status)
    if raw_state is None:
        return UNKNOWN
    return None


def _nested_raw_invariant_ok(row: Mapping[str, Any]) -> bool:
    s_p = row.get("S_P_raw")
    s_pc = row.get("S_PC_raw")
    s_pct = row.get("S_PCT_raw")
    s_pcvt = row.get("S_PCVT_raw")
    return not (
        (s_pcvt is True and s_pct is not True)
        or (s_pct is True and s_pc is not True)
        or (s_pc is True and s_p is not True)
    )


def _termination_reason(row: Mapping[str, Any]) -> str:
    if row.get("raw_state") is False and row.get("validity_status") == VALID:
        return "raw_state_false"
    status = str(row.get("validity_status", UNKNOWN))
    if status == BLOCKED:
        return "raw_state_blocked"
    if status == DIAGNOSTIC_REQUIRED:
        return "raw_state_diagnostic_required"
    return "raw_state_unknown"


def _interval_id(
    key: tuple[str, int, float, float, int, str], sequence: int, confirmation_date: str
) -> str:
    security_id, window, q, weak_delta, confirmation_k, state_name = key
    return (
        f"{security_id}|W{window}|q{q:.2f}|d{weak_delta:.2f}|"
        f"K{confirmation_k}|{state_name}|{confirmation_date}|{sequence:04d}"
    )


def _normalise_k_values(k_values: Sequence[int]) -> tuple[int, ...]:
    normalised = tuple(int(value) for value in k_values)
    invalid = [value for value in normalised if value not in CONFIRMATION_K_VALUES]
    if invalid:
        raise ValueError(
            f"confirmation_k must be one of {CONFIRMATION_K_VALUES}: {invalid}"
        )
    return normalised


def _dates_from_confirmation(
    raw_segment_dates: Sequence[str], confirmation_date: str
) -> tuple[str, ...]:
    for index, date in enumerate(raw_segment_dates):
        if date == confirmation_date:
            return tuple(raw_segment_dates[index:])
    return ()


def _normalise_row(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    if hasattr(row, "as_dict"):
        return dict(row.as_dict())
    return dict(row)


def _confirmation_group_key(
    row: Mapping[str, Any], state_name: str
) -> tuple[str, int, float, float, str]:
    return (
        str(row["security_id"]),
        int(row["percentile_window_W"]),
        float(row["q"]),
        float(row["weak_delta"]),
        state_name,
    )


def _interval_group_key(
    row: Mapping[str, Any],
) -> tuple[str, int, float, float, int, str]:
    return (
        str(row["security_id"]),
        int(row["percentile_window_W"]),
        float(row["q"]),
        float(row["weak_delta"]),
        int(row["confirmation_k"]),
        str(row["state_name"]),
    )


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (str(row.get("trading_date", "")), str(row.get("security_id", "")))


def _daily_confirmation_sort_key(
    item: DailyConfirmationResult,
) -> tuple[str, str, int, float, float, int, int]:
    return (
        item.security_id,
        item.trading_date,
        item.percentile_window_W,
        item.q,
        item.weak_delta,
        item.confirmation_k,
        STATE_ORDER[item.state_name],
    )


def _interval_sort_key(
    item: ConfirmedIntervalResult,
) -> tuple[str, int, float, float, int, int, str]:
    return (
        item.security_id,
        item.percentile_window_W,
        item.q,
        item.weak_delta,
        item.confirmation_k,
        STATE_ORDER[item.state_name],
        item.confirmation_date,
    )


def _state_validity_status(row: Mapping[str, Any], state_name: str) -> str:
    field = STATE_VALIDITY_FIELD_BY_NAME[state_name]
    status = row.get(field)
    if status is None:
        status = row.get("validity_status", UNKNOWN)
    return str(status)


def _state_reasons(row: Mapping[str, Any], state_name: str) -> tuple[str, ...]:
    field = STATE_REASON_FIELD_BY_NAME[state_name]
    reasons = row.get(field)
    if reasons is None:
        reasons = row.get("reason_codes", ())
    return tuple(reasons or ())


def _propagated_status(status: str) -> str:
    if status in {UNKNOWN, DIAGNOSTIC_REQUIRED, BLOCKED}:
        return status
    return UNKNOWN


def _unique_reasons(reason_codes: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(reason) for reason in reason_codes))


def _walk_keys(value: Any) -> tuple[str, ...]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(nested_value))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for nested_value in value:
            keys.extend(_walk_keys(nested_value))
    return tuple(keys)


def _lineage_sources(lineage: Mapping[str, Any] | Sequence[str]) -> tuple[str, ...]:
    if isinstance(lineage, Mapping):
        values = lineage.get("sources", lineage.get("source_lineage", ()))
        if isinstance(values, str):
            return (values,)
        return tuple(str(value) for value in values)
    if isinstance(lineage, str):
        return (lineage,)
    return tuple(str(value) for value in lineage)


def _is_prohibited_source(source: str) -> bool:
    return any(prohibited in source for prohibited in PROHIBITED_SOURCES)
