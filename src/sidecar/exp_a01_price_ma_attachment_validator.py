"""Independent validation helpers for EXP-A01 configuration and raw metrics."""

# SQL templates intentionally preserve readable independent expressions.
# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

TASK_ID = "EXP-A01"
A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
INDICATOR_IDS = (A1_ID, A2_ID, A2B_ID)
A1_REQUIRED_OBSERVATIONS = 60
A2_REQUIRED_OBSERVATIONS = 79
METRIC_ENGINE_VERSION = "exp_a01_price_ma_attachment.v1"
RAW_METRIC_NAMES = {
    A1_ID: "LogBodyCenterToMACloudCenter_5_60",
    A2_ID: "BodyCenterOutsideMACloudRate20_5_60",
    A2B_ID: "BodyToMACloudGapMean20_5_60",
}
OUTPUT_FIELDS = (
    "security_id",
    "trading_date",
    "indicator_id",
    "raw_metric_name",
    "raw_value",
    "validity_status",
    "reason_codes",
    "input_window_start",
    "input_window_end",
    "required_observation_count",
    "actual_valid_observation_count",
    "metric_engine_version",
)
REASON_CODES = (
    "valid_no_blocker",
    "window_insufficient",
    "missing_adjusted_open",
    "missing_adjusted_close",
    "missing_required_history",
    "nonpositive_adjusted_open",
    "nonpositive_adjusted_close",
    "nonpositive_MA",
    "adjustment_failure",
    "suspension_in_required_window",
    "listing_pause_in_required_window",
    "invalid_trading_status",
    "reopen_after_suspension",
)
VALIDITY_STATUSES = ("valid", "unknown", "blocked", "diagnostic_required")
D3_T07_CONTRACT = "D3_T07_CANDIDATE_DAILY_OBSERVATION_CONTRACT_V1"
D3_T08_CONTRACT = "D3_T08_RESEARCH_DATASET_REGISTRY_CONTRACT_V1"
INDEX_CONTRACT = "EXP_A01_EXPECTED_PRICE_OBSERVATION_INDEX_V1"
FORBIDDEN_FIELD_TOKENS = (
    "percentile",
    "score",
    "state",
    "winner",
    "selected_indicator",
    "replacement_approved",
    "future_return",
    "future_volatility",
    "future_direction",
    "backtest",
    "portfolio",
    "transaction_cost",
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_ARTIFACTS = (
    "d3_t07_candidate_daily_observation",
    "d3_t07_handoff_report",
    "d3_t07_quality_report",
    "d3_t08_handoff_report",
    "d3_t08_quality_report",
    "expected_price_observation_index",
)
EXPECTED_CANDIDATES = (
    {
        "indicator_id": A1_ID,
        "raw_metric_name": RAW_METRIC_NAMES[A1_ID],
        "minimum_history": A1_REQUIRED_OBSERVATIONS,
        "raw_value_domain": "finite_nonnegative",
    },
    {
        "indicator_id": A2_ID,
        "raw_metric_name": RAW_METRIC_NAMES[A2_ID],
        "minimum_history": A2_REQUIRED_OBSERVATIONS,
        "raw_value_domain": "finite_unit_interval",
    },
    {
        "indicator_id": A2B_ID,
        "raw_metric_name": RAW_METRIC_NAMES[A2B_ID],
        "minimum_history": A2_REQUIRED_OBSERVATIONS,
        "raw_value_domain": "finite_nonnegative",
    },
)


def validate_static_config(config: Mapping[str, Any]) -> list[str]:
    """Return deterministic errors for the frozen A01 implementation boundary."""

    errors: list[str] = []
    for key, expected in {
        "task_id": TASK_ID,
        "experiment_id": TASK_ID,
        "program_id": "EXP-A",
        "research_route": "sidecar_exploration",
        "candidate_layer": "A",
        "candidate_layer_name": "price_ma_attachment",
        "workflow_mode": "long_lived_same_pr",
        "phase": "implementation_review",
        "program_phase": "A01_formal_execution_package_implementation",
        "implementation_review_status": "pending",
        "reviewed_implementation_sha": "",
        "formal_run_allowed": False,
        "formal_run_status": "not_started",
        "formal_run_executed": False,
        "formal_artifacts_generated": False,
        "result_review_status": "not_started",
        "EXP-A02_started": False,
        "mainline_task_unchanged": True,
        "mainline_current_task": "R3-T02",
        "formal_layer_registered": False,
        "pcvt_modified": False,
        "pcatv_created": False,
        "existing_indicator_modified": False,
        "future_outcome_used": False,
    }.items():
        if config.get(key) != expected:
            errors.append(f"config_{key}_mismatch")

    price_basis = config.get("price_basis")
    if not isinstance(price_basis, Mapping):
        errors.append("config_price_basis_missing")
    else:
        if price_basis.get("authoritative_contract") != D3_T07_CONTRACT:
            errors.append("config_authoritative_adjusted_ohlc_contract_mismatch")
        if price_basis.get("authoritative_object") != "d3_candidate_daily_observation":
            errors.append("config_authoritative_object_mismatch")
        if price_basis.get("candidate_materialization_contract") != D3_T07_CONTRACT:
            errors.append("config_candidate_materialization_contract_mismatch")
        if price_basis.get("source_role") != "exploration_research_candidate":
            errors.append("config_source_role_mismatch")
        if price_basis.get("formal_data_version") is not False:
            errors.append("config_formal_data_version_mismatch")
        if price_basis.get("raw_ohlc_forbidden") is not True:
            errors.append("config_raw_ohlc_not_forbidden")
        if price_basis.get("future_observations_forbidden") is not True:
            errors.append("config_future_observations_not_forbidden")
        if price_basis.get("centered_moving_average_forbidden") is not True:
            errors.append("config_centered_ma_not_forbidden")
        if price_basis.get("adjusted_fields") != [
            "adjusted_open",
            "adjusted_high",
            "adjusted_low",
            "adjusted_close",
        ]:
            errors.append("config_adjusted_fields_mismatch")
        if price_basis.get("canonical_column_mapping") != {
            "security_id": "ts_code",
            "trading_date": "trade_date",
            "adjusted_open": "adjusted_open",
            "adjusted_close": "adjusted_close",
            "adjustment_factor": "effective_adj_factor",
        }:
            errors.append("config_canonical_column_mapping_mismatch")
        if price_basis.get("moving_average_windows") != [5, 10, 20, 30, 60]:
            errors.append("config_ma_windows_mismatch")
        if set(price_basis.get("trading_status_allowed_values", [])) != {
            "normal_trading",
            "limit_up",
            "limit_down",
            "one_price_limit_up",
            "one_price_limit_down",
        }:
            errors.append("config_trading_status_vocabulary_mismatch")
        if set(price_basis.get("daily_status_allowed_values", [])) != {"resolved"}:
            errors.append("config_daily_status_vocabulary_mismatch")
        if set(price_basis.get("adjustment_factor_status_allowed_values", [])) != {
            "resolved",
            "not_applicable_or_carry_forward",
            "neutral_factor_1_policy",
            "factor_interval_policy",
        }:
            errors.append("config_adjustment_status_vocabulary_mismatch")
        if "candidate_input_aliases" in price_basis:
            errors.append("config_hybrid_input_aliases_forbidden")
        for forbidden in (
            "continuous_ohlc_integrity_status",
            "adjustment_method",
            "factor_as_of_time",
            "corporate_action_flag",
        ):
            if forbidden in json.dumps(price_basis, ensure_ascii=False):
                errors.append(f"config_forced_field_forbidden:{forbidden}")

    parameters = config.get("parameters")
    if not isinstance(parameters, Mapping):
        errors.append("config_parameters_missing")
    else:
        for key, expected in {
            "ma_windows": [5, 10, 20, 30, 60],
            "a2_rolling_window": 20,
            "a1_required_observations": 60,
            "a2_required_observations": 79,
            "current_day_included": True,
            "raw_value_direction": "lower_is_more_attached",
        }.items():
            if parameters.get(key) != expected:
                errors.append(f"config_parameter_{key}_mismatch")

    candidates = config.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, str | bytes):
        errors.append("config_candidates_missing")
    else:
        candidate_ids = [
            item.get("indicator_id") for item in candidates if isinstance(item, Mapping)
        ]
        if tuple(candidate_ids) != INDICATOR_IDS:
            errors.append("config_candidate_ids_mismatch")
        for expected, actual in zip(EXPECTED_CANDIDATES, candidates, strict=False):
            if not isinstance(actual, Mapping):
                errors.append("config_candidate_not_mapping")
                continue
            for key, value in expected.items():
                if actual.get(key) != value:
                    errors.append(
                        f"config_candidate_{key}_mismatch:{expected['indicator_id']}"
                    )

    validity = config.get("validity_contract")
    if not isinstance(validity, Mapping):
        errors.append("config_validity_contract_missing")
    else:
        if validity.get("validity_statuses") != list(VALIDITY_STATUSES):
            errors.append("config_validity_statuses_mismatch")
        if set(validity.get("reason_codes", [])) != set(REASON_CODES):
            errors.append("config_reason_codes_mismatch")
        if validity.get("unknown_not_false") is not True:
            errors.append("config_unknown_not_false_mismatch")
        if validity.get("invalid_has_no_ordinary_numeric_raw_value") is not True:
            errors.append("config_invalid_numeric_guard_mismatch")

    input_contract = config.get("input_contract")
    if not isinstance(input_contract, Mapping):
        errors.append("config_input_contract_missing")
    else:
        for key, expected in {
            "source_manifest_required": True,
            "source_manifest_cli": "--input-manifest",
            "input_root_cli": "--input-root",
            "input_root_env": "CONVERGENCE_RESEARCH_INPUT_ROOT",
            "source_manifest_resolution": (
                "absolute_declared_path_or_relative_to_manifest_parent; "
                "no_recursive_search"
            ),
            "implementation_does_not_open_real_large_duckdb": True,
        }.items():
            if input_contract.get(key) != expected:
                errors.append(f"config_input_{key}_mismatch")
        names = input_contract.get("manifest_artifact_names")
        if tuple(names or ()) != EXPECTED_ARTIFACTS:
            errors.append("config_manifest_artifact_names_mismatch")
        artifacts = input_contract.get("artifacts")
        if not isinstance(artifacts, Mapping) or set(artifacts) != set(
            EXPECTED_ARTIFACTS
        ):
            errors.append("config_input_artifacts_mismatch")
        else:
            for artifact_id in EXPECTED_ARTIFACTS:
                artifact = artifacts[artifact_id]
                if not isinstance(artifact, Mapping):
                    errors.append(f"config_artifact_not_mapping:{artifact_id}")
                    continue
                if artifact.get("artifact_id") != artifact_id:
                    errors.append(f"config_artifact_id_mismatch:{artifact_id}")
                if artifact.get("formal_data_version") is not False:
                    errors.append(f"config_artifact_formal_data_version:{artifact_id}")
                kind = artifact.get("artifact_kind")
                if kind == "duckdb_table":
                    if not artifact.get("table") or not artifact.get(
                        "required_columns"
                    ):
                        errors.append(
                            f"config_duckdb_artifact_schema_missing:{artifact_id}"
                        )
                elif kind == "evidence_json":
                    if not artifact.get("required_json_fields"):
                        errors.append(f"config_evidence_fields_missing:{artifact_id}")
                else:
                    errors.append(f"config_artifact_kind_mismatch:{artifact_id}")
            candidate = artifacts.get("d3_t07_candidate_daily_observation", {})
            if isinstance(candidate, Mapping):
                if candidate.get("source_contract") != D3_T07_CONTRACT:
                    errors.append("config_input_source_contract_mismatch")
                required_columns = set(candidate.get("required_columns", []))
                if required_columns != {
                    "ts_code",
                    "trade_date",
                    "adjusted_open",
                    "adjusted_close",
                    "trading_status",
                    "daily_status",
                    "effective_adj_factor",
                    "adjustment_factor_status",
                    "is_listing_pause",
                    "source_task_id",
                    "generated_by_task",
                    "row_provenance",
                }:
                    errors.append("config_input_required_columns_mismatch")
            index_artifact = artifacts.get("expected_price_observation_index", {})
            if (
                isinstance(index_artifact, Mapping)
                and index_artifact.get("source_contract") != INDEX_CONTRACT
            ):
                errors.append("config_expected_index_source_contract_mismatch")

    for gate_name in (
        "d3_t07_evidence_gate",
        "d3_t08_evidence_gate",
        "dense_window_contract",
    ):
        if not isinstance(config.get(gate_name), Mapping):
            errors.append(f"config_{gate_name}_missing")
    output_contract = config.get("output_contract")
    if not isinstance(output_contract, Mapping):
        errors.append("config_output_contract_missing")
    else:
        if output_contract.get("formal_execution_implemented") is not True:
            errors.append("config_output_formal_execution_missing")
        if output_contract.get("no_formal_output_in_implementation") is not False:
            errors.append("config_output_formal_guard_mismatch")
        if output_contract.get("parallel_mode") != "single_threaded":
            errors.append("config_output_parallel_mode_mismatch")
        if output_contract.get("worker_count") != 1:
            errors.append("config_output_worker_count_mismatch")
        if output_contract.get("duckdb_threads") != 1:
            errors.append("config_output_duckdb_threads_mismatch")
        if output_contract.get("memory_limit") != "8GB":
            errors.append("config_output_memory_limit_mismatch")
        if output_contract.get("run_id_pattern") != (
            "^EXP-A01-[0-9]{8}T[0-9]{6}(?:[0-9]{3,6})?Z$"
        ):
            errors.append("config_output_run_id_pattern_mismatch")
        raw_table = output_contract.get("raw_metric_table")
        if (
            not isinstance(raw_table, Mapping)
            or raw_table.get("table") != "exp_a01_raw_metrics"
        ):
            errors.append("config_output_raw_table_mismatch")
        forbidden = output_contract.get("forbidden_output_fields")
        if not isinstance(forbidden, Sequence) or isinstance(forbidden, str | bytes):
            errors.append("config_forbidden_output_fields_missing")
        else:
            for token in FORBIDDEN_FIELD_TOKENS:
                if token not in {str(value) for value in forbidden}:
                    errors.append(f"config_forbidden_output_token_missing:{token}")

    return list(dict.fromkeys(errors))


