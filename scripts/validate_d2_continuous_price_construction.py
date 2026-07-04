"""Validate synthetic D2 continuous research price construction rows."""

from __future__ import annotations

from math import isclose
from typing import Any


class ContinuousPriceConstructionValidationError(ValueError):
    """Raised when synthetic continuous price rows fail D2-T05 gates."""


def _declared_row_fields(contract: dict[str, Any]) -> list[str]:
    fields = (
        contract["required_fields"]
        + contract["synthetic_input_raw_fields"]
        + contract["synthetic_input_factor_fields"]
    )
    return list(dict.fromkeys(fields))


def validate_required_fields_only(
    row: dict[str, Any],
    required_fields: list[str],
) -> None:
    expected = set(required_fields)
    actual = set(row)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContinuousPriceConstructionValidationError(
            f"row fields mismatch missing={missing} extra={extra}"
        )


def validate_primary_key_unique(
    rows: list[dict[str, Any]],
    primary_key_fields: list[str],
) -> None:
    keys = [tuple(row[field] for field in primary_key_fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise ContinuousPriceConstructionValidationError("duplicate primary key")


def validate_security_ids_in_membership_alignment(
    rows: list[dict[str, Any]],
    membership_alignment: dict[str, Any],
) -> None:
    members = {row["security_id"] for row in membership_alignment["rows"]}
    for row in rows:
        if row["security_id"] not in members:
            raise ContinuousPriceConstructionValidationError(
                "security_id outside membership alignment"
            )


def validate_adjustment_factor_positive(row: dict[str, Any]) -> None:
    if row["adjustment_factor"] <= 0:
        raise ContinuousPriceConstructionValidationError(
            "adjustment_factor is nonpositive"
        )


def validate_factor_as_of_time_present(row: dict[str, Any]) -> None:
    if not row.get("factor_as_of_time"):
        raise ContinuousPriceConstructionValidationError("factor_as_of_time missing")


def validate_factor_as_of_time_not_future(
    row: dict[str, Any],
    observation_cutoff_by_trading_date: dict[str, str],
) -> None:
    cutoff = observation_cutoff_by_trading_date[row["trading_date"]]
    if str(row["factor_as_of_time"]) > str(cutoff):
        raise ContinuousPriceConstructionValidationError(
            "factor_as_of_time after observation cutoff"
        )


def validate_adjusted_ohlc_order(row: dict[str, Any]) -> None:
    adj_open = row["adj_open"]
    adj_high = row["adj_high"]
    adj_low = row["adj_low"]
    adj_close = row["adj_close"]
    if adj_high < max(adj_open, adj_low, adj_close):
        raise ContinuousPriceConstructionValidationError(
            "adj_high violates adjusted OHLC order"
        )
    if adj_low > min(adj_open, adj_high, adj_close):
        raise ContinuousPriceConstructionValidationError(
            "adj_low violates adjusted OHLC order"
        )


def _assert_close(
    actual: float, expected: float, abs_tol: float, rel_tol: float
) -> None:
    if not isclose(actual, expected, abs_tol=abs_tol, rel_tol=rel_tol):
        raise ContinuousPriceConstructionValidationError(
            f"value mismatch actual={actual} expected={expected}"
        )


def validate_identity_no_adjustment_consistency(
    row: dict[str, Any],
    tolerance_abs: float,
    tolerance_rel: float,
) -> None:
    if row["adjustment_method"] != "identity_no_adjustment":
        return
    _assert_close(row["adjustment_factor"], 1.0, tolerance_abs, tolerance_rel)
    for raw_field, adj_field in [
        ("raw_open", "adj_open"),
        ("raw_high", "adj_high"),
        ("raw_low", "adj_low"),
        ("raw_close", "adj_close"),
    ]:
        _assert_close(row[adj_field], row[raw_field], tolerance_abs, tolerance_rel)


def validate_multiplicative_factor_consistency(
    row: dict[str, Any],
    tolerance_abs: float,
    tolerance_rel: float,
) -> None:
    for raw_field, adj_field in [
        ("raw_open", "adj_open"),
        ("raw_high", "adj_high"),
        ("raw_low", "adj_low"),
        ("raw_close", "adj_close"),
    ]:
        expected = row[raw_field] * row["adjustment_factor"]
        _assert_close(row[adj_field], expected, tolerance_abs, tolerance_rel)


def validate_reverse_check_to_raw_prices(
    row: dict[str, Any],
    tolerance_abs: float,
    tolerance_rel: float,
) -> None:
    for raw_field, adj_field in [
        ("raw_open", "adj_open"),
        ("raw_high", "adj_high"),
        ("raw_low", "adj_low"),
        ("raw_close", "adj_close"),
    ]:
        recovered = row[adj_field] / row["adjustment_factor"]
        _assert_close(recovered, row[raw_field], tolerance_abs, tolerance_rel)


def validate_adjustment_method_and_revision_not_unknown(row: dict[str, Any]) -> None:
    if row["adjustment_method"] == "unknown":
        raise ContinuousPriceConstructionValidationError("adjustment_method unknown")
    if row["adjustment_revision"] == "unknown":
        raise ContinuousPriceConstructionValidationError("adjustment_revision unknown")


def validate_corporate_action_flag_not_silently_false(row: dict[str, Any]) -> None:
    invalid_values = {False, 0, "false", "0", ""}
    if row.get("corporate_action_flag") in invalid_values:
        raise ContinuousPriceConstructionValidationError(
            "corporate_action_flag silently converted"
        )


def validate_no_gap_event_label_or_future_fields(row: dict[str, Any]) -> None:
    prohibited = {
        "raw_gap",
        "adjusted_gap",
        "gap_attribution",
        "future_return",
        "label",
        "event_type",
        "pcvt_state",
        "ticker",
        "exchange",
        "source_symbol",
        "vendor_payload",
        "formal_ingestion_authorized",
        "source_formal_ingestion_authorized",
    }
    extra = prohibited & set(row)
    if extra:
        raise ContinuousPriceConstructionValidationError(
            f"prohibited fields present: {sorted(extra)}"
        )


def validate_continuous_price_rows(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    membership_alignment: dict[str, Any],
    observation_cutoff_by_trading_date: dict[str, str],
) -> None:
    if not rows:
        raise ContinuousPriceConstructionValidationError("rows are empty")
    tolerance_abs = contract["construction_rule"]["reverse_check_tolerance_abs"]
    tolerance_rel = contract["construction_rule"]["reverse_check_tolerance_rel"]
    declared_fields = _declared_row_fields(contract)
    for row in rows:
        validate_no_gap_event_label_or_future_fields(row)
        validate_required_fields_only(row, declared_fields)
        validate_security_ids_in_membership_alignment([row], membership_alignment)
        validate_adjustment_factor_positive(row)
        validate_factor_as_of_time_present(row)
        validate_factor_as_of_time_not_future(row, observation_cutoff_by_trading_date)
        validate_adjusted_ohlc_order(row)
        validate_adjustment_method_and_revision_not_unknown(row)
        validate_corporate_action_flag_not_silently_false(row)
        validate_identity_no_adjustment_consistency(row, tolerance_abs, tolerance_rel)
        validate_multiplicative_factor_consistency(row, tolerance_abs, tolerance_rel)
        validate_reverse_check_to_raw_prices(row, tolerance_abs, tolerance_rel)
    validate_primary_key_unique(rows, contract["primary_key"])
