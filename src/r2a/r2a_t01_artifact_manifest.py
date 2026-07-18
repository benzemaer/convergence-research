"""Schema descriptor and manifest helpers for R2A-T01 packages."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.common.canonical_io import formal_source_binding
from src.r2a.r2a_t01_input_manifest import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]

TABLE_ORDER = (
    "securities",
    "trading_sessions",
    "security_observation_spine",
    "dimension_definitions",
    "dimension_components",
    "daily_component_scores",
    "daily_dimension_scores",
)

TABLE_COLUMNS = {
    "securities": ("security_id", "security_name", "universe_id"),
    "trading_sessions": ("trading_date", "observation_sequence", "available_time"),
    "security_observation_spine": (
        "security_id",
        "trading_date",
        "observation_sequence",
        "observation_status",
        "observation_available_time",
    ),
    "dimension_definitions": ("dimension_id", "dimension_order", "component_count"),
    "dimension_components": (
        "dimension_id",
        "indicator_id",
        "component_order",
    ),
    "daily_component_scores": (
        "security_id",
        "trading_date",
        "observation_sequence",
        "indicator_id",
        "percentile_window",
        "raw_value",
        "eligible",
        "percentile",
        "score",
        "validity_status",
        "reason_codes",
        "reference_observation_count",
        "reference_sequence_start",
        "reference_sequence_end",
        "available_time",
        "source_release_id",
    ),
    "daily_dimension_scores": (
        "security_id",
        "trading_date",
        "observation_sequence",
        "dimension_id",
        "percentile_window",
        "eligible_dimension",
        "score_dimension",
        "score_dimension_min",
        "validity_status",
        "reason_codes",
        "available_time",
        "source_release_id",
    ),
}

PRIMARY_KEYS = {
    "securities": ("security_id",),
    "trading_sessions": ("trading_date",),
    "security_observation_spine": ("security_id", "trading_date"),
    "dimension_definitions": ("dimension_id",),
    "dimension_components": ("dimension_id", "indicator_id"),
    "daily_component_scores": ("security_id", "trading_date", "indicator_id"),
    "daily_dimension_scores": ("security_id", "trading_date", "dimension_id"),
}

FORMAL_EXECUTION_SURFACE = (
    "configs/r2a/r2a_t01_pcavt_score_release.v1.json",
    "configs/r2a/r2a_t01_eod_availability_policy.v1.json",
    "schemas/r2a/r2a_t01_pcavt_score_release_config.schema.json",
    "schemas/r2a/r2a_t01_eod_availability_policy.schema.json",
    "schemas/r2a/r2a_t01_score_release_schema.schema.json",
    "schemas/r2a/r2a_t01_score_release_manifest.schema.json",
    "schemas/r2a/r2a_t01_validation_receipt.schema.json",
    "schemas/r2a/r2a_t01_authorized_input_manifest.schema.json",
    "src/r2a/__init__.py",
    "src/r2a/score_engine.py",
    "src/r2a/r2a_t01_input_manifest.py",
    "src/r2a/r2a_t01_artifact_manifest.py",
    "src/r2a/r2a_t01_score_release.py",
    "src/r2a/r2a_t01_validator.py",
    "src/r2a/r2a_t01_result_analysis.py",
    "scripts/r2a/build_r2a_t01_authorized_input_manifest.py",
    "scripts/r2a/run_r2a_t01_score_release.py",
    "scripts/r2a/validate_r2a_t01_score_release.py",
    "scripts/r2a/analyze_r2a_t01_score_release.py",
    "requirements-dev.txt",
)


def schema_descriptor() -> dict[str, Any]:
    return {
        "schema_version": "r2a_t01_score_release_schema.v1",
        "table_order": list(TABLE_ORDER),
        "tables": {
            table: {
                "primary_key": list(PRIMARY_KEYS[table]),
                "columns": list(TABLE_COLUMNS[table]),
            }
            for table in TABLE_ORDER
        },
    }


def write_schema(path: str | Path) -> dict[str, Any]:
    payload = schema_descriptor()
    descriptor_schema = json.loads(
        (ROOT / "schemas/r2a/r2a_t01_score_release_schema.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(descriptor_schema).validate(payload)
    write_json_atomic(path, payload)
    return payload


def build_manifest(
    *,
    package_dir: str | Path,
    run_id: str,
    score_release_id: str,
    authorized_input_manifest: str | Path,
    config_path: str | Path,
    availability_policy_path: str | Path,
    row_counts: Mapping[str, int],
    worker_count: int,
    synthetic_only: bool,
    execution_commit: str | None,
) -> dict[str, Any]:
    package = Path(package_dir)
    policy_path = Path(availability_policy_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    bindings: dict[str, dict[str, Any]] = {}
    if not synthetic_only:
        if execution_commit is None:
            raise ValueError("formal_execution_commit_required")
        for relative in FORMAL_EXECUTION_SURFACE:
            bindings[relative] = formal_source_binding(
                ROOT / relative, execution_commit, root=ROOT
            )
        input_relative = Path(authorized_input_manifest).resolve().relative_to(ROOT)
        input_key = input_relative.as_posix()
        bindings[input_key] = formal_source_binding(
            Path(authorized_input_manifest), execution_commit, root=ROOT
        )
    config_hash = (
        bindings[Path(config_path).resolve().relative_to(ROOT).as_posix()][
            "committed_byte_sha256"
        ]
        if bindings
        else sha256_file(config_path)
    )
    policy_hash = (
        bindings[policy_path.resolve().relative_to(ROOT).as_posix()][
            "committed_byte_sha256"
        ]
        if bindings
        else sha256_file(policy_path)
    )
    input_hash = (
        bindings[
            Path(authorized_input_manifest).resolve().relative_to(ROOT).as_posix()
        ]["committed_byte_sha256"]
        if bindings
        else sha256_file(authorized_input_manifest)
    )
    payload = {
        "manifest_version": "r2a_t01_score_release_manifest.v1",
        "run_id": run_id,
        "score_release_id": score_release_id,
        "synthetic_only": synthetic_only,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authorized_input_manifest": str(Path(authorized_input_manifest).resolve()),
        "authorized_input_manifest_sha256": input_hash,
        "score_data_sha256": sha256_file(package / "score_data.duckdb"),
        "schema_sha256": sha256_file(package / "schema.json"),
        "config_sha256": config_hash,
        "availability_policy_id": policy["policy_id"],
        "availability_policy_version": policy["policy_version"],
        "availability_policy_sha256": policy_hash,
        "timezone": policy["timezone"],
        "market_information_cutoff": policy["market_information_cutoff"],
        "execution_commit": execution_commit,
        "environment_lock_sha256": (
            bindings["requirements-dev.txt"]["committed_byte_sha256"]
            if bindings
            else sha256_file(ROOT / "requirements-dev.txt")
        ),
        "formal_source_bindings": bindings,
        "worker_count": worker_count,
        "row_counts": {name: int(row_counts[name]) for name in TABLE_ORDER},
    }
    manifest_schema = json.loads(
        (ROOT / "schemas/r2a/r2a_t01_score_release_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(manifest_schema, format_checker=FormatChecker()).validate(
        payload
    )
    write_json_atomic(package / "manifest.json", payload)
    return payload