def validate_metric_rows(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Independently validate core output rows and prohibited-field boundaries."""

    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    last_key: tuple[str, str, int] | None = None
    order = {indicator_id: index for index, indicator_id in enumerate(INDICATOR_IDS)}
    expected_by_id = {item["indicator_id"]: item for item in EXPECTED_CANDIDATES}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"row_{index}_not_mapping")
            continue
        fields = {str(key) for key in row}
        missing = set(OUTPUT_FIELDS) - fields
        extra = fields - set(OUTPUT_FIELDS)
        if missing:
            errors.append(f"row_{index}_missing_fields:{sorted(missing)}")
        if extra:
            errors.append(f"row_{index}_unexpected_fields:{sorted(extra)}")
        forbidden = sorted(
            field
            for field in fields
            if any(token in field.lower() for token in FORBIDDEN_FIELD_TOKENS)
        )
        if forbidden:
            errors.append(f"row_{index}_forbidden_fields:{forbidden}")
        try:
            security_id = str(row["security_id"])
            trading_date = str(row["trading_date"])
            indicator_id = str(row["indicator_id"])
        except KeyError:
            continue
        if not security_id or not DATE_PATTERN.fullmatch(trading_date):
            errors.append(f"row_{index}_identity_invalid")
        if indicator_id not in order:
            errors.append(f"row_{index}_indicator_invalid:{indicator_id}")
            continue
        key = security_id, trading_date, indicator_id
        if key in seen:
            errors.append(f"row_{index}_duplicate_key:{key}")
        seen.add(key)
        sort_key = security_id, trading_date, order[indicator_id]
        if last_key is not None and sort_key < last_key:
            errors.append(f"row_{index}_not_deterministically_sorted")
        last_key = sort_key

        expected = expected_by_id[indicator_id]
        if row.get("raw_metric_name") != expected["raw_metric_name"]:
            errors.append(f"row_{index}_raw_metric_name_mismatch")
        if row.get("required_observation_count") != expected["minimum_history"]:
            errors.append(f"row_{index}_required_observation_count_mismatch")
        if row.get("metric_engine_version") != METRIC_ENGINE_VERSION:
            errors.append(f"row_{index}_engine_version_mismatch")
        for field in ("input_window_start", "input_window_end"):
            value = row.get(field)
            if value is not None and not DATE_PATTERN.fullmatch(str(value)):
                errors.append(f"row_{index}_{field}_invalid")
        status = row.get("validity_status")
        reasons = row.get("reason_codes")
        if status not in VALIDITY_STATUSES:
            errors.append(f"row_{index}_validity_status_invalid")
        if not isinstance(reasons, Sequence) or isinstance(reasons, str | bytes):
            errors.append(f"row_{index}_reason_codes_invalid")
            reasons = []
        unknown_reasons = sorted(
            set(str(reason) for reason in reasons) - set(REASON_CODES)
        )
        if unknown_reasons:
            errors.append(f"row_{index}_unknown_reason_codes:{unknown_reasons}")
        raw_value = row.get("raw_value")
        if status == "valid":
            if reasons != ["valid_no_blocker"]:
                errors.append(f"row_{index}_valid_reason_codes_invalid")
            if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                errors.append(f"row_{index}_valid_raw_value_missing")
            elif not math.isfinite(float(raw_value)) or float(raw_value) < 0.0:
                errors.append(f"row_{index}_valid_raw_value_domain_invalid")
            elif indicator_id == A2_ID and float(raw_value) > 1.0:
                errors.append(f"row_{index}_a2_raw_value_out_of_range")
        else:
            if raw_value is not None:
                errors.append(f"row_{index}_invalid_raw_value_present")
            if not reasons:
                errors.append(f"row_{index}_invalid_reason_codes_empty")
            if "valid_no_blocker" in reasons:
                errors.append(f"row_{index}_invalid_has_valid_reason")
        actual_count = row.get("actual_valid_observation_count")
        if not isinstance(actual_count, int) or isinstance(actual_count, bool):
            errors.append(f"row_{index}_actual_valid_count_invalid")
        elif actual_count < 0 or actual_count > expected["minimum_history"]:
            errors.append(f"row_{index}_actual_valid_count_out_of_range")
        elif status == "valid" and actual_count != expected["minimum_history"]:
            errors.append(f"row_{index}_valid_count_not_full_window")
    return list(dict.fromkeys(errors))


def validate_output_directory(
    output_dir: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a future A01 directory without generating or modifying it."""

    root = Path(output_dir)
    errors: list[str] = []
    if not root.is_dir():
        return {
            "task_id": TASK_ID,
            "status": "failed",
            "valid": False,
            "errors": [f"output_directory_missing:{root}"],
        }
    for path in root.iterdir():
        if any(token in path.name.lower() for token in FORBIDDEN_FIELD_TOKENS):
            errors.append(f"forbidden_output_filename:{path.name}")
    if config is not None:
        errors.extend(validate_static_config(config))
    expected = set(EXPECTED_FORMAL_FILES)
    actual = {path.name for path in root.iterdir()}
    errors.extend(f"missing_output_file:{name}" for name in sorted(expected - actual))
    errors.extend(
        f"unexpected_output_file:{name}" for name in sorted(actual - expected)
    )
    return {
        "task_id": TASK_ID,
        "status": "passed" if not errors else "failed",
        "valid": not errors,
        "errors": list(dict.fromkeys(errors)),
        "checked_files": sorted(path.name for path in root.iterdir()),
    }


def canonical_text_errors(raw: bytes) -> list[str]:
    """Return deterministic UTF-8/LF errors for formal evidence text."""

    errors: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("bom_present")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("not_utf8")
    if b"\r" in raw:
        errors.append("bare_or_crlf_line_ending")
    if not raw.endswith(b"\n"):
        errors.append("missing_final_lf")
    if raw.endswith(b"\n\n"):
        errors.append("more_than_one_final_lf")
    return errors


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON object with a small, testable helper."""

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


RAW_TABLE_COLUMNS = (
    "run_id",
    "security_id",
    "trading_date",
    "observation_sequence",
    "expected_observation_status",
    "indicator_id",
    "raw_metric_name",
    "raw_value",
    "validity_status",
    "reason_codes_json",
    "input_window_start",
    "input_window_end",
    "required_observation_count",
    "actual_valid_observation_count",
    "metric_engine_version",
    "source_ref",
)
EXPECTED_FORMAL_FILES = (
    "exp_a01_raw_metrics.duckdb",
    "exp_a01_metric_profile.csv",
    "exp_a01_validity_profile.csv",
    "exp_a01_year_coverage.csv",
    "exp_a01_security_coverage.csv",
    "exp_a01_manifest.json",
    "exp_a01_validator_result.json",
    "exp_a01_anomaly_scan.json",
    "exp_a01_result_analysis.md",
)
CSV_FIELDS = {
    "exp_a01_metric_profile.csv": (
        "indicator_id",
        "required_observation_count",
        "total_row_count",
        "valid_count",
        "unknown_count",
        "blocked_count",
        "diagnostic_required_count",
        "valid_rate",
        "zero_count",
        "zero_rate_among_valid",
        "positive_count",
        "unique_value_count",
        "min_value",
        "mean_value",
        "stddev_pop_value",
        "q01_value",
        "q05_value",
        "q25_value",
        "median_value",
        "q75_value",
        "q95_value",
        "q99_value",
        "max_value",
        "first_valid_date",
        "last_valid_date",
        "unique_security_count",
        "valid_security_count",
        "nonzero_year_count",
        "max_year_valid_share",
        "max_security_valid_share",
    ),
    "exp_a01_validity_profile.csv": (
        "indicator_id",
        "profile_dimension",
        "profile_value",
        "row_count",
        "denominator_count",
        "row_share",
    ),
    "exp_a01_year_coverage.csv": (
        "calendar_year",
        "indicator_id",
        "row_count",
        "valid_count",
        "valid_rate",
        "zero_count",
        "zero_rate_among_valid",
        "min_value",
        "q05_value",
        "median_value",
        "q95_value",
        "max_value",
        "unique_security_count",
        "valid_security_count",
    ),
    "exp_a01_security_coverage.csv": (
        "security_id",
        "indicator_id",
        "row_count",
        "valid_count",
        "valid_rate",
        "zero_count",
        "zero_rate_among_valid",
        "first_date",
        "last_date",
        "first_valid_date",
        "last_valid_date",
        "min_value",
        "median_value",
        "max_value",
    ),
}
_SEVERE_REASONS = {
    "adjustment_failure",
    "invalid_trading_status",
    "nonpositive_adjusted_open",
    "nonpositive_adjusted_close",
    "nonpositive_MA",
    "suspension_in_required_window",
    "listing_pause_in_required_window",
}


def validate_formal_result(
    output_dir: str | Path,
    *,
    config: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    input_manifest_path: str | Path,
    input_paths: Mapping[str, str | Path],
    input_metadata: Mapping[str, Mapping[str, Any]],
    expected_index_row_count: int,
    reviewed_implementation_sha: str,
    require_final_manifest: bool = True,
) -> dict[str, Any]:
    """Independently validate persisted raw rows and all compact profiles."""

    root = Path(output_dir)
    errors: list[str] = []
    mismatch_counts = {
        "raw_table_schema_mismatch": 0,
        "raw_row_count_mismatch": 0,
        "duplicate_result_key": 0,
        "validity_domain_mismatch": 0,
        "reason_code_domain_mismatch": 0,
        "independent_recompute_mismatch": 0,
        "metric_profile_mismatch": 0,
        "validity_profile_mismatch": 0,
        "year_coverage_mismatch": 0,
        "security_coverage_mismatch": 0,
        "artifact_hash_mismatch": 0,
        "input_hash_changed": 0,
        "analysis_section_mismatch": 0,
        "prohibited_output_mismatch": 0,
    }
    if not root.is_dir():
        return _validation_result(
            errors=[f"output_directory_missing:{root}"],
            mismatch_counts=mismatch_counts,
            reviewed_implementation_sha=reviewed_implementation_sha,
            input_manifest=input_manifest,
            input_manifest_path=input_manifest_path,
        )
    actual_files = {path.name for path in root.iterdir()}
    expected_files = {
        "exp_a01_raw_metrics.duckdb",
        "exp_a01_metric_profile.csv",
        "exp_a01_validity_profile.csv",
        "exp_a01_year_coverage.csv",
        "exp_a01_security_coverage.csv",
        "exp_a01_manifest.json",
    }
    if require_final_manifest:
        expected_files.update(
            {
                "exp_a01_validator_result.json",
                "exp_a01_anomaly_scan.json",
                "exp_a01_result_analysis.md",
            }
        )
    for missing in sorted(expected_files - actual_files):
        errors.append(f"missing_output_file:{missing}")
    for extra in sorted(actual_files - expected_files):
        errors.append(f"unexpected_output_file:{extra}")
    manifest_path = root / "exp_a01_manifest.json"
    formal_manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest_raw = manifest_path.read_bytes()
            text_errors = canonical_text_errors(manifest_raw)
            if text_errors:
                errors.append(f"formal_manifest_text_contract:{text_errors}")
            formal_manifest = json.loads(manifest_raw.decode("utf-8"))
            if not isinstance(formal_manifest, dict):
                errors.append("formal_manifest_root_not_object")
                formal_manifest = {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"formal_manifest_invalid:{exc}")
    if require_final_manifest:
        _validate_final_manifest_identity(
            formal_manifest,
            errors,
            reviewed_implementation_sha=reviewed_implementation_sha,
            input_manifest=input_manifest,
            input_manifest_path=input_manifest_path,
        )

    raw_path = root / "exp_a01_raw_metrics.duckdb"
    if raw_path.is_file():
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover
            errors.append(f"duckdb_import_failed:{exc}")
        else:
            connection = duckdb.connect(str(raw_path), read_only=True)
            try:
                _validate_raw_table_schema(connection, errors, mismatch_counts)
                raw_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM exp_a01_raw_metrics"
                    ).fetchone()[0]
                )
                expected_count = expected_index_row_count * 3
                if raw_count != expected_count:
                    mismatch_counts["raw_row_count_mismatch"] += 1
                    errors.append(
                        f"raw_row_count_mismatch:expected={expected_count}:actual={raw_count}"
                    )
                duplicate_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM (
                          SELECT security_id, trading_date, indicator_id
                          FROM exp_a01_raw_metrics
                          GROUP BY security_id, trading_date, indicator_id
                          HAVING COUNT(*) > 1
                        )
                        """
                    ).fetchone()[0]
                )
                if duplicate_count:
                    mismatch_counts["duplicate_result_key"] += duplicate_count
                    errors.append(f"duplicate_result_key:{duplicate_count}")
                _validate_raw_domains(connection, errors, mismatch_counts)
                _validate_raw_against_independent_recompute(
                    connection,
                    input_paths=input_paths,
                    expected_index_row_count=expected_index_row_count,
                    run_id=str(formal_manifest.get("run_id", "")),
                    errors=errors,
                    mismatch_counts=mismatch_counts,
                )
                for filename in CSV_FIELDS:
                    path = root / filename
                    if not path.is_file():
                        continue
                    expected_rows = _expected_profile_rows(connection, filename)
                    _compare_csv_file(
                        path,
                        filename,
                        expected_rows,
                        errors,
                        mismatch_counts,
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"independent_validation_exception:{exc}")
                mismatch_counts["independent_recompute_mismatch"] += 1
            finally:
                connection.close()

    if require_final_manifest:
        _validate_output_artifact_hashes(root, formal_manifest, errors, mismatch_counts)
        analysis_path = root / "exp_a01_result_analysis.md"
        if analysis_path.is_file():
            analysis_errors = canonical_text_errors(analysis_path.read_bytes())
            if analysis_errors:
                mismatch_counts["analysis_section_mismatch"] += 1
                errors.append(f"analysis_text_contract:{analysis_errors}")
            required_sections = [
                "Actual run / reviewed SHA",
                "Input manifest and authorization",
                "D3-T07 lineage",
                "D3-T08 evidence",
                "Dense expected-index reconciliation",
                "Fixed candidate definitions",
                "Raw table cardinality",
                "Metric domains and distributions",
                "Validity status profile",
                "Reason-code profile",
                "Year coverage",
                "Security coverage",
                "Independent full recomputation",
                "Validator result",
                "Anomaly scan",
                "Supported and unsupported conclusions",
                "Readiness for user Formal-result review",
            ]
            analysis_text = analysis_path.read_text(encoding="utf-8")
            missing_sections = [
                section for section in required_sections if section not in analysis_text
            ]
            if missing_sections:
                mismatch_counts["analysis_section_mismatch"] += len(missing_sections)
                errors.append(f"analysis_required_sections_missing:{missing_sections}")
            if any(
                token in analysis_text.lower()
                for token in (
                    "future_volatility",
                    "future_direction",
                    "future_outcome",
                    "backtest",
                    "winner",
                    "selected_indicator",
                    "replacement",
                    "pcatv",
                    "prediction",
                    "return",
                    "portfolio",
                    "transaction_cost",
                    "a layer approved",
                    "a02 decision",
                )
            ):
                mismatch_counts["prohibited_output_mismatch"] += 1
                errors.append("analysis_contains_prohibited_output_token")

    for artifact_id, metadata in input_metadata.items():
        path = Path(str(metadata.get("path", input_paths[artifact_id])))
        actual_hash = sha256_file(path)
        if actual_hash != metadata.get("sha256"):
            mismatch_counts["input_hash_changed"] += 1
            errors.append(f"input_hash_changed:{artifact_id}")

    result = _validation_result(
        errors=list(dict.fromkeys(errors)),
        mismatch_counts=mismatch_counts,
        reviewed_implementation_sha=reviewed_implementation_sha,
        input_manifest=input_manifest,
        input_manifest_path=input_manifest_path,
        formal_manifest=formal_manifest,
    )
    result["input_hash_after_run"] = {
        artifact_id: sha256_file(
            Path(str(metadata.get("path", input_paths[artifact_id])))
        )
        for artifact_id, metadata in input_metadata.items()
    }
    if isinstance(formal_manifest.get("output_artifacts"), Mapping):
        result["artifact_hash_checks"] = {
            filename: {
                "declared_sha256": declaration.get("sha256"),
                "actual_sha256": sha256_file(root / filename),
                "match": declaration.get("sha256") == sha256_file(root / filename),
            }
            for filename, declaration in formal_manifest["output_artifacts"].items()
            if (root / filename).is_file()
        }
    return result


