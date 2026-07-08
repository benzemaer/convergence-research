from __future__ import annotations

import csv
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "docs/evidence/r1/R1-T03_27_grid_light_profile_evidence.md"
CONFIG = ROOT / "configs/r1/r1_t03_27_grid_light_profile.v1.json"
SCHEMA = ROOT / "schemas/r1/r1_t03_27_grid_light_profile.schema.json"

FORBIDDEN_OUTPUT_TOKENS = (
    "future_return",
    "backtest",
    "portfolio",
    "trade_signal",
    "trading_signal",
    "jointlift",
    "empirical_p",
    "z_score",
    "r2_decision_matrix",
    "freeze_candidate",
    "review_candidate",
    "do_not_freeze",
    "best_config",
    "winner",
    "optimized_config",
)
EXPECTED_STATES = {"S_P", "S_PC", "S_PCT", "S_PCVT"}


class R1T03LightProfileValidationError(RuntimeError):
    pass


def validate_r1_t03_27_grid_light_profile(
    summary_path: Path,
    evidence_path: Path = DEFAULT_EVIDENCE,
    *,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    summary = _load_json(summary_path, errors, "summary")
    evidence = _parse_evidence(evidence_path)
    config = _load_json(CONFIG, errors, "config")
    schema = _load_json(SCHEMA, errors, "schema")
    _check_schema(config, schema, errors)
    _check_summary(summary, summary_path, evidence, errors)
    _check_outputs(summary, errors, root)
    _check_evidence(summary, summary_path, evidence, errors, output_path, root)
    result = {
        "task_id": "R1-T03",
        "validator_status": "passed" if not errors else "failed",
        "summary_path": _display_path(summary_path, root),
        "summary_sha256": sha256_file(summary_path) if summary_path.exists() else None,
        "evidence_path": _display_path(evidence_path, root),
        "errors": errors,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if errors:
        raise R1T03LightProfileValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_schema(
    config: dict[str, Any], schema: dict[str, Any], errors: list[str]
) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"config_schema_invalid:{exc}")


def _check_summary(
    summary: dict[str, Any],
    summary_path: Path,
    evidence: dict[str, str],
    errors: list[str],
) -> None:
    if summary.get("task_id") != "R1-T03":
        errors.append("summary_task_id_mismatch")
    if summary.get("status") != "completed":
        errors.append("summary_status_not_completed")
    if summary.get("max_workers", 99) > 3:
        errors.append("summary_max_workers_gt_3")
    if summary.get("duckdb_threads_per_worker") != 1:
        errors.append("summary_duckdb_threads_not_1")
    if summary.get("candidate_config_count") != 27:
        errors.append("summary_candidate_config_count_mismatch")
    if summary.get("state_name_count") != 4:
        errors.append("summary_state_name_count_mismatch")
    if summary.get("profile_row_count") != 108:
        errors.append("summary_profile_row_count_mismatch")
    if summary.get("blocked_config_count") != 0:
        errors.append("summary_blocked_config_count_not_zero")
    if summary.get("zero_confirmed_interval_acknowledged") is not True:
        errors.append("summary_zero_confirmed_not_acknowledged")
    gates = summary.get("downstream_gates", {})
    if gates.get("R1-T04_allowed_to_start") is not True:
        errors.append("summary_R1_T04_not_allowed")
    if gates.get("R1-T07_allowed_to_start") is not False:
        errors.append("summary_R1_T07_not_blocked")
    if gates.get("R2_allowed_to_start") is not False:
        errors.append("summary_R2_not_blocked")
    if evidence and evidence.get("profile_summary_sha256") != sha256_file(summary_path):
        errors.append("evidence_summary_hash_mismatch")


def _check_outputs(summary: dict[str, Any], errors: list[str], root: Path) -> None:
    outputs = summary.get("output_paths", {})
    for key, item in outputs.items():
        path = root / item.get("path", "")
        if not path.exists():
            errors.append(f"output_missing:{key}")
            continue
        if item.get("sha256") != sha256_file(path):
            errors.append(f"output_hash_mismatch:{key}")
    profile_item = outputs.get("profile_by_config_state_csv", {})
    profile_path = root / profile_item.get("path", "")
    if profile_path.exists():
        _check_profile_csv(profile_path, errors)
    profile_json_item = outputs.get("profile_by_config_state_json", {})
    profile_json_path = root / profile_json_item.get("path", "")
    if profile_json_path.exists():
        profile_rows = _load_json(profile_json_path, errors, "profile_json")
        _check_profile_rows(profile_rows, errors)
    relative_item = outputs.get("relative_to_baseline_profile", {})
    relative_path = root / relative_item.get("path", "")
    if relative_path.exists():
        relative = _load_json(relative_path, errors, "relative")
        if _contains_forbidden_key(relative):
            errors.append("relative_contains_forbidden_selection_field")
    retention_item = outputs.get("retention_profile", {})
    retention_path = root / retention_item.get("path", "")
    if retention_path.exists():
        retention = _load_json(retention_path, errors, "retention")
        _check_retention_nulls(retention, errors)


def _check_profile_csv(path: Path, errors: list[str]) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    _check_profile_rows(rows, errors)


def _check_profile_rows(rows: Any, errors: list[str]) -> None:
    if not isinstance(rows, list):
        errors.append("profile_rows_not_list")
        return
    if len(rows) != 108:
        errors.append("profile_row_count_mismatch")
    configs = {row["candidate_config_id"] for row in rows}
    states = {row["state_name"] for row in rows}
    if len(configs) != 27:
        errors.append("profile_config_count_mismatch")
    if states != EXPECTED_STATES:
        errors.append("profile_state_set_mismatch")
    if "R0_W250_Q20_K3_WEAK_D010" not in configs:
        errors.append("profile_baseline_missing")
    if any(_token_in_keys(row) for row in rows):
        errors.append("profile_forbidden_column")


def _check_retention_nulls(retention: Any, errors: list[str]) -> None:
    for row in retention if isinstance(retention, list) else []:
        for key, value in row.items():
            if key.endswith("_denominator_zero") and value is True:
                metric = key.removesuffix("_denominator_zero")
                if row.get(metric) is not None:
                    errors.append(f"retention_denominator_zero_not_null:{metric}")


def _check_evidence(
    summary: dict[str, Any],
    summary_path: Path,
    evidence: dict[str, str],
    errors: list[str],
    output_path: Path | None,
    root: Path,
) -> None:
    if not evidence:
        errors.append("evidence_missing")
        return
    required = {
        "task_id": "R1-T03",
        "status": "completed",
        "validator_status": "passed",
        "R1-T04_allowed_to_start": "true",
        "R1-T07_allowed_to_start": "false",
        "R2_allowed_to_start": "false",
        "no_zero_model_check": "passed",
        "no_parameter_selection_check": "passed",
        "row_payload_absence_check": "passed",
    }
    for key, expected in required.items():
        if evidence.get(key) != expected:
            errors.append(f"evidence_field_mismatch:{key}")
    if evidence.get("profile_summary_path") != _display_path(summary_path, root):
        errors.append("evidence_summary_path_mismatch")
    if evidence.get("profile_summary_sha256") != sha256_file(summary_path):
        errors.append("evidence_summary_hash_mismatch")
    validation_path = evidence.get("validation_result_path")
    validation_hash = evidence.get("validation_result_sha256")
    if validation_path and validation_hash:
        path = root / validation_path
        if not path.exists() or sha256_file(path) != validation_hash:
            errors.append("evidence_validation_result_hash_mismatch")
    elif output_path is None:
        errors.append("evidence_validation_result_missing")
    if not re.fullmatch(r"[0-9a-f]{40}", evidence.get("code_commit", "")):
        errors.append("evidence_code_commit_not_full_sha")


def _load_json(path: Path, errors: list[str], label: str) -> Any:
    if not path.exists():
        errors.append(f"{label}_missing")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}_invalid_json:{exc}")
        return {}


def _parse_evidence(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not path.exists():
        return fields
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("`") or "`:" not in line:
            continue
        key_end = line.find("`:")
        fields[line[1:key_end].strip()] = line[key_end + 2 :].strip().replace("`", "")
    return fields


def _token_in_keys(row: dict[str, Any]) -> bool:
    return any(token in key.lower() for token in FORBIDDEN_OUTPUT_TOKENS for key in row)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(token in str(key).lower() for token in FORBIDDEN_OUTPUT_TOKENS)
            or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _display_path(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
