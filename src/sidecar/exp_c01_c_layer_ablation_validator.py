"""Independent contract, artifact, manifest, and anomaly validation for EXP-C01."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import subprocess
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
YEAR_ACTIVE_CONCENTRATION_THRESHOLD = 0.50
SECURITY_ACTIVE_CONCENTRATION_THRESHOLD = 0.10
CANDIDATE_ACTIVE_COUNT_RATIO_LOW = 0.25
CANDIDATE_ACTIVE_COUNT_RATIO_HIGH = 4.0
INTERSECTION_INTEGER_TOLERANCE = 1e-6
REQUIRED_RESULT_ANALYSIS_HEADINGS = (
    "## 1. Actual run / reviewed SHA / input lineage",
    "## 2. Fixed parameters and variants",
    "## 3. Cardinality and date range",
    "## 4. Core counts",
    "## 5. Overlap",
    "## 6. Score correlations and score differences",
    "## 7. Duration, fragments, and transitions",
    "## 8. Availability",
    "## 9. Year profiles",
    "## 10. Security profiles",
    "## 11. Baseline reconciliation",
    "## 12. Anomaly scan",
    "## 13. Independent recomputation",
    "## 14. Alternative explanations",
    "## 15. Supported conclusions",
    "## 16. Unsupported conclusions",
    "## 17. Readiness for user formal-result review",
)

_SOURCE_ARTIFACT_ALIASES = {
    "indicator_score": (
        "indicator_score",
        "r0_t05_indicator_score",
        "r0_t05_indicator_score_results",
    ),
    "dimension_score": (
        "dimension_score",
        "r0_t05_dimension_score",
        "r0_t05_dimension_score_results",
    ),
    "dimension_state": (
        "dimension_state",
        "r0_t06_dimension_state",
        "r0_t06_dimension_state_results",
        "r0_t15_dimension_state",
        "r0_t15_dimension_state_results",
    ),
}


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
            if manifest.get("phase") == "formal_run":
                errors.extend(
                    "manifest_canonical_text:" + item
                    for item in _canonical_text_errors(manifest_path.read_bytes())
                )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"manifest_read_error:{exc}")
            manifest = {}

    if config is not None:
        errors.extend(validate_static_config(config))
    errors.extend(
        _validate_variant_profile(
            artifacts.get("variant_profile"), artifacts.get("year_profile")
        )
    )
    errors.extend(
        _validate_overlap_profile(
            artifacts.get("overlap_profile"), artifacts.get("variant_profile")
        )
    )
    errors.extend(_validate_score_comparison(artifacts.get("score_comparison")))
    errors.extend(_validate_year_profile(artifacts.get("year_profile")))
    errors.extend(_validate_security_profile(artifacts.get("security_profile")))
    errors.extend(_validate_availability_profile(artifacts.get("availability_profile")))
    recomputation = recompute_readback_metrics(artifacts)
    errors.extend(f"readback_mismatch:{item}" for item in recomputation["mismatches"])

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
        analysis_path = root / OUTPUT_FILES["result_analysis"]
        if analysis_path.is_file():
            errors.extend(_validate_result_analysis(analysis_path))
        anomaly_path = root / OUTPUT_FILES["anomaly_scan"]
        if anomaly_path.is_file():
            try:
                errors.extend(
                    "anomaly_scan_canonical_text:" + item
                    for item in _canonical_text_errors(anomaly_path.read_bytes())
                )
                stored_anomaly = _load_json(anomaly_path)
                if stored_anomaly != anomaly_scan:
                    errors.append("anomaly_scan_file_mismatch")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"anomaly_scan_read_error:{exc}")
        validator_path = root / OUTPUT_FILES["validator_result"]
        if validator_path.is_file():
            try:
                errors.extend(
                    "validator_result_canonical_text:" + item
                    for item in _canonical_text_errors(validator_path.read_bytes())
                )
                stored_validator = _load_json(validator_path)
                if stored_validator.get("task_id") != TASK_ID:
                    errors.append("validator_result_task_id_mismatch")
                if stored_validator.get("status") not in {"passed", "failed"}:
                    errors.append("validator_result_status_invalid")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"validator_result_read_error:{exc}")

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
    input_contract = config.get("input_contract")
    if not isinstance(input_contract, Mapping):
        errors.append("config_input_contract_missing")
    else:
        if input_contract.get("source_manifest_required") is not True:
            errors.append("config_source_manifest_not_required")
        if input_contract.get("source_manifest_cli") != "--input-manifest":
            errors.append("config_source_manifest_cli_mismatch")
        expected_resolution = (
            "declared_path_relative_to_manifest_parent; "
            "basename_local_only_opt_in; no_recursive_search"
        )
        if input_contract.get("source_manifest_resolution") != expected_resolution:
            errors.append("config_source_manifest_resolution_mismatch")
    thresholds = config.get("anomaly_thresholds")
    expected_thresholds = {
        "year_active_concentration_share": YEAR_ACTIVE_CONCENTRATION_THRESHOLD,
        "security_active_concentration_share": SECURITY_ACTIVE_CONCENTRATION_THRESHOLD,
        "candidate_active_count_ratio_low": CANDIDATE_ACTIVE_COUNT_RATIO_LOW,
        "candidate_active_count_ratio_high": CANDIDATE_ACTIVE_COUNT_RATIO_HIGH,
    }
    if not isinstance(thresholds, Mapping):
        errors.append("config_anomaly_thresholds_missing")
    else:
        for key, expected in expected_thresholds.items():
            if not _same_float(thresholds.get(key), expected):
                errors.append(f"config_anomaly_threshold_mismatch:{key}")
    return errors


def _validate_result_analysis(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"result_analysis_read_error:{exc}"]
    errors = [
        "result_analysis_canonical_text:" + item for item in _canonical_text_errors(raw)
    ]
    lines = set(text.splitlines())
    errors.extend(
        f"result_analysis_missing_section:{heading}"
        for heading in REQUIRED_RESULT_ANALYSIS_HEADINGS
        if heading not in lines
    )
    readiness_values = {
        "ready_for_user_formal_result_review",
        "needs_investigation_before_user_review",
    }
    if sum(value in text for value in readiness_values) != 1:
        errors.append("result_analysis_readiness_status_invalid")
    forbidden_phrases = (
        "accepted",
        "selected indicator",
        "delete c1",
        "delete c2",
        "replacement approved",
        "replacement_approved",
        "c_v2",
        "winner",
    )
    lowered = text.lower()
    errors.extend(
        f"result_analysis_forbidden_phrase:{phrase}"
        for phrase in forbidden_phrases
        if phrase in lowered
    )
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


def extract_source_artifact_declaration(
    source_manifest: Mapping[str, Any],
    artifact_name: str,
    config_artifact: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Extract one authorized input declaration without searching the filesystem.

    Upstream R0 manifests have used both a normalized ``input_artifacts`` mapping
    and task-specific keys such as ``r0_t05_indicator_score``.  This adapter
    accepts those declared JSON shapes, but it never guesses a path from a local
    directory.  The caller remains responsible for resolving and hashing the
    declared path.
    """

    filename = str(config_artifact.get("filename", ""))
    aliases = {
        alias.lower() for alias in _SOURCE_ARTIFACT_ALIASES.get(artifact_name, ())
    }

    def walk(value: Any, key_hint: str = "") -> dict[str, Any] | None:
        if isinstance(value, Mapping):
            normalized_hint = key_hint.lower()
            candidate = _normalize_source_declaration(value, filename)
            hint_matches = any(alias in normalized_hint for alias in aliases)
            if candidate.get("path") and (
                hint_matches or _declaration_matches_filename(candidate, filename)
            ):
                return candidate
            for key, nested in value.items():
                found = walk(nested, str(key))
                if found is not None:
                    return found
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            for nested in value:
                found = walk(nested, key_hint)
                if found is not None:
                    return found
        return None

    for container_key in ("input_artifacts", "artifacts", "outputs"):
        container = source_manifest.get(container_key)
        if isinstance(container, Mapping):
            for key, value in container.items():
                if not isinstance(value, Mapping):
                    continue
                if any(alias in str(key).lower() for alias in aliases):
                    candidate = _normalize_source_declaration(value, filename)
                    if candidate.get("path"):
                        return candidate
    return walk(source_manifest)


