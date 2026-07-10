from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/governance/r_formal_experiment_governance.v1.json"
PACKAGE_SCHEMA_PATH = (
    ROOT / "schemas/governance/r_formal_experiment_result_package.schema.json"
)
REVIEW_SCHEMA_PATH = (
    ROOT / "schemas/governance/r_formal_experiment_scientific_review.schema.json"
)


class FormalExperimentPackageValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationContext:
    package_path: Path
    mode: str
    root: Path = ROOT


def validate_formal_experiment_package(
    result_package_path: Path,
    *,
    mode: str,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    ctx = ValidationContext(result_package_path, mode, root)
    errors: list[str] = []
    package = _load_json(result_package_path, errors, "result_package")
    config = _load_json(CONFIG_PATH, errors, "governance_config")
    package_schema = _load_json(PACKAGE_SCHEMA_PATH, errors, "package_schema")
    review_schema = _load_json(REVIEW_SCHEMA_PATH, errors, "review_schema")

    _validate_schema(package_schema, package, errors, "result_package_schema")
    _check_common_package(ctx, package, config, errors)
    if mode == "author-draft":
        _check_author_draft(package, errors)
    elif mode == "review-complete":
        _check_review_complete(ctx, package, review_schema, errors)
    elif mode == "final-gate":
        _check_final_gate(ctx, package, review_schema, errors)
    else:
        errors.append(f"unknown_mode:{mode}")

    result = {
        "validator": "r_formal_experiment_package_validator",
        "mode": mode,
        "result_package_path": _display_path(result_package_path, root),
        "result_package_sha256": sha256_file(result_package_path)
        if result_package_path.exists()
        else None,
        "author_package_validator_status": "passed" if not errors else "failed",
        "formal_task_completed": bool(
            mode == "final-gate"
            and not errors
            and package.get("downstream_gate_allowed") is True
        ),
        "downstream_gate_allowed": package.get("downstream_gate_allowed"),
        "errors": errors,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if errors:
        raise FormalExperimentPackageValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_common_package(
    ctx: ValidationContext,
    package: dict[str, Any],
    config: dict[str, Any],
    errors: list[str],
) -> None:
    if package.get("task_class") != "formal_experiment":
        errors.append("task_class_not_formal_experiment")
    if not package.get("primary_result_artifacts"):
        errors.append("primary_result_artifacts_missing")
    if _contains_row_payload(package):
        errors.append("result_package_embeds_row_payload")

    gate = package.get("gate_status", {})
    required_gate = {
        "engineering_validator_status": "passed",
        "result_artifact_status": "passed",
        "author_result_analysis_status": "passed",
    }
    for key, expected in required_gate.items():
        if gate.get(key) != expected:
            errors.append(f"gate_status_mismatch:{key}")
    if package.get("superseded") is True and package.get("downstream_gate_allowed"):
        errors.append("superseded_package_allows_downstream")

    _check_required_artifact_roles(package, config, errors)
    for field in _path_hash_fields(package):
        _check_path_hash(ctx.root, package, field, errors, require_tracked=True)
    for group in ("primary_result_artifacts", "diagnostic_artifacts"):
        for index, artifact in enumerate(package.get(group, [])):
            _check_artifact(ctx.root, artifact, f"{group}[{index}]", errors)

    _check_engineering_validation_result(ctx.root, package, errors)
    _check_analysis(ctx.root, package, config, errors)
    _check_anomaly_scan(ctx.root, package, config, errors)
    _check_formal_evidence(ctx.root, package, errors)


def _check_author_draft(package: dict[str, Any], errors: list[str]) -> None:
    gate = package.get("gate_status", {})
    anomaly_status = gate.get("anomaly_resolution_status")
    if package.get("status") != "author_analysis_complete":
        errors.append("author_draft_status_must_be_author_analysis_complete")
    if gate.get("scientific_review_status") != "pending":
        errors.append("author_draft_scientific_review_not_pending")
    if anomaly_status not in {"passed", "not_applicable", "unresolved"}:
        errors.append("author_draft_invalid_anomaly_resolution_status")
    if (
        anomaly_status == "unresolved"
        and package.get("downstream_gate_allowed") is True
    ):
        errors.append("author_draft_unresolved_anomaly_allows_downstream")
    if package.get("downstream_gate_allowed") is not False:
        errors.append("author_draft_downstream_gate_must_be_false")
    if gate.get("review_phase") != "author_analysis_complete":
        errors.append("author_draft_review_phase_mismatch")
    if gate.get("readme_gate_updated") is True:
        errors.append("author_draft_readme_advanced")


def _check_final_gate(
    ctx: ValidationContext,
    package: dict[str, Any],
    review_schema: dict[str, Any],
    errors: list[str],
) -> None:
    gate = package.get("gate_status", {})
    if package.get("status") != "completed":
        errors.append("final_gate_status_not_completed")
    if gate.get("scientific_review_status") != "passed":
        errors.append("final_gate_scientific_review_not_passed")
    if gate.get("anomaly_resolution_status") not in {"passed", "not_applicable"}:
        errors.append("final_gate_anomaly_not_resolved")
    if package.get("superseded") is not False:
        errors.append("final_gate_superseded_not_false")
    if package.get("downstream_gate_allowed") is not True:
        errors.append("final_gate_downstream_gate_not_true")
    if gate.get("review_phase") != "independent_review_complete":
        errors.append("final_gate_review_phase_mismatch")
    if gate.get("readme_gate_updated") is not True:
        errors.append("final_gate_readme_gate_not_consistent")
    _check_readme_gate(ctx.root, package, errors)

    _check_scientific_review(ctx, package, review_schema, errors)


def _check_review_complete(
    ctx: ValidationContext,
    package: dict[str, Any],
    review_schema: dict[str, Any],
    errors: list[str],
) -> None:
    gate = package.get("gate_status", {})
    if package.get("status") != "author_analysis_complete":
        errors.append("review_complete_status_must_be_author_analysis_complete")
    if gate.get("scientific_review_status") != "passed":
        errors.append("review_complete_scientific_review_not_passed")
    if gate.get("anomaly_resolution_status") not in {"passed", "not_applicable"}:
        errors.append("review_complete_anomaly_not_resolved")
    if package.get("superseded") is not False:
        errors.append("review_complete_superseded_not_false")
    if package.get("downstream_gate_allowed") is not False:
        errors.append("review_complete_downstream_gate_must_be_false")
    if gate.get("review_phase") != "independent_review_complete":
        errors.append("review_complete_review_phase_mismatch")
    if gate.get("readme_gate_updated") is not False:
        errors.append("review_complete_readme_must_not_advance")

    _check_scientific_review(ctx, package, review_schema, errors)


def _check_scientific_review(
    ctx: ValidationContext,
    package: dict[str, Any],
    review_schema: dict[str, Any],
    errors: list[str],
) -> None:
    review_path = package.get("scientific_review_record_path")
    review_sha = package.get("scientific_review_record_sha256")
    review_md_path = package.get("scientific_review_md_path")
    review_md_sha = package.get("scientific_review_md_sha256")
    if not review_path or not review_sha:
        errors.append("final_gate_scientific_review_record_missing")
        return
    if not review_md_path or not review_md_sha:
        errors.append("final_gate_scientific_review_md_missing")
    else:
        _check_path_hash(
            ctx.root,
            package,
            ("scientific_review_md_path", "scientific_review_md_sha256"),
            errors,
            require_tracked=True,
        )
    review_file = _resolve_repo_relative(
        ctx.root, review_path, errors, "scientific_review"
    )
    if review_file is None:
        return
    if not review_file.exists():
        errors.append("final_gate_scientific_review_file_missing")
        return
    if sha256_file(review_file) != review_sha:
        errors.append("scientific_review_hash_mismatch")
    review = _load_json(review_file, errors, "scientific_review")
    _validate_schema(review_schema, review, errors, "scientific_review_schema")
    if review.get("reviewed_code_commit") != package.get("code_commit"):
        errors.append("scientific_review_code_commit_mismatch")
    if review.get("reviewed_analysis_sha256") != package.get("result_analysis_sha256"):
        errors.append("scientific_review_analysis_hash_mismatch")
    if review.get("reviewed_summary_sha256") != package.get(
        "experiment_summary_sha256"
    ):
        errors.append("scientific_review_summary_hash_mismatch")
    if review.get("implementation_actor") != package.get("implementation_actor"):
        errors.append("scientific_review_implementation_actor_mismatch")
    if review.get("reviewer_identity") == package.get("implementation_actor"):
        errors.append("scientific_review_not_independent")
    if review.get("independence_attestation") is not True:
        errors.append("scientific_review_independence_attestation_missing")
    if not review.get("independent_recomputations"):
        errors.append("scientific_review_recomputations_missing")
    if not review.get("alternative_explanations"):
        errors.append("scientific_review_alternative_explanations_missing")
    if review.get("blocking_findings"):
        errors.append("scientific_review_blocking_findings_not_empty")
    if review.get("scientific_review_status") != "passed":
        errors.append("scientific_review_record_status_not_passed")
    if review.get("downstream_gate_recommendation") is not True:
        errors.append("scientific_review_downstream_recommendation_not_true")


def _check_required_artifact_roles(
    package: dict[str, Any], config: dict[str, Any], errors: list[str]
) -> None:
    roles = {
        "experiment_summary": bool(package.get("experiment_summary_path")),
        "primary_results": bool(package.get("primary_result_artifacts")),
        "diagnostic_summary": bool(package.get("diagnostic_artifacts")),
        "anomaly_scan": bool(package.get("anomaly_scan_path")),
        "engineering_validation_result": bool(
            package.get("engineering_validation_result_path")
        ),
        "result_analysis": bool(package.get("result_analysis_path")),
        "formal_evidence": bool(package.get("formal_evidence_path")),
        "scientific_review_json": bool(package.get("scientific_review_record_path")),
        "scientific_review_md": bool(package.get("scientific_review_md_path")),
    }
    phase_required = set(config.get("required_artifact_roles", []))
    if package.get("gate_status", {}).get("scientific_review_status") == "pending":
        phase_required -= {"scientific_review_json", "scientific_review_md"}
    for role in phase_required:
        if not roles.get(role):
            errors.append(f"required_artifact_role_missing:{role}")


def _check_engineering_validation_result(
    root: Path, package: dict[str, Any], errors: list[str]
) -> None:
    path_value = package.get("engineering_validation_result_path")
    if not path_value:
        errors.append("engineering_validation_result_path_missing")
        return
    path = _resolve_repo_relative(root, path_value, errors, "engineering_validation")
    if path is None or not path.exists():
        errors.append("engineering_validation_result_missing")
        return
    result = _load_json(path, errors, "engineering_validation_result")
    status = result.get("validator_status", result.get("status"))
    if status != "passed":
        errors.append("engineering_validation_result_not_passed")
    if result.get("errors") not in (None, []):
        errors.append("engineering_validation_result_has_errors")
    for key in ("task_id", "run_id", "code_commit"):
        if key in result and result.get(key) != package.get(key):
            errors.append(f"engineering_validation_{key}_mismatch")
    gate_status = package.get("gate_status", {}).get("engineering_validator_status")
    if gate_status != status:
        errors.append("engineering_validator_status_not_derived_from_result")


def _check_analysis(
    root: Path,
    package: dict[str, Any],
    config: dict[str, Any],
    errors: list[str],
) -> None:
    path_value = package.get("result_analysis_path")
    if not path_value:
        errors.append("result_analysis_path_missing")
        return
    path = root / path_value
    if not path.exists():
        errors.append("result_analysis_missing")
        return
    text = path.read_text(encoding="utf-8")
    for heading in config.get("required_result_analysis_headings", []):
        if heading not in text:
            errors.append(f"result_analysis_heading_missing:{heading}")
    if "observed_fact" not in text or "research_judgment" not in text:
        errors.append("result_analysis_evidence_type_markers_missing")


def _check_anomaly_scan(
    root: Path,
    package: dict[str, Any],
    config: dict[str, Any],
    errors: list[str],
) -> None:
    path_value = package.get("anomaly_scan_path")
    if not path_value:
        errors.append("anomaly_scan_path_missing")
        return
    path = root / path_value
    if not path.exists():
        errors.append("anomaly_scan_missing")
        return
    scan = _load_json(path, errors, "anomaly_scan")
    if scan.get("task_id") != package.get("task_id"):
        errors.append("anomaly_scan_task_id_mismatch")
    if scan.get("run_id") != package.get("run_id"):
        errors.append("anomaly_scan_run_id_mismatch")
    if scan.get("code_commit") != package.get("code_commit"):
        errors.append("anomaly_scan_code_commit_mismatch")
    checks = scan.get("checks", {})
    registered_paths = _registered_artifact_paths(package)
    blocked_checks: set[str] = set()
    for name in config.get("mandatory_anomaly_checks", []):
        item = checks.get(name)
        if not isinstance(item, dict):
            errors.append(f"anomaly_check_missing:{name}")
            continue
        if item.get("status") not in {"passed", "not_applicable", "blocked"}:
            errors.append(f"anomaly_check_invalid_status:{name}")
        if not item.get("rationale"):
            errors.append(f"anomaly_check_missing_rationale:{name}")
        if "metrics" not in item or "artifact_references" not in item:
            errors.append(f"anomaly_check_missing_traceability:{name}")
        if item.get("status") == "blocked":
            blocked_checks.add(name)
        metrics = item.get("metrics")
        if item.get("status") != "not_applicable" and not metrics:
            errors.append(f"anomaly_check_empty_metrics:{name}")
        references = item.get("artifact_references")
        if not references:
            errors.append(f"anomaly_check_empty_artifact_references:{name}")
        for reference in references or []:
            if reference not in registered_paths:
                errors.append(f"anomaly_check_unknown_artifact_reference:{name}")
    blocking = scan.get("blocking_anomalies", [])
    unresolved = scan.get("unresolved_questions", [])
    gate = package.get("gate_status", {})
    blocking_set = set(blocking if isinstance(blocking, list) else [])
    if blocking_set != blocked_checks:
        errors.append("blocking_anomalies_do_not_match_blocked_checks")
    for name in blocking_set:
        item = checks.get(name, {})
        if item.get("status") != "blocked":
            errors.append(f"blocking_anomaly_not_blocked_check:{name}")
    if scan.get("scan_status") == "passed" and (blocked_checks or unresolved):
        errors.append("anomaly_scan_status_inconsistent")
    if scan.get("scan_status") == "blocked" and not (blocked_checks or unresolved):
        errors.append("anomaly_scan_status_inconsistent")
    if (blocking or unresolved) and package.get("downstream_gate_allowed") is True:
        errors.append("unresolved_or_blocking_anomaly_allows_downstream")
    if blocking and gate.get("anomaly_resolution_status") not in {
        "unresolved",
        "blocked",
    }:
        errors.append("blocking_anomaly_status_not_blocked")


def _check_formal_evidence(
    root: Path, package: dict[str, Any], errors: list[str]
) -> None:
    path_value = package.get("formal_evidence_path")
    if not path_value:
        errors.append("formal_evidence_path_missing")
        return
    path = _resolve_repo_relative(root, path_value, errors, "formal_evidence")
    if path is None or not path.exists():
        errors.append("formal_evidence_missing")
        return
    evidence = _parse_evidence(path)
    gate = package.get("gate_status", {})
    expected = {
        "engineering_validator_status": gate.get("engineering_validator_status"),
        "result_artifact_status": gate.get("result_artifact_status"),
        "author_result_analysis_status": gate.get("author_result_analysis_status"),
        "scientific_review_status": gate.get("scientific_review_status"),
        "anomaly_resolution_status": gate.get("anomaly_resolution_status"),
        "downstream_gate_allowed": str(package.get("downstream_gate_allowed")).lower(),
    }
    for key, value in expected.items():
        if value is not None and evidence.get(key) != value:
            errors.append(f"formal_evidence_gate_mismatch:{key}")
    hash_fields = {
        "result_analysis_sha256": package.get("result_analysis_sha256"),
        "anomaly_scan_sha256": package.get("anomaly_scan_sha256"),
        "engineering_validation_result_sha256": package.get(
            "engineering_validation_result_sha256"
        ),
        "scientific_review_sha256": package.get("scientific_review_record_sha256"),
    }
    for key, value in hash_fields.items():
        if value and evidence.get(key) != value:
            errors.append(f"formal_evidence_hash_mismatch:{key}")


def _check_readme_gate(root: Path, package: dict[str, Any], errors: list[str]) -> None:
    readme_path = package.get("readme_path")
    if not readme_path:
        errors.append("readme_path_missing")
        return
    path = _resolve_repo_relative(root, readme_path, errors, "readme")
    if path is None or not path.exists():
        errors.append("readme_missing")
        return
    text = path.read_text(encoding="utf-8")
    expected = {
        "current_stage": package.get("expected_current_stage"),
        "current_task": package.get("expected_current_task"),
        "next_planned_task": package.get("expected_next_planned_task"),
    }
    for key, value in expected.items():
        if value and f"{key}: {value}" not in text:
            errors.append(f"readme_pointer_mismatch:{key}")
    marker = package.get("expected_downstream_gate_marker")
    if marker and marker not in text:
        errors.append("readme_downstream_gate_marker_missing")


def _registered_artifact_paths(package: dict[str, Any]) -> set[str]:
    paths = {
        package.get("experiment_summary_path"),
        package.get("anomaly_scan_path"),
        package.get("result_analysis_path"),
        package.get("engineering_validation_result_path"),
        package.get("formal_evidence_path"),
        package.get("scientific_review_record_path"),
        package.get("scientific_review_md_path"),
    }
    for group in ("primary_result_artifacts", "diagnostic_artifacts"):
        for artifact in package.get(group, []):
            paths.add(artifact.get("path"))
    return {str(path) for path in paths if path}


def _path_hash_fields(package: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return (
        ("config_path", "config_sha256"),
        ("experiment_summary_path", "experiment_summary_sha256"),
        ("anomaly_scan_path", "anomaly_scan_sha256"),
        ("result_analysis_path", "result_analysis_sha256"),
        (
            "engineering_validation_result_path",
            "engineering_validation_result_sha256",
        ),
        ("formal_evidence_path", "formal_evidence_sha256"),
        ("readme_path", "readme_sha256"),
    )


def _check_path_hash(
    root: Path,
    payload: dict[str, Any],
    field_pair: tuple[str, str],
    errors: list[str],
    *,
    require_tracked: bool = False,
) -> None:
    path_key, hash_key = field_pair
    path_value = payload.get(path_key)
    hash_value = payload.get(hash_key)
    if not path_value or not hash_value:
        errors.append(f"path_or_hash_missing:{path_key}")
        return
    path = _resolve_repo_relative(root, path_value, errors, path_key)
    if path is None:
        return
    if not path.exists():
        errors.append(f"path_missing:{path_key}")
        return
    if sha256_file(path) != hash_value:
        errors.append(f"hash_mismatch:{path_key}")
    if require_tracked and not _is_git_tracked(root, path_value):
        errors.append(f"path_not_git_tracked:{path_key}")


def _check_artifact(
    root: Path,
    artifact: dict[str, Any],
    label: str,
    errors: list[str],
) -> None:
    path_value = artifact.get("path")
    if not path_value:
        errors.append(f"artifact_path_missing:{label}")
        return
    path = _resolve_repo_relative(root, path_value, errors, label)
    if path is None:
        return
    if not path.exists():
        errors.append(f"artifact_missing:{label}")
        return
    if artifact.get("sha256") != sha256_file(path):
        errors.append(f"artifact_hash_mismatch:{label}")
    if "row_count" not in artifact and "record_count" not in artifact:
        errors.append(f"artifact_count_missing:{label}")
    if artifact.get("committed_to_repo") is not True:
        errors.append(f"artifact_not_committed:{label}")
    if not _is_git_tracked(root, path_value):
        errors.append(f"artifact_not_git_tracked:{label}")


def _resolve_repo_relative(
    root: Path, path_value: str, errors: list[str], label: str
) -> Path | None:
    raw = Path(path_value)
    if raw.is_absolute():
        errors.append(f"path_not_repo_relative:{label}")
        return None
    if ".." in raw.parts:
        errors.append(f"path_escapes_repo:{label}")
        return None
    root_resolved = root.resolve()
    path = (root_resolved / raw).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError:
        errors.append(f"path_escapes_repo:{label}")
        return None
    return path


def _is_git_tracked(root: Path, path_value: str) -> bool:
    if not (root / ".git").exists():
        return True
    raw = Path(path_value)
    if raw.is_absolute() or ".." in raw.parts:
        return False
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", raw.as_posix()],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _contains_row_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in {"rows", "row_payload", "embedded_rows"}:
                return True
            if key_lower == "row_payload_embedded" and item is True:
                return True
            if _contains_row_payload(item):
                return True
    if isinstance(value, list):
        return any(_contains_row_payload(item) for item in value)
    return False


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
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("`") or "`:" not in line:
            continue
        key_end = line.find("`:")
        fields[line[1:key_end].strip()] = line[key_end + 2 :].strip().replace("`", "")
    return fields


def _validate_schema(
    schema: dict[str, Any], payload: Any, errors: list[str], label: str
) -> None:
    if not schema or not payload:
        return
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}_invalid:{exc}")


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
