from __future__ import annotations

# ruff: noqa: E501
import csv
import json
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
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
    config_path = ROOT / str(summary.get("config_path", ""))
    config = _load_optional(config_path)
    protocol_version = config.get("protocol_version")
    current_revision = protocol_version in {
        "R1.v0.4.R1-T14-02.v2",
        "R1.v0.4.R1-T14-02.v3",
    }
    expected_review_status = (
        "needs_revision" if protocol_version == "R1.v0.4.R1-T14-02.v3" else "pending"
    )
    if not config_path.is_file() or sha256_file(config_path) != summary.get(
        "config_sha256"
    ):
        errors.append("summary_config_binding")
    if current_revision:
        _validate_revision_binding(config, summary, errors)
    if (
        summary.get("scientific_review_status") != expected_review_status
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
        or row.get("scientific_review_status") != expected_review_status
        or row.get("formal_task_completed") != "false"
        or row.get("selection_path_not_independently_confirmed") != "true"
        or row.get("parent_child_raw_violation_count") != "0"
        or row.get("parent_child_confirmed_violation_count") != "0"
        or row.get("year_level_delta_conflict") != "false"
        or row.get("pooled_security_sign_reversal") != "false"
        for row in decisions
    ):
        errors.append("candidate_decision_boundary")
    if current_revision:
        _validate_revised_science_gates(run_dir, config, decisions, errors)
    if require_author_package:
        package = _load_optional(run_dir / "r1_t14_02_result_package.json")
        if (
            package.get("status") != "author_draft_complete"
            or package.get("scientific_review_status") != expected_review_status
            or package.get("independent_review_status")
            != (
                "needs_revision"
                if expected_review_status == "needs_revision"
                else "not_started"
            )
            or package.get("repository_final_gate_status") != "pending"
            or package.get("R1-T10_allowed_to_start") is not False
            or package.get("formal_task_completed") is not False
            or package.get("selection_path_not_independently_confirmed") is not True
            or (current_revision and package.get("stale_dependency") is not True)
            or (
                current_revision
                and package.get("upstream_binding") != config.get("upstream_binding")
            )
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


def _validate_revision_binding(
    config: dict[str, Any], summary: dict[str, Any], errors: list[str]
) -> None:
    upstream = config.get("upstream_binding", {})
    if summary.get("upstream_binding") != upstream:
        errors.append("summary_upstream_binding_mismatch")
    expected = {
        "exact_head_commit": "faea7a957b84b0bd0e327d1af945c00c967f6ecb",
        "merge_commit": "09fb86510dc021f031c5f646777c5202013f2e86",
        "result_package_sha256": (
            "aaea43c420289d95a384b49ce045f69045007ba6a5ac669079d6d3f055d72ac2"
        ),
        "handoff_manifest_sha256": (
            "438d2f09ee7a853547a037521ba4ca133bd18bf1fa5dfef91f97db5f670393c3"
        ),
        "artifact_manifest_sha256": (
            "664b6d4558978806db80912aa5e544e0c81824b188a5ea71fece8e20507a8c51"
        ),
        "candidate_registry_sha256": (
            "02fdaf1b94780ef42115a9109ae9f1fd6b90a6e019925a5067ad1bac96d4944f"
        ),
        "external_review_sha256": (
            "28062c827c54b35bdf15bf2ea881866da097c0ee923d956f87538172cc39722a"
        ),
        "final_gate_validation_sha256": (
            "2e68d0fab0af768dc0b3648d183c34d711645befe4b0ae81f66e5b00f9808aa1"
        ),
        "goal_internal_continuation_gate_status": ("passed_after_repository_merge"),
        "goal_internal_t14_02_authorized": True,
        "repository_t14_02_gate_passed": True,
        "current_dependency_verified": True,
        "stale_dependency": True,
    }
    for key, value in expected.items():
        if upstream.get(key) != value:
            errors.append(f"revised_upstream_binding:{key}")
    is_v3 = config.get("protocol_version") == "R1.v0.4.R1-T14-02.v3"
    if is_v3 and (
        upstream.get("current_dependency_stale") is not False
        or upstream.get("superseded_run_dependency_stale") is not True
        or upstream.get("stale_dependency_scope")
        != "superseded_runs_only_current_dependency_verified"
    ):
        errors.append("stale_dependency_scope_ambiguous")
    superseded = config.get("superseded_run", {})
    supersession_path = ROOT / str(superseded.get("supersession_path", ""))
    expected_superseded_run = (
        "R1-T14-02-20260711T0900Z" if is_v3 else "R1-T14-02-20260710T2340Z"
    )
    if (
        superseded.get("run_id") != expected_superseded_run
        or not supersession_path.is_file()
        or sha256_file(supersession_path) != superseded.get("supersession_sha256")
    ):
        errors.append("superseded_run_binding")
    elif _load_optional(supersession_path).get("status") != "superseded":
        errors.append("superseded_run_status")
    if is_v3:
        review_path = ROOT / str(superseded.get("external_review_path", ""))
        review = _load_optional(review_path)
        if (
            not review_path.is_file()
            or sha256_file(review_path) != superseded.get("external_review_sha256")
            or review.get("review_comment_id") != 4944536998
            or review.get("external_review_status") != "needs_revision"
        ):
            errors.append("superseded_external_review_binding")
    if config.get("null_model", {}).get("reuse_prior_null") is not False:
        errors.append("prior_null_reuse_not_disabled")


def _validate_revised_science_gates(
    run_dir: Path,
    config: dict[str, Any],
    decisions: list[dict[str, str]],
    errors: list[str],
) -> None:
    dominance = _csv_rows(run_dir / "r1_t14_02_complexity_dominance_matrix.csv")
    expected_envelope_sha = config["diagnostic_reconciliation_inputs"][
        "t14_01_robust_envelope"
    ]["sha256"]
    if len(dominance) != 8 or any(
        row.get("robust_envelope_source_sha256") != expected_envelope_sha
        or row.get("robust_envelope_source_policy")
        != "R1-T14-01_scope_specific_max_LOYO_MAD_fallback"
        or (
            row.get("material_improvement") == "false"
            and (
                row.get("complexity_not_justified") != "true"
                or row.get("prefer_shared_q") != "true"
            )
        )
        for row in dominance
    ):
        errors.append("scope_specific_robust_envelope_contract")
    v_neighbors = [
        row
        for row in dominance
        if row.get("request_role") == "immediate_neighbor"
        and row.get("state_line") == "S_PCVT"
        and abs(float(row.get("qV", "nan")) - 0.25) < 1e-12
    ]
    if len(v_neighbors) != 2 or any(
        row.get("improvement_beyond_stability_envelope") != "false"
        or row.get("complexity_not_justified") != "true"
        or row.get("prefer_shared_q") != "true"
        or row.get("dominance_status") != "stability_envelope_equivalent"
        for row in v_neighbors
    ):
        errors.append("v_neighbor_robust_envelope_classification")

    existence = _csv_rows(run_dir / "r1_t14_02_existence_profile.csv")
    confirmed_counts = {
        (row.get("formal_vector_id"), row.get("state_line")): int(
            row["state_true_day_count"]
        )
        for row in existence
        if row.get("analysis_level") == "confirmed"
    }
    registry = _csv_rows(run_dir / "r1_t14_02_candidate_registry.csv")
    baseline_by_window = {
        row["W"]: row["formal_vector_id"]
        for row in registry
        if row.get("baseline_reuse") == "true"
    }
    v_decisions = [row for row in decisions if row.get("state_line") == "S_PCVT"]
    for row in v_decisions:
        vector_id = row["formal_vector_id"]
        baseline_id = baseline_by_window.get(row["W"])
        candidate_ratio_from_source = _safe_ratio(
            confirmed_counts.get((vector_id, "S_PCVT")),
            confirmed_counts.get((baseline_id, "S_PCT")),
        )
        baseline_ratio_from_source = _safe_ratio(
            confirmed_counts.get((baseline_id, "S_PCVT")),
            confirmed_counts.get((baseline_id, "S_PCT")),
        )
        candidate_ratio = float(row["v_candidate_pcvt_pct_ratio"])
        baseline_ratio = float(row["v_baseline_pcvt_pct_ratio"])
        retained = float(row["v_selectivity_retained"])
        expected = (1 - candidate_ratio) / (1 - baseline_ratio)
        if (
            row.get("v_ratio_scope") != "confirmed_state_days"
            or candidate_ratio_from_source is None
            or baseline_ratio_from_source is None
            or abs(candidate_ratio - candidate_ratio_from_source) > 1e-15
            or abs(baseline_ratio - baseline_ratio_from_source) > 1e-15
            or abs(retained - expected) > 1e-15
            or row.get("v_candidate_ratio_lt_one") != "true"
            or row.get("v_nested_formal_pass") != "true"
            or row.get("v_selectivity_guard_pass") != "true"
        ):
            errors.append("v_selectivity_guard_contract")
            break
    v_centers = [row for row in v_decisions if row.get("request_role") == "center"]
    if len(v_centers) != 2 or any(
        float(row["security_negative_delta_share"]) > 0
        and (
            row.get("security_heterogeneity_warning") != "true"
            or "V_security_negative_delta_share_material"
            not in row.get("candidate_warning_codes", "")
        )
        for row in v_centers
    ):
        errors.append("v_security_heterogeneity_warning_missing")

    denominator_path = run_dir / "r1_t14_02_denominator_reconciliation.csv"
    denominator = _csv_rows(denominator_path)
    if not denominator_path.is_file() or len(denominator) != 10:
        errors.append("denominator_reconciliation_missing_or_incomplete")
        return
    for row in denominator:
        if (
            sum(
                int(row[key])
                for key in ("t14_02_n11", "t14_02_n10", "t14_02_n01", "t14_02_n00")
            )
            != int(row["t14_02_N"])
            or row.get("t14_02_vs_r1_t06_parent_true_cell_mismatch_count") != "0"
            or int(row["t14_02_vs_r1_t06_parent_false_expansion_count"]) < 0
            or row.get("t14_02_vs_r1_t06_baseline_reconciliation_status") != "passed"
            or row.get("affected_structural_gate_flip") != "false"
        ):
            errors.append("denominator_reconciliation_contract")
            break


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


def _safe_ratio(left: int | None, right: int | None) -> float | None:
    if left is None or right in (None, 0):
        return None
    return left / right


def _row_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return max(sum(1 for _ in handle) - 1, 0)
