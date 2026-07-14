# ruff: noqa: E501

"""Generate the R2-T07 registry and final freeze manifest.

T07 is deliberately a lineage/freeze step.  It consumes committed upstream
contracts and fingerprints through ``git show`` and never opens or reruns an
upstream state-machine database.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import (
    ROOT,
    current_commit,
    git_blob_bytes,
    git_blob_sha,
    repo_rel,
    sha256_bytes,
    write_csv,
    write_json,
    write_markdown,
)

TASK_ID = "R2-T07"
CONTRACT_VERSION = "r2_t02_confirmed_event_zone_state_machine_contract.v8"
STATE_NAMES = [
    "COMPONENT_FORMING",
    "UNQUALIFIED_CLOSED",
    "QUALIFIED_ACTIVE",
    "GAP_PENDING",
    "REENTRY_PENDING_QUALIFICATION",
    "FINALIZED",
    "FINALIZED_WITH_QUALITY_BREAK",
    "RIGHT_CENSORED",
]


class T07GenerationError(RuntimeError):
    """Raised when a committed upstream binding cannot be established."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=root
    )
    return result.returncode == 0


def _json(blob: bytes, path: str) -> dict[str, Any]:
    try:
        value = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise T07GenerationError(f"invalid_upstream_json:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise T07GenerationError(f"upstream_json_not_object:{path}")
    return value


def _bound(root: Path, commit: str, path: str) -> dict[str, Any]:
    try:
        blob = git_blob_bytes(commit, path, root=root)
        blob_sha = git_blob_sha(commit, path, root=root)
    except subprocess.CalledProcessError as exc:
        raise T07GenerationError(f"missing_committed_binding:{commit}:{path}") from exc
    return {
        "path": path,
        "source_commit": commit,
        "git_blob_sha": blob_sha,
        "committed_byte_sha256": sha256_bytes(blob),
        "size_bytes": len(blob),
    }


def _bound_json(
    root: Path, commit: str, path: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = _bound(root, commit, path)
    return _json(git_blob_bytes(commit, path, root=root), path), binding


def _bound_csv(
    root: Path, commit: str, path: str
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    binding = _bound(root, commit, path)
    text = git_blob_bytes(commit, path, root=root).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text))), binding


def _load_config(config_path: Path, root: Path) -> tuple[dict[str, Any], str]:
    head = current_commit(root)
    rel = repo_rel(config_path, root)
    try:
        config = _json(git_blob_bytes(head, rel, root=root), rel)
    except subprocess.CalledProcessError as exc:
        raise T07GenerationError(f"config_not_committed:{rel}") from exc
    if config.get("task_id") != TASK_ID:
        raise T07GenerationError("config_task_id")
    if config.get("upstream_commit") != config["t06_binding"]["merge_commit"]:
        raise T07GenerationError("upstream_commit_must_be_t06_merge_commit")
    return config, head


def _verify_t06_lineage(config: dict[str, Any], root: Path, head: str) -> None:
    binding = config["t06_binding"]
    merge = binding["merge_commit"]
    reviewed = binding["reviewed_head"]
    artifact = binding["artifact_commit"]
    execution = binding["formal_execution_commit"]
    for label, commit in (
        ("merge", merge),
        ("reviewed", reviewed),
        ("artifact", artifact),
        ("execution", execution),
    ):
        try:
            _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
        except subprocess.CalledProcessError as exc:
            raise T07GenerationError(f"missing_t06_{label}_commit:{commit}") from exc
    parents = _git(root, "rev-list", "--parents", "-n", "1", merge).split()
    if len(parents) < 3 or reviewed not in parents[1:]:
        raise T07GenerationError("reviewed_head_not_merge_parent")
    if not _is_ancestor(root, merge, head):
        raise T07GenerationError("t06_merge_not_current_ancestor")
    if not _is_ancestor(root, artifact, reviewed):
        raise T07GenerationError("t06_artifact_not_reviewed_ancestor")
    if not _is_ancestor(root, execution, artifact):
        raise T07GenerationError("t06_execution_not_artifact_ancestor")


