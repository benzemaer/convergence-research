from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from src.r1.r1_t10_precedence_validator import (
    recompute_handoff_status,
    validate_readme_transition,
)

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _float(row: dict[str, str], key: str) -> float:
    if key not in row or row[key] in ("", None):
        raise ValueError(
            f"mandatory_numeric_field_missing:{key}:{row.get('handoff_row_id')}"
        )
    return float(row[key])


def _check_rate_identity(row: dict[str, str]) -> list[str]:
    errors = []
    try:
        target = _float(row, "target_marginal")
        retention = _float(row, "retention")
        lift = _float(row, "association_lift")
        delta = _float(row, "absolute_increment")
    except ValueError as exc:
        return [str(exc)]
    if target <= 0:
        errors.append(f"nonpositive_target_marginal:{row['handoff_row_id']}")
    if abs(retention - lift * target) > 1e-10:
        errors.append(f"retention_lift_identity:{row['handoff_row_id']}")
    if abs(delta - (retention - target)) > 1e-10:
        errors.append(f"delta_identity:{row['handoff_row_id']}")
    return errors


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def _check_q_nested_family(row: dict[str, str]) -> list[str]:
    if not row["formal_vector_id"]:
        return []
    expected_family = (
        "F4_T_GIVEN_PC" if row["state_line"] == "S_PCT" else "F5_V_GIVEN_PCT"
    )
    null_path = (
        ROOT
        / "data/generated/r1/r1_t14_02/R1-T14-02-20260711T1100Z"
        / "r1_t14_02_null_results.csv"
    )
    matches = [
        r
        for r in _read_csv(null_path)
        if r["formal_vector_id"] == row["formal_vector_id"]
        and r["family_id"] == expected_family
    ]
    if len(matches) != 1:
        return [f"nested_family_source_missing:{row['handoff_row_id']}"]
    expected = matches[0]
    errors = []
    if abs(float(row["nested_joint_lift"]) - float(expected["joint_lift"])) > 1e-10:
        errors.append(f"nested_family_lift_mismatch:{row['handoff_row_id']}")
    if abs(float(row["nested_joint_excess"]) - float(expected["joint_excess"])) > 1e-10:
        errors.append(f"nested_family_excess_mismatch:{row['handoff_row_id']}")
    return errors


