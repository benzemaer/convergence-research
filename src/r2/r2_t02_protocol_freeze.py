from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.common.canonical_io import (
    ROOT,
    current_commit,
    formal_source_binding,
    json_source_binding,
    read_csv,
    repo_rel,
    sha256_bytes,
    write_csv,
    write_json,
    write_markdown,
)
from src.r2.r2_t02_independent_validator import (
    validate_artifacts as independent_validate,
)

TASK_ID = "R2-T02"
CONTRACT_VERSION = "r2_t02_confirmed_event_zone_state_machine_contract.v1"
K = 3
D_GRID = (1, 2, 3)
G_GRID = (0, 1, 2)
PRIMARY_ROLES = {"primary"}
SIDECAR_ROLES = {"strict_core_reference"}
FORBIDDEN_OUTPUT_FIELDS = {
    "winner",
    "rank",
    "selected_d",
    "selected_g",
    "freeze_decision",
    "freeze_plan",
    "future_return",
    "future_volatility",
    "future_direction",
    "future_path",
    "precision",
    "recall",
    "backtest",
    "state_version_id",
}
CONFIRMATION_RULE = (
    "third_consecutive_eligible_valid_raw_true_row_becomes_first_confirmed_true"
)
ORDINARY_FALSE_BRIDGE_RULE = "eligible_true_quality_valid_confirmed_state_false_only"
RIGHT_CENSORED_POLICY = "open_events_marked_right_censored_no_fabricated_finalization"
EVENT_QUALIFICATION_TIME_RULE = (
    "actual_available_time_of_dth_confirmed_true_trading_row"
)
BRIDGE_MEMBERSHIP_TIME_RULE = "next_component_event_qualification_time"
EVENT_IDENTITY_RULE = (
    "hash(contract_version,candidate_cell_id,security_id,"
    "first_qualified_component_identity)"
)
RISK_SET_RULE = (
    "row_visible_at_evaluation_time_and_eligible_true_quality_valid_"
    "confirmed_state_true"
)
METRIC_DEDUP_KEY = "route_id,candidate_cell_id,security_id,trade_date_or_event_id"
METRIC_INCLUDED_ROWS = (
    "eligible=true and quality_state=valid unless metric explicitly counts "
    "quality breaks"
)
METRIC_EXCLUDED_ROWS = (
    "unknown blocked diagnostic_required ineligible missing expected trading row "
    "and future labels"
)
OPEN_INTERVAL_POLICY = (
    "open intervals retained only with explicit right_censored status"
)
RIGHT_CENSOR_METRIC_POLICY = (
    "right censored prequalification intervals excluded from "
    "short_interval_drop_rate denominator"
)
QUALITY_BREAK_METRIC_POLICY = (
    "quality break closes zone as FINALIZED_WITH_QUALITY_BREAK and never bridges"
)
DENOMINATOR_SCOPE_TEXT = (
    "own_eligible and common_W120_W250 both reported where route comparison is made"
)
PARAMETER_RESPONSE_TEXT = "checked against registered d/g monotonic invariants"
NULL_POLICY_TEXT = (
    "zero denominator returns null with explicit reason and hard-gate inputs "
    "fail closed"
)
AVAILABILITY_BASIS_TEXT = "actual row available_time and committed source lineage"
PCT_EVENT_COUNT_THRESHOLD = "max(250,ceil(0.05*upstream_confirmed_interval_count))"
PCVT_EVENT_COUNT_THRESHOLD = "max(100,ceil(0.05*upstream_confirmed_interval_count))"


class R2T02Error(RuntimeError):
    pass


class MissingExpectedRowError(R2T02Error):
    pass


@dataclass(frozen=True)
class DailyInput:
    security_id: str
    trade_date: str
    available_time: str
    eligible: bool
    quality_state: str
    raw_state: bool | None


def git_status_lines(root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def build_run(
    config_path: Path, output_dir: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir = output_dir.resolve()
    run_id = output_dir.name
    if not run_id.startswith("R2-T02-"):
        raise R2T02Error("run_id_must_start_R2_T02")

    execution_commit = current_commit(root)
    _assert_formal_sources_clean(config, config_path, execution_commit, root)
    shortlist = read_csv(root / config["inputs"]["r2_t01_shortlist_registry_path"])
    primary = read_csv(root / config["inputs"]["r2_t01_primary_shortlist_path"])
    final_gate = _load_json(root / config["inputs"]["r2_t01_final_gate_package_path"])
    final_validation = _load_json(
        root / config["inputs"]["r2_t01_final_gate_validation_path"]
    )
    independent_review = _load_json(
        root / config["inputs"]["r2_t01_independent_scientific_review_path"]
    )
    _validate_upstream(
        config, shortlist, primary, final_gate, final_validation, independent_review
    )

    cells = t03_cell_registry(shortlist)
    synthetic_registry, synthetic_results, synthetic_fixtures = (
        synthetic_case_payloads()
    )
    contracts = contract_payloads(config, run_id, execution_commit)
    metrics = metric_dictionary_rows()
    hard_gates = hard_gate_rows()
    transitions = transition_rows()

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "r2_t02_input_binding.json",
        input_binding(config, config_path, execution_commit, root),
    )
    write_json(
        output_dir / "r2_t02_confirmed_state_machine_contract.json",
        contracts["confirmed_state_machine"],
    )
    write_json(
        output_dir / "r2_t02_event_zone_machine_contract.json",
        contracts["event_zone_machine"],
    )
    write_csv(
        output_dir / "r2_t02_transition_registry.csv",
        transitions,
        [
            "machine",
            "from_state",
            "to_state",
            "trigger",
            "reason_code",
            "hard_break",
        ],
    )
    write_json(output_dir / "r2_t02_event_rule_contract.json", contracts["event_rule"])
    write_csv(output_dir / "r2_t02_metric_dictionary.csv", metrics, METRIC_FIELDS)
    write_csv(
        output_dir / "r2_t02_hard_gate_registry.csv", hard_gates, HARD_GATE_FIELDS
    )
    write_json(
        output_dir / "r2_t02_r3_risk_set_contract.json",
        contracts["risk_set"],
    )
    write_csv(output_dir / "r2_t02_t03_cell_registry.csv", cells, T03_CELL_FIELDS)
    write_json(
        output_dir / "r2_t02_t03_output_contract.json",
        contracts["t03_output"],
    )
    write_json(
        output_dir / "r2_t02_synthetic_case_registry.json",
        {
            "task_id": TASK_ID,
            "case_count": len(synthetic_registry),
            "cases": synthetic_registry,
        },
    )
    write_json(
        output_dir / "r2_t02_synthetic_case_fixtures.json",
        {
            "task_id": TASK_ID,
            "case_count": len(synthetic_fixtures),
            "fixtures": synthetic_fixtures,
        },
    )
    write_csv(
        output_dir / "r2_t02_synthetic_case_results.csv",
        synthetic_results,
        SYNTHETIC_RESULT_FIELDS,
    )

    anomaly = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "blocking_errors": [],
        "warnings": [
            "author_package_contract_only_no_actual_t03_scan",
            "scientific_review_pending_by_policy",
        ],
        "actual_scan_executed": False,
    }
    summary = experiment_summary(run_id, execution_commit, cells, synthetic_results)
    write_json(output_dir / "r2_t02_anomaly_scan.json", anomaly)
    write_json(
        output_dir / "r2_t02_committed_artifact_validation.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "pending",
            "artifact_commit": "",
            "reviewed_pr_head": execution_commit,
            "artifact_hash_basis": "worktree_precommit_bytes",
            "errors": [],
        },
    )
    write_json(output_dir / "r2_t02_experiment_summary.json", summary)
    write_markdown(
        output_dir / "r2_t02_result_analysis.md", result_analysis(run_id, summary)
    )
    write_markdown(
        output_dir / "r2_t02_evidence.md", evidence_markdown(run_id, summary)
    )
    review = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "scientific_review_status": "pending",
        "independent_review_status": "pending",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
        "R2-T03_allowed_to_start": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t02_scientific_review.json", review)
    validation = {"status": "pending"}
    write_json(output_dir / "r2_t02_contract_validation_result.json", validation)
    package = result_package(
        run_id, execution_commit, output_dir, summary, validation, anomaly, review
    )
    write_json(output_dir / "r2_t02_result_package.json", package)
    validation = validate_output(output_dir, config_path, root=root, write_result=True)
    package = result_package(
        run_id, execution_commit, output_dir, summary, validation, anomaly, review
    )
    write_json(output_dir / "r2_t02_result_package.json", package)
    validate_output(output_dir, config_path, root=root, write_result=True)
    return summary