def scan_persisted_anomalies(
    output_dir: str | Path, *, expected_index_row_count: int
) -> dict[str, Any]:
    """Scan only persisted raw/profile/governance files for anomalies."""

    root = Path(output_dir)
    blocking: list[str] = []
    investigation: list[str] = []
    raw_path = root / "exp_a01_raw_metrics.duckdb"
    if not raw_path.is_file():
        blocking.append("empty_raw_metric_table")
    else:
        try:
            import duckdb

            connection = duckdb.connect(str(raw_path), read_only=True)
            try:
                count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM exp_a01_raw_metrics"
                    ).fetchone()[0]
                )
                if count == 0:
                    blocking.append("empty_raw_metric_table")
                if count != expected_index_row_count * 3:
                    blocking.append("row_count_not_three_times_expected_index")
                checks = (
                    (
                        "duplicate_result_key",
                        """
                        SELECT COUNT(*) FROM (
                          SELECT security_id, trading_date, indicator_id
                          FROM exp_a01_raw_metrics GROUP BY 1,2,3 HAVING COUNT(*) > 1
                        )
                        """,
                    ),
                    (
                        "valid_raw_value_null",
                        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status='valid' AND raw_value IS NULL",
                    ),
                    (
                        "invalid_raw_value_present",
                        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status <> 'valid' AND raw_value IS NOT NULL",
                    ),
                    (
                        "nonfinite_raw_value",
                        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE raw_value IS NOT NULL AND NOT isfinite(raw_value)",
                    ),
                    (
                        "negative_A1",
                        f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id='{A1_ID}' AND raw_value < 0",
                    ),
                    (
                        "negative_A2b",
                        f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id='{A2B_ID}' AND raw_value < 0",
                    ),
                    (
                        "A2_out_of_range",
                        f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id='{A2_ID}' AND (raw_value < 0 OR raw_value > 1)",
                    ),
                    (
                        "unknown_indicator",
                        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id NOT IN (?, ?, ?)",
                    ),
                    (
                        "unknown_validity_status",
                        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status NOT IN ('valid','unknown','blocked','diagnostic_required')",
                    ),
                    (
                        "unknown_reason_code",
                        """
                        SELECT COUNT(*) FROM exp_a01_raw_metrics r, LATERAL json_each(r.reason_codes_json) j
                        WHERE json_extract_string(j.value, '$') NOT IN
                          ('valid_no_blocker','window_insufficient','missing_adjusted_open','missing_adjusted_close',
                           'missing_required_history','nonpositive_adjusted_open','nonpositive_adjusted_close',
                           'nonpositive_MA','adjustment_failure','suspension_in_required_window',
                           'listing_pause_in_required_window','invalid_trading_status','reopen_after_suspension')
                        """,
                    ),
                )
                for name, query in checks:
                    statement = (
                        connection.execute(
                            query,
                            [A1_ID, A2_ID, A2B_ID]
                            if name == "unknown_indicator"
                            else None,
                        )
                        if name == "unknown_indicator"
                        else connection.execute(query)
                    )
                    value = int(statement.fetchone()[0])
                    if value:
                        blocking.append(f"{name}:{value}")
                for indicator_id in INDICATOR_IDS:
                    valid_count = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id=? AND validity_status='valid'",
                            [indicator_id],
                        ).fetchone()[0]
                    )
                    if valid_count == 0:
                        blocking.append(f"no_valid_rows:{indicator_id}")
                    else:
                        zero_count = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id=? AND validity_status='valid' AND raw_value=0",
                                [indicator_id],
                            ).fetchone()[0]
                        )
                        one_count = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id=? AND validity_status='valid' AND raw_value=1",
                                [indicator_id],
                            ).fetchone()[0]
                        )
                        distinct = int(
                            connection.execute(
                                "SELECT COUNT(DISTINCT raw_value) FROM exp_a01_raw_metrics WHERE indicator_id=? AND validity_status='valid'",
                                [indicator_id],
                            ).fetchone()[0]
                        )
                        if zero_count == valid_count:
                            investigation.append(
                                f"all_valid_values_zero:{indicator_id}"
                            )
                        if indicator_id == A2_ID and one_count == valid_count:
                            investigation.append(f"all_valid_values_one:{indicator_id}")
                        if distinct <= 1:
                            investigation.append(
                                f"constant_valid_values:{indicator_id}"
                            )
                for dimension, label, threshold in (
                    ("year", "year_valid_concentration", 0.50),
                    ("security", "security_valid_concentration", 0.10),
                ):
                    query = (
                        "SELECT indicator_id, MAX(valid_count::DOUBLE / NULLIF(total_valid,0)) "
                        "FROM (SELECT indicator_id, "
                        + (
                            "YEAR(trading_date)"
                            if dimension == "year"
                            else "security_id"
                        )
                        + " AS grouping_key, COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count, "
                        + "SUM(COUNT(*) FILTER (WHERE validity_status='valid')) OVER (PARTITION BY indicator_id) AS total_valid "
                        + "FROM exp_a01_raw_metrics GROUP BY indicator_id, grouping_key) q GROUP BY indicator_id"
                    )
                    for indicator_id, share in connection.execute(query).fetchall():
                        if share is not None and float(share) > threshold:
                            investigation.append(f"{label}:{indicator_id}:{share}")
            finally:
                connection.close()
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"anomaly_scan_exception:{exc}")

    validator_path = root / "exp_a01_validator_result.json"
    if validator_path.is_file():
        try:
            validator = load_json(validator_path)
            if (
                validator.get("status") != "passed"
                or validator.get("valid") is not True
            ):
                blocking.append("validator_failed")
            mismatches = validator.get("mismatch_counts", {})
            if int(mismatches.get("independent_recompute_mismatch", 0)):
                blocking.append("independent_recompute_mismatch")
            if int(mismatches.get("artifact_hash_mismatch", 0)):
                blocking.append("artifact_hash_mismatch")
            if int(mismatches.get("input_hash_changed", 0)):
                blocking.append("input_hash_changed")
            if any(
                int(mismatches.get(name, 0))
                for name in (
                    "metric_profile_mismatch",
                    "validity_profile_mismatch",
                    "year_coverage_mismatch",
                    "security_coverage_mismatch",
                )
            ):
                blocking.append("csv_reconciliation_mismatch")
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"validator_result_invalid:{exc}")
    else:
        blocking.append("validator_failed")
    status = (
        "failed"
        if blocking
        else ("passed_with_investigation_items" if investigation else "passed")
    )
    return {
        "task_id": TASK_ID,
        "run_id": _read_run_id(root),
        "status": status,
        "blocking_anomalies": sorted(set(blocking)),
        "investigation_items": sorted(set(investigation)),
        "blocking_anomaly_count": len(set(blocking)),
        "investigation_item_count": len(set(investigation)),
    }