def _normalize_source_declaration(
    value: Mapping[str, Any], filename: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, nested in value.items():
        key_text = str(key).lower()
        if "sha256" in key_text and isinstance(nested, str):
            result.setdefault("sha256", nested)
        elif "row_count" in key_text:
            result.setdefault("row_count", nested)
        elif key_text in {"table", "table_name", "relation"}:
            result.setdefault("table", nested)
        elif key_text in {"security_count", "input_security_count"}:
            result.setdefault("security_count", nested)
        elif key_text in {"date_min", "input_date_min"}:
            result.setdefault("date_min", nested)
        elif key_text in {"date_max", "input_date_max"}:
            result.setdefault("date_max", nested)
        elif key_text in {
            "path",
            "duckdb_path",
            "file_path",
            "output_path",
        } and isinstance(nested, str):
            result.setdefault("path", nested)
        elif isinstance(nested, str) and Path(nested).name == filename:
            result.setdefault("path", nested)
        elif isinstance(nested, bool) and key_text in {
            "local_only_relocation",
            "allow_local_relocation",
        }:
            result.setdefault("local_only_relocation", nested)
        elif key_text in {"path_policy", "resolution_policy"}:
            result.setdefault("path_policy", nested)
    return result


def _declaration_matches_filename(
    declaration: Mapping[str, Any], filename: str
) -> bool:
    path = declaration.get("path")
    return isinstance(path, str) and Path(path).name == filename


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

    source_manifest_value = manifest.get("source_manifest_path")
    source_manifest_hash = manifest.get("source_manifest_sha256")
    source_manifest: dict[str, Any] = {}
    source_manifest_path: Path | None = None
    if not source_manifest_value:
        errors.append("manifest_source_manifest_path_missing")
    else:
        source_manifest_path = _manifest_path(root, source_manifest_value)
        if not source_manifest_path.is_file():
            errors.append("manifest_source_manifest_file_missing")
        else:
            actual_source_hash = _sha256_file(source_manifest_path)
            if source_manifest_hash != actual_source_hash:
                errors.append("manifest_source_manifest_hash_mismatch")
            if manifest.get("phase") == "formal_run":
                errors.extend(
                    "manifest_source_manifest_canonical_text:" + item
                    for item in _canonical_text_errors(
                        source_manifest_path.read_bytes()
                    )
                )
            try:
                source_manifest = _load_json(source_manifest_path)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"manifest_source_manifest_read_error:{exc}")
            expected_schema = manifest.get("source_manifest_schema_version")
            actual_schema = source_manifest.get(
                "schema_version", source_manifest.get("input_schema_version")
            )
            if expected_schema != actual_schema:
                errors.append("manifest_source_manifest_schema_mismatch")

    input_artifacts = manifest.get("input_artifacts")
    source_artifacts = manifest.get("source_manifest_artifacts")
    expected_input_names = set(_SOURCE_ARTIFACT_ALIASES)
    if not isinstance(input_artifacts, Mapping):
        errors.append("manifest_input_artifacts_missing")
    elif set(input_artifacts) != expected_input_names:
        errors.append("manifest_input_artifact_set_mismatch")
    if not isinstance(source_artifacts, Mapping):
        errors.append("manifest_source_manifest_artifacts_missing")
    elif set(source_artifacts) != expected_input_names:
        errors.append("manifest_source_manifest_artifact_set_mismatch")

    if isinstance(input_artifacts, Mapping):
        for name in sorted(expected_input_names):
            entry = input_artifacts.get(name)
            if not isinstance(entry, Mapping):
                errors.append(f"manifest_input_entry_invalid:{name}")
                continue
            path_value = entry.get("path")
            if not path_value:
                errors.append(f"manifest_input_path_missing:{name}")
                continue
            path = _manifest_path(root, path_value)
            if not path.is_file():
                errors.append(f"manifest_input_file_missing:{name}")
                continue
            actual_hash = _sha256_file(path)
            if entry.get("sha256") != actual_hash:
                errors.append(f"manifest_input_hash_mismatch:{name}")
            full_count = _nonnegative_int(entry.get("source_full_row_count"))
            filtered_count = _nonnegative_int(entry.get("query_filtered_row_count"))
            if full_count is None:
                errors.append(f"manifest_input_source_full_row_count_invalid:{name}")
            if filtered_count is None:
                errors.append(f"manifest_input_query_filtered_row_count_invalid:{name}")
            if entry.get("row_count") != entry.get("source_full_row_count"):
                errors.append(f"manifest_input_row_count_alias_mismatch:{name}")
            table = entry.get("actual_table", entry.get("table"))
            required_columns = entry.get("required_columns")
            if not isinstance(table, str) or not table:
                errors.append(f"manifest_input_table_missing:{name}")
            if not isinstance(required_columns, Sequence) or isinstance(
                required_columns, str
            ):
                errors.append(f"manifest_input_required_columns_missing:{name}")
            else:
                actual_columns = entry.get("actual_columns")
                if not isinstance(actual_columns, Sequence) or isinstance(
                    actual_columns, str
                ):
                    errors.append(f"manifest_input_actual_columns_missing:{name}")
                elif not set(required_columns).issubset(set(actual_columns)):
                    errors.append(f"manifest_input_required_column_mismatch:{name}")
            declared_for_duckdb: Mapping[str, Any] = {}
            if source_manifest:
                config_artifact = _config_source_artifact(config, name, entry)
                declared = extract_source_artifact_declaration(
                    source_manifest, name, config_artifact
                )
                if declared is None:
                    errors.append(f"manifest_source_declaration_missing:{name}")
                else:
                    declared_for_duckdb = declared
                    stored_declared = {
                        "path": entry.get("source_manifest_declared_path"),
                        "sha256": entry.get("source_manifest_declared_sha256"),
                        "row_count": entry.get("source_manifest_declared_row_count"),
                        "table": entry.get("source_manifest_declared_table"),
                        "security_count": entry.get(
                            "source_manifest_declared_security_count"
                        ),
                        "date_min": entry.get("source_manifest_declared_date_min"),
                        "date_max": entry.get("source_manifest_declared_date_max"),
                    }
                    for field in ("path", "sha256", "row_count", "table"):
                        if field not in declared:
                            errors.append(
                                f"manifest_source_declaration_field_missing:{name}:{field}"
                            )
                        elif stored_declared[field] != declared[field]:
                            errors.append(
                                f"manifest_source_declaration_mismatch:{name}:{field}"
                            )
                    for field in ("security_count", "date_min", "date_max"):
                        if (
                            field in declared
                            and stored_declared[field] != declared[field]
                        ):
                            errors.append(
                                f"manifest_source_declaration_mismatch:{name}:{field}"
                            )
                    stored_source_artifact = (
                        source_artifacts.get(name)
                        if isinstance(source_artifacts, Mapping)
                        else None
                    )
                    if not isinstance(stored_source_artifact, Mapping):
                        errors.append(f"manifest_source_artifact_entry_missing:{name}")
                    else:
                        for field, value in declared.items():
                            if stored_source_artifact.get(field) != value:
                                errors.append(
                                    f"manifest_source_artifact_mismatch:{name}:{field}"
                                )
                    if (
                        full_count is not None
                        and declared.get("row_count") != full_count
                    ):
                        errors.append(
                            f"manifest_input_source_row_count_mismatch:{name}"
                        )
                    if declared.get("sha256") != entry.get("sha256"):
                        errors.append(f"manifest_input_source_hash_mismatch:{name}")
                    if declared.get("table") != table:
                        errors.append(f"manifest_input_source_table_mismatch:{name}")
            if (
                isinstance(table, str)
                and isinstance(required_columns, Sequence)
                and not isinstance(required_columns, str)
            ):
                errors.extend(
                    f"manifest_input_duckdb:{name}:{item}"
                    for item in _validate_duckdb_binding(
                        path,
                        table,
                        [str(column) for column in required_columns],
                        full_count,
                        expected_security_count=declared_for_duckdb.get(
                            "security_count"
                        ),
                        expected_date_min=declared_for_duckdb.get("date_min"),
                        expected_date_max=declared_for_duckdb.get("date_max"),
                    )
                )

    config_binding = manifest.get("config")
    if not isinstance(config_binding, Mapping):
        errors.append("manifest_config_binding_missing")
    else:
        config_path_value = config_binding.get("path")
        if config_path_value:
            config_path = Path(str(config_path_value))
            if not config_path.is_file():
                errors.append("manifest_config_file_missing")
            elif config_binding.get("sha256") != _sha256_file(config_path):
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
    execution = manifest.get("execution")
    if manifest.get("phase") == "formal_run":
        if not isinstance(execution, Mapping) or not isinstance(
            execution.get("source_bindings"), Mapping
        ):
            errors.append("manifest_formal_source_bindings_missing")
        else:
            errors.extend(
                f"manifest_formal_source_binding:{item}"
                for item in _validate_formal_source_bindings(
                    execution["source_bindings"], manifest.get("implementation_sha")
                )
            )
    return errors


