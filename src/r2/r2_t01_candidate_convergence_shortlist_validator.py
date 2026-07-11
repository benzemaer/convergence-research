from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r2.r2_t01_candidate_convergence_shortlist import (
    ROOT,
    dump_json,
    load_config,
    read_csv,
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

    expected_registry = [_expected_registry_row(config, row) for row in matrix]
    expected_by_id = {row["r1_handoff_row_id"]: row for row in expected_registry}
    actual_registry = _read_jsonish_csv(output_dir / "r2_t01_shortlist_registry.csv")
    actual_by_id = {row["r1_handoff_row_id"]: row for row in actual_registry}
    errors: list[str] = []

    schema = json.loads(
        (
            root / "schemas/r2/r2_t01_candidate_convergence_shortlist.schema.json"
        ).read_text(encoding="utf-8")
    )
    schema_validator = Draft202012Validator(schema)
    for row in actual_registry:
        schema_errors = sorted(schema_validator.iter_errors(row), key=lambda e: e.path)
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
            "state_line",
            "window_track_id",
            "W",
            "K",
            "qP",
            "qC",
            "qT",
            "qV",
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
    primary_rows = _read_jsonish_csv(output_dir / "r2_t01_primary_shortlist.csv")
    if len(primary_rows) != 4:
        errors.append("primary_shortlist_row_count_check")
    if sorted(row["route_id"] for row in primary_rows) != sorted(
        config["primary_shortlist_route_ids"]
    ):
        errors.append("primary_shortlist_exact_identity_check")

    reconciliation = _independent_reconciliation(
        config, matrix, candidate, warning, recomputation, upstream
    )
    audit = [
        _independent_audit_row(
            config, source, actual_by_id.get(source["handoff_row_id"], {})
        )
        for source in matrix
        if source["handoff_row_id"] in actual_by_id
    ]
    errors.extend(
        _independent_anomaly_errors(
            config, matrix, actual_registry, audit, reconciliation
        )
    )

    summary_for_run = json.loads(
        (output_dir / "r2_t01_experiment_summary.json").read_text(encoding="utf-8")
    )
    code_commit = json.loads(
        (output_dir / "r2_t01_engineering_validation_result.json").read_text(
            encoding="utf-8"
        )
    ).get("code_commit", "")
    if summary_for_run.get("role_counts") != dict(role_counts):
        errors.append("result_artifact_analysis_count_mismatch")
    readme_ok = _readme_gate_passed(root, config)
    if not readme_ok:
        errors.append("README_transition_check")

    engineering = {
        "task_id": "R2-T01",
        "validator": "r2_t01_independent_validator_v2",
        "status": "passed" if not errors else "failed",
        "error_count": len(set(errors)),
        "errors": sorted(set(errors)),
        "matrix_sha256": sha256_file(root / config["inputs"]["decision_matrix_path"]),
        "config_sha256": sha256_file(config_path),
        "code_commit": code_commit,
        "role_counts": dict(role_counts),
        "canonical_output_hashes": _canonical_output_hashes(output_dir),
        "independent_rebuilt_registry_sha256": _canonical_json_sha256(
            expected_registry
        ),
        "deterministic_output_check": "passed" if not errors else "blocked",
        "README_transition_check": "passed" if readme_ok else "blocked",
        "downstream_gate_allowed": False,
        "R2-T02_allowed_to_start": False,
    }
    dump_json(output_dir / "r2_t01_engineering_validation_result.json", engineering)
    if engineering["status"] != "passed":
        raise RuntimeError(json.dumps(engineering, ensure_ascii=False))
    return engineering


def _expected_registry_row(
    config: dict[str, Any], source: dict[str, str]
) -> dict[str, Any]:
    rule = config["source_row_to_route_mapping"][source["handoff_row_id"]]
    role = rule["candidate_role"]
    return {
        "route_id": rule["route_id"],
        "state_line": source["state_line"],
        "window_track_id": config["window_track_mapping"][f"W{source['W']}"],
        "W": int(source["W"]),
        "K": int(source["K"]),
        "qP": source["qP"],
        "qC": source["qC"],
        "qT": source["qT"],
        "qV": source["qV"],
        "candidate_role": role,
        "r1_handoff_row_id": source["handoff_row_id"],
        "r1_handoff_status": source["overall_handoff_status"],
        "r1_required_R2_decision": source["required_R2_decision"],
        "selection_eligible": role == "primary",
        "fallback_eligible": bool(rule.get("fallback_eligible", False)),
        "independent_product_eligible": bool(
            rule.get("independent_product_eligible", role == "primary")
        ),
        "t03_geometry_role": rule["t03_geometry_role"],
        "paired_primary_route_id": rule.get("paired_primary_route_id", ""),
        "role_reason_code": rule["role_reason_code"],
        "role_capabilities": rule["role_capabilities"],
        "selection_path_not_independently_confirmed": source[
            "selection_path_not_independently_confirmed"
        ]
        == "True",
        "warning_codes": json.loads(source["warning_codes"]),
        "source_artifact_refs": json.loads(source["source_artifact_refs"]),
        "source_artifact_hashes": json.loads(source["source_artifact_hashes"]),
        "source_matrix_sha256": config["inputs"]["expected_sha256"]["decision_matrix"],
        "contract_version": config["protocol_version"],
    }


def _independent_reconciliation(
    config: dict[str, Any],
    matrix: list[dict[str, str]],
    candidate_registry: list[dict[str, str]],
    warning_registry: list[dict[str, str]],
    recomputation: list[dict[str, str]],
    upstream: list[dict[str, str]],
) -> list[dict[str, str]]:
    candidate_by_id = {row["handoff_row_id"]: row for row in candidate_registry}
    warning_by_id: dict[str, set[str]] = {}
    for row in warning_registry:
        warning_by_id.setdefault(row["handoff_row_id"], set()).add(row["warning_code"])
    recompute_by_id = {row["handoff_row_id"]: row for row in recomputation}
    rows: list[dict[str, str]] = []
    for source in matrix:
        handoff_id = source["handoff_row_id"]
        candidate = candidate_by_id.get(handoff_id)
        candidate_status = "passed"
        if candidate is None:
            candidate_status = "missing"
        else:
            mismatches = [
                field
                for field in config["reconciliation"]["candidate_registry_key_fields"]
                if str(candidate.get(field, "")) != str(source.get(field, ""))
            ]
            if mismatches:
                candidate_status = "mismatch:" + ",".join(mismatches)
        expected_warnings = set(json.loads(source["warning_codes"]))
        recompute = recompute_by_id.get(handoff_id)
        rows.append(
            {
                "handoff_row_id": handoff_id,
                "candidate_registry_reconciliation": candidate_status,
                "warning_registry_reconciliation": "passed"
                if warning_by_id.get(handoff_id, set()) == expected_warnings
                else "mismatch",
                "decision_recomputation_status": "passed"
                if recompute
                and recompute["expected_status"] == recompute["actual_status"]
                and not recompute["mismatch_reason"]
                else "mismatch",
                "source_artifact_hash_check": "passed"
                if _source_hashes_match(source)
                else "failed",
                "source_supersession_check": "passed"
                if _source_current(source)
                else "failed",
            }
        )
    if any(row["reconciliation_status"] != "passed" for row in upstream):
        rows.append(
            {
                "handoff_row_id": "__upstream__",
                "candidate_registry_reconciliation": "not_applicable",
                "warning_registry_reconciliation": "not_applicable",
                "decision_recomputation_status": "not_applicable",
                "source_artifact_hash_check": "not_applicable",
                "source_supersession_check": "failed",
            }
        )
    return rows


def _source_hashes_match(row: dict[str, str]) -> bool:
    hashes = json.loads(row["source_artifact_hashes"])
    for meta in hashes.values():
        path = ROOT / meta["path"]
        if not path.is_file() or sha256_file(path) != meta["sha256"]:
            return False
    return True


def _source_current(row: dict[str, str]) -> bool:
    hashes = json.loads(row["source_artifact_hashes"])
    for meta in hashes.values():
        path = ROOT / meta["path"]
        if not path.is_file():
            return False
        if path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if payload.get("superseded") is True or payload.get("status") == "superseded":
            return False
        if payload.get("superseded_by"):
            return False
    return True


def _independent_audit_row(
    config: dict[str, Any], source: dict[str, str], actual: dict[str, Any]
) -> dict[str, str]:
    expected = config["source_row_to_route_mapping"][source["handoff_row_id"]]
    source_warnings = json.loads(source["warning_codes"])
    return {
        "r1_handoff_row_id": source["handoff_row_id"],
        "assignment_status": "passed"
        if expected["candidate_role"] == actual.get("candidate_role")
        else "failed",
        "warning_reconciliation_status": "passed"
        if source_warnings == actual.get("warning_codes")
        else "failed",
        "selection_path_propagation_status": "passed"
        if (source["selection_path_not_independently_confirmed"] == "True")
        == actual.get("selection_path_not_independently_confirmed")
        else "failed",
    }


def _independent_anomaly_errors(
    config: dict[str, Any],
    matrix: list[dict[str, str]],
    registry: list[dict[str, Any]],
    audit: list[dict[str, str]],
    reconciliation: list[dict[str, str]],
) -> list[str]:
    errors: list[str] = []
    role_counts = Counter(row["candidate_role"] for row in registry)
    if dict(role_counts) != config["expected_role_counts"]:
        errors.append("role_count_check")
    primary_ids = sorted(
        row["route_id"] for row in registry if row["candidate_role"] == "primary"
    )
    if primary_ids != sorted(config["primary_shortlist_route_ids"]):
        errors.append("primary_shortlist_exact_identity_check")
    if len({row["r1_handoff_row_id"] for row in registry}) != len(registry):
        errors.append("duplicate_handoff_row_check")
    for row in registry:
        rule = config["source_row_to_route_mapping"].get(row["r1_handoff_row_id"], {})
        if row["paired_primary_route_id"] != rule.get("paired_primary_route_id", ""):
            errors.append(f"pairing_check:{row['r1_handoff_row_id']}")
        if row["qT"] == "0.3" and row["candidate_role"] == "primary":
            errors.append("q_vector_role_check:t30_primary")
        if row["qV"] == "0.25" and row["candidate_role"] != "excluded":
            errors.append("q_vector_role_check:v25_not_excluded")
    if any(row["assignment_status"] != "passed" for row in audit):
        errors.append("role_assignment_audit_check")
    if any(row["warning_reconciliation_status"] != "passed" for row in audit):
        errors.append("warning_registry_reconciliation")
    if any(row["selection_path_propagation_status"] != "passed" for row in audit):
        errors.append("selection_path_propagation_check")
    status_cols = [key for key in reconciliation[0] if key != "handoff_row_id"]
    if any(any(row[key] != "passed" for key in status_cols) for row in reconciliation):
        errors.append("source_reconciliation_check")
    if len(matrix) != len(registry):
        errors.append("funnel_accounting_check")
    return errors


def _canonical_output_hashes(output_dir: Path) -> dict[str, str]:
    names = [
        "r2_t01_shortlist_registry.csv",
        "r2_t01_primary_shortlist.csv",
        "r2_t01_role_assignment_audit.csv",
        "r2_t01_source_reconciliation.csv",
        "r2_t01_evidence_snapshot.csv",
    ]
    return {name: sha256_file(output_dir / name) for name in names}


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _readme_gate_passed(root: Path, config: dict[str, Any]) -> bool:
    readme = (root / "docs/tasks/README.md").read_text(encoding="utf-8")
    gate = config["author_draft_gate_state"]
    required = [
        gate["current_stage"],
        gate["current_task"],
        gate["next_planned_task"],
        "R2-T02_allowed_to_start: false",
        "R3_allowed_to_start: false",
    ]
    return all(token in readme for token in required)


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
