from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

VALID = "valid"
UNKNOWN = "unknown"
DIAGNOSTIC_REQUIRED = "diagnostic_required"
BLOCKED = "blocked"

STATE_ENGINE_VERSION = "r0_t06_weak_dimension_nested_state.v1"
Q_VALUES = (0.10, 0.20, 0.30)
BASELINE_Q = 0.20
WEAK_DELTA = 0.10
FLOAT_EPSILON = 1e-12
DIMENSIONS = ("P", "C", "T", "V")
DIMENSION_ORDER = {dimension: index for index, dimension in enumerate(DIMENSIONS)}

FORBIDDEN_OUTPUT_FIELDS = {
    "confirmation",
    "confirmed_state",
    "streak",
    "state_interval",
    "state_intervals",
    "future_label",
    "future_labels",
    "future_return",
    "future_returns",
    "breakout_direction",
    "backtest",
    "portfolio",
    "formal_data_version",
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
    "synthetic_in_memory_scores",
    "r0_t05_strict_past_percentile_score",
}


@dataclass(frozen=True)
class IndicatorStateResult:
    security_id: str
    trading_date: str
    percentile_window_W: int
    q: float
    indicator_id: str
    score: float | None
    eligible: bool
    indicator_active: bool | None
    validity_status: str
    reason_codes: tuple[str, ...]
    state_engine_version: str = field(default=STATE_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "percentile_window_W": self.percentile_window_W,
            "q": self.q,
            "indicator_id": self.indicator_id,
            "score": self.score,
            "eligible": self.eligible,
            "indicator_active": self.indicator_active,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "state_engine_version": self.state_engine_version,
        }


@dataclass(frozen=True)
class DimensionStateResult:
    security_id: str
    trading_date: str
    percentile_window_W: int
    q: float
    weak_delta: float
    dimension: str
    score_dimension: float | None
    score_dimension_min: float | None
    eligible_dimension: bool
    dimension_active_weak: bool | None
    validity_status: str
    reason_codes: tuple[str, ...]
    component_indicator_ids: tuple[str, ...]
    state_engine_version: str = field(default=STATE_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "percentile_window_W": self.percentile_window_W,
            "q": self.q,
            "weak_delta": self.weak_delta,
            "dimension": self.dimension,
            "score_dimension": self.score_dimension,
            "score_dimension_min": self.score_dimension_min,
            "eligible_dimension": self.eligible_dimension,
            "dimension_active_weak": self.dimension_active_weak,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "component_indicator_ids": list(self.component_indicator_ids),
            "state_engine_version": self.state_engine_version,
        }


@dataclass(frozen=True)
class NestedDailyStateResult:
    security_id: str
    trading_date: str
    percentile_window_W: int
    q: float
    weak_delta: float
    P_raw: bool | None
    C_raw: bool | None
    T_raw: bool | None
    V_raw: bool | None
    S_P_raw: bool | None
    S_PC_raw: bool | None
    S_PCT_raw: bool | None
    S_PCVT_raw: bool | None
    exclusive_state_layer: str
    eligible_state: bool
    validity_status: str
    reason_codes: tuple[str, ...]
    state_engine_version: str = field(default=STATE_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "percentile_window_W": self.percentile_window_W,
            "q": self.q,
            "weak_delta": self.weak_delta,
            "P_raw": self.P_raw,
            "C_raw": self.C_raw,
            "T_raw": self.T_raw,
            "V_raw": self.V_raw,
            "S_P_raw": self.S_P_raw,
            "S_PC_raw": self.S_PC_raw,
            "S_PCT_raw": self.S_PCT_raw,
            "S_PCVT_raw": self.S_PCVT_raw,
            "exclusive_state_layer": self.exclusive_state_layer,
            "eligible_state": self.eligible_state,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "state_engine_version": self.state_engine_version,
        }