def scan_anomalies(
    artifacts: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]],
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    anomalies: list[dict[str, Any]] = []
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
                        "detail": {"variant_id": str(row.get("variant_id"))},
                    }
                )

    overlap_by_pair = {
        (str(row.get("left_variant")), str(row.get("right_variant"))): row
        for row in overlap_rows
    }
    if len(overlap_rows) == 3 and all(
        _int(row.get("symmetric_difference_count")) == 0 for row in overlap_rows
    ):
        anomalies.append(
            {
                "code": "three_variants_identical",
                "detail": {"all_pairwise_symmetric_difference_count": 0},
            }
        )
    for candidate in (C1_VARIANT, C2_VARIANT):
        row = overlap_by_pair.get((BASELINE_VARIANT, candidate))
        if row is None:
            row = overlap_by_pair.get((candidate, BASELINE_VARIANT))
        if row is not None and _int(row.get("symmetric_difference_count")) == 0:
            anomalies.append(
                {
                    "code": f"candidate_no_identity_response:{candidate}",
                    "detail": {
                        "candidate_variant": candidate,
                        "baseline_variant": BASELINE_VARIANT,
                        "symmetric_difference_count": 0,
                    },
                }
            )

    variant_by_id = {str(row.get("variant_id")): row for row in variant_rows}
    baseline_count = _int(
        variant_by_id.get(BASELINE_VARIANT, {}).get("active_true_count")
    )
    for candidate in (C1_VARIANT, C2_VARIANT):
        candidate_count = _int(
            variant_by_id.get(candidate, {}).get("active_true_count")
        )
        if baseline_count > 0:
            ratio: float | None = candidate_count / baseline_count
            shifted = (
                ratio < CANDIDATE_ACTIVE_COUNT_RATIO_LOW
                or ratio > CANDIDATE_ACTIVE_COUNT_RATIO_HIGH
            )
        else:
            ratio = None
            shifted = candidate_count > 0
        if shifted:
            anomalies.append(
                {
                    "code": "candidate_active_count_order_of_magnitude_shift",
                    "detail": {
                        "candidate_variant": candidate,
                        "baseline_active_count": baseline_count,
                        "candidate_active_count": candidate_count,
                        "candidate_to_baseline_ratio": ratio,
                        "ratio_low": CANDIDATE_ACTIVE_COUNT_RATIO_LOW,
                        "ratio_high": CANDIDATE_ACTIVE_COUNT_RATIO_HIGH,
                        "baseline_zero": baseline_count == 0,
                    },
                }
            )

    for variant_id in VARIANT_IDS:
        stats = _year_variant_stats(year_rows, variant_id)
        if (
            stats["total_active_count"] > 0
            and stats["max_active_share"] > YEAR_ACTIVE_CONCENTRATION_THRESHOLD
        ):
            anomalies.append(
                {
                    "code": "year_active_concentration",
                    "detail": {
                        "variant": variant_id,
                        "variant_id": variant_id,
                        "share": stats["max_active_share"],
                        "max_year_active_share": stats["max_active_share"],
                        "dominant_year": stats["dominant_year"],
                        "dominant_active_count": stats["dominant_active_count"],
                        "dominant_year_active_count": stats["dominant_active_count"],
                        "total_active_count": stats["total_active_count"],
                        "threshold": YEAR_ACTIVE_CONCENTRATION_THRESHOLD,
                    },
                }
            )

    if security_rows:
        by_candidate: dict[str, list[Mapping[str, Any]]] = {}
        for row in security_rows:
            by_candidate.setdefault(str(row.get("candidate_variant")), []).append(row)
        for candidate, rows in by_candidate.items():
            for field, code in (
                ("baseline_true_count", "baseline_security_active_concentration"),
                ("candidate_true_count", "candidate_security_active_concentration"),
            ):
                total = sum(_int(row.get(field)) for row in rows)
                dominant = max(rows, key=lambda row: _int(row.get(field)), default=None)
                maximum = _int(dominant.get(field)) if dominant else 0
                if (
                    total > 0
                    and maximum / total > SECURITY_ACTIVE_CONCENTRATION_THRESHOLD
                ):
                    anomalies.append(
                        {
                            "code": code,
                            "detail": {
                                "candidate": candidate,
                                "candidate_variant": candidate,
                                "security_id": (
                                    dominant.get("security_id") if dominant else None
                                ),
                                "share": maximum / total,
                                "active_count": maximum,
                                "total_active_count": total,
                                "threshold": SECURITY_ACTIVE_CONCENTRATION_THRESHOLD,
                            },
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
                            "detail": {"indicator_id": str(row.get("indicator_id"))},
                        }
                    )
                if _int(row.get("availability_gain_vs_pair")) != native - reported_pair:
                    anomalies.append(
                        {
                            "code": "availability_gain_mismatch",
                            "detail": {"indicator_id": str(row.get("indicator_id"))},
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
                    "detail": {"mismatch_fields": list(RECONCILIATION_MISMATCH_FIELDS)},
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
    year_artifact: tuple[Sequence[str], Sequence[Mapping[str, Any]]] | None,
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
        valid_block_count = _int(row.get("valid_block_count"))
        expected_valid_steps = eligible - valid_block_count
        if _int(row.get("valid_step_count")) != expected_valid_steps:
            errors.append(f"valid_step_count_mismatch:{variant_id}")
        transition_count = _int(row.get("transition_count"))
        if transition_count < 0 or transition_count > expected_valid_steps:
            errors.append(f"transition_step_count_mismatch:{variant_id}")
        expected_transition_rate = (
            None
            if expected_valid_steps == 0
            else transition_count * 100.0 / expected_valid_steps
        )
        if not _same_optional_float(
            row.get("transition_rate_per_100_valid_steps"), expected_transition_rate
        ):
            errors.append(f"transition_rate_mismatch:{variant_id}")
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
        if year_artifact is not None:
            year_stats = _year_variant_stats(year_artifact[1], variant_id)
            if not _same_optional_float(
                row.get("max_year_active_share"), year_stats["max_active_share"]
            ):
                errors.append(f"max_year_active_share_mismatch:{variant_id}")
            if not _same_optional_float(
                row.get("max_year_active_rate"), year_stats["max_active_rate"]
            ):
                errors.append(f"max_year_active_rate_mismatch:{variant_id}")
            if _int(row.get("nonzero_year_count")) != year_stats["nonzero_year_count"]:
                errors.append(f"nonzero_year_count_mismatch:{variant_id}")
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


def recompute_readback_metrics(
    artifacts: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, Any]]]],
) -> dict[str, Any]:
    """Recompute formula-derived values from the six persisted CSVs.

    This deliberately does not consume in-memory observations or the builder's
    intermediate objects.  It is used both by the final validator and by the
    result-analysis generator.
    """

    mismatches: list[str] = []
    variant_rows = _rows(artifacts, "variant_profile")
    overlap_rows = _rows(artifacts, "overlap_profile")
    year_rows = _rows(artifacts, "year_profile")
    security_rows = _rows(artifacts, "security_profile")
    availability_rows = _rows(artifacts, "availability_profile")
    variant_metrics: dict[str, dict[str, Any]] = {}

    for row in variant_rows:
        variant = str(row.get("variant_id"))
        eligible = _int(row.get("eligible_row_count"))
        active_true = _int(row.get("active_true_count"))
        active_false = _int(row.get("active_false_count"))
        blocks = _int(row.get("valid_block_count"))
        steps = eligible - blocks
        transitions = _int(row.get("transition_count"))
        segment_count = _int(row.get("segment_count"))
        singleton_count = _int(row.get("singleton_segment_count"))
        year_stats = _year_variant_stats(year_rows, variant)
        expected = {
            "active_rate": _ratio_value(active_true, eligible),
            "valid_step_count": steps,
            "transition_rate_per_100_valid_steps": (
                None if steps == 0 else transitions * 100.0 / steps
            ),
            "segment_duration_sum": active_true,
            "singleton_segment_ratio": _ratio_value(singleton_count, segment_count),
            "max_year_active_share": year_stats["max_active_share"],
            "max_year_active_rate": year_stats["max_active_rate"],
        }
        for field, expected_value in expected.items():
            actual = row.get(field)
            if field in {"valid_step_count", "segment_duration_sum"}:
                if _int(actual) != expected_value:
                    mismatches.append(f"variant:{variant}:{field}")
            elif not _same_optional_float(actual, expected_value):
                mismatches.append(f"variant:{variant}:{field}")
        if active_true + active_false != eligible:
            mismatches.append(f"variant:{variant}:active_count_conservation")
        variant_metrics[variant] = {
            **expected,
            "eligible_row_count": eligible,
            "active_true_count": active_true,
            "active_false_count": active_false,
            "transition_count": transitions,
            "valid_block_count": blocks,
            "segment_count": segment_count,
            "nonzero_year_count": year_stats["nonzero_year_count"],
            "dominant_year": year_stats["dominant_year"],
            "dominant_active_count": year_stats["dominant_active_count"],
            "total_active_count": year_stats["total_active_count"],
        }

    overlap_metrics: list[dict[str, Any]] = []
    for row in overlap_rows:
        pair = f"{row.get('left_variant')}:{row.get('right_variant')}"
        common = _int(row.get("common_valid_rows"))
        n11 = _int(row.get("n11"))
        n10 = _int(row.get("n10"))
        n01 = _int(row.get("n01"))
        n00 = _int(row.get("n00"))
        left_true = n11 + n10
        right_true = n11 + n01
        union = n11 + n10 + n01
        expected = {
            "left_true_count": left_true,
            "right_true_count": right_true,
            "jaccard": _ratio_value(n11, union),
            "left_given_right": _ratio_value(n11, right_true),
            "right_given_left": _ratio_value(n11, left_true),
            "symmetric_difference_count": n10 + n01,
            "symmetric_difference_rate": _ratio_value(n10 + n01, common),
        }
        if n11 + n10 + n01 + n00 != common:
            mismatches.append(f"overlap:{pair}:n2x2")
        for field, expected_value in expected.items():
            actual = row.get(field)
            if field.endswith("_count"):
                if _int(actual) != expected_value:
                    mismatches.append(f"overlap:{pair}:{field}")
            elif not _same_optional_float(actual, expected_value):
                mismatches.append(f"overlap:{pair}:{field}")
        overlap_metrics.append(
            {
                "left_variant": str(row.get("left_variant")),
                "right_variant": str(row.get("right_variant")),
                "common_valid_rows": common,
                **expected,
            }
        )

    year_metrics = [
        {
            "calendar_year": _int(row.get("calendar_year")),
            "candidate_variant": str(row.get("candidate_variant")),
            "common_valid_rows": _int(row.get("common_valid_rows")),
            "baseline_true_count": _int(row.get("baseline_true_count")),
            "candidate_true_count": _int(row.get("candidate_true_count")),
            "jaccard": _optional_float(row.get("jaccard")),
            "baseline_retention": _optional_float(row.get("baseline_retention")),
            "candidate_precision": _optional_float(row.get("candidate_precision")),
            "symmetric_difference_rate": _optional_float(
                row.get("symmetric_difference_rate")
            ),
        }
        for row in year_rows
    ]
    for row in year_rows:
        key = f"{row.get('calendar_year')}:{row.get('candidate_variant')}"
        common = _int(row.get("common_valid_rows"))
        baseline_true = _int(row.get("baseline_true_count"))
        candidate_true = _int(row.get("candidate_true_count"))
        _intersection, overlap_errors = _recompute_overlap_ratio_fields(
            row,
            f"year:{key}",
            denominator=common,
            include_symmetric_difference=True,
        )
        mismatches.extend(overlap_errors)
        if not _same_optional_float(
            row.get("baseline_active_rate"), _ratio_value(baseline_true, common)
        ):
            mismatches.append(f"year:{key}:baseline_active_rate")
        if not _same_optional_float(
            row.get("candidate_active_rate"), _ratio_value(candidate_true, common)
        ):
            mismatches.append(f"year:{key}:candidate_active_rate")
        if not _same_optional_float(
            row.get("active_rate"), _ratio_value(candidate_true, common)
        ):
            mismatches.append(f"year:{key}:active_rate")

    security_metrics = [
        {
            "security_id": str(row.get("security_id")),
            "candidate_variant": str(row.get("candidate_variant")),
            "valid_row_count": _int(row.get("valid_row_count")),
            "baseline_true_count": _int(row.get("baseline_true_count")),
            "candidate_true_count": _int(row.get("candidate_true_count")),
            "jaccard": _optional_float(row.get("jaccard")),
            "baseline_retention": _optional_float(row.get("baseline_retention")),
            "candidate_precision": _optional_float(row.get("candidate_precision")),
        }
        for row in security_rows
    ]
    for row in security_rows:
        key = f"{row.get('security_id')}:{row.get('candidate_variant')}"
        valid = _int(row.get("valid_row_count"))
        _intersection, overlap_errors = _recompute_overlap_ratio_fields(
            row,
            f"security:{key}",
            denominator=valid,
            include_symmetric_difference=False,
        )
        mismatches.extend(overlap_errors)

    availability_metrics: list[dict[str, Any]] = []
    pair_count = next(
        (
            _int(row.get("pair_common_valid_count"))
            for row in availability_rows
            if row.get("indicator_id") == "pair_common_valid"
        ),
        None,
    )
    for row in availability_rows:
        indicator = str(row.get("indicator_id"))
        native = _int(row.get("native_valid_count"))
        reported_pair = _int(row.get("pair_common_valid_count"))
        expected_gain = (
            0 if indicator == "pair_common_valid" else native - reported_pair
        )
        if (
            indicator in {C1_ID, C2_ID}
            and pair_count is not None
            and reported_pair != pair_count
        ):
            mismatches.append(f"availability:{indicator}:pair_common_valid_count")
        if _int(row.get("availability_gain_vs_pair")) != expected_gain:
            mismatches.append(f"availability:{indicator}:availability_gain_vs_pair")
        availability_metrics.append(
            {
                "indicator_id": indicator,
                "input_row_count": _int(row.get("input_row_count")),
                "native_valid_count": native,
                "pair_common_valid_count": reported_pair,
                "availability_gain_vs_pair": expected_gain,
            }
        )

    return {
        "status": "passed" if not mismatches else "failed",
        "mismatches": list(dict.fromkeys(mismatches)),
        "variant_metrics": variant_metrics,
        "overlap_metrics": overlap_metrics,
        "year_metrics": year_metrics,
        "security_metrics": security_metrics,
        "availability_metrics": availability_metrics,
    }


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


