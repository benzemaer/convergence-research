from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_TOKENS = (
    "selected_d",
    "selected_g",
    "event_id",
    "event_zone_member",
    "future_return",
    "future_volatility",
    "future_direction",
    "future_path",
    "precision",
    "recall",
    "backtest",
    "state_version_id",
    "freeze_decision",
    "freeze_plan",
)


class R2T01Error(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(value, list | dict)
                    else value
                    for key, value in row.items()
                }
            )


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )


def load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R2T01Error("config_not_object")
    return value


def repo_rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def current_commit(root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_dirty(root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    allowed_prefixes = (
        "?? configs/r2/",
        "?? docs/experiments/r2/",
        "?? docs/tasks/R2-T01_",
        "?? schemas/r2/",
        "?? scripts/r2/",
        "?? src/r2/",
        "?? tests/r2/",
    )
    return [
        line
        for line in result.stdout.splitlines()
        if line and not line.startswith(allowed_prefixes)
    ]


def build_run(
    config_path: Path, output_dir: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = load_config(config_path)
    run_id = output_dir.name
    if not run_id.startswith("R2-T01-"):
        raise R2T01Error("run_id_must_start_R2_T01")
    output_dir.mkdir(parents=True, exist_ok=True)

    final_gate = _load_json(root / config["inputs"]["final_gate_package_path"])
    final_validation = _load_json(root / config["inputs"]["final_gate_validation_path"])
    matrix_path = root / config["inputs"]["decision_matrix_path"]
    rows = read_csv(matrix_path)
    _check_input_authorization(config, final_gate, final_validation, rows, matrix_path)

    candidate_rows = read_csv(root / config["inputs"]["candidate_registry_path"])
    warning_rows = read_csv(root / config["inputs"]["warning_registry_path"])
    recomputation_rows = read_csv(
        root / config["inputs"]["decision_recomputation_path"]
    )
    upstream_rows = read_csv(root / config["inputs"]["upstream_reconciliation_path"])
    reconciliation = reconcile_sources(
        config, rows, candidate_rows, warning_rows, recomputation_rows, upstream_rows
    )

    registry = [canonical_row(config, row) for row in sorted(rows, key=_sort_key)]
    disposition = [
        disposition_row(row, registry_row)
        for row, registry_row in zip(sorted(rows, key=_sort_key), registry)
    ]
    primary = [row for row in registry if row["candidate_role"] == "primary"]
    audit = [
        audit_row(config, source, actual)
        for source, actual in zip(sorted(rows, key=_sort_key), registry)
    ]
    evidence = [evidence_row(row) for row in sorted(rows, key=_sort_key)]
    code_commit = current_commit(root)
    anomalies = anomaly_scan(
        config, run_id, code_commit, rows, registry, audit, reconciliation
    )
    summary = experiment_summary(config, run_id, rows, registry, anomalies)
    diagnostic = diagnostic_summary(config, registry, audit, reconciliation, anomalies)

    input_binding = input_binding_payload(config, config_path, rows, root)
    engineering = {
        "task_id": "R2-T01",
        "run_id": run_id,
        "validator": "builder_preflight_contract_v1",
        "status": "passed" if not anomalies["blocking_errors"] else "failed",
        "error_count": len(anomalies["blocking_errors"]),
        "errors": anomalies["blocking_errors"],
        "matrix_sha256": sha256_file(matrix_path),
        "config_sha256": sha256_file(config_path),
        "code_commit": code_commit,
    }
    if engineering["status"] != "passed":
        dump_json(output_dir / "r2_t01_engineering_validation_result.json", engineering)
        raise R2T01Error(json.dumps(engineering, ensure_ascii=False))

    write_csv(output_dir / "r2_t01_source_reconciliation.csv", reconciliation)
    write_csv(output_dir / "r2_t01_candidate_disposition_registry.csv", disposition)
    write_csv(output_dir / "r2_t01_shortlist_registry.csv", registry)
    write_csv(output_dir / "r2_t01_primary_shortlist.csv", primary)
    write_csv(output_dir / "r2_t01_role_assignment_audit.csv", audit)
    write_csv(output_dir / "r2_t01_evidence_snapshot.csv", evidence)
    dump_json(output_dir / "r2_t01_input_binding.json", input_binding)
    dump_json(output_dir / "r2_t01_experiment_summary.json", summary)
    dump_json(output_dir / "r2_t01_diagnostic_summary.json", diagnostic)
    dump_json(output_dir / "r2_t01_anomaly_scan.json", anomalies)
    dump_json(output_dir / "r2_t01_engineering_validation_result.json", engineering)
    dump_json(
        output_dir / "r2_t01_scientific_review.json", pending_review(run_id, registry)
    )
    return summary


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R2T01Error(f"json_not_object:{path}")
    return value


def _check_input_authorization(
    config: dict[str, Any],
    final_gate: dict[str, Any],
    final_validation: dict[str, Any],
    rows: list[dict[str, str]],
    matrix_path: Path,
) -> None:
    expected = config["input_authorization"]["final_gate_required_fields"]
    mismatches = [
        key for key, value in expected.items() if final_gate.get(key) != value
    ]
    if mismatches:
        raise R2T01Error(f"input_final_gate_check:{','.join(mismatches)}")
    if (
        final_validation.get("status") != "passed"
        or final_validation.get("R2_allowed_to_start") is not True
    ):
        raise R2T01Error("input_final_gate_validation_check")
    expected_counts = config["expected_input_counts"]["overall_handoff_status"]
    counts = Counter(row["overall_handoff_status"] for row in rows)
    if len(rows) != config["expected_input_counts"]["row_count"]:
        raise R2T01Error("input_matrix_cardinality_check")
    if len({row["handoff_row_id"] for row in rows}) != len(rows):
        raise R2T01Error("duplicate_handoff_row_check")
    if dict(counts) != expected_counts:
        raise R2T01Error("input_status_count_check")
    if (
        sha256_file(matrix_path)
        != config["inputs"]["expected_sha256"]["decision_matrix"]
    ):
        raise R2T01Error("input_matrix_hash_check")
    _check_final_input_chain(config, final_gate, final_validation, rows)


def _check_final_input_chain(
    config: dict[str, Any],
    final_gate: dict[str, Any],
    final_validation: dict[str, Any],
    rows: list[dict[str, str]],
) -> None:
    paths = config["inputs"]
    final_package_path = ROOT / paths["final_gate_package_path"]
    reviewed_path = ROOT / paths["reviewed_author_package_path"]
    review_path = ROOT / paths["scientific_review_path"]
    handoff_path = ROOT / paths["handoff_manifest_path"]
    reviewed = _load_json(reviewed_path)
    review = _load_json(review_path)
    handoff = _load_json(handoff_path)
    if final_validation.get("final_gate_package_sha256") != sha256_file(
        final_package_path
    ):
        raise R2T01Error("input_final_gate_package_sha_check")
    if final_gate.get("reviewed_author_package_sha256") != sha256_file(reviewed_path):
        raise R2T01Error("input_reviewed_author_package_sha_check")
    if final_gate.get("reviewed_author_package_sha256") != review.get(
        "reviewed_author_package_sha256"
    ):
        raise R2T01Error("input_review_author_package_cross_binding_check")
    if final_gate.get("reviewed_author_package_sha256") != review.get(
        "reviewed_result_package_sha256"
    ):
        raise R2T01Error("input_review_result_package_cross_binding_check")
    if final_gate.get("scientific_review_status") != review.get(
        "scientific_review_status"
    ):
        raise R2T01Error("input_scientific_review_status_binding_check")
    if final_gate.get("independent_review_status") != review.get(
        "independent_review_status"
    ):
        raise R2T01Error("input_independent_review_status_binding_check")
    matrix_sha = config["inputs"]["expected_sha256"]["decision_matrix"]
    if (
        handoff.get("matrix_sha256") != matrix_sha
        or review.get("reviewed_matrix_sha256") != matrix_sha
    ):
        raise R2T01Error("input_handoff_matrix_sha_check")
    if handoff.get("row_count") != len(rows):
        raise R2T01Error("input_handoff_matrix_cardinality_check")
    if (
        reviewed.get("committed_artifacts", {})
        .get(paths["decision_matrix_path"], {})
        .get("sha256")
        != matrix_sha
    ):
        raise R2T01Error("input_reviewed_package_matrix_sha_check")
    expected_head = final_gate.get("reviewed_pr_head_commit")
    if expected_head and not _is_ancestor(expected_head, current_commit(ROOT), ROOT):
        raise R2T01Error("input_pr90_merge_lineage_check")


def _is_ancestor(ancestor: str, descendant: str, root: Path) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def reconcile_sources(
    config: dict[str, Any],
    matrix: list[dict[str, str]],
    candidate_registry: list[dict[str, str]],
    warning_registry: list[dict[str, str]],
    recomputation: list[dict[str, str]],
    upstream: list[dict[str, str]],
) -> list[dict[str, Any]]:
    candidate_by_id = {row["handoff_row_id"]: row for row in candidate_registry}
    matrix_by_id = {row["handoff_row_id"]: row for row in matrix}
    warning_by_id: dict[str, set[str]] = {}
    for row in warning_registry:
        warning_by_id.setdefault(row["handoff_row_id"], set()).add(row["warning_code"])
    recompute_errors = [
        row["handoff_row_id"]
        for row in recomputation
        if row["expected_status"] != row["actual_status"] or row["mismatch_reason"]
    ]
    upstream_failed = [
        row for row in upstream if row["reconciliation_status"] != "passed"
    ]
    rows = []
    for handoff_id in sorted(matrix_by_id):
        source = matrix_by_id[handoff_id]
        candidate = candidate_by_id.get(handoff_id)
        candidate_status = "passed"
        if candidate is None:
            candidate_status = "missing"
        else:
            key_fields = config["reconciliation"]["candidate_registry_key_fields"]
            mismatched = [
                field
                for field in key_fields
                if str(candidate.get(field, "")) != str(source.get(field, ""))
            ]
            if mismatched:
                candidate_status = "mismatch:" + ",".join(mismatched)
        matrix_warnings = set(json.loads(source["warning_codes"]))
        warning_status = (
            "passed"
            if warning_by_id.get(handoff_id, set()) == matrix_warnings
            else "mismatch"
        )
        rows.append(
            {
                "handoff_row_id": handoff_id,
                "candidate_registry_reconciliation": candidate_status,
                "warning_registry_reconciliation": warning_status,
                "decision_recomputation_status": "passed"
                if handoff_id not in recompute_errors
                else "mismatch",
                "source_artifact_hash_check": "passed"
                if _source_hashes_match(source)
                else "failed",
                "source_supersession_check": "passed"
                if _source_current(source)
                else "failed",
            }
        )
    if upstream_failed:
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
            payload = _load_json(path)
        except Exception:
            return False
        if payload.get("superseded") is True or payload.get("status") == "superseded":
            return False
        if payload.get("superseded_by"):
            return False
    return True


def canonical_row(config: dict[str, Any], source: dict[str, str]) -> dict[str, Any]:
    rule = config["source_row_to_route_mapping"][source["handoff_row_id"]]
    role = rule["candidate_role"]
    warnings = json.loads(source["warning_codes"])
    hashes = json.loads(source["source_artifact_hashes"])
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
        "warning_codes": warnings,
        "source_artifact_refs": json.loads(source["source_artifact_refs"]),
        "source_artifact_hashes": hashes,
        "source_matrix_sha256": config["inputs"]["expected_sha256"]["decision_matrix"],
        "contract_version": config["protocol_version"],
    }


def disposition_row(source: dict[str, str], registry: dict[str, Any]) -> dict[str, Any]:
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


def audit_row(
    config: dict[str, Any], source: dict[str, str], actual: dict[str, Any]
) -> dict[str, Any]:
    expected = config["source_row_to_route_mapping"][source["handoff_row_id"]]
    source_warnings = json.loads(source["warning_codes"])
    actual_warnings = actual["warning_codes"]
    return {
        "r1_handoff_row_id": source["handoff_row_id"],
        "observed_handoff_status": source["overall_handoff_status"],
        "observed_q_vector": source["q_or_q_vector"],
        "expected_candidate_role": expected["candidate_role"],
        "actual_candidate_role": actual["candidate_role"],
        "mapping_rule_id": expected["mapping_rule_id"],
        "warning_reconciliation_status": "passed"
        if source_warnings == actual_warnings
        else "failed",
        "selection_path_propagation_status": "passed"
        if (source["selection_path_not_independently_confirmed"] == "True")
        == actual["selection_path_not_independently_confirmed"]
        else "failed",
        "assignment_status": "passed"
        if expected["candidate_role"] == actual["candidate_role"]
        else "failed",
        "failure_reason": "",
    }


def evidence_row(row: dict[str, str]) -> dict[str, Any]:
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
    result["eligible_days"] = _eligible_days(row)
    result["denominator_scope"] = _denominator_scope(row)
    result["metric_source_task"] = _metric_source_task(row)
    result["metric_source_run"] = _metric_source_run(row)
    result["coverage_comparable_group"] = _coverage_comparable_group(row)
    result["coverage_cross_group_comparable"] = "False"
    return result


def _eligible_days(row: dict[str, str]) -> int:
    coverage = float(row["confirmed_coverage"])
    if coverage <= 0:
        return 0
    return round(float(row["confirmed_state_days"]) / coverage)


def _denominator_scope(row: dict[str, str]) -> str:
    if row["handoff_row_id"].startswith("shared_"):
        return "r1_t01_to_t09_strict_common_valid_mixed_scope"
    return "r1_t14_02_same_sample_ordered_short_circuit_scope"


def _metric_source_task(row: dict[str, str]) -> str:
    if row["handoff_row_id"].startswith("shared_"):
        return "R1-T01..R1-T09"
    return "R1-T14-02"


def _metric_source_run(row: dict[str, str]) -> str:
    refs = json.loads(row["source_artifact_hashes"])
    if row["handoff_row_id"].startswith("shared_"):
        return "lineage_mixed_R1-T01_R1-T09"
    path = refs.get("R1-T14-02", {}).get("path", "")
    if not path:
        return "unknown"
    return Path(path).parts[-2]


def _coverage_comparable_group(row: dict[str, str]) -> str:
    if row["handoff_row_id"].startswith("shared_"):
        return f"mixed_scope_shared_q_W{row['W']}_{row['state_line']}"
    if row["state_line"] == "S_PCT":
        return f"same_scope_t14_02_pct_W{row['W']}"
    return f"same_scope_t14_02_pcvt_W{row['W']}"


def anomaly_scan(
    config: dict[str, Any],
    run_id: str,
    code_commit: str,
    source_rows: list[dict[str, str]],
    registry: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    reconciliation: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    role_counts = Counter(row["candidate_role"] for row in registry)
    expected_role_counts = config["expected_role_counts"]
    if dict(role_counts) != expected_role_counts:
        errors.append("role_count_check")
    primary_ids = sorted(
        row["route_id"] for row in registry if row["candidate_role"] == "primary"
    )
    if primary_ids != sorted(config["primary_shortlist_route_ids"]):
        errors.append("primary_shortlist_exact_identity_check")
    for row in registry:
        if row["candidate_role"] == "strict_core_reference":
            if not row["fallback_eligible"] or row["independent_product_eligible"]:
                errors.append(f"fallback_capability_check:{row['r1_handoff_row_id']}")
            if not row["paired_primary_route_id"]:
                errors.append(
                    f"shared_primary_pairing_check:{row['r1_handoff_row_id']}"
                )
        if row["candidate_role"] in {"sensitivity", "excluded"}:
            if (
                row["selection_eligible"]
                or row["fallback_eligible"]
                or row["t03_geometry_role"] != "not_run"
            ):
                errors.append(f"selection_eligibility_check:{row['r1_handoff_row_id']}")
        if row["qT"] == "0.3" and row["candidate_role"] == "primary":
            errors.append("q_vector_role_check:t30_primary")
        if row["qV"] == "0.25" and row["candidate_role"] != "excluded":
            errors.append("q_vector_role_check:v25_not_excluded")
    if any(r["assignment_status"] != "passed" for r in audit):
        errors.append("role_assignment_audit_check")
    if any(r["warning_reconciliation_status"] != "passed" for r in audit):
        errors.append("warning_registry_reconciliation")
    if any(r["selection_path_propagation_status"] != "passed" for r in audit):
        errors.append("selection_path_propagation_check")
    if any(
        row["candidate_registry_reconciliation"] != "passed"
        or row["warning_registry_reconciliation"] != "passed"
        or row["decision_recomputation_status"] != "passed"
        or row["source_artifact_hash_check"] != "passed"
        or row["source_supersession_check"] != "passed"
        for row in reconciliation
    ):
        errors.append("source_reconciliation_check")
    by_window = Counter((row["W"], row["candidate_role"]) for row in registry)
    for window in (120, 250):
        expected = {
            "primary": 2,
            "strict_core_reference": 2,
            "sensitivity": 1,
            "excluded": 1,
        }
        if {role: by_window[(window, role)] for role in expected} != expected:
            errors.append(f"window_role_distribution_check:W{window}")
    flags = Counter(
        row["selection_path_not_independently_confirmed"] for row in registry
    )
    if flags[True] != 8 or flags[False] != 4:
        errors.append("selection_path_flag_distribution_check")
    generic = {
        "primary_output_nonempty": bool(primary_ids),
        "selection_eligible_not_all_zero_or_one": 0
        < sum(r["selection_eligible"] for r in registry)
        < len(registry),
        "fallback_eligible_not_all_zero_or_one": 0
        < sum(r["fallback_eligible"] for r in registry)
        < len(registry),
        "candidate_role_not_single_value": len(role_counts) > 1,
        "required_columns_not_all_null": all(
            row["route_id"] and row["r1_handoff_row_id"] for row in registry
        ),
    }
    for key, passed in generic.items():
        if not passed:
            errors.append(key)
    serialized = json.dumps(
        {"registry": registry, "summary": role_counts}, ensure_ascii=False
    )
    forbidden = [token for token in FORBIDDEN_TOKENS if token in serialized]
    if forbidden:
        errors.append("forbidden_field_check:" + ",".join(forbidden))
    artifact_refs = [
        "data/generated/r2/r2_t01/" + run_id + "/r2_t01_shortlist_registry.csv",
        "data/generated/r2/r2_t01/" + run_id + "/r2_t01_role_assignment_audit.csv",
        "data/generated/r2/r2_t01/" + run_id + "/r2_t01_source_reconciliation.csv",
        "data/generated/r2/r2_t01/" + run_id + "/r2_t01_evidence_snapshot.csv",
    ]
    coverage_groups = Counter(_coverage_comparable_group(row) for row in source_rows)
    source_routes = Counter(row["source_route"] for row in source_rows)
    post_hoc_passed = _post_hoc_selection_passed(source_rows, registry, config)
    readme_passed = _readme_gate_passed(config)
    if not post_hoc_passed:
        errors.append("post_hoc_selection_check")
    if not readme_passed:
        errors.append("README_transition_check")
    checks = {
        "primary_output_nonempty": _check_payload(
            bool(primary_ids),
            "Primary shortlist contains the four pre-registered routes.",
            {"primary_route_count": len(primary_ids)},
            artifact_refs,
        ),
        "all_zero_check": _check_payload(
            len(role_counts) > 1,
            "Registry roles are not degenerate to one all-zero class.",
            {"role_counts": dict(role_counts)},
            artifact_refs,
        ),
        "all_one_check": _check_payload(
            len(role_counts) > 1,
            "Registry roles are not degenerate to one all-one class.",
            {"role_counts": dict(role_counts)},
            artifact_refs,
        ),
        "all_null_check": _check_payload(
            all(row["route_id"] and row["r1_handoff_row_id"] for row in registry),
            "Required identity fields are populated on every registry row.",
            {"registry_rows": len(registry)},
            artifact_refs,
        ),
        "validity_rate_check": _check_payload(
            all(row["r1_handoff_status"] != "blocked_return_to_R0" for row in registry),
            "No blocked_return_to_R0 handoff row entered the R2-T01 registry.",
            dict(Counter(row["r1_handoff_status"] for row in registry)),
            artifact_refs,
        ),
        "coverage_check": _check_payload(
            all(float(row["confirmed_coverage"]) > 0 for row in source_rows),
            "Coverage is positive for all source evidence rows; cross-scope "
            "comparisons are disallowed by denominator metadata.",
            {"coverage_comparable_groups": dict(coverage_groups)},
            artifact_refs,
        ),
        "parameter_response_check": _not_applicable(
            "R2-T01 does not scan parameters; it validates deterministic role "
            "disposition of R1-T10 handed-off rows.",
            artifact_refs,
        ),
        "baseline_challenger_check": _check_payload(
            role_counts["strict_core_reference"] == 4
            and role_counts["primary"] == 4
            and role_counts["sensitivity"] == 2
            and role_counts["excluded"] == 2,
            "Shared-q, q-vector center, qT sensitivity, and qV excluded cohorts "
            "are all present as deterministic dispositions.",
            {"role_counts": dict(role_counts)},
            artifact_refs,
        ),
        "nested_invariant_check": _not_applicable(
            "Nested-state truth tables are not recomputed in R2-T01; upstream "
            "source hashes and current package status are checked instead.",
            artifact_refs,
        ),
        "funnel_accounting_check": _check_payload(
            len(source_rows) == len(registry) == len(audit) == len(reconciliation),
            "Source matrix, registry, audit, and reconciliation preserve the "
            "12-row handoff cardinality.",
            {
                "source_rows": len(source_rows),
                "registry_rows": len(registry),
                "audit_rows": len(audit),
                "reconciliation_rows": len(reconciliation),
            },
            artifact_refs,
        ),
        "denominator_integrity_check": _check_payload(
            len(coverage_groups) >= 4
            and all(float(r["confirmed_coverage"]) > 0 for r in source_rows),
            "Denominator scopes are explicitly separated into comparable groups "
            "and eligible_days are derivable.",
            {"coverage_comparable_groups": dict(coverage_groups)},
            artifact_refs,
        ),
        "sample_size_check": _check_payload(
            len(source_rows) == config["expected_input_counts"]["row_count"],
            "Input row count matches the authorized R1-T10 handoff matrix.",
            {"source_rows": len(source_rows)},
            artifact_refs,
        ),
        "upstream_consistency_check": _check_payload(
            all(
                row["candidate_registry_reconciliation"] == "passed"
                and row["warning_registry_reconciliation"] == "passed"
                and row["decision_recomputation_status"] == "passed"
                and row["source_artifact_hash_check"] == "passed"
                and row["source_supersession_check"] == "passed"
                for row in reconciliation
            ),
            "R1-T10 source registries, warnings, recomputation rows, source "
            "hashes, and current-status checks passed.",
            {"reconciliation_rows": len(reconciliation)},
            artifact_refs,
        ),
        "scale_shift_check": _check_payload(
            all(0 < float(row["confirmed_coverage"]) < 1 for row in source_rows)
            and all(float(row["association_lift"]) > 0 for row in source_rows),
            "Coverage proportions and lift values are in expected positive ranges.",
            {"source_routes": dict(source_routes)},
            artifact_refs,
        ),
        "time_alignment_check": _check_payload(
            all(_source_hashes_match(row) for row in source_rows),
            "All row-level source artifact hashes resolve to current committed bytes.",
            {"source_rows": len(source_rows)},
            artifact_refs,
        ),
        "future_leakage_check": _check_payload(
            not forbidden,
            "Registry serialization contains no forbidden d/g/event/future/"
            "freeze/backtest fields.",
            {"forbidden_tokens": forbidden},
            artifact_refs,
        ),
        "post_hoc_selection_check": _check_payload(
            post_hoc_passed,
            "Primary routes exactly match the pre-registered config and "
            "row-level selection-path limitations are preserved.",
            {"primary_route_ids": primary_ids, "selection_path_flags": dict(flags)},
            artifact_refs,
        ),
        "conclusion_support_check": _check_payload(
            not errors,
            "Conclusions are limited to deterministic 12-row registry "
            "disposition and keep downstream gates closed.",
            {"blocking_error_count": len(errors)},
            artifact_refs,
        ),
    }
    determinism_status = "passed" if not errors else "blocked"
    return {
        "task_id": "R2-T01",
        "run_id": run_id,
        "code_commit": code_commit,
        "scan_status": "passed" if not errors else "blocked",
        "status": "passed" if not errors else "blocked",
        "checks": checks,
        "blocking_anomalies": [
            name for name, payload in checks.items() if payload["status"] == "blocked"
        ],
        "unresolved_questions": [],
        "blocking_errors": errors,
        "generic_checks": generic,
        "role_counts": dict(role_counts),
        "selection_path_flag_counts": {str(k): v for k, v in flags.items()},
        "post_hoc_selection_check": "passed" if post_hoc_passed else "blocked",
        "deterministic_output_check": determinism_status,
        "README_transition_check": "passed" if readme_passed else "blocked",
    }


def _check_payload(
    passed: bool,
    rationale: str,
    metrics: dict[str, Any],
    artifact_refs: list[str],
) -> dict[str, Any]:
    return {
        "status": "passed" if passed else "blocked",
        "rationale": rationale,
        "metrics": metrics,
        "artifact_references": artifact_refs,
    }


def _not_applicable(
    rationale: str, artifact_refs: list[str] | None = None
) -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "rationale": rationale,
        "metrics": {},
        "artifact_references": artifact_refs or [],
    }


def _post_hoc_selection_passed(
    source_rows: list[dict[str, str]],
    registry: list[dict[str, Any]],
    config: dict[str, Any],
) -> bool:
    actual_primary = sorted(
        row["route_id"] for row in registry if row["candidate_role"] == "primary"
    )
    if actual_primary != sorted(config["primary_shortlist_route_ids"]):
        return False
    by_id = {row["r1_handoff_row_id"]: row for row in registry}
    for source in source_rows:
        actual = by_id.get(source["handoff_row_id"])
        if actual is None:
            return False
        if (source["selection_path_not_independently_confirmed"] == "True") != actual[
            "selection_path_not_independently_confirmed"
        ]:
            return False
    return True


def _readme_gate_passed(config: dict[str, Any]) -> bool:
    readme = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
    gate = config["author_draft_gate_state"]
    required = [
        gate["current_stage"],
        gate["current_task"],
        gate["next_planned_task"],
        "R2-T02_allowed_to_start: false",
        "R3_allowed_to_start: false",
    ]
    return all(token in readme for token in required)


def experiment_summary(
    config: dict[str, Any],
    run_id: str,
    source_rows: list[dict[str, str]],
    registry: list[dict[str, Any]],
    anomalies: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": "R2-T01",
        "run_id": run_id,
        "task_class": config["task_class"],
        "protocol_version": config["protocol_version"],
        "source_row_count": len(source_rows),
        "canonical_registry_row_count": len(registry),
        "role_counts": dict(Counter(row["candidate_role"] for row in registry)),
        "primary_route_ids": [
            row["route_id"] for row in registry if row["candidate_role"] == "primary"
        ],
        "scientific_review_status": "pending",
        "independent_review_status": "pending",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
        "downstream_gate_allowed": False,
        "R2-T02_allowed_to_start": False,
        "anomaly_status": anomalies["status"],
    }


def diagnostic_summary(
    config: dict[str, Any],
    registry: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    reconciliation: list[dict[str, Any]],
    anomalies: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_id": "R2-T01",
        "role_counts": dict(Counter(row["candidate_role"] for row in registry)),
        "window_role_counts": {
            f"W{window}": dict(
                Counter(row["candidate_role"] for row in registry if row["W"] == window)
            )
            for window in (120, 250)
        },
        "audit_failed_count": sum(
            row["assignment_status"] != "passed" for row in audit
        ),
        "warning_reconciliation_failed_count": sum(
            row["warning_reconciliation_status"] != "passed" for row in audit
        ),
        "source_reconciliation_failed_count": sum(
            row["source_artifact_hash_check"] != "passed"
            or row["source_supersession_check"] != "passed"
            for row in reconciliation
        ),
        "anomaly_blocking_error_count": len(anomalies["blocking_errors"]),
    }


def input_binding_payload(
    config: dict[str, Any], config_path: Path, rows: list[dict[str, str]], root: Path
) -> dict[str, Any]:
    artifacts = {}
    for key, rel in config["inputs"].items():
        if key == "expected_sha256":
            continue
        path = root / rel
        artifacts[key] = {"path": rel, "sha256": sha256_file(path)}
    return {
        "task_id": "R2-T01",
        "config_path": repo_rel(config_path),
        "config_sha256": sha256_file(config_path),
        "input_artifacts": artifacts,
        "decision_matrix_row_count": len(rows),
        "decision_matrix_status_counts": dict(
            Counter(row["overall_handoff_status"] for row in rows)
        ),
        "bound_at_utc": datetime.now(UTC).isoformat(),
    }


def pending_review(run_id: str, registry: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_id": "R2-T01",
        "run_id": run_id,
        "scientific_review_status": "pending",
        "independent_review_status": "pending",
        "implementation_actor": "codex",
        "reviewer_identity": None,
        "independence_attestation": False,
        "blocking_findings": ["pending_independent_scientific_review"],
        "required_independent_recomputations": [
            "primary_route_identity",
            "one_shared_primary_pairing",
            "one_sensitivity_disposition",
            "one_excluded_disposition",
            "role_count_4_4_2_2",
            "selection_path_flag_propagation",
        ],
    }


def _sort_key(row: dict[str, str]) -> tuple[int, str, int, str]:
    # Config-independent stable grouping for source rows before canonical mapping.
    if row["handoff_row_id"].startswith("q_") and row["qT"] == "0.3":
        order = 2
    elif row["handoff_row_id"].startswith("q_") and row["qV"] == "0.25":
        order = 3
    elif row["handoff_row_id"].startswith("shared_"):
        order = 1
    else:
        order = 0
    return (order, row["state_line"], int(row["W"]), row["handoff_row_id"])
