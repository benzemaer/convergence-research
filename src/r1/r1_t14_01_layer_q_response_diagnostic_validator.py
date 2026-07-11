# ruff: noqa: E501
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r1_t14_01_layer_q_response_diagnostic import CSV_ARTIFACTS, ROOT, TASK_ID


def validate_r1_t14_01_layer_q_response_diagnostic(
    *,
    run_dir: str | Path,
    require_author_package: bool = False,
    require_final_package: bool = False,
) -> dict[str, Any]:
    if require_author_package and require_final_package:
        raise ValueError("author and final package modes are mutually exclusive")
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
        return _finish(
            run_dir,
            errors,
            require_author_package=require_author_package,
            require_final_package=require_final_package,
        )
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
    allowed_classifications = {
        "dominant_bottleneck",
        "material_constraint",
        "low_material_impact",
        "structural_dilution_risk",
        "sample_collapse_risk",
        "unstable_response",
    }
    if any(
        not row.get("classifications")
        or not set(row["classifications"].split("|")).issubset(allowed_classifications)
        for row in response
    ):
        errors.append("layer_response_classification_invalid")
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
        required_registry_fields = {
            "state_line_role",
            "same_parameter_parent_id",
            "diagnostic_metrics",
            "material_advantage",
            "warnings",
            "rejected_alternatives",
        }
        if any(not required_registry_fields.issubset(row) for row in registry):
            errors.append("materialization_request_registry_metadata_incomplete")
        if any(not row.get("diagnostic_metrics") for row in registry):
            errors.append("materialization_request_diagnostic_metrics_empty")
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
    if require_final_package:
        _validate_final_package(run_dir, decision, errors)
    return _finish(
        run_dir,
        errors,
        require_author_package=require_author_package,
        require_final_package=require_final_package,
    )


def _validate_final_package(
    run_dir: Path,
    decision: dict[str, Any],
    errors: list[str],
) -> None:
    package_path = run_dir / "r1_t14_01_result_package.json"
    if not package_path.is_file():
        errors.append("final_result_package_missing")
        return
    package = _load_json(package_path)
    gate = package.get("gate_status", {})
    expected_package = {
        "status": "completed",
        "scientific_review_status": "passed",
        "formal_task_completed": True,
        "downstream_gate_allowed": True,
        "R0_q_vector_materialization_allowed_to_start": True,
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "downstream_gate_scope": "R0-T15_only",
        "superseded": False,
        "independence_attestation": True,
    }
    for key, expected in expected_package.items():
        if package.get(key) != expected:
            errors.append(f"final_package_field_mismatch:{key}")
    expected_gate = {
        "engineering_validator_status": "passed",
        "author_result_analysis_status": "passed",
        "anomaly_resolution_status": "passed",
        "scientific_review_status": "passed",
        "review_phase": "independent_review_complete",
        "independent_review_status": "completed",
        "repository_final_gate_status": "passed",
        "readme_gate_updated": True,
    }
    for key, expected in expected_gate.items():
        if gate.get(key) != expected:
            errors.append(f"final_gate_field_mismatch:{key}")
    if package.get("decision") != "q_vector_materialization_request":
        errors.append("final_package_decision_not_materialization_request")
    if package.get("R0_q_vector_materialization_task_id") != "R0-T15":
        errors.append("final_package_r0_task_not_bound")
    if package.get("R0_q_vector_materialization_request_status") != "approved":
        errors.append("final_package_r0_request_not_approved")
    if package.get("R0_q_vector_materialization_status") != "authorized":
        errors.append("final_package_r0_status_not_authorized")
    decision_path = run_dir / "r1_t14_01_materialization_request.json"
    if not decision_path.is_file():
        errors.append("final_package_materialization_request_missing")
    elif package.get("decision_sha256") != sha256_file(decision_path):
        errors.append("final_package_decision_hash_mismatch")
    if decision.get("scientific_review_status") != "pending":
        errors.append("reviewed_author_decision_bytes_were_mutated")

    _check_package_artifacts(package, errors)
    review = _check_final_review(package, errors)
    _check_final_document(package, "readme", errors)
    _check_final_document(package, "formal_evidence", errors)
    _check_final_document(package, "result_analysis", errors)
    _check_final_document(package, "config", errors)
    _check_final_document(package, "engineering_validation_result", errors)
    _check_final_document(package, "anomaly_scan", errors)
    _check_final_document(package, "decision", errors)
    _check_final_document(package, "diagnostic_summary", errors)
    _check_final_readme_state(package, errors)
    _check_final_evidence_state(package, errors)
    if review and package.get("reviewer_identity") != review.get("reviewer_identity"):
        errors.append("final_package_reviewer_identity_mismatch")


