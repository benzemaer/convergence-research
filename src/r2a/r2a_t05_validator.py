"""Independent, fail-closed validation for the R2A-T05 candidate.

The validator recomputes request counts, q-subsets, termination classes,
margin formulas, observation-sequence re-entry lags and interval containment
from the synthetic inputs.  It never treats builder-reported counts as
evidence by themselves.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from src.r2a.r2a_t05_ca_exit_decomposition import (
    DIMENSIONS,
    EPSILON,
    IDENTITY_CLASSES,
    PRIMARY_TERMINATION_CATEGORIES,
    QUALITY_TERMINATION_REASONS,
    RAW_FALSE_SUBCLASSES,
    REQUEST_ORDER,
    T05Error,
    _connection,
    _finite,
    _tables,
    _validate_request_schema_connection,
    accepted_request_identities,
    load_t05_config,
    validate_input_schema,
)

WEAK_DELTA = 0.10
RAW_WINDOW = 5
CONFIRMED_WINDOW = 10
RAW_THRESHOLDS = (1, 3, 5)
CONFIRMED_THRESHOLDS = (5, 10)


class T05ValidationError(ValueError):
    """Validation error with a stable code and optional detail."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


def _rows(
    connection: duckdb.DuckDBPyConnection, query: str, parameters: Sequence[Any] = ()
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, list(parameters))
    names = [str(item[0]) for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _fail(issues: list[str], code: str, detail: str | None = None) -> None:
    issues.append(code if detail is None else f"{code}:{detail}")


def _independent_gate(state: Mapping[str, Any] | None, q_bp: int) -> str:
    if state is None or state.get("dimension_ready") is not True:
        return "NOT_EVALUABLE"
    mean = _finite(state.get("score_dimension"))
    minimum = _finite(state.get("score_dimension_min"))
    if mean is None or minimum is None:
        return "NOT_EVALUABLE"
    main = mean < 1.0 - q_bp / 10000.0 - EPSILON
    weak = minimum < 1.0 - q_bp / 10000.0 - WEAK_DELTA - EPSILON
    if main and weak:
        return "MAIN_AND_WEAK_FAIL"
    if main:
        return "MAIN_ONLY_FAIL"
    if weak:
        return "WEAK_ONLY_FAIL"
    return "NO_GATE_FAIL"


def _raw_false_subclass(
    dimension_rows: Mapping[tuple[str, int, str], Mapping[str, Any]],
    security_id: str,
    sequence: int,
) -> tuple[str, bool, bool]:
    c = dimension_rows.get((security_id, sequence, "C"))
    a = dimension_rows.get((security_id, sequence, "A"))
    if (
        c is None
        or a is None
        or c.get("dimension_active") not in (True, False)
        or a.get("dimension_active") not in (True, False)
    ):
        raise T05ValidationError("raw_false_unclassified")
    c_active = bool(c["dimension_active"])
    a_active = bool(a["dimension_active"])
    if c_active and a_active:
        raise T05ValidationError("raw_false_joint_active_lineage_mismatch")
    if c_active:
        return "A_ONLY_FAIL", c_active, a_active
    if a_active:
        return "C_ONLY_FAIL", c_active, a_active
    return "CA_BOTH_FAIL", c_active, a_active


def _load_raw_request(
    source: duckdb.DuckDBPyConnection | Path | str,
    expected: Any,
) -> dict[str, Any]:
    with _connection(source) as connection:
        _validate_request_schema_connection(connection)
        dynamic = _rows(connection, "SELECT * FROM dynamic_request")
        if len(dynamic) != 1:
            raise T05ValidationError("dynamic_request_cardinality")
        row = dynamic[0]
        if (
            row["request_id"] != expected.request_id
            or row["request_hash"] != expected.request_hash
        ):
            raise T05ValidationError(
                "request_identity_mismatch", expected.logical_request_name
            )
        if (
            row["request_schema_version"] != "r2a_t02_dynamic_request.v1"
            or row["output_schema_version"] != "r2a_t03_dynamic_evaluation_output.v1"
        ):
            raise T05ValidationError("protocol_schema_version_mismatch")
        joint = _rows(
            connection,
            "SELECT * FROM daily_joint_states "
            "ORDER BY security_id,observation_sequence",
        )
        scope = _rows(connection, "SELECT * FROM evaluation_scope")
        if len(scope) != 1 or scope[0]["request_id"] != expected.request_id:
            raise T05ValidationError("scope_request_id_mismatch")
        dimension_rows = _rows(
            connection,
            "SELECT * FROM daily_dimension_states WHERE dimension_id IN ('C','A') "
            "ORDER BY security_id,observation_sequence,dimension_id",
        )
        intervals = _rows(
            connection,
            "SELECT * FROM confirmed_intervals ORDER BY security_id,interval_ordinal",
        )
    if any(
        item["request_id"] != expected.request_id for item in (*joint, *dimension_rows)
    ):
        raise T05ValidationError("daily_request_id_mismatch")
    dimensions = {
        (
            str(item["security_id"]),
            int(item["observation_sequence"]),
            str(item["dimension_id"]),
        ): item
        for item in dimension_rows
    }
    interval_days: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for interval in intervals:
        key = (str(interval["security_id"]), int(interval["interval_ordinal"]))
        interval_days[key] = {
            (str(item["security_id"]), int(item["observation_sequence"]))
            for item in joint
            if str(item["security_id"]) == key[0]
            and item["confirmed_state"] is True
            and item["confirmed_interval_ordinal"] is not None
            and int(item["confirmed_interval_ordinal"]) == key[1]
        }
    return {
        "request_id": str(row["request_id"]),
        "request_hash": str(row["request_hash"]),
        "joint": joint,
        "dimensions": dimensions,
        "intervals": intervals,
        "interval_days": interval_days,
        "raw_keys": {
            (str(item["security_id"]), int(item["observation_sequence"]))
            for item in joint
            if item["raw_state"] is True
        },
        "confirmed_keys": {
            (str(item["security_id"]), int(item["observation_sequence"]))
            for item in joint
            if item["confirmed_state"] is True
        },
    }


def _independent_threshold_metrics(
    joint: Sequence[Mapping[str, Any]],
    security_id: str,
    termination_sequence: int,
    max_lag: int,
    field: str,
) -> dict[str, Any]:
    rows = [
        item
        for item in joint
        if str(item["security_id"]) == security_id
        and 0 < int(item["observation_sequence"]) - termination_sequence <= max_lag
    ]
    rows.sort(key=lambda item: int(item["observation_sequence"]))
    first_event_lag = next(
        (
            int(item["observation_sequence"]) - termination_sequence
            for item in rows
            if item[field] is True
        ),
        None,
    )
    first_quality_lag = next(
        (
            int(item["observation_sequence"]) - termination_sequence
            for item in rows
            if item["expected_observation_status"] != "present"
            or item["joint_ready"] is not True
            or item["joint_validity_status"] != "valid"
        ),
        None,
    )
    max_observed_followup_lag = (
        None
        if not rows
        else int(rows[-1]["observation_sequence"]) - termination_sequence
    )

    def outcome(threshold: int) -> dict[str, Any]:
        if (
            first_event_lag is not None
            and first_event_lag <= threshold
            and (first_quality_lag is None or first_event_lag < first_quality_lag)
        ):
            return {"lag": first_event_lag, "status": "reentered"}
        if (
            first_quality_lag is not None
            and first_quality_lag <= threshold
            and (first_event_lag is None or first_quality_lag <= first_event_lag)
        ):
            return {"lag": None, "status": "quality_interrupted"}
        if max_observed_followup_lag is None or max_observed_followup_lag < threshold:
            return {"lag": None, "status": "insufficient_followup_censored"}
        return {"lag": None, "status": "not_reentered_within_window"}

    thresholds = RAW_THRESHOLDS if field == "raw_state" else CONFIRMED_THRESHOLDS
    return {
        "first_event_lag": first_event_lag,
        "first_quality_lag": first_quality_lag,
        "max_observed_followup_lag": max_observed_followup_lag,
        "thresholds": {str(threshold): outcome(threshold) for threshold in thresholds},
    }


def _compare_float(left: Any, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return math.isclose(float(left), right, rel_tol=0.0, abs_tol=EPSILON)
    except (TypeError, ValueError):
        return False


def _independent_request_reconciliation(
    source: duckdb.DuckDBPyConnection | Path | str,
    expected: Mapping[str, int],
) -> dict[str, int]:
    with _connection(source) as connection:
        return {
            "raw_true": int(
                connection.execute(
                    "SELECT count(*) FROM daily_joint_states WHERE raw_state IS TRUE"
                ).fetchone()[0]
            ),
            "confirmed_true": int(
                connection.execute(
                    "SELECT count(*) FROM daily_joint_states "
                    "WHERE confirmed_state IS TRUE"
                ).fetchone()[0]
            ),
            "intervals": int(
                connection.execute(
                    "SELECT count(*) FROM confirmed_intervals"
                ).fetchone()[0]
            ),
            "securities_with_interval": int(
                connection.execute(
                    "SELECT count(DISTINCT security_id) FROM confirmed_intervals"
                ).fetchone()[0]
            ),
        }


def _independent_mappings(
    raw: Mapping[str, dict[str, Any]], issues: list[str]
) -> dict[tuple[str, int], tuple[str, int]]:
    mapping: dict[tuple[str, int], tuple[str, int]] = {}
    for child_name, parent_name in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
        child = raw[child_name]
        parent = raw[parent_name]
        for child_key, child_days in child["interval_days"].items():
            candidates = [
                parent_key
                for parent_key, parent_days in parent["interval_days"].items()
                if parent_key[0] == child_key[0] and child_days <= parent_days
            ]
            if len(candidates) != 1:
                _fail(
                    issues,
                    "cross_q_parent_mapping_not_unique",
                    f"{child_name}:{child_key}",
                )
            else:
                mapping[(child_name, child_key[0], child_key[1])] = (
                    parent_name,
                    candidates[0],
                )
    return mapping


def _validate_interval_rows(
    candidate: Mapping[str, Any],
    raw: Mapping[str, dict[str, Any]],
    issues: list[str],
) -> None:
    expected = {
        (name, str(row["security_id"]), int(row["interval_ordinal"])): row
        for name, data in raw.items()
        for row in data["intervals"]
    }
    actual_rows = candidate.get("termination_records", [])
    actual_keys = {
        (
            row.get("logical_request_name"),
            str(row.get("security_id")),
            int(row.get("interval_ordinal")),
        )
        for row in actual_rows
    }
    if actual_keys != set(expected):
        _fail(issues, "interval_inventory_key_reconciliation_mismatch")
    for row in actual_rows:
        key = (
            row.get("logical_request_name"),
            str(row.get("security_id")),
            int(row.get("interval_ordinal")),
        )
        if key not in expected:
            continue
        source = expected[key]
        reason = str(source["termination_reason"])
        right = bool(source["right_censored"])
        if right and reason != "input_end_open_right_censored":
            _fail(issues, "right_censoring_reason_mismatch", str(key))
        expected_primary = (
            "input_end_open_right_censored"
            if right
            else "raw_false"
            if reason == "raw_false"
            else "quality_or_availability_termination"
        )
        if row.get("primary_termination_reason") != expected_primary:
            _fail(issues, "termination_primary_category_mismatch", str(key))
        if expected_primary == "raw_false":
            sequence = source["termination_observation_sequence"]
            if sequence is None:
                _fail(issues, "raw_false_termination_sequence_missing", str(key))
            else:
                try:
                    subclass, c_active, a_active = _raw_false_subclass(
                        raw[key[0]]["dimensions"],
                        str(source["security_id"]),
                        int(sequence),
                    )
                except T05ValidationError as error:
                    _fail(issues, error.reason_code, str(key))
                else:
                    if (
                        subclass not in RAW_FALSE_SUBCLASSES
                        or row.get("raw_false_subclass") != subclass
                    ):
                        _fail(issues, "raw_false_subclass_mismatch", str(key))
                    if (
                        row.get("termination_C_active") != c_active
                        or row.get("termination_A_active") != a_active
                    ):
                        _fail(issues, "raw_false_active_state_mismatch", str(key))
        elif row.get("raw_false_subclass") is not None:
            _fail(issues, "quality_termination_has_raw_false_subclass", str(key))
        if row.get("primary_termination_reason") not in PRIMARY_TERMINATION_CATEGORIES:
            _fail(issues, "termination_primary_category_invalid", str(key))
        if (
            expected_primary == "quality_or_availability_termination"
            and reason not in QUALITY_TERMINATION_REASONS
        ):
            _fail(issues, "quality_reason_not_preserved", str(key))
        q_bp = int(row.get("q_bp", 0))
        for endpoint_name in (
            "last_confirmed_end_metrics",
            "termination_observation_metrics",
        ):
            endpoint = row.get(endpoint_name, {})
            for dimension in DIMENSIONS:
                metric = endpoint.get(dimension, {})
                q = int(metric.get("q_bp", q_bp))
                mean = _finite(metric.get("score_dimension"))
                minimum = _finite(metric.get("score_dimension_min"))
                main_threshold = 1.0 - q / 10000.0
                weak_threshold = main_threshold - WEAK_DELTA
                mean_margin = None if mean is None else mean - main_threshold
                min_margin = None if minimum is None else minimum - weak_threshold
                active_margin = (
                    None
                    if mean_margin is None or min_margin is None
                    else min(mean_margin, min_margin)
                )
                for field, value in (
                    ("mean_margin", mean_margin),
                    ("min_margin", min_margin),
                    ("active_margin", active_margin),
                ):
                    if not _compare_float(metric.get(field), value):
                        _fail(
                            issues,
                            "threshold_margin_formula_mismatch",
                            f"{key}:{endpoint_name}:{dimension}:{field}",
                        )
                if metric.get("gate_failure_class") != _independent_gate(metric, q):
                    _fail(
                        issues,
                        "threshold_gate_class_mismatch",
                        f"{key}:{endpoint_name}:{dimension}",
                    )
                expected_component_count = (
                    0 if metric.get("observation_sequence") is None else 2
                )
                if metric.get("component_count") != expected_component_count:
                    _fail(
                        issues,
                        "component_score_cardinality_invalid",
                        f"{key}:{endpoint_name}:{dimension}",
                    )
        if expected_primary != "input_end_open_right_censored":
            sequence = source["termination_observation_sequence"]
            if sequence is None:
                _fail(issues, "termination_sequence_missing", str(key))
            else:
                raw_metrics = _independent_threshold_metrics(
                    raw[key[0]]["joint"],
                    str(source["security_id"]),
                    int(sequence),
                    RAW_WINDOW,
                    "raw_state",
                )
                confirmed_metrics = _independent_threshold_metrics(
                    raw[key[0]]["joint"],
                    str(source["security_id"]),
                    int(sequence),
                    CONFIRMED_WINDOW,
                    "confirmed_state",
                )
                reentry = row.get("reentry", {})
                if (
                    reentry.get("first_raw_true_lag") != raw_metrics["first_event_lag"]
                    or reentry.get("first_confirmed_true_lag")
                    != confirmed_metrics["first_event_lag"]
                    or reentry.get("first_quality_interruption_lag")
                    != confirmed_metrics["first_quality_lag"]
                    or reentry.get("max_observed_followup_lag")
                    != confirmed_metrics["max_observed_followup_lag"]
                    or reentry.get("followup_input_end_censored")
                    != (
                        confirmed_metrics["first_quality_lag"] is None
                        and raw_metrics["first_event_lag"] is None
                        and confirmed_metrics["first_event_lag"] is None
                        and (
                            confirmed_metrics["max_observed_followup_lag"] is None
                            or confirmed_metrics["max_observed_followup_lag"]
                            < CONFIRMED_WINDOW
                        )
                    )
                ):
                    _fail(issues, "reentry_observability_fields_mismatch", str(key))
                for field, metrics, thresholds in (
                    ("raw_thresholds", raw_metrics, RAW_THRESHOLDS),
                    ("confirmed_thresholds", confirmed_metrics, CONFIRMED_THRESHOLDS),
                ):
                    if reentry.get(field) != metrics["thresholds"]:
                        _fail(
                            issues, "reentry_threshold_observation_mismatch", str(key)
                        )
                    terminal = metrics["thresholds"][str(thresholds[-1])]
                    prefix = "raw" if field == "raw_thresholds" else "confirmed"
                    if (
                        reentry.get(f"next_{prefix}_true_lag") != terminal["lag"]
                        or reentry.get(f"next_{prefix}_true_status")
                        != terminal["status"]
                    ):
                        _fail(
                            issues,
                            f"{prefix}_reentry_observation_lag_mismatch",
                            str(key),
                        )
        else:
            reentry = row.get("reentry", {})
            if any(
                reentry.get(field) is not None
                for field in (
                    "first_raw_true_lag",
                    "first_confirmed_true_lag",
                    "first_quality_interruption_lag",
                    "max_observed_followup_lag",
                    "followup_input_end_censored",
                )
            ):
                _fail(issues, "right_censored_reentry_observability_mismatch", str(key))
            for field, thresholds in (
                ("raw_thresholds", RAW_THRESHOLDS),
                ("confirmed_thresholds", CONFIRMED_THRESHOLDS),
            ):
                expected = {
                    str(threshold): {
                        "lag": None,
                        "status": "not_applicable_right_censored",
                    }
                    for threshold in thresholds
                }
                if reentry.get(field) != expected:
                    _fail(issues, "right_censored_reentry_threshold_mismatch", str(key))
        for field in (
            "first_raw_true_lag",
            "first_confirmed_true_lag",
            "first_quality_interruption_lag",
            "max_observed_followup_lag",
            "followup_input_end_censored",
        ):
            if row.get(field) != reentry.get(field):
                _fail(
                    issues, "termination_reentry_observability_alias_mismatch", str(key)
                )


def _validate_daily_identities(
    candidate: Mapping[str, Any],
    raw: Mapping[str, dict[str, Any]],
    issues: list[str],
) -> None:
    mapping = _independent_mappings(raw, issues)
    daily = list(candidate.get("daily_level_identities", []))
    q10 = raw["CA_q10_k5"]
    q15 = raw["CA_q15_k5"]
    q20 = raw["CA_q20_k5"]
    q25 = raw["CA_q25_k5"]
    q10_global = set(q10["confirmed_keys"])
    q15_global = set(q15["confirmed_keys"])
    q20_global = set(q20["confirmed_keys"])

    q15_to_q20 = {
        key[1:]: value[1] for key, value in mapping.items() if key[0] == "CA_q15_k5"
    }
    q10_to_q15 = {
        key[1:]: value[1] for key, value in mapping.items() if key[0] == "CA_q10_k5"
    }
    q10_by_q20: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for q10_key, q15_key in q10_to_q15.items():
        q20_key = q15_to_q20.get(q15_key)
        if q20_key is not None:
            q10_by_q20.setdefault(q20_key, []).append(q10_key)
    q15_by_q20: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for q15_key, q20_key in q15_to_q20.items():
        q15_by_q20.setdefault(q20_key, []).append(q15_key)
    q20_to_q25 = {
        key[1:]: value[1] for key, value in mapping.items() if key[0] == "CA_q20_k5"
    }
    q20_by_q25: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for q20_key, q25_key in q20_to_q25.items():
        q20_by_q25.setdefault(q25_key, []).append(q20_key)

    expected_daily: dict[tuple[str, int, int], str] = {}
    for q25_key, q25_days in q25["interval_days"].items():
        for security_day in q25_days:
            key = (security_day[0], security_day[1], q25_key[1])
            if key in expected_daily:
                _fail(issues, "daily_identity_expected_key_duplicate", str(key))
            expected_daily[key] = (
                "Q10_CORE"
                if security_day in q10_global
                else "Q15_NOT_Q10_CORE"
                if security_day in q15_global
                else "Q20_NOT_Q15_ANCHOR"
                if security_day in q20_global
                else "Q25_NOT_Q20_SHELL"
            )
    actual_daily: dict[tuple[str, int, int], str] = {}
    for row in daily:
        try:
            key = (
                str(row.get("security_id")),
                int(row.get("observation_sequence")),
                int(row.get("q25_parent_interval_ordinal")),
            )
        except (TypeError, ValueError):
            _fail(issues, "daily_identity_key_invalid")
            continue
        if key in actual_daily:
            _fail(issues, "daily_identity_duplicate", str(key))
        actual_daily[key] = row.get("identity")
        if row.get("identity") not in IDENTITY_CLASSES:
            _fail(issues, "daily_identity_invalid", str(key))
        if "q20_interval_ordinal" in row:
            _fail(issues, "daily_identity_child_scoped_key_present", str(key))
    if len(daily) != len(q25["confirmed_keys"]):
        _fail(issues, "daily_identity_count_not_conserved")
    if set(actual_daily) != set(expected_daily):
        _fail(issues, "daily_identity_global_key_set_mismatch")
    for key, identity in expected_daily.items():
        if actual_daily.get(key) != identity:
            _fail(issues, "daily_identity_membership_mismatch", str(key))
    for q25_key, q25_days in q25["interval_days"].items():
        parent_key = (q25_key[0], q25_key[1])
        expected_shell = sum(
            identity == "Q25_NOT_Q20_SHELL"
            for key, identity in expected_daily.items()
            if (key[0], key[2]) == parent_key
        )
        actual_shell = sum(
            identity == "Q25_NOT_Q20_SHELL"
            for key, identity in actual_daily.items()
            if (key[0], key[2]) == parent_key
        )
        if expected_shell != len(q25_days - q20_global):
            _fail(
                issues,
                "daily_identity_expected_shell_difference_mismatch",
                str(q25_key),
            )
        if actual_shell != expected_shell:
            _fail(issues, "daily_identity_shell_difference_mismatch", str(q25_key))

    def _compare_summary_rows(
        actual_rows: Sequence[Mapping[str, Any]],
        expected_rows: Mapping[tuple[str, int], Mapping[str, Any]],
        key_fields: tuple[str, str],
        issue_prefix: str,
    ) -> None:
        actual_by_key: dict[tuple[str, int], Mapping[str, Any]] = {}
        for row in actual_rows:
            try:
                key = (str(row.get(key_fields[0])), int(row.get(key_fields[1])))
            except (TypeError, ValueError):
                _fail(issues, f"{issue_prefix}_key_invalid")
                continue
            if key in actual_by_key:
                _fail(issues, f"{issue_prefix}_duplicate", str(key))
            actual_by_key[key] = row
        if set(actual_by_key) != set(expected_rows):
            _fail(issues, f"{issue_prefix}_key_set_mismatch")
        for key, expected_row in expected_rows.items():
            actual_row = actual_by_key.get(key)
            if actual_row is None:
                continue
            for field, expected_value in expected_row.items():
                if actual_row.get(field) != expected_value:
                    _fail(issues, f"{issue_prefix}_field_mismatch", f"{key}:{field}")

    expected_parent_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for q25_key, q25_days in q25["interval_days"].items():
        security_id, q25_ordinal = q25_key
        children = q20_by_q25.get(q25_key, [])
        q20_days = q25_days & q20_global
        q15_days = q25_days & q15_global
        q10_days = q25_days & q10_global
        expected_parent_rows[q25_key] = {
            "logical_request_name": "CA_q25_k5",
            "request_id": q25["request_id"],
            "request_hash": q25["request_hash"],
            "security_id": security_id,
            "q25_parent_interval_ordinal": q25_ordinal,
            "q25_parent_confirmed_day_count": len(q25_days),
            "q20_confirmed_day_count_inside_parent": len(q20_days),
            "q25_only_shell_day_count": len(q25_days - q20_days),
            "q20_child_interval_count": len(children),
            "q20_fragmented_within_q25_parent": len(children) > 1,
            "q20_equals_q25_parent": q20_days == q25_days,
            "q10_confirmed_day_count_inside_parent": len(q10_days),
            "q15_confirmed_day_count_inside_parent": len(q15_days),
            "q25_only_shell_identity_day_count": len(
                (q25_days - q20_days) - q20_global
            ),
        }
    _compare_summary_rows(
        candidate.get("cross_q_structure_summary", []),
        expected_parent_rows,
        ("security_id", "q25_parent_interval_ordinal"),
        "cross_q_parent_summary",
    )

    expected_child_rows: dict[tuple[str, int], dict[str, Any]] = {}
    for q20_key, q25_key in q20_to_q25.items():
        security_id, q20_ordinal = q20_key
        parent_days = q25["interval_days"][q25_key]
        q20_days = q20["interval_days"][q20_key]
        q25_only_days = parent_days - q20_global
        by_sequence = {
            day[1]: day for day in sorted(parent_days, key=lambda item: item[1])
        }
        child_sequences = [day[1] for day in q20_days]
        leading = 0
        sequence = min(child_sequences) - 1
        while sequence in by_sequence and by_sequence[sequence] in q25_only_days:
            leading += 1
            sequence -= 1
        trailing = 0
        sequence = max(child_sequences) + 1
        while sequence in by_sequence and by_sequence[sequence] in q25_only_days:
            trailing += 1
            sequence += 1
        q15_keys = q15_by_q20.get(q20_key, [])
        q10_keys = q10_by_q20.get(q20_key, [])
        q15_days = (
            set().union(*(q15["interval_days"][key] for key in q15_keys))
            if q15_keys
            else set()
        )
        q10_days = (
            set().union(*(q10["interval_days"][key] for key in q10_keys))
            if q10_keys
            else set()
        )
        expected_child_rows[q20_key] = {
            "logical_request_name": "CA_q20_k5",
            "request_id": q20["request_id"],
            "request_hash": q20["request_hash"],
            "security_id": security_id,
            "q20_interval_ordinal": q20_ordinal,
            "q25_parent_interval_ordinal": q25_key[1],
            "q10_confirmed_day_count_inside_q20": len(q10_days),
            "q15_confirmed_day_count_inside_q20": len(q15_days),
            "q20_confirmed_day_count": len(q20_days),
            "q25_parent_confirmed_day_count": len(parent_days),
            "q25_local_leading_shell_days": leading,
            "q25_local_trailing_shell_days": trailing,
            "q25_local_adjacent_shell_days": leading + trailing,
            "q10_child_interval_count": len(q10_keys),
            "q15_child_interval_count": len(q15_keys),
            "q20_sibling_count_within_q25_parent": len(q20_by_q25.get(q25_key, [])) - 1,
            "q20_open_right_censored": bool(
                next(
                    item["right_censored"]
                    for item in q20["intervals"]
                    if str(item["security_id"]) == security_id
                    and int(item["interval_ordinal"]) == q20_ordinal
                )
            ),
        }
    _compare_summary_rows(
        candidate.get("cross_q_child_structure_summary", []),
        expected_child_rows,
        ("security_id", "q20_interval_ordinal"),
        "cross_q_child_summary",
    )


def _validate_profiles(
    candidate: Mapping[str, Any], raw: Mapping[str, dict[str, Any]], issues: list[str]
) -> None:
    """Reconcile compact profiles against the independently checked inventory."""

    records = list(candidate.get("termination_records", []))
    reason_counts = Counter(
        (
            row.get("logical_request_name"),
            row.get("primary_termination_reason"),
            row.get("original_primary_termination_reason"),
        )
        for row in records
    )
    actual_reason_counts = {
        (
            row.get("logical_request_name"),
            row.get("primary_termination_reason"),
            row.get("original_primary_termination_reason"),
        ): int(row.get("interval_count", -1))
        for row in candidate.get("termination_reason_profile", [])
    }
    if dict(reason_counts) != actual_reason_counts:
        _fail(issues, "termination_reason_profile_count_mismatch")

    raw_counts = Counter(
        (row.get("logical_request_name"), row.get("raw_false_subclass"))
        for row in records
        if row.get("primary_termination_reason") == "raw_false"
    )
    actual_raw_counts = {
        (row.get("logical_request_name"), row.get("raw_false_subclass")): int(
            row.get("interval_count", -1)
        )
        for row in candidate.get("raw_false_exit_decomposition", [])
    }
    if dict(raw_counts) != actual_raw_counts:
        _fail(issues, "raw_false_profile_count_mismatch")

    year_counts = Counter(
        (
            row.get("logical_request_name"),
            None
            if row.get("termination_observation_date") is None
            else int(str(row["termination_observation_date"])[:4]),
            row.get("primary_termination_reason"),
        )
        for row in records
    )
    actual_year_counts = {
        (
            row.get("logical_request_name"),
            row.get("year"),
            row.get("primary_termination_reason"),
        ): int(row.get("interval_count", -1))
        for row in candidate.get("year_profile", [])
    }
    if dict(year_counts) != actual_year_counts:
        _fail(issues, "year_profile_count_mismatch")

    security_counts = Counter(
        (
            row.get("logical_request_name"),
            row.get("security_id"),
            row.get("primary_termination_reason"),
        )
        for row in records
    )
    actual_security_counts = {
        (
            row.get("logical_request_name"),
            row.get("security_id"),
            row.get("primary_termination_reason"),
        ): int(row.get("interval_count", -1))
        for row in candidate.get("security_profile", [])
    }
    if dict(security_counts) != actual_security_counts:
        _fail(issues, "security_profile_count_mismatch")

    expected_reentry: dict[tuple[str, str, int], dict[str, Any]] = {}
    for name in REQUEST_ORDER:
        non_right_intervals = [
            interval
            for interval in raw[name]["intervals"]
            if bool(interval["right_censored"]) is False
        ]
        for metric, max_lag, field, thresholds in (
            ("raw", RAW_WINDOW, "raw_state", RAW_THRESHOLDS),
            ("confirmed", CONFIRMED_WINDOW, "confirmed_state", CONFIRMED_THRESHOLDS),
        ):
            outcome_rows = []
            for interval in non_right_intervals:
                sequence = interval["termination_observation_sequence"]
                if sequence is None:
                    _fail(
                        issues,
                        "termination_sequence_missing_for_profile",
                        f"{name}:{interval['security_id']}:{interval['interval_ordinal']}",
                    )
                    continue
                metrics = _independent_threshold_metrics(
                    raw[name]["joint"],
                    str(interval["security_id"]),
                    int(sequence),
                    max_lag,
                    field,
                )
                outcome_rows.append(metrics["thresholds"])
            for threshold in thresholds:
                outcomes = [row[str(threshold)] for row in outcome_rows]
                reentered = sum(
                    outcome["status"] == "reentered" for outcome in outcomes
                )
                clean = sum(
                    outcome["status"] == "not_reentered_within_window"
                    for outcome in outcomes
                )
                insufficient = sum(
                    outcome["status"] == "insufficient_followup_censored"
                    for outcome in outcomes
                )
                quality = sum(
                    outcome["status"] == "quality_interrupted" for outcome in outcomes
                )
                observable = reentered + clean
                expected_reentry[(name, metric, threshold)] = {
                    "total_non_right_censored_termination_count": len(
                        non_right_intervals
                    ),
                    "observable_denominator": observable,
                    "reentered_count": reentered,
                    "clean_not_reentered_count": clean,
                    "insufficient_followup_censored_count": insufficient,
                    "quality_interrupted_count": quality,
                    "reentry_rate": (
                        None if observable == 0 else reentered / observable
                    ),
                }
    actual_reentry = {
        (
            row.get("logical_request_name"),
            row.get("metric"),
            int(row.get("lag_threshold")),
        ): {
            field: row.get(field)
            for field in (
                "total_non_right_censored_termination_count",
                "observable_denominator",
                "reentered_count",
                "clean_not_reentered_count",
                "insufficient_followup_censored_count",
                "quality_interrupted_count",
                "reentry_rate",
            )
        }
        for row in candidate.get("quick_reentry_profile", [])
    }
    if set(expected_reentry) != set(actual_reentry):
        _fail(issues, "quick_reentry_profile_count_mismatch")
    for key, expected in expected_reentry.items():
        actual = actual_reentry.get(key)
        if actual is None:
            continue
        for field in (
            "total_non_right_censored_termination_count",
            "observable_denominator",
            "reentered_count",
            "clean_not_reentered_count",
            "insufficient_followup_censored_count",
            "quality_interrupted_count",
        ):
            if actual.get(field) != expected[field]:
                _fail(issues, "quick_reentry_profile_count_mismatch", f"{key}:{field}")
        if not _compare_float(actual.get("reentry_rate"), expected["reentry_rate"]):
            _fail(issues, "quick_reentry_profile_rate_mismatch", str(key))
    if set(expected_reentry) != set(actual_reentry):
        _fail(issues, "quick_reentry_profile_count_mismatch")

    samples = list(candidate.get("deterministic_interval_samples", []))
    sample_keys = [str(row.get("sample_hash")) for row in samples]
    expected_samples = []
    for row in records:
        token = (
            f"{row.get('request_hash')}:{row.get('security_id')}:"
            f"{row.get('confirmation_date')}:{row.get('interval_ordinal')}"
        )
        expected_samples.append(hashlib.sha256(token.encode("utf-8")).hexdigest())
    expected_samples = sorted(set(expected_samples))[:20]
    if sample_keys != expected_samples:
        _fail(issues, "deterministic_sample_inventory_mismatch")


def detect_result_anomalies(candidate: Mapping[str, Any]) -> list[str]:
    """Scan compact candidate facts for degeneracy and impossible structure."""

    issues: list[str] = []
    reconciliations = list(candidate.get("request_reconciliation", []))
    actuals = [row.get("actual", {}) for row in reconciliations]
    if actuals and all(
        int(row.get("raw_true", 0)) == 0 and int(row.get("confirmed_true", 0)) == 0
        for row in actuals
    ):
        _fail(issues, "all_zero_state_counts")
    if actuals and all(int(row.get("intervals", 0)) == 0 for row in actuals):
        _fail(issues, "all_zero_interval_counts")
    profiles = candidate.get("threshold_margin_summary", [])
    if any(row.get("all_null") is True for row in profiles):
        _fail(issues, "all_null_margin_columns")
    if profiles and all(row.get("constant") is True for row in profiles):
        _fail(issues, "constant_margin_columns")
    if len(actuals) == 4:
        raw_counts = [int(row.get("raw_true", 0)) for row in actuals]
        confirmed_counts = [int(row.get("confirmed_true", 0)) for row in actuals]
        if len(set(raw_counts)) == 1 and len(set(confirmed_counts)) == 1:
            _fail(issues, "q_parameter_no_response")
    metrics = [
        metric
        for record in candidate.get("termination_records", [])
        for endpoint in (
            "last_confirmed_end_metrics",
            "termination_observation_metrics",
        )
        for metric in record.get(endpoint, {}).values()
        if metric.get("observation_sequence") is not None
    ]
    gate_classes = {metric.get("gate_failure_class") for metric in metrics}
    if gate_classes == {"NO_GATE_FAIL"}:
        _fail(issues, "all_one_gate_states")
    for row in candidate.get("cross_q_structure_summary", []):
        if int(row.get("q10_confirmed_day_count_inside_parent", 0)) > int(
            row.get("q15_confirmed_day_count_inside_parent", 0)
        ):
            _fail(issues, "cross_q_q10_q15_day_order_reversed")
        if int(row.get("q15_confirmed_day_count_inside_parent", 0)) > int(
            row.get("q20_confirmed_day_count_inside_parent", 0)
        ):
            _fail(issues, "cross_q_q15_q20_day_order_reversed")
        if int(row.get("q20_confirmed_day_count_inside_parent", 0)) > int(
            row.get("q25_parent_confirmed_day_count", 0)
        ):
            _fail(issues, "cross_q_q20_q25_day_order_reversed")
        if int(row.get("q25_only_shell_day_count", 0)) != int(
            row.get("q25_parent_confirmed_day_count", 0)
        ) - int(row.get("q20_confirmed_day_count_inside_parent", 0)):
            _fail(issues, "cross_q_q25_shell_conservation_mismatch")
    for record in candidate.get("termination_records", []):
        for followup in record.get("reentry", {}).get("followup_observations", []):
            unavailable = (
                followup.get("expected_observation_status") != "present"
                or followup.get("joint_ready") is not True
                or followup.get("joint_validity_status") != "valid"
            )
            if unavailable and (
                followup.get("raw_state") is True
                or followup.get("confirmed_state") is True
            ):
                _fail(issues, "availability_state_inconsistency")
    return sorted(set(issues))


def validate_t05_candidate(
    candidate: Mapping[str, Any],
    request_sources: Mapping[str, duckdb.DuckDBPyConnection | Path | str] | None = None,
    score_source: duckdb.DuckDBPyConnection | Path | str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a receipt; any mismatch is blocking and never silently downgraded."""

    loaded = dict(config or load_t05_config())
    issues: list[str] = []
    try:
        identities = accepted_request_identities(loaded)
    except T05Error as error:
        return {"status": "blocked", "blocking_reasons": [error.reason_code]}
    expected_identity_set = {
        (name, identity.request_id, identity.request_hash)
        for name, identity in identities.items()
    }
    candidate_identity_set = {
        (
            row.get("logical_request_name"),
            row.get("request_id"),
            row.get("request_hash"),
        )
        for row in candidate.get("request_reconciliation", [])
    }
    if candidate_identity_set != expected_identity_set:
        _fail(issues, "request_identity_reconciliation_mismatch")
    for field, expected_value in (
        ("status", "implementation_candidate"),
        ("research_anchor_q", 2000),
        ("research_anchor_role", "exit_mechanism_decomposition"),
        ("q_selection_status", "not_selected"),
        ("canonical_dynamic_request_selected", False),
        ("formal_run_allowed", False),
        ("formal_run_started", False),
        ("real_score_data_read", False),
        ("formal_artifacts_generated", False),
        ("R2A-T05_DONE", "absent"),
        ("R2A-T06_allowed_to_start", False),
    ):
        if candidate.get(field) != expected_value:
            _fail(issues, "candidate_boundary_mismatch", field)
    raw: dict[str, dict[str, Any]] = {}
    if request_sources is not None or score_source is not None:
        if request_sources is None or score_source is None:
            _fail(issues, "independent_input_pair_incomplete")
        else:
            try:
                if tuple(request_sources) != REQUEST_ORDER:
                    raise T05ValidationError("request_source_order_or_set_mismatch")
                validate_input_schema(
                    next(iter(request_sources.values())), score_source
                )
                for name in REQUEST_ORDER:
                    raw[name] = _load_raw_request(
                        request_sources[name], identities[name]
                    )
                with _connection(score_source) as score:
                    expected_score_id = loaded["accepted_bindings"]["score_release"][
                        "score_release_id"
                    ]
                    score_ids_by_table = {
                        table: {
                            str(row[0])
                            for row in score.execute(
                                f'SELECT DISTINCT score_release_id FROM "{table}"'
                            ).fetchall()
                        }
                        for table in sorted(_tables(score))
                    }
                    if any(
                        ids != {expected_score_id}
                        for ids in score_ids_by_table.values()
                    ):
                        _fail(issues, "score_table_release_identity_mismatch")
            except (T05Error, T05ValidationError, duckdb.Error) as error:
                _fail(
                    issues,
                    getattr(
                        error, "reason_code", "independent_input_recalculation_failed"
                    ),
                )
            if raw:
                for name in REQUEST_ORDER:
                    actual = _independent_request_reconciliation(
                        raw[name]
                        if isinstance(raw[name], duckdb.DuckDBPyConnection)
                        else request_sources[name],
                        loaded["accepted_t04_counts"][name],
                    )
                    candidate_row = next(
                        (
                            row
                            for row in candidate.get("request_reconciliation", [])
                            if row.get("logical_request_name") == name
                        ),
                        None,
                    )
                    if candidate_row is None or candidate_row.get("actual") != actual:
                        _fail(issues, "independent_count_reconciliation_mismatch", name)
                    if actual != loaded["accepted_t04_counts"][name]:
                        _fail(issues, "accepted_t04_count_mismatch", name)
                for lower, upper in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
                    if not raw[lower]["raw_keys"] <= raw[upper]["raw_keys"]:
                        _fail(
                            issues, "cross_q_raw_subset_violation", f"{lower}->{upper}"
                        )
                    if not raw[lower]["confirmed_keys"] <= raw[upper]["confirmed_keys"]:
                        _fail(
                            issues,
                            "cross_q_confirmed_subset_violation",
                            f"{lower}->{upper}",
                        )
                _validate_interval_rows(candidate, raw, issues)
                _validate_daily_identities(candidate, raw, issues)
                _validate_profiles(candidate, raw, issues)
    else:
        _fail(issues, "independent_raw_inputs_not_supplied")
    issues.extend(detect_result_anomalies(candidate))
    receipt = {
        "status": "passed" if not issues else "blocked",
        "independent_recalculation": bool(raw),
        "request_identity_match": "request_identity_reconciliation_mismatch"
        not in issues,
        "t04_reconciliation_match": not any(
            "count_mismatch" in item for item in issues
        ),
        "cross_q_mapping_unique": not any("parent_mapping" in item for item in issues),
        "daily_identity_conservation": not any(
            "daily_identity" in item for item in issues
        ),
        "forbidden_input_fields_absent": not any(
            "schema" in item or "unapproved" in item for item in issues
        ),
        "deterministic_output": True,
        "blocking_reasons": sorted(set(issues)),
    }
    return receipt


def validate_t05_result_package(
    candidate: Mapping[str, Any],
    request_sources: Mapping[str, duckdb.DuckDBPyConnection | Path | str] | None = None,
    score_source: duckdb.DuckDBPyConnection | Path | str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility name used by the CLI and future package validator."""

    return validate_t05_candidate(
        candidate,
        request_sources=request_sources,
        score_source=score_source,
        config=config,
    )


__all__ = [
    "T05ValidationError",
    "detect_result_anomalies",
    "validate_t05_candidate",
    "validate_t05_result_package",
]
