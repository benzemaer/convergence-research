# ruff: noqa: E501

"""Generate the R2-T07 state-version registries and final freeze manifest.

This task is registry/freeze-only.  It reads every upstream input through
committed Git blobs and never replays an upstream database or imports the
state-machine implementation used by T03/T06.
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
    canonical_json_bytes,
    canonical_json_sha256,
    current_commit,
    git_blob_bytes,
    git_blob_sha,
    repo_rel,
    sha256_bytes,
    write_csv,
    write_json,
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
ALLOWED_USES = [
    "T08_R2_final_acceptance_input",
    "T08_R3_handoff_source",
    "canonical_daily_state_consumption",
    "canonical_event_zone_consumption",
    "canonical_event_membership_consumption",
    "state_risk_set_consumption",
    "qualified_event_risk_set_consumption",
    "R3_contract_design_only",
]
FORBIDDEN_USES = [
    "no_trading_advantage_claim",
    "no_global_optimum_claim",
    "no_future_outcome_selection",
    "confirmed_exit_is_not_release",
    "quality_interruption_is_not_natural_release",
    "event_zone_member_is_not_risk_set",
    "no_finalization_time_backfill",
    "no_risk_set_mixing",
    "strict_core_is_not_independent_product",
    "no_PCT_parent_product",
    "transition_trigger_trade_date_not_causal_time",
    "no_cross_state_version_event_merge",
]
FORBIDDEN_REINTERPRETATIONS = [
    "no_trading_advantage_claim",
    "no_global_optimum_claim",
    "no_future_outcome_selection",
    "confirmed_exit_is_not_release",
    "quality_interruption_is_not_natural_release",
    "event_zone_member_is_not_risk_set",
    "no_zone_finalization_time_backfill",
    "no_state_and_qualified_event_risk_set_mixing",
    "strict_core_is_not_independent_product",
    "no_PCT_parent_product",
    "transition_trigger_trade_date_not_causal_time",
    "no_cross_state_version_event_merge",
]
AUTHORITATIVE_TIMES = [
    "confirmation_time",
    "first_qualification_time",
    "last_exit_observation_time",
    "zone_finalization_time",
    "membership_available_time",
]


class T07GenerationError(RuntimeError):
    """Raised when a committed upstream binding cannot be established."""


def _git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


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
        payload = git_blob_bytes(commit, path, root=root)
        blob_sha = git_blob_sha(commit, path, root=root)
    except subprocess.CalledProcessError as exc:
        raise T07GenerationError(f"missing_committed_binding:{commit}:{path}") from exc
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
    binding = _bound(root, commit, path)
    return _json(git_blob_bytes(commit, path, root=root), path), binding


def _bound_csv(
    root: Path, commit: str, path: str
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    binding = _bound(root, commit, path)
    text = git_blob_bytes(commit, path, root=root).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text))), binding


def _compact_array(values: list[str]) -> str:
    return canonical_json_bytes(values).decode("utf-8")


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
    parents = str(_git(root, "rev-list", "--parents", "-n", "1", merge)).split()
    if len(parents) < 3 or reviewed not in parents[1:]:
        raise T07GenerationError("reviewed_head_not_merge_parent")
    if not _is_ancestor(root, merge, head):
        raise T07GenerationError("t06_merge_not_current_ancestor")
    if not _is_ancestor(root, artifact, reviewed):
        raise T07GenerationError("t06_artifact_not_reviewed_ancestor")
    if not _is_ancestor(root, execution, artifact):
        raise T07GenerationError("t06_execution_not_artifact_ancestor")


def _verify_t02_contracts(
    config: dict[str, Any], contracts: dict[str, tuple[Any, dict[str, Any]]]
) -> None:
    confirmed = contracts["confirmed_state"][0]
    event_zone = contracts["event_zone"][0]
    event_rule = contracts["event_rule"][0]
    risk_set = contracts["risk_set"][0]
    if (
        confirmed.get("contract_version") != CONTRACT_VERSION
        or confirmed.get("K") != 3
        or confirmed.get("no_backfill") is not True
    ):
        raise T07GenerationError("t02_confirmation_rule")
    if (
        confirmed.get("confirmation_rule")
        != "third_consecutive_eligible_valid_raw_true_row_becomes_first_confirmed_true"
    ):
        raise T07GenerationError("t02_confirmation_rule_text")
    if (
        event_zone.get("d_grid") != [1, 2, 3]
        or event_zone.get("g_grid") != [0, 1, 2]
        or event_zone.get("transitive_merge") is not True
    ):
        raise T07GenerationError("t02_d_g_grid")
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
    if (
        event_rule.get("event_identity")
        != "hash(contract_version,candidate_cell_id,security_id,first_qualified_component_identity)"
    ):
        raise T07GenerationError("t02_event_identity")
    if risk_set.get(
        "missing_field_policy"
    ) != "fail_closed" or "event_zone_member=true" not in risk_set.get(
        "qualified_event_risk_set_eligible_rule", ""
    ):
        raise T07GenerationError("t02_risk_contract")


def _verify_t04(
    config: dict[str, Any],
    decision: dict[str, Any],
    plan: dict[str, Any],
    user: dict[str, Any],
) -> None:
    binding = config["t04_binding"]
    if (
        decision.get("decision_hash") != binding["decision_hash"]
        or decision.get("freeze_decision_hash") != binding["freeze_decision_hash"]
    ):
        raise T07GenerationError("t04_decision_binding")
    if (
        decision.get("selected_version_count") != 2
        or decision.get("strict_core_only_count") != 2
        or decision.get("rejected_decision_unit_count") != 2
    ):
        raise T07GenerationError("t04_count_binding")
    if (
        plan.get("freeze_plan_hash") != binding["freeze_plan_hash"]
        or plan.get("planned_state_version_count") != 2
        or len(plan.get("planned_versions", [])) != 2
    ):
        raise T07GenerationError("t04_plan_binding")
    if (
        user.get("automatic_recommendation_authoritative") is not False
        or len(user.get("decision_units", [])) != 4
    ):
        raise T07GenerationError("t04_user_decision_binding")


def _verify_t05_t06(config: dict[str, Any], inputs: dict[str, Any]) -> None:
    t05 = config["t05_binding"]
    tables = inputs["t05_fingerprint"].get("tables", {})
    expected = {
        "r2_canonical_daily_state": (t05["daily_row_count"], t05["daily_sha256"]),
        "r2_canonical_event_zone": (t05["event_row_count"], t05["event_sha256"]),
        "r2_canonical_event_membership": (
            t05["membership_row_count"],
            t05["membership_sha256"],
        ),
    }
    for name, (count, digest) in expected.items():
        table = tables.get(name, {})
        if (
            table.get("row_count") != count
            or table.get("stable_multiset_sha256") != digest
        ):
            raise T07GenerationError(f"t05_fingerprint:{name}")
    if inputs["t06_result_package"].get("R2-T07_allowed_to_start") is not False:
        raise T07GenerationError("t06_author_stage_gate")
    if (
        inputs["t06_independent_validation"].get("status") != "passed"
        or inputs["t06_anomaly_scan"].get("status") != "passed"
        or inputs["t06_anomaly_scan"].get("anomaly_count") != 0
    ):
        raise T07GenerationError("t06_validation_status")
    committed = inputs["t06_committed_validation"]
    if (
        committed.get("status") != "passed"
        or committed.get("failure_count") != 0
        or committed.get("validated_commit")
        != config["t06_binding"]["artifact_commit"][:7]
    ):
        raise T07GenerationError("t06_committed_validation")
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


def _selected_rows(
    config: dict[str, Any], plan: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = []
    for expected in config["expected_versions"]:
        planned = next(
            (
                item
                for item in plan["planned_versions"]
                if item.get("planned_state_version_id") == expected["state_version_id"]
            ),
            None,
        )
        if planned is None:
            raise T07GenerationError(
                f"missing_planned_version:{expected['state_version_id']}"
            )
        for key in (
            "state_line",
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
        ):
            if planned.get(key) != expected.get(key):
                raise T07GenerationError(
                    f"planned_version_mismatch:{expected['state_version_id']}:{key}"
                )
        rows.append(expected)
    return rows


def _row_hash(row: dict[str, str]) -> str:
    return canonical_json_sha256(row)


def _route_binding(
    root: Path,
    commit: str,
    state: dict[str, Any],
    adapter: dict[str, Any],
    cell_rows: list[dict[str, str]],
    r1_rows: list[dict[str, str]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str, str]:
    routes = {row["route_id"]: row for row in adapter["route_mappings"]}
    primary = routes.get(state["formula_route_id"])
    strict = routes.get(state["strict_core_route_id"])
    if primary is None or strict is None:
        raise T07GenerationError(
            f"state_formula_binding_unresolved:{state['state_version_id']}"
        )
    candidate = next(
        (
            row
            for row in cell_rows
            if row.get("candidate_cell_id") == state["source_candidate_cell_id"]
        ),
        None,
    )
    strict_cell = next(
        (
            row
            for row in cell_rows
            if row.get("candidate_cell_id")
            == state["strict_core_source_candidate_cell_id"]
        ),
        None,
    )
    handoff = next(
        (
            row
            for row in r1_rows
            if row.get("handoff_row_id") == state["r1_handoff_row_id"]
        ),
        None,
    )
    if candidate is None or strict_cell is None or handoff is None:
        raise T07GenerationError(
            f"state_formula_binding_unresolved:{state['state_version_id']}"
        )
    if (
        candidate.get("route_id") != primary["route_id"]
        or strict_cell.get("route_id") != strict["route_id"]
    ):
        raise T07GenerationError(
            f"state_formula_binding_route_mismatch:{state['state_version_id']}"
        )
    bindings = [
        _bound(root, commit, config["source_contracts"]["t03_interval_adapter"]),
        _bound(root, commit, config["source_contracts"]["t02_cell_registry"]),
        _bound(root, commit, config["source_contracts"]["r1_candidate_registry"]),
    ]
    bindings = sorted(bindings, key=lambda item: item["path"])
    formula_sha = canonical_json_sha256(bindings)
    formula_id = f"state_formula_binding_{state['state_line']}_W{state['W']}_v8"
    return bindings, formula_id, formula_sha, _row_hash(handoff)


def _state_registry_rows(
    config: dict[str, Any],
    selected: list[dict[str, Any]],
    route_data: dict[str, Any],
    user_sha: str,
) -> list[dict[str, Any]]:
    rows = []
    for state in selected:
        binding, formula_id, formula_sha, handoff_sha = route_data[
            state["state_version_id"]
        ]
        rows.append(
            {
                "state_version_id": state["state_version_id"],
                "freeze_status": "frozen",
                "state_line": state["state_line"],
                "window_track_id": state["window_track_id"],
                "W": state["W"],
                "K": state["K"],
                "qP": state["qP"],
                "qC": state["qC"],
                "qT": state["qT"],
                "qV": state["qV"],
                "d": state["d"],
                "g": state["g"],
                "source_candidate_cell_id": state["source_candidate_cell_id"],
                "strict_core_enabled": state["strict_core_enabled"],
                "strict_core_source_candidate_cell_id": state[
                    "strict_core_source_candidate_cell_id"
                ],
                "state_formula_binding_id": formula_id,
                "state_formula_binding_sha256": formula_sha,
                "r1_handoff_row_id": state["r1_handoff_row_id"],
                "r1_handoff_row_sha256": handoff_sha,
                "confirmed_state_contract_id": config["contract_version"],
                "interval_rule_registry_id": config["policy"][
                    "interval_rule_registry_id"
                ],
                "event_state_machine_registry_id": config["policy"][
                    "event_state_machine_registry_id"
                ],
                "state_risk_set_rule_id": config["policy"]["state_risk_set_rule_id"],
                "qualified_event_risk_set_rule_id": config["policy"][
                    "qualified_event_risk_set_rule_id"
                ],
                "t04_decision_unit": f"{state['state_line']}×{state['window_track_id']}",
                "t04_decision_hash": config["t04_binding"]["decision_hash"],
                "t04_freeze_decision_hash": config["t04_binding"][
                    "freeze_decision_hash"
                ],
                "t04_freeze_plan_hash": config["t04_binding"]["freeze_plan_hash"],
                "t04_user_decision_record_sha256": user_sha,
                "t05_run_id": config["t05_binding"]["run_id"],
                "t06_run_id": config["t06_binding"]["authoritative_run"],
                "canonical_daily_state_sha256": config["t05_binding"]["daily_sha256"],
                "canonical_event_zone_sha256": config["t05_binding"]["event_sha256"],
                "canonical_event_membership_sha256": config["t05_binding"][
                    "membership_sha256"
                ],
                "warning_codes": _compact_array(sorted(state["warning_codes"])),
                "selection_path_not_independently_confirmed": True,
                "allowed_uses": _compact_array(ALLOWED_USES),
                "forbidden_uses": _compact_array(FORBIDDEN_USES),
            }
        )
    return rows


def _interval_registry(
    config: dict[str, Any],
    contracts: dict[str, tuple[Any, dict[str, Any]]],
    selected_ids: list[str],
) -> dict[str, Any]:
    confirmed, confirmed_binding = contracts["confirmed_state"]
    event_zone, event_zone_binding = contracts["event_zone"]
    event_rule, event_rule_binding = contracts["event_rule"]
    return {
        "task_id": TASK_ID,
        "registry_id": config["policy"]["interval_rule_registry_id"],
        "contract_version": CONTRACT_VERSION,
        "applicable_state_version_ids": selected_ids,
        "K": 3,
        "confirmation_rule": confirmed["confirmation_rule"],
        "confirmation_backfill_allowed": False,
        "atomic_interval_rule": "per security and selected candidate cell, ordered trading rows; hard breaks terminate the current valid streak",
        "termination_reason_mapping": {
            "raw_state_false": "natural_state_exit",
            "end_of_input_open": "sample_end_censoring",
            "raw_state_blocked": "quality_interruption",
            "raw_state_diagnostic_required": "quality_interruption",
            "raw_state_unknown": "quality_interruption",
        },
        "d": 2,
        "d_operator": event_zone["d_operator"],
        "d_count_unit": "confirmed_trading_day",
        "g": 1,
        "g_count_unit": "eligible_valid_raw_false_trading_day",
        "raw_false_gap_rule": event_zone["raw_false_gap_day_rule"],
        "preconfirmation_raw_true_rule": event_zone["preconfirmation_gap_rule"],
        "hard_break_reasons": sorted(event_zone["hard_breaks"]),
        "g_plus_one_finalization_rule": "g+1 eligible valid raw-false gap day causes irreversible finalization before requalification",
        "unqualified_reentry_policy": "unqualified confirmed reentry is retained, blocks merge, and is not an ordinary false-gap bridge",
        "transitive_merge_policy": "accepted bridge decisions are transitive across the event zone",
        "anti_percolation_policy": "intervening unqualified confirmed intervals prevent transitive merge",
        "left_censor_policy": "left-censored input cannot fabricate a prior confirmation or qualification",
        "right_censor_policy": event_zone["right_censored_policy"],
        "open_zone_policy": "open event zones are right-censored; no fabricated finalization time",
        "qualification_time_rule": event_rule["event_qualification_time_rule"],
        "finalization_time_rule": "last observed authoritative exit/finalization fact; never backfilled from replay trigger date",
        "membership_available_time_rule": "source fact or contract-defined next-component time; never earlier than source availability",
        "source_bindings": sorted(
            [confirmed_binding, event_zone_binding, event_rule_binding],
            key=lambda item: item["path"],
        ),
    }


def _canonical_mapping() -> dict[str, Any]:
    return {
        "evaluation_time": {
            "canonical_status": "not_exposed_as_standalone_field",
            "consumer_rule": "use daily.available_time/evaluation_time semantics; do not expose evaluation_time as a standalone R3 causal field",
        },
        "eligible": "r2_canonical_daily_state.eligible_state",
        "quality_state": "r2_canonical_daily_state.quality_state",
        "confirmed_state": "r2_canonical_daily_state.confirmed_state",
        "event_zone_member": "r2_canonical_event_membership.event_zone_member",
        "is_raw_false_bridge": "r2_canonical_event_membership.is_bridged_gap",
        "is_preconfirmation_gap": "r2_canonical_event_membership.is_prequalification_confirmed_day",
        "retrospective_component_member": "r2_canonical_event_membership.retrospective_component_member",
        "component_qualified_as_of": "r2_canonical_event_membership.component_qualified_as_of",
        "membership_available_time": "r2_canonical_event_membership.membership_available_time",
        "state_risk_set_eligible": "r2_canonical_daily_state.state_risk_set_eligible",
        "qualified_event_risk_set_eligible": "r2_canonical_daily_state.qualified_event_risk_set_eligible",
        "raw_false_gap_ordinal_as_of": {
            "canonical_status": "audit_only_not_exposed_to_R3"
        },
        "raw_false_gap_count_as_of": {
            "canonical_status": "audit_only_not_exposed_to_R3"
        },
    }


def _event_registry(
    config: dict[str, Any],
    contracts: dict[str, tuple[Any, dict[str, Any]]],
    selected_ids: list[str],
) -> dict[str, Any]:
    event_zone, event_zone_binding = contracts["event_zone"]
    event_rule, event_rule_binding = contracts["event_rule"]
    risk_set, risk_set_binding = contracts["risk_set"]
    transitions, transition_binding = contracts["transition_registry"]
    mapping = _canonical_mapping()
    return {
        "task_id": TASK_ID,
        "registry_id": config["policy"]["event_state_machine_registry_id"],
        "contract_version": CONTRACT_VERSION,
        "applicable_state_version_ids": selected_ids,
        "states": STATE_NAMES,
        "transitions": transitions,
        "transition_registry_sha256": transition_binding["committed_byte_sha256"],
        "event_identity_policy": {
            "identity": event_rule["event_identity"],
            "event_id_fixed_at_first_qualified_component": True,
            "reentry_does_not_change_event_id": True,
            "zone_revision_is_integer_non_decreasing": True,
            "cross_state_version_merge_allowed": False,
            "membership_available_not_before_source_fact": True,
        },
        "zone_revision_policy": {
            "event_id_fixed_at_first_qualified_component": True,
            "reentry_does_not_change_event_id": True,
            "revision_increments_or_stays_non_decreasing": True,
            "no_cross_state_version_merge": True,
            "membership_availability_not_before_source_fact": True,
        },
        "exit_policy": "confirmed exit is an observation and is not a release label",
        "quality_break_policy": "unknown, blocked, diagnostic, ineligible and missing are hard breaks",
        "censor_policy": "open event zones are right-censored without fabricated finalization",
        "time_semantics": {
            "authoritative_time_fields": AUTHORITATIVE_TIMES,
            "non_authoritative_time_fields": [
                "r2_t06_replayed_transition_ledger.trigger_trade_date"
            ],
            "trigger_trade_date_is_causal": False,
            "trigger_trade_date_is_release_anchor": False,
            "availability_precedes_causal_use": True,
        },
        "source_contract_risk_set_policy": {
            "missing_field_policy": risk_set["missing_field_policy"],
            "source_required_fields": risk_set["required_fields"],
            "source_state_rule": risk_set["state_risk_set_eligible_rule"],
            "source_qualified_rule": risk_set["qualified_event_risk_set_eligible_rule"],
            "source_fields_are_not_canonical_claim": True,
        },
        "canonical_consumer_mapping": mapping,
        "canonical_risk_set_policy": {
            "state_risk_set_eligible": "direct canonical daily field; not derived from event_zone_member",
            "qualified_event_risk_set_eligible": "direct canonical daily/membership field; event_zone_member alone is insufficient",
            "daily_audit_formula": "qualified_event_risk_set_eligible => state_risk_set_eligible AND component_qualified_as_of AND event_zone_member AND NOT is_raw_false_bridge AND NOT is_preconfirmation_gap",
            "membership_audit_formula": "event_zone_member AND NOT state_risk_set_eligible is permitted for bridge/preconfirmation rows and is not an audit failure",
            "required_canonical_fields": [
                "state_risk_set_eligible",
                "qualified_event_risk_set_eligible",
            ],
            "excluded_source_only_fields": [
                "raw_false_gap_ordinal_as_of",
                "raw_false_gap_count_as_of",
            ],
        },
        "source_bindings": sorted(
            [
                event_zone_binding,
                event_rule_binding,
                risk_set_binding,
                transition_binding,
            ],
            key=lambda item: item["path"],
        ),
    }


def _decision_log(
    config: dict[str, Any],
    decision: dict[str, Any],
    plan: dict[str, Any],
    user: dict[str, Any],
    user_sha: str,
) -> dict[str, Any]:
    units = []
    for unit in user["decision_units"]:
        units.append(
            {
                "decision_unit": unit["decision_unit"],
                "pair_disposition": unit["pair_disposition"],
                "strict_core_enabled": unit["strict_core_enabled"],
                "accepted_warnings": sorted(unit.get("accepted_warnings", [])),
            }
        )
    return {
        "task_id": TASK_ID,
        "user_decision_record_path": config["upstream_artifacts"][
            "t04_user_decision_record"
        ],
        "user_decision_record_sha256": user_sha,
        "decision_unit_count": 4,
        "selected_decision_unit_count": 2,
        "rejected_decision_unit_count": 2,
        "strict_core_only_count": 2,
        "selection_path_not_independently_confirmed": True,
        "decision_hash": decision["decision_hash"],
        "freeze_decision_hash": decision["freeze_decision_hash"],
        "freeze_plan_hash": plan["freeze_plan_hash"],
        "decision_authority": user["decision_authority"],
        "automatic_recommendation_authoritative": False,
        "selection_path": "explicit_user_decision_not_automatic_recommendation",
        "decision_units": units,
    }


def _artifact_ref(output_dir: Path, name: str) -> dict[str, Any]:
    payload = (output_dir / name).read_bytes()
    return {
        "path": f"data/generated/r2/r2_t07/{output_dir.name}/{name}",
        "sha256": sha256_bytes(payload),
        "size_bytes": len(payload),
    }


def _final_manifest(
    config: dict[str, Any],
    output_dir: Path,
    selected: list[dict[str, Any]],
    decision_log: dict[str, Any],
) -> dict[str, Any]:
    ids = sorted(item["state_version_id"] for item in selected)
    return {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "completed_author_draft_pending_independent_scientific_review",
        "execution_commit": current_commit(ROOT),
        "registry_freeze_only": True,
        "replay_performed": False,
        "state_version_registry": _artifact_ref(
            output_dir, "r2_state_version_registry.csv"
        ),
        "interval_rule_registry": _artifact_ref(
            output_dir, "r2_interval_rule_registry.json"
        ),
        "event_state_machine_registry": _artifact_ref(
            output_dir, "r2_event_state_machine_registry.json"
        ),
        "freeze_decision_log": _artifact_ref(output_dir, "r2_freeze_decision_log.json"),
        "t02_contract_version": CONTRACT_VERSION,
        "t04_run_id": config["t04_binding"]["run_id"],
        "t04_decision_hash": config["t04_binding"]["decision_hash"],
        "t04_freeze_decision_hash": config["t04_binding"]["freeze_decision_hash"],
        "t04_freeze_plan_hash": config["t04_binding"]["freeze_plan_hash"],
        "t04_user_decision_record_sha256": decision_log["user_decision_record_sha256"],
        "t05_run_id": config["t05_binding"]["run_id"],
        "t05_database_sha256": config["t05_binding"]["database_sha256"],
        "canonical_daily_state_sha256": config["t05_binding"]["daily_sha256"],
        "canonical_event_zone_sha256": config["t05_binding"]["event_sha256"],
        "canonical_event_membership_sha256": config["t05_binding"]["membership_sha256"],
        "canonical_daily_row_count": config["t05_binding"]["daily_row_count"],
        "canonical_event_row_count": config["t05_binding"]["event_row_count"],
        "canonical_membership_row_count": config["t05_binding"]["membership_row_count"],
        "t06_run_id": config["t06_binding"]["authoritative_run"],
        "t06_merge_commit": config["t06_binding"]["merge_commit"],
        "t06_reviewed_head": config["t06_binding"]["reviewed_head"],
        "t06_scientific_review_id": config["t06_binding"]["scientific_review_id"],
        "t06_artifact_commit": config["t06_binding"]["artifact_commit"],
        "t06_replay_database_sha256": config["t06_binding"]["duckdb_sha256"],
        "frozen_version_count": len(selected),
        "frozen_state_version_ids": ids,
        "selection_path_not_independently_confirmed": True,
        "authoritative_time_fields": AUTHORITATIVE_TIMES,
        "non_authoritative_time_fields": [
            "r2_t06_replayed_transition_ledger.trigger_trade_date"
        ],
        "allowed_uses": ALLOWED_USES,
        "forbidden_reinterpretations": FORBIDDEN_REINTERPRETATIONS,
        "downstream_gates": {
            "R2-T08_allowed_to_start": False,
            "R3_allowed_to_start": False,
        },
    }


def _write_output_manifest(output_dir: Path) -> dict[str, Any]:
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
                "path": f"data/generated/r2/r2_t07/{output_dir.name}/{path.name}",
                "sha256": sha256_bytes(payload),
                "size_bytes": len(payload),
            }
        )
    manifest = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
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
    if not output_dir.name.startswith("R2-T07-"):
        raise T07GenerationError("output_run_id")
    _verify_t06_lineage(config, root, execution_commit)
    upstream_commit = config["upstream_commit"]

    contracts: dict[str, tuple[Any, dict[str, Any]]] = {}
    for name, path in config["source_contracts"].items():
        contracts[name] = (
            _bound_csv(root, upstream_commit, path)
            if path.endswith(".csv")
            else _bound_json(root, upstream_commit, path)
        )
    _verify_t02_contracts(config, contracts)

    upstream: dict[str, Any] = {}
    input_bindings: dict[str, dict[str, Any]] = {}
    for name, path in config["upstream_artifacts"].items():
        value = (
            None
            if name in {"t06_duckdb"}
            else _bound_json(root, upstream_commit, path)[0]
        )
        upstream[name] = value
        input_bindings[name] = _bound(root, upstream_commit, path)
    _verify_t04(
        config,
        upstream["t04_freeze_decision"],
        upstream["t04_freeze_plan"],
        upstream["t04_user_decision_record"],
    )
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
    selected = _selected_rows(config, upstream["t04_freeze_plan"])
    r1_rows, _ = contracts["r1_candidate_registry"]
    cell_rows, _ = contracts["t02_cell_registry"]
    adapter, _ = contracts["t03_interval_adapter"]
    route_data = {}
    for state in selected:
        route_data[state["state_version_id"]] = _route_binding(
            root, upstream_commit, state, adapter, cell_rows, r1_rows, config
        )
    user_sha = input_bindings["t04_user_decision_record"]["committed_byte_sha256"]
    for state in selected:
        state["warning_codes"] = (
            [
                "affected_lift_deterioration_vs_baseline",
                "layer_q_complexity_added",
                "same_sample_formal_revalidation_only",
                "selection_path_not_independently_confirmed",
            ]
            if state["state_line"] == "S_PCT"
            else [
                "V_security_negative_delta_share_material",
                "V_selectivity_reduced_but_guard_passed",
                "layer_q_complexity_added",
                "same_sample_formal_revalidation_only",
                "selection_path_not_independently_confirmed",
            ]
        )
    registry_fields = [
        "state_version_id",
        "freeze_status",
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
        "strict_core_enabled",
        "strict_core_source_candidate_cell_id",
        "state_formula_binding_id",
        "state_formula_binding_sha256",
        "r1_handoff_row_id",
        "r1_handoff_row_sha256",
        "confirmed_state_contract_id",
        "interval_rule_registry_id",
        "event_state_machine_registry_id",
        "state_risk_set_rule_id",
        "qualified_event_risk_set_rule_id",
        "t04_decision_unit",
        "t04_decision_hash",
        "t04_freeze_decision_hash",
        "t04_freeze_plan_hash",
        "t04_user_decision_record_sha256",
        "t05_run_id",
        "t06_run_id",
        "canonical_daily_state_sha256",
        "canonical_event_zone_sha256",
        "canonical_event_membership_sha256",
        "warning_codes",
        "selection_path_not_independently_confirmed",
        "allowed_uses",
        "forbidden_uses",
    ]
    registry_rows = _state_registry_rows(config, selected, route_data, user_sha)
    write_csv(
        output_dir / "r2_state_version_registry.csv", registry_rows, registry_fields
    )
    interval = _interval_registry(
        config, contracts, [state["state_version_id"] for state in selected]
    )
    event = _event_registry(
        config, contracts, [state["state_version_id"] for state in selected]
    )
    decision = _decision_log(
        config,
        upstream["t04_freeze_decision"],
        upstream["t04_freeze_plan"],
        upstream["t04_user_decision_record"],
        user_sha,
    )
    write_json(output_dir / "r2_interval_rule_registry.json", interval)
    write_json(output_dir / "r2_event_state_machine_registry.json", event)
    write_json(output_dir / "r2_freeze_decision_log.json", decision)
    write_json(
        output_dir / "r2_t07_supersession_record.json",
        config["supersession_record"] | {"successor_run_id": output_dir.name},
    )
    write_json(
        output_dir / "r2_t07_source_readiness.json",
        {
            "task_id": TASK_ID,
            "run_id": output_dir.name,
            "status": "passed",
            "binding_mode": "git_show_committed_blobs",
            "bindings": sorted(
                list(contracts.values())[0][1:]
                if False
                else [
                    *input_bindings.values(),
                    *[binding for _, binding in contracts.values()],
                ],
                key=lambda item: item["path"],
            ),
            "failure_count": 0,
        },
    )
    write_json(
        output_dir / "r2_t07_input_binding.json",
        {
            "task_id": TASK_ID,
            "run_id": output_dir.name,
            "status": "passed",
            "source_commit": upstream_commit,
            "t04": input_bindings,
            "source_contracts": [binding for _, binding in contracts.values()],
        },
    )
    write_json(
        output_dir / "r2_t07_canonical_artifact_binding.json",
        {
            "task_id": TASK_ID,
            "run_id": output_dir.name,
            "status": "passed",
            "t05": config["t05_binding"],
            "t06": config["t06_binding"],
        },
    )
    write_json(
        output_dir / "r2_final_freeze_manifest.json",
        _final_manifest(config, output_dir, selected, decision),
    )
    _write_output_manifest(output_dir)
    return output_dir


__all__ = [
    "ALLOWED_USES",
    "AUTHORITATIVE_TIMES",
    "FORBIDDEN_REINTERPRETATIONS",
    "FORBIDDEN_USES",
    "STATE_NAMES",
    "T07GenerationError",
    "run_formal",
]
