"""Validate synthetic D2 raw market price rows against materialization gates."""

from __future__ import annotations

from typing import Any


class RawMarketPriceValidationError(ValueError):
    """Raised when synthetic raw market price rows fail D2-T03 gates."""


def validate_required_fields_only(
    row: dict[str, Any], required_fields: list[str]
) -> None:
    expected = set(required_fields)
    actual = set(row)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RawMarketPriceValidationError(
            f"row fields mismatch missing={missing} extra={extra}"
        )


def validate_primary_key_unique(
    rows: list[dict[str, Any]],
    primary_key_fields: list[str],
) -> None:
    keys = [tuple(row[field] for field in primary_key_fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise RawMarketPriceValidationError("duplicate primary key")


def validate_security_ids_in_membership_alignment(
    rows: list[dict[str, Any]],
    membership_alignment: dict[str, Any],
) -> None:
    members = {row["security_id"] for row in membership_alignment["rows"]}
    for row in rows:
        if row["security_id"] not in members:
            raise RawMarketPriceValidationError("security_id outside membership")


def validate_ohlc_order(row: dict[str, Any]) -> None:
    raw_open = row["raw_open"]
    raw_high = row["raw_high"]
    raw_low = row["raw_low"]
    raw_close = row["raw_close"]
    if raw_high < max(raw_open, raw_low, raw_close):
        raise RawMarketPriceValidationError("raw_high violates OHLC order")
    if raw_low > min(raw_open, raw_high, raw_close):
        raise RawMarketPriceValidationError("raw_low violates OHLC order")


def validate_volume_amount_nonnegative(row: dict[str, Any]) -> None:
    if row["volume"] < 0:
        raise RawMarketPriceValidationError("volume is negative")
    if row["amount"] < 0:
        raise RawMarketPriceValidationError("amount is negative")


def validate_source_registry_candidate_only(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    source_id = row["source_registry_id"]
    boundary = contract["candidate_source_boundary"]
    if source_id not in boundary["candidate_only_source_registry_ids"]:
        raise RawMarketPriceValidationError("source is not candidate-only allowed")
    if source_id in boundary["prohibited_source_registry_ids"]:
        raise RawMarketPriceValidationError("source is prohibited")


def validate_observed_at_present_and_not_trading_date(row: dict[str, Any]) -> None:
    observed_at = row.get("observed_at")
    if not observed_at:
        raise RawMarketPriceValidationError("observed_at missing")
    if str(observed_at) == str(row["trading_date"]):
        raise RawMarketPriceValidationError("observed_at equals trading_date")


def validate_no_adjusted_fields(row: dict[str, Any]) -> None:
    prohibited = {
        "ticker",
        "exchange",
        "source_symbol",
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_close",
        "adjustment_factor",
        "gap_attribution",
    }
    extra = prohibited & set(row)
    if extra:
        raise RawMarketPriceValidationError(
            f"prohibited fields present: {sorted(extra)}"
        )


def validate_status_unknown_not_false(row: dict[str, Any]) -> None:
    invalid_trading_status = {False, 0, "false", "0", "active", ""}
    invalid_limit_status = {False, 0, "false", "0", "not_at_limit", ""}
    if row.get("trading_status") in invalid_trading_status:
        raise RawMarketPriceValidationError("trading_status silently converted")
    if row.get("price_limit_status") in invalid_limit_status:
        raise RawMarketPriceValidationError("price_limit_status silently converted")


def validate_raw_market_price_rows(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    membership_alignment: dict[str, Any],
) -> None:
    if not rows:
        raise RawMarketPriceValidationError("rows are empty")
    required_fields = contract["required_fields"]
    for row in rows:
        validate_no_adjusted_fields(row)
        validate_required_fields_only(row, required_fields)
        validate_security_ids_in_membership_alignment([row], membership_alignment)
        validate_ohlc_order(row)
        validate_volume_amount_nonnegative(row)
        validate_source_registry_candidate_only(row, contract)
        validate_observed_at_present_and_not_trading_date(row)
        validate_status_unknown_not_false(row)
    validate_primary_key_unique(rows, contract["primary_key"])
