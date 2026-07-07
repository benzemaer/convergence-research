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
SCORE_ENGINE_VERSION = "r0_t05_strict_past_percentile_score.v1"

PERCENTILE_WINDOWS = (120, 250, 500)
TIE_METHOD = "midrank"
CURRENT_VALUE_IN_REFERENCE_SET = False

INPUT_TO_ACTIVE_INDICATOR = {
    "P1_NATR14": "P1_NATR14",
    "P2_LogRange20": "P2_LogRange20",
    "C1_LogMASpread_5_60": "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60": "C2_AdjVWAPSpread_5_60",
    "T1_ER20": "T1_ER20",
    "T2_AbsTrendT20": "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60": "V1_TurnoverShrink20_60",
    "V2_LogAmount20_base": "V2_AmountLevel20Pct",
}
ACTIVE_INDICATORS = (
    "P1_NATR14",
    "P2_LogRange20",
    "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60",
    "T1_ER20",
    "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60",
    "V2_AmountLevel20Pct",
)
ACTIVE_INDICATOR_ORDER = {
    indicator_id: index for index, indicator_id in enumerate(ACTIVE_INDICATORS)
}
DIMENSION_COMPONENTS = {
    "P": ("P1_NATR14", "P2_LogRange20"),
    "C": ("C1_LogMASpread_5_60", "C2_AdjVWAPSpread_5_60"),
    "T": ("T1_ER20", "T2_AbsTrendT20"),
    "V": ("V1_TurnoverShrink20_60", "V2_AmountLevel20Pct"),
}
FORBIDDEN_OUTPUT_FIELDS = {
    "indicator_active",
    "dimension_active",
    "state_active",
    "pcvt_state",
    "pcvt_states",
    "state_interval",
    "state_intervals",
    "S_P",
    "S_PC",
    "S_PCT",
    "S_PCVT",
    "q_threshold",
    "weak_rule",
    "confirmation",
    "streak",
    "future_label",
    "future_labels",
    "future_return",
    "future_returns",
    "breakout_direction",
    "backtest",
    "portfolio",
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
    "synthetic_in_memory_raw_metrics",
    "r0_t04_raw_metric_engine",
}


@dataclass(frozen=True)
class IndicatorScoreResult:
    security_id: str
    trading_date: str
    percentile_window_W: int
    indicator_id: str
    raw_metric_name: str
    raw_value: float | None
    eligible: bool
    percentile: float | None
    score: float | None
    validity_status: str
    reason_codes: tuple[str, ...]
    reference_observation_count: int
    reference_window_start: str | None
    reference_window_end: str | None
    current_value_in_reference_set: bool = field(default=CURRENT_VALUE_IN_REFERENCE_SET)
    tie_method: str = field(default=TIE_METHOD)
    score_engine_version: str = field(default=SCORE_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "percentile_window_W": self.percentile_window_W,
            "indicator_id": self.indicator_id,
            "raw_metric_name": self.raw_metric_name,
            "raw_value": self.raw_value,
            "eligible": self.eligible,
            "percentile": self.percentile,
            "score": self.score,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "reference_observation_count": self.reference_observation_count,
            "reference_window_start": self.reference_window_start,
            "reference_window_end": self.reference_window_end,
            "current_value_in_reference_set": self.current_value_in_reference_set,
            "tie_method": self.tie_method,
            "score_engine_version": self.score_engine_version,
        }


@dataclass(frozen=True)
class DimensionScoreResult:
    security_id: str
    trading_date: str
    percentile_window_W: int
    dimension: str
    score_dimension: float | None
    score_dimension_min: float | None
    eligible_dimension: bool
    validity_status: str
    reason_codes: tuple[str, ...]
    component_indicator_ids: tuple[str, ...]
    score_engine_version: str = field(default=SCORE_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "percentile_window_W": self.percentile_window_W,
            "dimension": self.dimension,
            "score_dimension": self.score_dimension,
            "score_dimension_min": self.score_dimension_min,
            "eligible_dimension": self.eligible_dimension,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "component_indicator_ids": list(self.component_indicator_ids),
            "score_engine_version": self.score_engine_version,
        }


