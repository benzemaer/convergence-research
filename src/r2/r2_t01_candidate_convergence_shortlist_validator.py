from __future__ import annotations

import csv
import hashlib
import json
import subprocess
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
    errors: list[str] = []
    errors.extend(_independent_input_chain_errors(config, output_dir, root))

    ordered_matrix = sorted(matrix, key=_independent_sort_key)
    expected_registry = [_expected_registry_row(config, row) for row in ordered_matrix]
    expected_by_id = {row["r1_handoff_row_id"]: row for row in expected_registry}
    actual_registry = _read_jsonish_csv(output_dir / "r2_t01_shortlist_registry.csv")
    actual_by_id = {row["r1_handoff_row_id"]: row for row in actual_registry}

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
        config, matrix, candidate, warning, recomputation, upstream, root
    )
    audit = [
        _independent_audit_row(
            config, source, actual_by_id.get(source["handoff_row_id"], {})
        )
        for source in ordered_matrix
        if source["handoff_row_id"] in actual_by_id
    ]
    disposition = [
        _independent_disposition_row(source, expected)
        for source, expected in zip(ordered_matrix, expected_registry)
    ]
    evidence = [_independent_evidence_row(row) for row in ordered_matrix]
    expected_artifacts = {
        "r2_t01_shortlist_registry.csv": expected_registry,
        "r2_t01_primary_shortlist.csv": [
            row for row in expected_registry if row["candidate_role"] == "primary"
        ],
        "r2_t01_candidate_disposition_registry.csv": disposition,
        "r2_t01_role_assignment_audit.csv": audit,
        "r2_t01_source_reconciliation.csv": reconciliation,
        "r2_t01_evidence_snapshot.csv": evidence,
    }
    comparison_errors, actual_hashes = _compare_committed_artifacts(
        output_dir, expected_artifacts
    )
    errors.extend(comparison_errors)
    rebuild_one = _canonical_artifact_hashes(expected_artifacts)
    rebuild_two = _canonical_artifact_hashes(
        _independent_rebuild(
            config, matrix, candidate, warning, recomputation, upstream, root
        )
    )
    deterministic_ok = rebuild_one == rebuild_two and rebuild_one == actual_hashes
    if not deterministic_ok:
        errors.append("deterministic_output_check")
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
        "validator": "r2_t01_independent_validator_v3",
        "status": "passed" if not errors else "failed",
        "error_count": len(set(errors)),
        "errors": sorted(set(errors)),
        "matrix_sha256": sha256_file(root / config["inputs"]["decision_matrix_path"]),
        "config_sha256": sha256_file(config_path),
        "code_commit": code_commit,
        "role_counts": dict(role_counts),
        "canonical_output_hashes": _canonical_output_hashes(output_dir),
        "canonical_normalized_output_hashes": actual_hashes,
        "independent_rebuild_1_hashes": rebuild_one,
        "independent_rebuild_2_hashes": rebuild_two,
        "independent_rebuilt_registry_sha256": _canonical_json_sha256(
            expected_registry
        ),
        "deterministic_output_check": "passed" if deterministic_ok else "failed",
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
    root: Path,
) -> list[dict[str, str]]:
    candidate_by_id = {row["handoff_row_id"]: row for row in candidate_registry}
    warning_by_id: dict[str, set[str]] = {}
    for row in warning_registry:
        warning_by_id.setdefault(row["handoff_row_id"], set()).add(row["warning_code"])
    recompute_by_id = {row["handoff_row_id"]: row for row in recomputation}
    rows: list[dict[str, str]] = []
    for source in sorted(matrix, key=lambda row: row["handoff_row_id"]):
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
                if _source_hashes_match(source, root)
                else "failed",
                "source_supersession_check": "passed"
                if _source_current(source, root)
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


def _source_hashes_match(row: dict[str, str], root: Path) -> bool:
    hashes = json.loads(row["source_artifact_hashes"])
    for meta in hashes.values():
        path = root / meta["path"]
        if not path.is_file() or sha256_file(path) != meta["sha256"]:
            return False
    return True


def _source_current(row: dict[str, str], root: Path) -> bool:
    hashes = json.loads(row["source_artifact_hashes"])
    for meta in hashes.values():
        path = root / meta["path"]
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
        "observed_handoff_status": source["overall_handoff_status"],
        "observed_q_vector": source["q_or_q_vector"],
        "expected_candidate_role": expected["candidate_role"],
        "actual_candidate_role": actual.get("candidate_role", ""),
        "mapping_rule_id": expected["mapping_rule_id"],
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
        "failure_reason": "",
    }


