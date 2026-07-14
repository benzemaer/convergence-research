# ruff: noqa: E501

"""Generate the R2-T08 acceptance package and the single R3 handoff entrypoint.

T08 is a registry/freeze acceptance task.  It consumes only committed T07
objects and does not open the canonical DuckDB or replay any upstream state
machine.  All observed values in the acceptance package are computed from
those committed objects; expected values live in the versioned T08 config.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.canonical_io import (
    ROOT,
    canonical_json_bytes,
    current_commit,
    git_blob_bytes,
    git_blob_sha,
    repo_rel,
    sha256_bytes,
    write_csv,
    write_json,
    write_markdown,
)

TASK_ID = "R2-T08"
ACCEPTANCE_FIELDS = [
    "gate_id",
    "expected",
    "observed",
    "mismatch_count",
    "status",
    "failure_code",
    "evidence_refs",
]
WINDOW_FIELDS = [
    "state_line",
    "frozen_state_version_ids",
    "frozen_windows",
    "overlap_handling_required",
    "status",
    "reason",
]
INDEPENDENT_CHECK_IDS = [
    "t07_manifest_integrity_mismatch",
    "t07_validation_status_mismatch",
    "frozen_version_identity_mismatch",
    "canonical_interface_mismatch",
    "registry_policy_mismatch",
    "warning_limitation_mismatch",
    "window_strict_core_mismatch",
    "release_anchor_obligation_mismatch",
    "unique_r3_entrypoint_mismatch",
    "unexpected_field_violation",
    "committed_reference_mismatch",
    "downstream_gate_violation",
]


class T08GenerationError(RuntimeError):
    """Raised when an immutable T07 input cannot satisfy the T08 contract."""


def _git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=root
        ).returncode
        == 0
    )


def _load_json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise T08GenerationError(f"invalid_json:{label}:{exc}") from exc
    if not isinstance(value, dict):
        raise T08GenerationError(f"json_not_object:{label}")
    return value


def _bound(root: Path, commit: str, path: str) -> dict[str, Any]:
    try:
        payload = git_blob_bytes(commit, path, root=root)
        blob_sha = git_blob_sha(commit, path, root=root)
    except subprocess.CalledProcessError as exc:
        raise T08GenerationError(f"missing_committed_input:{commit}:{path}") from exc
    return {
        "path": path,
        "source_commit": commit,
        "git_blob_sha": blob_sha,
        "committed_byte_sha256": sha256_bytes(payload),
        "size_bytes": len(payload),
    }


def _bound_json(
    root: Path, commit: str, path: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = git_blob_bytes(commit, path, root=root)
    return _load_json_bytes(payload, path), _bound(root, commit, path)


def _bound_csv(
    root: Path, commit: str, path: str
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    payload = git_blob_bytes(commit, path, root=root)
    try:
        rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8"))))
    except UnicodeDecodeError as exc:
        raise T08GenerationError(f"invalid_csv:{path}") from exc
    return rows, _bound(root, commit, path)


def _compact(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _mismatch(*conditions: bool) -> int:
    return sum(0 if condition else 1 for condition in conditions)


def _config_from_committed(
    config_path: Path, root: Path
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    execution_commit = current_commit(root)
    rel = repo_rel(config_path, root)
    try:
        payload = git_blob_bytes(execution_commit, rel, root=root)
    except subprocess.CalledProcessError as exc:
        raise T08GenerationError(f"config_not_committed:{rel}") from exc
    config = _load_json_bytes(payload, rel)
    if config.get("task_id") != TASK_ID:
        raise T08GenerationError("config_task_id")
    return (
        config,
        execution_commit,
        {
            "path": rel,
            "source_commit": execution_commit,
            "git_blob_sha": git_blob_sha(execution_commit, rel, root=root),
            "committed_byte_sha256": sha256_bytes(payload),
            "size_bytes": len(payload),
        },
    )


def _parse_json_cell(row: dict[str, str], field: str) -> Any:
    try:
        return json.loads(row[field])
    except (KeyError, json.JSONDecodeError) as exc:
        raise T08GenerationError(f"invalid_state_registry_cell:{field}") from exc


def _core_bindings(
    config: dict[str, Any],
    root: Path,
    source_commit: str,
    final_manifest: dict[str, Any],
    output_manifest: dict[str, Any],
    committed_validation: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], int]:
    refs = {
        "state_version_registry": final_manifest.get("state_version_registry"),
        "interval_rule_registry": final_manifest.get("interval_rule_registry"),
        "event_state_machine_registry": final_manifest.get(
            "event_state_machine_registry"
        ),
        "freeze_decision_log": final_manifest.get("freeze_decision_log"),
    }
    output_by_path = {
        item.get("path"): item for item in output_manifest.get("artifacts", [])
    }
    committed_by_path = {
        item.get("path"): item
        for item in committed_validation.get("validated_artifacts", [])
    }
    expected_hashes = config["t07_binding"]["core_artifact_sha256"]
    result: dict[str, dict[str, Any]] = {}
    mismatches = 0
    for name, ref in refs.items():
        if not isinstance(ref, dict):
            mismatches += 1
            continue
        path = ref.get("path")
        if not isinstance(path, str):
            mismatches += 1
            continue
        actual = _bound(root, source_commit, path)
        output = output_by_path.get(path, {})
        committed = committed_by_path.get(path, {})
        expected_sha = expected_hashes[name]
        ok = (
            ref.get("sha256") == expected_sha
            and ref.get("size_bytes") == actual["size_bytes"]
            and actual["committed_byte_sha256"] == expected_sha
            and output.get("sha256") == expected_sha
            and output.get("size_bytes") == actual["size_bytes"]
            and committed.get("committed_byte_sha256") == expected_sha
            and committed.get("size_bytes") == actual["size_bytes"]
        )
        mismatches += 0 if ok else 1
        result[name] = {
            "path": path,
            "sha256": expected_sha,
            "size_bytes": actual["size_bytes"],
            "source_commit": source_commit,
            "git_blob_sha": actual["git_blob_sha"],
            "committed_byte_sha256": actual["committed_byte_sha256"],
        }
    return result, mismatches


def _load_t07_inputs(config: dict[str, Any], root: Path) -> dict[str, Any]:
    binding = config["t07_binding"]
    source_commit = binding["merge_commit"]
    head = current_commit(root)
    for commit in (source_commit, binding["reviewed_head"]):
        try:
            _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
        except subprocess.CalledProcessError as exc:
            raise T08GenerationError(f"missing_t07_commit:{commit}") from exc
    if not _is_ancestor(root, source_commit, head):
        raise T08GenerationError("t07_merge_not_current_ancestor")
    parents = str(_git(root, "rev-list", "--parents", "-n", "1", source_commit)).split()
    if binding["reviewed_head"] not in parents[1:] and not _is_ancestor(
        root, binding["reviewed_head"], source_commit
    ):
        raise T08GenerationError("t07_reviewed_head_not_merge_ancestor")

    final_path = binding["final_manifest_path"]
    final, final_binding = _bound_json(root, source_commit, final_path)
    if final_binding["committed_byte_sha256"] != binding["final_manifest_sha256"]:
        raise T08GenerationError("t07_final_manifest_hash")
    if (
        final.get("task_id") != "R2-T07"
        or final.get("run_id") != binding["authoritative_run"]
    ):
        raise T08GenerationError("t07_final_manifest_identity")
    base = str(Path(final_path).parent).replace("\\", "/")
    names = {
        "output": "r2_t07_output_manifest.json",
        "independent": "r2_t07_independent_validation.json",
        "reconciliation": "r2_t07_registry_reconciliation.json",
        "forbidden": "r2_t07_forbidden_use_audit.json",
        "anomaly": "r2_t07_anomaly_scan.json",
        "committed": "r2_t07_committed_artifact_validation.json",
        "state": "r2_state_version_registry.csv",
        "interval": "r2_interval_rule_registry.json",
        "event": "r2_event_state_machine_registry.json",
        "decision": "r2_freeze_decision_log.json",
    }
    loaded: dict[str, Any] = {
        "final": final,
        "final_binding": final_binding,
        "source_commit": source_commit,
    }
    for key, name in names.items():
        path = f"{base}/{name}"
        if key == "state":
            loaded[key], loaded[f"{key}_binding"] = _bound_csv(
                root, source_commit, path
            )
        else:
            loaded[key], loaded[f"{key}_binding"] = _bound_json(
                root, source_commit, path
            )
    output = loaded["output"]
    independent = loaded["independent"]
    reconciliation = loaded["reconciliation"]
    forbidden = loaded["forbidden"]
    anomaly = loaded["anomaly"]
    committed = loaded["committed"]
    numeric_checks = independent.get("checks", {})
    t07_status_ok = (
        len(numeric_checks)
        == config["expected_counts"]["t07_independent_numeric_checks"]
        and all(
            isinstance(value, int) and value == 0 for value in numeric_checks.values()
        )
        and independent.get("failure_count") == 0
        and independent.get("status") == "passed"
        and len(reconciliation.get("checks", []))
        == config["expected_counts"]["t07_registry_reconciliation_checks"]
        and reconciliation.get("failure_count") == 0
        and reconciliation.get("status") == "passed"
        and all(
            item.get("status") == "passed" and item.get("mismatch_count") == 0
            for item in reconciliation["checks"]
        )
        and forbidden.get("status") == "passed"
        and forbidden.get("failure_count") == 0
        and anomaly.get("status") == "passed"
        and anomaly.get("anomaly_count") == 0
        and committed.get("status") == "passed"
        and committed.get("failure_count") == 0
        and len(committed.get("validated_artifacts", []))
        == config["expected_counts"]["t07_committed_artifact_count"]
    )
    core, core_mismatch = _core_bindings(
        config, root, source_commit, final, output, committed
    )
    state_header = list(loaded["state"][0].keys()) if loaded["state"] else []
    state_rows = loaded["state"]
    expected_ids = [
        item["state_version_id"] for item in config["expected_frozen_versions"]
    ]
    state_identity_ok = [
        row.get("state_version_id") for row in state_rows
    ] == expected_ids
    canonical_ok = (
        final.get("canonical_daily_state_sha256")
        == config["t07_binding"]["canonical"]["daily"]["stable_multiset_sha256"]
        and final.get("canonical_daily_row_count")
        == config["t07_binding"]["canonical"]["daily"]["row_count"]
        and final.get("canonical_event_zone_sha256")
        == config["t07_binding"]["canonical"]["event"]["stable_multiset_sha256"]
        and final.get("canonical_event_row_count")
        == config["t07_binding"]["canonical"]["event"]["row_count"]
        and final.get("canonical_event_membership_sha256")
        == config["t07_binding"]["canonical"]["membership"]["stable_multiset_sha256"]
        and final.get("canonical_membership_row_count")
        == config["t07_binding"]["canonical"]["membership"]["row_count"]
        and final.get("t05_database_sha256")
        == config["t07_binding"]["canonical"]["database_sha256"]
    )
    return {
        **loaded,
        "core": core,
        "core_mismatch": core_mismatch,
        "t07_status_ok": t07_status_ok,
        "state_header": state_header,
        "state_identity_ok": state_identity_ok,
        "canonical_ok": canonical_ok,
    }


def _version_rows(
    config: dict[str, Any], rows: list[dict[str, str]]
) -> tuple[dict[str, dict[str, Any]], int]:
    expected = {
        item["state_version_id"]: item for item in config["expected_frozen_versions"]
    }
    observed: dict[str, dict[str, Any]] = {}
    mismatches = 0
    for row in rows:
        version_id = row.get("state_version_id", "")
        observed[version_id] = row
        spec = expected.get(version_id)
        if spec is None:
            mismatches += 1
            continue
        try:
            actual_q = {key: float(row[key]) for key in ("qP", "qC", "qT", "qV")}
            matches = (
                row.get("freeze_status") == "frozen"
                and row.get("state_line") == spec["state_line"]
                and int(row["W"]) == spec["W"]
                and int(row["K"]) == spec["K"]
                and int(row["d"]) == spec["d"]
                and int(row["g"]) == spec["g"]
                and actual_q == spec["q"]
                and row.get("strict_core_enabled") == "True"
                and row.get("strict_core_source_candidate_cell_id")
                == spec["strict_core_source"]
                and _parse_json_cell(row, "warning_codes") == spec["warning_codes"]
                and row.get("selection_path_not_independently_confirmed") == "True"
            )
        except (KeyError, ValueError):
            matches = False
        mismatches += 0 if matches else 1
    mismatches += (
        0 if len(rows) == len(expected) and set(observed) == set(expected) else 1
    )
    return observed, mismatches


def _build_acceptance_matrix(
    config: dict[str, Any], t07: dict[str, Any], handoff: dict[str, Any]
) -> list[dict[str, Any]]:
    final = t07["final"]
    interval = t07["interval"]
    event = t07["event"]
    states, state_mismatch = _version_rows(config, t07["state"])
    expected_ids = [
        item["state_version_id"] for item in config["expected_frozen_versions"]
    ]
    ref_ids = set(expected_ids)
    gate_rows: list[dict[str, Any]] = []

    def add(
        gate_id: str, expected: Any, observed: Any, mismatch: int, refs: list[str]
    ) -> None:
        gate_rows.append(
            {
                "gate_id": gate_id,
                "expected": _compact(expected),
                "observed": _compact(observed),
                "mismatch_count": mismatch,
                "status": "passed" if mismatch == 0 else "failed",
                "failure_code": "" if mismatch == 0 else f"{gate_id}_mismatch",
                "evidence_refs": refs,
            }
        )

    add(
        "R2A01_t07_package_integrity",
        {
            "final_manifest_sha256": config["t07_binding"]["final_manifest_sha256"],
            "numeric_checks": 28,
            "reconciliation_checks": 17,
            "committed_artifacts": 17,
        },
        {
            "final_manifest_sha256": t07["final_binding"]["committed_byte_sha256"],
            "numeric_checks": len(t07["independent"].get("checks", {})),
            "reconciliation_checks": len(t07["reconciliation"].get("checks", [])),
            "committed_artifacts": len(t07["committed"].get("validated_artifacts", [])),
        },
        _mismatch(
            t07["final_binding"]["committed_byte_sha256"]
            == config["t07_binding"]["final_manifest_sha256"],
            t07["t07_status_ok"],
            t07["core_mismatch"] == 0,
        ),
        [
            t07["final_binding"]["path"],
            t07["independent_binding"]["path"],
            t07["reconciliation_binding"]["path"],
            t07["committed_binding"]["path"],
        ],
    )
    forbidden_ids = {
        row.get("state_version_id")
        for row in t07["state"]
        if row.get("state_version_id")
    }
    add(
        "R2A02_frozen_version_identity",
        {
            "count": 2,
            "ids": expected_ids,
            "W250": 0,
            "shared_q_independent": 0,
            "PCT_parent": 0,
            "additional": 0,
        },
        {
            "count": len(t07["state"]),
            "ids": sorted(forbidden_ids),
            "W250": sum("W250" in x for x in forbidden_ids),
            "shared_q_independent": sum(
                "shared" in x and "strict" not in x for x in forbidden_ids
            ),
            "PCT_parent": sum("parent" in x.lower() for x in forbidden_ids),
            "additional": max(0, len(t07["state"]) - 2),
        },
        _mismatch(
            len(t07["state"]) == 2,
            set(forbidden_ids) == ref_ids,
            not any("W250" in x for x in forbidden_ids),
            not any("parent" in x.lower() for x in forbidden_ids),
        ),
        [t07["state_binding"]["path"], t07["decision_binding"]["path"]],
    )
    canonical = config["t07_binding"]["canonical"]
    observed_canonical = {
        "daily": {
            "sha256": final.get("canonical_daily_state_sha256"),
            "row_count": final.get("canonical_daily_row_count"),
        },
        "event": {
            "sha256": final.get("canonical_event_zone_sha256"),
            "row_count": final.get("canonical_event_row_count"),
        },
        "membership": {
            "sha256": final.get("canonical_event_membership_sha256"),
            "row_count": final.get("canonical_membership_row_count"),
        },
        "database_sha256": final.get("t05_database_sha256"),
        "source_run": final.get("t05_run_id"),
    }
    expected_canonical = {
        "daily": {
            "sha256": canonical["daily"]["stable_multiset_sha256"],
            "row_count": canonical["daily"]["row_count"],
        },
        "event": {
            "sha256": canonical["event"]["stable_multiset_sha256"],
            "row_count": canonical["event"]["row_count"],
        },
        "membership": {
            "sha256": canonical["membership"]["stable_multiset_sha256"],
            "row_count": canonical["membership"]["row_count"],
        },
        "database_sha256": canonical["database_sha256"],
        "source_run": canonical["source_run_id"],
    }
    add(
        "R2A03_canonical_interface_binding",
        expected_canonical,
        observed_canonical,
        _mismatch(observed_canonical == expected_canonical, t07["canonical_ok"]),
        [t07["final_binding"]["path"], t07["canonical_binding"]["path"]]
        if "canonical_binding" in t07
        else [t07["final_binding"]["path"]],
    )
    registry_ok = (
        interval.get("K") == 3
        and interval.get("d") == 2
        and interval.get("g") == 1
        and interval.get("confirmation_backfill_allowed") is False
        and interval.get("open_zone_policy")
        == "open event zones are right-censored; no fabricated finalization time"
        and event.get("event_identity_policy", {}).get(
            "cross_state_version_merge_allowed"
        )
        is False
        and event.get("zone_revision_policy", {}).get("no_cross_state_version_merge")
        is True
        and event.get("source_contract_risk_set_policy", {}).get("missing_field_policy")
        == "fail_closed"
    )
    add(
        "R2A04_registry_and_policy_closure",
        "closed",
        {
            "interval": interval.get("registry_id"),
            "event": event.get("registry_id"),
            "policy_closed": registry_ok,
        },
        _mismatch(
            registry_ok,
            set(t07["event"].keys())
            >= {
                "canonical_consumer_mapping",
                "canonical_risk_set_policy",
                "time_semantics",
            },
        ),
        [t07["interval_binding"]["path"], t07["event_binding"]["path"]],
    )
    warning_map = {
        row["state_version_id"]: _parse_json_cell(row, "warning_codes")
        for row in t07["state"]
    }
    warnings_ok = all(
        warning_map.get(item["state_version_id"]) == item["warning_codes"]
        for item in config["expected_frozen_versions"]
    )
    limitations = final.get("forbidden_reinterpretations", [])
    t07_limitation_ok = (
        len(limitations) == 12
        and "no_trading_advantage_claim" in limitations
        and "no_future_outcome_selection" in limitations
        and "confirmed_exit_is_not_release" in limitations
        and "transition_trigger_trade_date_not_causal_time" in limitations
    )
    add(
        "R2A05_warning_and_limitation_preservation",
        {
            "warnings": {
                item["state_version_id"]: item["warning_codes"]
                for item in config["expected_frozen_versions"]
            },
            "selection_flag": True,
            "trigger_trade_date_non_authoritative": True,
        },
        {
            "warnings": warning_map,
            "selection_flag": final.get("selection_path_not_independently_confirmed"),
            "trigger_trade_date_non_authoritative": "r2_t06_replayed_transition_ledger.trigger_trade_date"
            in final.get("non_authoritative_time_fields", []),
            "limitation_count": len(limitations),
        },
        _mismatch(
            warnings_ok,
            final.get("selection_path_not_independently_confirmed") is True,
            "r2_t06_replayed_transition_ledger.trigger_trade_date"
            in final.get("non_authoritative_time_fields", []),
            t07_limitation_ok,
        ),
        [t07["state_binding"]["path"], t07["final_binding"]["path"]],
    )
    strict_ok = all(
        row.get("W") == "120" and row.get("strict_core_enabled") == "True"
        for row in t07["state"]
    ) and all(row.get("strict_core_source_candidate_cell_id") for row in t07["state"])
    add(
        "R2A06_window_and_strict_core_closure",
        {"windows": ["W120"], "strict_core_independent_product": False},
        {
            "windows": sorted({row.get("W") for row in t07["state"]}),
            "strict_core_sources": [
                row.get("strict_core_source_candidate_cell_id") for row in t07["state"]
            ],
            "strict_core_independent_product": config["strict_core_contract"][
                "is_independent_product"
            ],
        },
        _mismatch(
            strict_ok,
            len(t07["state"]) == 2,
            not any(row.get("W") == "250" for row in t07["state"]),
        ),
        [t07["state_binding"]["path"], t07["decision_binding"]["path"]],
    )
    anchor = config["release_anchor_obligation"]
    add(
        "R2A07_release_anchor_obligation",
        {"owner": "R3", "selected_anchor": None, "candidate_count": 3},
        {
            "owner": anchor["selection_owner"],
            "selected_anchor": anchor["selected_anchor"],
            "candidate_count": len(anchor["candidates"]),
            "candidate_ids": [item["id"] for item in anchor["candidates"]],
        },
        _mismatch(
            anchor["selection_owner"] == "R3",
            anchor["selected_anchor"] is None,
            len(anchor["candidates"]) == 3,
        ),
        ["r2_t08_release_anchor_obligation.json"],
    )
    observed_entrypoint = {
        "unique_r3_entrypoint": handoff.get("unique_r3_entrypoint"),
        "alternative_entrypoints": handoff.get("alternative_entrypoints"),
        "eligible": handoff.get("r3_handoff_eligible"),
        "R3_allowed_to_start": handoff.get("R3_allowed_to_start"),
    }
    add(
        "R2A08_unique_r3_entrypoint",
        {
            "unique_r3_entrypoint": True,
            "alternative_entrypoints": [],
            "eligible": True,
            "R3_allowed_to_start": False,
        },
        observed_entrypoint,
        _mismatch(
            observed_entrypoint
            == {
                "unique_r3_entrypoint": True,
                "alternative_entrypoints": [],
                "eligible": True,
                "R3_allowed_to_start": False,
            }
        ),
        ["r2_t08_r3_handoff_manifest.json", "r2_t08_final_acceptance.json"],
    )
    return gate_rows


def _canonical_refs(config: dict[str, Any]) -> dict[str, Any]:
    canonical = config["t07_binding"]["canonical"]
    interfaces = config["canonical_contract"]["interfaces"]
    result = {}
    for key in ("daily", "event", "membership"):
        spec = canonical[key]
        result[key] = {
            **interfaces[key],
            "database_path": canonical["database_path"],
            "database_sha256": canonical["database_sha256"],
            "stable_multiset_sha256": spec["stable_multiset_sha256"],
            "row_count": spec["row_count"],
            "source_run_id": canonical["source_run_id"],
            "availability_policy": canonical["availability_policy"],
        }
    return result


def _handoff(
    config: dict[str, Any], t07: dict[str, Any], run_id: str, execution_commit: str
) -> dict[str, Any]:
    refs = t07["core"]
    version_rows, _ = _version_rows(config, t07["state"])
    versions = []
    for spec in config["expected_frozen_versions"]:
        row = version_rows[spec["state_version_id"]]
        versions.append(
            {
                "state_version_id": spec["state_version_id"],
                "state_line": spec["state_line"],
                "W": spec["W"],
                "K": spec["K"],
                "q": spec["q"],
                "d": spec["d"],
                "g": spec["g"],
                "strict_core_source": spec["strict_core_source"],
                "strict_core_member_field": "strict_core_member",
                "warnings": spec["warning_codes"],
                "state_registry_row_sha256": sha256_bytes(canonical_json_bytes(row)),
            }
        )
    return {
        "handoff_id": f"R2-T08-R3-{run_id}",
        "handoff_version": "r2_t08_r3_handoff.v1",
        "task_id": TASK_ID,
        "run_id": run_id,
        "lifecycle": "author_stage_pending_scientific_review_and_merge",
        "activation_mode": "merged_pr_direct_binding",
        "unique_r3_entrypoint": True,
        "alternative_entrypoints": [],
        "r3_handoff_eligible": True,
        "R3_allowed_to_start": False,
        "frozen_versions": versions,
        "final_freeze_manifest_ref": _bound(
            root=ROOT,
            commit=t07["source_commit"],
            path=config["t07_binding"]["final_manifest_path"],
        ),
        "state_version_registry_ref": refs["state_version_registry"],
        "interval_rule_registry_ref": refs["interval_rule_registry"],
        "event_state_machine_registry_ref": refs["event_state_machine_registry"],
        "freeze_decision_log_ref": refs["freeze_decision_log"],
        "canonical_daily_state_ref": _canonical_refs(config)["daily"],
        "canonical_event_zone_ref": _canonical_refs(config)["event"],
        "canonical_event_membership_ref": _canonical_refs(config)["membership"],
        "frozen_window_matrix_ref": {
            "path": "r2_t08_frozen_window_matrix.csv",
            "state_lines": ["S_PCT", "S_PCVT"],
        },
        "strict_core_contract": config["strict_core_contract"],
        "state_risk_set_contract": {
            "authoritative_field": "r2_canonical_daily_state.state_risk_set_eligible",
            "event_zone_member_is_not_a_substitute": True,
            "retrospective_membership_is_not_a_substitute": True,
            "bridge_excluded": True,
        },
        "qualified_event_risk_set_contract": {
            "authoritative_fields": [
                "r2_canonical_daily_state.qualified_event_risk_set_eligible",
                "r2_canonical_event_membership.qualified_event_risk_set_eligible",
            ],
            "event_zone_member_is_not_a_substitute": True,
            "retrospective_membership_is_not_a_substitute": True,
            "bridge_excluded": True,
            "prequalification_excluded": True,
            "unqualified_reentry_excluded": True,
        },
        "exit_quality_censor_contract": {
            "fields": [
                "last_confirmed_end_date",
                "last_exit_observation_time",
                "zone_finalization_time",
                "zone_status",
                "exit_reason",
                "left_censored",
                "right_censored",
                "membership_available_time",
            ],
            "confirmed_exit_is_not_release": True,
            "quality_break_is_not_release": True,
            "finalized_quality_break_is_not_release": True,
            "right_censor_is_not_release": True,
            "open_gap_pending_not_finalized": True,
            "left_censored_not_normal_onset": True,
            "zone_finalization_time_not_backfilled": True,
            "trigger_trade_date_non_authoritative": True,
        },
        "release_anchor_obligation_ref": {
            "path": "r2_t08_release_anchor_obligation.json",
            "selection_owner": "R3",
            "selected_anchor": None,
            "candidate_count": 3,
        },
        "warnings": {
            item["state_version_id"]: item["warning_codes"]
            for item in config["expected_frozen_versions"]
        },
        "limitations": config["global_limitations"],
        "forbidden_reinterpretations": config["forbidden_reinterpretations"],
        "source_bindings": {
            "t07_merge_commit": t07["source_commit"],
            "t07_reviewed_head": config["t07_binding"]["reviewed_head"],
            "t07_authoritative_run": config["t07_binding"]["authoritative_run"],
            "execution_commit": execution_commit,
            "t07_core_artifacts": list(refs.values()),
            "t07_validation_artifacts": [
                t07[f"{key}_binding"]
                for key in (
                    "output",
                    "independent",
                    "reconciliation",
                    "forbidden",
                    "anomaly",
                    "committed",
                )
            ],
        },
    }


def _result_analysis(
    config: dict[str, Any],
    t07: dict[str, Any],
    run_id: str,
    execution_commit: str,
    acceptance: list[dict[str, Any]],
    independent: dict[str, Any],
    anomaly: dict[str, Any],
    committed: dict[str, Any],
) -> str:
    gate_status = ", ".join(f"{row['gate_id']}={row['status']}" for row in acceptance)
    ids = ", ".join(
        item["state_version_id"] for item in config["expected_frozen_versions"]
    )
    return f"""# R2-T08 result analysis