def compute_indicator_active_states(
    indicator_scores: Sequence[Mapping[str, Any] | Any],
    q_values: Sequence[float] = Q_VALUES,
) -> tuple[IndicatorStateResult, ...]:
    results: list[IndicatorStateResult] = []
    for row_like in indicator_scores:
        row = _normalise_row(row_like)
        for q in _normalise_q_values(q_values):
            results.append(_indicator_state_for_row(row, q))
    return tuple(sorted(results, key=_indicator_sort_key))


def compute_dimension_weak_states(
    dimension_scores: Sequence[Mapping[str, Any] | Any],
    q_values: Sequence[float] = Q_VALUES,
    weak_delta: float = WEAK_DELTA,
) -> tuple[DimensionStateResult, ...]:
    results: list[DimensionStateResult] = []
    for row_like in dimension_scores:
        row = _normalise_row(row_like)
        for q in _normalise_q_values(q_values):
            results.append(_dimension_state_for_row(row, q, weak_delta))
    return tuple(sorted(results, key=_dimension_sort_key))


def compute_nested_daily_states(
    dimension_states: Sequence[DimensionStateResult | Mapping[str, Any]],
) -> tuple[NestedDailyStateResult, ...]:
    grouped: dict[tuple[str, str, int, float], dict[str, dict[str, Any]]] = defaultdict(
        dict
    )
    for item in dimension_states:
        row = item.as_dict() if hasattr(item, "as_dict") else dict(item)
        key = (
            str(row["security_id"]),
            str(row["trading_date"]),
            int(row["percentile_window_W"]),
            float(row["q"]),
        )
        grouped[key][str(row["dimension"])] = row

    results = [_nested_state_for_group(key, rows) for key, rows in grouped.items()]
    return tuple(sorted(results, key=_nested_sort_key))


def assert_no_forbidden_state_outputs(
    payload: Mapping[str, Any],
) -> IndicatorStateResult:
    reasons = [
        "forbidden_output_field"
        for key in _walk_keys(payload)
        if key in FORBIDDEN_OUTPUT_FIELDS
    ]
    if reasons:
        return _guard_result(BLOCKED, reasons)
    return _guard_result(VALID, ("valid_no_blocker",))


def check_state_lineage(
    lineage: Mapping[str, Any] | Sequence[str],
) -> IndicatorStateResult:
    sources = _lineage_sources(lineage)
    if not sources:
        return _guard_result(UNKNOWN, ("state_lineage_missing",))
    if any(_is_prohibited_source(source) for source in sources):
        return _guard_result(BLOCKED, ("direct_real_data_source_forbidden",))
    if not any(source in ALLOWED_LINEAGE_SOURCES for source in sources):
        return _guard_result(UNKNOWN, ("state_lineage_missing",))
    return _guard_result(VALID, ("valid_no_blocker",))


def _indicator_state_for_row(row: Mapping[str, Any], q: float) -> IndicatorStateResult:
    score = _finite_float(row.get("score"))
    eligible = row.get("eligible") is True
    valid = eligible and row.get("validity_status") == VALID and score is not None
    reasons = tuple(row.get("reason_codes", ()))
    if valid:
        indicator_active = _meets_threshold(score, _indicator_threshold(q))
        status = VALID
        reason_codes = ("valid_no_blocker",)
    else:
        indicator_active = None
        status = _propagated_status(row)
        reason_codes = _unique_reasons(
            (*reasons, "score_missing" if score is None else "indicator_not_eligible")
        )
    return IndicatorStateResult(
        security_id=str(row.get("security_id", "")),
        trading_date=str(row.get("trading_date", "")),
        percentile_window_W=int(row.get("percentile_window_W", 0)),
        q=q,
        indicator_id=str(row.get("indicator_id", "")),
        score=score,
        eligible=eligible,
        indicator_active=indicator_active,
        validity_status=status,
        reason_codes=reason_codes,
    )


