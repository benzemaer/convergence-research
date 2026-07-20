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


def _independent_followup(
    joint: Sequence[Mapping[str, Any]],
    security_id: str,
    termination_sequence: int,
    max_lag: int,
    field: str,
) -> tuple[int | None, str]:
    rows = [
        item
        for item in joint
        if str(item["security_id"]) == security_id
        and 0 < int(item["observation_sequence"]) - termination_sequence <= max_lag
    ]
    rows.sort(key=lambda item: int(item["observation_sequence"]))
    lag = next(
        (
            int(item["observation_sequence"]) - termination_sequence
            for item in rows
            if item[field] is True
        ),
        None,
    )
    first_quality = next(
        (
            int(item["observation_sequence"]) - termination_sequence
            for item in rows
            if item["expected_observation_status"] != "present"
            or item["joint_ready"] is not True
            or item["joint_validity_status"] != "valid"
        ),
        None,
    )
    if lag is not None and (first_quality is None or lag < first_quality):
        return lag, "reentered"
    if first_quality is not None:
        return None, "quality_interrupted"
    if (
        not rows
        or int(rows[-1]["observation_sequence"]) - termination_sequence < max_lag
    ):
        return None, "insufficient_followup_censored"
    return None, "not_reentered_within_window"


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
                raw_lag, raw_status = _independent_followup(
                    raw[key[0]]["joint"],
                    str(source["security_id"]),
                    int(sequence),
                    RAW_WINDOW,
                    "raw_state",
                )
                confirmed_lag, confirmed_status = _independent_followup(
                    raw[key[0]]["joint"],
                    str(source["security_id"]),
                    int(sequence),
                    CONFIRMED_WINDOW,
                    "confirmed_state",
                )
                reentry = row.get("reentry", {})
                if (
                    reentry.get("next_raw_true_lag") != raw_lag
                    or reentry.get("next_raw_true_status") != raw_status
                ):
                    _fail(issues, "raw_reentry_observation_lag_mismatch", str(key))
                if (
                    reentry.get("next_confirmed_true_lag") != confirmed_lag
                    or reentry.get("next_confirmed_true_status") != confirmed_status
                ):
                    _fail(
                        issues, "confirmed_reentry_observation_lag_mismatch", str(key)
                    )


def _validate_daily_identities(
    candidate: Mapping[str, Any],
    raw: Mapping[str, dict[str, Any]],
    issues: list[str],
) -> None:
    mapping = _independent_mappings(raw, issues)
    daily = candidate.get("daily_level_identities", [])
    seen: set[tuple[str, int, int]] = set()
    q15_to_q20 = {
        (key[1], key[2]): value[1]
        for key, value in mapping.items()
        if key[0] == "CA_q15_k5"
    }
    q10_to_q15 = {
        (key[1], key[2]): value[1]
        for key, value in mapping.items()
        if key[0] == "CA_q10_k5"
    }
    q10_to_q20 = {
        key: q15_to_q20[q10_to_q15[key]]
        for key in q10_to_q15
        if key in q10_to_q15 and q10_to_q15[key] in q15_to_q20
    }
    q20_to_q25 = {
        (key[1], key[2]): value[1]
        for key, value in mapping.items()
        if key[0] == "CA_q20_k5"
    }
    for row in daily:
        key = (
            str(row.get("security_id")),
            int(row.get("observation_sequence")),
            int(row.get("q20_interval_ordinal")),
        )
        if key in seen:
            _fail(issues, "daily_identity_duplicate", str(key))
        seen.add(key)
        if row.get("identity") not in IDENTITY_CLASSES:
            _fail(issues, "daily_identity_invalid")
    for q20_key, q25_key in q20_to_q25.items():
        q20_days = raw["CA_q20_k5"]["interval_days"][q20_key]
        q25_days = raw["CA_q25_k5"]["interval_days"][q25_key]
        q15_days = set().union(
            *(
                raw["CA_q15_k5"]["interval_days"][key[1:]]
                for key, parent in mapping.items()
                if key[0] == "CA_q15_k5" and parent[1] == q20_key
            )
        )
        q10_days = set().union(
            *(
                raw["CA_q10_k5"]["interval_days"][key]
                for key, parent in q10_to_q20.items()
                if parent == q20_key
            )
        )
        rows = [
            item
            for item in daily
            if str(item.get("security_id")) == q20_key[0]
            and int(item.get("q20_interval_ordinal")) == q20_key[1]
        ]
        if len(rows) != len(q25_days):
            _fail(issues, "daily_identity_count_not_conserved", str(q20_key))
        expected_identity = {
            day: "Q10_CORE"
            if day in q10_days
            else "Q15_NOT_Q10_CORE"
            if day in q15_days
            else "Q20_NOT_Q15_ANCHOR"
            if day in q20_days
            else "Q25_NOT_Q20_SHELL"
            for day in q25_days
        }
        actual_identity = {
            (str(item["security_id"]), int(item["observation_sequence"])): item.get(
                "identity"
            )
            for item in rows
        }
        for day, identity in expected_identity.items():
            if actual_identity.get(day) != identity:
                _fail(issues, "daily_identity_membership_mismatch", f"{q20_key}:{day}")


