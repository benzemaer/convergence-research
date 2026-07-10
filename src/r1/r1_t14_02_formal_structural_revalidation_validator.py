from __future__ import annotations

# ruff: noqa: E501
import csv
import json
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

TASK_ID = "R1-T14-02"
REQUIRED = {
    "r1_t14_02_candidate_registry.csv": 10,
    "r1_t14_02_r0_lineage_reconciliation.csv": 12,
    "r1_t14_02_existence_profile.csv": 24,
    "r1_t14_02_intralayer_profile.csv": 40,
    "r1_t14_02_identity_overlap.csv": 8,
    "r1_t14_02_interval_profile.csv": 12,
    "r1_t14_02_year_profile.csv": 132,
    "r1_t14_02_null_results.csv": 30,
    "r1_t14_02_family_max_statistic.csv": 50000,
    "r1_t14_02_multiplicity_results.csv": 30,
    "r1_t14_02_neighborhood_profile.csv": 4,
    "r1_t14_02_complexity_dominance_matrix.csv": 8,
    "r1_t14_02_candidate_decision_matrix.csv": 8,
}


def validate_r1_t14_02_formal_structural_revalidation(
    *, run_dir: str | Path, require_author_package: bool = False
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    errors: list[str] = []
    for name, expected in REQUIRED.items():
        path = run_dir / name
        if not path.is_file():
            errors.append(f"missing:{name}")
        elif _row_count(path) != expected:
            errors.append(f"row_count:{name}:{_row_count(path)}!={expected}")
    for name in (
        "r1_t14_02_leave_one_year_out.csv",
        "r1_t14_02_interlayer_profile.csv",
        "r1_t14_02_null_replicates_manifest.json",
        "r1_t14_02_anomaly_scan.json",
        "r1_t14_02_diagnostic_summary.json",
        "r1_t14_02_experiment_summary.json",
    ):
        if not (run_dir / name).is_file():
            errors.append(f"missing:{name}")
    summary = _load_optional(run_dir / "r1_t14_02_experiment_summary.json")
    anomaly = _load_optional(run_dir / "r1_t14_02_anomaly_scan.json")
    manifest = _load_optional(run_dir / "r1_t14_02_null_replicates_manifest.json")
    if summary.get("task_id") != TASK_ID or summary.get("N_perm") != 10000:
        errors.append("summary_identity_or_N_perm")
    if (
        summary.get("scientific_review_status") != "pending"
        or summary.get("formal_task_completed") is not False
    ):
        errors.append("summary_author_boundary")
    if anomaly.get("status") != "passed" or anomaly.get("blocking_findings"):
        errors.append("anomaly_not_passed")
    if (
        manifest.get("N_perm") != 10000
        or manifest.get("family_count") != 5
        or manifest.get("family_max_row_count") != 50000
    ):
        errors.append("replicate_manifest_contract")
    registry = _csv_rows(run_dir / "r1_t14_02_candidate_registry.csv")
    if (
        len({row.get("formal_vector_id") for row in registry}) != 10
        or sum(row.get("baseline_reuse") == "true" for row in registry) != 2
    ):
        errors.append("registry_not_exact")
    reconciliation = _csv_rows(run_dir / "r1_t14_02_r0_lineage_reconciliation.csv")
    if any(
        row.get("mismatch_count") != "0" or row.get("reconciliation_status") != "passed"
        for row in reconciliation
    ):
        errors.append("r0_reconciliation_mismatch")
    multiplicity = _csv_rows(run_dir / "r1_t14_02_multiplicity_results.csv")
    if {row.get("family_id") for row in multiplicity} != {
        "F1_GLOBAL_PCT",
        "F2_GLOBAL_PCVT",
        "F3_C_GIVEN_P",
        "F4_T_GIVEN_PC",
        "F5_V_GIVEN_PCT",
    }:
        errors.append("multiplicity_family_mismatch")
    for row in multiplicity:
        if (
            row.get("N_perm") != "10000"
            or row.get("selection_path_not_independently_confirmed") != "true"
        ):
            errors.append("multiplicity_row_contract")
            break
        p_value = float(row["family_adjusted_p"])
        expected = (int(row["n_family_extreme"]) + 1) / 10001
        if abs(p_value - expected) > 1e-15:
            errors.append("multiplicity_formula_mismatch")
            break
    decisions = _csv_rows(run_dir / "r1_t14_02_candidate_decision_matrix.csv")
    allowed = {
        "formal_structure_supported",
        "formal_structure_supported_with_warning",
        "review_only",
        "do_not_advance",
        "blocked_return_to_R0",
    }
    if any(
        row.get("candidate_status") not in allowed
        or row.get("scientific_review_status") != "pending"
        or row.get("formal_task_completed") != "false"
        or row.get("selection_path_not_independently_confirmed") != "true"
        for row in decisions
    ):
        errors.append("candidate_decision_boundary")
    if require_author_package:
        package = _load_optional(run_dir / "r1_t14_02_result_package.json")
        if (
            package.get("status") != "author_draft_complete"
            or package.get("scientific_review_status") != "pending"
            or package.get("independent_review_status") != "not_started"
            or package.get("repository_final_gate_status") != "pending"
            or package.get("R1-T10_allowed_to_start") is not False
            or package.get("formal_task_completed") is not False
            or package.get("selection_path_not_independently_confirmed") is not True
        ):
            errors.append("author_package_boundary")
        for artifact in package.get("committed_artifacts", []):
            path = Path(artifact.get("path", ""))
            if not path.is_absolute():
                path = Path(__file__).resolve().parents[2] / path
            if not path.is_file() or sha256_file(path) != artifact.get("sha256"):
                errors.append(f"author_package_hash:{artifact.get('path')}")
    result = {
        "task_id": TASK_ID,
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
    }
    write_json_atomic(
        run_dir
        / (
            "r1_t14_02_author_draft_package_validation_result.json"
            if require_author_package
            else "r1_t14_02_engineering_validation_result.json"
        ),
        result,
    )
    return result


def _load_optional(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _row_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)