def _dimension_state_for_row(
    row: Mapping[str, Any], q: float, weak_delta: float
) -> DimensionStateResult:
    score_dimension = _finite_float(row.get("score_dimension"))
    score_dimension_min = _finite_float(row.get("score_dimension_min"))
    eligible = row.get("eligible_dimension") is True
    valid = (
        eligible
        and row.get("validity_status") == VALID
        and score_dimension is not None
        and score_dimension_min is not None
    )
    reasons = tuple(row.get("reason_codes", ()))
    if valid:
        active = _meets_threshold(
            score_dimension, _dimension_mean_threshold(q)
        ) and _meets_threshold(
            score_dimension_min, _dimension_min_threshold(q, weak_delta)
        )
        status = VALID
        reason_codes = ("valid_no_blocker",)
    else:
        active = None
        status = _propagated_status(row)
        missing_reasons = []
        if score_dimension is None:
            missing_reasons.append("score_dimension_missing")
        if score_dimension_min is None:
            missing_reasons.append("score_dimension_min_missing")
        if not eligible:
            missing_reasons.append("dimension_not_eligible")
        reason_codes = _unique_reasons((*reasons, *missing_reasons))
    return DimensionStateResult(
        security_id=str(row.get("security_id", "")),
        trading_date=str(row.get("trading_date", "")),
        percentile_window_W=int(row.get("percentile_window_W", 0)),
        q=q,
        weak_delta=weak_delta,
        dimension=str(row.get("dimension", "")),
        score_dimension=score_dimension,
        score_dimension_min=score_dimension_min,
        eligible_dimension=eligible,
        dimension_active_weak=active,
        validity_status=status,
        reason_codes=reason_codes,
        component_indicator_ids=tuple(
            str(component) for component in row.get("component_indicator_ids", ())
        ),
    )


def _nested_state_for_group(
    key: tuple[str, str, int, float], rows: Mapping[str, Mapping[str, Any]]
) -> NestedDailyStateResult:
    security_id, trading_date, window, q = key
    values = {
        dimension: _dimension_value(rows.get(dimension)) for dimension in DIMENSIONS
    }
    p_raw = values["P"]
    c_raw = values["C"]
    t_raw = values["T"]
    v_raw = values["V"]

    s_p = p_raw
    s_pc = _chain_and(s_p, c_raw)
    s_pct = _chain_and(s_pc, t_raw)
    s_pcvt = _chain_and(s_pct, v_raw)
    layer, status, reasons = _exclusive_layer(values, rows)

    return NestedDailyStateResult(
        security_id=security_id,
        trading_date=trading_date,
        percentile_window_W=window,
        q=q,
        weak_delta=_weak_delta_from_rows(rows),
        P_raw=p_raw,
        C_raw=c_raw,
        T_raw=t_raw,
        V_raw=v_raw,
        S_P_raw=s_p,
        S_PC_raw=s_pc,
        S_PCT_raw=s_pct,
        S_PCVT_raw=s_pcvt,
        exclusive_state_layer=layer,
        eligible_state=status == VALID,
        validity_status=status,
        reason_codes=reasons,
    )


def _exclusive_layer(
    values: Mapping[str, bool | None],
    rows: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, tuple[str, ...]]:
    p_raw = values["P"]
    c_raw = values["C"]
    t_raw = values["T"]
    v_raw = values["V"]
    if p_raw is None:
        return _non_ready_layer(("P",), rows)
    if p_raw is False:
        if all(values[dimension] is not None for dimension in DIMENSIONS):
            return "NONE", VALID, ("valid_no_blocker",)
        return _non_ready_layer(_none_dimensions(values), rows)
    if c_raw is None:
        return _non_ready_layer(("C",), rows)
    if c_raw is False:
        return "P_ONLY", VALID, ("valid_no_blocker",)
    if t_raw is None:
        return _non_ready_layer(("T",), rows)
    if t_raw is False:
        return "PC_ONLY", VALID, ("valid_no_blocker",)
    if v_raw is None:
        return _non_ready_layer(("V",), rows)
    if v_raw is False:
        return "PCT_ONLY", VALID, ("valid_no_blocker",)
    return "PCVT", VALID, ("valid_no_blocker",)


