from __future__ import annotations

import csv
import json
from pathlib import Path


def validate(output: Path) -> dict:
    errors = []
    with (output / "r1_t10_r2_decision_matrix.csv").open(
        encoding="utf-8-sig", newline=""
    ) as h:
        rows = list(csv.DictReader(h))
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
    for k, v in expected.items():
        if sum(r["overall_handoff_status"] == k for r in rows) != v:
            errors.append(f"unexpected_{k}_count")
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
    anomaly = json.loads(
        (output / "r1_t10_anomaly_scan.json").read_text(encoding="utf-8")
    )
    if anomaly.get("decision_status_mismatch_count") != 0:
        errors.append("decision_recomputation_mismatch")
    result = {
        "validator": "independent_read_only_contract_v1",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "decision_status_mismatch_count": 0 if not errors else None,
    }
    return result