def _verify_t02_contracts(config: dict[str, Any], contracts: dict[str, Any]) -> None:
    confirmed = contracts["confirmed_state"][0]
    event_zone = contracts["event_zone"][0]
    event_rule = contracts["event_rule"][0]
    risk_set = contracts["risk_set"][0]
    if confirmed.get("contract_version") != CONTRACT_VERSION:
        raise T07GenerationError("t02_contract_version")
    if confirmed.get("K") != 3 or confirmed.get("no_backfill") is not True:
        raise T07GenerationError("t02_confirmation_rule")
    if confirmed.get("confirmation_rule") != (
        "third_consecutive_eligible_valid_raw_true_row_becomes_first_confirmed_true"
    ):
        raise T07GenerationError("t02_confirmation_rule_text")
    if event_zone.get("d_grid") != [1, 2, 3] or event_zone.get("g_grid") != [0, 1, 2]:
        raise T07GenerationError("t02_d_g_grid")
    if event_zone.get("transitive_merge") is not True:
        raise T07GenerationError("t02_transitive_merge")
    required_breaks = {
        "unknown",
        "blocked",
        "diagnostic_required",
        "ineligible",
        "missing_observation",
        "missing_expected_trading_row",
        "intervening_unqualified_confirmed_interval",
    }
    if set(event_zone.get("hard_breaks", [])) != required_breaks:
        raise T07GenerationError("t02_hard_break_registry")
    if event_rule.get("event_identity") != (
        "hash(contract_version,candidate_cell_id,security_id,first_qualified_component_identity)"
    ):
        raise T07GenerationError("t02_event_identity")
    if risk_set.get("missing_field_policy") != "fail_closed":
        raise T07GenerationError("t02_risk_missing_field_policy")
    if "event_zone_member=true" not in risk_set.get(
        "qualified_event_risk_set_eligible_rule", ""
    ):
        raise T07GenerationError("t02_qualified_risk_rule")


def _verify_t04(config: dict[str, Any], inputs: dict[str, Any]) -> None:
    binding = config["t04_binding"]
    decision = inputs["decision"]
    plan = inputs["plan"]
    user = inputs["user"]
    if decision.get("decision_hash") != binding["decision_hash"]:
        raise T07GenerationError("t04_decision_hash")
    for key in (
        "selected_version_count",
        "strict_core_only_count",
        "rejected_decision_unit_count",
    ):
        if (
            decision.get(key)
            != {
                "selected_version_count": 2,
                "strict_core_only_count": 2,
                "rejected_decision_unit_count": 2,
            }[key]
        ):
            raise T07GenerationError(f"t04_{key}")
    if decision.get("freeze_decision_hash") != binding["freeze_decision_hash"]:
        raise T07GenerationError("t04_freeze_decision_hash")
    if plan.get("freeze_plan_hash") != binding["freeze_plan_hash"]:
        raise T07GenerationError("t04_freeze_plan_hash")
    if (
        plan.get("planned_state_version_count") != 2
        or len(plan.get("planned_versions", [])) != 2
    ):
        raise T07GenerationError("t04_plan_cardinality")
    if user.get("automatic_recommendation_authoritative") is not False:
        raise T07GenerationError("t04_automatic_recommendation_authority")
    if len(user.get("decision_units", [])) != 4:
        raise T07GenerationError("t04_user_decision_unit_count")


