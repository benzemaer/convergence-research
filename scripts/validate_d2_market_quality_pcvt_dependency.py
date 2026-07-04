"""Synthetic validators for D2-T07 market quality and PCVT dependencies."""

from __future__ import annotations

from typing import Any


class MarketQualityPCVTValidationError(ValueError):
    """Raised when a synthetic row violates D2-T07 dependency gates."""


FUTURE_FIELDS = {
    "future_return",
    "label",
    "breakout_direction",
    "target",
    "outcome",
    "portfolio_return",
    "backtest_signal",
}
ROW_LEVEL_PAYLOAD_FIELDS = {
    "raw_rows",
    "qfq_rows",
    "hfq_rows",
    "price_rows",
    "vendor_payload",
    "raw_response_body",
    "raw_response_rows",
    "rows",
}
TRADING_CONSTRAINTS = {
    "normal_trading",
    "suspended",
    "zero_volume",
    "limit_up",
    "limit_down",
    "one_price_limit_up",
    "one_price_limit_down",
    "reopen_after_suspension",
    "unknown",
}
GAP_ATTRIBUTIONS = {
    "none",
    "market_gap",
    "corporate_action_mechanical_gap",
    "suspension_reopen_gap",
    "limit_constraint_gap",
    "code_mapping_gap",
    "unknown",
}


def _require_present(row: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if row.get(field) in (None, "")]
    if missing:
        raise MarketQualityPCVTValidationError(f"missing fields: {missing}")


def validate_no_future_fields(row: dict[str, Any]) -> None:
    extra = FUTURE_FIELDS & set(row)
    if extra:
        raise MarketQualityPCVTValidationError(
            f"future outcome fields present: {sorted(extra)}"
        )
    if (
        row.get("d3_generated") is True
        or row.get("formal_ingestion_authorized") is True
    ):
        raise MarketQualityPCVTValidationError("formal generation marker present")


def validate_no_row_level_price_payload(payload: dict[str, Any]) -> None:
    extra = ROW_LEVEL_PAYLOAD_FIELDS & set(payload)
    if extra:
        raise MarketQualityPCVTValidationError(
            f"row-level payload fields present: {sorted(extra)}"
        )


def validate_raw_ohlcv_integrity(row: dict[str, Any]) -> None:
    validate_no_future_fields(row)
    _require_present(
        row,
        [
            "security_id",
            "trading_date",
            "raw_open",
            "raw_high",
            "raw_low",
            "raw_close",
            "volume",
            "amount",
            "trading_status",
            "price_limit_status",
        ],
    )
    if row["raw_high"] < max(row["raw_open"], row["raw_close"]):
        raise MarketQualityPCVTValidationError("raw_high violates OHLC order")
    if row["raw_low"] > min(row["raw_open"], row["raw_close"]):
        raise MarketQualityPCVTValidationError("raw_low violates OHLC order")
    if row["raw_high"] < row["raw_low"]:
        raise MarketQualityPCVTValidationError("raw_high below raw_low")
    if row["raw_close"] <= 0:
        raise MarketQualityPCVTValidationError("raw_close nonpositive")
    if row["volume"] < 0:
        raise MarketQualityPCVTValidationError("volume negative")
    if row["amount"] < 0:
        raise MarketQualityPCVTValidationError("amount negative")
    classify_trading_constraint(row)


def validate_continuous_ohlc_integrity(row: dict[str, Any]) -> None:
    validate_no_future_fields(row)
    _require_present(
        row,
        [
            "adj_open",
            "adj_high",
            "adj_low",
            "adj_close",
            "adjustment_factor",
            "adjustment_method",
            "adjustment_revision",
        ],
    )
    if row["adj_high"] < max(row["adj_open"], row["adj_close"]):
        raise MarketQualityPCVTValidationError("adj_high violates OHLC order")
    if row["adj_low"] > min(row["adj_open"], row["adj_close"]):
        raise MarketQualityPCVTValidationError("adj_low violates OHLC order")
    if row["adj_high"] < row["adj_low"]:
        raise MarketQualityPCVTValidationError("adj_high below adj_low")
    if row["adj_close"] <= 0:
        raise MarketQualityPCVTValidationError("adj_close nonpositive")
    if row["adjustment_factor"] <= 0:
        raise MarketQualityPCVTValidationError("adjustment_factor nonpositive")
    if row["adjustment_method"] == "unknown":
        raise MarketQualityPCVTValidationError("adjustment_method unknown")
    if row["adjustment_revision"] == "unknown":
        raise MarketQualityPCVTValidationError("adjustment_revision unknown")
    if row.get("qfq_or_hfq_used_as_raw_fact") is True:
        raise MarketQualityPCVTValidationError("adjusted price used as raw fact")
    if row.get("implied_factor_marked_vendor_official") is True:
        raise MarketQualityPCVTValidationError("implied factor marked official")