def _non_ready_layer(
    dimensions: Sequence[str], rows: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str, tuple[str, ...]]:
    statuses = []
    reasons = []
    for dimension in dimensions:
        row = rows.get(dimension)
        if row is None:
            statuses.append(UNKNOWN)
            reasons.append("missing_dimension_state")
            continue
        statuses.append(str(row.get("validity_status", UNKNOWN)))
        reasons.extend(str(reason) for reason in row.get("reason_codes", ()))
    status = _status_from_statuses(statuses)
    return status.upper(), status, _unique_reasons(reasons)


def _chain_and(left: bool | None, right: bool | None) -> bool | None:
    if left is False:
        return False
    if left is None:
        return None
    return right


def _dimension_value(row: Mapping[str, Any] | None) -> bool | None:
    if row is None:
        return None
    value = row.get("dimension_active_weak")
    return value if isinstance(value, bool) else None


def _none_dimensions(values: Mapping[str, bool | None]) -> tuple[str, ...]:
    return tuple(dimension for dimension, value in values.items() if value is None)


def _weak_delta_from_rows(rows: Mapping[str, Mapping[str, Any]]) -> float:
    for row in rows.values():
        value = _finite_float(row.get("weak_delta"))
        if value is not None:
            return value
    return WEAK_DELTA


def _indicator_threshold(q: float) -> float:
    return 1.0 - q


def _dimension_mean_threshold(q: float) -> float:
    return 1.0 - q


def _dimension_min_threshold(q: float, weak_delta: float) -> float:
    return 1.0 - q - weak_delta


def _meets_threshold(value: float, threshold: float) -> bool:
    return value + FLOAT_EPSILON >= threshold


def _normalise_row(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    if hasattr(row, "as_dict"):
        return dict(row.as_dict())
    return dict(row)


def _normalise_q_values(q_values: Sequence[float]) -> tuple[float, ...]:
    return tuple(float(q) for q in q_values)


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _propagated_status(row: Mapping[str, Any]) -> str:
    status = str(row.get("validity_status", UNKNOWN))
    if status in {UNKNOWN, DIAGNOSTIC_REQUIRED, BLOCKED}:
        return status
    return UNKNOWN


def _status_from_statuses(statuses: Sequence[str]) -> str:
    status_set = set(statuses)
    if BLOCKED in status_set:
        return BLOCKED
    if DIAGNOSTIC_REQUIRED in status_set:
        return DIAGNOSTIC_REQUIRED
    return UNKNOWN


def _unique_reasons(reason_codes: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(reason) for reason in reason_codes))


def _guard_result(status: str, reasons: Sequence[str]) -> IndicatorStateResult:
    return IndicatorStateResult(
        security_id="",
        trading_date="",
        percentile_window_W=0,
        q=BASELINE_Q,
        indicator_id="r0_t06_guard",
        score=None,
        eligible=status == VALID,
        indicator_active=None,
        validity_status=status,
        reason_codes=_unique_reasons(reasons),
    )


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


def _indicator_sort_key(item: IndicatorStateResult) -> tuple[str, str, int, float, str]:
    return (
        item.security_id,
        item.trading_date,
        item.percentile_window_W,
        item.q,
        item.indicator_id,
    )


def _dimension_sort_key(item: DimensionStateResult) -> tuple[str, str, int, float, int]:
    return (
        item.security_id,
        item.trading_date,
        item.percentile_window_W,
        item.q,
        DIMENSION_ORDER.get(item.dimension, len(DIMENSION_ORDER)),
    )


def _nested_sort_key(item: NestedDailyStateResult) -> tuple[str, str, int, float]:
    return (
        item.security_id,
        item.trading_date,
        item.percentile_window_W,
        item.q,
    )