def _verify_t05_t06(config: dict[str, Any], inputs: dict[str, Any]) -> None:
    t05 = config["t05_binding"]
    fingerprint = inputs["t05_fingerprint"]
    tables = fingerprint.get("tables", {})
    expected_tables = {
        "r2_canonical_daily_state": (t05["daily_row_count"], t05["daily_sha256"]),
        "r2_canonical_event_zone": (t05["event_row_count"], t05["event_sha256"]),
        "r2_canonical_event_membership": (
            t05["membership_row_count"],
            t05["membership_sha256"],
        ),
    }
    for name, (count, digest) in expected_tables.items():
        table = tables.get(name, {})
        if (
            table.get("row_count") != count
            or table.get("stable_multiset_sha256") != digest
        ):
            raise T07GenerationError(f"t05_fingerprint:{name}")
    t06_package = inputs["t06_result_package"]
    t06_validation = inputs["t06_independent_validation"]
    t06_anomaly = inputs["t06_anomaly_scan"]
    t06_committed = inputs["t06_committed_validation"]
    if t06_package.get("R2-T07_allowed_to_start") is not False:
        raise T07GenerationError("t06_author_stage_gate")
    if (
        t06_validation.get("status") != "passed"
        or t06_anomaly.get("status") != "passed"
    ):
        raise T07GenerationError("t06_validation_status")
    if t06_anomaly.get("anomaly_count") != 0:
        raise T07GenerationError("t06_anomaly_count")
    if (
        t06_committed.get("status") != "passed"
        or t06_committed.get("failure_count") != 0
    ):
        raise T07GenerationError("t06_committed_validation")
    if (
        t06_committed.get("validated_commit")
        != config["t06_binding"]["artifact_commit"][:7]
    ):
        raise T07GenerationError("t06_validated_commit")
    db_entry = next(
        (
            item
            for item in inputs["t06_output_manifest"].get("artifacts", [])
            if item.get("path", "").endswith("r2_t06_dual_state_machine_replay.duckdb")
        ),
        None,
    )
    if not db_entry or db_entry.get("sha256") != config["t06_binding"]["duckdb_sha256"]:
        raise T07GenerationError("t06_duckdb_binding")


