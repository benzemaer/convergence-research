"""Validate synthetic D2 candidate market snapshot probe rows."""

from __future__ import annotations

from math import isclose
from typing import Any


class CandidateMarketSnapshotProbeValidationError(ValueError):
    """Raised when synthetic candidate market snapshot probe rows fail gates."""


def validate_required_fields_only(
    row: dict[str, Any],
    required_fields: list[str],
) -> None:
    expected = set(required_fields)
    actual = set(row)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CandidateMarketSnapshotProbeValidationError(
            f"row fields mismatch missing={missing} extra={extra}"
        )


def validate_security_ids_in_membership_alignment(
    rows: list[dict[str, Any]],
    membership_alignment: dict[str, Any],
) -> None:
    members = {row["security_id"] for row in membership_alignment["rows"]}
    for row in rows:
        if row["security_id"] not in members:
            raise CandidateMarketSnapshotProbeValidationError(
                "security_id outside membership alignment"
            )


def validate_source_registry_candidate_only(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    source_id = row["source_registry_id"]
    if source_id not in contract["candidate_source_registry_ids"]:
        raise CandidateMarketSnapshotProbeValidationError("source is not candidate")
    if source_id in contract["prohibited_source_registry_ids"]:
        raise CandidateMarketSnapshotProbeValidationError("source is prohibited")


def validate_retrieved_and_observed_at_present(row: dict[str, Any]) -> None:
    if not row.get("retrieved_at"):
        raise CandidateMarketSnapshotProbeValidationError("retrieved_at missing")
    if not row.get("observed_at"):
        raise CandidateMarketSnapshotProbeValidationError("observed_at missing")


def validate_source_snapshot_and_hash_present(row: dict[str, Any]) -> None:
    if not row.get("source_snapshot_id"):
        raise CandidateMarketSnapshotProbeValidationError("source_snapshot_id missing")
    if not row.get("raw_response_sha256"):
        raise CandidateMarketSnapshotProbeValidationError("raw_response_sha256 missing")


def validate_raw_close_positive_for_implied_factor(row: dict[str, Any]) -> None:
    has_implied = (
        row.get("implied_qfq_factor") is not None
        or row.get("implied_hfq_factor") is not None
    )
    if has_implied and row["raw_close"] <= 0:
        raise CandidateMarketSnapshotProbeValidationError(
            "raw_close nonpositive for implied factor"
        )


def _assert_close(
    actual: float, expected: float, abs_tol: float, rel_tol: float
) -> None:
    if not isclose(actual, expected, abs_tol=abs_tol, rel_tol=rel_tol):
        raise CandidateMarketSnapshotProbeValidationError(
            f"value mismatch actual={actual} expected={expected}"
        )


def validate_implied_factor_consistency(
    row: dict[str, Any],
    tolerance_abs: float,
    tolerance_rel: float,
) -> None:
    if row.get("implied_qfq_factor") is not None:
        _assert_close(
            row["implied_qfq_factor"],
            row["qfq_close"] / row["raw_close"],
            tolerance_abs,
            tolerance_rel,
        )
    if row.get("implied_hfq_factor") is not None:
        _assert_close(
            row["implied_hfq_factor"],
            row["hfq_close"] / row["raw_close"],
            tolerance_abs,
            tolerance_rel,
        )
    if (
        not row["has_vendor_adjustment_factor"]
        and row.get("vendor_adjustment_factor") == "official_from_implied_factor"
    ):
        raise CandidateMarketSnapshotProbeValidationError(
            "implied factor marked as vendor official factor"
        )


def validate_history_revision_class_allowed(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    allowed = contract["controlled_vocabularies"]["history_revision_class"][
        "allowed_values"
    ]
    if row["history_revision_class"] not in allowed:
        raise CandidateMarketSnapshotProbeValidationError(
            "history_revision_class is not allowed"
        )


def validate_research_use_tier_allowed(
    row: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    allowed = contract["controlled_vocabularies"]["research_use_tier"]["allowed_values"]
    if row["research_use_tier"] not in allowed:
        raise CandidateMarketSnapshotProbeValidationError(
            "research_use_tier is not allowed"
        )


def validate_no_formal_use_without_asof_revision(row: dict[str, Any]) -> None:
    if (
        row["history_revision_class"] == "point_in_time_candidate"
        and not row["has_factor_as_of_time"]
        and not row["has_revision_timestamp"]
    ):
        raise CandidateMarketSnapshotProbeValidationError(
            "point_in_time_candidate lacks as-of and revision evidence"
        )
    if row["research_use_tier"] == "formal_candidate_after_review" and (
        not row["has_factor_as_of_time"]
        or not row["has_revision_timestamp"]
        or not row["source_snapshot_id"]
        or not row["raw_response_sha256"]
    ):
        raise CandidateMarketSnapshotProbeValidationError(
            "formal_candidate_after_review lacks complete evidence"
        )


def validate_no_raw_qfq_hfq_substitution(row: dict[str, Any]) -> None:
    if row.get("blocking_reason") == "qfq_or_hfq_marked_as_raw_trading_fact":
        raise CandidateMarketSnapshotProbeValidationError(
            "qfq/hfq marked as raw trading fact"
        )


def validate_no_future_or_label_fields(row: dict[str, Any]) -> None:
    prohibited = {
        "future_return",
        "label",
        "event_type",
        "pcvt_state",
        "gap_attribution",
    }
    extra = prohibited & set(row)
    if extra:
        raise CandidateMarketSnapshotProbeValidationError(
            f"prohibited fields present: {sorted(extra)}"
        )


def validate_candidate_probe_rows(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    membership_alignment: dict[str, Any],
) -> None:
    if not rows:
        raise CandidateMarketSnapshotProbeValidationError("rows are empty")
    required_fields = contract["future_probe_output_required_fields"]
    tolerance_abs = contract["implied_factor_rule"][
        "synthetic_implied_factor_tolerance_abs"
    ]
    tolerance_rel = contract["implied_factor_rule"][
        "synthetic_implied_factor_tolerance_rel"
    ]
    for row in rows:
        validate_no_future_or_label_fields(row)
        validate_required_fields_only(row, required_fields)
        validate_security_ids_in_membership_alignment([row], membership_alignment)
        validate_source_registry_candidate_only(row, contract)
        validate_retrieved_and_observed_at_present(row)
        validate_source_snapshot_and_hash_present(row)
        validate_raw_close_positive_for_implied_factor(row)
        validate_implied_factor_consistency(row, tolerance_abs, tolerance_rel)
        validate_history_revision_class_allowed(row, contract)
        validate_research_use_tier_allowed(row, contract)
        validate_no_formal_use_without_asof_revision(row)
        validate_no_raw_qfq_hfq_substitution(row)
