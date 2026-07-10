# ruff: noqa: E501
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r0_t15_layer_q_vector_materializer import (
    DAILY_DB,
    DAILY_TABLE,
    DIMENSION_DB,
    DIMENSION_TABLE,
    INTERVAL_DB,
    INTERVAL_TABLE,
    NESTED_DB,
    NESTED_TABLE,
    ROOT,
    TASK_ID,
)


def validate_r0_t15_layer_q_vector_materialization(
    *, run_dir: str | Path, require_author_package: bool = False
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    errors: list[str] = []
    required = [
        "r0_t15_request_binding.json",
        "r0_t15_candidate_registry.csv",
        DIMENSION_DB,
        NESTED_DB,
        DAILY_DB,
        INTERVAL_DB,
        "r0_t15_artifact_manifest.json",
        "r0_t15_authorized_handoff_manifest.json",
        "r0_t15_schema_validation.json",
        "r0_t15_upstream_reconciliation.csv",
        "r0_t15_anomaly_scan.json",
        "r0_t15_final_gate_validation_result.json",
        "r0_t15_execution_summary.json",
    ]
    for name in required:
        if not (run_dir / name).is_file():
            errors.append(f"missing_artifact:{name}")
    if errors:
        return _finish(run_dir, errors, require_author_package)
    binding = _load_json(run_dir / "r0_t15_request_binding.json")
    manifest = _load_json(run_dir / "r0_t15_artifact_manifest.json")
    handoff = _load_json(run_dir / "r0_t15_authorized_handoff_manifest.json")
    schema = _load_json(run_dir / "r0_t15_schema_validation.json")
    anomaly = _load_json(run_dir / "r0_t15_anomaly_scan.json")
    final_gate = _load_json(run_dir / "r0_t15_final_gate_validation_result.json")
    registry = _read_csv(run_dir / "r0_t15_candidate_registry.csv")
    reconciliation = _read_csv(run_dir / "r0_t15_upstream_reconciliation.csv")
    if (
        len(registry) != 10
        or sum(row["materialize"] == "true" for row in registry) != 8
    ):
        errors.append("registry_cardinality_invalid")
    if (
        binding.get("upstream_pr_number") != 87
        or binding.get("upstream_head_commit")
        != "2e2cc2931a4c3ff1ab427966bc78f79a0f69c151"
    ):
        errors.append("upstream_pr_binding_invalid")
    if (
        binding.get("upstream_internal_continuation_gate_status") != "passed"
        or binding.get("repository_r0_materialization_gate_passed") is not False
    ):
        errors.append("upstream_gate_boundary_invalid")
    if any(int(row["mismatch_count"]) != 0 for row in reconciliation):
        errors.append("baseline_reconciliation_mismatch")
    if (
        anomaly.get("status") != "passed"
        or anomaly.get("blocking_findings")
        or anomaly.get("unresolved_questions")
    ):
        errors.append("anomaly_scan_not_passed")
    if schema.get("status") != "passed" or schema.get("primary_key_status") != "passed":
        errors.append("schema_validation_not_passed")
    if (
        final_gate.get("status") != "pending_external_review"
        or final_gate.get("formal_task_completed") is not False
    ):
        errors.append("final_gate_boundary_invalid")
    if (
        handoff.get("R1-T14-02_allowed_to_start") is not False
        or handoff.get("repository_t14_02_gate_passed") is not False
    ):
        errors.append("handoff_repository_gate_boundary_invalid")
    output_map = {
        "dimension_state": (DIMENSION_DB, DIMENSION_TABLE),
        "nested_daily_state": (NESTED_DB, NESTED_TABLE),
        "daily_confirmation": (DAILY_DB, DAILY_TABLE),
        "confirmed_interval": (INTERVAL_DB, INTERVAL_TABLE),
    }
    import duckdb  # noqa: PLC0415

    for key, (filename, table) in output_map.items():
        record = manifest.get("outputs", {}).get(key, {})
        path = run_dir / filename
        if sha256_file(path) != record.get("sha256"):
            errors.append(f"output_hash_mismatch:{key}")
            continue
        con = duckdb.connect(str(path), read_only=True)
        try:
            row_count, vector_count = con.execute(
                f"SELECT count(*),count(DISTINCT formal_vector_id) FROM {table}"
            ).fetchone()
        finally:
            con.close()
        if int(row_count) != int(record.get("row_count", -1)) or int(vector_count) != 8:
            errors.append(f"output_summary_mismatch:{key}")
    if require_author_package:
        package_path = run_dir / "r0_t15_result_package.json"
        analysis_copy = run_dir / "r0_t15_result_analysis.md"
        evidence_copy = run_dir / "r0_t15_evidence.md"
        if (
            not package_path.is_file()
            or not analysis_copy.is_file()
            or not evidence_copy.is_file()
        ):
            errors.append("author_package_or_reports_missing")
        else:
            package = _load_json(package_path)
            gate = package.get("gate_status", {})
            if (
                package.get("R0_q_vector_materialization_status")
                != "author_draft_complete"
                or package.get("formal_task_completed") is not False
            ):
                errors.append("author_package_status_invalid")
            if (
                package.get("independent_review_status") != "not_started"
                or package.get("repository_final_gate_status") != "pending"
            ):
                errors.append("author_package_review_boundary_invalid")
            if package.get("R1-T14-02_allowed_to_start") is not False:
                errors.append("author_package_formal_t14_02_gate_open")
            if (
                gate.get("goal_internal_continuation_gate_status") != "passed"
                or gate.get("engineering_validator_status") != "passed"
                or gate.get("author_result_analysis_status") != "passed"
            ):
                errors.append("author_package_internal_gate_invalid")
            for artifact in package.get("committed_artifacts", []):
                path = ROOT / artifact["path"]
                if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                    errors.append(f"package_artifact_hash_mismatch:{artifact['path']}")
    return _finish(run_dir, errors, require_author_package)


def _finish(
    run_dir: Path, errors: list[str], require_author_package: bool
) -> dict[str, Any]:
    result = {
        "task_id": TASK_ID,
        "validation_mode": "author_package"
        if require_author_package
        else "engineering",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
        "R1-T14-02_allowed_to_start": False,
        "formal_task_completed": False,
    }
    filename = (
        "r0_t15_author_draft_package_validation_result.json"
        if require_author_package
        else "r0_t15_engineering_validation_result.json"
    )
    write_json_atomic(run_dir / filename, result)
    return result


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value