def _check_package_artifacts(package: dict[str, Any], errors: list[str]) -> None:
    for artifact in package.get("primary_result_artifacts", []) + package.get(
        "diagnostic_artifacts", []
    ):
        path_value = artifact.get("path")
        path = ROOT / path_value if path_value else None
        if path is None or not path.is_file():
            errors.append(f"package_artifact_missing:{path_value}")
        elif sha256_file(path) != artifact.get("sha256"):
            errors.append(f"package_artifact_hash_mismatch:{path_value}")


def _check_final_review(package: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    record_path_value = package.get("scientific_review_record_path")
    markdown_path_value = package.get("scientific_review_md_path")
    if not record_path_value or not markdown_path_value:
        errors.append("scientific_review_paths_missing")
        return {}
    record_path = ROOT / record_path_value
    markdown_path = ROOT / markdown_path_value
    if not record_path.is_file():
        errors.append("scientific_review_record_missing")
        return {}
    if not markdown_path.is_file():
        errors.append("scientific_review_markdown_missing")
    elif sha256_file(markdown_path) != package.get("scientific_review_md_sha256"):
        errors.append("scientific_review_markdown_hash_mismatch")
    if sha256_file(record_path) != package.get("scientific_review_record_sha256"):
        errors.append("scientific_review_record_hash_mismatch")
    review = _load_json(record_path)
    summary_path_value = package.get("diagnostic_summary_path")
    if not summary_path_value:
        errors.append("diagnostic_summary_path_missing")
        reviewed_summary_sha256 = None
    else:
        summary_path = ROOT / summary_path_value
        reviewed_summary_sha256 = (
            sha256_file(summary_path) if summary_path.is_file() else None
        )
        if reviewed_summary_sha256 is None:
            errors.append("diagnostic_summary_missing")
        elif package.get("diagnostic_summary_sha256") != reviewed_summary_sha256:
            errors.append("diagnostic_summary_hash_mismatch")
    expected = {
        "reviewer_identity": "benzemaer",
        "reviewer_role": "independent_scientific_reviewer",
        "implementation_actor": "codex",
        "independence_attestation": True,
        "reviewed_code_commit": package.get("code_commit"),
        "reviewed_summary_sha256": reviewed_summary_sha256,
        "reviewed_analysis_sha256": package.get("result_analysis_sha256"),
        "reviewed_config_sha256": package.get("config_sha256"),
        "reviewed_decision_sha256": package.get("decision_sha256"),
        "reviewed_pr_head_commit": package.get("reviewed_pr_head_commit"),
        "scientific_review_status": "passed",
        "downstream_gate_recommendation": True,
    }
    for key, value in expected.items():
        if review.get(key) != value:
            errors.append(f"scientific_review_field_mismatch:{key}")
    if review.get("reviewer_identity") == review.get("implementation_actor"):
        errors.append("scientific_review_not_independent")
    if review.get("blocking_findings") != []:
        errors.append("scientific_review_blocking_findings_not_empty")
    if not review.get("independent_recomputations"):
        errors.append("scientific_review_recomputations_missing")
    if not review.get("alternative_explanations"):
        errors.append("scientific_review_alternative_explanations_missing")
    for field in (
        "baseline_challenger_review",
        "parameter_response_review",
        "anomaly_review",
    ):
        if not review.get(field):
            errors.append(f"scientific_review_field_missing:{field}")
    if str(review.get("review_comment_id")) != "4941866339":
        errors.append("scientific_review_source_comment_mismatch")
    if review.get("review_source") != package.get("scientific_review_source"):
        errors.append("scientific_review_source_url_mismatch")
    return review


def _check_final_document(
    package: dict[str, Any], prefix: str, errors: list[str]
) -> None:
    path_value = package.get(f"{prefix}_path")
    hash_value = package.get(f"{prefix}_sha256")
    if not path_value:
        errors.append(f"{prefix}_path_missing")
        return
    path = ROOT / path_value
    if not path.is_file():
        errors.append(f"{prefix}_missing")
    elif sha256_file(path) != hash_value:
        errors.append(f"{prefix}_hash_mismatch")


def _check_final_readme_state(package: dict[str, Any], errors: list[str]) -> None:
    path_value = package.get("readme_path")
    if not path_value:
        return
    readme_path = ROOT / path_value
    if not readme_path.is_file():
        return
    text = _readme_current_stage_block(readme_path.read_text(encoding="utf-8"), errors)
    markers = (
        "current_stage: R0",
        "current_task: R0-T15 正式 q-vector 物化",
        "next_planned_task: R1-T14-02 层级 q-vector R0 物化接收与正式结构复验",
        "R1-T14-01_decision_status: q_vector_materialization_request",
        "R0_q_vector_materialization_request_status: approved",
        "R0_q_vector_materialization_task_id: R0-T15",
        "R0_q_vector_materialization_allowed_to_start: true",
        "R0_q_vector_materialization_status: authorized",
        "R1-T14-02_status: blocked_pending_R0",
        "R1-T14-02_allowed_to_start: false",
        "R1-T10_allowed_to_start: false",
        "R2_allowed_to_start: false",
    )
    for marker in markers:
        if marker not in text:
            errors.append(f"readme_final_gate_marker_missing:{marker}")


def _readme_current_stage_block(text: str, errors: list[str]) -> str:
    try:
        return text.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
    except IndexError:
        errors.append("readme_current_stage_block_missing")
        return ""


def _check_final_evidence_state(package: dict[str, Any], errors: list[str]) -> None:
    path_value = package.get("formal_evidence_path")
    if not path_value:
        return
    evidence_path = ROOT / path_value
    if not evidence_path.is_file():
        return
    text = evidence_path.read_text(encoding="utf-8")
    markers = (
        "scientific_review_status=passed",
        "reviewer_identity=benzemaer",
        "independence_attestation=true",
        "repository_final_gate_status=passed",
        "downstream_gate_scope=R0-T15_only",
        "R0_q_vector_materialization_allowed_to_start=true",
        "R1-T14-02_allowed_to_start=false",
        "R1-T10_allowed_to_start=false",
        "R2_allowed_to_start=false",
        "formal_task_completed=true",
        "selection_path_not_independently_confirmed=true",
    )
    for marker in markers:
        if marker not in text:
            errors.append(f"evidence_final_gate_marker_missing:{marker}")


def _finish(
    run_dir: Path,
    errors: list[str],
    *,
    require_author_package: bool,
    require_final_package: bool,
) -> dict[str, Any]:
    mode = (
        "final_package"
        if require_final_package
        else "author_package"
        if require_author_package
        else "engineering"
    )
    final_passed = require_final_package and not errors
    result = {
        "task_id": TASK_ID,
        "validation_mode": mode,
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "scientific_review_status": "passed" if final_passed else "pending",
        "independent_review_status": "completed" if final_passed else "not_started",
        "repository_final_gate_status": "passed" if final_passed else "pending",
    }
    if require_final_package:
        package_path = run_dir / "r1_t14_01_result_package.json"
        result["result_package_path"] = _display_path(package_path)
        result["result_package_sha256"] = (
            sha256_file(package_path) if package_path.is_file() else None
        )
    if require_final_package:
        result.update(
            {
                "downstream_gate_scope": "R0-T15_only",
                "R0_q_vector_materialization_allowed_to_start": final_passed,
                "R1-T14-02_allowed_to_start": False,
                "R1-T10_allowed_to_start": False,
                "R2_allowed_to_start": False,
                "selection_path_not_independently_confirmed": True,
                "formal_task_completed": final_passed,
                "downstream_gate_allowed": final_passed,
            }
        )
    name = {
        "engineering": "r1_t14_01_engineering_validation_result.json",
        "author_package": "r1_t14_01_author_draft_package_validation_result.json",
        "final_package": "r1_t14_01_final_gate_package_validation_result.json",
    }[mode]
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


def _display_path(path: Path) -> str:
    try:
        value = path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        value = path.resolve()
    return str(value).replace("\\", "/")