@dataclass(frozen=True)
class CommonEligibleSampleResult:
    security_id: str
    trading_date: str
    common_eligible_sample: bool
    common_eligible_windows: tuple[int, ...]
    reason_codes: tuple[str, ...]
    score_engine_version: str = field(default=SCORE_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "common_eligible_sample": self.common_eligible_sample,
            "common_eligible_windows": list(self.common_eligible_windows),
            "reason_codes": list(self.reason_codes),
            "score_engine_version": self.score_engine_version,
        }


def compute_indicator_scores(
    raw_metric_rows: Sequence[Mapping[str, Any] | Any],
    percentile_windows: Sequence[int] = PERCENTILE_WINDOWS,
) -> tuple[IndicatorScoreResult, ...]:
    rows = [_normalise_raw_metric_row(row) for row in raw_metric_rows]
    results: list[IndicatorScoreResult] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        output_indicator_id = _output_indicator_id(row)
        if output_indicator_id is None:
            continue
        grouped[(row["security_id"], output_indicator_id)].append(row)

    for (security_id, output_indicator_id), group_rows in sorted(grouped.items()):
        sorted_rows = sorted(group_rows, key=_row_sort_key)
        valid_history: list[dict[str, Any]] = []
        for row in sorted_rows:
            for window in percentile_windows:
                results.append(
                    _score_one_row(
                        row=row,
                        security_id=security_id,
                        output_indicator_id=output_indicator_id,
                        valid_history=valid_history,
                        percentile_window=int(window),
                    )
                )
            if row.get("indicator_id") != "V2_AmountLevel20Pct" and _raw_metric_valid(
                row
            ):
                valid_history.append(row)

    return tuple(sorted(results, key=_indicator_score_sort_key))


def compute_dimension_scores(
    indicator_scores: Sequence[IndicatorScoreResult | Mapping[str, Any]],
) -> tuple[DimensionScoreResult, ...]:
    by_key: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    security_dates: set[tuple[str, str, int]] = set()
    for item in indicator_scores:
        row = item.as_dict() if hasattr(item, "as_dict") else dict(item)
        key = (
            str(row["security_id"]),
            str(row["trading_date"]),
            int(row["percentile_window_W"]),
            str(row["indicator_id"]),
        )
        by_key[key] = row
        security_dates.add(key[:3])

    results: list[DimensionScoreResult] = []
    for security_id, trading_date, window in sorted(security_dates):
        for dimension, components in DIMENSION_COMPONENTS.items():
            component_rows = [
                by_key.get((security_id, trading_date, window, component))
                for component in components
            ]
            missing = [
                component
                for component, row in zip(components, component_rows, strict=True)
                if row is None
            ]
            invalid_rows = [
                row
                for row in component_rows
                if row is not None and not row.get("eligible")
            ]
            if not missing and not invalid_rows:
                scores = [
                    float(row["score"]) for row in component_rows if row is not None
                ]
                results.append(
                    DimensionScoreResult(
                        security_id=security_id,
                        trading_date=trading_date,
                        percentile_window_W=window,
                        dimension=dimension,
                        score_dimension=sum(scores) / len(scores),
                        score_dimension_min=min(scores),
                        eligible_dimension=True,
                        validity_status=VALID,
                        reason_codes=("valid_no_blocker",),
                        component_indicator_ids=components,
                    )
                )
                continue

            reasons: list[str] = []
            for _component in missing:
                reasons.append("missing_component_score")
            for row in invalid_rows:
                reasons.extend(str(reason) for reason in row.get("reason_codes", ()))
            results.append(
                DimensionScoreResult(
                    security_id=security_id,
                    trading_date=trading_date,
                    percentile_window_W=window,
                    dimension=dimension,
                    score_dimension=None,
                    score_dimension_min=None,
                    eligible_dimension=False,
                    validity_status=_status_from_component_rows(invalid_rows),
                    reason_codes=_unique_reasons(reasons),
                    component_indicator_ids=components,
                )
            )
    return tuple(results)


