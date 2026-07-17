"""Independent validation helpers for EXP-A01 configuration and raw metrics."""

# SQL templates intentionally preserve readable independent expressions.
# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

TASK_ID = "EXP-A01"
ROOT = Path(__file__).resolve().parents[2]
A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
INDICATOR_IDS = (A1_ID, A2_ID, A2B_ID)
A1_REQUIRED_OBSERVATIONS = 60
A2_REQUIRED_OBSERVATIONS = 79
METRIC_ENGINE_VERSION = "exp_a01_price_ma_attachment.v1"
VALIDATION_STRATEGY = "r0_t10_full_invariants_plus_stratified_oracle_v1"
ORACLE_SAMPLE_VERSION = "EXP_A01_STRATIFIED_ORACLE_V1"
ORACLE_SAMPLE_TARGET_LIMIT = 10000
SMALL_INPUT_FULL_ORACLE_LIMIT = 100000
SAMPLED_NUMERIC_TOLERANCES = {
    A1_ID: {"absolute": 1e-12, "relative": 1e-9},
    A2_ID: {"absolute": 1e-12, "relative": 1e-9},
    A2B_ID: {"absolute": 1e-12, "relative": 1e-9},
}
FLOAT64_EPSILON = 2.220446049250313e-16
BOUNDARY_ULPS = 8
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
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
QUALIFIED_COLUMN_PATTERN = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*$"
)
EXPECTED_INDEX_STATUSES = {"present", "listing_pause", "missing", "unresolved"}
AUTHORIZED_MANIFEST_SCHEMA = (
    ROOT / "schemas" / "sidecar" / "exp_a01_authorized_input_manifest.schema.json"
)
CONFIG_SCHEMA = (
    ROOT / "schemas" / "sidecar" / "exp_a01_price_ma_attachment_candidates.schema.json"
)
FORMAL_SOURCE_PATHS = (
    "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json",
    "schemas/sidecar/exp_a01_price_ma_attachment_candidates.schema.json",
    "schemas/sidecar/exp_a01_authorized_input_manifest.schema.json",
    "src/sidecar/exp_a01_price_ma_attachment.py",
    "src/sidecar/exp_a01_price_ma_attachment_formal.py",
    "src/sidecar/exp_a01_price_ma_attachment_validator.py",
    "scripts/sidecar/run_exp_a01_price_ma_attachment.py",
    "scripts/sidecar/validate_exp_a01_price_ma_attachment.py",
)
EXPECTED_ARTIFACTS = (
    "d3_t07_candidate_daily_observation",
    "d3_t07_handoff_report",
    "d3_t07_quality_report",
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
        "implementation_review_status": "needs_revision",
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
            "listed_open_resolved_daily",
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

    governance = config.get("input_governance")
    if not isinstance(governance, Mapping):
        errors.append("config_input_governance_missing")
    else:
        if governance.get("d3_t08_required") is not False:
            errors.append("config_d3_t08_required_mismatch")
        if governance.get("d3_t08_policy") != "not_required_for_EXP-A01":
            errors.append("config_d3_t08_policy_mismatch")
        if not str(governance.get("rationale", "")).strip():
            errors.append("config_input_governance_rationale_missing")

    execution_governance = config.get("execution_profile_governance")
    if not isinstance(execution_governance, Mapping):
        errors.append("config_execution_profile_governance_missing")
    else:
        for key, expected in {
            "owner_override": True,
            "authorization_continuity": "preserved",
            "configuration_review_required": False,
            "implementation_review_required": False,
            "human_rereview_required": False,
            "authorization_roll_forward": "automatic_after_exact_head_quality_success",
            "scientific_contract_unchanged": True,
        }.items():
            if execution_governance.get(key) != expected:
                errors.append(f"config_execution_governance_{key}_mismatch")

    for gate_name in ("d3_t07_evidence_gate", "dense_window_contract"):
        if not isinstance(config.get(gate_name), Mapping):
            errors.append(f"config_{gate_name}_missing")
    validation_contract = config.get("validation_contract")
    if not isinstance(validation_contract, Mapping):
        errors.append("config_validation_contract_missing")
    else:
        expected_validation = {
            "strategy": VALIDATION_STRATEGY,
            "full_independent_recompute_required": False,
            "full_persisted_invariant_scan_required": True,
            "small_input_full_oracle_max_expected_observations": SMALL_INPUT_FULL_ORACLE_LIMIT,
            "oracle_sample_version": ORACLE_SAMPLE_VERSION,
            "oracle_sample_target_limit": ORACLE_SAMPLE_TARGET_LIMIT,
            "per_security_anchors": [
                "first_observation",
                "last_observation",
                "first_a1_valid",
                "first_a2_valid",
                "deterministic_valid",
                "deterministic_nonvalid",
            ],
            "per_indicator_validity_status_limit": 20,
            "per_indicator_reason_code_limit": 10,
            "per_indicator_year_valid_limit": 5,
            "per_indicator_extreme_tail_limit": 20,
        }
        for key, expected in expected_validation.items():
            if validation_contract.get(key) != expected:
                errors.append(f"config_validation_contract_{key}_mismatch")
        tolerances = validation_contract.get("sample_numeric_tolerances")
        if tolerances != SAMPLED_NUMERIC_TOLERANCES:
            errors.append(
                "config_validation_contract_sample_numeric_tolerances_mismatch"
            )
        if validation_contract.get("boundary_policy") != {
            "name": "scale_aware_8_ulp",
            "float64_epsilon": FLOAT64_EPSILON,
            "boundary_ulps": BOUNDARY_ULPS,
            "a2_a2b_shared": True,
            "reason": "The observed production/oracle disagreement is one floating-point ULP. Eight ULPs provide a narrow execution-order allowance while remaining many orders of magnitude below any economically or statistically meaningful A2/A2b distance.",
        }:
            errors.append("config_validation_contract_boundary_policy_mismatch")
    output_contract = config.get("output_contract")
    if not isinstance(output_contract, Mapping):
        errors.append("config_output_contract_missing")
    else:
        if output_contract.get("formal_execution_implemented") is not True:
            errors.append("config_output_formal_execution_missing")
        if output_contract.get("no_formal_output_in_implementation") is not False:
            errors.append("config_output_formal_guard_mismatch")
        if output_contract.get("parallel_mode") != "single_process_duckdb_parallel":
            errors.append("config_output_parallel_mode_mismatch")
        if output_contract.get("worker_count") != 1:
            errors.append("config_output_worker_count_mismatch")
        if output_contract.get("duckdb_threads") != 12:
            errors.append("config_output_duckdb_threads_mismatch")
        if output_contract.get("memory_limit") != "12GB":
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
    config_path: str | Path,
    input_manifest_path: str | Path | None = None,
    input_root: str | Path | None = None,
    reviewed_implementation_sha: str | None = None,
    schema_path: str | Path | None = None,
    require_final_manifest: bool = True,
    allow_failed_package_files: bool = False,
) -> dict[str, Any]:
    """Replay EXP-A01 lineage from disk, then independently read back outputs.

    The runner is intentionally not a source of truth for this entrypoint.  All
    input declarations, evidence payloads, dense-index counts, and reviewed
    source bindings are re-derived from the paths supplied to this function.
    """

    root = Path(output_dir).resolve()
    formal_manifest = _read_formal_output_manifest(root)
    errors = list(formal_manifest.pop("_errors", []))
    reviewed_sha = str(
        reviewed_implementation_sha
        or formal_manifest.get("reviewed_implementation_sha")
        or formal_manifest.get("implementation_sha")
        or ""
    )
    manifest_value = input_manifest_path
    if manifest_value is None:
        manifest_value = formal_manifest.get("input_manifest_path")
    manifest_path = (
        Path(str(manifest_value)).resolve()
        if manifest_value not in (None, "")
        else None
    )
    lineage = _derive_independent_lineage(
        config_path=Path(config_path).resolve(),
        schema_path=Path(schema_path).resolve() if schema_path else CONFIG_SCHEMA,
        input_manifest_path=manifest_path,
        input_root=Path(input_root).resolve() if input_root else None,
        formal_manifest=formal_manifest,
        reviewed_implementation_sha=reviewed_sha,
    )
    errors.extend(lineage["errors"])

    has_inputs = set(lineage["input_paths"]) == set(EXPECTED_ARTIFACTS) and set(
        lineage["input_metadata"]
    ) == set(EXPECTED_ARTIFACTS)
    if has_inputs:
        persisted = _validate_persisted_formal_outputs(
            root,
            config=lineage["config"],
            input_manifest=lineage["input_manifest"],
            input_manifest_path=lineage["input_manifest_path"],
            input_paths=lineage["input_paths"],
            input_metadata=lineage["input_metadata"],
            expected_index_row_count=lineage["expected_index_row_count"],
            reviewed_implementation_sha=reviewed_sha,
            require_final_manifest=require_final_manifest,
            allow_failed_package_files=allow_failed_package_files,
        )
    else:
        persisted = _empty_validation_result(
            root,
            reviewed_implementation_sha=reviewed_sha,
            input_manifest=lineage["input_manifest"],
            input_manifest_path=lineage["input_manifest_path"],
            formal_manifest=formal_manifest,
            require_final_manifest=require_final_manifest,
        )

    errors.extend(persisted.get("errors", []))
    mismatch_counts = {
        str(key): int(value)
        for key, value in persisted.get("mismatch_counts", {}).items()
    }
    mismatch_counts["lineage_mismatch"] = len(lineage["errors"])
    unique_errors = list(dict.fromkeys(errors))
    persisted["errors"] = unique_errors
    persisted["mismatch_counts"] = mismatch_counts
    persisted["status"] = "passed" if not unique_errors else "failed"
    persisted["valid"] = not unique_errors and all(
        value == 0 for value in mismatch_counts.values()
    )
    persisted["reviewed_implementation_sha"] = reviewed_sha
    persisted["lineage_checks"] = lineage["checks"]
    persisted["lineage_replayed_from_disk"] = True
    return persisted


