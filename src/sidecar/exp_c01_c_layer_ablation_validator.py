"""Independent contract, artifact, manifest, and anomaly validation for EXP-C01."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.sidecar.exp_c01_c_layer_ablation import (
    BASELINE_VARIANT,
    C1_ID,
    C1_VARIANT,
    C2_ID,
    C2_VARIANT,
    CSV_FIELDS,
    OUTPUT_FILES,
    TASK_ID,
    VARIANT_IDS,
    WEAK_DELTA,
    Q,
    W,
)

EXPECTED_VARIANT_RULES = {
    BASELINE_VARIANT: "pair_valid AND score_C_mean >= 0.80 AND score_C_min >= 0.70",
    C1_VARIANT: "C1 valid AND score_C1 >= 0.80",
    C2_VARIANT: "C2 valid AND score_C2 >= 0.80",
}
EXPECTED_COMPARISONS = {
    "c1_vs_c2",
    "c1_vs_baseline_mean",
    "c2_vs_baseline_mean",
}
EXPECTED_OVERLAPS = {
    (BASELINE_VARIANT, C1_VARIANT),
    (BASELINE_VARIANT, C2_VARIANT),
    (C1_VARIANT, C2_VARIANT),
}
FORBIDDEN_FIELD_TOKENS = (
    "future",
    "return",
    "release",
    "backtest",
    "portfolio",
    "selected_indicator",
    "winner",
    "best_indicator",
    "replacement_approved",
    "c_v2",
    "freeze_candidate",
)
FORBIDDEN_DIMENSION_FIELD = re.compile(r"^(?:p|t|v)(?:_|$)", re.IGNORECASE)
RECONCILIATION_MISMATCH_FIELDS = (
    "key_count_mismatch",
    "score_mean_mismatch",
    "score_min_mismatch",
    "eligible_mismatch",
    "active_mismatch",
    "validity_mismatch",
    "dimension_validity_mismatch",
    "state_validity_mismatch",
    "mismatch_total",
)


def read_csv_artifact(path: str | Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Read a UTF-8 CSV and reject BOMs, duplicate headers, and empty headers."""

    artifact_path = Path(path)
    raw = artifact_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"BOM is forbidden: {artifact_path}")
    text = raw.decode("utf-8")
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError(f"CSV has no header: {artifact_path}")
    headers = tuple(str(value) for value in reader.fieldnames)
    if len(set(headers)) != len(headers) or any(not header for header in headers):
        raise ValueError(f"CSV header is invalid: {artifact_path}")
    return headers, [dict(row) for row in reader]