def _independent_disposition_row(
    source: dict[str, str], registry: dict[str, Any]
) -> dict[str, Any]:
    return {
        "r1_handoff_row_id": source["handoff_row_id"],
        "route_id": registry["route_id"],
        "candidate_role": registry["candidate_role"],
        "r1_handoff_status": source["overall_handoff_status"],
        "required_R2_decision": source["required_R2_decision"],
        "selection_eligible": registry["selection_eligible"],
        "fallback_eligible": registry["fallback_eligible"],
        "t03_geometry_role": registry["t03_geometry_role"],
        "role_reason_code": registry["role_reason_code"],
        "warning_codes": registry["warning_codes"],
    }


def _independent_evidence_row(row: dict[str, str]) -> dict[str, Any]:
    fields = [
        "handoff_row_id",
        "state_line",
        "W",
        "K",
        "qP",
        "qC",
        "qT",
        "qV",
        "source_route",
        "archetype",
        "confirmed_state_days",
        "confirmed_coverage",
        "unique_securities",
        "confirmed_intervals",
        "nonzero_years",
        "max_year_share",
        "fragment_rate",
        "median_duration",
        "retention",
        "target_marginal",
        "association_lift",
        "absolute_increment",
        "global_joint_lift",
        "nested_joint_lift",
        "warning_codes",
    ]
    result = {field: row[field] for field in fields}
    result["W"] = int(result["W"])
    result["K"] = int(result["K"])
    result["warning_codes"] = json.loads(result["warning_codes"])
    coverage = float(row["confirmed_coverage"])
    result["eligible_days"] = round(float(row["confirmed_state_days"]) / coverage)
    shared = row["handoff_row_id"].startswith("shared_")
    result["denominator_scope"] = (
        "r1_t01_to_t09_strict_common_valid_mixed_scope"
        if shared
        else "r1_t14_02_same_sample_ordered_short_circuit_scope"
    )
    result["metric_source_task"] = "R1-T01..R1-T09" if shared else "R1-T14-02"
    refs = json.loads(row["source_artifact_hashes"])
    result["metric_source_run"] = (
        "lineage_mixed_R1-T01_R1-T09"
        if shared
        else Path(refs["R1-T14-02"]["path"]).parts[-2]
    )
    family = "pct" if row["state_line"] == "S_PCT" else "pcvt"
    result["coverage_comparable_group"] = (
        f"mixed_scope_shared_q_W{row['W']}_{row['state_line']}"
        if shared
        else f"same_scope_t14_02_{family}_W{row['W']}"
    )
    result["coverage_cross_group_comparable"] = False
    return result


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


def _independent_rebuild(
    config: dict[str, Any],
    matrix: list[dict[str, str]],
    candidate: list[dict[str, str]],
    warning: list[dict[str, str]],
    recomputation: list[dict[str, str]],
    upstream: list[dict[str, str]],
    root: Path,
) -> dict[str, list[dict[str, Any]]]:
    ordered = sorted(matrix, key=_independent_sort_key)
    registry = [_expected_registry_row(config, row) for row in ordered]
    audit = [
        _independent_audit_row(config, source, actual)
        for source, actual in zip(ordered, registry)
    ]
    return {
        "r2_t01_shortlist_registry.csv": registry,
        "r2_t01_primary_shortlist.csv": [
            row for row in registry if row["candidate_role"] == "primary"
        ],
        "r2_t01_candidate_disposition_registry.csv": [
            _independent_disposition_row(source, actual)
            for source, actual in zip(ordered, registry)
        ],
        "r2_t01_role_assignment_audit.csv": audit,
        "r2_t01_source_reconciliation.csv": _independent_reconciliation(
            config, matrix, candidate, warning, recomputation, upstream, root
        ),
        "r2_t01_evidence_snapshot.csv": [
            _independent_evidence_row(row) for row in ordered
        ],
    }


def _compare_committed_artifacts(
    output_dir: Path, expected: dict[str, list[dict[str, Any]]]
) -> tuple[list[str], dict[str, str]]:
    errors: list[str] = []
    actual_hashes: dict[str, str] = {}
    for name, expected_rows in expected.items():
        actual_rows = _read_jsonish_csv(output_dir / name)
        actual_hashes[name] = _canonical_json_sha256(actual_rows)
        if actual_rows != expected_rows:
            errors.append(f"committed_artifact_mismatch:{name}")
            if len(actual_rows) != len(expected_rows):
                errors.append(f"committed_artifact_row_count:{name}")
            elif sorted(actual_rows, key=_row_identity) == sorted(
                expected_rows, key=_row_identity
            ):
                errors.append(f"committed_artifact_order:{name}")
    return errors, actual_hashes