def _validate_persisted_formal_outputs(
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
    allow_failed_package_files: bool = False,
) -> dict[str, Any]:
    """Validate persisted raw rows and compact profiles after lineage is derived."""

    root = Path(output_dir)
    errors: list[str] = []
    mismatch_counts = {
        "raw_table_schema_mismatch": 0,
        "raw_row_count_mismatch": 0,
        "raw_expected_key_mismatch": 0,
        "indicator_set_mismatch": 0,
        "duplicate_result_key": 0,
        "static_field_mismatch": 0,
        "validity_domain_mismatch": 0,
        "reason_code_domain_mismatch": 0,
        "window_invariant_mismatch": 0,
        "a2_a2b_pair_mismatch": 0,
        "full_invariant_mismatch": 0,
        "oracle_sample_mismatch": 0,
        "metric_profile_mismatch": 0,
        "validity_profile_mismatch": 0,
        "year_coverage_mismatch": 0,
        "security_coverage_mismatch": 0,
        "artifact_hash_mismatch": 0,
        "input_hash_changed": 0,
        "analysis_section_mismatch": 0,
        "prohibited_output_mismatch": 0,
    }
    validation_details: dict[str, Any] = {
        "validation_strategy": VALIDATION_STRATEGY,
        "full_independent_recompute_performed": False,
        "full_persisted_invariant_scan_performed": False,
        "oracle_mode": None,
        "oracle_sample_version": ORACLE_SAMPLE_VERSION,
        "oracle_target_observation_count": 0,
        "oracle_sample_target_fingerprint": None,
        "oracle_compared_raw_row_count": 0,
        "oracle_sample_security_count": 0,
        "oracle_sample_indicator_ids": [],
        "oracle_sample_validity_statuses": [],
        "oracle_sample_reason_codes": [],
        "oracle_sample_years": [],
        "oracle_mismatch_count": 0,
        "oracle_max_absolute_difference_by_indicator": {},
        "oracle_max_relative_difference_by_indicator": {},
        "oracle_numeric_tolerances": SAMPLED_NUMERIC_TOLERANCES,
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
    elif allow_failed_package_files:
        # A failed package preserves each diagnostic artifact only when the
        # runner reached the stage that produced it.  The failure summary is
        # the sole required marker; this mode is read-only diagnostic output
        # and cannot approve old raw metrics after the boundary policy change.
        expected_files.add("failure_summary.json")
        optional_failed_files = {
            "exp_a01_validator_result.json",
            "exp_a01_anomaly_scan.json",
            "exp_a01_result_analysis.md",
        }
        unexpected_optional = optional_failed_files & actual_files
        expected_files.update(unexpected_optional)
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
                    mismatch_counts["full_invariant_mismatch"] += 1
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
                _validate_full_persisted_invariants(
                    connection,
                    expected_index_path=input_paths["expected_price_observation_index"],
                    expected_index_table=config["input_contract"]["artifacts"][
                        "expected_price_observation_index"
                    ]["table"],
                    expected_index_row_count=expected_index_row_count,
                    run_id=str(formal_manifest.get("run_id", "")),
                    config=config,
                    errors=errors,
                    mismatch_counts=mismatch_counts,
                )
                validation_details["full_persisted_invariant_scan_performed"] = True
                validation_details.update(
                    _validate_stratified_independent_oracle(
                        connection,
                        candidate_path=input_paths[
                            "d3_t07_candidate_daily_observation"
                        ],
                        index_path=input_paths["expected_price_observation_index"],
                        expected_index_table=config["input_contract"]["artifacts"][
                            "expected_price_observation_index"
                        ]["table"],
                        expected_index_row_count=expected_index_row_count,
                        run_id=str(formal_manifest.get("run_id", "")),
                        config=config,
                        errors=errors,
                        mismatch_counts=mismatch_counts,
                    )
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
                errors.append(f"full_invariant_validation_exception:{exc}")
                mismatch_counts["full_invariant_mismatch"] += 1
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
                "Input governance override",
                "Dense expected-index reconciliation",
                "Fixed candidate definitions",
                "Raw table cardinality",
                "Metric domains and distributions",
                "Validity status profile",
                "Reason-code profile",
                "Year coverage",
                "Security coverage",
                "Full invariant validation and stratified independent oracle",
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
    result.update(validation_details)
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


def _empty_validation_result(
    root: Path,
    *,
    reviewed_implementation_sha: str,
    input_manifest: Mapping[str, Any],
    input_manifest_path: Path | None,
    formal_manifest: Mapping[str, Any],
    require_final_manifest: bool,
) -> dict[str, Any]:
    mismatch_counts = {
        "raw_table_schema_mismatch": 0,
        "raw_row_count_mismatch": 0,
        "raw_expected_key_mismatch": 0,
        "indicator_set_mismatch": 0,
        "duplicate_result_key": 0,
        "static_field_mismatch": 0,
        "validity_domain_mismatch": 0,
        "reason_code_domain_mismatch": 0,
        "window_invariant_mismatch": 0,
        "a2_a2b_pair_mismatch": 0,
        "full_invariant_mismatch": 0,
        "oracle_sample_mismatch": 0,
        "metric_profile_mismatch": 0,
        "validity_profile_mismatch": 0,
        "year_coverage_mismatch": 0,
        "security_coverage_mismatch": 0,
        "artifact_hash_mismatch": 0,
        "input_hash_changed": 0,
        "analysis_section_mismatch": 0,
        "prohibited_output_mismatch": 0,
    }
    expected = {
        "exp_a01_raw_metrics.duckdb",
        "exp_a01_metric_profile.csv",
        "exp_a01_validity_profile.csv",
        "exp_a01_year_coverage.csv",
        "exp_a01_security_coverage.csv",
        "exp_a01_manifest.json",
    }
    if require_final_manifest:
        expected.update(
            {
                "exp_a01_validator_result.json",
                "exp_a01_anomaly_scan.json",
                "exp_a01_result_analysis.md",
            }
        )
    return {
        "task_id": TASK_ID,
        "run_id": formal_manifest.get("run_id"),
        "status": "failed",
        "valid": False,
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "input_manifest_sha256": (
            sha256_file(input_manifest_path)
            if input_manifest_path is not None and input_manifest_path.is_file()
            else None
        ),
        "input_manifest_path": str(input_manifest_path or ""),
        "checked_files": sorted(expected),
        "checked_tables": ["exp_a01_raw_metrics"],
        "comparison_counts": {"raw_rows_expected": 0},
        "mismatch_counts": mismatch_counts,
        "artifact_hash_checks": {},
        "input_hash_after_run": {},
        "errors": [],
        "warnings": [],
        "validation_strategy": VALIDATION_STRATEGY,
        "full_independent_recompute_performed": False,
        "full_persisted_invariant_scan_performed": False,
        "oracle_mode": None,
        "oracle_sample_version": ORACLE_SAMPLE_VERSION,
        "oracle_target_observation_count": 0,
        "oracle_sample_target_fingerprint": None,
        "oracle_compared_raw_row_count": 0,
        "oracle_sample_security_count": 0,
        "oracle_sample_indicator_ids": [],
        "oracle_sample_validity_statuses": [],
        "oracle_sample_reason_codes": [],
        "oracle_sample_years": [],
        "oracle_mismatch_count": 0,
        "oracle_max_absolute_difference_by_indicator": {},
        "oracle_max_relative_difference_by_indicator": {},
        "oracle_numeric_tolerances": SAMPLED_NUMERIC_TOLERANCES,
    }


def _read_formal_output_manifest(root: Path) -> dict[str, Any]:
    path = root / "exp_a01_manifest.json"
    if not path.is_file():
        return {"_errors": [f"formal_manifest_missing:{path}"]}
    try:
        raw = path.read_bytes()
        errors = canonical_text_errors(raw)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"_errors": [f"formal_manifest_invalid:{exc}"]}
    if not isinstance(payload, dict):
        return {"_errors": ["formal_manifest_root_not_object"]}
    return {
        **payload,
        "_errors": [f"formal_manifest_text_contract:{errors}"] if errors else [],
    }


def _derive_independent_lineage(
    *,
    config_path: Path,
    schema_path: Path,
    input_manifest_path: Path | None,
    input_root: Path | None,
    formal_manifest: Mapping[str, Any],
    reviewed_implementation_sha: str,
) -> dict[str, Any]:
    errors: list[str] = []
    checks: dict[str, Any] = {
        "config": "not_checked",
        "authorized_manifest_schema": "not_checked",
        "authorization": "not_checked",
        "cross_artifact_bindings": "not_checked",
        "input_artifact_bindings": "not_checked",
        "d3_t07_evidence": "not_checked",
        "dense_expected_index": "not_checked",
        "formal_source_bindings": "not_checked",
        "final_manifest_bindings": "not_checked",
    }
    config: dict[str, Any] = {}
    input_manifest: dict[str, Any] = {}
    input_paths: dict[str, Path] = {}
    input_metadata: dict[str, dict[str, Any]] = {}
    if not config_path.is_file():
        errors.append(f"config_missing:{config_path}")
    else:
        config, config_errors = _read_json_object(config_path, "config")
        errors.extend(config_errors)
        errors.extend(validate_static_config(config))
        schema_errors = _validate_config_schema(config, schema_path)
        errors.extend(schema_errors)
        checks["config"] = (
            "passed" if not config_errors and not schema_errors else "failed"
        )

    manifest_path = input_manifest_path
    if manifest_path is None:
        value = formal_manifest.get("input_manifest_path")
        if isinstance(value, str) and value.strip():
            manifest_path = Path(value).resolve()
    if manifest_path is None:
        errors.append("authorized_input_manifest_path_missing")
    elif not manifest_path.is_file():
        errors.append(f"authorized_input_manifest_missing:{manifest_path}")
    else:
        input_manifest, manifest_errors = _read_json_object(
            manifest_path, "authorized input manifest"
        )
        errors.extend(manifest_errors)
        schema_errors = _validate_json_schema(
            input_manifest,
            AUTHORIZED_MANIFEST_SCHEMA,
            "authorized input manifest",
        )
        errors.extend(schema_errors)
        authorization_errors = _authorization_errors(input_manifest)
        errors.extend(authorization_errors)
        checks["authorized_manifest_schema"] = (
            "passed" if not schema_errors else "failed"
        )
        checks["authorization"] = "passed" if not authorization_errors else "failed"

    input_contract = config.get("input_contract", {})
    artifacts = (
        input_contract.get("artifacts", {})
        if isinstance(input_contract, Mapping)
        else {}
    )
    artifact_ids = (
        input_contract.get("manifest_artifact_names", [])
        if isinstance(input_contract, Mapping)
        else []
    )
    if (
        not isinstance(artifacts, Mapping)
        or not isinstance(artifact_ids, Sequence)
        or isinstance(artifact_ids, str | bytes)
    ):
        errors.append("config_input_artifacts_not_replayable")
        artifact_ids = []
    manifest_artifacts = input_manifest.get("input_artifacts")
    if not isinstance(manifest_artifacts, Mapping):
        errors.append("authorized_input_manifest_input_artifacts_missing")
        manifest_artifacts = {}
    if set(str(value) for value in artifact_ids) != set(EXPECTED_ARTIFACTS):
        errors.append("authorized_input_manifest_artifact_contract_mismatch")

    resolved_root = input_root
    if resolved_root is None:
        environment_root = os.environ.get("CONVERGENCE_RESEARCH_INPUT_ROOT")
        if environment_root:
            resolved_root = Path(environment_root).resolve()
    for artifact_id in EXPECTED_ARTIFACTS:
        artifact = artifacts.get(artifact_id)
        declaration = manifest_artifacts.get(artifact_id)
        if not isinstance(artifact, Mapping):
            errors.append(f"config_artifact_missing:{artifact_id}")
            continue
        if not isinstance(declaration, Mapping):
            errors.append(f"authorized_input_manifest_artifact_missing:{artifact_id}")
            continue
        try:
            path = _resolve_independent_input_path(
                manifest_path,
                resolved_root,
                declaration,
                artifact,
            )
            metadata = _inspect_independent_input_artifact(path, artifact, declaration)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"input_artifact_binding_failed:{artifact_id}:{exc}")
            continue
        metadata["path"] = str(path)
        input_paths[artifact_id] = path
        input_metadata[artifact_id] = metadata
    if len(input_metadata) == len(EXPECTED_ARTIFACTS):
        checks["input_artifact_bindings"] = "passed"
        try:
            _validate_cross_artifact_bindings_independent(
                input_manifest, manifest_artifacts
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cross_artifact_binding_failed:{exc}")
            checks["cross_artifact_bindings"] = "failed"
        else:
            checks["cross_artifact_bindings"] = "passed"
        try:
            _validate_d3_t07_evidence_independent(
                candidate_path=input_paths["d3_t07_candidate_daily_observation"],
                candidate_artifact=artifacts["d3_t07_candidate_daily_observation"],
                quality=input_metadata["d3_t07_quality_report"]["json"],
                handoff=input_metadata["d3_t07_handoff_report"]["json"],
                gate=config["d3_t07_evidence_gate"],
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"d3_t07_evidence_gate_failed:{exc}")
            checks["d3_t07_evidence"] = "failed"
        else:
            checks["d3_t07_evidence"] = "passed"
        try:
            dense_counts = _validate_expected_index_reconciliation_independent(
                candidate_path=input_paths["d3_t07_candidate_daily_observation"],
                candidate_artifact=artifacts["d3_t07_candidate_daily_observation"],
                index_path=input_paths["expected_price_observation_index"],
                index_artifact=artifacts["expected_price_observation_index"],
                dense_contract=config["dense_window_contract"],
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"dense_expected_index_reconciliation_failed:{exc}")
            checks["dense_expected_index"] = "failed"
            dense_counts = {}
        else:
            checks["dense_expected_index"] = "passed"
        expected_index_row_count = int(
            input_metadata.get("expected_price_observation_index", {}).get(
                "source_full_row_count", 0
            )
        )
        if (
            dense_counts
            and dense_counts.get("index_row_count") != expected_index_row_count
        ):
            errors.append(
                "dense_expected_index_row_count_mismatch:"
                f"metadata={expected_index_row_count}:reconciliation={dense_counts.get('index_row_count')}"
            )
    else:
        checks["input_artifact_bindings"] = "failed"
        dense_counts = {}
        expected_index_row_count = 0

    source_errors = _validate_formal_source_lineage(
        formal_manifest, reviewed_implementation_sha, errors
    )
    checks["formal_source_bindings"] = "passed" if not source_errors else "failed"
    errors.extend(source_errors)
    manifest_errors = _validate_final_manifest_input_lineage(
        formal_manifest,
        input_manifest=input_manifest,
        input_manifest_path=manifest_path,
        input_declarations=manifest_artifacts,
        input_metadata=input_metadata,
        dense_counts=dense_counts,
    )
    checks["final_manifest_bindings"] = "passed" if not manifest_errors else "failed"
    errors.extend(manifest_errors)
    return {
        "errors": list(dict.fromkeys(errors)),
        "checks": checks,
        "config": config,
        "input_manifest": input_manifest,
        "input_manifest_path": manifest_path
        or Path("__missing_authorized_input_manifest__"),
        "input_paths": input_paths,
        "input_metadata": input_metadata,
        "expected_index_row_count": expected_index_row_count,
    }


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        raw = path.read_bytes()
        text_errors = canonical_text_errors(raw)
        if text_errors:
            errors.append(f"{label}_text_contract:{text_errors}")
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, [f"{label}_invalid:{exc}"]
    if not isinstance(value, dict):
        errors.append(f"{label}_root_not_object")
        return {}, errors
    return value, errors


def _validate_config_schema(config: Mapping[str, Any], schema_path: Path) -> list[str]:
    return _validate_json_schema(config, schema_path, "config")


def _validate_json_schema(
    payload: Mapping[str, Any], schema_path: Path, label: str
) -> list[str]:
    errors: list[str] = []
    try:
        raw = schema_path.read_bytes()
        text_errors = canonical_text_errors(raw)
        if text_errors:
            errors.append(f"{label}_schema_text_contract:{text_errors}")
        schema = json.loads(raw.decode("utf-8"))
        from jsonschema import Draft202012Validator, FormatChecker

        Draft202012Validator.check_schema(schema)
        errors.extend(
            f"{label}_schema_validation:{error.message}"
            for error in Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(payload)
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label}_schema_invalid:{exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}_schema_validation_error:{exc}")
    return errors


def _authorization_errors(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {
        "manifest_type": "exp_a01_authorized_input_manifest",
        "schema_version": "exp_a01_authorized_input_manifest.v2",
        "task_id": TASK_ID,
        "authorized_for_task": TASK_ID,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            errors.append(f"authorized_manifest_{field}_mismatch")
    if manifest.get("authorized_research_candidate_input") is not True:
        errors.append("authorized_manifest_research_candidate_flag_mismatch")
    if manifest.get("formal_data_version") is not False:
        errors.append("authorized_manifest_formal_data_version_mismatch")
    authorization = manifest.get("authorization")
    if not isinstance(authorization, Mapping):
        errors.append("authorized_manifest_authorization_missing")
    else:
        if authorization.get("authorization_status") != "authorized_for_exp_a01":
            errors.append("authorized_manifest_authorization_status_mismatch")
        if not str(authorization.get("authorization_evidence", "")).strip():
            errors.append("authorized_manifest_authorization_evidence_missing")
    governance = manifest.get("input_governance")
    if not isinstance(governance, Mapping):
        errors.append("authorized_manifest_input_governance_missing")
    else:
        if governance.get("d3_t08_required") is not False:
            errors.append("authorized_manifest_d3_t08_required_mismatch")
        if governance.get("owner_override") is not True:
            errors.append("authorized_manifest_owner_override_missing")
        if not str(governance.get("override_reason", "")).strip():
            errors.append("authorized_manifest_override_reason_missing")
    artifact_ids = set(EXPECTED_ARTIFACTS)
    artifacts = manifest.get("input_artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != artifact_ids:
        errors.append("authorized_manifest_exact_four_artifacts_mismatch")
    bindings = manifest.get("cross_artifact_bindings")
    expected_binding_names = {
        "d3_t07_candidate_sha256",
        "d3_t07_quality_sha256",
        "d3_t07_handoff_sha256",
        "expected_index_sha256",
    }
    if not isinstance(bindings, Mapping) or set(bindings) != expected_binding_names:
        errors.append("authorized_manifest_cross_binding_set_mismatch")
    return errors


def _resolve_independent_input_path(
    manifest_path: Path | None,
    input_root: Path | None,
    declaration: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> Path:
    value = declaration.get("path")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("declaration path is missing")
    declared = Path(value)
    if declared.is_absolute():
        candidate = declared
    else:
        if manifest_path is None:
            raise RuntimeError("relative declaration has no manifest parent")
        candidate = manifest_path.parent / declared
    if not candidate.is_file():
        if (
            str(declaration.get("path_policy", "")) == "basename_local_only"
            and declared.name == value
            and input_root is not None
        ):
            candidate = input_root / declared.name
    if not candidate.is_file():
        raise RuntimeError(f"declared input is missing: {candidate}")
    expected_filename = str(artifact.get("filename", ""))
    if candidate.name != expected_filename:
        raise RuntimeError(
            f"filename mismatch: expected={expected_filename} actual={candidate.name}"
        )
    return candidate.resolve()


def _inspect_independent_input_artifact(
    path: Path,
    artifact: Mapping[str, Any],
    declaration: Mapping[str, Any],
) -> dict[str, Any]:
    artifact_id = str(artifact.get("artifact_id", ""))
    if declaration.get("artifact_id") != artifact_id:
        raise RuntimeError("artifact_id mismatch")
    for field in ("source_contract", "source_role", "formal_data_version", "sha256"):
        if field not in declaration:
            raise RuntimeError(f"declaration field missing: {field}")
    for field in ("source_contract", "source_role", "formal_data_version"):
        if declaration.get(field) != artifact.get(field):
            raise RuntimeError(f"{field} does not match config")
    expected_filename = str(artifact.get("filename", ""))
    if declaration.get("filename") != expected_filename:
        raise RuntimeError("filename declaration does not match config")
    declared_sha = str(declaration.get("sha256", ""))
    if not SHA_PATTERN.fullmatch(declared_sha):
        raise RuntimeError("sha256 declaration is invalid")
    actual_sha = sha256_file(path)
    if actual_sha != declared_sha:
        raise RuntimeError(
            f"sha256 mismatch: declared={declared_sha} actual={actual_sha}"
        )

    if artifact.get("artifact_kind") == "evidence_json":
        required_fields = [
            str(value) for value in artifact.get("required_json_fields", [])
        ]
        if list(declaration.get("required_json_fields", [])) != required_fields:
            raise RuntimeError("required JSON fields declaration does not match config")
        raw = path.read_bytes()
        text_errors = canonical_text_errors(raw)
        if text_errors:
            raise RuntimeError(f"evidence text contract: {text_errors}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("evidence JSON is invalid") from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("evidence JSON root is not an object")
        missing = sorted(set(required_fields) - set(payload))
        if missing:
            raise RuntimeError(f"evidence fields are missing: {missing}")
        return {
            "artifact_id": artifact_id,
            "path": str(path),
            "sha256": actual_sha,
            "json": dict(payload),
        }

    if artifact.get("artifact_kind") != "duckdb_table":
        raise RuntimeError(
            f"unsupported artifact kind: {artifact.get('artifact_kind')}"
        )
    table = str(artifact.get("table", ""))
    if not IDENTIFIER_PATTERN.fullmatch(table):
        raise RuntimeError(f"unsafe table identifier: {table}")
    if declaration.get("table") != table:
        raise RuntimeError("table declaration does not match config")
    required_columns = [str(value) for value in artifact.get("required_columns", [])]
    if list(declaration.get("required_columns", [])) != required_columns:
        raise RuntimeError("required columns declaration does not match config")
    if "row_count" not in declaration:
        raise RuntimeError("row_count declaration is missing")
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for input lineage validation") from exc
    connection = duckdb.connect(str(path), read_only=True)
    try:
        exists = int(
            connection.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
                [table],
            ).fetchone()[0]
        )
        if exists != 1:
            raise RuntimeError(f"table is missing: {table}")
        actual_columns = [
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        ]
        missing = sorted(set(required_columns) - set(actual_columns))
        if missing:
            raise RuntimeError(f"required columns are missing: {missing}")
        row_count = int(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
        if row_count != int(declaration["row_count"]):
            raise RuntimeError(
                f"row_count mismatch: declared={declaration['row_count']} actual={row_count}"
            )
    finally:
        connection.close()
    return {
        "artifact_id": artifact_id,
        "path": str(path),
        "sha256": actual_sha,
        "table": table,
        "actual_columns": actual_columns,
        "source_full_row_count": row_count,
        "required_columns": required_columns,
    }


def _validate_cross_artifact_bindings_independent(
    manifest: Mapping[str, Any], declarations: Mapping[str, Any]
) -> None:
    bindings = manifest.get("cross_artifact_bindings")
    if not isinstance(bindings, Mapping):
        raise RuntimeError("cross-artifact bindings are missing")
    expected = {
        "d3_t07_candidate_sha256": "d3_t07_candidate_daily_observation",
        "d3_t07_quality_sha256": "d3_t07_quality_report",
        "d3_t07_handoff_sha256": "d3_t07_handoff_report",
        "expected_index_sha256": "expected_price_observation_index",
    }
    for binding_name, artifact_id in expected.items():
        if bindings.get(binding_name) != declarations[artifact_id].get("sha256"):
            raise RuntimeError(f"binding mismatch: {binding_name}")


def _validate_d3_t07_evidence_independent(
    *,
    candidate_path: Path,
    candidate_artifact: Mapping[str, Any],
    quality: Mapping[str, Any],
    handoff: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> None:
    _require_equal_independent(quality, "task_id", "D3-T07", "D3-T07 quality")
    _require_equal_independent(quality, "source_task_id", "D2-T20", "D3-T07 quality")
    _require_equal_independent(handoff, "task_id", "D3-T07", "D3-T07 handoff")
    _require_equal_independent(handoff, "source_task_id", "D2-T20", "D3-T07 handoff")
    accepted = set(
        str(value) for value in gate.get("accepted_generation_decisions", [])
    )
    if handoff.get("d3_t07_generation_decision") not in accepted:
        raise RuntimeError("handoff generation decision is not accepted")
    if quality.get("candidate_generation_decision") not in accepted:
        raise RuntimeError("quality generation decision is not accepted")
    _require_true_independent(handoff, str(gate["generated_field"]), "D3-T07 handoff")
    _require_true_independent(
        quality, "candidate_observation_generated", "D3-T07 quality"
    )
    _require_false_independent(
        handoff, str(gate["formal_data_version_field"]), "D3-T07 handoff"
    )
    for field in gate.get("forbidden_true_fields", []):
        _require_false_independent(handoff, str(field), "D3-T07 handoff")
    for field in gate.get("quality_blockers", []):
        _require_zero_independent(quality, str(field), "D3-T07 quality")
    identity = gate.get("main_table_identity", {})
    _validate_candidate_main_table_independent(
        candidate_path, candidate_artifact, identity
    )


def _validate_candidate_main_table_independent(
    path: Path, artifact: Mapping[str, Any], identity: Mapping[str, Any]
) -> None:
    table = str(artifact.get("table", ""))
    if not IDENTIFIER_PATTERN.fullmatch(table):
        raise RuntimeError("unsafe candidate table identifier")
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for D3-T07 gate") from exc
    connection = duckdb.connect(str(path), read_only=True)
    try:
        source_task_id = str(identity.get("source_task_id", "")).replace("'", "''")
        generated_by_task = str(identity.get("generated_by_task", "")).replace(
            "'", "''"
        )
        predicates = {
            "source_task_id_invalid": (
                f"source_task_id IS NULL OR source_task_id != '{source_task_id}'"
            ),
            "generated_by_task_invalid": (
                "generated_by_task IS NULL OR "
                f"generated_by_task != '{generated_by_task}'"
            ),
            "row_provenance_missing": (
                "row_provenance IS NULL OR trim(row_provenance) = ''"
            ),
            "listing_pause_present": "is_listing_pause IS NOT FALSE",
            "effective_factor_invalid": (
                "effective_adj_factor IS NULL OR "
                "NOT isfinite(effective_adj_factor) OR effective_adj_factor <= 0"
            ),
        }
        failures = {
            key: _scalar_count(
                connection, f"SELECT COUNT(*) FROM {table} WHERE {predicate}"
            )
            for key, predicate in predicates.items()
        }
    finally:
        connection.close()
    if any(value > 0 for value in failures.values()):
        raise RuntimeError(f"main table gate failed: {failures}")


def _require_equal_independent(
    payload: Mapping[str, Any], field: str, expected: Any, label: str
) -> None:
    if payload.get(field) != expected:
        raise RuntimeError(
            f"{label} {field} mismatch: expected={expected!r} actual={payload.get(field)!r}"
        )


def _require_true_independent(
    payload: Mapping[str, Any], field: str, label: str
) -> None:
    if payload.get(field) is not True:
        raise RuntimeError(f"{label} {field} must be true")


def _require_false_independent(
    payload: Mapping[str, Any], field: str, label: str
) -> None:
    if payload.get(field) is not False:
        raise RuntimeError(f"{label} {field} must be false")


def _require_zero_independent(
    payload: Mapping[str, Any], field: str, label: str
) -> None:
    if field not in payload:
        raise RuntimeError(f"{label} blocker field is missing: {field}")
    try:
        value = int(payload[field])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} blocker is not numeric: {field}") from exc
    if value != 0:
        raise RuntimeError(f"{label} blocker is nonzero: {field}={value}")


def _scalar_count(connection: Any, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0] or 0)


def _canonical_sql_date_expression(column: str) -> str:
    if not QUALIFIED_COLUMN_PATTERN.fullmatch(column):
        raise ValueError(f"unsafe SQL date column: {column!r}")
    return (
        "CAST(COALESCE("
        f"try_strptime(CAST({column} AS VARCHAR), '%Y-%m-%d'), "
        f"try_strptime(CAST({column} AS VARCHAR), '%Y%m%d')"
        ") AS DATE)"
    )


def _validate_expected_index_reconciliation_independent(
    *,
    candidate_path: Path,
    candidate_artifact: Mapping[str, Any],
    index_path: Path,
    index_artifact: Mapping[str, Any],
    dense_contract: Mapping[str, Any],
) -> dict[str, int]:
    """Replay dense-index reconciliation without importing the formal runner."""

    candidate_table = str(candidate_artifact.get("table", ""))
    index_table = str(index_artifact.get("table", ""))
    for table in (candidate_table, index_table):
        if not IDENTIFIER_PATTERN.fullmatch(table):
            raise RuntimeError(f"unsafe table identifier: {table}")
    if (
        set(str(value) for value in dense_contract.get("statuses", []))
        != EXPECTED_INDEX_STATUSES
    ):
        raise RuntimeError("dense index status vocabulary mismatch")
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for dense index validation") from exc
    connection = duckdb.connect(":memory:")
    try:
        candidate_literal = str(candidate_path).replace("'", "''")
        index_literal = str(index_path).replace("'", "''")
        connection.execute(f"ATTACH '{candidate_literal}' AS candidate (READ_ONLY)")
        connection.execute(f"ATTACH '{index_literal}' AS expected (READ_ONLY)")
        schema_rows = connection.execute(
            f"PRAGMA table_info('expected.{index_table}')"
        ).fetchall()
        schema_types = {str(row[1]): str(row[2]).upper() for row in schema_rows}
        sequence_type = schema_types.get("observation_sequence", "")
        date_type = schema_types.get("trading_date", "")
        errors: dict[str, int] = {
            "index_sequence_type_invalid": int(
                not any(
                    token in sequence_type for token in ("INT", "DECIMAL", "HUGEINT")
                )
            ),
            "index_date_type_invalid": int(
                not any(
                    token in date_type
                    for token in ("DATE", "TIMESTAMP", "VARCHAR", "TEXT")
                )
            ),
        }
        candidate_date_expr = _canonical_sql_date_expression("m.trade_date")
        index_date_expr = _canonical_sql_date_expression("i.trading_date")
        errors["invalid_index_identity"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM expected.{index_table}
            WHERE security_id IS NULL OR trim(CAST(security_id AS VARCHAR)) = ''
               OR trading_date IS NULL OR observation_sequence IS NULL
            """,
        )
        errors["invalid_index_sequence_value"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM expected.{index_table}
            WHERE try_cast(observation_sequence AS DECIMAL(38, 10)) IS NULL
               OR try_cast(observation_sequence AS DECIMAL(38, 10)) < 0
               OR try_cast(observation_sequence AS DECIMAL(38, 10))
                    != floor(try_cast(observation_sequence AS DECIMAL(38, 10)))
            """,
        )
        errors["invalid_index_date"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM expected.{index_table} AS i
            WHERE {index_date_expr} IS NULL
            """,
        )
        errors["invalid_main_date"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM candidate.{candidate_table} AS m
            WHERE {candidate_date_expr} IS NULL
            """,
        )
        errors["duplicate_index_security_date"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM (
              SELECT security_id, canonical_date
              FROM (
                SELECT i.security_id, {index_date_expr} AS canonical_date
                FROM expected.{index_table} AS i
                WHERE {index_date_expr} IS NOT NULL
              ) canonical_index
              GROUP BY 1, 2 HAVING COUNT(*) > 1
            )
            """,
        )
        errors["duplicate_index_security_sequence"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM (
              SELECT security_id, observation_sequence
              FROM expected.{index_table}
              GROUP BY 1, 2 HAVING COUNT(*) > 1
            )
            """,
        )
        errors["invalid_index_status"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM expected.{index_table}
            WHERE expected_observation_status NOT IN (
                'present', 'listing_pause', 'missing', 'unresolved'
            ) OR expected_observation_status IS NULL
            """,
        )
        expected_source_contract = str(
            index_artifact.get("source_contract", "")
        ).replace("'", "''")
        errors["empty_index_source_contract"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM expected.{index_table}
            WHERE source_contract IS NULL OR trim(source_contract) = ''
               OR source_contract != '{expected_source_contract}'
            """,
        )
        errors["empty_index_source_ref"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM expected.{index_table}
            WHERE source_ref IS NULL OR trim(source_ref) = ''
            """,
        )
        errors["non_monotonic_index_sequence"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM (
              SELECT observation_sequence,
                     lag(observation_sequence) OVER (
                       PARTITION BY security_id ORDER BY observation_sequence
                     ) AS previous_sequence
              FROM (
                SELECT security_id,
                       try_cast(observation_sequence AS DECIMAL(38, 10))
                         AS observation_sequence
                FROM expected.{index_table}
              ) ordered_index
            )
            WHERE previous_sequence IS NOT NULL
              AND observation_sequence != previous_sequence + 1
            """,
        )
        errors["non_monotonic_index_date"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM (
              SELECT canonical_date,
                     lag(canonical_date) OVER (
                       PARTITION BY security_id ORDER BY observation_sequence
                     ) AS previous_date
              FROM (
                SELECT security_id, observation_sequence,
                       {index_date_expr} AS canonical_date
                FROM expected.{index_table} AS i
              ) ordered_index
            )
            WHERE previous_date IS NOT NULL AND canonical_date <= previous_date
            """,
        )
        errors["main_duplicate_security_date"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM (
              SELECT ts_code, canonical_date
              FROM (
                SELECT m.ts_code, {candidate_date_expr} AS canonical_date
                FROM candidate.{candidate_table} AS m
                WHERE {candidate_date_expr} IS NOT NULL
              ) canonical_candidate
              GROUP BY 1, 2 HAVING COUNT(*) > 1
            )
            """,
        )
        errors["main_invalid_identity"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM candidate.{candidate_table}
            WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR trade_date IS NULL
            """,
        )
        errors["main_listing_pause_row_present"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM candidate.{candidate_table}
            WHERE is_listing_pause IS NOT FALSE
            """,
        )
        errors["main_source_task_invalid"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM candidate.{candidate_table}
            WHERE source_task_id IS NULL OR source_task_id != 'D2-T20'
            """,
        )
        errors["main_generated_by_task_invalid"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM candidate.{candidate_table}
            WHERE generated_by_task IS NULL OR generated_by_task != 'D3-T07'
            """,
        )
        errors["main_row_provenance_missing"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM candidate.{candidate_table}
            WHERE row_provenance IS NULL OR trim(row_provenance) = ''
            """,
        )
        errors["main_effective_factor_invalid"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*) FROM candidate.{candidate_table}
            WHERE effective_adj_factor IS NULL
               OR NOT isfinite(effective_adj_factor)
               OR effective_adj_factor <= 0
            """,
        )
        errors["main_key_not_present_index"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*)
            FROM candidate.{candidate_table} m
            LEFT JOIN expected.{index_table} i
              ON i.security_id = m.ts_code
             AND {index_date_expr} = {candidate_date_expr}
             AND i.expected_observation_status = 'present'
            WHERE i.security_id IS NULL
            """,
        )
        errors["present_index_key_missing_main"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*)
            FROM expected.{index_table} i
            LEFT JOIN candidate.{candidate_table} m
              ON m.ts_code = i.security_id
             AND {candidate_date_expr} = {index_date_expr}
            WHERE i.expected_observation_status = 'present'
              AND m.ts_code IS NULL
            """,
        )
        errors["non_present_index_key_in_main"] = _scalar_count(
            connection,
            f"""
            SELECT COUNT(*)
            FROM expected.{index_table} i
            JOIN candidate.{candidate_table} m
              ON m.ts_code = i.security_id
             AND {candidate_date_expr} = {index_date_expr}
            WHERE i.expected_observation_status != 'present'
            """,
        )
        errors["index_row_count"] = _scalar_count(
            connection, f"SELECT COUNT(*) FROM expected.{index_table}"
        )
        errors["main_row_count"] = _scalar_count(
            connection, f"SELECT COUNT(*) FROM candidate.{candidate_table}"
        )
        if errors["index_row_count"] <= 0:
            errors["empty_index"] = 1
        failures = {
            key: value
            for key, value in errors.items()
            if value > 0 and key not in {"index_row_count", "main_row_count"}
        }
        if failures:
            raise RuntimeError(f"expected_index_reconcile_failed: {failures}")
        return errors
    finally:
        connection.close()


def _validate_formal_source_bindings(reviewed_sha: str) -> dict[str, Any]:
    """Read the reviewed Git commit and return its canonical source bindings."""

    if not COMMIT_SHA_PATTERN.fullmatch(reviewed_sha):
        raise RuntimeError("reviewed implementation SHA is not a 40-character SHA")
    bindings: dict[str, Any] = {}
    for relative in FORMAL_SOURCE_PATHS:
        try:
            blob_sha = subprocess.run(
                ["git", "rev-parse", f"{reviewed_sha}:{relative}"],
                cwd=str(ROOT),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            committed = subprocess.run(
                ["git", "show", f"{reviewed_sha}:{relative}"],
                cwd=str(ROOT),
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                f"reviewed source binding unavailable: {relative}"
            ) from exc
        if not COMMIT_SHA_PATTERN.fullmatch(blob_sha):
            raise RuntimeError(f"reviewed source blob SHA invalid: {relative}")
        if not isinstance(committed, bytes):
            raise RuntimeError(f"reviewed source bytes unavailable: {relative}")
        text_errors = canonical_text_errors(committed)
        if text_errors:
            raise RuntimeError(
                f"reviewed source text contract: {relative}:{text_errors}"
            )
        bindings[relative] = {
            "source_commit": reviewed_sha,
            "git_blob_sha": blob_sha,
            "committed_byte_sha256": hashlib.sha256(committed).hexdigest(),
            "normalized_text_sha256": hashlib.sha256(
                committed.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            ).hexdigest(),
            "encoding": "UTF-8",
            "line_ending": "LF",
            "BOM": False,
            "final_LF_count": len(committed) - len(committed.rstrip(b"\n")),
        }
    return bindings


def _validate_formal_source_lineage(
    formal_manifest: Mapping[str, Any], reviewed_sha: str, errors: list[str]
) -> list[str]:
    lineage_errors: list[str] = []
    try:
        expected = _validate_formal_source_bindings(reviewed_sha)
    except Exception as exc:  # noqa: BLE001
        lineage_errors.append(f"formal_source_binding_replay_failed:{exc}")
        return lineage_errors
    actual = formal_manifest.get("source_bindings")
    if not isinstance(actual, Mapping) or set(actual) != set(FORMAL_SOURCE_PATHS):
        lineage_errors.append("formal_manifest_source_binding_set_mismatch")
        return lineage_errors
    for relative in FORMAL_SOURCE_PATHS:
        if actual.get(relative) != expected[relative]:
            lineage_errors.append(f"formal_manifest_source_binding_mismatch:{relative}")
    config = formal_manifest.get("config")
    if isinstance(config, Mapping):
        expected_sha = expected[
            "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"
        ]["committed_byte_sha256"]
        if config.get("sha256") != expected_sha:
            lineage_errors.append("formal_manifest_config_source_sha_mismatch")
    else:
        lineage_errors.append("formal_manifest_config_binding_missing")
    return lineage_errors


def _validate_final_manifest_input_lineage(
    formal_manifest: Mapping[str, Any],
    *,
    input_manifest: Mapping[str, Any],
    input_manifest_path: Path | None,
    input_declarations: Mapping[str, Any],
    input_metadata: Mapping[str, Mapping[str, Any]],
    dense_counts: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if input_manifest_path is not None and input_manifest_path.is_file():
        expected_sha = sha256_file(input_manifest_path)
        if formal_manifest.get("input_manifest_sha256") != expected_sha:
            errors.append("formal_manifest_input_manifest_sha_mismatch")
        if str(formal_manifest.get("input_manifest_path", "")) != str(
            input_manifest_path
        ):
            errors.append("formal_manifest_input_manifest_path_mismatch")
    actual_declarations = formal_manifest.get("input_artifact_declarations")
    if not isinstance(actual_declarations, Mapping) or set(actual_declarations) != set(
        EXPECTED_ARTIFACTS
    ):
        errors.append("formal_manifest_input_declaration_set_mismatch")
    else:
        for artifact_id in EXPECTED_ARTIFACTS:
            expected = input_declarations.get(artifact_id)
            actual = actual_declarations.get(artifact_id)
            if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
                errors.append(
                    f"formal_manifest_input_declaration_missing:{artifact_id}"
                )
                continue
            for field in (
                "artifact_id",
                "filename",
                "sha256",
                "source_contract",
                "source_role",
                "formal_data_version",
            ):
                if actual.get(field) != expected.get(field):
                    errors.append(
                        f"formal_manifest_input_declaration_mismatch:{artifact_id}:{field}"
                    )
            manifest_artifacts_value = input_manifest.get("input_artifacts", {})
            artifact_declaration = (
                manifest_artifacts_value.get(artifact_id, {})
                if isinstance(manifest_artifacts_value, Mapping)
                else {}
            )
            artifact_kind = (
                artifact_declaration.get("artifact_kind")
                if isinstance(artifact_declaration, Mapping)
                else None
            )
            if artifact_kind == "duckdb_table":
                for field in ("table", "row_count", "required_columns"):
                    if actual.get(field) != expected.get(field):
                        errors.append(
                            f"formal_manifest_input_declaration_mismatch:{artifact_id}:{field}"
                        )
            else:
                if actual.get("required_json_fields") != expected.get(
                    "required_json_fields"
                ):
                    errors.append(
                        f"formal_manifest_input_declaration_mismatch:{artifact_id}:required_json_fields"
                    )
    actual_metadata = formal_manifest.get("input_artifact_actual_metadata")
    if not isinstance(actual_metadata, Mapping) or set(actual_metadata) != set(
        EXPECTED_ARTIFACTS
    ):
        errors.append("formal_manifest_input_metadata_set_mismatch")
    else:
        for artifact_id in EXPECTED_ARTIFACTS:
            expected = input_metadata.get(artifact_id, {})
            actual = actual_metadata.get(artifact_id)
            if not isinstance(actual, Mapping):
                errors.append(f"formal_manifest_input_metadata_missing:{artifact_id}")
                continue
            for field in ("path", "sha256"):
                if actual.get(field) != expected.get(field):
                    errors.append(
                        f"formal_manifest_input_metadata_mismatch:{artifact_id}:{field}"
                    )
            for field in ("table", "source_full_row_count", "actual_columns"):
                if field in expected and actual.get(field) != expected.get(field):
                    errors.append(
                        f"formal_manifest_input_metadata_mismatch:{artifact_id}:{field}"
                    )
    if dense_counts:
        actual_dense = formal_manifest.get("dense_reconciliation_counts")
        if not isinstance(actual_dense, Mapping):
            errors.append("formal_manifest_dense_reconciliation_missing")
        else:
            for key, expected in dense_counts.items():
                if actual_dense.get(key) != expected:
                    errors.append(
                        f"formal_manifest_dense_reconciliation_mismatch:{key}"
                    )
    return list(dict.fromkeys(errors))


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
            if int(mismatches.get("full_invariant_mismatch", 0)):
                blocking.append("full_invariant_mismatch")
            if int(mismatches.get("oracle_sample_mismatch", 0)):
                blocking.append("oracle_sample_mismatch")
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
    manifest_path = Path(input_manifest_path)
    return {
        "task_id": TASK_ID,
        "run_id": (formal_manifest or {}).get("run_id"),
        "status": "passed" if valid else "failed",
        "valid": valid,
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "input_manifest_sha256": (
            sha256_file(manifest_path) if manifest_path.is_file() else None
        ),
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
    for field, expected in {
        "parallel_mode": "single_process_duckdb_parallel",
        "worker_count": 1,
        "duckdb_threads": 12,
        "memory_limit": "12GB",
        "execution_profile_owner_override": True,
        "authorization_continuity": "preserved",
    }.items():
        if formal_manifest.get(field) != expected:
            errors.append(f"formal_manifest_{field}_mismatch")
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
        mismatches["full_invariant_mismatch"] = (
            mismatches.get("full_invariant_mismatch", 0) + 1
        )
        errors.append(f"raw_table_missing:{exc}")
        return
    columns = [str(row[1]) for row in rows]
    if columns != list(RAW_TABLE_COLUMNS):
        mismatches["raw_table_schema_mismatch"] += 1
        mismatches["full_invariant_mismatch"] = (
            mismatches.get("full_invariant_mismatch", 0) + 1
        )
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
            mismatches["full_invariant_mismatch"] = (
                mismatches.get("full_invariant_mismatch", 0) + 1
            )
            errors.append(f"raw_table_type_mismatch:{column}:{types[column]}")


def _validate_raw_domains(
    connection: Any, errors: list[str], mismatches: dict[str, int]
) -> None:
    checks = (
        (
            "validity_domain_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status IS NULL OR validity_status NOT IN ('valid','unknown','blocked','diagnostic_required')",
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
            "validity_domain_mismatch",
            f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id='{A2_ID}' AND validity_status='valid' AND abs(raw_value * 20.0 - round(raw_value * 20.0)) > {SAMPLED_NUMERIC_TOLERANCES[A2_ID]['absolute']}",
        ),
        (
            "reason_code_domain_mismatch",
            """
          SELECT COUNT(*) FROM exp_a01_raw_metrics r, LATERAL json_each(CASE WHEN json_valid(r.reason_codes_json) THEN r.reason_codes_json ELSE '[]' END) j
          WHERE json_valid(r.reason_codes_json)
            AND json_extract_string(j.value, '$') NOT IN
            ('valid_no_blocker','window_insufficient','missing_adjusted_open','missing_adjusted_close',
             'missing_required_history','nonpositive_adjusted_open','nonpositive_adjusted_close','nonpositive_MA',
             'adjustment_failure','suspension_in_required_window','listing_pause_in_required_window',
             'invalid_trading_status','reopen_after_suspension')
        """,
        ),
        (
            "reason_code_domain_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE reason_codes_json IS NULL OR NOT json_valid(reason_codes_json) OR (json_valid(reason_codes_json) AND json_array_length(reason_codes_json)=0)",
        ),
        (
            "reason_code_domain_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status='valid' AND reason_codes_json IS DISTINCT FROM '[\"valid_no_blocker\"]'",
        ),
        (
            "reason_code_domain_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status<>'valid' AND strpos(reason_codes_json, '\"valid_no_blocker\"') > 0",
        ),
    )
    for key, query in checks:
        count = int(connection.execute(query).fetchone()[0])
        if count:
            mismatches[key] += count
            errors.append(f"{key}:{count}")


def _sql_literal(value: str | Path) -> str:
    return str(value).replace("'", "''")


def _safe_identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value


def _attach_read_only(connection: Any, path: str | Path, alias: str) -> None:
    databases = {
        str(row[1]) for row in connection.execute("PRAGMA database_list").fetchall()
    }
    if alias not in databases:
        connection.execute(
            f"ATTACH '{_sql_literal(path)}' AS {_safe_identifier(alias)} (READ_ONLY)"
        )


def _add_invariant_count(
    connection: Any,
    query: str,
    name: str,
    errors: list[str],
    mismatches: dict[str, int],
) -> int:
    count = int(connection.execute(query).fetchone()[0] or 0)
    if count:
        mismatches[name] = mismatches.get(name, 0) + count
        mismatches["full_invariant_mismatch"] = (
            mismatches.get("full_invariant_mismatch", 0) + count
        )
        errors.append(f"{name}:{count}")
    return count


def _validate_full_persisted_invariants(
    connection: Any,
    *,
    expected_index_path: str | Path,
    expected_index_table: str,
    expected_index_row_count: int,
    run_id: str,
    config: Mapping[str, Any],
    errors: list[str],
    mismatch_counts: dict[str, int],
) -> None:
    """Run the full persisted-output scan using DuckDB set-based invariants."""

    table = _safe_identifier(expected_index_table)
    _attach_read_only(connection, expected_index_path, "expected_lineage")
    index_date = _canonical_sql_date_expression("i.trading_date")
    expected_table = f"expected_lineage.{table}"
    indicators_sql = ", ".join(f"'{indicator}'" for indicator in INDICATOR_IDS)
    raw_key_cte = """
      SELECT security_id, trading_date, observation_sequence,
             COUNT(*) AS row_count,
             COUNT(DISTINCT indicator_id) AS indicator_count
      FROM exp_a01_raw_metrics
      GROUP BY security_id, trading_date, observation_sequence
    """
    index_key_cte = f"""
      SELECT i.security_id, {index_date} AS trading_date,
             CAST(i.observation_sequence AS BIGINT) AS observation_sequence
      FROM {expected_table} i
    """
    _add_invariant_count(
        connection,
        f"""
        WITH raw_keys AS ({raw_key_cte}), index_keys AS ({index_key_cte})
        SELECT COUNT(*) FROM index_keys i
        LEFT JOIN raw_keys r USING (security_id, trading_date, observation_sequence)
        WHERE r.security_id IS NULL OR r.row_count <> 3 OR r.indicator_count <> 3
        """,
        "raw_expected_key_mismatch",
        errors,
        mismatch_counts,
    )
    _add_invariant_count(
        connection,
        f"""
        WITH index_keys AS ({index_key_cte})
        SELECT COUNT(*) FROM (
          SELECT DISTINCT r.security_id, r.trading_date, r.observation_sequence
          FROM exp_a01_raw_metrics r
          LEFT JOIN index_keys i USING (security_id, trading_date, observation_sequence)
          WHERE i.security_id IS NULL
        ) extra_keys
        """,
        "raw_expected_key_mismatch",
        errors,
        mismatch_counts,
    )
    _add_invariant_count(
        connection,
        f"""
        WITH index_keys AS ({index_key_cte})
        SELECT COUNT(*)
        FROM exp_a01_raw_metrics r
        LEFT JOIN {expected_table} i
          ON i.security_id = r.security_id
         AND {index_date} = r.trading_date
         AND CAST(i.observation_sequence AS BIGINT) = r.observation_sequence
        WHERE i.security_id IS NULL
           OR r.expected_observation_status IS DISTINCT FROM i.expected_observation_status
           OR r.source_ref IS DISTINCT FROM i.source_ref
        """,
        "raw_expected_key_mismatch",
        errors,
        mismatch_counts,
    )
    _add_invariant_count(
        connection,
        """
        SELECT COUNT(*) FROM (
          SELECT security_id, trading_date, observation_sequence, indicator_id
          FROM exp_a01_raw_metrics
          GROUP BY 1,2,3,4 HAVING COUNT(*) > 1
        ) duplicates
        """,
        "duplicate_result_key",
        errors,
        mismatch_counts,
    )
    _add_invariant_count(
        connection,
        f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE indicator_id NOT IN ({indicators_sql}) OR indicator_id IS NULL",
        "indicator_set_mismatch",
        errors,
        mismatch_counts,
    )
    static_queries = (
        (
            "static_field_mismatch",
            f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE run_id IS DISTINCT FROM '{_sql_literal(run_id)}'",
        ),
        (
            "static_field_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE metric_engine_version IS DISTINCT FROM 'exp_a01_price_ma_attachment.v1'",
        ),
        (
            "static_field_mismatch",
            f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE (indicator_id='{A1_ID}' AND raw_metric_name IS DISTINCT FROM 'LogBodyCenterToMACloudCenter_5_60') OR (indicator_id='{A2_ID}' AND raw_metric_name IS DISTINCT FROM 'BodyCenterOutsideMACloudRate20_5_60') OR (indicator_id='{A2B_ID}' AND raw_metric_name IS DISTINCT FROM 'BodyToMACloudGapMean20_5_60')",
        ),
        (
            "static_field_mismatch",
            f"SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE required_observation_count IS NULL OR (indicator_id='{A1_ID}' AND required_observation_count <> 60) OR (indicator_id IN ('{A2_ID}','{A2B_ID}') AND required_observation_count <> 79)",
        ),
        (
            "static_field_mismatch",
            "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE input_window_end IS DISTINCT FROM trading_date",
        ),
    )
    for name, query in static_queries:
        _add_invariant_count(connection, query, name, errors, mismatch_counts)

    _add_invariant_count(
        connection,
        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE actual_valid_observation_count IS NULL OR actual_valid_observation_count < 0 OR actual_valid_observation_count > required_observation_count",
        "window_invariant_mismatch",
        errors,
        mismatch_counts,
    )

    _validate_raw_domains(connection, errors, mismatch_counts)
    # _validate_raw_domains predates the aggregate counter; fold its direct
    # domain/reason counts into the full-invariant total for one clear gate.
    domain_names = {
        "validity_domain_mismatch",
        "reason_code_domain_mismatch",
    }
    mismatch_counts["full_invariant_mismatch"] += sum(
        mismatch_counts.get(name, 0) for name in domain_names
    )

    window_query = f"""
    WITH indexed AS (
      SELECT {index_date} AS trading_date,
             CAST(i.observation_sequence AS BIGINT) AS observation_sequence,
             i.security_id,
             COUNT(*) OVER p60 AS count60,
             COUNT(*) OVER p79 AS count79,
             FIRST_VALUE({index_date}) OVER p60 AS start60,
             FIRST_VALUE({index_date}) OVER p79 AS start79
      FROM {expected_table} i
      WINDOW
        p60 AS (PARTITION BY i.security_id ORDER BY CAST(i.observation_sequence AS BIGINT) ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
        p79 AS (PARTITION BY i.security_id ORDER BY CAST(i.observation_sequence AS BIGINT) ROWS BETWEEN 78 PRECEDING AND CURRENT ROW)
    )
    SELECT COUNT(*) FROM exp_a01_raw_metrics r
    JOIN indexed i USING (security_id, trading_date, observation_sequence)
    WHERE
      (r.indicator_id='{A1_ID}' AND ((r.validity_status='valid' AND (i.count60 <> 60 OR r.actual_valid_observation_count <> 60 OR r.input_window_start IS DISTINCT FROM i.start60)) OR (i.count60 < 60 AND (r.validity_status='valid' OR strpos(r.reason_codes_json, 'window_insufficient')=0 OR strpos(r.reason_codes_json, 'missing_required_history')=0))))
      OR
      (r.indicator_id IN ('{A2_ID}','{A2B_ID}') AND ((r.validity_status='valid' AND (i.count79 <> 79 OR r.actual_valid_observation_count <> 79 OR r.input_window_start IS DISTINCT FROM i.start79)) OR (i.count79 < 79 AND (r.validity_status='valid' OR strpos(r.reason_codes_json, 'window_insufficient')=0 OR strpos(r.reason_codes_json, 'missing_required_history')=0))))
    """
    _add_invariant_count(
        connection,
        window_query,
        "window_invariant_mismatch",
        errors,
        mismatch_counts,
    )
    pair_query = f"""
      SELECT COUNT(*) FROM (
        SELECT security_id, trading_date, observation_sequence,
               MAX(validity_status) FILTER (WHERE indicator_id='{A2_ID}') AS a2_validity,
               MAX(validity_status) FILTER (WHERE indicator_id='{A2B_ID}') AS a2b_validity,
               MAX(reason_codes_json) FILTER (WHERE indicator_id='{A2_ID}') AS a2_reason,
               MAX(reason_codes_json) FILTER (WHERE indicator_id='{A2B_ID}') AS a2b_reason,
               MAX(input_window_start) FILTER (WHERE indicator_id='{A2_ID}') AS a2_start,
               MAX(input_window_start) FILTER (WHERE indicator_id='{A2B_ID}') AS a2b_start,
               MAX(input_window_end) FILTER (WHERE indicator_id='{A2_ID}') AS a2_end,
               MAX(input_window_end) FILTER (WHERE indicator_id='{A2B_ID}') AS a2b_end,
               MAX(required_observation_count) FILTER (WHERE indicator_id='{A2_ID}') AS a2_required,
               MAX(required_observation_count) FILTER (WHERE indicator_id='{A2B_ID}') AS a2b_required,
               MAX(actual_valid_observation_count) FILTER (WHERE indicator_id='{A2_ID}') AS a2_count,
               MAX(actual_valid_observation_count) FILTER (WHERE indicator_id='{A2B_ID}') AS a2b_count,
               COUNT(*) FILTER (WHERE indicator_id='{A2_ID}') AS a2_rows,
               COUNT(*) FILTER (WHERE indicator_id='{A2B_ID}') AS a2b_rows
        FROM exp_a01_raw_metrics
        GROUP BY 1,2,3
        HAVING a2_rows <> 1 OR a2b_rows <> 1
          OR a2_validity IS DISTINCT FROM a2b_validity
          OR a2_reason IS DISTINCT FROM a2b_reason
          OR a2_start IS DISTINCT FROM a2b_start
          OR a2_end IS DISTINCT FROM a2b_end
          OR a2_required IS DISTINCT FROM a2b_required
          OR a2_count IS DISTINCT FROM a2b_count
      ) pair_mismatches
    """
    _add_invariant_count(
        connection,
        pair_query,
        "a2_a2b_pair_mismatch",
        errors,
        mismatch_counts,
    )
    _add_invariant_count(
        connection,
        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE validity_status='valid' AND expected_observation_status IS DISTINCT FROM 'present'",
        "validity_domain_mismatch",
        errors,
        mismatch_counts,
    )
    _add_invariant_count(
        connection,
        "SELECT COUNT(*) FROM exp_a01_raw_metrics WHERE expected_observation_status <> 'present' AND validity_status='valid'",
        "validity_domain_mismatch",
        errors,
        mismatch_counts,
    )


def _sample_hash_expression(alias: str = "r") -> str:
    return (
        "md5(CAST("
        f"{alias}.security_id AS VARCHAR) || '|' || CAST({alias}.observation_sequence AS VARCHAR) || '|' || '{ORACLE_SAMPLE_VERSION}'"
        ")"
    )


def _sampled_raw_row_compare(
    expected: Mapping[str, Any],
    actual: Sequence[Any] | None,
) -> tuple[list[str], float | None, float | None]:
    if actual is None:
        return ["missing_persisted_row"], None, None
    actual_map = dict(zip(RAW_TABLE_COLUMNS, actual, strict=True))
    differences: list[str] = []
    for field in RAW_TABLE_COLUMNS:
        expected_value = expected[field]
        actual_value = actual_map[field]
        if field == "raw_value":
            if expected_value is None or actual_value is None:
                if expected_value is not None or actual_value is not None:
                    differences.append(field)
                continue
            try:
                left = float(expected_value)
                right = float(actual_value)
            except (TypeError, ValueError):
                differences.append(field)
                continue
            if not math.isfinite(left) or not math.isfinite(right):
                differences.append(field)
                continue
            tolerance = SAMPLED_NUMERIC_TOLERANCES[expected["indicator_id"]]
            if expected["indicator_id"] == A2_ID:
                expected_count = round(left * 20.0)
                actual_count = round(right * 20.0)
                if actual_count != expected_count or not math.isclose(
                    right,
                    expected_count / 20.0,
                    rel_tol=tolerance["relative"],
                    abs_tol=tolerance["absolute"],
                ):
                    differences.append("raw_value")
            elif not math.isclose(
                left,
                right,
                rel_tol=tolerance["relative"],
                abs_tol=tolerance["absolute"],
            ):
                differences.append("raw_value")
        elif field == "reason_codes_json":
            try:
                expected_reason = json.dumps(
                    json.loads(str(expected_value)), separators=(",", ":")
                )
                actual_reason = json.dumps(
                    json.loads(str(actual_value)), separators=(",", ":")
                )
            except (TypeError, json.JSONDecodeError):
                expected_reason = actual_reason = None
            if expected_reason != actual_reason:
                differences.append(field)
        elif field in {"trading_date", "input_window_start", "input_window_end"}:
            if _date_text(actual_value) != expected_value:
                differences.append(field)
        elif actual_value != expected_value:
            differences.append(field)
    try:
        expected_float = float(expected["raw_value"])
        actual_float = float(actual_map["raw_value"])
        absolute = abs(expected_float - actual_float)
        relative = absolute / max(abs(expected_float), abs(actual_float), 1.0)
    except (TypeError, ValueError):
        absolute = relative = None
    return differences, absolute, relative


def _validate_stratified_independent_oracle(
    connection: Any,
    *,
    candidate_path: str | Path,
    index_path: str | Path,
    expected_index_table: str,
    expected_index_row_count: int,
    run_id: str,
    config: Mapping[str, Any],
    errors: list[str],
    mismatch_counts: dict[str, int],
) -> dict[str, Any]:
    """Compare all rows only for a deterministic target-key sample."""

    del config
    table = _safe_identifier(expected_index_table)
    indicators_sql = ", ".join(f"'{indicator}'" for indicator in INDICATOR_IDS)
    _attach_read_only(connection, index_path, "expected_lineage")
    _attach_read_only(connection, candidate_path, "candidate_lineage")
    expected_table = f"expected_lineage.{table}"
    mode = (
        "full_small_input"
        if expected_index_row_count <= SMALL_INPUT_FULL_ORACLE_LIMIT
        else "deterministic_stratified_sample"
    )
    connection.execute("DROP TABLE IF EXISTS oracle_sample_targets")
    if mode == "full_small_input":
        connection.execute(
            f"""
            CREATE TEMP TABLE oracle_sample_targets AS
            SELECT DISTINCT security_id, CAST(observation_sequence AS BIGINT) AS observation_sequence
            FROM {expected_table}
            """
        )
    else:
        connection.execute(
            """
            CREATE TEMP TABLE oracle_sample_target_candidates(
              security_id VARCHAR, observation_sequence BIGINT
            )
            """
        )
        # Every security has the first/last anchors and, when available, the
        # first valid A1/A2 plus deterministic valid/nonvalid anchors. The
        # hash ordering makes the choices independent of Python hash randomization.
        anchor_queries = (
            "SELECT security_id, MIN(observation_sequence) FROM exp_a01_raw_metrics GROUP BY 1",
            "SELECT security_id, MAX(observation_sequence) FROM exp_a01_raw_metrics GROUP BY 1",
            f"SELECT security_id, MIN(observation_sequence) FROM exp_a01_raw_metrics WHERE indicator_id='{A1_ID}' AND validity_status='valid' GROUP BY 1",
            f"SELECT security_id, MIN(observation_sequence) FROM exp_a01_raw_metrics WHERE indicator_id='{A2_ID}' AND validity_status='valid' GROUP BY 1",
            f"""
            SELECT security_id, observation_sequence FROM (
              SELECT r.security_id, r.observation_sequence,
                     ROW_NUMBER() OVER (
                       PARTITION BY r.security_id
                       ORDER BY {_sample_hash_expression("r")}
                     ) AS rn
              FROM exp_a01_raw_metrics r
              WHERE r.validity_status='valid'
            ) ranked WHERE rn=1
            """,
            f"""
            SELECT security_id, observation_sequence FROM (
              SELECT r.security_id, r.observation_sequence,
                     ROW_NUMBER() OVER (
                       PARTITION BY r.security_id
                       ORDER BY {_sample_hash_expression("r")}
                     ) AS rn
              FROM exp_a01_raw_metrics r
              WHERE r.validity_status<>'valid'
            ) ranked WHERE rn=1
            """,
        )
        for query in anchor_queries:
            connection.execute(
                "INSERT INTO oracle_sample_target_candidates SELECT * FROM ("
                + query
                + ")"
            )
        for status in ("valid", "unknown", "blocked", "diagnostic_required"):
            connection.execute(
                f"""
                INSERT INTO oracle_sample_target_candidates
                SELECT security_id, observation_sequence
                FROM (
                  SELECT security_id, observation_sequence,
                         ROW_NUMBER() OVER (PARTITION BY indicator_id, validity_status ORDER BY {_sample_hash_expression()}) AS rn
                  FROM exp_a01_raw_metrics r
                  WHERE validity_status='{status}'
                ) ranked WHERE rn <= 20
                """
            )
        connection.execute(
            f"""
            INSERT INTO oracle_sample_target_candidates
            SELECT security_id, observation_sequence
            FROM (
              SELECT security_id, observation_sequence,
                     ROW_NUMBER() OVER (PARTITION BY indicator_id, reason_code ORDER BY hash_key) AS rn
              FROM (
                SELECT r.security_id, r.observation_sequence, r.indicator_id,
                       json_extract_string(j.value, '$') AS reason_code,
                       {_sample_hash_expression("r")} AS hash_key
                FROM exp_a01_raw_metrics r, LATERAL json_each(CASE WHEN json_valid(r.reason_codes_json) THEN r.reason_codes_json ELSE '[]' END) j
                WHERE r.indicator_id IN ({indicators_sql})
              ) expanded
            ) ranked WHERE rn <= 10
            """
        )
        connection.execute(
            f"""
            INSERT INTO oracle_sample_target_candidates
            SELECT security_id, observation_sequence
            FROM (
              SELECT security_id, observation_sequence,
                     ROW_NUMBER() OVER (PARTITION BY indicator_id, YEAR(trading_date) ORDER BY {_sample_hash_expression()}) AS rn
              FROM exp_a01_raw_metrics r
              WHERE validity_status='valid'
            ) ranked WHERE rn <= 5
            """
        )
        connection.execute(
            """
            INSERT INTO oracle_sample_target_candidates
            SELECT security_id, observation_sequence FROM (
              SELECT security_id, observation_sequence,
                     ROW_NUMBER() OVER (PARTITION BY indicator_id ORDER BY raw_value ASC, security_id, observation_sequence) AS rn
              FROM exp_a01_raw_metrics WHERE validity_status='valid'
            ) ranked WHERE rn <= 20
            UNION ALL
            SELECT security_id, observation_sequence FROM (
              SELECT security_id, observation_sequence,
                     ROW_NUMBER() OVER (PARTITION BY indicator_id ORDER BY raw_value DESC, security_id, observation_sequence) AS rn
              FROM exp_a01_raw_metrics WHERE validity_status='valid'
            ) ranked WHERE rn <= 20
            """
        )
        connection.execute(
            """
            CREATE TEMP TABLE oracle_sample_targets AS
            SELECT DISTINCT security_id, observation_sequence
            FROM oracle_sample_target_candidates
            """
        )
    target_count = int(
        connection.execute("SELECT COUNT(*) FROM oracle_sample_targets").fetchone()[0]
    )
    if mode != "full_small_input" and target_count > ORACLE_SAMPLE_TARGET_LIMIT:
        mismatch_counts["oracle_sample_mismatch"] += 1
        errors.append("oracle_sample_target_limit_exceeded")
        return {
            "oracle_mode": mode,
            "oracle_target_observation_count": target_count,
            "oracle_sample_target_fingerprint": None,
            "oracle_compared_raw_row_count": 0,
            "oracle_sample_security_count": 0,
            "oracle_mismatch_count": 1,
            "oracle_sample_indicator_ids": [],
            "oracle_sample_validity_statuses": [],
            "oracle_sample_reason_codes": [],
            "oracle_sample_years": [],
            "oracle_max_absolute_difference_by_indicator": {},
            "oracle_max_relative_difference_by_indicator": {},
        }
    raw_target_rows = connection.execute(
        """
        SELECT r.*
        FROM exp_a01_raw_metrics r
        JOIN oracle_sample_targets t
          ON t.security_id=r.security_id
         AND t.observation_sequence=r.observation_sequence
        ORDER BY r.security_id, r.observation_sequence,
          CASE r.indicator_id WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END
        """,
        [A1_ID, A2_ID],
    ).fetchall()
    target_fingerprint = hashlib.sha256(
        "\n".join(
            f"{row[0]}|{int(row[1])}"
            for row in connection.execute(
                "SELECT security_id, observation_sequence FROM oracle_sample_targets ORDER BY security_id, observation_sequence"
            ).fetchall()
        ).encode("utf-8")
    ).hexdigest()
    actual_by_key = {
        (str(row[1]), int(row[3]), str(row[5])): row for row in raw_target_rows
    }
    candidate_join_sql = """
      LEFT JOIN candidate_lineage.d3_candidate_daily_observation m
        ON i.expected_observation_status='present'
       AND m.ts_code=i.security_id
       AND CAST(COALESCE(try_strptime(CAST(m.trade_date AS VARCHAR), '%Y-%m-%d'), try_strptime(CAST(m.trade_date AS VARCHAR), '%Y%m%d')) AS DATE)
           = CAST(COALESCE(try_strptime(CAST(i.trading_date AS VARCHAR), '%Y-%m-%d'), try_strptime(CAST(i.trading_date AS VARCHAR), '%Y%m%d')) AS DATE)
    """
    if mode == "full_small_input":
        target_select_sql = """
             i.security_id AS target_security_id,
             CAST(i.observation_sequence AS BIGINT) AS target_observation_sequence,
        """
        source_sql = f"FROM {expected_table} i\n{candidate_join_sql}"
        order_sql = "i.security_id, CAST(i.observation_sequence AS BIGINT)"
    else:
        target_select_sql = """
             t.security_id AS target_security_id,
             t.observation_sequence AS target_observation_sequence,
        """
        source_sql = f"""
      FROM oracle_sample_targets t
      JOIN {expected_table} i
        ON i.security_id=t.security_id
       AND CAST(i.observation_sequence AS BIGINT) BETWEEN t.observation_sequence - 78 AND t.observation_sequence
      {candidate_join_sql}
        """
        order_sql = "t.security_id, t.observation_sequence, CAST(i.observation_sequence AS BIGINT)"
    history_query = f"""
      SELECT {target_select_sql}
             i.security_id,
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
      {source_sql}
      ORDER BY {order_sql}
    """
    cursor = connection.execute(history_query)
    current_target: tuple[str, int] | None = None
    history: list[dict[str, Any]] = []
    compared = 0
    oracle_mismatches = 0
    max_abs: dict[str, float] = {indicator: 0.0 for indicator in INDICATOR_IDS}
    max_rel: dict[str, float] = {indicator: 0.0 for indicator in INDICATOR_IDS}
    sampled_statuses: set[str] = set()
    sampled_reasons: set[str] = set()
    sampled_years: set[str] = set()
    sampled_indicators: set[str] = set()

    def process_target(target: tuple[str, int], rows: list[dict[str, Any]]) -> None:
        nonlocal compared, oracle_mismatches
        for expected_row in _independent_metrics(rows, run_id=run_id):
            key = (
                expected_row["security_id"],
                expected_row["observation_sequence"],
                expected_row["indicator_id"],
            )
            actual = actual_by_key.get(key)
            differences, absolute, relative = _sampled_raw_row_compare(
                expected_row, actual
            )
            compared += 1
            sampled_indicators.add(expected_row["indicator_id"])
            sampled_statuses.add(str((actual or [None] * 16)[8]))
            if expected_row["trading_date"]:
                sampled_years.add(str(expected_row["trading_date"])[:4])
            try:
                sampled_reasons.update(
                    str(reason)
                    for reason in json.loads(expected_row["reason_codes_json"])
                )
            except (TypeError, json.JSONDecodeError):
                pass
            if absolute is not None:
                max_abs[expected_row["indicator_id"]] = max(
                    max_abs[expected_row["indicator_id"]], absolute
                )
            if relative is not None:
                max_rel[expected_row["indicator_id"]] = max(
                    max_rel[expected_row["indicator_id"]], relative
                )
            if differences:
                oracle_mismatches += len(differences)
                mismatch_counts["oracle_sample_mismatch"] += len(differences)
                if len(errors) < 50:
                    errors.append(
                        f"oracle_sample_mismatch:{target[0]}:{target[1]}:{differences}"
                    )

    if mode == "full_small_input":
        history_by_security: dict[str, list[dict[str, Any]]] = {}
        for row in _fetchmany(cursor):
            current = _independent_input_row(row[2:])
            security_history = history_by_security.setdefault(
                current["security_id"], []
            )
            security_history.append(current)
            if len(security_history) > 79:
                del security_history[:-79]
            process_target(
                (current["security_id"], current["observation_sequence"]),
                security_history,
            )
    else:
        for row in _fetchmany(cursor):
            target = (str(row[0]), int(row[1]))
            if current_target is None:
                current_target = target
            if target != current_target:
                process_target(current_target, history)
                history = []
                current_target = target
            history.append(_independent_input_row(row[2:]))
        if current_target is not None:
            process_target(current_target, history)
    observed_security_count = int(
        connection.execute(
            "SELECT COUNT(DISTINCT security_id) FROM exp_a01_raw_metrics"
        ).fetchone()[0]
    )
    sampled_security_count = int(
        connection.execute(
            "SELECT COUNT(DISTINCT security_id) FROM oracle_sample_targets"
        ).fetchone()[0]
    )
    observed_statuses = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT validity_status FROM exp_a01_raw_metrics"
        ).fetchall()
    }
    observed_reasons = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT DISTINCT json_extract_string(j.value, '$')
            FROM exp_a01_raw_metrics r, LATERAL json_each(CASE WHEN json_valid(r.reason_codes_json) THEN r.reason_codes_json ELSE '[]' END) j
            WHERE json_valid(r.reason_codes_json)
            """
        ).fetchall()
    }
    observed_years = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT CAST(YEAR(trading_date) AS VARCHAR) FROM exp_a01_raw_metrics WHERE validity_status='valid'"
        ).fetchall()
    }
    if sampled_security_count != observed_security_count:
        oracle_mismatches += 1
        mismatch_counts["oracle_sample_mismatch"] += 1
        errors.append(
            f"oracle_sample_security_coverage_mismatch:expected={observed_security_count}:actual={sampled_security_count}"
        )
    if sampled_indicators != set(INDICATOR_IDS):
        oracle_mismatches += 1
        mismatch_counts["oracle_sample_mismatch"] += 1
        errors.append("oracle_sample_indicator_coverage_mismatch")
    if not observed_statuses.issubset(sampled_statuses):
        oracle_mismatches += 1
        mismatch_counts["oracle_sample_mismatch"] += 1
        errors.append("oracle_sample_validity_status_coverage_mismatch")
    if not observed_reasons.issubset(sampled_reasons):
        oracle_mismatches += 1
        mismatch_counts["oracle_sample_mismatch"] += 1
        errors.append("oracle_sample_reason_code_coverage_mismatch")
    if not observed_years.issubset(sampled_years):
        oracle_mismatches += 1
        mismatch_counts["oracle_sample_mismatch"] += 1
        errors.append("oracle_sample_year_coverage_mismatch")
    return {
        "oracle_mode": mode,
        "oracle_target_observation_count": target_count,
        "oracle_sample_target_fingerprint": target_fingerprint,
        "oracle_compared_raw_row_count": compared,
        "oracle_sample_security_count": sampled_security_count,
        "oracle_sample_indicator_ids": sorted(sampled_indicators),
        "oracle_sample_validity_statuses": sorted(sampled_statuses),
        "oracle_sample_reason_codes": sorted(sampled_reasons),
        "oracle_sample_years": sorted(sampled_years),
        "oracle_mismatch_count": oracle_mismatches,
        "oracle_max_absolute_difference_by_indicator": max_abs,
        "oracle_max_relative_difference_by_indicator": max_rel,
    }


def _fetchmany(cursor: Any, size: int = 4096) -> Iterable[tuple[Any, ...]]:
    while True:
        rows = cursor.fetchmany(size)
        if not rows:
            return
        yield from rows


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
        "listed_open_resolved_daily",
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
    low_tolerance = boundary_tolerance(body, low)
    high_tolerance = boundary_tolerance(body, high)
    return body < low - low_tolerance or body > high + high_tolerance


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
    low_tolerance = boundary_tolerance(body_high, low)
    high_tolerance = boundary_tolerance(body_low, high)
    if body_high < low - low_tolerance:
        return low - body_high
    if body_low > high + high_tolerance:
        return body_low - high
    return 0.0


def boundary_tolerance(left: float, right: float) -> float:
    """Return the independent validator's shared eight-ULP allowance."""

    return BOUNDARY_ULPS * FLOAT64_EPSILON * max(1.0, abs(left), abs(right))


def _csv_float_equal(expected: Any, actual: Any) -> bool:
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
    return difference <= 1e-12 and relative <= 1e-9


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
            return _csv_float_equal(expected, float(actual))
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


def _validate_final_package_bindings(
    output_dir: str | Path,
    *,
    core_validation: Mapping[str, Any],
    anomaly: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    input_manifest_path: str | Path,
    input_paths: Mapping[str, str | Path],
    input_metadata: Mapping[str, Mapping[str, Any]],
    reviewed_implementation_sha: str,
    expected_manifest_sha256: str | None = None,
    require_validator_result: bool = False,
) -> dict[str, Any]:
    """Perform only final-package binding checks; never rerun core validation."""

    root = Path(output_dir)
    errors: list[str] = []
    mismatch_counts = {
        "artifact_hash_mismatch": 0,
        "input_hash_changed": 0,
        "analysis_section_mismatch": 0,
        "prohibited_output_mismatch": 0,
    }
    expected_files = {
        "exp_a01_raw_metrics.duckdb",
        "exp_a01_metric_profile.csv",
        "exp_a01_validity_profile.csv",
        "exp_a01_year_coverage.csv",
        "exp_a01_security_coverage.csv",
        "exp_a01_manifest.json",
        "exp_a01_anomaly_scan.json",
        "exp_a01_result_analysis.md",
        "exp_a01_validator_result.json",
    }
    actual_files = {path.name for path in root.iterdir()} if root.is_dir() else set()
    for name in sorted(expected_files - actual_files):
        if require_validator_result or name != "exp_a01_validator_result.json":
            errors.append(f"missing_output_file:{name}")
    for name in sorted(actual_files - expected_files):
        errors.append(f"unexpected_output_file:{name}")
    if (
        core_validation.get("status") != "passed"
        or core_validation.get("valid") is not True
    ):
        errors.append("core_validation_not_passed")
    if anomaly.get("status") == "failed":
        errors.append("anomaly_status_failed")

    manifest_path = root / "exp_a01_manifest.json"
    formal_manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            raw = manifest_path.read_bytes()
            text_errors = canonical_text_errors(raw)
            if text_errors:
                errors.append(f"formal_manifest_text_contract:{text_errors}")
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, Mapping):
                formal_manifest = dict(value)
            else:
                errors.append("formal_manifest_root_not_object")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"formal_manifest_invalid:{exc}")
    _validate_final_manifest_identity(
        formal_manifest,
        errors,
        reviewed_implementation_sha=reviewed_implementation_sha,
        input_manifest=input_manifest,
        input_manifest_path=input_manifest_path,
    )
    if (
        expected_manifest_sha256 is not None
        and sha256_file(manifest_path) != expected_manifest_sha256
    ):
        mismatch_counts["artifact_hash_mismatch"] += 1
        errors.append("final_manifest_sha256_mismatch")
    if formal_manifest.get("validator_status") != "passed":
        errors.append("final_manifest_validator_status_not_passed")
    if formal_manifest.get("anomaly_status") == "failed":
        errors.append("final_manifest_anomaly_status_failed")
    _validate_output_artifact_hashes(root, formal_manifest, errors, mismatch_counts)

    for artifact_id, metadata in input_metadata.items():
        path = Path(str(metadata.get("path", input_paths[artifact_id])))
        if sha256_file(path) != metadata.get("sha256"):
            mismatch_counts["input_hash_changed"] += 1
            errors.append(f"input_hash_changed:{artifact_id}")

    analysis_path = root / "exp_a01_result_analysis.md"
    if analysis_path.is_file():
        raw_analysis = analysis_path.read_bytes()
        text_errors = canonical_text_errors(raw_analysis)
        if text_errors:
            mismatch_counts["analysis_section_mismatch"] += 1
            errors.append(f"analysis_text_contract:{text_errors}")
        analysis_text = raw_analysis.decode("utf-8", errors="replace")
        required_sections = (
            "Actual run / reviewed SHA",
            "Input manifest and authorization",
            "D3-T07 lineage",
            "Input governance override",
            "Dense expected-index reconciliation",
            "Fixed candidate definitions",
            "Raw table cardinality",
            "Metric domains and distributions",
            "Validity status profile",
            "Reason-code profile",
            "Year coverage",
            "Security coverage",
            "Full invariant validation and stratified independent oracle",
            "Validator result",
            "Anomaly scan",
            "Supported and unsupported conclusions",
            "Readiness for user Formal-result review",
        )
        missing = [
            section for section in required_sections if section not in analysis_text
        ]
        if missing:
            mismatch_counts["analysis_section_mismatch"] += len(missing)
            errors.append(f"analysis_required_sections_missing:{missing}")
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
                "independent full recomputation",
            )
        ):
            mismatch_counts["prohibited_output_mismatch"] += 1
            errors.append("analysis_contains_prohibited_output_token")

    result = dict(core_validation)
    combined_errors = list(dict.fromkeys([*core_validation.get("errors", []), *errors]))
    combined_counts = {
        str(key): int(value)
        for key, value in core_validation.get("mismatch_counts", {}).items()
    }
    for key, value in mismatch_counts.items():
        combined_counts[key] = combined_counts.get(key, 0) + int(value)
    result.update(
        {
            "errors": combined_errors,
            "mismatch_counts": combined_counts,
            "status": "passed"
            if not combined_errors
            and all(value == 0 for value in combined_counts.values())
            else "failed",
            "valid": not combined_errors
            and all(value == 0 for value in combined_counts.values()),
            "final_package_validation_performed": True,
            "core_validator_reexecuted": False,
            "oracle_reexecuted": False,
            "final_manifest_sha256": sha256_file(manifest_path)
            if manifest_path.is_file()
            else None,
        }
    )
    return result


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