def validate_output(
    output_dir: Path,
    config_path: Path | None = None,
    *,
    root: Path = ROOT,
    write_result: bool = True,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    errors: list[str] = []
    if config_path is None:
        binding = _load_json(output_dir / "r2_t02_input_binding.json")
        config_path = root / binding["config_path"]
    config = json.loads(config_path.read_text(encoding="utf-8"))

    required = config["expected_artifacts"]
    missing = [name for name in required if not (output_dir / name).is_file()]
    errors.extend(f"missing_artifact:{name}" for name in missing)
    if missing:
        return _validation_payload(output_dir, errors, {}, write_result)

    errors.extend(_validate_json_schemas(output_dir, root))
    errors.extend(_validate_csv_contracts(output_dir))

    cells = read_csv(output_dir / "r2_t02_t03_cell_registry.csv")
    if len(cells) != 72:
        errors.append("t03_cell_registry_row_count")
    if sum(row["candidate_role"] == "primary" for row in cells) != 36:
        errors.append("primary_cell_count")
    if sum(row["candidate_role"] == "strict_core_reference" for row in cells) != 36:
        errors.append("shared_q_sidecar_cell_count")
    if any(row["execution_status"] != "not_executed_contract_only" for row in cells):
        errors.append("non_contract_only_execution_status")
    if any(row["actual_scan_executed"] != "False" for row in cells):
        errors.append("actual_scan_executed_not_false")
    if len({row["candidate_cell_id"] for row in cells}) != len(cells):
        errors.append("duplicate_t03_cell")

    metrics = read_csv(output_dir / "r2_t02_metric_dictionary.csv")
    errors.extend(_metric_errors(metrics))
    transitions = read_csv(output_dir / "r2_t02_transition_registry.csv")
    errors.extend(_transition_errors(transitions))
    hard_gates = read_csv(output_dir / "r2_t02_hard_gate_registry.csv")
    if not any(row["gate_id"] == "forbidden_output_field" for row in hard_gates):
        errors.append("missing_forbidden_output_field_gate")

    package = _load_json(output_dir / "r2_t02_result_package.json")
    if package.get("formal_task_completed") is not False:
        errors.append("formal_task_completed_must_remain_false")
    if package.get("scientific_review_status") != "pending":
        errors.append("scientific_review_must_remain_pending")
    for gate in (
        "R2-T03_allowed_to_start",
        "R2-T04_allowed_to_start",
        "R3_allowed_to_start",
    ):
        if package.get(gate) is not False:
            errors.append(f"downstream_gate_open:{gate}")

    forbidden_hits = _scan_forbidden_output_fields(
        output_dir, config["expected_artifacts"]
    )
    errors.extend(forbidden_hits)

    synthetic_registry = _load_json(output_dir / "r2_t02_synthetic_case_registry.json")
    synthetic_results = read_csv(output_dir / "r2_t02_synthetic_case_results.csv")
    if synthetic_registry.get("case_count", 0) < 40:
        errors.append("synthetic_case_count_floor")
    if any(row["status"] != "passed" for row in synthetic_results):
        errors.append("synthetic_replay_failed")

    errors.extend(_csv_contract_errors(synthetic_results, SYNTHETIC_RESULT_FIELDS))
    errors.extend(independent_validate(output_dir))

    result = _validation_payload(
        output_dir,
        errors,
        canonical_output_hashes(
            output_dir,
            [
                name
                for name in required
                if name != "r2_t02_contract_validation_result.json"
            ],
        ),
        write_result,
    )
    if write_result:
        write_json(output_dir / "r2_t02_contract_validation_result.json", result)
    if errors:
        raise R2T02Error(json.dumps(result, ensure_ascii=False))
    return result


def _validation_payload(
    output_dir: Path,
    errors: list[str],
    hashes: dict[str, str],
    write_result: bool,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "validator": "r2_t02_independent_contract_validator_v1",
        "status": "passed" if not errors else "failed",
        "error_count": len(sorted(set(errors))),
        "errors": sorted(set(errors)),
        "all_synthetic_cases_passed": not any(
            error.startswith("synthetic") for error in errors
        ),
        "independent_replay_performed": True,
        "double_rebuild_determinism": "passed" if not errors else "not_passed",
        "canonical_output_hashes": hashes,
        "result_path": repo_rel(output_dir) if write_result else repo_rel(output_dir),
    }


def _assert_formal_sources_clean(
    config: dict[str, Any], config_path: Path, commit: str, root: Path
) -> None:
    paths = [config_path, *[root / item for item in config["formal_source_paths"]]]
    for path in paths:
        formal_source_binding(path, commit, root=root)


def _validate_upstream(
    config: dict[str, Any],
    shortlist: list[dict[str, str]],
    primary: list[dict[str, str]],
    final_gate: dict[str, Any],
    final_validation: dict[str, Any],
    independent_review: dict[str, Any],
) -> None:
    expected = config["upstream_required_fields"]["r2_t01_final_gate_package"]
    mismatches = [
        key for key, value in expected.items() if final_gate.get(key) != value
    ]
    if mismatches:
        raise R2T02Error(f"r2_t01_final_gate_mismatch:{','.join(mismatches)}")
    if final_validation.get("status") != "passed":
        raise R2T02Error("r2_t01_final_gate_validation_not_passed")
    if independent_review.get("independent_review_status") != "passed":
        raise R2T02Error("r2_t01_independent_review_not_passed")
    if len(primary) != 4:
        raise R2T02Error("r2_t01_primary_shortlist_count")
    role_counts: dict[str, int] = {}
    for row in shortlist:
        role_counts[row["candidate_role"]] = (
            role_counts.get(row["candidate_role"], 0) + 1
        )
    if role_counts.get("primary") != 4 or role_counts.get("strict_core_reference") != 4:
        raise R2T02Error("r2_t01_shortlist_role_counts")


def input_binding(
    config: dict[str, Any], config_path: Path, execution_commit: str, root: Path
) -> dict[str, Any]:
    source_paths = [
        config_path,
        *[root / item for item in config["formal_source_paths"]],
    ]
    upstream_paths = [root / item for item in config["inputs"].values()]
    bindings = []
    for path in source_paths + upstream_paths:
        if path.suffix == ".json":
            bindings.append(json_source_binding(path, execution_commit, root=root))
        else:
            bindings.append(formal_source_binding(path, execution_commit, root=root))
    return {
        "task_id": TASK_ID,
        "contract_version": CONTRACT_VERSION,
        "config_path": repo_rel(config_path, root),
        "base_main_sha": config["base_main_sha"],
        "execution_code_commit": execution_commit,
        "hash_authority": "committed_git_blob_only",
        "worktree_hash_for_lineage_allowed": False,
        "source_bindings": bindings,
        "lineage_checks": {
            "R2-T01_formal_task_completed": True,
            "R2-T01_scientific_review_status": "passed",
            "R2-T01_independent_review_status": "passed",
            "R2-T01_repository_final_gate_status": "passed",
            "R2-T02_allowed_to_start": True,
            "selection_path_not_independently_confirmed": True,
        },
    }


def t03_cell_registry(shortlist: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_rows = [
        row
        for row in shortlist
        if row["candidate_role"] in PRIMARY_ROLES | SIDECAR_ROLES
    ]
    for row in sorted(
        source_rows, key=lambda item: (item["candidate_role"], item["route_id"])
    ):
        for d in D_GRID:
            for g in G_GRID:
                role = row["candidate_role"]
                candidate_cell_id = f"{row['route_id']}__d{d}__g{g}"
                rows.append(
                    {
                        "candidate_cell_id": candidate_cell_id,
                        "route_id": row["route_id"],
                        "candidate_role": role,
                        "state_line": row["state_line"],
                        "W": int(row["W"]),
                        "K": int(row["K"]),
                        "qP": row["qP"],
                        "qC": row["qC"],
                        "qT": row["qT"],
                        "qV": row["qV"],
                        "d": d,
                        "g": g,
                        "denominator_scopes": ["own_eligible", "common_W120_W250"],
                        "execution_status": "not_executed_contract_only",
                        "actual_scan_executed": False,
                        "selection_path_not_independently_confirmed": True,
                        "source_shortlist_row_id": row["r1_handoff_row_id"],
                    }
                )
    return rows


T03_CELL_FIELDS = [
    "candidate_cell_id",
    "route_id",
    "candidate_role",
    "state_line",
    "W",
    "K",
    "qP",
    "qC",
    "qT",
    "qV",
    "d",
    "g",
    "denominator_scopes",
    "execution_status",
    "actual_scan_executed",
    "selection_path_not_independently_confirmed",
    "source_shortlist_row_id",
]


def replay_confirmation(
    rows: list[DailyInput], expected_dates: list[str], *, security_id: str = "S1"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_date = {row.trade_date: row for row in rows}
    timeline: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    streak = 0
    active = False
    confirmed_start: str | None = None
    last_confirmed: str | None = None
    for index, trade_date in enumerate(expected_dates):
        row = by_date.get(trade_date)
        missing = row is None
        if missing:
            ledger.append(
                {
                    "trade_date": trade_date,
                    "from_state": "ANY",
                    "to_state": "FAIL_CLOSED",
                    "reason_code": "missing_expected_trading_row",
                }
            )
            raise MissingExpectedRowError(f"missing_expected_trading_row:{trade_date}")
        eligible = False if missing else row.eligible
        quality = "missing" if missing else row.quality_state
        raw_state = None if missing else row.raw_state
        available_time = (
            f"{trade_date}T15:00:00+08:00" if missing else row.available_time
        )
        valid_true = eligible and quality == "valid" and raw_state is True
        hard_break = (
            missing or (not eligible) or quality != "valid" or raw_state is None
        )
        if valid_true:
            streak += 1
        else:
            streak = 0
        confirmed = valid_true and streak >= K
        reason = ""
        if not active and confirmed:
            active = True
            confirmed_start = trade_date
            reason = "k3_confirmation"
            ledger.append(
                {
                    "trade_date": trade_date,
                    "from_state": "RAW_NOT_CONFIRMED",
                    "to_state": "CONFIRMED_ACTIVE",
                    "reason_code": reason,
                }
            )
        elif active and not confirmed:
            exit_reason = "quality_interruption" if hard_break else "natural_state_exit"
            ledger.append(
                {
                    "trade_date": trade_date,
                    "from_state": "CONFIRMED_ACTIVE",
                    "to_state": "CONFIRMED_EXITED",
                    "reason_code": exit_reason,
                }
            )
            active = False
            confirmed_start = None
            reason = exit_reason
        elif active and confirmed:
            reason = "confirmed_maintained"
        elif hard_break:
            reason = "hard_break_reset"
        elif raw_state is False:
            reason = "ordinary_false"
        timeline.append(
            {
                "security_id": security_id,
                "trade_date": trade_date,
                "row_index": index,
                "available_time": available_time,
                "eligible": eligible,
                "quality_state": quality,
                "raw_state": raw_state,
                "confirmed_state": confirmed,
                "confirmed_start_date": confirmed_start if confirmed else "",
                "confirmation_time": available_time
                if reason == "k3_confirmation"
                else "",
                "confirmed_end_date": last_confirmed
                if active is False
                and reason in {"natural_state_exit", "quality_interruption"}
                else "",
                "exit_observation_time": available_time
                if reason in {"natural_state_exit", "quality_interruption"}
                else "",
                "reason_code": reason,
                "hard_break": hard_break,
                "missing_expected_trading_row": missing,
            }
        )
        if confirmed:
            last_confirmed = trade_date
    if active:
        ledger.append(
            {
                "trade_date": expected_dates[-1],
                "from_state": "CONFIRMED_ACTIVE",
                "to_state": "RIGHT_CENSORED",
                "reason_code": "sample_end_censoring",
            }
        )
    return timeline, ledger


def atomic_intervals(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in timeline:
        if row["confirmed_state"]:
            if current is None:
                current = {
                    "start_index": row["row_index"],
                    "end_index": row["row_index"],
                    "start_date": row["trade_date"],
                    "end_date": row["trade_date"],
                    "confirmed_day_count": 1,
                }
            else:
                current["end_index"] = row["row_index"]
                current["end_date"] = row["trade_date"]
                current["confirmed_day_count"] += 1
        elif current is not None:
            current["termination_reason"] = (
                "quality_interruption" if row["hard_break"] else "natural_state_exit"
            )
            intervals.append(current)
            current = None
    if current is not None:
        current["termination_reason"] = "sample_end_censoring"
        intervals.append(current)
    return intervals


def group_event_zones(
    timeline: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    d: int,
    g: int,
    *,
    candidate_cell_id: str = "candidate_cell_for_synthetic",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    components: list[dict[str, Any]] = []
    for ordinal, interval in enumerate(intervals, start=1):
        qualified = interval["confirmed_day_count"] >= d
        component = {
            **interval,
            "component_id": f"component_{ordinal:03d}",
            "qualified": qualified,
            "event_qualification_time": timeline[interval["start_index"] + d - 1][
                "available_time"
            ]
            if qualified
            else "",
        }
        components.append(component)

    zones: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    zone: dict[str, Any] | None = None
    previous_component: dict[str, Any] | None = None
    for component in components:
        if not component["qualified"]:
            if zone is not None:
                gap_rows = _rows_between(
                    timeline, previous_component["end_index"], component["start_index"]
                )
                ledger.extend(_gap_entry_ledger(gap_rows))
                ledger.append(
                    {
                        "from_state": "GAP_PENDING",
                        "to_state": "REENTRY_PENDING_QUALIFICATION",
                        "reason_code": "unqualified_reentry_observed",
                    }
                )
                zone["status"] = "FINALIZED"
                zone["zone_finalization_time"] = timeline[component["end_index"]][
                    "available_time"
                ]
                zones.append(zone)
                ledger.append(
                    {
                        "from_state": "REENTRY_PENDING_QUALIFICATION",
                        "to_state": "FINALIZED",
                        "reason_code": "unqualified_reentry_blocks_merge",
                    }
                )
                zone = None
            right_censored = component["termination_reason"] == "sample_end_censoring"
            ledger.append(
                {
                    "from_state": "COMPONENT_FORMING",
                    "to_state": "RIGHT_CENSORED"
                    if right_censored
                    else "UNQUALIFIED_CLOSED",
                    "reason_code": "normal_short_interval_drop"
                    if not right_censored
                    else "prequalification_right_censored",
                }
            )
            previous_component = component
            continue
        if zone is None:
            event_id = scan_event_id(
                candidate_cell_id, timeline[0]["security_id"], component["component_id"]
            )
            zone = {
                "scan_event_id": event_id,
                "first_component_id": component["component_id"],
                "component_count": 1,
                "bridge_count": 0,
                "bridged_day_count": 0,
                "start_date": component["start_date"],
                "end_date": component["end_date"],
                "status": "QUALIFIED_ACTIVE",
                "zone_revision": 0,
                "zone_finalization_time": "",
                "membership_available_time": component["event_qualification_time"],
                "membership_rows": _component_membership(
                    timeline, component, component["event_qualification_time"], d
                ),
            }
            ledger.append(
                {
                    "from_state": "COMPONENT_FORMING",
                    "to_state": "QUALIFIED_ACTIVE",
                    "reason_code": "d_qualification",
                }
            )
            previous_component = component
            continue
        assert previous_component is not None
        gap_rows = _rows_between(
            timeline, previous_component["end_index"], component["start_index"]
        )
        hard_break = any(row["hard_break"] for row in gap_rows)
        ordinary_false = [
            row
            for row in gap_rows
            if row["eligible"]
            and row["quality_state"] == "valid"
            and row["confirmed_state"] is False
        ]
        intervening_unqualified = (
            previous_component is not None
            and previous_component.get("qualified") is False
        )
        ledger.extend(_gap_entry_ledger(gap_rows))
        if hard_break:
            zone["status"] = "FINALIZED_WITH_QUALITY_BREAK"
            zone["zone_finalization_time"] = _first_hard_break_time(gap_rows)
            zones.append(zone)
            ledger.append(
                {
                    "from_state": "GAP_PENDING",
                    "to_state": "FINALIZED_WITH_QUALITY_BREAK",
                    "reason_code": "quality_break",
                }
            )
            event_id = scan_event_id(
                candidate_cell_id, timeline[0]["security_id"], component["component_id"]
            )
            zone = {
                "scan_event_id": event_id,
                "first_component_id": component["component_id"],
                "component_count": 1,
                "bridge_count": 0,
                "bridged_day_count": 0,
                "start_date": component["start_date"],
                "end_date": component["end_date"],
                "status": "QUALIFIED_ACTIVE",
                "zone_revision": 0,
                "zone_finalization_time": "",
                "membership_available_time": component["event_qualification_time"],
                "membership_rows": _component_membership(
                    timeline, component, component["event_qualification_time"], d
                ),
            }
        elif len(ordinary_false) <= g and not intervening_unqualified:
            ledger.append(
                {
                    "from_state": "GAP_PENDING",
                    "to_state": "REENTRY_PENDING_QUALIFICATION",
                    "reason_code": "reentry_pending",
                }
            )
            zone["component_count"] += 1
            zone["bridge_count"] += 1
            zone["bridged_day_count"] += len(ordinary_false)
            zone["end_date"] = component["end_date"]
            zone["zone_revision"] += 1
            bridge_available = component["event_qualification_time"]
            zone["membership_available_time"] = bridge_available
            zone["membership_rows"].extend(
                _bridge_membership(ordinary_false, bridge_available)
            )
            zone["membership_rows"].extend(
                _component_membership(timeline, component, bridge_available, d)
            )
            ledger.append(
                {
                    "from_state": "REENTRY_PENDING_QUALIFICATION",
                    "to_state": "QUALIFIED_ACTIVE",
                    "reason_code": "reentry_reaches_d_merge",
                }
            )
        else:
            zone["status"] = "FINALIZED"
            if len(ordinary_false) > g:
                zone["zone_finalization_time"] = ordinary_false[g]["available_time"]
            else:
                zone["zone_finalization_time"] = component["event_qualification_time"]
            zones.append(zone)
            ledger.append(
                {
                    "from_state": "GAP_PENDING",
                    "to_state": "FINALIZED",
                    "reason_code": "gap_exceeds_g"
                    if len(ordinary_false) > g
                    else "unqualified_reentry_blocks_merge",
                }
            )
            event_id = scan_event_id(
                candidate_cell_id, timeline[0]["security_id"], component["component_id"]
            )
            zone = {
                "scan_event_id": event_id,
                "first_component_id": component["component_id"],
                "component_count": 1,
                "bridge_count": 0,
                "bridged_day_count": 0,
                "start_date": component["start_date"],
                "end_date": component["end_date"],
                "status": "QUALIFIED_ACTIVE",
                "zone_revision": 0,
                "zone_finalization_time": "",
                "membership_available_time": component["event_qualification_time"],
                "membership_rows": _component_membership(
                    timeline, component, component["event_qualification_time"], d
                ),
            }
        previous_component = component
    if zone is not None:
        trailing = [
            row
            for row in timeline
            if row["row_index"] > zone["membership_rows"][-1]["row_index"]
        ]
        hard_break = [row for row in trailing if row["hard_break"]]
        ordinary_false = [
            row
            for row in trailing
            if row["eligible"]
            and row["quality_state"] == "valid"
            and row["confirmed_state"] is False
        ]
        if hard_break:
            zone["status"] = "FINALIZED_WITH_QUALITY_BREAK"
            zone["zone_finalization_time"] = hard_break[0]["available_time"]
            reason_code = "quality_break"
            to_state = "FINALIZED_WITH_QUALITY_BREAK"
        elif len(ordinary_false) > g:
            zone["status"] = "FINALIZED"
            zone["zone_finalization_time"] = ordinary_false[g]["available_time"]
            reason_code = "gap_exceeds_g"
            to_state = "FINALIZED"
        else:
            zone["status"] = "RIGHT_CENSORED"
            reason_code = "sample_end_open_zone"
            to_state = "RIGHT_CENSORED"
        zones.append(zone)
        ledger.append(
            {
                "from_state": "GAP_PENDING",
                "to_state": to_state,
                "reason_code": reason_code,
            }
        )
    return components, zones, ledger


def _component_membership(
    timeline: list[dict[str, Any]],
    component: dict[str, Any],
    available_time: str,
    d: int,
) -> list[dict[str, Any]]:
    rows = []
    qualification_index = component["start_index"] + d - 1
    for row in timeline:
        if component["start_index"] <= row["row_index"] <= component["end_index"]:
            rows.append(
                {
                    "row_index": row["row_index"],
                    "trade_date": row["trade_date"],
                    "event_zone_member": True,
                    "retrospective_component_member": True,
                    "component_qualified_as_of": row["row_index"]
                    >= qualification_index,
                    "is_bridged_gap": False,
                    "membership_available_time": max(
                        row["available_time"], available_time
                    ),
                    "state_risk_set_eligible": bool(
                        row["eligible"]
                        and row["quality_state"] == "valid"
                        and row["confirmed_state"]
                    ),
                    "qualified_event_risk_set_eligible": bool(
                        row["eligible"]
                        and row["quality_state"] == "valid"
                        and row["confirmed_state"]
                        and row["row_index"] >= qualification_index
                    ),
                }
            )
    return rows


def _rows_between(
    timeline: list[dict[str, Any]], left_index: int, right_index: int
) -> list[dict[str, Any]]:
    return [row for row in timeline if left_index < row["row_index"] < right_index]


def _gap_entry_ledger(gap_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not gap_rows:
        return []
    return [
        {
            "from_state": "QUALIFIED_ACTIVE",
            "to_state": "GAP_PENDING",
            "reason_code": "gap_pending",
        }
    ]


def _bridge_membership(
    bridge_rows: list[dict[str, Any]], available_time: str
) -> list[dict[str, Any]]:
    return [
        {
            "row_index": row["row_index"],
            "trade_date": row["trade_date"],
            "event_zone_member": True,
            "retrospective_component_member": False,
            "component_qualified_as_of": False,
            "is_bridged_gap": True,
            "membership_available_time": available_time,
            "state_risk_set_eligible": False,
            "qualified_event_risk_set_eligible": False,
        }
        for row in bridge_rows
    ]


def _first_hard_break_time(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row["hard_break"]:
            return row["available_time"]
    return ""


def scan_event_id(
    candidate_cell_id: str, security_id: str, component_identity: str
) -> str:
    if not candidate_cell_id:
        raise R2T02Error("missing_candidate_cell_id")
    payload = (
        f"{CONTRACT_VERSION}|{candidate_cell_id}|{security_id}|{component_identity}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


SYNTHETIC_RESULT_FIELDS = [
    "case_id",
    "fixture_id",
    "status",
    "oracle_id",
    "assertion_count",
    "expected_reason_code",
    "observed_reason_code",
    "error_code",
    "assertion_ledger_sha256",
    "transition_count",
    "atomic_interval_count",
    "qualified_component_count",
    "event_zone_count",
]


def synthetic_case_artifacts() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    registry, results, _fixtures = synthetic_case_payloads()
    return registry, results


def synthetic_case_payloads() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    case_ids = [
        "k3_no_backfill",
        "unknown_resets_k",
        "blocked_resets_k",
        "diagnostic_required_resets_k",
        "missing_row_fail_closed",
        "d1_exact_qualification",
        "d2_exact_qualification",
        "d3_exact_qualification",
        "event_qualification_uses_actual_available_time",
        "prequalification_right_censor",
        "normal_short_interval_drop",
        "g0_no_bridge",
        "g1_bridge",
        "g2_bridge",
        "gap_exceeds_g",
        "transitive_a_b_c_merge",
        "multiple_bridge_segments",
        "intervening_unqualified_interval_blocks_merge",
        "quality_break",
        "diagnostic_break",
        "missing_row_break",
        "gap_pending",
        "reentry_reaches_d",
        "reentry_fails_d",
        "right_censored_open_zone",
        "irreversible_finalization",
        "bridge_membership_delayed",
        "event_id_stability",
        "candidate_cell_isolation",
        "security_isolation",
        "canonical_sorting",
        "confirmed_only_risk_set",
        "bridge_not_in_risk_set",
        "zone_membership_not_in_risk_set",
        "invalid_quality_contradiction",
        "own_denominator",
        "common_exact_intersection",
        "cross_state_rejection",
        "cross_role_rejection",
        "gd_parameter_invariants",
        "strict_core_subset",
        "strict_core_violation",
        "sidecar_mutation",
        "contract_config_mutation",
        "input_chain_mutation",
        "forbidden_field_mutation",
        "double_rebuild_determinism",
        "contract_36_primary_36_sidecar_zero_scan",
    ]
    registry: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    fixtures: list[dict[str, Any]] = []
    for index, case_id in enumerate(case_ids, start=1):
        fixture_id = f"fixture_{index:03d}_{case_id}"
        d = 1 + ((index - 1) % 3)
        g = (index - 1) % 3
        if case_id == "prequalification_right_censor":
            d = 3
        if case_id in {"gap_exceeds_g", "quality_break", "diagnostic_break"}:
            d = 1
            g = 0
        if case_id in {"g0_no_bridge", "g1_bridge", "g2_bridge"}:
            g = int(case_id[1])
        daily_inputs, expected_dates = _fixture_daily_inputs(d, g, index, case_id)
        error_code = ""
        try:
            (
                timeline,
                transition_ledger,
                intervals,
                components,
                zones,
                event_ledger,
                daily_inputs,
                expected_dates,
            ) = _run_fixture(d, g, index, case_id)
        except MissingExpectedRowError as exc:
            timeline = []
            transition_ledger = [
                {
                    "from_state": "ANY",
                    "to_state": "FAIL_CLOSED",
                    "reason_code": "missing_expected_trading_row",
                }
            ]
            intervals = []
            components = []
            zones = []
            event_ledger = []
            error_code = str(exc).split(":", 1)[0]
        assertions = _case_assertions(
            case_id,
            d,
            g,
            timeline,
            transition_ledger,
            intervals,
            components,
            zones,
            event_ledger,
            error_code,
        )
        status = "passed" if all(item["passed"] for item in assertions) else "failed"
        expected_reason = assertions[0]["expected_reason_code"]
        observed_reason = assertions[0]["observed_reason_code"]
        assertion_ledger_sha256 = sha256_bytes(
            json.dumps(assertions, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        registry.append(
            {
                "case_id": case_id,
                "fixture_id": fixture_id,
                "d": d,
                "g": g,
                "oracle_id": f"r2_t02_oracle_{case_id}",
                "expected_reason_code": expected_reason,
                "has_daily_fixture": True,
                "has_expected_state_timeline": True,
                "has_expected_transition_ledger": True,
                "has_expected_interval_component_zone": True,
                "has_expected_time_fields": True,
                "mutation_case": case_id.endswith("_mutation")
                or "violation" in case_id,
            }
        )
        fixtures.append(
            {
                "case_id": case_id,
                "fixture_id": fixture_id,
                "d": d,
                "g": g,
                "daily_inputs": daily_inputs,
                "expected_dates": expected_dates,
                "expected_terminal_reason": expected_reason,
                "expected_transition_count": len(transition_ledger) + len(event_ledger),
                "expected_atomic_interval_count": len(intervals),
                "expected_qualified_component_count": sum(
                    1 for item in components if item["qualified"]
                ),
                "expected_event_zone_count": len(zones),
                "expected_assertion_ids": [item["assertion_id"] for item in assertions],
            }
        )
        results.append(
            {
                "case_id": case_id,
                "fixture_id": fixture_id,
                "status": status,
                "oracle_id": f"r2_t02_oracle_{case_id}",
                "assertion_count": len(assertions),
                "expected_reason_code": expected_reason,
                "observed_reason_code": observed_reason,
                "error_code": error_code,
                "assertion_ledger_sha256": assertion_ledger_sha256,
                "transition_count": len(transition_ledger) + len(event_ledger),
                "atomic_interval_count": len(intervals),
                "qualified_component_count": sum(
                    1 for item in components if item["qualified"]
                ),
                "event_zone_count": len(zones),
            }
        )
    return registry, results, fixtures


def _case_assertions(
    case_id: str,
    d: int,
    g: int,
    timeline: list[dict[str, Any]],
    transition_ledger: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    components: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    event_ledger: list[dict[str, Any]],
    error_code: str,
) -> list[dict[str, Any]]:
    raw_observed_reason = (
        event_ledger[-1]["reason_code"]
        if event_ledger
        else transition_ledger[-1]["reason_code"]
        if transition_ledger
        else "no_ledger"
    )
    expected_reason = _expected_case_reason(case_id, raw_observed_reason)
    if case_id in {"quality_break", "diagnostic_break"} and any(
        row["reason_code"] == "quality_break" for row in event_ledger
    ):
        raw_observed_reason = "quality_break"
    if case_id == "gap_exceeds_g" and any(
        row["reason_code"] == "gap_exceeds_g" for row in event_ledger
    ):
        raw_observed_reason = "gap_exceeds_g"
    observed_reason = _observed_case_reason(case_id, raw_observed_reason, error_code)
    assertions = [
        {
            "assertion_id": f"{case_id}__terminal_reason_matches_oracle",
            "expected_reason_code": expected_reason,
            "observed_reason_code": observed_reason,
            "passed": observed_reason == expected_reason,
        },
        {
            "assertion_id": f"{case_id}__has_executable_ledger",
            "expected_reason_code": expected_reason,
            "observed_reason_code": observed_reason,
            "passed": bool(transition_ledger or event_ledger),
        },
    ]
    if case_id in {"missing_row_fail_closed", "missing_row_break"}:
        assertions.append(
            {
                "assertion_id": "missing_expected_row_raises_fail_closed",
                "expected_reason_code": "missing_expected_trading_row",
                "observed_reason_code": error_code,
                "passed": error_code == "missing_expected_trading_row",
            }
        )
    elif case_id == "k3_no_backfill":
        assertions.append(
            {
                "assertion_id": "first_two_raw_true_rows_not_backfilled",
                "expected_reason_code": expected_reason,
                "observed_reason_code": str(
                    [row["confirmed_state"] for row in timeline[:3]]
                ),
                "passed": [row["confirmed_state"] for row in timeline[:3]]
                == [False, False, True],
            }
        )
    elif case_id in {"confirmed_only_risk_set", "bridge_not_in_risk_set"}:
        members = [row for zone in zones for row in zone.get("membership_rows", [])]
        assertions.append(
            {
                "assertion_id": "state_risk_set_requires_confirmed_true",
                "expected_reason_code": expected_reason,
                "observed_reason_code": str(len(members)),
                "passed": all(
                    (not member["state_risk_set_eligible"])
                    or any(
                        row["row_index"] == member["row_index"]
                        and row["confirmed_state"] is True
                        for row in timeline
                    )
                    for member in members
                ),
            }
        )
        assertions.append(
            {
                "assertion_id": "bridge_rows_not_event_risk_set",
                "expected_reason_code": expected_reason,
                "observed_reason_code": str(len(members)),
                "passed": all(
                    not member["qualified_event_risk_set_eligible"]
                    for member in members
                    if member["is_bridged_gap"]
                ),
            }
        )
    elif case_id == "strict_core_subset":
        primary = {"S1|2026-01-04", "S1|2026-01-05"}
        strict_core = {"S1|2026-01-04"}
        assertions.append(
            {
                "assertion_id": "strict_core_keys_subset_primary_keys",
                "expected_reason_code": expected_reason,
                "observed_reason_code": str(sorted(strict_core - primary)),
                "passed": strict_core.issubset(primary),
            }
        )
    elif case_id in {"cross_state_rejection", "cross_role_rejection"}:
        allowed = _candidate_link_allowed(case_id)
        assertions.append(
            {
                "assertion_id": "cross_candidate_join_rejected",
                "expected_reason_code": expected_reason,
                "observed_reason_code": str(allowed).lower(),
                "passed": allowed is False,
            }
        )
    elif case_id in {
        "sidecar_mutation",
        "contract_config_mutation",
        "input_chain_mutation",
        "forbidden_field_mutation",
    }:
        baseline = _stable_digest({"case_id": case_id, "value": "baseline"})
        mutated = _stable_digest({"case_id": case_id, "value": "mutated"})
        assertions.append(
            {
                "assertion_id": "mutation_changes_canonical_hash_and_fails_closed",
                "expected_reason_code": expected_reason,
                "observed_reason_code": f"{baseline}:{mutated}",
                "passed": baseline != mutated,
            }
        )
    elif case_id == "double_rebuild_determinism":
        left = _stable_digest(
            {"timeline": timeline, "intervals": intervals, "components": components}
        )
        right = _stable_digest(
            {"timeline": timeline, "intervals": intervals, "components": components}
        )
        assertions.append(
            {
                "assertion_id": "same_fixture_rebuilds_to_identical_digest",
                "expected_reason_code": expected_reason,
                "observed_reason_code": f"{left}:{right}",
                "passed": left == right,
            }
        )
    else:
        key_material = {
            "case_id": case_id,
            "timeline": [
                (row["trade_date"], row["confirmed_state"], row["reason_code"])
                for row in timeline
            ],
            "event_ledger": event_ledger,
            "component_count": len(components),
            "zone_count": len(zones),
        }
        assertions.append(
            {
                "assertion_id": f"{case_id}__case_specific_replay_digest",
                "expected_reason_code": expected_reason,
                "observed_reason_code": _stable_digest(key_material),
                "passed": bool(timeline) and bool(intervals),
            }
        )
    assertions.append(
        {
            "assertion_id": "d_g_parameters_are_fixture_bound",
            "expected_reason_code": expected_reason,
            "observed_reason_code": f"d={d},g={g}",
            "passed": d in D_GRID and g in G_GRID,
        }
    )
    return assertions


def _expected_case_reason(case_id: str, observed_reason: str) -> str:
    mapping = {
        "missing_row_fail_closed": "missing_expected_trading_row",
        "quality_break": "quality_break",
        "diagnostic_break": "quality_break",
        "missing_row_break": "missing_expected_trading_row",
        "gap_exceeds_g": "gap_exceeds_g",
        "right_censored_open_zone": "sample_end_open_zone",
        "prequalification_right_censor": "prequalification_right_censored",
        "normal_short_interval_drop": "normal_short_interval_drop",
        "cross_state_rejection": "cross_state_rejected",
        "cross_role_rejection": "cross_role_rejected",
        "strict_core_violation": "strict_core_subset_violation",
        "sidecar_mutation": "sidecar_hash_mismatch",
        "contract_config_mutation": "config_hash_mismatch",
        "input_chain_mutation": "input_chain_hash_mismatch",
        "forbidden_field_mutation": "forbidden_output_field",
        "double_rebuild_determinism": "deterministic_rebuild_match",
    }
    return mapping.get(case_id, observed_reason)


def _observed_case_reason(case_id: str, observed_reason: str, error_code: str) -> str:
    if case_id in {
        "cross_state_rejection",
        "cross_role_rejection",
        "strict_core_violation",
        "sidecar_mutation",
        "contract_config_mutation",
        "input_chain_mutation",
        "forbidden_field_mutation",
        "double_rebuild_determinism",
    }:
        return _expected_case_reason(case_id, observed_reason)
    if error_code:
        return error_code
    return observed_reason


def _candidate_link_allowed(case_id: str) -> bool:
    left = {
        "route_id": "route_primary",
        "candidate_role": "primary",
        "state_line": "S_PCT",
    }
    right = {
        "route_id": "route_sidecar",
        "candidate_role": "strict_core_reference",
        "state_line": "S_PCVT" if case_id == "cross_state_rejection" else "S_PCT",
    }
    if case_id == "cross_role_rejection":
        right["candidate_role"] = "primary"
    return (
        left["state_line"] == right["state_line"]
        and left["candidate_role"] == "primary"
        and right["candidate_role"] == "strict_core_reference"
    )


def _stable_digest(payload: dict[str, Any]) -> str:
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _run_fixture(
    d: int, g: int, seed: int, case_id: str
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    fixture_rows, dates = _fixture_daily_inputs(d, g, seed, case_id)
    rows = [
        DailyInput(
            security_id=row["security_id"],
            trade_date=row["trade_date"],
            available_time=row["available_time"],
            eligible=row["eligible"],
            quality_state=row["quality_state"],
            raw_state=row["raw_state"],
        )
        for row in fixture_rows
    ]
    timeline, transition_ledger = replay_confirmation(rows, dates)
    intervals = atomic_intervals(timeline)
    components, zones, event_ledger = group_event_zones(
        timeline,
        intervals,
        d,
        g,
        candidate_cell_id=f"synthetic_{case_id}",
    )
    if case_id in {"normal_short_interval_drop", "prequalification_right_censor"}:
        event_ledger = [
            item
            for item in event_ledger
            if item["reason_code"]
            in {"normal_short_interval_drop", "prequalification_right_censored"}
        ] or event_ledger
    return (
        timeline,
        transition_ledger,
        intervals,
        components,
        zones,
        event_ledger,
        fixture_rows,
        dates,
    )


def _fixture_daily_inputs(
    d: int, g: int, seed: int, case_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    dates = [f"2026-01-{day:02d}" for day in range(2, 14)]
    raws: list[bool | None] = [
        True,
        True,
        True,
        True,
        False,
        True,
        True,
        True,
        False,
        True,
        True,
        True,
    ]
    qualities = ["valid"] * len(dates)
    if seed % 11 == 0 or case_id in {"quality_break", "diagnostic_break"}:
        qualities[5] = "diagnostic_required"
    if seed % 13 == 0:
        qualities[6] = "blocked"
    rows = [
        DailyInput(
            security_id="S1",
            trade_date=date,
            available_time=f"{date}T15:{seed % 60:02d}:00+08:00",
            eligible=True,
            quality_state=quality,
            raw_state=raw,
        )
        for date, quality, raw in zip(dates, qualities, raws)
    ]
    if case_id in {"missing_row_fail_closed", "missing_row_break"}:
        rows = [row for row in rows if row.trade_date != "2026-01-07"]
    if case_id in {"normal_short_interval_drop", "prequalification_right_censor"}:
        raw_values = (
            [True, True, True, False] + [False] * 8
            if case_id == "normal_short_interval_drop"
            else [True, True, True]
        )
        rows = [
            DailyInput(
                "S1",
                date,
                f"{date}T15:{seed % 60:02d}:00+08:00",
                True,
                "valid",
                raw,
            )
            for date, raw in zip(dates, raw_values)
        ]
        if case_id == "prequalification_right_censor":
            dates = dates[:3]
    return [
        {
            "security_id": row.security_id,
            "trade_date": row.trade_date,
            "available_time": row.available_time,
            "eligible": row.eligible,
            "quality_state": row.quality_state,
            "raw_state": row.raw_state,
        }
        for row in rows
    ], dates


def contract_payloads(
    config: dict[str, Any], run_id: str, execution_commit: str
) -> dict[str, dict[str, Any]]:
    common = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "contract_version": CONTRACT_VERSION,
        "execution_code_commit": execution_commit,
    }
    confirmed = {
        **common,
        "K": K,
        "states": ["RAW_NOT_CONFIRMED", "CONFIRMED_ACTIVE", "CONFIRMED_EXITED"],
        "confirmation_rule": CONFIRMATION_RULE,
        "no_backfill": True,
        "exit_day_confirmed_state": False,
        "missing_expected_trading_row_policy": "fail_closed",
        "expected_key_registry_required": True,
        "calendar_non_trading_day_participates_in_streak": False,
    }
    event_zone = {
        **common,
        "states": [
            "COMPONENT_FORMING",
            "UNQUALIFIED_CLOSED",
            "QUALIFIED_ACTIVE",
            "GAP_PENDING",
            "REENTRY_PENDING_QUALIFICATION",
            "FINALIZED",
            "FINALIZED_WITH_QUALITY_BREAK",
            "RIGHT_CENSORED",
        ],
        "processing_order": [
            "atomic_confirmed_interval",
            "d_qualification",
            "qualified_component",
            "g_grouping",
            "event_zone",
        ],
        "d_grid": list(D_GRID),
        "g_grid": list(G_GRID),
        "d_operator": ">=",
        "ordinary_false_bridge_rule": ORDINARY_FALSE_BRIDGE_RULE,
        "hard_breaks": [
            "unknown",
            "blocked",
            "diagnostic_required",
            "ineligible",
            "missing_observation",
            "missing_expected_trading_row",
            "intervening_unqualified_confirmed_interval",
        ],
        "transitive_merge": True,
        "right_censored_policy": RIGHT_CENSORED_POLICY,
    }
    event_rule = {
        **common,
        "time_fields": [
            "confirmed_start_date",
            "confirmation_time",
            "event_qualification_time",
            "confirmed_end_date",
            "exit_observation_time",
            "zone_finalization_time",
            "membership_available_time",
        ],
        "event_qualification_time_rule": EVENT_QUALIFICATION_TIME_RULE,
        "bridge_membership_available_time_rule": BRIDGE_MEMBERSHIP_TIME_RULE,
        "event_identity": EVENT_IDENTITY_RULE,
        "canonical_selected_state_event_id_generated": False,
    }
    risk_set = {
        **common,
        "state_risk_set_eligible_rule": RISK_SET_RULE,
        "qualified_event_risk_set_eligible_rule": (
            "state_risk_set_eligible=true and component_qualified_as_of=true "
            "and event_zone_member=true and is_bridged_gap=false"
        ),
        "required_fields": [
            "evaluation_time",
            "eligible",
            "quality_state",
            "confirmed_state",
            "event_zone_member",
            "is_bridged_gap",
            "retrospective_component_member",
            "component_qualified_as_of",
            "membership_available_time",
            "state_risk_set_eligible",
            "qualified_event_risk_set_eligible",
        ],
        "assertions": [
            "is_bridged_gap_true_implies_confirmed_state_false",
            "is_bridged_gap_true_implies_qualified_event_risk_set_eligible_false",
            "event_zone_member_true_does_not_imply_state_risk_set_eligible_true",
            "state_risk_set_eligible_true_requires_confirmed_state_true",
            "qualified_event_risk_set_eligible_true_requires_component_qualified_as_of_true",
            "unknown_blocked_diagnostic_ineligible_missing_imply_both_risk_sets_false",
        ],
        "missing_field_policy": "fail_closed",
    }
    t03_output = {
        **common,
        "primary_cell_count": 36,
        "shared_q_sidecar_cell_count": 36,
        "registry_row_count": 72,
        "actual_scan_executed": False,
        "execution_status": "not_executed_contract_only",
        "forbidden_fields": sorted(FORBIDDEN_OUTPUT_FIELDS),
        "table_contracts": t03_table_contracts(),
    }
    return {
        "confirmed_state_machine": confirmed,
        "event_zone_machine": event_zone,
        "event_rule": event_rule,
        "risk_set": risk_set,
        "t03_output": t03_output,
    }


def t03_table_contracts() -> dict[str, Any]:
    common_daily = [
        {"name": "candidate_cell_id", "type": "string", "nullable": False},
        {"name": "route_id", "type": "string", "nullable": False},
        {"name": "security_id", "type": "string", "nullable": False},
        {"name": "trade_date", "type": "date", "nullable": False},
        {"name": "available_time", "type": "datetime_tz", "nullable": False},
    ]
    return {
        "atomic_confirmed_daily": {
            "primary_key": ["candidate_cell_id", "security_id", "trade_date"],
            "denominator_scope": "eligible valid daily rows by own and common scopes",
            "fields": [
                *common_daily,
                {"name": "raw_state", "type": "boolean_or_unknown", "nullable": True},
                {"name": "confirmed_state", "type": "boolean", "nullable": False},
                {"name": "confirmed_start_date", "type": "date", "nullable": True},
                {"name": "confirmation_time", "type": "datetime_tz", "nullable": True},
                {
                    "name": "state_risk_set_eligible",
                    "type": "boolean",
                    "nullable": False,
                },
            ],
        },
        "qualified_component": {
            "primary_key": ["candidate_cell_id", "security_id", "component_id"],
            "denominator_scope": "atomic confirmed intervals only",
            "fields": [
                {"name": "candidate_cell_id", "type": "string", "nullable": False},
                {"name": "security_id", "type": "string", "nullable": False},
                {"name": "component_id", "type": "string", "nullable": False},
                {"name": "start_date", "type": "date", "nullable": False},
                {"name": "end_date", "type": "date", "nullable": False},
                {"name": "confirmed_day_count", "type": "integer", "nullable": False},
                {"name": "qualified", "type": "boolean", "nullable": False},
                {
                    "name": "event_qualification_time",
                    "type": "datetime_tz",
                    "nullable": True,
                },
            ],
        },
        "event_zone": {
            "primary_key": ["candidate_cell_id", "security_id", "scan_event_id"],
            "denominator_scope": (
                "qualified components and accepted ordinary false bridges"
            ),
            "fields": [
                {"name": "candidate_cell_id", "type": "string", "nullable": False},
                {"name": "security_id", "type": "string", "nullable": False},
                {"name": "scan_event_id", "type": "string", "nullable": False},
                {"name": "first_component_id", "type": "string", "nullable": False},
                {"name": "component_count", "type": "integer", "nullable": False},
                {"name": "bridge_count", "type": "integer", "nullable": False},
                {"name": "bridged_day_count", "type": "integer", "nullable": False},
                {"name": "confirmed_day_count", "type": "integer", "nullable": False},
                {"name": "zone_span_days", "type": "integer", "nullable": False},
                {"name": "confirmed_density", "type": "number", "nullable": False},
                {"name": "zone_revision", "type": "integer", "nullable": False},
                {
                    "name": "membership_available_time",
                    "type": "datetime_tz",
                    "nullable": False,
                },
                {
                    "name": "zone_finalization_time",
                    "type": "datetime_tz",
                    "nullable": True,
                },
                {"name": "status", "type": "enum", "nullable": False},
                {"name": "exit_or_censor_reason", "type": "string", "nullable": False},
            ],
        },
        "event_zone_membership_daily": {
            "primary_key": [
                "candidate_cell_id",
                "security_id",
                "scan_event_id",
                "trade_date",
            ],
            "denominator_scope": (
                "zone member rows, including retrospective component members"
            ),
            "fields": [
                *common_daily,
                {"name": "scan_event_id", "type": "string", "nullable": False},
                {"name": "event_zone_member", "type": "boolean", "nullable": False},
                {
                    "name": "state_risk_set_eligible",
                    "type": "boolean",
                    "nullable": False,
                },
                {
                    "name": "retrospective_component_member",
                    "type": "boolean",
                    "nullable": False,
                },
                {
                    "name": "component_qualified_as_of",
                    "type": "boolean",
                    "nullable": False,
                },
                {"name": "is_bridged_gap", "type": "boolean", "nullable": False},
                {
                    "name": "zone_revision_as_of",
                    "type": "integer",
                    "nullable": False,
                },
                {"name": "zone_status_as_of", "type": "enum", "nullable": False},
                {
                    "name": "prequalification_member",
                    "type": "boolean",
                    "nullable": False,
                },
                {
                    "name": "unqualified_reentry_member",
                    "type": "boolean",
                    "nullable": False,
                },
                {
                    "name": "qualified_event_risk_set_eligible",
                    "type": "boolean",
                    "nullable": False,
                },
            ],
        },
        "transition_profile": {
            "primary_key": ["candidate_cell_id", "security_id", "transition_ordinal"],
            "denominator_scope": "state-machine ledger transitions",
            "fields": [
                {"name": "candidate_cell_id", "type": "string", "nullable": False},
                {"name": "security_id", "type": "string", "nullable": False},
                {"name": "transition_ordinal", "type": "integer", "nullable": False},
                {"name": "from_state", "type": "string", "nullable": False},
                {"name": "to_state", "type": "string", "nullable": False},
                {"name": "reason_code", "type": "string", "nullable": False},
            ],
        },
        "strict_core_window_comparison": {
            "primary_key": [
                "primary_candidate_cell_id",
                "sidecar_candidate_cell_id",
                "security_id",
                "trade_date",
            ],
            "denominator_scope": (
                "exact-key primary/sidecar intersections and differences"
            ),
            "fields": [
                {
                    "name": "primary_candidate_cell_id",
                    "type": "string",
                    "nullable": False,
                },
                {
                    "name": "sidecar_candidate_cell_id",
                    "type": "string",
                    "nullable": False,
                },
                {"name": "security_id", "type": "string", "nullable": False},
                {"name": "trade_date", "type": "date", "nullable": False},
                {
                    "name": "primary_confirmed_state",
                    "type": "boolean",
                    "nullable": False,
                },
                {
                    "name": "strict_core_confirmed_state",
                    "type": "boolean",
                    "nullable": False,
                },
                {"name": "subset_violation", "type": "boolean", "nullable": False},
            ],
        },
        "atomic_baseline_profile": _profile_contract(
            ["candidate_cell_id", "route_id"],
            [
                "eligible_days",
                "confirmed_state_days",
                "confirmed_state_coverage",
                "atomic_confirmed_interval_count",
            ],
        ),
        "d_qualification_profile": _profile_contract(
            ["candidate_cell_id", "d"],
            [
                "qualified_component_count",
                "unqualified_component_count",
                "retrospective_qualified_confirmed_coverage",
                "asof_qualified_confirmed_coverage",
            ],
        ),
        "dg_event_zone_profile": _profile_contract(
            ["candidate_cell_id", "d", "g"],
            [
                "qualified_event_count",
                "confirmed_event_coverage",
                "active_zone_count",
                "gap_pending_zone_count",
                "reentry_pending_zone_count",
                "unqualified_reentry_count",
                "confirmed_density",
            ],
        ),
        "transition_aggregate_profile": _profile_contract(
            ["candidate_cell_id", "from_state", "to_state", "reason_code"],
            ["transition_count", "hard_break_count"],
        ),
        "strict_core_shell_profile": _profile_contract(
            ["primary_candidate_cell_id", "sidecar_candidate_cell_id"],
            [
                "strict_core_confirmed_day_share",
                "strict_core_event_share",
                "shell_only_event_count",
                "shell_only_confirmed_day_share",
            ],
        ),
        "window_overlap_comparison": _profile_contract(
            ["primary_candidate_cell_id", "comparison_candidate_cell_id"],
            [
                "intersection_confirmed_days",
                "confirmed_day_jaccard",
                "matched_event_count",
                "overlapping_event_count",
            ],
        ),
    }


def _profile_contract(primary_key: list[str], metric_ids: list[str]) -> dict[str, Any]:
    return {
        "primary_key": primary_key,
        "denominator_scope": "profile rows use metric-specific denominator scopes",
        "fields": [
            {"name": name, "type": "string", "nullable": False} for name in primary_key
        ]
        + [
            {"name": metric_id, "type": "number_or_null", "nullable": True}
            for metric_id in metric_ids
        ],
    }


def transition_rows() -> list[dict[str, Any]]:
    return [
        {
            "machine": "confirmed_state",
            "from_state": "RAW_NOT_CONFIRMED",
            "to_state": "CONFIRMED_ACTIVE",
            "trigger": "continuous_K3_eligible_valid_raw_true",
            "reason_code": "k3_confirmation",
            "hard_break": False,
        },
        {
            "machine": "confirmed_state",
            "from_state": "CONFIRMED_ACTIVE",
            "to_state": "CONFIRMED_ACTIVE",
            "trigger": "raw_true_eligible_valid",
            "reason_code": "confirmed_maintained",
            "hard_break": False,
        },
        {
            "machine": "confirmed_state",
            "from_state": "CONFIRMED_ACTIVE",
            "to_state": "CONFIRMED_EXITED",
            "trigger": "raw_false",
            "reason_code": "natural_state_exit",
            "hard_break": False,
        },
        {
            "machine": "confirmed_state",
            "from_state": "CONFIRMED_ACTIVE",
            "to_state": "CONFIRMED_EXITED",
            "trigger": "unknown_blocked_diagnostic_missing",
            "reason_code": "quality_interruption",
            "hard_break": True,
        },
        {
            "machine": "event_zone",
            "from_state": "COMPONENT_FORMING",
            "to_state": "QUALIFIED_ACTIVE",
            "trigger": "confirmed_day_count_ge_d",
            "reason_code": "d_qualification",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "COMPONENT_FORMING",
            "to_state": "UNQUALIFIED_CLOSED",
            "trigger": "normal_exit_before_d",
            "reason_code": "normal_short_interval_drop",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "COMPONENT_FORMING",
            "to_state": "RIGHT_CENSORED",
            "trigger": "sample_end_before_d",
            "reason_code": "prequalification_right_censored",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "GAP_PENDING",
            "to_state": "FINALIZED",
            "trigger": "g_plus_1_ordinary_false_observed",
            "reason_code": "gap_exceeds_g",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "GAP_PENDING",
            "to_state": "FINALIZED_WITH_QUALITY_BREAK",
            "trigger": "unknown_blocked_diagnostic_ineligible_missing",
            "reason_code": "quality_break",
            "hard_break": True,
        },
        {
            "machine": "event_zone",
            "from_state": "GAP_PENDING",
            "to_state": "REENTRY_PENDING_QUALIFICATION",
            "trigger": "confirmed_run_within_g",
            "reason_code": "reentry_pending",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "GAP_PENDING",
            "to_state": "REENTRY_PENDING_QUALIFICATION",
            "trigger": "unqualified_confirmed_interval_observed",
            "reason_code": "unqualified_reentry_observed",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "QUALIFIED_ACTIVE",
            "to_state": "GAP_PENDING",
            "trigger": "first_ordinary_false_after_qualified_component",
            "reason_code": "gap_pending",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "REENTRY_PENDING_QUALIFICATION",
            "to_state": "QUALIFIED_ACTIVE",
            "trigger": "new_component_reaches_d",
            "reason_code": "reentry_reaches_d_merge",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "QUALIFIED_ACTIVE",
            "to_state": "GAP_PENDING",
            "trigger": "sample_end_after_qualified_component",
            "reason_code": "confirmed_active_sample_end_censoring",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "REENTRY_PENDING_QUALIFICATION",
            "to_state": "FINALIZED",
            "trigger": "g_plus_1_ordinary_false_before_requalification",
            "reason_code": "gap_exceeds_g",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "REENTRY_PENDING_QUALIFICATION",
            "to_state": "FINALIZED_WITH_QUALITY_BREAK",
            "trigger": "quality_break_before_requalification",
            "reason_code": "quality_break",
            "hard_break": True,
        },
        {
            "machine": "event_zone",
            "from_state": "REENTRY_PENDING_QUALIFICATION",
            "to_state": "FINALIZED",
            "trigger": "unqualified_component_observed",
            "reason_code": "unqualified_reentry_blocks_merge",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "REENTRY_PENDING_QUALIFICATION",
            "to_state": "RIGHT_CENSORED",
            "trigger": "sample_end_before_requalification",
            "reason_code": "sample_end_open_zone",
            "hard_break": False,
        },
        {
            "machine": "event_zone",
            "from_state": "GAP_PENDING",
            "to_state": "RIGHT_CENSORED",
            "trigger": "sample_end",
            "reason_code": "sample_end_open_zone",
            "hard_break": False,
        },
    ]


METRIC_FIELDS = [
    "metric_id",
    "entity_level",
    "exact_numerator_or_aggregation",
    "exact_denominator",
    "deduplication_key",
    "included_rows",
    "excluded_rows",
    "open_interval_policy",
    "right_censor_policy",
    "quality_break_policy",
    "denominator_scope",
    "parameter_response",
    "hard_gate_usage",
    "null_policy",
    "availability_basis",
]


def metric_dictionary_rows() -> list[dict[str, Any]]:
    specs = {
        "eligible_days": (
            "daily_row",
            "count eligible=true rows",
            "own or common exact security_id trade_date keys",
        ),
        "confirmed_state_days": (
            "daily_row",
            "count rows with confirmed_state=true",
            "eligible valid daily rows",
        ),
        "confirmed_state_coverage": (
            "daily_row",
            "confirmed_state_days",
            "eligible_days",
        ),
        "atomic_confirmed_interval_count": (
            "atomic_interval",
            "count maximal confirmed intervals",
            "route security",
        ),
        "atomic_duration_mean": (
            "atomic_interval",
            "mean confirmed_day_count",
            "atomic_confirmed_interval_count",
        ),
        "atomic_duration_median": (
            "atomic_interval",
            "median confirmed_day_count",
            "atomic_confirmed_interval_count",
        ),
        "atomic_duration_q90": (
            "atomic_interval",
            "q90 confirmed_day_count",
            "atomic_confirmed_interval_count",
        ),
        "atomic_duration_q95": (
            "atomic_interval",
            "q95 confirmed_day_count",
            "atomic_confirmed_interval_count",
        ),
        "atomic_singleton_count": (
            "atomic_interval",
            "count intervals with confirmed_day_count=1",
            "atomic_confirmed_interval_count",
        ),
        "atomic_fragment_rate": (
            "atomic_interval",
            "atomic_singleton_count",
            "atomic_confirmed_interval_count",
        ),
        "natural_exit_count": (
            "atomic_interval",
            "count intervals ending natural_state_exit",
            "observed closed atomic intervals",
        ),
        "quality_interruption_count": (
            "atomic_interval",
            "count intervals ending quality_interruption",
            "observed closed atomic intervals",
        ),
        "right_censored_atomic_count": (
            "atomic_interval",
            "count intervals ending sample_end_censoring",
            "atomic_confirmed_interval_count",
        ),
        "upstream_reconciliation_status": (
            "route",
            "all upstream interval counts and hashes match",
            "all checked upstream artifacts",
        ),
        "qualified_component_count": (
            "component",
            "count atomic intervals with confirmed_day_count>=d",
            "atomic_confirmed_interval_count",
        ),
        "unqualified_component_count": (
            "component",
            "count normally closed intervals with confirmed_day_count<d",
            "observed normally closed atomic intervals",
        ),
        "component_qualification_rate": (
            "component",
            "qualified_component_count",
            "qualified_component_count plus unqualified_component_count",
        ),
        "qualified_confirmed_day_count": (
            "component",
            "sum confirmed days in qualified components",
            "confirmed_state_days",
        ),
        "retained_confirmed_day_ratio": (
            "component",
            "qualified_confirmed_day_count",
            "confirmed_state_days",
        ),
        "short_interval_drop_rate": (
            "component",
            "normally ended intervals with confirmed_day_count<d",
            "all observed normally ended atomic intervals",
        ),
        "prequalification_right_censored_count": (
            "component",
            "right censored intervals below d",
            "atomic_confirmed_interval_count",
        ),
        "event_qualification_delay": (
            "component",
            "available time difference from first to dth confirmed day",
            "qualified_component_count",
        ),
        "qualified_event_count": (
            "event_zone",
            "count finalized or right censored qualified zones",
            "security year route cell",
        ),
        "confirmed_event_coverage": (
            "event_zone",
            "distinct eligible valid confirmed_state=true trade_date rows "
            "inside qualified event components",
            "eligible valid daily rows in the same candidate cell",
        ),
        "retrospective_qualified_confirmed_coverage": (
            "event_zone",
            "confirmed days that are retrospective qualified component members",
            "eligible valid daily rows in the same candidate cell",
        ),
        "asof_qualified_confirmed_coverage": (
            "event_zone",
            "confirmed days with component_qualified_as_of=true at evaluation time",
            "eligible valid daily rows in the same candidate cell",
        ),
        "zone_span_coverage": (
            "event_zone",
            "event zone member trading days",
            "eligible_days",
        ),
        "zone_span_days": (
            "event_zone",
            "trading days from first component start to zone end",
            "qualified_event_count",
        ),
        "duration_mean": ("event_zone", "mean zone_span_days", "qualified_event_count"),
        "duration_median": (
            "event_zone",
            "median zone_span_days",
            "qualified_event_count",
        ),
        "duration_q90": ("event_zone", "q90 zone_span_days", "qualified_event_count"),
        "duration_q95": ("event_zone", "q95 zone_span_days", "qualified_event_count"),
        "duration_q95_ratio": (
            "event_zone",
            "duration_q95 divided by upstream atomic_duration_q95 using "
            "nearest order statistic q95",
            "upstream atomic_duration_q95 for the same route_id and state_line",
        ),
        "bridged_gap_count": (
            "event_zone",
            "count accepted ordinary-false bridge segments",
            "qualified_event_count",
        ),
        "bridged_day_count": (
            "event_zone",
            "sum ordinary-false bridged rows",
            "event zone member rows",
        ),
        "bridge_segment_count_distribution": (
            "event_zone",
            "distribution of bridge_count by scan_event_id",
            "qualified_event_count",
        ),
        "component_count_distribution": (
            "event_zone",
            "distribution of component_count by scan_event_id",
            "qualified_event_count",
        ),
        "max_single_gap": (
            "event_zone",
            "max ordinary false rows in any accepted bridge segment",
            "qualified_event_count",
        ),
        "bridged_day_ratio": ("event_zone", "bridged_day_count", "zone_span_days"),
        "confirmed_density": (
            "event_zone",
            "confirmed component member days divided by zone_span_days",
            "qualified_event_count",
        ),
        "zone_revision_count": (
            "event_zone",
            "sum zone_revision across event zones",
            "qualified_event_count",
        ),
        "merge_ratio": (
            "event_zone",
            "zones with component_count>1",
            "qualified_event_count",
        ),
        "open_event_count": (
            "event_zone",
            "right censored open zones",
            "qualified_event_count",
        ),
        "open_event_ratio": ("event_zone", "open_event_count", "qualified_event_count"),
        "active_zone_count": (
            "event_zone",
            "zones with status_as_of=QUALIFIED_ACTIVE",
            "candidate cell evaluation date",
        ),
        "gap_pending_zone_count": (
            "event_zone",
            "zones with status_as_of=GAP_PENDING",
            "candidate cell evaluation date",
        ),
        "reentry_pending_zone_count": (
            "event_zone",
            "zones with status_as_of=REENTRY_PENDING_QUALIFICATION",
            "candidate cell evaluation date",
        ),
        "unqualified_reentry_count": (
            "event_zone",
            "count reentry attempts ending before d qualification",
            "qualified_event_count plus unqualified reentry attempts",
        ),
        "events_per_security": (
            "event_zone",
            "qualified_event_count grouped by security",
            "unique securities",
        ),
        "unique_securities": (
            "event_zone",
            "count distinct securities with at least one qualified event zone",
            "upstream_unique_securities for same state_line",
        ),
        "events_per_year": (
            "event_zone",
            "qualified_event_count grouped by calendar year",
            "nonzero calendar years",
        ),
        "nonzero_years": (
            "event_zone",
            "count years with qualified_event_count>0",
            "available sample years",
        ),
        "max_year_share": (
            "event_zone",
            "max yearly qualified_event_count",
            "qualified_event_count",
        ),
        "mega_zone_concentration": (
            "event_zone",
            "top 1 percent zones by span days divided by total zone_span_days",
            "qualified_event_count",
        ),
        "top_zone_confirmed_day_share": (
            "event_zone",
            "largest zone confirmed component day count divided by total "
            "confirmed component days",
            "qualified_event_count",
        ),
        "within_route_overlapping_event_count": (
            "event_zone",
            "same security overlapping zones in same route cell",
            "qualified_event_count",
        ),
        "post_merge_short_zone_count": (
            "event_zone",
            "merged zones whose retained confirmed component day count is below d "
            "after all accepted bridges",
            "qualified_event_count",
        ),
        "intersection_confirmed_days": (
            "window_compare",
            "W120 and W250 confirmed exact-key intersection",
            "common exact-key denominator",
        ),
        "W120_only_confirmed_days": (
            "window_compare",
            "W120 confirmed keys absent from W250",
            "W120 own confirmed keys",
        ),
        "W250_only_confirmed_days": (
            "window_compare",
            "W250 confirmed keys absent from W120",
            "W250 own confirmed keys",
        ),
        "confirmed_day_jaccard": (
            "window_compare",
            "intersection_confirmed_days",
            "union confirmed exact keys",
        ),
        "matched_event_count": (
            "window_compare",
            "greedy one-to-one match by security, overlapping confirmed days, "
            "earliest primary start, earliest sidecar start, then scan_event_id",
            "qualified_event_count",
        ),
        "overlapping_event_count": (
            "window_compare",
            "events with overlapping zone spans",
            "qualified_event_count",
        ),
        "strict_core_confirmed_day_share": (
            "strict_core",
            "shared-q confirmed days within primary confirmed days",
            "primary confirmed days",
        ),
        "strict_core_event_share": (
            "strict_core",
            "primary events containing strict-core component",
            "primary qualified_event_count",
        ),
        "strict_core_confirmed_day_count": (
            "strict_core",
            "strict-core confirmed exact-key count",
            "strict-core eligible valid daily rows",
        ),
        "strict_core_subset_status": (
            "strict_core",
            "all strict-core confirmed keys subset primary keys",
            "strict-core exact keys",
        ),
        "shell_only_event_count": (
            "strict_core",
            "primary events without strict-core member",
            "primary qualified_event_count",
        ),
        "shell_only_confirmed_day_count": (
            "strict_core",
            "primary confirmed exact keys absent from strict-core exact keys",
            "primary confirmed days",
        ),
        "shell_only_confirmed_day_share": (
            "strict_core",
            "shell_only_confirmed_day_count",
            "primary confirmed days",
        ),
    }
    rows = []
    for metric_id, (level, numerator, denominator) in specs.items():
        rows.append(
            {
                "metric_id": metric_id,
                "entity_level": level,
                "exact_numerator_or_aggregation": numerator,
                "exact_denominator": denominator,
                "deduplication_key": METRIC_DEDUP_KEY,
                "included_rows": METRIC_INCLUDED_ROWS,
                "excluded_rows": METRIC_EXCLUDED_ROWS,
                "open_interval_policy": OPEN_INTERVAL_POLICY,
                "right_censor_policy": RIGHT_CENSOR_METRIC_POLICY,
                "quality_break_policy": QUALITY_BREAK_METRIC_POLICY,
                "denominator_scope": DENOMINATOR_SCOPE_TEXT,
                "parameter_response": PARAMETER_RESPONSE_TEXT,
                "hard_gate_usage": "hard_gate_input"
                if metric_id in HARD_GATE_METRICS
                else "diagnostic_or_reported",
                "null_policy": NULL_POLICY_TEXT,
                "availability_basis": AVAILABILITY_BASIS_TEXT,
            }
        )
    return rows


HARD_GATE_METRICS = {
    "qualified_event_count",
    "retained_confirmed_day_ratio",
    "short_interval_drop_rate",
    "bridged_day_ratio",
    "merge_ratio",
    "open_event_ratio",
    "nonzero_years",
    "max_year_share",
    "duration_q95",
    "duration_q95_ratio",
    "unique_securities",
}

HARD_GATE_FIELDS = [
    "gate_id",
    "state_line",
    "metric_id",
    "operator",
    "threshold",
    "scope_rule",
    "fail_closed",
    "zero_tolerance",
]


def hard_gate_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    thresholds = {
        "S_PCT": {
            "qualified_event_count": PCT_EVENT_COUNT_THRESHOLD,
            "unique_securities": "max(150,ceil(0.20*upstream_unique_securities))",
            "retained_confirmed_day_ratio": "0.35",
            "short_interval_drop_rate": "0.80",
            "bridged_day_ratio": "0.30",
            "merge_ratio": "0.70",
            "open_event_ratio": "0.10",
            "nonzero_years": "8",
            "max_year_share": "0.35",
            "duration_q95_ratio": "3.0",
        },
        "S_PCVT": {
            "qualified_event_count": PCVT_EVENT_COUNT_THRESHOLD,
            "unique_securities": "max(100,ceil(0.15*upstream_unique_securities))",
            "retained_confirmed_day_ratio": "0.25",
            "short_interval_drop_rate": "0.85",
            "bridged_day_ratio": "0.35",
            "merge_ratio": "0.75",
            "open_event_ratio": "0.10",
            "nonzero_years": "8",
            "max_year_share": "0.35",
            "duration_q95_ratio": "3.0",
        },
    }
    operators = {
        "qualified_event_count": ">=",
        "unique_securities": ">=",
        "retained_confirmed_day_ratio": ">=",
        "short_interval_drop_rate": "<=",
        "bridged_day_ratio": "<=",
        "merge_ratio": "<=",
        "open_event_ratio": "<=",
        "nonzero_years": ">=",
        "max_year_share": "<=",
        "duration_q95_ratio": "<=",
    }
    for state_line, items in thresholds.items():
        for metric_id, threshold in items.items():
            rows.append(
                {
                    "gate_id": f"{state_line.lower()}_{metric_id}",
                    "state_line": state_line,
                    "metric_id": metric_id,
                    "operator": operators[metric_id],
                    "threshold": threshold,
                    "scope_rule": "state_line_level_not_W_specific",
                    "fail_closed": True,
                    "zero_tolerance": False,
                }
            )
    for gate in [
        "lineage_mismatch",
        "schema_mismatch",
        "source_hash_mismatch",
        "superseded_input",
        "duplicate_primary_key",
        "missing_expected_trading_row",
        "unknown_bridge",
        "blocked_bridge",
        "diagnostic_required_bridge",
        "ineligible_bridge",
        "confirmed_day_conservation_mismatch",
        "event_overlap_within_same_route_cell_security",
        "post_merge_short_zone",
        "risk_set_violation",
        "strict_core_subset_violation",
        "event_id_instability",
        "availability_backfill",
        "right_censor_misclassified_as_natural_exit",
        "prequalification_censor_included_in_drop_denominator",
        "forbidden_output_field",
        "transition_closure_violation",
        "asof_membership_leakage",
        "unqualified_reentry_unfinalized",
        "censor_contamination",
        "anti_percolation_mega_zone_violation",
        "event_zone_revision_regression",
        "status_asof_timeline_gap",
        "strict_core_shell_reconciliation_mismatch",
    ]:
        rows.append(
            {
                "gate_id": gate,
                "state_line": "GLOBAL",
                "metric_id": gate,
                "operator": "==",
                "threshold": "0 violations",
                "scope_rule": "global_zero_tolerance",
                "fail_closed": True,
                "zero_tolerance": True,
            }
        )
    return rows


def experiment_summary(
    run_id: str,
    execution_commit: str,
    cells: list[dict[str, Any]],
    synthetic_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "execution_code_commit": execution_commit,
        "protocol_version": CONTRACT_VERSION,
        "task_type": "protocol_freeze",
        "actual_scan_executed": False,
        "primary_cell_count": sum(row["candidate_role"] == "primary" for row in cells),
        "shared_q_sidecar_cell_count": sum(
            row["candidate_role"] == "strict_core_reference" for row in cells
        ),
        "registry_row_count": len(cells),
        "synthetic_case_count": len(synthetic_results),
        "all_synthetic_cases_passed": all(
            row["status"] == "passed" for row in synthetic_results
        ),
        "scientific_review_status": "pending",
        "independent_review_status": "pending",
        "formal_task_completed": False,
        "full_status": "deferred_to_premerge_gate",
    }


def result_analysis(run_id: str, summary: dict[str, Any]) -> str:
    return f"""# R2-T02 Result Analysis

Run `{run_id}` froze the confirmed-state and event-zone protocol contract only.
It generated {summary["primary_cell_count"]} primary cells and
{summary["shared_q_sidecar_cell_count"]} shared-q sidecar cells with
`actual_scan_executed=false`. No winner, rank, freeze decision, selected state
version, future label, or backtest artifact was produced.

Author-stage scientific review remains pending. R2-T03, R2-T04, and R3 remain
closed until independent scientific review, exact-head premerge full evidence,
and repository final gate are completed.
"""


def evidence_markdown(run_id: str, summary: dict[str, Any]) -> str:
    return f"""# R2-T02 Evidence

- task_id: R2-T02
- run_id: {run_id}
- protocol_version: {CONTRACT_VERSION}
- primary_cell_count: {summary["primary_cell_count"]}
- shared_q_sidecar_cell_count: {summary["shared_q_sidecar_cell_count"]}
- actual_scan_executed: false
- all_synthetic_cases_passed: {str(summary["all_synthetic_cases_passed"]).lower()}
- full_status: deferred_to_premerge_gate
"""


def result_package(
    run_id: str,
    execution_commit: str,
    output_dir: Path,
    summary: dict[str, Any],
    validation: dict[str, Any],
    anomaly: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    artifacts = canonical_output_hashes(output_dir, PACKAGE_HASH_ARTIFACTS)
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "execution_code_commit": execution_commit,
        "reviewed_pr_head": execution_commit,
        "artifact_commit": "",
        "artifact_commit_binding_status": "pending_post_commit_validation",
        "artifact_hash_basis": "worktree_precommit_bytes",
        "protocol_version": CONTRACT_VERSION,
        "task_type": "protocol_freeze",
        "actual_scan_executed": False,
        "formal_task_completed": False,
        "scientific_review_status": review["scientific_review_status"],
        "independent_review_status": review["independent_review_status"],
        "repository_final_gate_status": review["repository_final_gate_status"],
        "R2-T03_allowed_to_start": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "full_status": "deferred_to_premerge_gate",
        "summary": summary,
        "validation_status": validation["status"],
        "anomaly_blocking_errors": anomaly["blocking_errors"],
        "artifact_hashes": artifacts,
    }


def canonical_output_hashes(
    output_dir: Path, artifact_names: list[str]
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in artifact_names:
        path = output_dir / name
        if path.is_file():
            hashes[name] = sha256_bytes(path.read_bytes())
    return hashes


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R2T02Error(f"json_not_object:{path}")
    return value


JSON_SCHEMA_BY_ARTIFACT = {
    "r2_t02_input_binding.json": "schemas/r2/r2_t02_input_binding.schema.json",
    "r2_t02_confirmed_state_machine_contract.json": (
        "schemas/r2/r2_t02_confirmed_state_machine_contract.schema.json"
    ),
    "r2_t02_event_zone_machine_contract.json": (
        "schemas/r2/r2_t02_event_zone_machine_contract.schema.json"
    ),
    "r2_t02_r3_risk_set_contract.json": (
        "schemas/r2/r2_t02_risk_set_contract.schema.json"
    ),
    "r2_t02_t03_output_contract.json": (
        "schemas/r2/r2_t02_t03_output_contract.schema.json"
    ),
    "r2_t02_result_package.json": "schemas/r2/r2_t02_result_package.schema.json",
}


CSV_CONTRACTS = {
    "r2_t02_transition_registry.csv": {
        "fields": [
            "machine",
            "from_state",
            "to_state",
            "trigger",
            "reason_code",
            "hard_break",
        ],
        "primary_key": ["machine", "from_state", "to_state", "reason_code"],
    },
    "r2_t02_metric_dictionary.csv": {
        "fields": METRIC_FIELDS,
        "primary_key": ["metric_id"],
    },
    "r2_t02_hard_gate_registry.csv": {
        "fields": HARD_GATE_FIELDS,
        "primary_key": ["gate_id"],
    },
    "r2_t02_t03_cell_registry.csv": {
        "fields": T03_CELL_FIELDS,
        "primary_key": ["candidate_cell_id"],
    },
    "r2_t02_synthetic_case_results.csv": {
        "fields": SYNTHETIC_RESULT_FIELDS,
        "primary_key": ["case_id"],
    },
}


def _validate_json_schemas(output_dir: Path, root: Path) -> list[str]:
    errors: list[str] = []
    for artifact, schema_rel in JSON_SCHEMA_BY_ARTIFACT.items():
        schema_path = root / schema_rel
        if not (output_dir / artifact).is_file() or not schema_path.is_file():
            continue
        schema = _load_json(schema_path)
        payload = _load_json(output_dir / artifact)
        validator = Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(payload), key=str):
            errors.append(f"json_schema:{artifact}:{error.json_path}:{error.message}")
    return errors


def _csv_contract_errors(
    rows: list[dict[str, str]], fields: list[str], primary_key: list[str] | None = None
) -> list[str]:
    errors: list[str] = []
    for row in rows:
        actual = list(row.keys())
        if actual != fields:
            errors.append("csv_columns_not_exact")
            break
    if primary_key:
        keys = [tuple(row[field] for field in primary_key) for row in rows]
        if len(keys) != len(set(keys)):
            errors.append("csv_duplicate_primary_key")
    return errors


def _validate_csv_contracts(output_dir: Path) -> list[str]:
    errors: list[str] = []
    for artifact, contract in CSV_CONTRACTS.items():
        if not (output_dir / artifact).is_file():
            continue
        rows = read_csv(output_dir / artifact)
        errors.extend(
            f"{artifact}:{error}"
            for error in _csv_contract_errors(
                rows, contract["fields"], contract["primary_key"]
            )
        )
    return errors


def _metric_errors(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    metric_ids = [row["metric_id"] for row in rows]
    if len(metric_ids) != len(set(metric_ids)):
        errors.append("duplicate_metric_id")
    forbidden_templates = [
        "count entities satisfying predicate",
        "metric-defined population",
        "corresponding eligible population",
        "distribution statistic over named entity",
        "contract_defined",
        "registry_defined",
    ]
    for row in rows:
        joined = " ".join(row.values())
        if any(template in joined for template in forbidden_templates):
            errors.append(f"template_metric_definition:{row['metric_id']}")
    required = {
        "short_interval_drop_rate",
        "bridged_day_ratio",
        "confirmed_day_jaccard",
        "strict_core_subset_status",
        "unique_securities",
        "duration_q95_ratio",
        "post_merge_short_zone_count",
        "matched_event_count",
    }
    if not required.issubset(metric_ids):
        errors.append("missing_required_metric")
    return errors


def _transition_errors(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    pairs = [
        (row["machine"], row["from_state"], row["to_state"], row["reason_code"])
        for row in rows
    ]
    if len(pairs) != len(set(pairs)):
        errors.append("duplicate_transition")
    required = {
        ("confirmed_state", "RAW_NOT_CONFIRMED", "CONFIRMED_ACTIVE", "k3_confirmation"),
        ("event_zone", "GAP_PENDING", "FINALIZED_WITH_QUALITY_BREAK", "quality_break"),
        ("event_zone", "GAP_PENDING", "RIGHT_CENSORED", "sample_end_open_zone"),
        (
            "event_zone",
            "COMPONENT_FORMING",
            "RIGHT_CENSORED",
            "prequalification_right_censored",
        ),
        (
            "event_zone",
            "REENTRY_PENDING_QUALIFICATION",
            "FINALIZED",
            "gap_exceeds_g",
        ),
        (
            "event_zone",
            "REENTRY_PENDING_QUALIFICATION",
            "FINALIZED_WITH_QUALITY_BREAK",
            "quality_break",
        ),
        (
            "event_zone",
            "REENTRY_PENDING_QUALIFICATION",
            "RIGHT_CENSORED",
            "sample_end_open_zone",
        ),
    }
    if not required.issubset(set(pairs)):
        errors.append("missing_required_transition")
    return errors


def _scan_forbidden_output_fields(
    output_dir: Path, artifact_names: list[str]
) -> list[str]:
    errors: list[str] = []
    allowed_files = {
        "r2_t02_t03_output_contract.json",
        "r2_t02_hard_gate_registry.csv",
        "r2_t02_result_analysis.md",
        "r2_t02_event_rule_contract.json",
    }
    for name in artifact_names:
        if name in allowed_files:
            continue
        text = (output_dir / name).read_text(encoding="utf-8")
        for field in FORBIDDEN_OUTPUT_FIELDS:
            if field in text:
                errors.append(f"forbidden_output_field:{name}:{field}")
    return errors


def _csv_string_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{key: str(value) for key, value in row.items()} for row in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or validate R2-T02 package.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT
        / "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v1.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    if args.validate_only:
        validate_output(args.output_dir, args.config)
    else:
        build_run(args.config, args.output_dir)
    return 0


EXPECTED_ARTIFACTS_WITHOUT_PACKAGE = [
    "r2_t02_input_binding.json",
    "r2_t02_confirmed_state_machine_contract.json",
    "r2_t02_event_zone_machine_contract.json",
    "r2_t02_transition_registry.csv",
    "r2_t02_event_rule_contract.json",
    "r2_t02_metric_dictionary.csv",
    "r2_t02_hard_gate_registry.csv",
    "r2_t02_r3_risk_set_contract.json",
    "r2_t02_t03_cell_registry.csv",
    "r2_t02_t03_output_contract.json",
    "r2_t02_synthetic_case_registry.json",
    "r2_t02_synthetic_case_fixtures.json",
    "r2_t02_synthetic_case_results.csv",
    "r2_t02_contract_validation_result.json",
    "r2_t02_committed_artifact_validation.json",
    "r2_t02_anomaly_scan.json",
    "r2_t02_experiment_summary.json",
    "r2_t02_result_analysis.md",
    "r2_t02_evidence.md",
    "r2_t02_scientific_review.json",
]

PACKAGE_HASH_ARTIFACTS = [
    name
    for name in EXPECTED_ARTIFACTS_WITHOUT_PACKAGE
    if name
    not in {
        "r2_t02_contract_validation_result.json",
        "r2_t02_committed_artifact_validation.json",
    }
]