def _canonical_artifact_hashes(
    artifacts: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    return {name: _canonical_json_sha256(rows) for name, rows in artifacts.items()}


def _row_identity(row: dict[str, Any]) -> str:
    return str(row.get("r1_handoff_row_id", row.get("handoff_row_id", "")))


def _independent_sort_key(row: dict[str, str]) -> tuple[int, str, int, str]:
    handoff_id = row["handoff_row_id"]
    if handoff_id.startswith("q_") and row["qT"] == "0.3":
        group = 2
    elif handoff_id.startswith("q_") and row["qV"] == "0.25":
        group = 3
    elif handoff_id.startswith("shared_"):
        group = 1
    else:
        group = 0
    return group, row["state_line"], int(row["W"]), handoff_id


def _independent_input_chain_errors(
    config: dict[str, Any], output_dir: Path, root: Path
) -> list[str]:
    errors: list[str] = []
    paths = config["inputs"]
    payloads = {
        key: json.loads((root / paths[key]).read_text(encoding="utf-8"))
        for key in (
            "final_gate_package_path",
            "final_gate_validation_path",
            "reviewed_author_package_path",
            "scientific_review_path",
            "handoff_manifest_path",
        )
    }
    final_gate = payloads["final_gate_package_path"]
    validation = payloads["final_gate_validation_path"]
    reviewed = payloads["reviewed_author_package_path"]
    review = payloads["scientific_review_path"]
    handoff = payloads["handoff_manifest_path"]
    checks = [
        (
            validation.get("final_gate_package_sha256")
            == sha256_file(root / paths["final_gate_package_path"]),
            "input_final_gate_package_sha_check",
        ),
        (
            final_gate.get("reviewed_author_package_sha256")
            == sha256_file(root / paths["reviewed_author_package_path"]),
            "input_reviewed_author_package_sha_check",
        ),
        (
            final_gate.get("scientific_review_record_sha256")
            == sha256_file(root / paths["scientific_review_path"]),
            "input_scientific_review_file_sha_check",
        ),
        (
            final_gate.get("reviewed_author_package_sha256")
            == review.get("reviewed_author_package_sha256")
            == review.get("reviewed_result_package_sha256"),
            "input_review_package_cross_binding_check",
        ),
        (
            final_gate.get("scientific_review_status")
            == review.get("scientific_review_status")
            and final_gate.get("independent_review_status")
            == review.get("independent_review_status"),
            "input_review_status_binding_check",
        ),
        (
            handoff.get("matrix_sha256")
            == review.get("reviewed_matrix_sha256")
            == paths["expected_sha256"]["decision_matrix"],
            "input_handoff_matrix_sha_check",
        ),
        (
            handoff.get("row_count")
            == len(read_csv(root / paths["decision_matrix_path"])),
            "input_handoff_matrix_cardinality_check",
        ),
    ]
    for passed, code in checks:
        if not passed:
            errors.append(code)
    committed = reviewed.get("committed_artifacts", {})
    for label, key in {
        "decision_matrix": "decision_matrix_path",
        "handoff_manifest": "handoff_manifest_path",
        "candidate_registry": "candidate_registry_path",
        "warning_registry": "warning_registry_path",
        "decision_recomputation": "decision_recomputation_path",
        "upstream_reconciliation": "upstream_reconciliation_path",
    }.items():
        rel = paths[key]
        if committed.get(rel, {}).get("sha256") != sha256_file(root / rel):
            errors.append(f"input_reviewed_package_{label}_sha_check")
    binding = json.loads(
        (output_dir / "r2_t01_input_binding.json").read_text(encoding="utf-8")
    )
    if binding.get("config_sha256") != sha256_file(
        root / binding.get("config_path", "__missing__")
    ):
        errors.append("committed_input_binding_config_sha_check")
    for key, meta in binding.get("input_artifacts", {}).items():
        expected_path = paths.get(key)
        if (
            meta.get("path") != expected_path
            or not expected_path
            or meta.get("sha256") != sha256_file(root / expected_path)
        ):
            errors.append(f"committed_input_binding_artifact:{key}")
    expected_head = final_gate.get("reviewed_pr_head_commit")
    if expected_head:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", expected_head, "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            errors.append("input_pr90_merge_lineage_check")
    return errors


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
            elif key in {"W", "K", "eligible_days"} and value:
                row[key] = int(value)
    return rows