def _validate_profiles(candidate: Mapping[str, Any], issues: list[str]) -> None:
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

    expected_reentry: dict[tuple[str, str, int], dict[str, int]] = {}
    for metric, lag_field, status_field, thresholds in (
        (
            "raw",
            "next_raw_true_lag",
            "next_raw_true_status",
            (1, 3, 5),
        ),
        (
            "confirmed",
            "next_confirmed_true_lag",
            "next_confirmed_true_status",
            (5, 10),
        ),
    ):
        for name in {row.get("logical_request_name") for row in records}:
            group = [
                row
                for row in records
                if row.get("logical_request_name") == name
                and row.get("right_censored") is not True
            ]
            for threshold in thresholds:
                expected_reentry[(name, metric, threshold)] = {
                    "eligible_termination_count": len(group),
                    "reentered_count": sum(
                        1
                        for row in group
                        if row.get("reentry", {}).get(status_field) == "reentered"
                        and row.get("reentry", {}).get(lag_field) is not None
                        and int(row["reentry"][lag_field]) <= threshold
                    ),
                    "not_reentered_within_window_count": sum(
                        1
                        for row in group
                        if row.get("reentry", {}).get(status_field)
                        == "not_reentered_within_window"
                    ),
                    "insufficient_followup_censored_count": sum(
                        1
                        for row in group
                        if row.get("reentry", {}).get(status_field)
                        == "insufficient_followup_censored"
                    ),
                    "quality_interrupted_count": sum(
                        1
                        for row in group
                        if row.get("reentry", {}).get(status_field)
                        == "quality_interrupted"
                    ),
                }
    actual_reentry = {
        (
            row.get("logical_request_name"),
            row.get("metric"),
            int(row.get("lag_threshold")),
        ): {
            field: int(row.get(field, -1))
            for field in (
                "eligible_termination_count",
                "reentered_count",
                "not_reentered_within_window_count",
                "insufficient_followup_censored_count",
                "quality_interrupted_count",
            )
        }
        for row in candidate.get("quick_reentry_profile", [])
    }
    if expected_reentry != actual_reentry:
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
        if int(row.get("q10_confirmed_day_count_inside_q20", 0)) > int(
            row.get("q15_confirmed_day_count_inside_q20", 0)
        ):
            _fail(issues, "cross_q_q10_q15_day_order_reversed")
        if int(row.get("q15_confirmed_day_count_inside_q20", 0)) > int(
            row.get("q20_confirmed_day_count", 0)
        ):
            _fail(issues, "cross_q_q15_q20_day_order_reversed")
        if int(row.get("q20_confirmed_day_count", 0)) > int(
            row.get("q25_parent_confirmed_day_count", 0)
        ):
            _fail(issues, "cross_q_q20_q25_day_order_reversed")
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
                _validate_profiles(candidate, issues)
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