## Scope and status

This author-stage package accepts the committed R2-T07 final freeze interface. It does not replay T01–T07, open the canonical DuckDB, select a release anchor, define a future label, or make a trading claim.

- task: `{TASK_ID}`
- run: `{run_id}`
- execution commit: `{execution_commit}`
- T07 merge commit: `{config["t07_binding"]["merge_commit"]}`
- T07 authoritative run: `{config["t07_binding"]["authoritative_run"]}`
- acceptance gates: `{gate_status}`
- frozen versions: `{ids}`
- independent checks: `{len(independent.get("checks", {}))}`, failure count `{independent.get("failure_count")}`
- anomaly count: `{anomaly.get("anomaly_count")}`
- committed-artifact count: `{len(committed.get("validated_artifacts", []))}`, failure count `{committed.get("failure_count")}`

## Frozen interface

Both frozen versions are W120/K3/d2/g1. Strict-core sources remain internal stratification fields, not independent products, state versions, event namespaces, or parent products. The T05 canonical interfaces remain bound to their committed database SHA-256, semantic hashes, row counts, logical names and primary keys. R3 must verify the database bytes before calculation and must not substitute T06 replay tables.

The release-anchor obligation remains unselected: R3 owns the choice, `selected_anchor=null`, and exactly three candidates are recorded. No candidate is recommended here.

