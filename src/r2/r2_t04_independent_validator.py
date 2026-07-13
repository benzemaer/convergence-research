from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from src.common.canonical_io import canonical_json_sha256

ROOT = Path(__file__).resolve().parents[2]
T03_RUN = "data/generated/r2/r2_t03/R2-T03-PROMOTED-20260713T050903Z"
RUN_ID = "R2-T04-20260713T120000Z"
DECISION_VALIDATION_MODE = "explicit_user_override_over_hard_gate_eligible_candidates"
FORBIDDEN_FIELDS = {
    "backtest",
    "future_return",
    "future_path",
    "future_direction",
    "future_volatility",
    "trading_efficacy",
    "winner",
    "global_optimum",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_text(commit: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8")


def _git_rows(commit: str, path: str) -> list[dict[str, str]]:
    return list(csv.DictReader(_git_text(commit, path).splitlines()))


def _number(value: Any) -> float | None:
    if value in (None, "", "null", "None"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _threshold(rule: str) -> float | None:
    match = re.search(r"(?:>=|<=|==|=|>|<)\s*([0-9]+(?:\.[0-9]+)?)", rule)
    return float(match.group(1)) if match else None


def _operator(value: float | None, operator: str, threshold: float | None) -> bool:
    if value is None or threshold is None:
        return False
    return {
        ">=": value >= threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        "<": value < threshold,
        "==": value == threshold,
        "=": value == threshold,
    }.get(operator, False)


def _without_hash(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _forbidden(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_FIELDS:
                found.append(f"forbidden_output_field:{path}.{key}")
            found.extend(_forbidden(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_forbidden(item, f"{path}[{index}]"))
    return found


def _source_binding_paths(binding: dict[str, Any]) -> dict[str, str]:
    return {
        item["path"]: item["committed_byte_sha256"]
        for item in binding.get("source_bindings", [])
        if "path" in item and "committed_byte_sha256" in item
    }


def _schema_check(
    errors: list[str], output_dir: Path, filename: str, schema_name: str
) -> None:
    try:
        value = _json(output_dir / filename)
        schema = _json(ROOT / "schemas/r2" / schema_name)
        validate(value, schema)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        errors.append(f"schema_validation:{filename}:{exc}")


def validate_independently(output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    gate = _rows(output_dir / "r2_t04_hard_gate_report.csv")
    cells = _rows(output_dir / "r2_t04_cell_gate_summary.csv")
    objectives = _rows(output_dir / "r2_t04_pareto_objective_registry.csv")
    pareto = _rows(output_dir / "r2_t04_pareto_complexity_comparison.csv")
    recommendation = json.loads(
        (output_dir / "r2_t04_automatic_recommendation.json").read_text(
            encoding="utf-8"
        )
    )
    template = json.loads(
        (output_dir / "r2_t04_user_decision_template.json").read_text(encoding="utf-8")
    )
    schema_pairs = {
        "r2_t04_input_binding.json": "r2_t04_input_binding.schema.json",
        "r2_t04_phase_a_validation.json": "r2_t04_phase_a_validation.schema.json",
        "r2_t04_automatic_recommendation.json": (
            "r2_t04_automatic_recommendation.schema.json"
        ),
        "r2_t04_user_decision_template.json": (
            "r2_t04_user_decision_template.schema.json"
        ),
        "r2_t04_experiment_summary.json": "r2_t04_experiment_summary.schema.json",
    }
    for filename, schema_name in schema_pairs.items():
        try:
            value = json.loads((output_dir / filename).read_text(encoding="utf-8"))
            schema = json.loads(
                (ROOT / "schemas/r2" / schema_name).read_text(encoding="utf-8")
            )
            validate(value, schema)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            errors.append(f"schema_validation:{filename}:{exc}")
    if len(cells) != 72 or len({row["candidate_cell_id"] for row in cells}) != 72:
        errors.append("cell_count_or_duplicate")
    if len(pareto) != 72:
        errors.append("pareto_row_count")
    if not objectives or any(
        row.get("direction") not in {"min", "max"} for row in objectives
    ):
        errors.append("objective_registry_invalid")
    if any(
        row.get("status") not in {"passed", "failed", "failed_missing_evidence"}
        for row in gate
    ):
        errors.append("gate_status_vocabulary")
    for row in cells:
        expected = "passed" if int(row["failed_gate_count"]) == 0 else "failed"
        if row["hard_gate_status"] != expected:
            errors.append(f"cell_gate_reduction:{row['candidate_cell_id']}")
    if recommendation.get(
        "status"
    ) != "awaiting_user_decision" or not recommendation.get("user_decision_required"):
        errors.append("recommendation_not_pending")
    if template.get("user_decision_status") != "pending" or template.get(
        "formal_task_completed"
    ):
        errors.append("user_decision_template_open")
    if any(
        key in recommendation
        for key in ("selected_candidate_cell_id", "freeze_decision", "freeze_plan")
    ):
        errors.append("forbidden_decision_field")
    return {
        "task_id": "R2-T04",
        "phase": "A",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "independently_recomputed": [
            "cell_count",
            "gate_status_reduction",
            "pareto_row_count",
            "recommendation_pending",
            "user_decision_pending",
        ],
        "production_oracle_imported": False,
    }


def validate_phase_b(
    output_dir: Path, *, author_stage_preflight: bool = False
) -> dict[str, Any]:
    """Independently validate the Phase B user decision and freeze package.

    This routine deliberately reads the committed T02/T03 registries itself and
    does not import the Phase B production runner or its recommendation logic.
    """
    errors: list[str] = []
    required = [
        "r2_t04_input_binding.json",
        "r2_t04_phase_a_review_resolution.json",
        "r2_t04_user_decision_input.json",
        "r2_t04_user_decision_record.json",
        "r2_t04_selected_cell_gate_revalidation.csv",
        "r2_t04_selected_cell_gate_revalidation.json",
        "r2_t04_freeze_decision.json",
        "r2_t04_freeze_plan_manifest.json",
        "r2_t04_anomaly_scan.json",
        "r2_t04_result_package.json",
        "r2_t04_author_stage_scientific_review.json",
        "r2_t04_repository_final_gate.json",
    ]
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        return {
            "task_id": "R2-T04",
            "phase": "B",
            "status": "failed",
            "errors": [f"missing:{name}" for name in missing],
            "independently_recomputed": [],
            "production_oracle_imported": False,
            "pareto_recommendation_recomputed": False,
            "pareto_recommendation_used_for_final_decision": False,
            "decision_validation_mode": DECISION_VALIDATION_MODE,
        }

    try:
        binding = _json(output_dir / "r2_t04_input_binding.json")
        resolution = _json(output_dir / "r2_t04_phase_a_review_resolution.json")
        decision_input = _json(output_dir / "r2_t04_user_decision_input.json")
        decision = _json(output_dir / "r2_t04_user_decision_record.json")
        gate_revalidation = _rows(
            output_dir / "r2_t04_selected_cell_gate_revalidation.csv"
        )
        gate_summary = _json(output_dir / "r2_t04_selected_cell_gate_revalidation.json")
        freeze_decision = _json(output_dir / "r2_t04_freeze_decision.json")
        freeze_plan = _json(output_dir / "r2_t04_freeze_plan_manifest.json")
        anomaly = _json(output_dir / "r2_t04_anomaly_scan.json")
        package = _json(output_dir / "r2_t04_result_package.json")
        author_review = _json(output_dir / "r2_t04_author_stage_scientific_review.json")
        repository_gate = _json(output_dir / "r2_t04_repository_final_gate.json")
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        return {
            "task_id": "R2-T04",
            "phase": "B",
            "status": "failed",
            "errors": [f"read_error:{exc}"],
            "independently_recomputed": [],
            "production_oracle_imported": False,
            "pareto_recommendation_recomputed": False,
            "pareto_recommendation_used_for_final_decision": False,
            "decision_validation_mode": DECISION_VALIDATION_MODE,
        }

    _schema_check(
        errors,
        output_dir,
        "r2_t04_user_decision_input.json",
        "r2_t04_user_decision_input.schema.json",
    )
    schema_pairs = {
        "r2_t04_phase_a_review_resolution.json": (
            "r2_t04_phase_a_review_resolution.schema.json"
        ),
        "r2_t04_user_decision_record.json": "r2_t04_user_decision_record.schema.json",
        "r2_t04_freeze_decision.json": "r2_t04_freeze_decision.schema.json",
        "r2_t04_freeze_plan_manifest.json": "r2_t04_freeze_plan_manifest.schema.json",
        "r2_t04_anomaly_scan.json": "r2_t04_anomaly_scan.schema.json",
        "r2_t04_result_package.json": "r2_t04_result_package.schema.json",
        "r2_t04_author_stage_scientific_review.json": (
            "r2_t04_author_stage_scientific_review.schema.json"
        ),
        "r2_t04_repository_final_gate.json": "r2_t04_repository_final_gate.schema.json",
        "r2_t04_phase_b_independent_validation.json": (
            "r2_t04_phase_b_independent_validation.schema.json"
        ),
    }
    for filename, schema_name in schema_pairs.items():
        if (output_dir / filename).is_file():
            _schema_check(errors, output_dir, filename, schema_name)

    if binding.get("task_id") != "R2-T04" or binding.get("phase") != "A":
        errors.append("phase_a_binding_invalid")
    commit = binding.get("execution_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        errors.append("execution_commit_invalid")
        commit = ""
    if output_dir.name != RUN_ID:
        errors.append("run_id_mismatch")

    # Independent source reads: use the immutable paths in the Phase A binding.
    source_paths = _source_binding_paths(binding)
    gate_path = next(
        (
            path
            for path in source_paths
            if path.endswith("r2_t02_hard_gate_registry.csv")
        ),
        "",
    )
    runtime_path = next(
        (
            path
            for path in source_paths
            if path.endswith("r2_t03_runtime_gate_results.csv")
        ),
        "",
    )
    cell_path = next(
        (
            path
            for path in source_paths
            if path.endswith("r2_t02_t03_cell_registry.csv")
        ),
        "",
    )
    execution_path = next(
        (
            path
            for path in source_paths
            if path.endswith("r2_t03_cell_execution_registry.csv")
        ),
        "",
    )
    if not all((gate_path, runtime_path, cell_path, execution_path, commit)):
        errors.append("immutable_source_binding_incomplete")
        gates = runtime = cells = execution = []
    else:
        try:
            gates = _git_rows(commit, gate_path)
            runtime = _git_rows(commit, runtime_path)
            cells = _git_rows(commit, cell_path)
            execution = _git_rows(commit, execution_path)
        except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
            errors.append(f"committed_source_read:{exc}")
            gates = runtime = cells = execution = []

    units = decision_input.get("decision_units", [])
    unit_names = {unit.get("decision_unit") for unit in units}
    expected_units = {
        "S_PCT×W120",
        "S_PCT×W250",
        "S_PCVT×W120",
        "S_PCVT×W250",
    }
    if len(units) != 4 or unit_names != expected_units:
        errors.append("decision_units_incomplete_or_duplicate")
    if decision_input.get("decision_authority") != "user_explicit_instruction":
        errors.append("decision_authority_invalid")
    if (
        decision_input.get("reviewer_identity") != "Jianfeng Xie"
        or decision_input.get("github_identity") != "benzemaer"
    ):
        errors.append("reviewer_identity_invalid")
    if (
        decision_input.get("decision_goal")
        != "interpretable_freeze_not_global_parameter_optimum"
    ):
        errors.append("decision_goal_invalid")
    if decision_input.get("automatic_recommendation_override") is not True:
        errors.append("explicit_override_missing")
    if decision_input.get("parameter_search_closed") is not True:
        errors.append("parameter_search_not_closed")
    if (
        decision_input.get("interaction_sidecar_requested") is not False
        or decision_input.get("T25_V30_scan_requested") is not False
    ):
        errors.append("forbidden_interaction_scan_requested")
    if (
        decision_input.get("run_id") != RUN_ID
        or decision_input.get("task_id") != "R2-T04"
    ):
        errors.append("decision_input_identity_invalid")
    if decision_input.get("decision_input_hash") != canonical_json_sha256(
        _without_hash(decision_input, "decision_input_hash")
    ):
        errors.append("decision_input_hash_mismatch")

    expected_primary = {
        "S_PCT×W120": "r2_s_pct_w120_qt25_primary__d2__g1",
        "S_PCVT×W120": "r2_s_pcvt_w120_qv30_primary__d2__g1",
    }
    expected_shared = {
        "S_PCT×W120": "r2_s_pct_w120_q20_shared__d2__g1",
        "S_PCVT×W120": "r2_s_pcvt_w120_q20_shared__d2__g1",
    }
    selected_ids = []
    strict_ids = []
    for unit in units:
        name = unit.get("decision_unit")
        if name in expected_primary:
            if unit.get("user_disposition") != "selected":
                errors.append(f"selected_disposition_invalid:{name}")
            if unit.get("selected_candidate_cell_id") != expected_primary[name]:
                errors.append(f"selected_cell_invalid:{name}")
            if unit.get("paired_shared_candidate") != expected_shared[name]:
                errors.append(f"strict_core_pair_invalid:{name}")
            if (
                unit.get("primary_disposition") != "selected"
                or unit.get("shared_disposition") != "retain_as_strict_core_only"
            ):
                errors.append(f"disposition_vocabulary_invalid:{name}")
            if unit.get("strict_core_enabled") is not True:
                errors.append(f"strict_core_not_enabled:{name}")
            selected_ids.append(unit.get("selected_candidate_cell_id"))
            strict_ids.append(unit.get("paired_shared_candidate"))
            expected_warning_sets = {
                "S_PCT×W120": {
                    "affected_lift_deterioration_vs_baseline",
                    "layer_q_complexity_added",
                    "same_sample_formal_revalidation_only",
                    "selection_path_not_independently_confirmed",
                },
                "S_PCVT×W120": {
                    "V_security_negative_delta_share_material",
                    "V_selectivity_reduced_but_guard_passed",
                    "layer_q_complexity_added",
                    "same_sample_formal_revalidation_only",
                    "selection_path_not_independently_confirmed",
                },
            }
            if set(unit.get("accepted_warnings", [])) != expected_warning_sets[name]:
                errors.append(f"warning_loss_or_drift:{name}")
        elif name in {"S_PCT×W250", "S_PCVT×W250"}:
            if (
                unit.get("user_disposition") != "reject_pair"
                or unit.get("pair_disposition") != "reject_pair"
            ):
                errors.append(f"W250_pair_not_rejected:{name}")
            if (
                unit.get("primary_disposition") != "rejected"
                or unit.get("shared_disposition") != "rejected"
            ):
                errors.append(f"rejected_vocabulary_invalid:{name}")
            if unit.get("selected_candidate_cell_id") is not None:
                errors.append(f"rejected_pair_selected:{name}")
        if unit.get("override") is not True or not unit.get("override_justification"):
            errors.append(f"override_reason_missing:{name}")

    if len(selected_ids) != 2 or len(strict_ids) != 2:
        errors.append("selected_or_strict_core_count")
    selected_all = [item for item in selected_ids + strict_ids if item]
    cell_by_id = {row.get("candidate_cell_id"): row for row in cells}
    execution_by_id = {row.get("candidate_cell_id"): row for row in execution}
    for cell_id in selected_all:
        row = cell_by_id.get(cell_id)
        run_row = execution_by_id.get(cell_id)
        if row is None:
            errors.append(f"cell_not_in_t02_registry:{cell_id}")
            continue
        if run_row is None or run_row.get("status") != "completed":
            errors.append(f"cell_not_completed_in_t03:{cell_id}")
        if row.get("d") != "2" or row.get("g") != "1":
            errors.append(f"d_g_drift:{cell_id}")
        expected_role = (
            "primary" if cell_id in selected_ids else "strict_core_reference"
        )
        if row.get("candidate_role") != expected_role:
            errors.append(f"candidate_role_invalid:{cell_id}")
        if row.get("W") != "120":
            errors.append(f"non_W120_selected:{cell_id}")
        if row.get("state_line") not in {"S_PCT", "S_PCVT"}:
            errors.append(f"state_line_invalid:{cell_id}")
        if row.get("qT") == "0.30" or row.get("qV") == "0.25":
            errors.append(f"excluded_q_candidate:{cell_id}")

    # Independently reconstruct each selected/strict-core hard-gate result.
    aliases = {
        "strict_core_subset_violation": "strict_core_subset_status",
        "transition_closure_violation": "accepted_bridge_transition_closure",
    }
    runtime_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    global_runtime: dict[str, list[dict[str, str]]] = {}
    for row in runtime:
        candidate = row.get("candidate_cell_id", "")
        if candidate:
            runtime_by_key.setdefault((row.get("check_id", ""), candidate), []).append(
                row
            )
        else:
            global_runtime.setdefault(row.get("check_id", ""), []).append(row)
    gate_rows_by_key = {
        (row.get("candidate_cell_id"), row.get("gate_id")): row
        for row in gate_revalidation
    }
    recomputed_gate_count = 0
    inherited_count = 0
    for cell_id in selected_all:
        cell = cell_by_id.get(cell_id, {})
        for gate in gates:
            if gate.get("state_line") not in {"GLOBAL", cell.get("state_line")}:
                continue
            metric = aliases.get(gate.get("metric_id"), gate.get("metric_id"))
            evidence = (
                global_runtime.get(metric, [])
                if gate.get("state_line") == "GLOBAL"
                else runtime_by_key.get((gate.get("gate_id"), cell_id), [])
            )
            if gate.get("state_line") == "GLOBAL":
                inherited_count += 1
            recomputed_gate_count += 1
            if len(evidence) != 1:
                errors.append(
                    f"gate_evidence_cardinality:{cell_id}:{gate.get('gate_id')}"
                )
                continue
            record = evidence[0]
            value = _number(record.get("observed_value"))
            threshold = _threshold(record.get("expected_rule", ""))
            if record.get("status") != "passed" or not _operator(
                value, gate.get("operator", ""), threshold
            ):
                errors.append(f"gate_failed:{cell_id}:{gate.get('gate_id')}")
            output_row = gate_rows_by_key.get((cell_id, gate.get("gate_id")))
            if output_row is None:
                errors.append(
                    f"gate_revalidation_row_missing:{cell_id}:{gate.get('gate_id')}"
                )
            else:
                if output_row.get("status") != "passed":
                    errors.append(
                        f"gate_revalidation_not_passed:{cell_id}:{gate.get('gate_id')}"
                    )
                if output_row.get("missing_evidence", "").lower() == "true":
                    errors.append(
                        f"gate_revalidation_missing_evidence:{cell_id}:{gate.get('gate_id')}"
                    )
                if output_row.get("hard_gate_override", "").lower() == "true":
                    errors.append(f"hard_gate_override:{cell_id}:{gate.get('gate_id')}")
                if output_row.get("scope") != (
                    "GLOBAL_INHERITED" if gate.get("state_line") == "GLOBAL" else "CELL"
                ):
                    errors.append(
                        f"gate_scope_not_explicit:{cell_id}:{gate.get('gate_id')}"
                    )
    if len(gate_revalidation) != recomputed_gate_count:
        errors.append("gate_revalidation_row_count_mismatch")
    if inherited_count != 120 or gate_summary.get("global_gate_rows_inherited") != 120:
        errors.append("global_gate_inheritance_mismatch")
    if (
        gate_summary.get("selected_cell_gate_status") != "passed"
        or gate_summary.get("strict_core_cell_gate_status") != "passed"
    ):
        errors.append("selected_or_strict_core_gate_summary_failed")
    if (
        gate_summary.get("missing_evidence_count") != 0
        or gate_summary.get("hard_gate_override_count") != 0
    ):
        errors.append("gate_summary_missing_or_overridden")

    # Freeze structure and deterministic hashes.
    if decision.get("decision_hash") != canonical_json_sha256(
        _without_hash(decision, "decision_hash")
    ):
        errors.append("decision_hash_mismatch")
    if freeze_decision.get("freeze_decision_hash") != canonical_json_sha256(
        _without_hash(freeze_decision, "freeze_decision_hash")
    ):
        errors.append("freeze_decision_hash_mismatch")
    if freeze_plan.get("freeze_plan_hash") != canonical_json_sha256(
        _without_hash(freeze_plan, "freeze_plan_hash")
    ):
        errors.append("freeze_plan_hash_mismatch")
    if (
        freeze_decision.get("selected_version_count") != 2
        or freeze_decision.get("strict_core_only_count") != 2
        or freeze_decision.get("rejected_decision_unit_count") != 2
    ):
        errors.append("freeze_decision_counts_invalid")
    plans = freeze_plan.get("planned_versions", [])
    if (
        len(plans) != 2
        or len({plan.get("planned_state_version_id") for plan in plans}) != 2
    ):
        errors.append("planned_state_version_id_not_unique")
    expected_plan_cells = set(expected_primary.values())
    if {plan.get("source_candidate_cell_id") for plan in plans} != expected_plan_cells:
        errors.append("freeze_plan_selected_cell_mismatch")
    if any(plan.get("W") != 120 for plan in plans):
        errors.append("W250_in_freeze_plan")
    if any(plan.get("strict_core_enabled") is not True for plan in plans):
        errors.append("strict_core_plan_disabled")
    if any(
        "shared" in str(plan.get("planned_state_version_id", "")).lower()
        for plan in plans
    ):
        errors.append("strict_core_created_independent_version")
    if (
        freeze_plan.get("cross_window_overlap_handling_required") is not False
        or freeze_plan.get("cross_state_line_identity_must_remain_distinct") is not True
    ):
        errors.append("freeze_plan_identity_policy_invalid")
    if (
        decision.get("automatic_recommendation_authoritative") is not False
        or decision.get("phase_a_automatic_recommendation_consumed_by_freeze_decision")
        is not False
    ):
        errors.append("automatic_recommendation_used_as_authority")

    # Source artifact hashes and the result package must be self-consistent.
    for item in decision.get("source_artifact_bindings", []):
        path = ROOT / item.get("path", "")
        if not path.is_file():
            errors.append(f"source_artifact_missing:{item.get('path')}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            errors.append(f"source_artifact_hash_mismatch:{item.get('path')}")
    if package.get("decision_hash") != decision.get("decision_hash") or package.get(
        "freeze_plan_hash"
    ) != freeze_plan.get("freeze_plan_hash"):
        errors.append("result_package_hash_binding_mismatch")
    if package.get("independent_validation_status") not in {"pending", "passed"}:
        errors.append("result_package_independent_status_invalid")

    # The author-stage package must not open downstream stages or self-assign review.
    for value, name in (
        (
            resolution.get("automatic_recommendation_authoritative"),
            "resolution_recommendation_authority",
        ),
        (
            resolution.get("automatic_recommendation_consumed_by_freeze_decision"),
            "resolution_recommendation_consumed",
        ),
        (resolution.get("new_parameter_search_performed"), "new_parameter_search"),
        (resolution.get("new_candidate_generated"), "new_candidate_generated"),
    ):
        if value is not False:
            errors.append(name)
    if resolution.get("phase_a_review_status") != "needs_revision":
        errors.append("phase_a_review_status_invalid")
    if (
        author_review.get("independent_validation_status") != "passed"
        and not author_stage_preflight
    ):
        errors.append("author_independent_validation_not_passed")
    if (
        author_review.get("scientific_review_status")
        != "pending_independent_scientific_review"
    ):
        errors.append("author_scientific_review_opened")
    if (
        repository_gate.get("repository_final_gate_status")
        != "pending_independent_scientific_review_and_exact_head_validation"
    ):
        errors.append("repository_gate_opened")
    for document, name in (
        (package, "result_package"),
        (author_review, "author_review"),
        (repository_gate, "repository_gate"),
    ):
        errors.extend(_forbidden(document, name))
    if (
        anomaly.get("status") != "passed"
        or anomaly.get("blocking_failure_count") != 0
        or anomaly.get("scientific_investigation_item_count") != 0
    ):
        errors.append("anomaly_scan_not_clean")
    if (
        package.get("formal_task_completed") is not False
        or package.get("R2-T05_allowed_to_start") is not False
        or package.get("R3_allowed_to_start") is not False
    ):
        errors.append("downstream_marker_open")

    checks = {
        "user_decision_schema": not any(
            error.startswith("schema_validation:r2_t04_user_decision_input")
            for error in errors
        ),
        "four_decision_units_and_vocabulary": not any(
            error.startswith(
                (
                    "decision_units",
                    "selected_disposition",
                    "W250_pair",
                    "disposition_vocabulary",
                    "rejected_vocabulary",
                )
            )
            for error in errors
        ),
        "independent_hard_gate_revalidation": not any(
            error.startswith(
                (
                    "gate_",
                    "global_gate",
                    "selected_or_strict_core_gate",
                    "hard_gate_override",
                )
            )
            for error in errors
        ),
        "freeze_plan_structure": not any(
            error.startswith(
                ("freeze_", "planned_state", "W250_", "strict_core_plan", "cross_")
            )
            for error in errors
        ),
        "hash_bindings": not any("hash" in error for error in errors),
        "anomaly_scan_and_downstream_closed": not any(
            error in {"anomaly_scan_not_clean", "downstream_marker_open"}
            or error.startswith(
                ("author_", "repository_", "phase_a_review", "resolution_")
            )
            for error in errors
        ),
    }
    return {
        "task_id": "R2-T04",
        "phase": "B",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "checks": checks,
        "independently_recomputed": [
            "user_decision_schema_and_vocabulary",
            "selected_and_strict_core_cell_registry_roles",
            "immutable_t02_t03_hard_gate_evidence",
            "global_gate_inheritance",
            "freeze_plan_counts_and_candidate_ids",
            "decision_freeze_plan_hashes",
            "source_artifact_hash_bindings",
            "forbidden_fields_and_downstream_markers",
        ],
        "production_oracle_imported": False,
        "pareto_recommendation_recomputed": False,
        "pareto_recommendation_used_for_final_decision": False,
        "decision_validation_mode": DECISION_VALIDATION_MODE,
        "selected_cell_count": len(selected_ids),
        "strict_core_only_count": len(strict_ids),
        "rejected_pair_count": sum(
            unit.get("user_disposition") == "reject_pair" for unit in units
        ),
        "global_gate_rows_recomputed": inherited_count,
        "recomputed_gate_row_count": recomputed_gate_count,
    }
