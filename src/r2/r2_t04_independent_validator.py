from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
