from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r2.r2_t01_candidate_convergence_shortlist import (
    ROOT,
    anomaly_scan,
    audit_row,
    canonical_row,
    dump_json,
    load_config,
    read_csv,
    reconcile_sources,
    sha256_file,
)


def validate_output(
    output_dir: Path, config_path: Path | None = None, *, root: Path = ROOT
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    if config_path is None:
        binding = json.loads(
            (output_dir / "r2_t01_input_binding.json").read_text(encoding="utf-8")
        )
        config_path = root / binding["config_path"]
    config = load_config(config_path)
    matrix = read_csv(root / config["inputs"]["decision_matrix_path"])
    candidate = read_csv(root / config["inputs"]["candidate_registry_path"])
    warning = read_csv(root / config["inputs"]["warning_registry_path"])
    recomputation = read_csv(root / config["inputs"]["decision_recomputation_path"])
    upstream = read_csv(root / config["inputs"]["upstream_reconciliation_path"])
    expected_registry = [
        canonical_row(config, row)
        for row in sorted(
            matrix, key=lambda r: (r["state_line"], int(r["W"]), r["handoff_row_id"])
        )
    ]
    expected_by_id = {row["r1_handoff_row_id"]: row for row in expected_registry}
    actual_registry = _read_jsonish_csv(output_dir / "r2_t01_shortlist_registry.csv")
    actual_by_id = {row["r1_handoff_row_id"]: row for row in actual_registry}
    errors: list[str] = []
    schema = json.loads(
        (
            root / "schemas/r2/r2_t01_candidate_convergence_shortlist.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    for row in actual_registry:
        schema_errors = sorted(validator.iter_errors(row), key=lambda e: e.path)
        errors.extend(
            f"schema:{row.get('r1_handoff_row_id')}:{e.message}" for e in schema_errors
        )
    if len(actual_registry) != 12:
        errors.append("canonical_registry_row_count_check")
    if len(actual_by_id) != len(actual_registry):
        errors.append("shared_q_duplicate_or_duplicate_handoff_row")
    for handoff_id, expected in expected_by_id.items():
        actual = actual_by_id.get(handoff_id)
        if actual is None:
            errors.append(f"missing_registry_row:{handoff_id}")
            continue
        for field in (
            "route_id",
            "candidate_role",
            "window_track_id",
            "selection_eligible",
            "fallback_eligible",
            "independent_product_eligible",
            "t03_geometry_role",
            "paired_primary_route_id",
            "selection_path_not_independently_confirmed",
            "warning_codes",
            "source_matrix_sha256",
        ):
            if actual.get(field) != expected.get(field):
                errors.append(f"field_mismatch:{handoff_id}:{field}")
    role_counts = Counter(row["candidate_role"] for row in actual_registry)
    if dict(role_counts) != config["expected_role_counts"]:
        errors.append("role_count_check")
    if sorted(
        row["route_id"] for row in actual_registry if row["candidate_role"] == "primary"
    ) != sorted(config["primary_shortlist_route_ids"]):
        errors.append("primary_shortlist_exact_identity_check")
    primary_rows = _read_jsonish_csv(output_dir / "r2_t01_primary_shortlist.csv")
    if len(primary_rows) != 4:
        errors.append("primary_shortlist_row_count_check")
    reconciliation = reconcile_sources(
        config, matrix, candidate, warning, recomputation, upstream
    )
    audit = [
        audit_row(config, source, actual_by_id.get(source["handoff_row_id"], {}))
        for source in matrix
        if source["handoff_row_id"] in actual_by_id
    ]
    summary_for_run = json.loads(
        (output_dir / "r2_t01_experiment_summary.json").read_text(encoding="utf-8")
    )
    code_commit = json.loads(
        (output_dir / "r2_t01_engineering_validation_result.json").read_text(
            encoding="utf-8"
        )
    ).get("code_commit", "")
    anomalies = anomaly_scan(
        config,
        summary_for_run["run_id"],
        code_commit,
        matrix,
        actual_registry,
        audit,
        reconciliation,
    )
    if anomalies["blocking_errors"]:
        errors.extend(anomalies["blocking_errors"])
    if summary_for_run.get("role_counts") != dict(role_counts):
        errors.append("result_artifact_analysis_count_mismatch")
    engineering = {
        "task_id": "R2-T01",
        "validator": "r2_t01_independent_validator_v1",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": sorted(set(errors)),
        "matrix_sha256": sha256_file(root / config["inputs"]["decision_matrix_path"]),
        "code_commit": code_commit,
        "role_counts": dict(role_counts),
        "downstream_gate_allowed": False,
        "R2-T02_allowed_to_start": False,
    }
    dump_json(output_dir / "r2_t01_engineering_validation_result.json", engineering)
    if engineering["status"] != "passed":
        raise RuntimeError(json.dumps(engineering, ensure_ascii=False))
    return engineering


def _read_jsonish_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key, value in list(row.items()):
            if value in {"True", "False"}:
                row[key] = value == "True"
            elif value.startswith("[") or value.startswith("{"):
                row[key] = json.loads(value)
            elif key in {"W", "K"} and value:
                row[key] = int(value)
    return rows