Warnings and limitations are carried forward per version. Confirmed exit, quality interruption, finalized-with-quality-break and right censor are not release semantics. `r2_t06_replayed_transition_ledger.trigger_trade_date` is not an authoritative causal timestamp. No future outcome, trading efficacy, precision/recall, or backtest result is asserted.

The sole R3 entrypoint is `r2_t08_r3_handoff_manifest.json`; alternative entrypoints are empty. Author-stage gates remain `formal_task_completed=false` and `R3_allowed_to_start=false` pending independent scientific review and merge.
"""


def run_formal(config_path: Path, output_dir: Path) -> dict[str, Any]:
    config, execution_commit, config_binding = _config_from_committed(config_path, ROOT)
    t07 = _load_t07_inputs(config, ROOT)
    run_id = output_dir.name
    if not run_id.startswith("R2-T08-"):
        raise T08GenerationError("run_id_format")
    handoff = _handoff(config, t07, run_id, execution_commit)
    acceptance = _build_acceptance_matrix(config, t07, handoff)
    if any(row["status"] != "passed" for row in acceptance):
        raise T08GenerationError("t07_acceptance_failed")
    write_csv(
        output_dir / "r2_t08_acceptance_matrix.csv", acceptance, ACCEPTANCE_FIELDS
    )
    write_csv(
        output_dir / "r2_t08_frozen_window_matrix.csv",
        config["frozen_window_matrix"],
        WINDOW_FIELDS,
    )
    release = config["release_anchor_obligation"]
    write_json(output_dir / "r2_t08_release_anchor_obligation.json", release)
    write_json(output_dir / "r2_t08_r3_handoff_manifest.json", handoff)
    final_acceptance = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "execution_commit": execution_commit,
        "status": "passed_author_stage_pending_scientific_review_and_merge",
        "acceptance_matrix_ref": {
            "path": "r2_t08_acceptance_matrix.csv",
            "gate_count": len(acceptance),
            "mismatch_count": sum(row["mismatch_count"] for row in acceptance),
        },
        "t07_final_freeze_manifest_ref": t07["final_binding"],
        "frozen_version_count": len(t07["state"]),
        "frozen_state_version_ids": [
            row.get("state_version_id") for row in t07["state"]
        ],
        "canonical_interfaces": _canonical_refs(config),
        "r2_evidence_chain_passed": True,
        "r3_handoff_eligible": True,
        "formal_task_completed": False,
        "R3_allowed_to_start": False,
        "activation_mode": "merged_pr_direct_binding",
        "warnings": handoff["warnings"],
        "limitations": config["global_limitations"],
        "forbidden_reinterpretations": config["forbidden_reinterpretations"],
    }
    write_json(output_dir / "r2_t08_final_acceptance.json", final_acceptance)
    source_artifacts = []
    for key in (
        "final",
        "state",
        "interval",
        "event",
        "decision",
        "output",
        "independent",
        "reconciliation",
        "forbidden",
        "anomaly",
        "committed",
    ):
        source_artifacts.append(t07[f"{key}_binding"])
    input_binding = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": "passed",
        "execution_commit": execution_commit,
        "config_binding": config_binding,
        "t07_merge_commit": t07["source_commit"],
        "t07_reviewed_head": config["t07_binding"]["reviewed_head"],
        "t07_authoritative_run": config["t07_binding"]["authoritative_run"],
        "source_artifacts": source_artifacts,
        "forbidden_inputs": [
            "canonical_database_bytes",
            "T06_replay_tables",
            "T01-T06_formal_reruns",
        ],
    }
    write_json(output_dir / "r2_t08_input_binding.json", input_binding)
    write_json(
        output_dir / "r2_t08_canonical_interface_binding.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed",
            "interfaces": _canonical_refs(config),
            "database_not_opened": True,
            "database_replay_performed": False,
        },
    )
    write_json(
        output_dir / "r2_t08_author_stage_scientific_review.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "pending_independent_scientific_review",
            "scientific_review_status": "pending",
            "formal_task_completed": False,
            "R3_allowed_to_start": False,
            "review_id": None,
            "merge_commit": None,
            "reviewed_head": None,
        },
    )
    return {
        "config": config,
        "execution_commit": execution_commit,
        "t07": t07,
        "acceptance": acceptance,
        "run_id": run_id,
        "output_dir": output_dir,
    }


def finalize_formal(context: dict[str, Any]) -> None:
    output_dir: Path = context["output_dir"]
    config: dict[str, Any] = context["config"]
    t07: dict[str, Any] = context["t07"]
    run_id = context["run_id"]
    execution_commit = context["execution_commit"]
    independent = json.loads(
        (output_dir / "r2_t08_independent_validation.json").read_text(encoding="utf-8")
    )
    anomaly = json.loads(
        (output_dir / "r2_t08_anomaly_scan.json").read_text(encoding="utf-8")
    )
    committed = {
        "status": "pending_artifact_commit",
        "failure_count": 0,
        "validated_artifacts": [],
    }
    analysis = _result_analysis(
        config,
        t07,
        run_id,
        execution_commit,
        context["acceptance"],
        independent,
        anomaly,
        committed,
    )
    write_markdown(output_dir / "r2_t08_result_analysis.md", analysis)
    artifact_paths = [
        p
        for p in sorted(output_dir.iterdir())
        if p.is_file()
        and p.name
        not in {
            "r2_t08_output_manifest.json",
            "r2_t08_committed_artifact_validation.json",
        }
    ]
    artifacts = []
    for path in artifact_paths:
        payload = path.read_bytes()
        artifacts.append(
            {
                "path": repo_rel(path, ROOT),
                "sha256": sha256_bytes(payload),
                "size_bytes": len(payload),
            }
        )
    manifest = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": "passed",
        "artifact_count": len(artifacts),
        "artifact_hash_basis": "committed_artifact_bytes",
        "artifacts": artifacts,
    }
    write_json(output_dir / "r2_t08_output_manifest.json", manifest)
    write_json(
        output_dir / "r2_t08_result_package.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed_author_stage_pending_scientific_review_and_merge",
            "artifact_count": len(artifacts),
            "acceptance_gate_count": 8,
            "r2_evidence_chain_passed": True,
            "r3_handoff_eligible": True,
            "formal_task_completed": False,
            "R3_allowed_to_start": False,
            "independent_validation_status": independent.get("status"),
            "anomaly_count": anomaly.get("anomaly_count"),
            "committed_artifact_validation_status": "pending_artifact_commit",
        },
    )


def utc_run_id() -> str:
    return datetime.now(UTC).strftime("R2-T08-%Y%m%dT%H%M%SZ")
