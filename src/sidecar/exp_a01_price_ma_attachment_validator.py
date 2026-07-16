"""Independent validation helpers for EXP-A01 configuration and raw metrics."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.sidecar.exp_a01_price_ma_attachment import (
    A1_ID,
    A1_REQUIRED_OBSERVATIONS,
    A2_ID,
    A2_REQUIRED_OBSERVATIONS,
    A2B_ID,
    INDICATOR_IDS,
    METRIC_ENGINE_VERSION,
    OUTPUT_FIELDS,
    RAW_METRIC_NAMES,
    REASON_CODES,
    VALIDITY_STATUSES,
)

TASK_ID = "EXP-A01"
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
    """Return deterministic errors for the frozen A01 implementation config."""

    errors: list[str] = []
    constants = {
        "task_id": TASK_ID,
        "experiment_id": TASK_ID,
        "program_id": "EXP-A",
        "research_route": "sidecar_exploration",
        "candidate_layer": "A",
        "candidate_layer_name": "price_ma_attachment",
        "workflow_mode": "long_lived_same_pr",
        "phase": "implementation_review",
        "program_phase": "A01_candidate_raw_metric_implementation",
        "implementation_review_status": "pending",
        "formal_run_allowed": False,
        "formal_run_status": "not_started",
        "formal_run_executed": False,
        "result_review_status": "not_started",
        "mainline_task_unchanged": True,
        "mainline_current_task": "R3-T02",
        "formal_layer_registered": False,
        "pcvt_modified": False,
        "pcatv_created": False,
        "existing_indicator_modified": False,
        "future_outcome_used": False,
    }
    for key, expected in constants.items():
        if config.get(key) != expected:
            errors.append(f"config_{key}_mismatch")

    reviewed_sha = config.get("reviewed_implementation_sha")
    if (
        not isinstance(reviewed_sha, str)
        or reviewed_sha
        not in {
            "",
        }
        and not re.fullmatch(r"[0-9a-f]{40}", reviewed_sha)
    ):
        errors.append("config_reviewed_implementation_sha_invalid")

    parameters = config.get("parameters")
    if not isinstance(parameters, Mapping):
        errors.append("config_parameters_missing")
    else:
        expected_parameters = {
            "ma_windows": [5, 10, 20, 30, 60],
            "a2_rolling_window": 20,
            "a1_required_observations": 60,
            "a2_required_observations": 79,
            "current_day_included": True,
            "raw_value_direction": "lower_is_more_attached",
        }
        for key, expected in expected_parameters.items():
            if parameters.get(key) != expected:
                errors.append(f"config_parameter_{key}_mismatch")

    price_basis = config.get("price_basis")
    if not isinstance(price_basis, Mapping):
        errors.append("config_price_basis_missing")
    else:
        if price_basis.get("authoritative_contract") != (
            "D3_DAILY_MARKET_OBSERVATION_VALUES_CONTRACT_V1"
        ):
            errors.append("config_authoritative_adjusted_ohlc_contract_mismatch")
        if price_basis.get("candidate_materialization_contract") != (
            "D3_T07_CANDIDATE_DAILY_OBSERVATION_CONTRACT_V1"
        ):
            errors.append("config_candidate_materialization_contract_mismatch")
        if price_basis.get("moving_average_windows") != [5, 10, 20, 30, 60]:
            errors.append("config_ma_windows_mismatch")
        if price_basis.get("raw_ohlc_forbidden") is not True:
            errors.append("config_raw_ohlc_not_forbidden")

    candidate_rows = config.get("candidates")
    if not isinstance(candidate_rows, Sequence) or isinstance(
        candidate_rows, str | bytes
    ):
        errors.append("config_candidates_missing")
    else:
        if len(candidate_rows) != len(EXPECTED_CANDIDATES):
            errors.append("config_candidate_count_mismatch")
        for index, expected in enumerate(EXPECTED_CANDIDATES):
            if index >= len(candidate_rows) or not isinstance(
                candidate_rows[index], Mapping
            ):
                errors.append(f"config_candidate_{index}_missing")
                continue
            row = candidate_rows[index]
            for key, value in expected.items():
                if row.get(key) != value:
                    errors.append(f"config_candidate_{index}_{key}_mismatch")

    validity = config.get("validity_contract")
    if not isinstance(validity, Mapping):
        errors.append("config_validity_contract_missing")
    else:
        if validity.get("validity_statuses") != list(VALIDITY_STATUSES):
            errors.append("config_validity_statuses_mismatch")
        configured_reasons = validity.get("reason_codes")
        if not isinstance(configured_reasons, Sequence) or isinstance(
            configured_reasons, str | bytes
        ):
            errors.append("config_reason_codes_missing")
        else:
            missing = sorted(set(REASON_CODES) - set(configured_reasons))
            if missing:
                errors.append(f"config_reason_codes_missing_values:{missing}")
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
        artifacts = input_contract.get("artifacts")
        if not isinstance(artifacts, Mapping) or not isinstance(
            artifacts.get("adjusted_ohlc"), Mapping
        ):
            errors.append("config_adjusted_ohlc_artifact_missing")
        else:
            artifact = artifacts["adjusted_ohlc"]
            if artifact.get("source_contract") != (
                "D3_DAILY_MARKET_OBSERVATION_VALUES_CONTRACT_V1"
            ):
                errors.append("config_input_source_contract_mismatch")
            required_columns = artifact.get("required_columns")
            if (
                not isinstance(required_columns, Sequence)
                or isinstance(required_columns, str | bytes)
                or not {
                    "security_id",
                    "trading_date",
                    "adj_open",
                    "adj_close",
                }.issubset(set(required_columns))
            ):
                errors.append("config_input_required_columns_mismatch")

    output_contract = config.get("output_contract")
    if not isinstance(output_contract, Mapping):
        errors.append("config_output_contract_missing")
    else:
        if output_contract.get("no_formal_output_in_implementation") is not True:
            errors.append("config_output_formal_guard_mismatch")
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
        key = (security_id, trading_date, indicator_id)
        if key in seen:
            errors.append(f"row_{index}_duplicate_key:{key}")
        seen.add(key)
        sort_key = (security_id, trading_date, order[indicator_id])
        if last_key is not None and sort_key < last_key:
            errors.append(f"row_{index}_not_deterministically_sorted")
        last_key = sort_key

        expected = next(
            item for item in EXPECTED_CANDIDATES if item["indicator_id"] == indicator_id
        )
        if row.get("raw_metric_name") != expected["raw_metric_name"]:
            errors.append(f"row_{index}_raw_metric_name_mismatch")
        if row.get("required_observation_count") != expected["minimum_history"]:
            errors.append(f"row_{index}_required_observation_count_mismatch")
        if row.get("metric_engine_version") != METRIC_ENGINE_VERSION:
            errors.append(f"row_{index}_engine_version_mismatch")
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
    return {
        "task_id": TASK_ID,
        "status": "passed" if not errors else "failed",
        "valid": not errors,
        "errors": list(dict.fromkeys(errors)),
        "checked_files": sorted(path.name for path in root.iterdir()),
    }


def canonical_text_errors(raw: bytes) -> list[str]:
    """Return canonical UTF-8/LF errors for a formal manifest or source file."""

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
