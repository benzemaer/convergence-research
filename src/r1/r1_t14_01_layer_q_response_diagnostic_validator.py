# ruff: noqa: E501
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r1_t14_01_layer_q_response_diagnostic import CSV_ARTIFACTS, ROOT, TASK_ID


def validate_r1_t14_01_layer_q_response_diagnostic(
    *, run_dir: str | Path, require_author_package: bool = False
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    errors: list[str] = []
    required = [
        *CSV_ARTIFACTS,
        "r1_t14_01_anomaly_scan.json",
        "r1_t14_01_diagnostic_summary.json",
    ]
    decision_candidates = [
        run_dir / "r1_t14_01_materialization_request.json",
        run_dir / "r1_t14_01_no_candidate_decision.json",
    ]
    existing_decisions = [path for path in decision_candidates if path.is_file()]
    if len(existing_decisions) != 1:
        errors.append("exactly_one_decision_artifact_required")
    for name in required:
        if not (run_dir / name).is_file():
            errors.append(f"missing_artifact:{name}")
    if errors:
        return _finish(run_dir, errors, require_author_package)
    grid = _read_csv(run_dir / "r1_t14_01_grid_registry.csv")
    state = _read_csv(run_dir / "r1_t14_01_state_profile.csv")
    response = _read_csv(run_dir / "r1_t14_01_layer_response_profile.csv")
    reconciliation = _read_csv(run_dir / "r1_t14_01_upstream_reconciliation.csv")
    anomaly = _load_json(run_dir / "r1_t14_01_anomaly_scan.json")
    summary = _load_json(run_dir / "r1_t14_01_diagnostic_summary.json")
    decision = _load_json(existing_decisions[0])
    if len(grid) != 34 or len({row["candidate_q_vector_id"] for row in grid}) != 34:
        errors.append("grid_cardinality_not_34")
    by_w = {
        window: sum(int(row["W"]) == window for row in grid) for window in (120, 250)
    }
    if by_w != {120: 17, 250: 17}:
        errors.append("grid_per_W_cardinality_not_17")
    if len(state) != 136:
        errors.append("state_profile_cardinality_not_136")
    if len(response) != 56:
        errors.append("layer_response_cardinality_not_56")
    if any(int(row["mismatch_count"]) != 0 for row in reconciliation):
        errors.append("baseline_reconciliation_mismatch")
    if anomaly.get("status") != "passed" or anomaly.get("blocking_findings"):
        errors.append("anomaly_scan_not_passed")
    if (
        summary.get("task_id") != TASK_ID
        or summary.get("scientific_review_status") != "pending"
    ):
        errors.append("summary_governance_invalid")
    if (
        decision.get("scientific_review_status") != "pending"
        or decision.get("independence_attestation") is not False
    ):
        errors.append("decision_independent_review_boundary_invalid")
    if decision.get("decision") == "q_vector_materialization_request":
        registry = decision.get("frozen_registry", [])
        if not registry or decision.get("center_count", 0) < 1:
            errors.append("materialization_request_registry_empty")
        if sum(row["request_role"] != "baseline_reference" for row in registry) > 10:
            errors.append("materialization_request_nonbaseline_limit_exceeded")
    if require_author_package:
        package_path = run_dir / "r1_t14_01_result_package.json"
        if not package_path.is_file():
            errors.append("author_result_package_missing")
        else:
            package = _load_json(package_path)
            gate = package.get("gate_status", {})
            if (
                package.get("scientific_review_status") != "pending"
                or package.get("formal_task_completed") is not False
            ):
                errors.append("author_package_repository_gate_boundary_invalid")
            if (
                gate.get("engineering_validator_status") != "passed"
                or gate.get("author_result_analysis_status") != "passed"
            ):
                errors.append("author_package_internal_prerequisites_invalid")
            for artifact in package.get("primary_result_artifacts", []) + package.get(
                "diagnostic_artifacts", []
            ):
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
        "scientific_review_status": "pending",
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
    }
    name = (
        "r1_t14_01_author_draft_package_validation_result.json"
        if require_author_package
        else "r1_t14_01_engineering_validation_result.json"
    )
    write_json_atomic(run_dir / name, result)
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