def _validation_result(
    *,
    errors: list[str],
    mismatch_counts: Mapping[str, int],
    reviewed_implementation_sha: str,
    input_manifest: Mapping[str, Any],
    input_manifest_path: str | Path,
    formal_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    unique_errors = list(dict.fromkeys(errors))
    valid = not unique_errors and all(
        int(value) == 0 for value in mismatch_counts.values()
    )
    return {
        "task_id": TASK_ID,
        "run_id": (formal_manifest or {}).get("run_id"),
        "status": "passed" if valid else "failed",
        "valid": valid,
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "input_manifest_path": str(input_manifest_path),
        "checked_files": sorted(EXPECTED_FORMAL_FILES),
        "checked_tables": ["exp_a01_raw_metrics"],
        "comparison_counts": {
            "raw_rows_expected": int(
                (formal_manifest or {})
                .get("raw_metric_table", {})
                .get("expected_row_count", 0)
            ),
        },
        "mismatch_counts": {key: int(value) for key, value in mismatch_counts.items()},
        "artifact_hash_checks": {},
        "input_hash_after_run": {},
        "errors": unique_errors,
        "warnings": [],
    }


def _validate_final_manifest_identity(
    formal_manifest: Mapping[str, Any],
    errors: list[str],
    *,
    reviewed_implementation_sha: str,
    input_manifest: Mapping[str, Any],
    input_manifest_path: str | Path,
) -> None:
    if formal_manifest.get("task_id") != TASK_ID:
        errors.append("formal_manifest_task_id_mismatch")
    if formal_manifest.get("phase") != "formal_run":
        errors.append("formal_manifest_phase_mismatch")
    if (
        formal_manifest.get("reviewed_implementation_sha")
        != reviewed_implementation_sha
    ):
        errors.append("formal_manifest_reviewed_sha_mismatch")
    if formal_manifest.get("formal_data_version") is not False:
        errors.append("formal_manifest_formal_data_version_mismatch")
    expected_input_sha = sha256_file(input_manifest_path)
    actual_input_sha = str(formal_manifest.get("input_manifest_sha256", ""))
    if not actual_input_sha:
        errors.append("formal_manifest_input_sha_missing")
    if str(input_manifest_path) != str(formal_manifest.get("input_manifest_path", "")):
        errors.append("formal_manifest_input_manifest_path_mismatch")
    if actual_input_sha != expected_input_sha:
        errors.append("formal_manifest_input_manifest_sha_mismatch")


def _validate_raw_table_schema(
    connection: Any, errors: list[str], mismatches: dict[str, int]
) -> None:
    try:
        rows = connection.execute("PRAGMA table_info('exp_a01_raw_metrics')").fetchall()
    except Exception as exc:  # noqa: BLE001
        mismatches["raw_table_schema_mismatch"] += 1
        errors.append(f"raw_table_missing:{exc}")
        return
    columns = [str(row[1]) for row in rows]
    if columns != list(RAW_TABLE_COLUMNS):
        mismatches["raw_table_schema_mismatch"] += 1
        errors.append(f"raw_table_columns_mismatch:{columns}")
    types = {str(row[1]): str(row[2]).upper() for row in rows}
    for column, expected in {
        "trading_date": "DATE",
        "raw_value": "DOUBLE",
        "reason_codes_json": "VARCHAR",
        "input_window_start": "DATE",
        "input_window_end": "DATE",
    }.items():
        if column in types and expected not in types[column]:
            mismatches["raw_table_schema_mismatch"] += 1
            errors.append(f"raw_table_type_mismatch:{column}:{types[column]}")


def _validate_raw_domains(
    connection: Any, errors: list[str], mismatches: dict[str, int]
) -> None:
    checks = (
        (
            "validity_domain_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status NOT IN ('valid','unknown','blocked','diagnostic_required')",
        ),
        (
            "validity_domain_mismatch",
            f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id NOT IN ('{A1_ID}','{A2_ID}','{A2B_ID}')",
        ),
        (
            "validity_domain_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status='valid' AND (raw_value IS NULL OR NOT isfinite(raw_value))",
        ),
        (
            "validity_domain_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status<>'valid' AND raw_value IS NOT NULL",
        ),
        (
            "validity_domain_mismatch",
            f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id IN ('{A1_ID}','{A2B_ID}') AND raw_value < 0",
        ),
        (
            "validity_domain_mismatch",
            f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id='{A2_ID}' AND (raw_value < 0 OR raw_value > 1)",
        ),
        (
            "reason_code_domain_mismatch",
            """
          SELECT COUNT(*) FROM exp_a01_raw_metrics r, LATERAL json_each(r.reason_codes_json) j
          WHERE json_extract_string(j.value, '$') NOT IN
            ('valid_no_blocker','window_insufficient','missing_adjusted_open','missing_adjusted_close',
             'missing_required_history','nonpositive_adjusted_open','nonpositive_adjusted_close','nonpositive_MA',
             'adjustment_failure','suspension_in_required_window','listing_pause_in_required_window',
             'invalid_trading_status','reopen_after_suspension')
        """,
        ),
    )
    for key, query in checks:
        count = int(connection.execute(query).fetchone()[0])
        if count:
            mismatches[key] += count
            errors.append(f"{key}:{count}")


def _validate_raw_against_independent_recompute(
    connection: Any,
    *,
    input_paths: Mapping[str, str | Path],
    expected_index_row_count: int,
    run_id: str,
    errors: list[str],
    mismatch_counts: dict[str, int],
) -> None:
    actual_cursor = connection.execute(
        """
        SELECT run_id, security_id, trading_date, observation_sequence,
               expected_observation_status, indicator_id, raw_metric_name, raw_value,
               validity_status, reason_codes_json, input_window_start, input_window_end,
               required_observation_count, actual_valid_observation_count,
               metric_engine_version, source_ref
        FROM exp_a01_raw_metrics
        ORDER BY security_id, observation_sequence,
          CASE indicator_id WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END
        """,
        [A1_ID, A2_ID],
    )
    expected = _independent_raw_rows(
        input_paths["d3_t07_candidate_daily_observation"],
        input_paths["expected_price_observation_index"],
        run_id=run_id,
    )
    checked = 0
    for actual in _fetchmany(actual_cursor):
        try:
            expected_row = next(expected)
        except StopIteration:
            mismatch_counts["independent_recompute_mismatch"] += 1
            errors.append("independent_recompute_extra_persisted_row")
            continue
        checked += 1
        differences = _compare_raw_row(expected_row, actual)
        if differences:
            mismatch_counts["independent_recompute_mismatch"] += len(differences)
            if len(errors) < 50:
                errors.append(f"independent_recompute_mismatch:{differences}")
    missing = sum(1 for _ in expected)
    if missing:
        mismatch_counts["independent_recompute_mismatch"] += missing
        errors.append(f"independent_recompute_missing_rows:{missing}")


def _fetchmany(cursor: Any, size: int = 4096) -> Iterable[tuple[Any, ...]]:
    while True:
        rows = cursor.fetchmany(size)
        if not rows:
            return
        yield from rows


def _independent_raw_rows(
    candidate_path: str | Path, index_path: str | Path, *, run_id: str
) -> Iterable[dict[str, Any]]:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for independent recomputation") from exc
    connection = duckdb.connect(":memory:")
    candidate_literal = str(candidate_path).replace("'", "''")
    index_literal = str(index_path).replace("'", "''")
    connection.execute(f"ATTACH '{candidate_literal}' AS candidate (READ_ONLY)")
    connection.execute(f"ATTACH '{index_literal}' AS expected (READ_ONLY)")
    query = """
      SELECT i.security_id,
             CAST(COALESCE(try_strptime(CAST(i.trading_date AS VARCHAR), '%Y-%m-%d'), try_strptime(CAST(i.trading_date AS VARCHAR), '%Y%m%d')) AS DATE) AS trading_date,
             CAST(i.observation_sequence AS BIGINT) AS observation_sequence,
             i.expected_observation_status,
             CASE WHEN i.expected_observation_status='present' THEN m.adjusted_open END AS adjusted_open,
             CASE WHEN i.expected_observation_status='present' THEN m.adjusted_close END AS adjusted_close,
             CASE WHEN i.expected_observation_status='present' THEN m.trading_status ELSE i.expected_observation_status END AS trading_status,
             CASE WHEN i.expected_observation_status='present' THEN m.daily_status ELSE i.expected_observation_status END AS daily_status,
             CASE WHEN i.expected_observation_status='present' THEN m.effective_adj_factor END AS effective_adj_factor,
             CASE WHEN i.expected_observation_status='present' THEN m.adjustment_factor_status END AS adjustment_factor_status,
             CASE WHEN i.expected_observation_status='present' THEN m.is_listing_pause ELSE i.expected_observation_status='listing_pause' END AS is_listing_pause,
             CASE WHEN i.expected_observation_status='present' THEN m.row_provenance ELSE i.source_ref END AS row_provenance,
             i.source_contract, i.source_ref
      FROM expected.expected_price_observation_index i
      LEFT JOIN candidate.d3_candidate_daily_observation m
        ON i.expected_observation_status='present'
       AND m.ts_code=i.security_id
       AND CAST(COALESCE(try_strptime(CAST(m.trade_date AS VARCHAR), '%Y-%m-%d'), try_strptime(CAST(m.trade_date AS VARCHAR), '%Y%m%d')) AS DATE)
           = CAST(COALESCE(try_strptime(CAST(i.trading_date AS VARCHAR), '%Y-%m-%d'), try_strptime(CAST(i.trading_date AS VARCHAR), '%Y%m%d')) AS DATE)
      ORDER BY i.security_id, i.observation_sequence
    """
    cursor = connection.execute(query)
    history_by_security: dict[str, list[dict[str, Any]]] = {}
    try:
        for row in _fetchmany(cursor):
            current = _independent_input_row(row)
            history = history_by_security.setdefault(current["security_id"], [])
            history.append(current)
            if len(history) > 79:
                del history[:-79]
            yield from _independent_metrics(history, run_id=run_id)
    finally:
        connection.close()


def _independent_input_row(row: Sequence[Any]) -> dict[str, Any]:
    trading_date = row[1]
    if isinstance(trading_date, datetime):
        trading_date = trading_date.date()
    if isinstance(trading_date, date):
        trading_date = trading_date.isoformat()
    return {
        "security_id": str(row[0]),
        "trading_date": str(trading_date),
        "observation_sequence": int(row[2]),
        "expected_observation_status": str(row[3]).lower(),
        "adjusted_open": _finite_float(row[4]),
        "adjusted_close": _finite_float(row[5]),
        "trading_status": _optional_text(row[6]),
        "daily_status": _optional_text(row[7]),
        "effective_adj_factor": _finite_float(row[8]),
        "adjustment_factor_status": _optional_text(row[9]),
        "is_listing_pause": row[10],
        "row_provenance": str(row[11] or ""),
        "source_contract": str(row[12]),
        "source_ref": str(row[13]),
    }


def _independent_metrics(
    history: list[dict[str, Any]], *, run_id: str
) -> Iterable[dict[str, Any]]:
    current = history[-1]
    for indicator_id, required in (
        (A1_ID, A1_REQUIRED_OBSERVATIONS),
        (A2_ID, A2_REQUIRED_OBSERVATIONS),
        (A2B_ID, A2_REQUIRED_OBSERVATIONS),
    ):
        window = history[-required:]
        reasons: list[str] = []
        if len(window) != required:
            reasons.extend(("window_insufficient", "missing_required_history"))
        for row in window:
            reasons.extend(_independent_row_reasons(row))
        raw_value: float | None = None
        if not reasons:
            try:
                if indicator_id == A1_ID:
                    body, _low, _high, center = _independent_cloud_point(
                        history, len(history) - 1
                    )
                    raw_value = abs(body - center)
                else:
                    points = [
                        _independent_cloud_point(history, index)
                        for index in range(len(history) - 20, len(history))
                    ]
                    if indicator_id == A2_ID:
                        raw_value = (
                            sum(
                                1.0 if _independent_outside(body, low, high) else 0.0
                                for body, low, high, _center in points
                            )
                            / 20.0
                        )
                    else:
                        raw_value = (
                            sum(
                                _independent_gap(
                                    history, len(history) - 20 + offset, body, low, high
                                )
                                for offset, (body, low, high, _center) in enumerate(
                                    points
                                )
                            )
                            / 20.0
                        )
            except (ArithmeticError, ValueError):
                reasons.append("nonpositive_MA")
        reasons = _ordered_reasons(reasons)
        if reasons or raw_value is None or not math.isfinite(raw_value):
            if not reasons:
                reasons = ["nonpositive_MA"]
            raw_value = None
            status = _status_for_reasons(reasons)
        elif raw_value < 0 or (indicator_id == A2_ID and not 0 <= raw_value <= 1):
            raw_value = None
            reasons = ["nonpositive_MA"]
            status = "blocked"
        else:
            status = "valid"
            reasons = ["valid_no_blocker"]
        yield {
            "run_id": run_id,
            "security_id": current["security_id"],
            "trading_date": current["trading_date"],
            "observation_sequence": current["observation_sequence"],
            "expected_observation_status": current["expected_observation_status"],
            "indicator_id": indicator_id,
            "raw_metric_name": RAW_METRIC_NAMES[indicator_id],
            "raw_value": raw_value,
            "validity_status": status,
            "reason_codes_json": json.dumps(reasons, separators=(",", ":")),
            "input_window_start": window[0]["trading_date"] if window else None,
            "input_window_end": current["trading_date"],
            "required_observation_count": required,
            "actual_valid_observation_count": sum(
                not _independent_row_reasons(row) for row in window
            ),
            "metric_engine_version": METRIC_ENGINE_VERSION,
            "source_ref": current["source_ref"],
        }


def _independent_row_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = row["expected_observation_status"]
    if status == "listing_pause":
        reasons.append("listing_pause_in_required_window")
    elif status == "missing":
        reasons.append("missing_required_history")
    elif status == "unresolved":
        reasons.append("adjustment_failure")
    if row["adjusted_open"] is None:
        reasons.append("missing_adjusted_open")
    elif row["adjusted_open"] <= 0:
        reasons.append("nonpositive_adjusted_open")
    if row["adjusted_close"] is None:
        reasons.append("missing_adjusted_close")
    elif row["adjusted_close"] <= 0:
        reasons.append("nonpositive_adjusted_close")
    trading_status = (row["trading_status"] or "").lower()
    if trading_status == "reopen_after_suspension":
        reasons.append("reopen_after_suspension")
    elif trading_status == "suspended":
        reasons.append("suspension_in_required_window")
    elif trading_status not in {
        "normal_trading",
        "limit_up",
        "limit_down",
        "one_price_limit_up",
        "one_price_limit_down",
    }:
        reasons.append("invalid_trading_status")
    if (row["daily_status"] or "").lower() != "resolved":
        reasons.append("missing_required_history")
    if row["is_listing_pause"] is not False and row["is_listing_pause"] != 0:
        reasons.append("listing_pause_in_required_window")
    if (
        (row["adjustment_factor_status"] or "").lower()
        not in {
            "resolved",
            "not_applicable_or_carry_forward",
            "neutral_factor_1_policy",
            "factor_interval_policy",
        }
        or row["effective_adj_factor"] is None
        or row["effective_adj_factor"] <= 0
    ):
        reasons.append("adjustment_failure")
    return _ordered_reasons(reasons)


def _independent_cloud_point(
    history: list[dict[str, Any]], index: int
) -> tuple[float, float, float, float]:
    current = history[index]
    if _independent_row_reasons(current):
        raise ValueError("invalid current observation")
    body = (
        math.log(current["adjusted_open"]) + math.log(current["adjusted_close"])
    ) / 2.0
    log_mas: list[float] = []
    for size in (5, 10, 20, 30, 60):
        window = history[index - size + 1 : index + 1]
        if len(window) != size or any(_independent_row_reasons(row) for row in window):
            raise ValueError("invalid moving-average window")
        closes = [row["adjusted_close"] for row in window]
        if any(value is None or value <= 0 for value in closes):
            raise ValueError("nonpositive moving-average input")
        moving_average = sum(closes) / size
        if not math.isfinite(moving_average) or moving_average <= 0:
            raise ValueError("nonpositive moving average")
        log_mas.append(math.log(moving_average))
    return body, min(log_mas), max(log_mas), sum(log_mas) / 5.0


def _independent_outside(body: float, low: float, high: float) -> bool:
    return body < low or body > high


def _independent_gap(
    history: list[dict[str, Any]], index: int, body: float, low: float, high: float
) -> float:
    del body
    current = history[index]
    body_low = min(
        math.log(current["adjusted_open"]), math.log(current["adjusted_close"])
    )
    body_high = max(
        math.log(current["adjusted_open"]), math.log(current["adjusted_close"])
    )
    if body_high < low:
        return low - body_high
    if body_low > high:
        return body_low - high
    return 0.0


def _compare_raw_row(expected: Mapping[str, Any], actual: Sequence[Any]) -> list[str]:
    differences: list[str] = []
    actual_map = dict(zip(RAW_TABLE_COLUMNS, actual, strict=True))
    for field in RAW_TABLE_COLUMNS:
        expected_value = expected[field]
        actual_value = actual_map[field]
        if field == "raw_value":
            if not _float_equal(expected_value, actual_value):
                differences.append(field)
        elif field == "reason_codes_json":
            try:
                actual_reason = json.dumps(
                    json.loads(str(actual_value)), separators=(",", ":")
                )
            except (TypeError, json.JSONDecodeError):
                actual_reason = None
            if actual_reason != expected_value:
                differences.append(field)
        elif field in {"trading_date", "input_window_start", "input_window_end"}:
            if _date_text(actual_value) != expected_value:
                differences.append(field)
        elif actual_value != expected_value:
            differences.append(field)
    return differences


def _float_equal(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    try:
        left = float(expected)
        right = float(actual)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(left) or not math.isfinite(right):
        return False
    difference = abs(left - right)
    relative = difference / max(abs(left), abs(right), 1.0)
    return difference <= 1e-12 and relative <= 1e-12


def _expected_profile_rows(connection: Any, filename: str) -> list[tuple[Any, ...]]:
    if filename == "exp_a01_metric_profile.csv":
        query = _metric_profile_query()
    elif filename == "exp_a01_validity_profile.csv":
        query = _validity_profile_query()
    elif filename == "exp_a01_year_coverage.csv":
        query = _year_profile_query()
    else:
        query = _security_profile_query()
    return connection.execute(query).fetchall()


def _compare_csv_file(
    path: Path,
    filename: str,
    expected_rows: Sequence[Sequence[Any]],
    errors: list[str],
    mismatches: dict[str, int],
) -> None:
    fields = CSV_FIELDS[filename]
    try:
        raw = path.read_bytes()
        text_errors = canonical_text_errors(raw)
        if text_errors:
            errors.append(f"csv_text_contract:{filename}:{text_errors}")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(fields):
                mismatches[_csv_mismatch_key(filename)] += 1
                errors.append(f"csv_header_mismatch:{filename}")
                return
            actual_rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        mismatches[_csv_mismatch_key(filename)] += 1
        errors.append(f"csv_read_failed:{filename}:{exc}")
        return
    if len(actual_rows) != len(expected_rows):
        mismatches[_csv_mismatch_key(filename)] += 1
        errors.append(
            f"csv_row_count_mismatch:{filename}:expected={len(expected_rows)}:actual={len(actual_rows)}"
        )
    for index, expected in enumerate(expected_rows[: len(actual_rows)]):
        actual = actual_rows[index]
        for field, expected_value in zip(fields, expected, strict=True):
            if not _csv_value_equal(expected_value, actual.get(field, "")):
                mismatches[_csv_mismatch_key(filename)] += 1
                if len(errors) < 50:
                    errors.append(f"csv_value_mismatch:{filename}:{index}:{field}")


def _csv_mismatch_key(filename: str) -> str:
    return {
        "exp_a01_metric_profile.csv": "metric_profile_mismatch",
        "exp_a01_validity_profile.csv": "validity_profile_mismatch",
        "exp_a01_year_coverage.csv": "year_coverage_mismatch",
        "exp_a01_security_coverage.csv": "security_coverage_mismatch",
    }[filename]


def _csv_value_equal(expected: Any, actual: str) -> bool:
    if expected is None:
        return actual == ""
    if isinstance(expected, date | datetime):
        return _date_text(expected) == actual
    if isinstance(expected, bool):
        return str(expected) == actual
    if isinstance(expected, int) and not isinstance(expected, bool):
        try:
            return int(actual) == expected
        except ValueError:
            return False
    if isinstance(expected, float):
        try:
            return _float_equal(expected, float(actual))
        except ValueError:
            return False
    return str(expected) == actual


def _validate_output_artifact_hashes(
    root: Path,
    formal_manifest: Mapping[str, Any],
    errors: list[str],
    mismatches: dict[str, int],
) -> None:
    artifacts = formal_manifest.get("output_artifacts")
    expected = {
        "exp_a01_raw_metrics.duckdb",
        "exp_a01_metric_profile.csv",
        "exp_a01_validity_profile.csv",
        "exp_a01_year_coverage.csv",
        "exp_a01_security_coverage.csv",
        "exp_a01_result_analysis.md",
    }
    if not isinstance(artifacts, Mapping) or set(artifacts) != expected:
        mismatches["artifact_hash_mismatch"] += 1
        errors.append("formal_manifest_output_artifact_set_mismatch")
        return
    for filename in sorted(expected):
        path = root / filename
        declaration = artifacts[filename]
        if not path.is_file() or declaration.get("sha256") != sha256_file(path):
            mismatches["artifact_hash_mismatch"] += 1
            errors.append(f"artifact_hash_mismatch:{filename}")


def _metric_profile_query() -> str:
    order = _indicator_order_sql("indicator_id")
    return f"""
WITH years AS (
  SELECT indicator_id, YEAR(trading_date) AS calendar_year,
         COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count
  FROM exp_a01_raw_metrics GROUP BY indicator_id, calendar_year
), securities AS (
  SELECT indicator_id, security_id,
         COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count
  FROM exp_a01_raw_metrics GROUP BY indicator_id, security_id
), base AS (
  SELECT indicator_id,
         CASE indicator_id WHEN '{A1_ID}' THEN 60 ELSE 79 END AS required_observation_count,
         COUNT(*) AS total_row_count,
         COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count,
         COUNT(*) FILTER (WHERE validity_status='unknown') AS unknown_count,
         COUNT(*) FILTER (WHERE validity_status='blocked') AS blocked_count,
         COUNT(*) FILTER (WHERE validity_status='diagnostic_required') AS diagnostic_required_count,
         COUNT(*) FILTER (WHERE validity_status='valid')::DOUBLE / NULLIF(COUNT(*),0) AS valid_rate,
         COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value=0) AS zero_count,
         COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value=0)::DOUBLE / NULLIF(COUNT(*) FILTER (WHERE validity_status='valid'),0) AS zero_rate_among_valid,
         COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value>0) AS positive_count,
         COUNT(DISTINCT raw_value) FILTER (WHERE validity_status='valid') AS unique_value_count,
         MIN(raw_value) FILTER (WHERE validity_status='valid') AS min_value,
         AVG(raw_value) FILTER (WHERE validity_status='valid') AS mean_value,
         STDDEV_POP(raw_value) FILTER (WHERE validity_status='valid') AS stddev_pop_value,
         QUANTILE_CONT(raw_value,0.01) FILTER (WHERE validity_status='valid') AS q01_value,
         QUANTILE_CONT(raw_value,0.05) FILTER (WHERE validity_status='valid') AS q05_value,
         QUANTILE_CONT(raw_value,0.25) FILTER (WHERE validity_status='valid') AS q25_value,
         QUANTILE_CONT(raw_value,0.50) FILTER (WHERE validity_status='valid') AS median_value,
         QUANTILE_CONT(raw_value,0.75) FILTER (WHERE validity_status='valid') AS q75_value,
         QUANTILE_CONT(raw_value,0.95) FILTER (WHERE validity_status='valid') AS q95_value,
         QUANTILE_CONT(raw_value,0.99) FILTER (WHERE validity_status='valid') AS q99_value,
         MAX(raw_value) FILTER (WHERE validity_status='valid') AS max_value,
         MIN(trading_date) FILTER (WHERE validity_status='valid') AS first_valid_date,
         MAX(trading_date) FILTER (WHERE validity_status='valid') AS last_valid_date,
         COUNT(DISTINCT security_id) AS unique_security_count,
         COUNT(DISTINCT security_id) FILTER (WHERE validity_status='valid') AS valid_security_count
  FROM exp_a01_raw_metrics GROUP BY indicator_id
), ys AS (
  SELECT y.indicator_id, COUNT(*) FILTER (WHERE y.valid_count>0) AS nonzero_year_count,
         MAX(y.valid_count::DOUBLE / NULLIF(b.valid_count,0)) AS max_year_valid_share
  FROM years y JOIN base b USING (indicator_id) GROUP BY y.indicator_id
), ss AS (
  SELECT s.indicator_id, MAX(s.valid_count::DOUBLE / NULLIF(b.valid_count,0)) AS max_security_valid_share
  FROM securities s JOIN base b USING (indicator_id) GROUP BY s.indicator_id
)
SELECT b.indicator_id,b.required_observation_count,b.total_row_count,b.valid_count,
 b.unknown_count,b.blocked_count,b.diagnostic_required_count,b.valid_rate,b.zero_count,
 b.zero_rate_among_valid,b.positive_count,b.unique_value_count,b.min_value,b.mean_value,
 b.stddev_pop_value,b.q01_value,b.q05_value,b.q25_value,b.median_value,b.q75_value,
 b.q95_value,b.q99_value,b.max_value,b.first_valid_date,b.last_valid_date,
 b.unique_security_count,b.valid_security_count,ys.nonzero_year_count,ys.max_year_valid_share,
 ss.max_security_valid_share
FROM base b JOIN ys USING(indicator_id) JOIN ss USING(indicator_id)
ORDER BY {order}
"""


def _validity_profile_query() -> str:
    order = _indicator_order_sql("indicator_id")
    return f"""
WITH totals AS (SELECT indicator_id, COUNT(*) AS denominator_count FROM exp_a01_raw_metrics GROUP BY indicator_id), rows AS (
 SELECT r.indicator_id,'validity_status' AS profile_dimension,r.validity_status AS profile_value,COUNT(*) AS row_count,t.denominator_count
 FROM exp_a01_raw_metrics r JOIN totals t USING(indicator_id) GROUP BY r.indicator_id,r.validity_status,t.denominator_count
 UNION ALL
 SELECT r.indicator_id,'reason_code',json_extract_string(j.value,'$'),COUNT(*),t.denominator_count
 FROM exp_a01_raw_metrics r JOIN totals t USING(indicator_id), LATERAL json_each(r.reason_codes_json) j
 GROUP BY r.indicator_id,json_extract_string(j.value,'$'),t.denominator_count
 UNION ALL
 SELECT r.indicator_id,'current_expected_observation_status',r.expected_observation_status,COUNT(*),t.denominator_count
 FROM exp_a01_raw_metrics r JOIN totals t USING(indicator_id) GROUP BY r.indicator_id,r.expected_observation_status,t.denominator_count
)
SELECT indicator_id,profile_dimension,profile_value,row_count,denominator_count,row_count::DOUBLE/NULLIF(denominator_count,0)
FROM rows ORDER BY {order},profile_dimension,profile_value
"""


def _year_profile_query() -> str:
    return f"""
SELECT YEAR(trading_date) AS calendar_year,indicator_id,COUNT(*) AS row_count,
 COUNT(*) FILTER(WHERE validity_status='valid') AS valid_count,
 COUNT(*) FILTER(WHERE validity_status='valid')::DOUBLE/NULLIF(COUNT(*),0) AS valid_rate,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value=0) AS zero_count,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value=0)::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE validity_status='valid'),0) AS zero_rate_among_valid,
 MIN(raw_value) FILTER(WHERE validity_status='valid'),QUANTILE_CONT(raw_value,0.05) FILTER(WHERE validity_status='valid'),
 QUANTILE_CONT(raw_value,0.50) FILTER(WHERE validity_status='valid'),QUANTILE_CONT(raw_value,0.95) FILTER(WHERE validity_status='valid'),
 MAX(raw_value) FILTER(WHERE validity_status='valid'),COUNT(DISTINCT security_id),COUNT(DISTINCT security_id) FILTER(WHERE validity_status='valid')
FROM exp_a01_raw_metrics GROUP BY calendar_year,indicator_id
ORDER BY calendar_year,CASE indicator_id WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 ELSE 2 END
"""


def _security_profile_query() -> str:
    return f"""
SELECT security_id,indicator_id,COUNT(*) AS row_count,COUNT(*) FILTER(WHERE validity_status='valid') AS valid_count,
 COUNT(*) FILTER(WHERE validity_status='valid')::DOUBLE/NULLIF(COUNT(*),0) AS valid_rate,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value=0) AS zero_count,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value=0)::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE validity_status='valid'),0) AS zero_rate_among_valid,
 MIN(trading_date),MAX(trading_date),MIN(trading_date) FILTER(WHERE validity_status='valid'),MAX(trading_date) FILTER(WHERE validity_status='valid'),
 MIN(raw_value) FILTER(WHERE validity_status='valid'),QUANTILE_CONT(raw_value,0.50) FILTER(WHERE validity_status='valid'),MAX(raw_value) FILTER(WHERE validity_status='valid')
FROM exp_a01_raw_metrics GROUP BY security_id,indicator_id
ORDER BY security_id,CASE indicator_id WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 ELSE 2 END
"""


def _indicator_order_sql(column: str) -> str:
    return f"CASE {column} WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 WHEN '{A2B_ID}' THEN 2 ELSE 99 END,{column}"


def _read_run_id(root: Path) -> str | None:
    manifest = root / "exp_a01_manifest.json"
    if not manifest.is_file():
        return None
    try:
        return load_json(manifest).get("run_id")
    except Exception:  # noqa: BLE001
        return None


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_text(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _ordered_reasons(reasons: Iterable[str]) -> list[str]:
    unique = {str(reason) for reason in reasons if str(reason)}
    order = {reason: index for index, reason in enumerate(REASON_CODES)}
    return sorted(unique, key=lambda reason: (order.get(reason, len(order)), reason))


def _status_for_reasons(reasons: Sequence[str]) -> str:
    if any(reason in _SEVERE_REASONS for reason in reasons):
        return "blocked"
    if "reopen_after_suspension" in reasons:
        return "diagnostic_required"
    return "unknown"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
