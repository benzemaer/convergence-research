from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.r0.input_readiness_gate import (
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    READY,
    UNKNOWN,
    check_d3_only_lineage,
    evaluate_amount_level_readiness,
    evaluate_c2_readiness,
    evaluate_turnover_shrink_readiness,
)

VALID = "valid"
NOT_APPLICABLE = "not_applicable"
METRIC_ENGINE_VERSION = "r0_t04_raw_metric_engine.v1"

RAW_METRIC_IDS = (
    "P1_NATR14",
    "P2_LogRange20",
    "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60",
    "T1_ER20",
    "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60",
    "V2_LogAmount20_base",
)
FORBIDDEN_OUTPUT_FIELDS = {
    "AmountLevel20Pct",
    "amount_level_20_pct",
    "pcvt_percentile",
    "pcvt_percentiles",
    "strict_past_percentile",
    "pcvt_score",
    "pcvt_scores",
    "pcvt_state",
    "pcvt_states",
    "state_interval",
    "state_intervals",
    "future_label",
    "future_labels",
    "future_return",
    "future_returns",
    "breakout_direction",
    "backtest",
    "portfolio",
}


@dataclass(frozen=True)
class RawMetricResult:
    security_id: str
    trading_date: str
    indicator_id: str
    raw_metric_name: str
    raw_value: float | None
    validity_status: str
    reason_codes: tuple[str, ...]
    input_window_start: str | None
    input_window_end: str | None
    required_observation_count: int
    actual_valid_observation_count: int
    source_field_names: tuple[str, ...]
    metric_engine_version: str = field(default=METRIC_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trading_date": self.trading_date,
            "indicator_id": self.indicator_id,
            "raw_metric_name": self.raw_metric_name,
            "raw_value": self.raw_value,
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "input_window_start": self.input_window_start,
            "input_window_end": self.input_window_end,
            "required_observation_count": self.required_observation_count,
            "actual_valid_observation_count": self.actual_valid_observation_count,
            "source_field_names": list(self.source_field_names),
            "metric_engine_version": self.metric_engine_version,
        }