def compute_common_eligible_samples(
    indicator_scores: Sequence[IndicatorScoreResult | Mapping[str, Any]],
    percentile_windows: Sequence[int] = PERCENTILE_WINDOWS,
) -> tuple[CommonEligibleSampleResult, ...]:
    by_date: dict[tuple[str, str], dict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    seen_dates: set[tuple[str, str]] = set()
    for item in indicator_scores:
        row = item.as_dict() if hasattr(item, "as_dict") else dict(item)
        key = (str(row["security_id"]), str(row["trading_date"]))
        seen_dates.add(key)
        if row.get("eligible") is True:
            by_date[key][int(row["percentile_window_W"])].add(str(row["indicator_id"]))

    expected_indicators = set(ACTIVE_INDICATORS)
    expected_windows = tuple(int(window) for window in percentile_windows)
    results: list[CommonEligibleSampleResult] = []
    for security_id, trading_date in sorted(seen_dates):
        eligible_windows = tuple(
            window
            for window in expected_windows
            if by_date[(security_id, trading_date)].get(window, set())
            == expected_indicators
        )
        common = eligible_windows == expected_windows
        reasons = (
            ("valid_no_blocker",) if common else ("common_eligible_sample_incomplete",)
        )
        results.append(
            CommonEligibleSampleResult(
                security_id=security_id,
                trading_date=trading_date,
                common_eligible_sample=common,
                common_eligible_windows=eligible_windows,
                reason_codes=reasons,
            )
        )
    return tuple(results)


def assert_no_forbidden_score_outputs(
    payload: Mapping[str, Any],
) -> IndicatorScoreResult:
    reasons = [
        "forbidden_output_field"
        for key in _walk_keys(payload)
        if key in FORBIDDEN_OUTPUT_FIELDS
    ]
    if reasons:
        return _guard_result(BLOCKED, reasons)
    return _guard_result(VALID, ("valid_no_blocker",))


def check_score_lineage(
    lineage: Mapping[str, Any] | Sequence[str],
) -> IndicatorScoreResult:
    sources = _lineage_sources(lineage)
    if not sources:
        return _guard_result(UNKNOWN, ("score_lineage_missing",))
    if any(_is_prohibited_source(source) for source in sources):
        return _guard_result(BLOCKED, ("direct_real_data_source_forbidden",))
    if not any(source in ALLOWED_LINEAGE_SOURCES for source in sources):
        return _guard_result(UNKNOWN, ("score_lineage_missing",))
    return _guard_result(VALID, ("valid_no_blocker",))


def _score_one_row(
    row: Mapping[str, Any],
    security_id: str,
    output_indicator_id: str,
    valid_history: Sequence[Mapping[str, Any]],
    percentile_window: int,
) -> IndicatorScoreResult:
    raw_value = _float(row.get("raw_value"))
    raw_metric_name = _output_raw_metric_name(row, output_indicator_id)
    if row.get("indicator_id") == "V2_AmountLevel20Pct":
        return _indicator_result(
            row=row,
            output_indicator_id=output_indicator_id,
            raw_metric_name=raw_metric_name,
            raw_value=raw_value,
            percentile_window=percentile_window,
            status=BLOCKED,
            reasons=("amount_level_repeated_percentile_forbidden",),
        )
    if raw_value is None and row.get("validity_status") == VALID:
        return _indicator_result(
            row=row,
            output_indicator_id=output_indicator_id,
            raw_metric_name=raw_metric_name,
            raw_value=None,
            percentile_window=percentile_window,
            status=UNKNOWN,
            reasons=("raw_metric_not_valid", "raw_metric_value_missing"),
        )
    if not _raw_metric_valid(row):
        return _indicator_result(
            row=row,
            output_indicator_id=output_indicator_id,
            raw_metric_name=raw_metric_name,
            raw_value=raw_value,
            percentile_window=percentile_window,
            status=_propagated_status(row),
            reasons=("raw_metric_not_valid", *tuple(row.get("reason_codes", ()))),
        )
    if raw_value is None:
        return _indicator_result(
            row=row,
            output_indicator_id=output_indicator_id,
            raw_metric_name=raw_metric_name,
            raw_value=None,
            percentile_window=percentile_window,
            status=UNKNOWN,
            reasons=("raw_metric_not_valid", "raw_metric_value_missing"),
        )
    if len(valid_history) < percentile_window:
        return _indicator_result(
            row=row,
            output_indicator_id=output_indicator_id,
            raw_metric_name=raw_metric_name,
            raw_value=raw_value,
            percentile_window=percentile_window,
            status=UNKNOWN,
            reasons=("insufficient_strict_past_history",),
            reference_history=valid_history,
        )

    reference_rows = tuple(valid_history[-percentile_window:])
    reference_values = [
        _float(reference.get("raw_value")) for reference in reference_rows
    ]
    percentile = _midrank_percentile(
        raw_value, [value for value in reference_values if value is not None]
    )
    return IndicatorScoreResult(
        security_id=security_id,
        trading_date=str(row["trading_date"]),
        percentile_window_W=percentile_window,
        indicator_id=output_indicator_id,
        raw_metric_name=raw_metric_name,
        raw_value=raw_value,
        eligible=True,
        percentile=percentile,
        score=1.0 - percentile,
        validity_status=VALID,
        reason_codes=("valid_no_blocker",),
        reference_observation_count=percentile_window,
        reference_window_start=str(reference_rows[0]["trading_date"]),
        reference_window_end=str(reference_rows[-1]["trading_date"]),
    )


def _indicator_result(
    row: Mapping[str, Any],
    output_indicator_id: str,
    raw_metric_name: str,
    raw_value: float | None,
    percentile_window: int,
    status: str,
    reasons: Sequence[str],
    reference_history: Sequence[Mapping[str, Any]] = (),
) -> IndicatorScoreResult:
    reference_rows = tuple(reference_history[-percentile_window:])
    return IndicatorScoreResult(
        security_id=str(row.get("security_id", "")),
        trading_date=str(row.get("trading_date", "")),
        percentile_window_W=percentile_window,
        indicator_id=output_indicator_id,
        raw_metric_name=raw_metric_name,
        raw_value=raw_value,
        eligible=False,
        percentile=None,
        score=None,
        validity_status=status,
        reason_codes=_unique_reasons(reasons),
        reference_observation_count=len(reference_rows),
        reference_window_start=str(reference_rows[0]["trading_date"])
        if reference_rows
        else None,
        reference_window_end=str(reference_rows[-1]["trading_date"])
        if reference_rows
        else None,
    )


def _guard_result(status: str, reasons: Sequence[str]) -> IndicatorScoreResult:
    return IndicatorScoreResult(
        security_id="",
        trading_date="",
        percentile_window_W=0,
        indicator_id="r0_t05_guard",
        raw_metric_name="guard",
        raw_value=None,
        eligible=status == VALID,
        percentile=None,
        score=None,
        validity_status=status,
        reason_codes=_unique_reasons(reasons),
        reference_observation_count=0,
        reference_window_start=None,
        reference_window_end=None,
    )


def _midrank_percentile(
    current_value: float, reference_values: Sequence[float]
) -> float:
    less = sum(1 for value in reference_values if value < current_value)
    equal = sum(1 for value in reference_values if value == current_value)
    return (less + 0.5 * equal) / len(reference_values)


def _normalise_raw_metric_row(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    if hasattr(row, "as_dict"):
        return dict(row.as_dict())
    return dict(row)


def _output_indicator_id(row: Mapping[str, Any]) -> str | None:
    indicator_id = str(row.get("indicator_id", ""))
    if indicator_id == "V2_AmountLevel20Pct":
        return indicator_id
    return INPUT_TO_ACTIVE_INDICATOR.get(indicator_id)


def _output_raw_metric_name(row: Mapping[str, Any], output_indicator_id: str) -> str:
    if output_indicator_id == "V2_AmountLevel20Pct":
        return "AmountLevel20Pct"
    return str(row.get("raw_metric_name", ""))


def _raw_metric_valid(row: Mapping[str, Any]) -> bool:
    return (
        row.get("validity_status") == VALID and _float(row.get("raw_value")) is not None
    )


def _propagated_status(row: Mapping[str, Any]) -> str:
    status = str(row.get("validity_status", UNKNOWN))
    if status in {UNKNOWN, DIAGNOSTIC_REQUIRED, BLOCKED}:
        return status
    return UNKNOWN


def _status_from_component_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(row.get("validity_status", UNKNOWN)) for row in rows}
    if BLOCKED in statuses:
        return BLOCKED
    if DIAGNOSTIC_REQUIRED in statuses:
        return DIAGNOSTIC_REQUIRED
    return UNKNOWN


def _indicator_score_sort_key(item: IndicatorScoreResult) -> tuple[str, str, int, int]:
    return (
        item.security_id,
        item.trading_date,
        item.percentile_window_W,
        ACTIVE_INDICATOR_ORDER[item.indicator_id],
    )


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("trading_date", "")),
        str(row.get("security_id", "")),
        str(row.get("indicator_id", "")),
    )


def _float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


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
