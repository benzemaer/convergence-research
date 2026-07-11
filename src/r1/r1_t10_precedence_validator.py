"""Independent read-only R1-T10 precedence checks."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def row_gate_passed(value: Any) -> bool:
    return str(value) in {
        "passed",
        "passed_with_warning",
        "secondary_descriptive_evidence",
        "not_revalidated_for_q_vector_secondary_only",
        "shared_parameter_baseline",
        "requires_R2_parsimony_decision",
        "family_max_adjusted_passed",
        "pre_registered_family",
        "not_applicable",
        "complexity_not_justified",
    }


def recompute_handoff_status(row: dict[str, Any]) -> tuple[str, str]:
    input_gates = [
        "input_gate_status",
    ]
    scientific_gates = [
        "existence_status",
        "intra_layer_status",
        "inter_layer_increment_status",
        "global_null_status",
        "nested_increment_null_status",
        "year_stability_status",
        "identity_status",
        "interval_geometry_status",
        "neighborhood_status",
        "complexity_status",
        "multiplicity_status",
    ]
    input_failed = [gate for gate in input_gates if not row_gate_passed(row.get(gate))]
    if input_failed:
        return "blocked_return_to_R0", ";".join(input_failed)
    scientific_failed = [
        gate for gate in scientific_gates if not row_gate_passed(row.get(gate))
    ]
    if scientific_failed:
        return "do_not_freeze", ";".join(scientific_failed)
    if row.get("archetype") == "shared_q":
        return "freeze_candidate", ""
    if (
        row.get("request_role") == "immediate_neighbor"
        and float(row.get("qV", 0)) == 0.25
    ):
        if row.get("complexity_status") == "complexity_not_justified":
            return "do_not_freeze", ""
        return "blocked_return_to_R0", "v25_neighbor_without_complexity_rejection"
    if row.get("request_role") in {"center", "immediate_neighbor"}:
        return "review_candidate", ""
    return "blocked_return_to_R0", "unknown_candidate_role"


def current_stage_block(text: str) -> dict[str, str]:
    section = text.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
    block = section.split("```text", 1)[1].split("```", 1)[0]
    values: dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def validate_readme_transition(root: Path, transition: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    merge_commit = str(transition.get("t14_02_merge_commit", ""))
    if not merge_commit:
        return ["transition_missing_t14_02_merge_commit"]
    old_result = subprocess.run(
        ["git", "show", f"{merge_commit}:docs/tasks/README.md"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if old_result.returncode:
        return ["transition_old_readme_unreadable"]
    current_path = root / str(transition.get("current_task_index_path", ""))
    if not current_path.is_file():
        return ["transition_current_readme_missing"]
    old_fields = current_stage_block(old_result.stdout)
    new_fields = current_stage_block(current_path.read_text(encoding="utf-8"))
    allowed = set(transition.get("allowed_field_changes", []))
    changed = {
        key
        for key in set(old_fields) | set(new_fields)
        if old_fields.get(key) != new_fields.get(key)
    }
    unallowed = sorted(changed - allowed)
    if unallowed:
        errors.append("transition_unallowed_field_changes:" + ",".join(unallowed))
    expected_changed = sorted(changed)
    if transition.get("observed_field_changes") != expected_changed:
        errors.append("transition_observed_field_changes_mismatch")
    if new_fields.get("R2_allowed_to_start") != "false":
        errors.append("transition_current_R2_not_false")
    return errors