def validate_output_directory(
    output_dir: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
    require_governance_files: bool = True,
) -> dict[str, Any]:
    """Validate a future formal result directory without touching any database."""

    root = Path(output_dir)
    errors: list[str] = []
    warnings: list[str] = []
    artifacts: dict[str, tuple[tuple[str, ...], list[dict[str, str]]]] = {}

    expected_csv_keys = (
        "variant_profile",
        "overlap_profile",
        "score_comparison",
        "year_profile",
        "security_profile",
        "availability_profile",
    )
    for key in expected_csv_keys:
        path = root / OUTPUT_FILES[key]
        if not path.is_file():
            errors.append(f"missing_file:{OUTPUT_FILES[key]}")
            continue
        try:
            headers, rows = read_csv_artifact(path)
            artifacts[key] = (headers, rows)
            errors.extend(_validate_csv_headers(key, headers))
            if not rows:
                errors.append(f"empty_output:{OUTPUT_FILES[key]}")
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"csv_read_error:{key}:{exc}")

    manifest_path = root / OUTPUT_FILES["manifest"]
    if not manifest_path.is_file():
        errors.append(f"missing_file:{manifest_path.name}")
        manifest: dict[str, Any] = {}
    else:
        try:
            manifest = _load_json(manifest_path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"manifest_read_error:{exc}")
            manifest = {}

    if config is not None:
        errors.extend(validate_static_config(config))
    errors.extend(_validate_variant_profile(artifacts.get("variant_profile"), errors))
    errors.extend(
        _validate_overlap_profile(
            artifacts.get("overlap_profile"), artifacts.get("variant_profile")
        )
    )
    errors.extend(_validate_score_comparison(artifacts.get("score_comparison")))
    errors.extend(_validate_year_profile(artifacts.get("year_profile")))
    errors.extend(_validate_security_profile(artifacts.get("security_profile")))
    errors.extend(_validate_availability_profile(artifacts.get("availability_profile")))

    if manifest:
        errors.extend(validate_manifest(manifest, root, config=config))
        errors.extend(
            _validate_availability_against_manifest(
                _rows(artifacts, "availability_profile"), manifest
            )
        )
    else:
        errors.append("manifest_missing_or_invalid")

    anomaly_scan = scan_anomalies(artifacts, manifest)
    if anomaly_scan["status"] != "passed":
        errors.extend(f"anomaly:{item['code']}" for item in anomaly_scan["anomalies"])

    if require_governance_files:
        for key in ("validator_result", "anomaly_scan", "result_analysis"):
            path = root / OUTPUT_FILES[key]
            if not path.is_file():
                errors.append(f"missing_file:{path.name}")

    status = "passed" if not errors else "failed"
    return {
        "task_id": TASK_ID,
        "status": status,
        "valid": status == "passed",
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "checked_files": sorted(path.name for path in root.iterdir())
        if root.is_dir()
        else [],
        "anomaly_scan": anomaly_scan,
    }


