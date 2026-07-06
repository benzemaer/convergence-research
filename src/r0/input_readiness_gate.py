from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

READY = "ready"
UNKNOWN = "unknown"
DIAGNOSTIC_REQUIRED = "diagnostic_required"
BLOCKED = "blocked"

PROHIBITED_SOURCES = (
    "d1.raw_market_prices",
    "d2.adjusted_market_prices",
    "d2.market_price_quality_flags",
    "d2.membership_alignment",
    "data/raw",
    "data/external",
    "MarketDB",
    ".day",
)
ALLOWED_SOURCES = (
    "d3_candidate_daily_observation",
    "d3_t08_research_dataset_registry",
    "d3_quality_readiness_contract",
    "r0_t01_pcvt_candidate_spec",
)
SHARE_COMPARABILITY_ACTIONS = {
    "bonus_share",
    "split",
    "reverse_split",
    "rights_issue",
    "share_change",
}


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    reason_codes: tuple[str, ...]
    indicator_id: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "indicator_id": self.indicator_id,
            "details": dict(self.details),
        }


def evaluate_c2_readiness(row_or_context: Mapping[str, Any]) -> ReadinessResult:
    context = dict(row_or_context)
    reasons = _missing_reasons(
        context,
        (
            "amount",
            "volume",
            "amount_unit",
            "volume_unit",
            "amount_volume_unit_status",
            "raw_low",
            "raw_high",
            "daily_vwap_range_status",
            "corporate_action_flag",
            "adjusted_vwap_policy",
            "trading_status",
        ),
    )

    if _is_unknown(context.get("amount_unit")):
        reasons.append("amount_unit_unknown")
    if _is_unknown(context.get("volume_unit")):
        reasons.append("volume_unit_unknown")
    if _is_fail_or_unknown(context.get("amount_volume_unit_status")):
        reasons.append("amount_volume_unit_status_fail")

    daily_vwap_status = context.get("daily_vwap_range_status")
    if _is_unknown(daily_vwap_status):
        reasons.append("daily_vwap_range_unknown")
    elif _is_fail(daily_vwap_status):
        reasons.append("daily_vwap_range_fail")

    if _truthy(context.get("suspension_in_window")) or _is_suspended(
        context.get("trading_status")
    ):
        reasons.append("suspension_in_window")
    if _truthy(context.get("zero_volume_in_window")) or _zeroish(context.get("volume")):
        reasons.append("zero_volume_in_window")

    crosses_corporate_action = _truthy(context.get("corporate_action_window"))
    has_adjusted_vwap_policy = _has_policy(context.get("adjusted_vwap_policy"))
    has_common_basis = _has_policy(context.get("common_corporate_action_basis_policy"))
    if crosses_corporate_action and not (has_adjusted_vwap_policy or has_common_basis):
        reasons.append("adjusted_vwap_policy_missing")
        reasons.append("corporate_action_window_without_common_basis")
    if crosses_corporate_action and _truthy(
        context.get("raw_vwap_used_as_adjusted_vwap")
    ):
        reasons.append("corporate_action_window_without_common_basis")

    return _result("C2_AdjVWAPSpread_5_60", reasons)


def evaluate_v1_readiness(row_or_context: Mapping[str, Any]) -> ReadinessResult:
    context = dict(row_or_context)
    reasons = _missing_reasons(
        context,
        (
            "volume",
            "volume_unit",
            "trading_status",
            "corporate_action_flag",
            "suspension_flag",
        ),
    )

    if not _truthy(context.get("window_full")):
        reasons.append("window_not_full")
    if (
        context.get("valid_trading_days") is not None
        and context.get("valid_trading_days") < 80
    ):
        reasons.append("window_not_full")
    if (
        context.get("listing_age_trading_days") is not None
        and context.get("listing_age_trading_days") < 80
    ):
        reasons.append("listing_age_insufficient")
    if _is_unknown(context.get("volume_unit")):
        reasons.append("volume_unit_unknown")
    if (
        _truthy(context.get("suspension_in_window"))
        or _truthy(context.get("suspension_flag"))
        or _is_suspended(context.get("trading_status"))
    ):
        reasons.append("suspension_in_window")
    if _truthy(context.get("zero_volume_in_window")) or _zeroish(context.get("volume")):
        reasons.append("zero_volume_in_window")

    if _has_share_comparability_event(context):
        has_policy = (
            _has_policy(context.get("adjusted_volume"))
            or _has_policy(context.get("common_share_basis_policy"))
            or _has_policy(context.get("volume_comparability_policy"))
        )
        if not has_policy:
            reasons.append("corporate_action_volume_comparability_policy_missing")

    return _result("V1_VolShrink20_60", reasons)


def check_d3_only_lineage(
    lineage: Mapping[str, Any] | Sequence[str],
) -> ReadinessResult:
    sources = _lineage_sources(lineage)
    reasons: list[str] = []
    if not sources:
        reasons.append("d3_lineage_missing")
    if any(_is_prohibited_source(source) for source in sources):
        reasons.append("direct_d1_d2_bypass_detected")
    if not any(source in ALLOWED_SOURCES for source in sources):
        reasons.append("d3_lineage_missing")
    return _result("lineage", reasons)


def assert_unknown_guard(value: Any) -> ReadinessResult:
    reasons: list[str] = []
    if value is False or value == 0:
        reasons.append("unknown_not_false_guard")
    if value in {"previous", "mean", "filled_previous", "filled_mean"}:
        reasons.append("unknown_not_false_guard")
    return _result("unknown_guard", reasons)


def _result(indicator_id: str, reasons: Sequence[str]) -> ReadinessResult:
    unique_reasons = tuple(dict.fromkeys(reasons))
    if not unique_reasons:
        return ReadinessResult(READY, ("ready_no_blocker",), indicator_id)
    if any(
        reason
        in {
            "direct_d1_d2_bypass_detected",
            "daily_vwap_range_fail",
            "amount_volume_unit_status_fail",
        }
        for reason in unique_reasons
    ):
        status = BLOCKED
    elif any(
        reason in {"suspension_in_window", "zero_volume_in_window"}
        for reason in unique_reasons
    ):
        status = DIAGNOSTIC_REQUIRED
    else:
        status = UNKNOWN
    return ReadinessResult(status, unique_reasons, indicator_id)


def _missing_reasons(context: Mapping[str, Any], required: Sequence[str]) -> list[str]:
    return [
        "missing_required_field"
        for field_name in required
        if field_name not in context or context.get(field_name) is None
    ]


def _is_unknown(value: Any) -> bool:
    return value is None or str(value).lower() in {"", "unknown", "missing", "na"}


def _is_fail(value: Any) -> bool:
    return str(value).lower() in {"fail", "failed", "invalid", "error"}


def _is_fail_or_unknown(value: Any) -> bool:
    return _is_unknown(value) or _is_fail(value)


def _truthy(value: Any) -> bool:
    return value is True or str(value).lower() in {"true", "1", "yes", "y"}


def _zeroish(value: Any) -> bool:
    return value == 0 or value == 0.0 or str(value) == "0"


def _is_suspended(value: Any) -> bool:
    return str(value).lower() in {"suspended", "halted", "停牌"}


def _has_policy(value: Any) -> bool:
    return value not in {None, False, "", "unknown", "missing", "none"}


def _has_share_comparability_event(context: Mapping[str, Any]) -> bool:
    if _truthy(context.get("share_comparability_corporate_action_in_window")):
        return True
    events = context.get("corporate_action_types_in_window", ())
    if isinstance(events, str):
        events = (events,)
    return any(str(event) in SHARE_COMPARABILITY_ACTIONS for event in events)


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