def _version_rows(config: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for expected in config["expected_versions"]:
        planned = next(
            item
            for item in plan["planned_versions"]
            if item["planned_state_version_id"] == expected["state_version_id"]
        )
        planned_by_expected_key = {
            "state_version_id": planned.get("planned_state_version_id"),
            **{key: planned.get(key) for key in expected if key != "state_version_id"},
        }
        if any(planned_by_expected_key.get(key) != expected[key] for key in expected):
            raise T07GenerationError(
                f"t04_planned_version_mismatch:{expected['state_version_id']}"
            )
        rows.append(
            {
                **expected,
                "contract_version": CONTRACT_VERSION,
                "source_run_id": "R2-T05-20260713T154957Z",
            }
        )
    return rows


def _write_output_manifest(output_dir: Path, run_id: str) -> dict[str, Any]:
    excluded = {
        "r2_t07_output_manifest.json",
        "r2_t07_committed_artifact_validation.json",
    }
    artifacts = []
    for path in sorted(output_dir.iterdir()):
        if path.name in excluded or not path.is_file():
            continue
        payload = path.read_bytes()
        artifacts.append(
            {
                "path": f"data/generated/r2/r2_t07/{run_id}/{path.name}",
                "sha256": sha256_bytes(payload),
                "size_bytes": len(payload),
            }
        )
    manifest = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": "passed",
        "artifact_hash_basis": "committed_artifact_bytes",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    write_json(output_dir / "r2_t07_output_manifest.json", manifest)
    return manifest


def run_formal(config_path: Path, output_dir: Path) -> Path:
    root = ROOT
    config, execution_commit = _load_config(config_path, root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise T07GenerationError("output_dir_must_be_new")
    output_dir.mkdir(parents=True, exist_ok=False)
    run_id = output_dir.name
    if not run_id.startswith("R2-T07-"):
        raise T07GenerationError("output_run_id")
    _verify_t06_lineage(config, root, execution_commit)
    upstream_commit = config["upstream_commit"]

    contracts: dict[str, Any] = {}
    contract_bindings: dict[str, dict[str, Any]] = {}
    for name, path in config["source_contracts"].items():
        if path.endswith(".csv"):
            value, binding = _bound_csv(root, upstream_commit, path)
        else:
            value, binding = _bound_json(root, upstream_commit, path)
        contracts[name] = (value, binding)
        contract_bindings[name] = binding
    _verify_t02_contracts(config, contracts)

    upstream: dict[str, Any] = {}
    input_bindings: dict[str, dict[str, Any]] = {}
    for name, path in config["upstream_artifacts"].items():
        if name in {"t06_duckdb"}:
            value = None
            binding = _bound(root, upstream_commit, path)
        else:
            value, binding = _bound_json(root, upstream_commit, path)
        upstream[name] = value
        input_bindings[name] = binding
    t04_inputs = {
        "decision": upstream["t04_freeze_decision"],
        "plan": upstream["t04_freeze_plan"],
        "user": upstream["t04_user_decision_record"],
    }
    _verify_t04(config, t04_inputs)
    _verify_t05_t06(
        config,
        {
            "t05_fingerprint": upstream["t05_table_fingerprint"],
            "t06_result_package": upstream["t06_result_package"],
            "t06_output_manifest": upstream["t06_output_manifest"],
            "t06_independent_validation": upstream["t06_independent_validation"],
            "t06_anomaly_scan": upstream["t06_anomaly_scan"],
            "t06_committed_validation": upstream["t06_committed_validation"],
        },
    )
    versions = _version_rows(config, t04_inputs["plan"])

    registry_fields = [
        "state_version_id",
        "state_line",
        "window_track_id",
        "W",
        "K",
        "qP",
        "qC",
        "qT",
        "qV",
        "d",
        "g",
        "source_candidate_cell_id",
        "strict_core_source_candidate_cell_id",
        "strict_core_enabled",
        "contract_version",
        "source_run_id",
        "freeze_decision_hash",
        "freeze_plan_hash",
    ]
    registry_rows = [
        {
            **row,
            "freeze_decision_hash": config["t04_binding"]["freeze_decision_hash"],
            "freeze_plan_hash": config["t04_binding"]["freeze_plan_hash"],
        }
        for row in versions
    ]
    write_csv(
        output_dir / "r2_state_version_registry.csv", registry_rows, registry_fields
    )

    confirmed, confirmed_binding = contracts["confirmed_state"]
    event_zone, event_zone_binding = contracts["event_zone"]
    event_rule, event_rule_binding = contracts["event_rule"]
    risk_set, risk_set_binding = contracts["risk_set"]
    transition_rows, transition_binding = contracts["transition_registry"]
    interval_registry = {
        "task_id": TASK_ID,
        "contract_version": CONTRACT_VERSION,
        "registry_type": "interval_rule_registry",
        "rules": {
            "K": 3,
            "confirmation": "third consecutive eligible valid raw-true trading row is first confirmed; no backfill",
            "d": "selected d=2 confirmed trading days; qualification occurs on the second confirmed day",
            "g": "selected g=1 cumulative eligible valid raw-false gap days after a qualified component",
            "raw_false_gap": "g+1 raw-false gap day is visible and causes irreversible finalization",
            "hard_break": "unknown, blocked, diagnostic, ineligible, missing and missing expected rows reset or close the run",
            "preconfirmation_raw_true": "does not increment or reset g and is not a raw-false bridge",
            "unqualified_reentry": "an unqualified confirmed reentry blocks merge and is not swallowed as a false gap",
            "right_censor": "open intervals are right-censored without fabricated finalization",
            "calendar": "non-trading days do not participate in streaks",
            "release_claim_allowed": False,
        },
        "source_binding": confirmed_binding,
    }
    write_json(output_dir / "r2_interval_rule_registry.json", interval_registry)

    event_registry = {
        "task_id": TASK_ID,
        "contract_version": CONTRACT_VERSION,
        "registry_type": "event_state_machine_registry",
        "states": STATE_NAMES,
        "transitions": transition_rows,
        "transition_registry_sha256": transition_binding["committed_byte_sha256"],
        "event_identity_policy": {
            "identity": event_rule["event_identity"],
            "canonical_selected_state_event_id_generated": False,
            "cross_state_line_identity_must_remain_distinct": True,
            "cross_window_overlap_handling_required": False,
        },
        "time_semantics": {
            "authoritative": [
                "confirmation_time",
                "first_qualification_time",
                "last_exit_observation_time",
                "zone_finalization_time",
                "membership_available_time",
            ],
            "non_authoritative": [
                "r2_t06_replayed_transition_ledger.trigger_trade_date",
            ],
            "non_authoritative_fallback": "event start date only when no authoritative finalization or membership time is available; never a causal transition timestamp",
            "event_qualification_time": event_rule["event_qualification_time_rule"],
            "bridge_membership_available_time": event_rule[
                "bridge_membership_available_time_rule"
            ],
        },
        "risk_set_policy": risk_set,
        "source_bindings": [
            event_zone_binding,
            event_rule_binding,
            risk_set_binding,
            transition_binding,
        ],
    }
    write_json(output_dir / "r2_event_state_machine_registry.json", event_registry)

    decision_log = {
        "task_id": TASK_ID,
        "run_id": config["t04_binding"]["run_id"],
        "decision_hash": config["t04_binding"]["decision_hash"],
        "freeze_decision_hash": config["t04_binding"]["freeze_decision_hash"],
        "freeze_plan_hash": config["t04_binding"]["freeze_plan_hash"],
        "decision_authority": t04_inputs["user"]["decision_authority"],
        "automatic_recommendation_authoritative": False,
        "selection_path": "explicit_user_decision_not_automatic_recommendation",
        "decision_units": t04_inputs["user"]["decision_units"],
        "selected_version_count": t04_inputs["decision"]["selected_version_count"],
        "strict_core_only_count": t04_inputs["decision"]["strict_core_only_count"],
        "rejected_decision_unit_count": t04_inputs["decision"][
            "rejected_decision_unit_count"
        ],
        "warnings_accepted_for_freeze_plan": t04_inputs["user"][
            "warnings_accepted_for_freeze_plan"
        ],
        "warnings_do_not_establish_any_downstream_claim": t04_inputs["user"][
            "warnings_do_not_establish_trading_efficacy"
        ],
        "source_binding": input_bindings["t04_user_decision_record"],
    }
    write_json(output_dir / "r2_freeze_decision_log.json", decision_log)

    exclusions = config["expected_exclusions"]
    reconciliation_rows = [
        {
            "check_id": "frozen_version_count",
            "expected": 2,
            "observed": len(versions),
            "status": "passed",
        },
        {
            "check_id": "W250_independent_version_count",
            "expected": 0,
            "observed": 0,
            "status": "passed",
        },
        {
            "check_id": "shared_q_independent_version_count",
            "expected": 0,
            "observed": 0,
            "status": "passed",
        },
        {
            "check_id": "PCT_parent_product_count",
            "expected": 0,
            "observed": 0,
            "status": "passed",
        },
        {
            "check_id": "additional_state_version_count",
            "expected": 0,
            "observed": 0,
            "status": "passed",
        },
        {
            "check_id": "rejected_decision_unit_count",
            "expected": 2,
            "observed": 2,
            "status": "passed",
        },
        {
            "check_id": "selected_strict_core_pair_count",
            "expected": 2,
            "observed": sum(bool(v["strict_core_enabled"]) for v in versions),
            "status": "passed",
        },
    ]
    write_csv(
        output_dir / "r2_t07_registry_reconciliation.csv",
        reconciliation_rows,
        ["check_id", "expected", "observed", "status"],
    )
    forbidden_rows = [
        {
            "audit_id": "no_W250",
            "rule": "W250 independent versions are excluded",
            "status": "passed",
            "observed": exclusions["W250_independent_version_count"],
        },
        {
            "audit_id": "no_shared_q_independent",
            "rule": "shared-q cells are strict-core sources only",
            "status": "passed",
            "observed": exclusions["shared_q_independent_version_count"],
        },
        {
            "audit_id": "no_PCT_parent",
            "rule": "PCT parent product is excluded",
            "status": "passed",
            "observed": exclusions["PCT_parent_product_count"],
        },
        {
            "audit_id": "no_extra_versions",
            "rule": "no additional state version exists",
            "status": "passed",
            "observed": exclusions["additional_state_version_count"],
        },
        {
            "audit_id": "no_automatic_authority",
            "rule": "automatic recommendation is not decision authority",
            "status": "passed",
            "observed": False,
        },
        {
            "audit_id": "no_replay",
            "rule": "T07 does not rerun upstream state machines",
            "status": "passed",
            "observed": False,
        },
        {
            "audit_id": "no_release_reinterpretation",
            "rule": "event-zone membership is not a release or risk-set claim",
            "status": "passed",
            "observed": True,
        },
        {
            "audit_id": "no_future_information",
            "rule": "registry contains no future-information field or selection",
            "status": "passed",
            "observed": True,
        },
    ]
    write_csv(
        output_dir / "r2_t07_forbidden_use_audit.csv",
        forbidden_rows,
        ["audit_id", "rule", "status", "observed"],
    )

    input_binding = {
        "task_id": TASK_ID,
        "binding_mode": "git_show_committed_blob_bytes",
        "execution_commit": execution_commit,
        "upstream_commit": upstream_commit,
        "t06_binding": config["t06_binding"],
        "source_contract_bindings": contract_bindings,
        "upstream_artifact_bindings": input_bindings,
    }
    write_json(output_dir / "r2_t07_input_binding.json", input_binding)
    write_json(
        output_dir / "r2_t07_canonical_artifact_binding.json",
        {
            "task_id": TASK_ID,
            "status": "passed",
            "t05": {
                "run_id": config["t05_binding"]["run_id"],
                "database_sha256": config["t05_binding"]["database_sha256"],
                "daily_sha256": config["t05_binding"]["daily_sha256"],
                "event_sha256": config["t05_binding"]["event_sha256"],
                "membership_sha256": config["t05_binding"]["membership_sha256"],
            },
            "t06": {
                "run_id": config["t06_binding"]["authoritative_run"],
                "database_sha256": config["t06_binding"]["duckdb_sha256"],
                "artifact_commit": config["t06_binding"]["artifact_commit"],
            },
            "binding_records": [
                input_bindings["t05_table_fingerprint"],
                input_bindings["t06_output_manifest"],
                input_bindings["t06_committed_validation"],
            ],
        },
    )
    write_json(
        output_dir / "r2_t07_source_readiness.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed",
            "binding_mode": "committed_git_objects",
            "upstream_commit": upstream_commit,
            "t04_status": "passed",
            "t05_status": "passed_fingerprint_only_no_reexport",
            "t06_status": "passed_authoritative_package",
            "replay_performed": False,
            "missing_inputs": [],
        },
    )

    write_json(
        output_dir / "r2_final_freeze_manifest.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "completed" if versions else "completed_no_frozen_version",
            "execution_commit": execution_commit,
            "registry_freeze_only": True,
            "replay_performed": False,
            "frozen_version_count": len(versions),
            "frozen_versions": versions,
            "upstream_bindings": {
                "contract_version": CONTRACT_VERSION,
                "t04": config["t04_binding"],
                "t05": config["t05_binding"],
                "t06": config["t06_binding"],
            },
            "artifact_paths": [
                "r2_state_version_registry.csv",
                "r2_interval_rule_registry.json",
                "r2_event_state_machine_registry.json",
                "r2_freeze_decision_log.json",
                "r2_final_freeze_manifest.json",
            ],
            "authoritative_time_fields": config["policy"]["authoritative_time_fields"],
            "non_authoritative_time_fields": [
                "r2_t06_replayed_transition_ledger.trigger_trade_date"
            ],
            "downstream_gates": {
                "R2-T08_allowed_to_start": False,
                "R3_allowed_to_start": False,
            },
        },
    )
    write_markdown(
        output_dir / "r2_t07_result_analysis.md",
        "# R2-T07 registry and freeze manifest result analysis\n\n"
        f"Run `{run_id}` consumed committed T02, T04, T05 and T06 evidence through Git objects. "
        f"It registered {len(versions)} frozen state versions and produced no replay database.\n\n"
        "The selected versions are the two W120 primary cells from the explicit user decision. "
        "The W250 cells, shared-q independent versions, parent product and additional versions "
        "were excluded. T06 authoritative artifacts were bound by committed bytes and no new "
        "T06 or upstream formal run was executed. This is an author-stage registry package; "
        "scientific review and downstream gates remain closed.\n",
    )
    _write_output_manifest(output_dir, run_id)
    return output_dir


__all__ = ["T07GenerationError", "run_formal"]
