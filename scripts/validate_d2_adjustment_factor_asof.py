"""Validate synthetic D2 adjustment factor rows against as-of gates."""

from __future__ import annotations

from typing import Any


class AdjustmentFactorAsOfValidationError(ValueError):
    """Raised when synthetic adjusted price rows fail D2-T04 gates."""


def validate_required_fields_only(
    row: dict[str, Any],
    required_fields: list[str],
) -> None:
    expected = set(required_fields)
    actual = set(row)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise AdjustmentFactorAsOfValidationError(
            f"row fields mismatch missing={missing} extra={extra}"
        )


def validate_primary_key_unique(
    rows: list[dict[str, Any]],
    primary_key_fields: list[str],
) -> None:
    keys = [tuple(row[field] for field in primary_key_fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise AdjustmentFactorAsOfValidationError("duplicate primary key")


def validate_security_ids_in_membership_alignment(
    rows: list[dict[str, Any]],
    membership_alignment: dict[str, Any],
) -> None:
    members = {row["security_id"] for row in membership_alignment["rows"]}
    for row in rows:
        if row["security_id"] not in members:
            raise AdjustmentFactorAsOfValidationError(
                "security_id outside membership alignment"
            )


def validate_adjusted_ohlc_order(row: dict[str, Any]) -> None:
    adj_open = row["adj_open"]
    adj_high = row["adj_high"]
    adj_low = row["adj_low"]
    adj_close = row["adj_close"]
    if adj_high < max(adj_open, adj_low, adj_close):
        raise AdjustmentFactorAsOfValidationError(
            "adj_high violates adjusted OHLC order"
        )
    if adj_low > min(adj_open, adj_high, adj_close):
        raise AdjustmentFactorAsOfValidationError(
            "adj_low violates adjusted OHLC order"
        )


def validate_adjustment_factor_positive(row: dict[str, Any]) -> None:
    if row["adjustment_factor"] <= 0:
        raise AdjustmentFactorAsOfValidationError("adjustment_factor is nonpositive")


def validate_adjustment_method_allowed(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    method = row["adjustment_method"]
    allowed = contract["controlled_vocabularies"]["adjustment_method"]["allowed_values"]
    if method not in allowed:
        raise AdjustmentFactorAsOfValidationError("adjustment_method is not allowed")
    if method == "unknown":
        raise AdjustmentFactorAsOfValidationError("adjustment_method is unknown")


def validate_adjustment_revision_allowed(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    revision = row["adjustment_revision"]
    allowed = contract["controlled_vocabularies"]["adjustment_revision"][
        "allowed_values"
    ]
    if revision not in allowed:
        raise AdjustmentFactorAsOfValidationError("adjustment_revision is not allowed")
    if revision == "unknown":
        raise AdjustmentFactorAsOfValidationError("adjustment_revision is unknown")


def validate_factor_as_of_time_present(row: dict[str, Any]) -> None:
    if not row.get("factor_as_of_time"):
        raise AdjustmentFactorAsOfValidationError("factor_as_of_time missing")


def validate_factor_as_of_time_not_future(
    row: dict[str, Any],
    observation_cutoff_by_trading_date: dict[str, str],
) -> None:
    cutoff = observation_cutoff_by_trading_date[row["trading_date"]]
    if str(row["factor_as_of_time"]) > str(cutoff):
        raise AdjustmentFactorAsOfValidationError(
            "factor_as_of_time after observation cutoff"
        )


def validate_source_registry_candidate_only(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    source_id = row["source_registry_id"]
    boundary = contract["candidate_source_boundary"]
    if source_id not in boundary["candidate_only_source_registry_ids"]:
        raise AdjustmentFactorAsOfValidationError("source is not candidate-only")
    if source_id in boundary["prohibited_source_registry_ids"]:
        raise AdjustmentFactorAsOfValidationError("source is prohibited")
    if (
        source_id == "BAOSTOCK"
        and boundary["baostock_formal_adjusted_price_source_allowed"]
    ):
        raise AdjustmentFactorAsOfValidationError(
            "BAOSTOCK marked as formal adjusted price source"
        )


def validate_no_raw_or_gap_fields(row: dict[str, Any]) -> None:
    prohibited = {
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "raw_gap",
        "adjusted_gap",
        "gap_attribution",
        "ticker",
        "exchange",
        "source_symbol",
        "vendor_payload",
    }
    extra = prohibited & set(row)
    if extra:
        raise AdjustmentFactorAsOfValidationError(
            f"prohibited fields present: {sorted(extra)}"
        )


def validate_corporate_action_flag_not_silently_false(row: dict[str, Any]) -> None:
    invalid_values = {False, 0, "false", "0", ""}
    if row.get("corporate_action_flag") in invalid_values:
        raise AdjustmentFactorAsOfValidationError(
            "corporate_action_flag silently converted"
        )


def validate_adjustment_rows(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    membership_alignment: dict[str, Any],
    observation_cutoff_by_trading_date: dict[str, str] | None = None,
) -> None:
    if not rows:
        raise AdjustmentFactorAsOfValidationError("rows are empty")
    if observation_cutoff_by_trading_date is None:
        raise AdjustmentFactorAsOfValidationError("observation cutoffs missing")
    required_fields = contract["required_fields"]
    for row in rows:
        validate_no_raw_or_gap_fields(row)
        validate_required_fields_only(row, required_fields)
        validate_security_ids_in_membership_alignment([row], membership_alignment)
        validate_adjusted_ohlc_order(row)
        validate_adjustment_factor_positive(row)
        validate_adjustment_method_allowed(row, contract)
        validate_adjustment_revision_allowed(row, contract)
        validate_factor_as_of_time_present(row)
        validate_factor_as_of_time_not_future(row, observation_cutoff_by_trading_date)
        validate_source_registry_candidate_only(row, contract)
        validate_corporate_action_flag_not_silently_false(row)
    validate_primary_key_unique(rows, contract["primary_key"])