def _ratio_value(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _recompute_overlap_ratio_fields(
    row: Mapping[str, Any],
    prefix: str,
    *,
    denominator: int,
    include_symmetric_difference: bool,
) -> tuple[int, list[str]]:
    """Cross-check overlap ratios from the persisted count fields.

    Year and security profiles do not persist a full n2x2 table.  Their three
    overlap ratios therefore provide redundant implied-intersection estimates;
    inconsistent estimates are still a readback failure rather than silently
    trusting one copied CSV value.  The selected intersection is an integer so
    normal CSV float round-tripping cannot turn a valid count into a mismatch.
    """

    baseline = _int(row.get("baseline_true_count"))
    candidate = _int(row.get("candidate_true_count"))
    errors: list[str] = []
    if baseline < 0 or candidate < 0 or denominator < 0:
        errors.append(f"negative_count:{prefix}")
    if baseline > denominator or candidate > denominator:
        errors.append(f"active_count_exceeds_denominator:{prefix}")

    implied_intersections: list[float] = []
    retention = _optional_float(row.get("baseline_retention"))
    precision = _optional_float(row.get("candidate_precision"))
    jaccard = _optional_float(row.get("jaccard"))
    if retention is not None:
        implied_intersections.append(retention * baseline)
    if precision is not None:
        implied_intersections.append(precision * candidate)
    if jaccard is not None:
        if jaccard < 0.0 or jaccard > 1.0:
            errors.append(f"jaccard_out_of_range:{prefix}")
        elif baseline + candidate == 0:
            implied_intersections.append(0.0)
        else:
            implied_intersections.append(
                jaccard * (baseline + candidate) / (1.0 + jaccard)
            )

    rounded_intersections = [int(round(value)) for value in implied_intersections]
    for value, rounded in zip(
        implied_intersections, rounded_intersections, strict=True
    ):
        if abs(value - rounded) > INTERSECTION_INTEGER_TOLERANCE:
            errors.append(f"implied_intersection_not_integer:{prefix}")
    if rounded_intersections and len(set(rounded_intersections)) != 1:
        errors.append(f"implied_intersection_mismatch:{prefix}")
    intersection = rounded_intersections[0] if rounded_intersections else 0
    if intersection < 0 or intersection > min(baseline, candidate):
        errors.append(f"implied_intersection_out_of_range:{prefix}")

    expected = {
        "jaccard": _ratio_value(intersection, baseline + candidate - intersection),
        "baseline_retention": _ratio_value(intersection, baseline),
        "candidate_precision": _ratio_value(intersection, candidate),
    }
    if include_symmetric_difference:
        expected["symmetric_difference_rate"] = _ratio_value(
            baseline + candidate - 2.0 * intersection, denominator
        )
    for field, expected_value in expected.items():
        if not _same_optional_float(row.get(field), expected_value):
            errors.append(f"{field}_mismatch:{prefix}")
    return intersection, errors


def _year_variant_stats(
    rows: Sequence[Mapping[str, Any]], variant_id: str
) -> dict[str, Any]:
    by_year: dict[int, dict[str, int]] = {}
    for row in rows:
        candidate = str(row.get("candidate_variant"))
        if candidate not in {C1_VARIANT, C2_VARIANT}:
            continue
        year = _int(row.get("calendar_year"))
        if year < 0:
            continue
        if variant_id == BASELINE_VARIANT:
            by_year.setdefault(
                year,
                {
                    "valid_count": _int(row.get("common_valid_rows")),
                    "active_count": _int(row.get("baseline_true_count")),
                },
            )
        elif candidate == variant_id:
            by_year[year] = {
                "valid_count": _int(row.get("common_valid_rows")),
                "active_count": _int(row.get("candidate_true_count")),
            }
    total_active = sum(max(0, value["active_count"]) for value in by_year.values())
    if total_active == 0:
        return {
            "total_active_count": 0,
            "max_active_share": None,
            "max_active_rate": None,
            "dominant_year": None,
            "dominant_active_count": 0,
            "nonzero_year_count": 0,
        }
    dominant_year = max(
        by_year,
        key=lambda year: (by_year[year]["active_count"], -year),
    )
    active_rates = [
        value["active_count"] / value["valid_count"]
        for value in by_year.values()
        if value["valid_count"] > 0
    ]
    return {
        "total_active_count": total_active,
        "max_active_share": by_year[dominant_year]["active_count"] / total_active,
        "max_active_rate": max(active_rates) if active_rates else None,
        "dominant_year": dominant_year,
        "dominant_active_count": by_year[dominant_year]["active_count"],
        "nonzero_year_count": sum(
            1 for value in by_year.values() if value["active_count"] > 0
        ),
    }


def _nonnegative_int(value: Any) -> int | None:
    numeric = _int(value)
    return numeric if numeric >= 0 else None


def _config_source_artifact(
    config: Mapping[str, Any] | None,
    name: str,
    entry: Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(config, Mapping):
        input_contract = config.get("input_contract")
        if isinstance(input_contract, Mapping):
            artifacts = input_contract.get("artifacts")
            if isinstance(artifacts, Mapping) and isinstance(
                artifacts.get(name), Mapping
            ):
                return artifacts[name]
    return {"filename": entry.get("filename", Path(str(entry.get("path", ""))).name)}


def _validate_duckdb_binding(
    path: Path,
    table: str,
    required_columns: Sequence[str],
    expected_full_row_count: int | None,
    *,
    expected_security_count: Any = None,
    expected_date_min: Any = None,
    expected_date_max: Any = None,
) -> list[str]:
    try:
        import duckdb

        _assert_identifier(table)
        connection = duckdb.connect(str(path), read_only=True)
        try:
            table_rows = connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                [table],
            ).fetchall()
            if not table_rows:
                return ["table_missing"]
            columns = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table)})"
                ).fetchall()
            }
            missing = sorted(set(required_columns) - columns)
            errors = [f"required_column_missing:{column}" for column in missing]
            full_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
                ).fetchone()[0]
            )
            if (
                expected_full_row_count is not None
                and full_count != expected_full_row_count
            ):
                errors.append(
                    f"full_row_count_mismatch:{expected_full_row_count}:{full_count}"
                )
            if expected_security_count is not None and "security_id" in columns:
                actual_security_count = int(
                    connection.execute(
                        f"SELECT COUNT(DISTINCT {_quote_identifier('security_id')}) "
                        f"FROM {_quote_identifier(table)}"
                    ).fetchone()[0]
                )
                if actual_security_count != int(expected_security_count):
                    errors.append(
                        "security_count_mismatch:"
                        f"{expected_security_count}:{actual_security_count}"
                    )
            if (
                expected_date_min not in (None, "")
                or expected_date_max not in (None, "")
            ) and "trading_date" in columns:
                actual_date_min, actual_date_max = connection.execute(
                    f"SELECT MIN({_quote_identifier('trading_date')}), "
                    f"MAX({_quote_identifier('trading_date')}) "
                    f"FROM {_quote_identifier(table)}"
                ).fetchone()
                actual_date_min_text = _canonical_date_text(actual_date_min)
                actual_date_max_text = _canonical_date_text(actual_date_max)
                if expected_date_min not in (
                    None,
                    "",
                ) and actual_date_min_text != _canonical_date_text(expected_date_min):
                    errors.append(
                        f"date_min_mismatch:{expected_date_min}:{actual_date_min_text}"
                    )
                if expected_date_max not in (
                    None,
                    "",
                ) and actual_date_max_text != _canonical_date_text(expected_date_max):
                    errors.append(
                        f"date_max_mismatch:{expected_date_max}:{actual_date_max_text}"
                    )
            return errors
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001
        return [f"read_error:{exc}"]