def compute_raw_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[RawMetricResult, ...]:
    """Compute R0-T04 synthetic raw metrics from in-memory observation rows."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        copied = dict(row)
        security_id = str(copied.get("security_id", ""))
        grouped[security_id].append(copied)

    results: list[RawMetricResult] = []
    for security_id in sorted(grouped):
        security_rows = sorted(grouped[security_id], key=_date_key)
        for index, row in enumerate(security_rows):
            results.extend(
                (
                    calculate_natr14(security_rows, index),
                    calculate_log_range20(security_rows, index),
                    calculate_log_ma_spread_5_60(security_rows, index),
                    calculate_adj_vwap_spread_5_60(security_rows, index),
                    calculate_er20(security_rows, index),
                    calculate_abs_trend_t20(security_rows, index),
                    calculate_turnover_shrink20_60(security_rows, index),
                    calculate_log_amount20_base(security_rows, index),
                )
            )
    return tuple(
        sorted(
            results,
            key=lambda item: (
                item.security_id,
                item.trading_date,
                RAW_METRIC_IDS.index(item.indicator_id),
            ),
        )
    )


def calculate_natr14(rows: Sequence[Mapping[str, Any]], index: int) -> RawMetricResult:
    window = _window(rows, index, 15)
    reason = _window_reason(
        window, 15, ("adjusted_high", "adjusted_low", "adjusted_close")
    )
    if reason:
        return _invalid_result(
            rows[index],
            "P1_NATR14",
            "NATR14",
            UNKNOWN,
            reason,
            window,
            15,
            ("adjusted_high", "adjusted_low", "adjusted_close"),
        )

    tr_values: list[float] = []
    for offset in range(1, len(window)):
        previous_close = _float(window[offset - 1].get("adjusted_close"))
        high = _float(window[offset].get("adjusted_high"))
        low = _float(window[offset].get("adjusted_low"))
        if previous_close is None or previous_close <= 0:
            return _invalid_result(
                rows[index],
                "P1_NATR14",
                "NATR14",
                UNKNOWN,
                ("previous_close_missing",),
                window,
                15,
                ("adjusted_high", "adjusted_low", "adjusted_close"),
            )
        if high is None or low is None or high <= 0 or low <= 0:
            return _invalid_result(
                rows[index],
                "P1_NATR14",
                "NATR14",
                UNKNOWN,
                ("nonpositive_adjusted_price",),
                window,
                15,
                ("adjusted_high", "adjusted_low", "adjusted_close"),
            )
        if high < low:
            return _invalid_result(
                rows[index],
                "P1_NATR14",
                "NATR14",
                UNKNOWN,
                ("high_low_anomaly",),
                window,
                15,
                ("adjusted_high", "adjusted_low", "adjusted_close"),
            )
        tr_values.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )

    atr = sum(tr_values[:14]) / 14.0
    close = _float(window[-1].get("adjusted_close"))
    if close is None or close <= 0:
        return _invalid_result(
            rows[index],
            "P1_NATR14",
            "NATR14",
            UNKNOWN,
            ("nonpositive_adjusted_price",),
            window,
            15,
            ("adjusted_high", "adjusted_low", "adjusted_close"),
        )
    return _valid_result(
        rows[index],
        "P1_NATR14",
        "NATR14",
        atr / close,
        window,
        15,
        ("adjusted_high", "adjusted_low", "adjusted_close"),
    )


def calculate_log_range20(
    rows: Sequence[Mapping[str, Any]], index: int
) -> RawMetricResult:
    fields = ("adjusted_high", "adjusted_low")
    window = _window(rows, index, 20)
    reason = _window_reason(window, 20, fields)
    if reason:
        return _invalid_result(
            rows[index],
            "P2_LogRange20",
            "LogRange20",
            UNKNOWN,
            reason,
            window,
            20,
            fields,
        )
    highs = [_float(row.get("adjusted_high")) for row in window]
    lows = [_float(row.get("adjusted_low")) for row in window]
    if any(value is None or value <= 0 for value in highs + lows):
        return _invalid_result(
            rows[index],
            "P2_LogRange20",
            "LogRange20",
            UNKNOWN,
            ("nonpositive_adjusted_price",),
            window,
            20,
            fields,
        )
    if any(
        high < low
        for high, low in zip(highs, lows, strict=True)
        if high is not None and low is not None
    ):
        return _invalid_result(
            rows[index],
            "P2_LogRange20",
            "LogRange20",
            UNKNOWN,
            ("high_low_anomaly",),
            window,
            20,
            fields,
        )
    return _valid_result(
        rows[index],
        "P2_LogRange20",
        "LogRange20",
        math.log(max(highs) / min(lows)),
        window,
        20,
        fields,
    )


def calculate_log_ma_spread_5_60(
    rows: Sequence[Mapping[str, Any]], index: int
) -> RawMetricResult:
    fields = ("adjusted_close",)
    window = _window(rows, index, 60)
    reason = _window_reason(window, 60, fields)
    if reason:
        return _invalid_result(
            rows[index],
            "C1_LogMASpread_5_60",
            "LogMASpread_5_60",
            UNKNOWN,
            reason,
            window,
            60,
            fields,
        )
    closes = [_float(row.get("adjusted_close")) for row in window]
    if any(value is None or value <= 0 for value in closes):
        return _invalid_result(
            rows[index],
            "C1_LogMASpread_5_60",
            "LogMASpread_5_60",
            UNKNOWN,
            ("nonpositive_adjusted_price",),
            window,
            60,
            fields,
        )
    logs = [math.log(_mean(closes[-days:])) for days in (5, 10, 20, 30, 60)]
    return _valid_result(
        rows[index],
        "C1_LogMASpread_5_60",
        "LogMASpread_5_60",
        _std_population(logs),
        window,
        60,
        fields,
    )


def calculate_adj_vwap_spread_5_60(
    rows: Sequence[Mapping[str, Any]], index: int
) -> RawMetricResult:
    fields = ("daily_vwap", "volume_shares")
    window = _window(rows, index, 60)
    reason = _window_reason(window, 60, fields)
    if reason:
        return _invalid_result(
            rows[index],
            "C2_AdjVWAPSpread_5_60",
            "AdjVWAPSpread_5_60",
            UNKNOWN,
            reason,
            window,
            60,
            fields,
        )

    readiness = evaluate_c2_readiness(_with_window_flags(rows[index], window, 60))
    if readiness.status != READY:
        return _invalid_result(
            rows[index],
            "C2_AdjVWAPSpread_5_60",
            "AdjVWAPSpread_5_60",
            _validity_from_readiness(readiness.status),
            readiness.reason_codes,
            window,
            60,
            fields,
        )

    values: list[float] = []
    for days in (5, 10, 20, 30, 60):
        part = window[-days:]
        numerator = 0.0
        denominator = 0.0
        for row in part:
            daily_vwap = _float(row.get("daily_vwap"))
            volume = _float(row.get("volume_shares"))
            if daily_vwap is None or daily_vwap <= 0:
                return _invalid_result(
                    rows[index],
                    "C2_AdjVWAPSpread_5_60",
                    "AdjVWAPSpread_5_60",
                    UNKNOWN,
                    ("daily_vwap_range_unknown",),
                    window,
                    60,
                    fields,
                )
            if volume is None or volume <= 0:
                return _invalid_result(
                    rows[index],
                    "C2_AdjVWAPSpread_5_60",
                    "AdjVWAPSpread_5_60",
                    DIAGNOSTIC_REQUIRED,
                    ("zero_volume_in_window",),
                    window,
                    60,
                    fields,
                )
            numerator += daily_vwap * volume
            denominator += volume
        values.append(math.log(numerator / denominator))

    return _valid_result(
        rows[index],
        "C2_AdjVWAPSpread_5_60",
        "AdjVWAPSpread_5_60",
        _std_population(values),
        window,
        60,
        fields,
    )


def calculate_er20(rows: Sequence[Mapping[str, Any]], index: int) -> RawMetricResult:
    fields = ("adjusted_close",)
    window = _window(rows, index, 21)
    reason = _window_reason(window, 21, fields)
    if reason:
        return _invalid_result(
            rows[index], "T1_ER20", "ER20", UNKNOWN, reason, window, 21, fields
        )
    closes = [_float(row.get("adjusted_close")) for row in window]
    if any(value is None or value <= 0 for value in closes):
        return _invalid_result(
            rows[index],
            "T1_ER20",
            "ER20",
            UNKNOWN,
            ("nonpositive_adjusted_price",),
            window,
            21,
            fields,
        )
    logs = [math.log(value) for value in closes if value is not None]
    denominator = sum(
        abs(logs[offset] - logs[offset - 1]) for offset in range(1, len(logs))
    )
    if math.isclose(denominator, 0.0, abs_tol=1e-15):
        return _valid_result(
            rows[index],
            "T1_ER20",
            "ER20",
            0.0,
            window,
            21,
            fields,
            ("denominator_zero_flat_path",),
        )
    return _valid_result(
        rows[index],
        "T1_ER20",
        "ER20",
        abs(logs[-1] - logs[0]) / denominator,
        window,
        21,
        fields,
    )


def calculate_abs_trend_t20(
    rows: Sequence[Mapping[str, Any]], index: int
) -> RawMetricResult:
    fields = ("adjusted_close",)
    window = _window(rows, index, 20)
    reason = _window_reason(window, 20, fields)
    if reason:
        return _invalid_result(
            rows[index],
            "T2_AbsTrendT20",
            "AbsTrendT20",
            UNKNOWN,
            reason,
            window,
            20,
            fields,
        )
    closes = [_float(row.get("adjusted_close")) for row in window]
    if any(value is None or value <= 0 for value in closes):
        return _invalid_result(
            rows[index],
            "T2_AbsTrendT20",
            "AbsTrendT20",
            UNKNOWN,
            ("nonpositive_adjusted_price",),
            window,
            20,
            fields,
        )
    y = [math.log(value) for value in closes if value is not None]
    x = list(range(20))
    x_mean = _mean(x)
    y_mean = _mean(y)
    sum_xx = sum((value - x_mean) ** 2 for value in x)
    beta = (
        sum((xv - x_mean) * (yv - y_mean) for xv, yv in zip(x, y, strict=True)) / sum_xx
    )
    alpha = y_mean - beta * x_mean
    residuals = [yv - (alpha + beta * xv) for xv, yv in zip(x, y, strict=True)]
    sse = sum(value * value for value in residuals)
    if math.isclose(sse, 0.0, abs_tol=1e-15):
        if math.isclose(beta, 0.0, abs_tol=1e-15):
            return _valid_result(
                rows[index],
                "T2_AbsTrendT20",
                "AbsTrendT20",
                0.0,
                window,
                20,
                fields,
                ("flat_path_residual_se_zero",),
            )
        return _invalid_result(
            rows[index],
            "T2_AbsTrendT20",
            "AbsTrendT20",
            DIAGNOSTIC_REQUIRED,
            ("residual_se_zero_slope_nonzero",),
            window,
            20,
            fields,
        )
    se_beta = math.sqrt((sse / (20 - 2)) / sum_xx)
    return _valid_result(
        rows[index],
        "T2_AbsTrendT20",
        "AbsTrendT20",
        abs(beta / se_beta),
        window,
        20,
        fields,
    )


def calculate_turnover_shrink20_60(
    rows: Sequence[Mapping[str, Any]], index: int
) -> RawMetricResult:
    fields = (
        "turnover_float",
        "turnover_field_status",
        "share_field_status",
        "provider_turnover_crosscheck_status",
        "volume_shares",
        "float_share_shares",
        "trading_status",
        "corporate_action_flag",
        "suspension_flag",
        "corporate_action_types_in_window",
        "share_comparability_corporate_action_in_window",
        "common_share_basis_policy",
        "volume_comparability_policy",
    )
    window = _window(rows, index, 80)
    reason = _window_reason(window, 80, fields)
    if reason:
        status = (
            DIAGNOSTIC_REQUIRED
            if any(
                item in {"suspension_in_window", "listing_pause_in_window"}
                for item in reason
            )
            else UNKNOWN
        )
        return _invalid_result(
            rows[index],
            "V1_TurnoverShrink20_60",
            "TurnoverShrink20_60",
            status,
            reason,
            window,
            80,
            fields,
        )

    readiness = evaluate_turnover_shrink_readiness(
        _with_window_flags(rows[index], window, 80)
    )
    if readiness.status != READY:
        return _invalid_result(
            rows[index],
            "V1_TurnoverShrink20_60",
            "TurnoverShrink20_60",
            _validity_from_readiness(readiness.status),
            readiness.reason_codes,
            window,
            80,
            fields,
        )

    turnover_values = [_float(row.get("turnover_float")) for row in window]
    if any(value is None for value in turnover_values):
        return _invalid_result(
            rows[index],
            "V1_TurnoverShrink20_60",
            "TurnoverShrink20_60",
            UNKNOWN,
            ("turnover_float_missing",),
            window,
            80,
            fields,
        )
    prior_mean = _mean(turnover_values[:60])
    recent_mean = _mean(turnover_values[60:])
    if prior_mean <= 0:
        return _invalid_result(
            rows[index],
            "V1_TurnoverShrink20_60",
            "TurnoverShrink20_60",
            UNKNOWN,
            ("turnover_float_missing",),
            window,
            80,
            fields,
        )
    return _valid_result(
        rows[index],
        "V1_TurnoverShrink20_60",
        "TurnoverShrink20_60",
        recent_mean / prior_mean,
        window,
        80,
        fields,
    )


def calculate_log_amount20_base(
    rows: Sequence[Mapping[str, Any]], index: int
) -> RawMetricResult:
    fields = (
        "amount_yuan",
        "amount_unit",
        "amount_volume_unit_status",
        "zero_amount_flag",
        "trading_status",
        "suspension_flag",
    )
    window = _window(rows, index, 20)
    reason = _window_reason(window, 20, fields)
    if reason:
        status = DIAGNOSTIC_REQUIRED if "suspension_in_window" in reason else UNKNOWN
        return _invalid_result(
            rows[index],
            "V2_LogAmount20_base",
            "LogAmount20",
            status,
            reason,
            window,
            20,
            fields,
        )

    readiness = evaluate_amount_level_readiness(
        _with_window_flags(rows[index], window, 20)
    )
    if readiness.status != READY:
        return _invalid_result(
            rows[index],
            "V2_LogAmount20_base",
            "LogAmount20",
            _validity_from_readiness(readiness.status),
            readiness.reason_codes,
            window,
            20,
            fields,
        )

    amounts = [_float(row.get("amount_yuan")) for row in window]
    if any(value is None or value <= 0 for value in amounts):
        return _invalid_result(
            rows[index],
            "V2_LogAmount20_base",
            "LogAmount20",
            UNKNOWN,
            ("amount_yuan_nonpositive",),
            window,
            20,
            fields,
        )
    return _valid_result(
        rows[index],
        "V2_LogAmount20_base",
        "LogAmount20",
        math.log(_mean(amounts)),
        window,
        20,
        fields,
    )


def assert_no_forbidden_raw_metric_outputs(
    payload: Mapping[str, Any],
) -> RawMetricResult:
    reason_codes = []
    for key in _walk_keys(payload):
        if key in FORBIDDEN_OUTPUT_FIELDS:
            reason_codes.append("forbidden_output_field")
    if reason_codes:
        return RawMetricResult(
            security_id="",
            trading_date="",
            indicator_id="r0_t04_forbidden_output_guard",
            raw_metric_name="forbidden_output_guard",
            raw_value=None,
            validity_status=BLOCKED,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            input_window_start=None,
            input_window_end=None,
            required_observation_count=0,
            actual_valid_observation_count=0,
            source_field_names=(),
        )
    return RawMetricResult(
        security_id="",
        trading_date="",
        indicator_id="r0_t04_forbidden_output_guard",
        raw_metric_name="forbidden_output_guard",
        raw_value=None,
        validity_status=VALID,
        reason_codes=("valid_no_blocker",),
        input_window_start=None,
        input_window_end=None,
        required_observation_count=0,
        actual_valid_observation_count=0,
        source_field_names=(),
    )


def check_raw_metric_lineage(
    lineage: Mapping[str, Any] | Sequence[str],
) -> RawMetricResult:
    sources = _lineage_sources(lineage)
    if "synthetic_in_memory_rows" in sources:
        return RawMetricResult(
            security_id="",
            trading_date="",
            indicator_id="r0_t04_lineage_guard",
            raw_metric_name="lineage_guard",
            raw_value=None,
            validity_status=VALID,
            reason_codes=("valid_no_blocker",),
            input_window_start=None,
            input_window_end=None,
            required_observation_count=0,
            actual_valid_observation_count=0,
            source_field_names=(),
        )
    readiness = check_d3_only_lineage(lineage)
    status = (
        VALID
        if readiness.status == READY
        else _validity_from_readiness(readiness.status)
    )
    return RawMetricResult(
        security_id="",
        trading_date="",
        indicator_id="r0_t04_lineage_guard",
        raw_metric_name="lineage_guard",
        raw_value=None,
        validity_status=status,
        reason_codes=readiness.reason_codes,
        input_window_start=None,
        input_window_end=None,
        required_observation_count=0,
        actual_valid_observation_count=0,
        source_field_names=(),
    )


def _window(
    rows: Sequence[Mapping[str, Any]], index: int, required: int
) -> tuple[Mapping[str, Any], ...]:
    start = max(0, index - required + 1)
    return tuple(rows[start : index + 1])


def _window_reason(
    window: Sequence[Mapping[str, Any]],
    required: int,
    fields: Sequence[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if len(window) < required:
        reasons.append("window_insufficient")
    if any(_bad_trading_row(row) for row in window):
        reasons.append("suspension_in_window")
    if any(_adjustment_failure(row) for row in window):
        reasons.append("adjustment_failure")
    if any(
        field not in row or row.get(field) is None for row in window for field in fields
    ):
        reasons.append("missing_required_field")
    return tuple(dict.fromkeys(reasons))


def _valid_result(
    row: Mapping[str, Any],
    indicator_id: str,
    raw_metric_name: str,
    raw_value: float,
    window: Sequence[Mapping[str, Any]],
    required: int,
    fields: Sequence[str],
    reason_codes: Sequence[str] = ("valid_no_blocker",),
) -> RawMetricResult:
    return RawMetricResult(
        security_id=str(row.get("security_id", "")),
        trading_date=str(row.get("trading_date", "")),
        indicator_id=indicator_id,
        raw_metric_name=raw_metric_name,
        raw_value=raw_value,
        validity_status=VALID,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        input_window_start=_window_start(window),
        input_window_end=_window_end(window),
        required_observation_count=required,
        actual_valid_observation_count=_actual_valid_count(window),
        source_field_names=tuple(fields),
    )


def _invalid_result(
    row: Mapping[str, Any],
    indicator_id: str,
    raw_metric_name: str,
    status: str,
    reason_codes: Sequence[str],
    window: Sequence[Mapping[str, Any]],
    required: int,
    fields: Sequence[str],
) -> RawMetricResult:
    return RawMetricResult(
        security_id=str(row.get("security_id", "")),
        trading_date=str(row.get("trading_date", "")),
        indicator_id=indicator_id,
        raw_metric_name=raw_metric_name,
        raw_value=None,
        validity_status=status,
        reason_codes=tuple(dict.fromkeys(reason_codes)) or ("unknown_not_false_guard",),
        input_window_start=_window_start(window),
        input_window_end=_window_end(window),
        required_observation_count=required,
        actual_valid_observation_count=_actual_valid_count(window),
        source_field_names=tuple(fields),
    )


def _with_window_flags(
    row: Mapping[str, Any],
    window: Sequence[Mapping[str, Any]],
    required: int,
) -> dict[str, Any]:
    context = dict(row)
    context["window_full"] = len(window) >= required
    context["valid_trading_days"] = _actual_valid_count(window)
    context["suspension_in_window"] = any(_bad_trading_row(item) for item in window)
    context["zero_volume_in_window"] = any(
        _zeroish(item.get("volume_shares")) or _zeroish(item.get("volume"))
        for item in window
    )
    context["zero_amount_in_window"] = any(
        _truthy(item.get("zero_amount_flag")) or _zeroish(item.get("amount_yuan"))
        for item in window
    )
    context["corporate_action_window"] = any(
        _truthy(item.get("corporate_action_flag")) for item in window
    )
    context["listing_pause_in_window"] = any(
        str(item.get("trading_status", "")).lower() == "listing_pause"
        for item in window
    )
    return context


def _validity_from_readiness(status: str) -> str:
    if status == BLOCKED:
        return BLOCKED
    if status == DIAGNOSTIC_REQUIRED:
        return DIAGNOSTIC_REQUIRED
    if status == READY:
        return VALID
    return UNKNOWN


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std_population(values: Sequence[float]) -> float:
    mean_value = _mean(values)
    return math.sqrt(sum((value - mean_value) ** 2 for value in values) / len(values))


def _date_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("trading_date", "")), str(row.get("security_id", ""))


def _window_start(window: Sequence[Mapping[str, Any]]) -> str | None:
    return str(window[0].get("trading_date")) if window else None


def _window_end(window: Sequence[Mapping[str, Any]]) -> str | None:
    return str(window[-1].get("trading_date")) if window else None


def _actual_valid_count(window: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for row in window if not _bad_trading_row(row))


def _bad_trading_row(row: Mapping[str, Any]) -> bool:
    status = str(row.get("trading_status", "")).lower()
    return status in {"suspended", "halted", "listing_pause", "停牌"} or _truthy(
        row.get("suspension_flag")
    )


def _adjustment_failure(row: Mapping[str, Any]) -> bool:
    return _truthy(row.get("adjustment_failure")) or str(
        row.get("adjustment_status", "")
    ).lower() in {"fail", "failed", "invalid"}


def _truthy(value: Any) -> bool:
    return value is True or str(value).lower() in {"true", "1", "yes", "y"}


def _zeroish(value: Any) -> bool:
    return value == 0 or value == 0.0 or str(value) == "0"


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