def validate(output: Path) -> dict:
    errors = []
    with (output / "r1_t10_r2_decision_matrix.csv").open(
        encoding="utf-8-sig", newline=""
    ) as h:
        rows = list(csv.DictReader(h))
    upstream_path = output / "r1_t10_upstream_gate_reconciliation.csv"
    if upstream_path.is_file():
        with upstream_path.open(encoding="utf-8-sig", newline="") as h:
            upstream_reconciliation = list(csv.DictReader(h))
    else:
        errors.append("upstream_reconciliation_missing")
        upstream_reconciliation = []
    expected = {
        "freeze_candidate": 4,
        "review_candidate": 6,
        "do_not_freeze": 2,
        "blocked_return_to_R0": 0,
    }
    if len(rows) != 12:
        errors.append("matrix_row_count_must_equal_12")
    if len({r["handoff_row_id"] for r in rows}) != 12:
        errors.append("handoff_row_ids_must_be_unique")
    recomputed = []
    for r in rows:
        q = r["source_route"].startswith("R1-T14")
        if q and r["selection_path_not_independently_confirmed"] != "True":
            errors.append(f"missing_selection_flag:{r['handoff_row_id']}")
        if (
            r["state_line"] == "S_PCVT"
            and r["same_parameter_parent_id"]
            and f"W{r['W']}_" not in r["same_parameter_parent_id"]
        ):
            errors.append(f"cross_window_parent:{r['handoff_row_id']}")
        if (
            r["request_role"] == "immediate_neighbor"
            and r["qV"] == "0.25"
            and r["overall_handoff_status"] != "do_not_freeze"
        ):
            errors.append("v25_must_not_advance")
        if (
            r["request_role"] == "immediate_neighbor"
            and r["qT"] == "0.3"
            and r["overall_handoff_status"] == "freeze_candidate"
        ):
            errors.append("t30_must_not_freeze")
        if not json.loads(r["warning_codes"]):
            errors.append(f"warnings_empty:{r['handoff_row_id']}")
        if r["archetype"] == "shared_q":
            refs = set(json.loads(r["source_artifact_refs"]))
            missing = {f"R1-T{i:02d}" for i in range(1, 10)} - refs
            if missing:
                errors.append(f"shared_q_source_lineage_missing:{r['handoff_row_id']}")
        errors.extend(_check_rate_identity(r))
        errors.extend(_check_q_nested_family(r))
        hashes = json.loads(r["source_artifact_hashes"])
        for task, meta in hashes.items():
            path = ROOT / meta["path"]
            if not path.is_file() or _sha(path) != meta["sha256"]:
                errors.append(f"source_hash_mismatch:{r['handoff_row_id']}:{task}")
        expected_status, reason = recompute_handoff_status(r)
        recomputed.append(
            {
                "handoff_row_id": r["handoff_row_id"],
                "expected_status": expected_status,
                "actual_status": r["overall_handoff_status"],
                "mismatch_reason": ""
                if expected_status == r["overall_handoff_status"]
                else reason,
            }
        )
    for k, v in expected.items():
        if sum(r["expected_status"] == k for r in recomputed) != v:
            errors.append(f"unexpected_recomputed_{k}_count")
    anomaly = json.loads(
        (output / "r1_t10_anomaly_scan.json").read_text(encoding="utf-8")
    )
    upstream_failed = sum(
        r["reconciliation_status"] != "passed" for r in upstream_reconciliation
    )
    if len(upstream_reconciliation) != 12:
        errors.append("upstream_reconciliation_row_count_must_equal_12")
    for r in upstream_reconciliation:
        for key in ("package_unique", "non_superseded", "hashes_match"):
            if r.get(key) != "true":
                errors.append(f"upstream_{key}_failed:{r.get('task_id')}")
        if r.get("scientific_gate") not in {"passed", "passed_or_legacy_gate_adapter"}:
            errors.append(f"upstream_scientific_gate_failed:{r.get('task_id')}")
        if r.get("repository_gate") != "passed":
            errors.append(f"upstream_repository_gate_failed:{r.get('task_id')}")
        if r.get("formal_task_completed") != "true":
            errors.append(f"upstream_formal_task_incomplete:{r.get('task_id')}")
    if upstream_failed:
        errors.append(f"upstream_reconciliation_failed_count:{upstream_failed}")
    if anomaly.get("upstream_reconciliation_failed_count") != upstream_failed:
        errors.append("anomaly_upstream_reconciliation_failed_count_mismatch")
    mismatch_count = sum(r["expected_status"] != r["actual_status"] for r in recomputed)
    if anomaly.get("decision_status_mismatch_count") != mismatch_count:
        errors.append("anomaly_decision_mismatch_count_not_recomputed")
    if mismatch_count != 0:
        errors.append("decision_recomputation_mismatch")
    recomputation_path = output / "r1_t10_decision_recomputation.csv"
    if not recomputation_path.is_file():
        errors.append("decision_recomputation_artifact_missing")
    else:
        with recomputation_path.open(encoding="utf-8-sig", newline="") as h:
            recorded = list(csv.DictReader(h))
        if recorded != recomputed:
            errors.append("decision_recomputation_artifact_mismatch")
    transition_path = output / "r1_t10_readme_transition_artifact.json"
    if not transition_path.is_file():
        errors.append("readme_transition_artifact_missing")
    else:
        transition = json.loads(transition_path.read_text(encoding="utf-8"))
        if transition.get("t14_02_final_task_index_sha256") == transition.get(
            "current_task_index_sha256"
        ):
            errors.append("transition_does_not_bind_readme_change")
        if transition.get("R2_allowed_to_start") is not False:
            errors.append("transition_opened_R2")
        errors.extend(validate_readme_transition(ROOT, transition))
    checklist_path = output / "r1_t10_stage_acceptance_checklist.csv"
    if checklist_path.is_file():
        with checklist_path.open(encoding="utf-8-sig", newline="") as h:
            checklist = list(csv.DictReader(h))
        if any(r["status"] == "failed" for r in checklist) != bool(upstream_failed):
            errors.append("checklist_does_not_reflect_upstream_reconciliation")
    else:
        errors.append("stage_acceptance_checklist_missing")
    trigger_path = output / "r1_t10_optional_task_trigger_matrix.csv"
    if trigger_path.is_file():
        with trigger_path.open(encoding="utf-8-sig", newline="") as h:
            triggers = list(csv.DictReader(h))
        for row in triggers:
            if (
                row.get("trigger_status") != "not_triggered"
                or row.get("blocking_R2_handoff") != "false"
            ):
                errors.append(f"optional_trigger_conflict:{row.get('task_id')}")
    else:
        errors.append("optional_task_trigger_matrix_missing")
    result = {
        "validator": "independent_read_only_contract_v1",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "decision_status_mismatch_count": mismatch_count,
    }
    return result