def _assert_identifier(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"unsafe SQL identifier: {value}")


def _quote_identifier(value: str) -> str:
    _assert_identifier(value)
    return f'"{value}"'


def _validate_formal_source_bindings(
    bindings: Mapping[str, Any], implementation_sha: Any
) -> list[str]:
    root = Path(__file__).resolve().parents[2]
    errors: list[str] = []
    expected_names = {"config", "schema", "runner", "core", "validator"}
    if set(bindings) != expected_names:
        errors.append("source_binding_set_mismatch")
    for name in sorted(expected_names):
        entry = bindings.get(name)
        if not isinstance(entry, Mapping):
            errors.append(f"entry_missing:{name}")
            continue
        source_commit = str(entry.get("source_commit", ""))
        if implementation_sha and source_commit != str(implementation_sha):
            errors.append(f"source_commit_mismatch:{name}")
        relative = str(entry.get("path", ""))
        path = root / relative
        if not relative or not path.is_file():
            errors.append(f"source_file_missing:{name}")
            continue
        try:
            committed = subprocess.run(
                ["git", "show", f"{source_commit}:{relative}"],
                cwd=str(root),
                check=True,
                capture_output=True,
            ).stdout
            blob_sha = subprocess.run(
                ["git", "rev-parse", f"{source_commit}:{relative}"],
                cwd=str(root),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            errors.append(f"git_read_error:{name}:{exc}")
            continue
        text_errors = _canonical_text_errors(committed)
        errors.extend(f"canonical_text:{name}:{item}" for item in text_errors)
        committed_hash = hashlib.sha256(committed).hexdigest()
        if entry.get("git_blob_sha") != blob_sha:
            errors.append(f"blob_sha_mismatch:{name}")
        if entry.get("committed_byte_sha256") != committed_hash:
            errors.append(f"committed_byte_sha_mismatch:{name}")
        if entry.get("normalized_text_sha256") != committed_hash:
            errors.append(f"normalized_text_sha_mismatch:{name}")
        if path.read_bytes() != committed:
            errors.append(f"working_tree_source_mismatch:{name}")
    return errors


def _canonical_text_errors(raw: bytes) -> list[str]:
    errors: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("bom")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("not_utf8")
    if b"\r" in raw:
        errors.append("bare_or_crlf")
    if not raw.endswith(b"\n"):
        errors.append("missing_final_lf")
    elif raw.endswith(b"\n\n"):
        errors.append("multiple_final_lf")
    return errors


def _canonical_date_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        text = value.isoformat()
    else:
        text = str(value).replace("T", " ").split(" ", 1)[0]
    if re.fullmatch(r"[0-9]{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


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
