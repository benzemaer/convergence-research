"""D3-T10 field standardization helpers.

These helpers are pure transformations for provider field semantics. They do
not calculate PCVT metrics, states, labels, returns, or portfolio outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

TURNOVER_TOLERANCE_PCT = 0.05
VWAP_RANGE_TOLERANCE = 1e-8


@dataclass(frozen=True)
class QualityResult:
    status: str
    reasons: tuple[str, ...]


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(result):
        return None
    return result


def normalize_daily_fields(row: dict[str, Any]) -> dict[str, Any]:
    volume_raw = _number(row.get("vol"))
    amount_raw = _number(row.get("amount"))
    volume_shares = None if volume_raw is None else volume_raw * 100.0
    amount_yuan = None if amount_raw is None else amount_raw * 1000.0
    daily_vwap = None
    if volume_shares is not None and volume_shares > 0 and amount_yuan is not None:
        daily_vwap = amount_yuan / volume_shares
    return {
        "volume_raw": volume_raw,
        "volume_unit": "hand",
        "volume_shares": volume_shares,
        "amount_raw": amount_raw,
        "amount_unit": "thousand_yuan",
        "amount_yuan": amount_yuan,
        "daily_vwap": daily_vwap,
        "zero_volume_flag": volume_shares == 0 if volume_shares is not None else None,
        "zero_amount_flag": amount_yuan == 0 if amount_yuan is not None else None,
    }


def normalize_daily_basic_fields(row: dict[str, Any]) -> dict[str, Any]:
    total_share_raw = _number(row.get("total_share"))
    float_share_raw = _number(row.get("float_share"))
    free_share_raw = _number(row.get("free_share"))
    total_share_shares = None if total_share_raw is None else total_share_raw * 10000.0
    float_share_shares = None if float_share_raw is None else float_share_raw * 10000.0
    free_share_shares = None if free_share_raw is None else free_share_raw * 10000.0
    return {
        "total_share_raw": total_share_raw,
        "total_share_unit": "ten_thousand_shares",
        "total_share_shares": total_share_shares,
        "float_share_raw": float_share_raw,
        "float_share_unit": "ten_thousand_shares",
        "float_share_shares": float_share_shares,
        "free_share_raw": free_share_raw,
        "free_share_unit": "ten_thousand_shares",
        "free_share_shares": free_share_shares,
        "turnover_rate": _number(row.get("turnover_rate")),
        "turnover_rate_f": _number(row.get("turnover_rate_f")),
        "total_mv": _number(row.get("total_mv")),
        "circ_mv": _number(row.get("circ_mv")),
        "limit_status": row.get("limit_status"),
        "daily_basic_close": _number(row.get("close")),
    }


def combine_standardized_fields(
    daily_row: dict[str, Any], daily_basic_row: dict[str, Any]
) -> dict[str, Any]:
    result = normalize_daily_fields(daily_row)
    result.update(normalize_daily_basic_fields(daily_basic_row))
    volume_shares = result["volume_shares"]
    float_share_shares = result["float_share_shares"]
    free_share_shares = result["free_share_shares"]
    result["turnover_float"] = (
        None
        if volume_shares is None
        or float_share_shares is None
        or float_share_shares <= 0
        else volume_shares / float_share_shares
    )
    result["turnover_free"] = (
        None
        if volume_shares is None or free_share_shares is None or free_share_shares <= 0
        else volume_shares / free_share_shares
    )
    result["derived_turnover_rate_pct"] = (
        None if result["turnover_float"] is None else result["turnover_float"] * 100.0
    )
    result["derived_turnover_rate_f_pct"] = (
        None if result["turnover_free"] is None else result["turnover_free"] * 100.0
    )
    result.update(quality_statuses(result, daily_row))
    return result


def quality_statuses(
    standardized: dict[str, Any], raw_price_row: dict[str, Any]
) -> dict[str, str]:
    reasons: list[str] = []
    if standardized.get("volume_shares") is None or standardized["volume_shares"] < 0:
        reasons.append("invalid_volume_shares")
    if standardized.get("amount_yuan") is None or standardized["amount_yuan"] < 0:
        reasons.append("invalid_amount_yuan")
    amount_volume_unit_status = "valid" if not reasons else "fail"

    daily_vwap = standardized.get("daily_vwap")
    raw_low = _number(raw_price_row.get("low"))
    raw_high = _number(raw_price_row.get("high"))
    if daily_vwap is None:
        daily_vwap_range_status = "not_applicable_zero_or_missing_volume"
    elif raw_low is None or raw_high is None:
        daily_vwap_range_status = "unknown"
    elif (
        raw_low - VWAP_RANGE_TOLERANCE <= daily_vwap <= raw_high + VWAP_RANGE_TOLERANCE
    ):
        daily_vwap_range_status = "valid"
    else:
        daily_vwap_range_status = "fail"

    share_reasons = []
    total_share = standardized.get("total_share_shares")
    float_share = standardized.get("float_share_shares")
    free_share = standardized.get("free_share_shares")
    if total_share is None or total_share <= 0:
        share_reasons.append("invalid_total_share")
    if float_share is None or float_share <= 0:
        share_reasons.append("invalid_float_share")
    if free_share is None or free_share <= 0:
        share_reasons.append("invalid_free_share")
    if free_share is not None and float_share is not None and free_share > float_share:
        share_reasons.append("free_share_exceeds_float_share")
    if (
        float_share is not None
        and total_share is not None
        and float_share > total_share
    ):
        share_reasons.append("float_share_exceeds_total_share")
    share_field_status = "valid" if not share_reasons else "fail"

    turnover_values = (
        standardized.get("turnover_float"),
        standardized.get("turnover_free"),
    )
    turnover_field_status = (
        "valid"
        if all(value is not None and value >= 0 for value in turnover_values)
        else "unknown"
    )
    provider_turnover_crosscheck_status = provider_turnover_crosscheck(
        standardized
    ).status
    return {
        "amount_volume_unit_status": amount_volume_unit_status,
        "daily_vwap_range_status": daily_vwap_range_status,
        "share_field_status": share_field_status,
        "turnover_field_status": turnover_field_status,
        "provider_turnover_crosscheck_status": provider_turnover_crosscheck_status,
    }


def provider_turnover_crosscheck(standardized: dict[str, Any]) -> QualityResult:
    reasons: list[str] = []
    for provider_key, derived_key, reason in (
        (
            "turnover_rate",
            "derived_turnover_rate_pct",
            "turnover_rate_mismatch",
        ),
        (
            "turnover_rate_f",
            "derived_turnover_rate_f_pct",
            "turnover_rate_f_mismatch",
        ),
    ):
        provider_value = standardized.get(provider_key)
        derived_value = standardized.get(derived_key)
        if provider_value is None or derived_value is None:
            reasons.append(f"{provider_key}_missing")
        elif abs(provider_value - derived_value) > TURNOVER_TOLERANCE_PCT:
            reasons.append(reason)
    if not reasons:
        return QualityResult("valid", ())
    if all(reason.endswith("_missing") for reason in reasons):
        return QualityResult("unknown", tuple(reasons))
    return QualityResult("fail", tuple(reasons))


def forbidden_output_names() -> set[str]:
    return {
        "pcvt_values",
        "pcvt_scores",
        "pcvt_states",
        "state_intervals",
        "future_labels",
        "future_returns",
        "breakout_direction",
        "backtest",
        "portfolio",
        "formal_data_version",
    }