def validate_static_config(config: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if config.get("task_id") != TASK_ID:
        errors.append("config_task_id_mismatch")
    parameters = config.get("parameters")
    if not isinstance(parameters, Mapping):
        return [*errors, "config_parameters_missing"]
    if parameters.get("W") != W:
        errors.append("config_W_mismatch")
    if not _same_float(parameters.get("q"), Q):
        errors.append("config_q_mismatch")
    if not _same_float(parameters.get("weak_delta"), WEAK_DELTA):
        errors.append("config_weak_delta_mismatch")
    if config.get("denominator_scope") != "pair_common_valid":
        errors.append("config_denominator_scope_mismatch")
    variant_rows = config.get("variants")
    if not isinstance(variant_rows, Sequence) or isinstance(variant_rows, str):
        errors.append("config_variants_missing")
    else:
        variant_ids = [str(row.get("variant_id")) for row in variant_rows]
        if tuple(variant_ids) != VARIANT_IDS:
            errors.append("config_variant_set_mismatch")
        for row in variant_rows:
            if EXPECTED_VARIANT_RULES.get(str(row.get("variant_id"))) != row.get(
                "rule"
            ):
                errors.append(f"config_variant_rule_mismatch:{row.get('variant_id')}")
    return errors


def validate_indicator_score_rows(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Independently validate the filtered C1/C2 score input before aggregation."""

    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        prefix = f"input_row:{index}"
        try:
            window = int(row.get("percentile_window_W"))
        except (TypeError, ValueError):
            window = -1
        if window != W:
            errors.append(f"{prefix}:W_mismatch")
        indicator_id = str(row.get("indicator_id"))
        if indicator_id not in {C1_ID, C2_ID}:
            errors.append(f"{prefix}:indicator_mismatch")
        security_id = str(row.get("security_id"))
        trading_date = str(row.get("trading_date"))
        key = (security_id, trading_date, indicator_id)
        if key in seen:
            errors.append(f"{prefix}:duplicate_key")
        seen.add(key)
        eligible = row.get("eligible")
        if not isinstance(eligible, bool):
            errors.append(f"{prefix}:eligible_not_boolean")
        status = str(row.get("validity_status"))
        if status not in {"valid", "unknown", "blocked", "diagnostic_required"}:
            errors.append(f"{prefix}:validity_status_mismatch")
        score = _optional_float(row.get("score"))
        raw_score = row.get("score")
        if raw_score is not None and score is None:
            errors.append(f"{prefix}:score_not_finite_numeric")
        if score is not None and not 0.0 <= score <= 1.0:
            errors.append(f"{prefix}:score_out_of_range")
        if eligible is True and status == "valid" and score is None:
            errors.append(f"{prefix}:valid_score_missing")
        if eligible is False and score is not None:
            errors.append(f"{prefix}:ineligible_score_present")
    return errors


def build_input_availability_summary(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    """Compute native and pair-valid counts without using the aggregation engine."""

    counts = {
        C1_ID: {"input_row_count": 0, "native_valid_count": 0},
        C2_ID: {"input_row_count": 0, "native_valid_count": 0},
    }
    by_key: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        indicator_id = str(row.get("indicator_id"))
        if indicator_id not in counts:
            continue
        counts[indicator_id]["input_row_count"] += 1
        if _input_row_is_valid(row):
            counts[indicator_id]["native_valid_count"] += 1
        key = (str(row.get("security_id")), str(row.get("trading_date")))
        by_key.setdefault(key, {})[indicator_id] = row
    pair_count = sum(
        1
        for values in by_key.values()
        if _input_row_is_valid(values.get(C1_ID))
        and _input_row_is_valid(values.get(C2_ID))
    )
    summary = {
        indicator_id: {
            **values,
            "native_invalid_count": values["input_row_count"]
            - values["native_valid_count"],
            "pair_common_valid_count": pair_count,
            "availability_gain_vs_pair": values["native_valid_count"] - pair_count,
        }
        for indicator_id, values in counts.items()
    }
    summary["pair_common_valid"] = {
        "input_row_count": len(by_key),
        "native_valid_count": pair_count,
        "native_invalid_count": len(by_key) - pair_count,
        "pair_common_valid_count": pair_count,
        "availability_gain_vs_pair": 0,
    }
    return summary


def validate_baseline_reconciliation(payload: Mapping[str, Any]) -> list[str]:
    """Independently check that every reconciliation mismatch is zero."""

    errors: list[str] = []
    for field in RECONCILIATION_MISMATCH_FIELDS:
        value = payload.get(field)
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            errors.append(f"reconciliation_field_invalid:{field}")
            continue
        if numeric != 0:
            errors.append(f"reconciliation_nonzero:{field}")
    expected = payload.get("expected_key_count")
    for field in (
        "dimension_score_key_count",
        "dimension_state_key_count",
        "key_count",
    ):
        if expected is not None and payload.get(field) != expected:
            errors.append(f"reconciliation_key_count_mismatch:{field}")
    if payload.get("status") != "passed":
        errors.append("reconciliation_status_not_passed")
    return errors


def validate_manifest(
    manifest: Mapping[str, Any],
    output_dir: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
) -> list[str]:
    root = Path(output_dir)
    errors: list[str] = []
    if manifest.get("task_id") != TASK_ID:
        errors.append("manifest_task_id_mismatch")
    if manifest.get("parameters", {}).get("W") != W:
        errors.append("manifest_W_mismatch")
    if not _same_float(manifest.get("parameters", {}).get("q"), Q):
        errors.append("manifest_q_mismatch")
    if manifest.get("variants") != list(VARIANT_IDS):
        errors.append("manifest_variant_set_mismatch")
    if manifest.get("denominator_scope") != "pair_common_valid":
        errors.append("manifest_denominator_scope_mismatch")

    reconciliation = manifest.get("baseline_reconciliation")
    if not isinstance(reconciliation, Mapping):
        errors.append("baseline_reconciliation_missing")
    else:
        errors.extend(validate_baseline_reconciliation(reconciliation))

    files = manifest.get("files")
    if not isinstance(files, Mapping):
        errors.append("manifest_files_missing")
    else:
        expected_files = {
            OUTPUT_FILES[key]
            for key in (
                "variant_profile",
                "overlap_profile",
                "score_comparison",
                "year_profile",
                "security_profile",
                "availability_profile",
                "result_analysis",
            )
        }
        if set(files) != expected_files:
            errors.append("manifest_file_set_mismatch")
        for name in expected_files:
            entry = files.get(name)
            if not isinstance(entry, Mapping):
                errors.append(f"manifest_file_entry_missing:{name}")
                continue
            path = _manifest_path(root, entry.get("path", name))
            if not path.is_file():
                errors.append(f"manifest_file_missing:{name}")
                continue
            actual_hash = _sha256_file(path)
            if entry.get("sha256") != actual_hash:
                errors.append(f"manifest_hash_mismatch:{name}")
            actual_rows = _file_row_count(path, name)
            if entry.get("row_count") != actual_rows:
                errors.append(f"manifest_row_count_mismatch:{name}")

    input_artifacts = manifest.get("input_artifacts")
    if not isinstance(input_artifacts, Mapping):
        errors.append("manifest_input_artifacts_missing")
    else:
        for name, entry in input_artifacts.items():
            if not isinstance(entry, Mapping):
                errors.append(f"manifest_input_entry_invalid:{name}")
                continue
            path_value = entry.get("path")
            if not path_value:
                errors.append(f"manifest_input_path_missing:{name}")
                continue
            path = Path(str(path_value))
            if not path.is_file():
                errors.append(f"manifest_input_file_missing:{name}")
                continue
            if entry.get("sha256") != _sha256_file(path):
                errors.append(f"manifest_input_hash_mismatch:{name}")
            if "row_count" not in entry or int(entry["row_count"]) < 0:
                errors.append(f"manifest_input_row_count_invalid:{name}")

    config_binding = manifest.get("config")
    if not isinstance(config_binding, Mapping):
        errors.append("manifest_config_binding_missing")
    else:
        config_path_value = config_binding.get("path")
        if config_path_value:
            config_path = Path(str(config_path_value))
            if config_path.is_file() and config_binding.get("sha256") != _sha256_file(
                config_path
            ):
                errors.append("manifest_config_hash_mismatch")
        else:
            errors.append("manifest_config_path_missing")

    if config is not None:
        expected_rules = {
            str(row.get("variant_id")): row.get("rule")
            for row in config.get("variants", [])
            if isinstance(row, Mapping)
        }
        if manifest.get("variant_rules") != expected_rules:
            errors.append("manifest_variant_rules_mismatch")
    return errors


def scan_anomalies(
    artifacts: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]],
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    anomalies: list[dict[str, str]] = []
    variant_rows = _rows(artifacts, "variant_profile")
    overlap_rows = _rows(artifacts, "overlap_profile")
    year_rows = _rows(artifacts, "year_profile")
    security_rows = _rows(artifacts, "security_profile")
    availability_rows = _rows(artifacts, "availability_profile")

    if not variant_rows:
        anomalies.append(
            {"code": "all_null_output", "detail": "variant profile is empty"}
        )
    else:
        true_counts = [_int(row.get("active_true_count")) for row in variant_rows]
        eligible_counts = [_int(row.get("eligible_row_count")) for row in variant_rows]
        if true_counts and all(value == 0 for value in true_counts):
            anomalies.append(
                {"code": "all_zero", "detail": "all variants have zero active rows"}
            )
        if true_counts and all(
            eligible > 0 and true == eligible
            for true, eligible in zip(true_counts, eligible_counts, strict=True)
        ):
            anomalies.append(
                {
                    "code": "all_one",
                    "detail": "all variants are active on every valid row",
                }
            )
        if all(_row_is_all_null(row) for row in variant_rows):
            anomalies.append(
                {"code": "all_null", "detail": "variant metrics are all NULL"}
            )
        for row in variant_rows:
            if _int(row.get("active_true_count")) + _int(
                row.get("active_false_count")
            ) != _int(row.get("eligible_row_count")):
                anomalies.append(
                    {
                        "code": "hierarchy_count_nonconservation",
                        "detail": str(row.get("variant_id")),
                    }
                )

    if len(overlap_rows) == 3 and all(
        _int(row.get("symmetric_difference_count")) == 0 for row in overlap_rows
    ):
        anomalies.append(
            {
                "code": "three_variants_identical",
                "detail": "all pairwise differences are zero",
            }
        )
        anomalies.append(
            {
                "code": "candidate_no_identity_response",
                "detail": "candidates add no identity response",
            }
        )

    if year_rows and len({_int(row.get("calendar_year")) for row in year_rows}) == 1:
        anomalies.append(
            {
                "code": "single_year_concentration",
                "detail": "year profile contains one year",
            }
        )

    if security_rows:
        by_candidate: dict[str, list[Mapping[str, Any]]] = {}
        for row in security_rows:
            by_candidate.setdefault(str(row.get("candidate_variant")), []).append(row)
        for candidate, rows in by_candidate.items():
            total = sum(_int(row.get("valid_row_count")) for row in rows)
            maximum = max((_int(row.get("valid_row_count")) for row in rows), default=0)
            if total > 0 and len(rows) > 1 and maximum / total > 0.95:
                anomalies.append(
                    {
                        "code": "security_concentration",
                        "detail": f"{candidate} exceeds 95%",
                    }
                )

    if availability_rows:
        pair_rows = [
            row
            for row in availability_rows
            if row.get("indicator_id") == "pair_common_valid"
        ]
        pair_count = (
            _int(pair_rows[0].get("pair_common_valid_count")) if pair_rows else None
        )
        for row in availability_rows:
            if row.get("indicator_id") in {C1_ID, C2_ID}:
                native = _int(row.get("native_valid_count"))
                reported_pair = _int(row.get("pair_common_valid_count"))
                if pair_count is not None and reported_pair != pair_count:
                    anomalies.append(
                        {
                            "code": "availability_mismatch",
                            "detail": str(row.get("indicator_id")),
                        }
                    )
                if _int(row.get("availability_gain_vs_pair")) != native - reported_pair:
                    anomalies.append(
                        {
                            "code": "availability_gain_mismatch",
                            "detail": str(row.get("indicator_id")),
                        }
                    )

    if manifest:
        reconciliation = manifest.get("baseline_reconciliation", {})
        if isinstance(reconciliation, Mapping) and any(
            _int(reconciliation.get(field)) != 0
            for field in RECONCILIATION_MISMATCH_FIELDS
        ):
            anomalies.append(
                {
                    "code": "baseline_reconciliation_mismatch",
                    "detail": "nonzero mismatch count",
                }
            )

    return {
        "task_id": TASK_ID,
        "status": "passed" if not anomalies else "failed",
        "anomalies": anomalies,
        "checked_artifact_count": len(artifacts),
    }


def _validate_availability_against_manifest(
    rows: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> list[str]:
    expected = manifest.get("input_availability")
    if not isinstance(expected, Mapping):
        return ["manifest_input_availability_missing"]
    errors: list[str] = []
    for row in rows:
        indicator_id = str(row.get("indicator_id"))
        expected_row = expected.get(indicator_id)
        if not isinstance(expected_row, Mapping):
            errors.append(f"manifest_input_availability_entry_missing:{indicator_id}")
            continue
        for field in (
            "input_row_count",
            "native_valid_count",
            "native_invalid_count",
            "pair_common_valid_count",
            "availability_gain_vs_pair",
        ):
            if _int(row.get(field)) != _int(expected_row.get(field)):
                errors.append(f"availability_manifest_mismatch:{indicator_id}:{field}")
    return errors


def _validate_csv_headers(key: str, headers: Sequence[str]) -> list[str]:
    required = set(CSV_FIELDS[key])
    errors = [
        f"missing_column:{key}:{field}" for field in sorted(required - set(headers))
    ]
    for header in headers:
        lower = header.lower()
        if lower in {"p", "t", "v"} or FORBIDDEN_DIMENSION_FIELD.match(header):
            errors.append(f"forbidden_dimension_field:{key}:{header}")
        for token in FORBIDDEN_FIELD_TOKENS:
            if token in lower:
                errors.append(f"forbidden_field:{key}:{header}")
    return errors


def _validate_variant_profile(
    artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
    prior_errors: Sequence[str],
) -> list[str]:
    if artifact is None:
        return []
    _headers, rows = artifact
    errors: list[str] = []
    if {str(row.get("variant_id")) for row in rows} != set(VARIANT_IDS) or len(
        rows
    ) != 3:
        errors.append("variant_set_mismatch")
    for row in rows:
        variant_id = str(row.get("variant_id"))
        if variant_id not in VARIANT_IDS:
            continue
        errors.extend(_validate_common_parameters(row, f"variant:{variant_id}"))
        eligible = _int(row.get("eligible_row_count"))
        true_count = _int(row.get("active_true_count"))
        false_count = _int(row.get("active_false_count"))
        if eligible < 0 or true_count < 0 or false_count < 0:
            errors.append(f"negative_count:{variant_id}")
        if true_count + false_count != eligible:
            errors.append(f"active_count_not_conserved:{variant_id}")
        if not _same_ratio(row.get("active_rate"), true_count, eligible):
            errors.append(f"active_rate_mismatch:{variant_id}")
        if _int(row.get("segment_duration_sum")) != true_count:
            errors.append(f"segment_duration_not_conserved:{variant_id}")
        if _int(row.get("segment_count")) != _int(row.get("segment_start_count")):
            errors.append(f"segment_start_not_conserved:{variant_id}")
        if _int(row.get("transition_count")) != _int(
            row.get("true_to_false_transition_count")
        ) + _int(row.get("false_to_true_transition_count")):
            errors.append(f"transition_not_conserved:{variant_id}")
        if _int(row.get("segment_count")) > _int(row.get("valid_block_count")) + _int(
            row.get("false_to_true_transition_count")
        ):
            errors.append(f"segment_onset_impossible:{variant_id}")
    return errors


def _validate_overlap_profile(
    artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
    variant_artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
) -> list[str]:
    if artifact is None:
        return []
    _headers, rows = artifact
    errors: list[str] = []
    pairs = {
        (str(row.get("left_variant")), str(row.get("right_variant"))) for row in rows
    }
    if pairs != EXPECTED_OVERLAPS or len(rows) != 3:
        errors.append("overlap_pair_set_mismatch")
    variant_counts = {
        str(row.get("variant_id")): _int(row.get("eligible_row_count"))
        for row in (variant_artifact[1] if variant_artifact else ())
    }
    for row in rows:
        left = str(row.get("left_variant"))
        right = str(row.get("right_variant"))
        errors.extend(_validate_common_parameters(row, f"overlap:{left}:{right}"))
        common = _int(row.get("common_valid_rows"))
        n11 = _int(row.get("n11"))
        n10 = _int(row.get("n10"))
        n01 = _int(row.get("n01"))
        n00 = _int(row.get("n00"))
        if n11 + n10 + n01 + n00 != common:
            errors.append(f"overlap_2x2_not_conserved:{left}:{right}")
        if left in variant_counts and common != variant_counts[left]:
            errors.append(f"overlap_denominator_mismatch:{left}:{right}")
        if right in variant_counts and common != variant_counts[right]:
            errors.append(f"overlap_denominator_mismatch:{left}:{right}")
        if _int(row.get("left_true_count")) != n11 + n10:
            errors.append(f"left_count_mismatch:{left}:{right}")
        if _int(row.get("right_true_count")) != n11 + n01:
            errors.append(f"right_count_mismatch:{left}:{right}")
        if left == BASELINE_VARIANT:
            if not _same_optional_float(
                row.get("baseline_retention"), row.get("right_given_left")
            ):
                errors.append(f"baseline_retention_alias_mismatch:{right}")
            if not _same_optional_float(
                row.get("candidate_precision"), row.get("left_given_right")
            ):
                errors.append(f"candidate_precision_alias_mismatch:{right}")
    return errors


def _validate_score_comparison(
    artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
) -> list[str]:
    if artifact is None:
        return []
    _headers, rows = artifact
    errors: list[str] = []
    if {str(row.get("comparison_id")) for row in rows} != EXPECTED_COMPARISONS or len(
        rows
    ) != 3:
        errors.append("score_comparison_set_mismatch")
    for row in rows:
        errors.extend(
            _validate_common_parameters(row, f"score:{row.get('comparison_id')}")
        )
        if _int(row.get("common_valid_rows")) < 0:
            errors.append(f"negative_score_comparison_count:{row.get('comparison_id')}")
        for field in (
            "pooled_spearman",
            "per_security_spearman_median",
            "per_security_spearman_q25",
            "per_security_spearman_q75",
        ):
            value = _optional_float(row.get(field))
            if value is not None and not -1.0 - 1e-12 <= value <= 1.0 + 1e-12:
                errors.append(
                    f"spearman_out_of_range:{row.get('comparison_id')}:{field}"
                )
        for field in (
            "mean_absolute_score_difference",
            "median_absolute_score_difference",
            "q90_absolute_score_difference",
            "q95_absolute_score_difference",
        ):
            value = _optional_float(row.get(field))
            if value is not None and value < -1e-12:
                errors.append(
                    f"negative_score_difference:{row.get('comparison_id')}:{field}"
                )
    return errors


def _validate_year_profile(
    artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
) -> list[str]:
    if artifact is None:
        return []
    _headers, rows = artifact
    errors: list[str] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        errors.extend(
            _validate_common_parameters(row, f"year:{row.get('calendar_year')}")
        )
        candidate = str(row.get("candidate_variant"))
        if candidate not in {C1_VARIANT, C2_VARIANT}:
            errors.append(f"year_candidate_invalid:{candidate}")
        key = (_int(row.get("calendar_year")), candidate)
        if key in seen:
            errors.append(f"year_duplicate:{key}")
        seen.add(key)
        if str(row.get("baseline_variant")) != BASELINE_VARIANT:
            errors.append(f"year_baseline_invalid:{key}")
        if not _same_optional_float(
            row.get("active_rate"), row.get("candidate_active_rate")
        ):
            errors.append(f"year_active_rate_alias_mismatch:{key}")
        for field in (
            "active_rate",
            "baseline_active_rate",
            "candidate_active_rate",
            "jaccard",
            "baseline_retention",
            "candidate_precision",
            "symmetric_difference_rate",
        ):
            value = _optional_float(row.get(field))
            if value is not None and not -1e-12 <= value <= 1.0 + 1e-12:
                errors.append(f"year_rate_out_of_range:{key}:{field}")
    return errors


def _validate_security_profile(
    artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
) -> list[str]:
    if artifact is None:
        return []
    _headers, rows = artifact
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        candidate = str(row.get("candidate_variant"))
        key = (str(row.get("security_id")), candidate)
        if key in seen:
            errors.append(f"security_duplicate:{key}")
        seen.add(key)
        if candidate not in {C1_VARIANT, C2_VARIANT}:
            errors.append(f"security_candidate_invalid:{candidate}")
        if str(row.get("baseline_variant")) != BASELINE_VARIANT:
            errors.append(f"security_baseline_invalid:{key}")
        if _int(row.get("valid_row_count")) < 0:
            errors.append(f"security_negative_count:{key}")
        for field in ("jaccard", "baseline_retention", "candidate_precision"):
            value = _optional_float(row.get(field))
            if value is not None and not -1e-12 <= value <= 1.0 + 1e-12:
                errors.append(f"security_rate_out_of_range:{key}:{field}")
    return errors


def _validate_availability_profile(
    artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
) -> list[str]:
    if artifact is None:
        return []
    _headers, rows = artifact
    errors: list[str] = []
    expected = {C1_ID, C2_ID, "pair_common_valid"}
    if {str(row.get("indicator_id")) for row in rows} != expected or len(rows) != 3:
        errors.append("availability_indicator_set_mismatch")
    pair_count: int | None = None
    for row in rows:
        indicator = str(row.get("indicator_id"))
        errors.extend(_validate_common_parameters(row, f"availability:{indicator}"))
        input_count = _int(row.get("input_row_count"))
        native = _int(row.get("native_valid_count"))
        invalid = _int(row.get("native_invalid_count"))
        reported_pair = _int(row.get("pair_common_valid_count"))
        if input_count < 0 or native < 0 or invalid < 0 or reported_pair < 0:
            errors.append(f"availability_negative_count:{indicator}")
        if native + invalid != input_count and indicator != "pair_common_valid":
            errors.append(f"availability_native_count_not_conserved:{indicator}")
        if indicator == "pair_common_valid":
            pair_count = reported_pair
        if _int(row.get("availability_gain_vs_pair")) != native - reported_pair:
            errors.append(f"availability_gain_not_conserved:{indicator}")
    if pair_count is not None:
        for row in rows:
            if (
                str(row.get("indicator_id")) in {C1_ID, C2_ID}
                and _int(row.get("pair_common_valid_count")) != pair_count
            ):
                errors.append(
                    f"availability_pair_count_mismatch:{row.get('indicator_id')}"
                )
    return errors


def _validate_common_parameters(row: Mapping[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    if _int(row.get("W")) != W:
        errors.append(f"W_mismatch:{prefix}")
    if not _same_float(row.get("q"), Q):
        errors.append(f"q_mismatch:{prefix}")
    if "weak_delta" in row and not _same_float(row.get("weak_delta"), WEAK_DELTA):
        errors.append(f"weak_delta_mismatch:{prefix}")
    if (
        "denominator_scope" in row
        and row.get("denominator_scope") != "pair_common_valid"
    ):
        errors.append(f"denominator_scope_mismatch:{prefix}")
    return errors


def _rows(
    artifacts: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]], key: str
) -> list[Mapping[str, Any]]:
    artifact = artifacts.get(key)
    return list(artifact[1]) if artifact else []


def _row_is_all_null(row: Mapping[str, Any]) -> bool:
    values = [value for key, value in row.items() if key not in {"variant_id"}]
    return bool(values) and all(
        str(value).strip().lower() in {"", "none", "null"} for value in values
    )


def _input_row_is_valid(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return False
    return (
        row.get("eligible") is True
        and str(row.get("validity_status")) == "valid"
        and _optional_float(row.get("score")) is not None
    )


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip().lower() in {"", "none", "null"}:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return -1


def _same_float(left: Any, right: float) -> bool:
    value = _optional_float(left)
    return value is not None and abs(value - right) <= 1e-12


def _same_optional_float(left: Any, right: Any) -> bool:
    left_value = _optional_float(left)
    right_value = _optional_float(right)
    if left_value is None or right_value is None:
        return left_value is None and right_value is None
    return abs(left_value - right_value) <= 1e-12


def _same_ratio(value: Any, numerator: int, denominator: int) -> bool:
    actual = _optional_float(value)
    expected = None if denominator == 0 else numerator / denominator
    if actual is None or expected is None:
        return actual is None and expected is None
    return abs(actual - expected) <= 1e-12


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _manifest_path(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def _file_row_count(path: Path, name: str) -> int:
    if path.suffix.lower() == ".csv":
        _headers, rows = read_csv_artifact(path)
        return len(rows)
    return len(path.read_text(encoding="utf-8").splitlines())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