def classify_trading_constraint(row: dict[str, Any]) -> dict[str, Any]:
    if "trading_status" not in row:
        raise MarketQualityPCVTValidationError("missing trading_status")
    if "price_limit_status" not in row:
        raise MarketQualityPCVTValidationError("missing price_limit_status")
    status = row["trading_status"]
    limit_status = row["price_limit_status"]
    if status == "unknown":
        raise MarketQualityPCVTValidationError("unknown trading status as normal")
    if status not in TRADING_CONSTRAINTS:
        raise MarketQualityPCVTValidationError("invalid trading status")
    if status == "suspended":
        return {
            "constraint": "suspended",
            "valid_indicator_day": False,
            "readiness": "diagnostic_required",
        }
    if status == "zero_volume":
        return {
            "constraint": "zero_volume",
            "ordinary_low_participation": False,
            "readiness": "diagnostic_required",
        }
    if status in {
        "limit_up",
        "limit_down",
        "one_price_limit_up",
        "one_price_limit_down",
    }:
        return {
            "constraint": status,
            "valid_indicator_day": True,
            "readiness": "diagnostic_required",
        }
    if limit_status in {
        "limit_up",
        "limit_down",
        "one_price_limit_up",
        "one_price_limit_down",
    }:
        return {
            "constraint": limit_status,
            "valid_indicator_day": True,
            "readiness": "diagnostic_required",
        }
    return {
        "constraint": "normal_trading",
        "valid_indicator_day": True,
        "readiness": "ready",
    }


def classify_gap_attribution(row: dict[str, Any]) -> str:
    attribution = row.get("gap_attribution")
    if attribution not in GAP_ATTRIBUTIONS:
        raise MarketQualityPCVTValidationError("invalid gap attribution")
    if attribution == "unknown" and row.get("treated_as_none"):
        raise MarketQualityPCVTValidationError("unknown gap treated as none")
    if attribution == "market_gap" and row.get("corporate_action_flag"):
        raise MarketQualityPCVTValidationError(
            "corporate action mechanical gap treated as market_gap"
        )
    return str(attribution)


def validate_amount_volume_units(row: dict[str, Any]) -> str:
    amount_unit = row.get("amount_unit")
    volume_unit = row.get("volume_unit")
    if amount_unit not in {"yuan", "thousand_yuan", "ten_thousand_yuan", "unknown"}:
        raise MarketQualityPCVTValidationError("invalid amount_unit")
    if volume_unit not in {"share", "lot", "unknown"}:
        raise MarketQualityPCVTValidationError("invalid volume_unit")
    if amount_unit == "unknown" or volume_unit == "unknown":
        return "unit_validation_required"
    return "ready"


def _amount_yuan(row: dict[str, Any]) -> float:
    amount = float(row["amount"])
    unit = row["amount_unit"]
    if unit == "yuan":
        return amount
    if unit == "thousand_yuan":
        return amount * 1000
    if unit == "ten_thousand_yuan":
        return amount * 10000
    raise MarketQualityPCVTValidationError("amount_unit unknown")


def _volume_shares(row: dict[str, Any]) -> float:
    volume = float(row["volume"])
    unit = row["volume_unit"]
    if unit == "share":
        return volume
    if unit == "lot":
        return volume * 100
    raise MarketQualityPCVTValidationError("volume_unit unknown")


def validate_daily_vwap_range(row: dict[str, Any]) -> None:
    validate_amount_volume_units(row)
    volume = _volume_shares(row)
    if volume <= 0:
        raise MarketQualityPCVTValidationError("volume nonpositive for VWAP")
    vwap = _amount_yuan(row) / volume
    if not row["raw_low"] <= vwap <= row["raw_high"]:
        raise MarketQualityPCVTValidationError("amount_volume_unit_mismatch")


def validate_pcvt_indicator_readiness(
    indicator_id: str, context: dict[str, Any]
) -> str:
    if indicator_id in {
        "P1_NATR14",
        "P2_LogRange20",
        "C1_LogMASpread_5_60",
        "T1_ER20",
        "T2_AbsTrendT20",
    }:
        if context.get("has_full_window") and context.get("continuous_quality_pass"):
            return "ready_after_full_window_pull"
        return "diagnostic_required"
    if indicator_id == "C2_AdjVWAPSpread_5_60":
        if (
            context.get("amount_unit") == "unknown"
            or context.get("volume_unit") == "unknown"
        ):
            return "unit_validation_required"
        if not context.get("adjusted_vwap_policy_accepted"):
            return (
                "partial_pending_amount_volume_unit_validation_and_adjusted_vwap_policy"
            )
        return "ready_after_full_window_pull"
    if indicator_id == "V1_VolShrink20_60":
        if context.get("volume_unit") == "unknown":
            return "unit_validation_required"
        if not context.get("adjusted_volume_policy_accepted"):
            return "partial_pending_volume_unit_validation_and_adjusted_volume_policy"
        return "ready_after_full_window_pull"
    if indicator_id == "V2_AmountLevel20Pct":
        if context.get("amount_unit") == "unknown":
            return "unit_validation_required"
        if not context.get("strict_past_percentile_history"):
            return "diagnostic_required"
        return "ready_after_amount_unit_validation_and_history_window_pull"
    raise MarketQualityPCVTValidationError(f"unknown indicator_id {indicator_id}")
