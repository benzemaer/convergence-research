# ruff: noqa: E501

"""Independent validator for the R2-T07 registry and freeze package.

The validator contains its own frozen expectations and does not import the
T07 generator.  It checks registry semantics, upstream fingerprints, gate
boundaries, and the output manifest's file hashes.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from src.common.canonical_io import write_json, write_markdown

TASK_ID = "R2-T07"
CONTRACT_VERSION = "r2_t02_confirmed_event_zone_state_machine_contract.v8"
EXPECTED_T06 = {
    "merge_commit": "12cd31d125e31762e62f8b1db5a808d189c7c732",
    "reviewed_head": "4604117678b53b2c756d866babd9a4ad8d85a2ef",
    "scientific_review_id": "4690087611",
    "compatibility_review_id": "4690138251",
    "authoritative_run": "R2-T06-20260713T183455Z",
    "execution_commit": "b2b1b193ded0040c9695bca1ad98d22c10263044",
    "validator_commit": "8920a3cd3abfcc15ecd337ef6116d7fe286d5c01",
    "artifact_commit": "07f4771ea78038d230e1dba62c2494614b4553aa",
    "duckdb_sha256": "671b1a1027c1e56af0a551142fc35e31a399d699d732fc145d36c189973ccea1",
}
EXPECTED_T04 = {
    "decision_hash": "f1344346662225f1f0837bc160be1bf6f88f12174cbacc8f27f8a126ad9bf3bf",
    "freeze_decision_hash": "ceb99c3480aa49a13a545dd06d43a85c2faf378256c49623b17d1b0255e0048d",
    "freeze_plan_hash": "1ea368d67b9445a6916ee31ff33e6f0a5f94ed43b0fd5a2b716f8d60c39a80dc",
}
EXPECTED_T05 = {
    "run_id": "R2-T05-20260713T154957Z",
    "database_sha256": "4488f0cca26f703890dfea8701ed761e7de124467a6d373f2e0264dbd0215129",
    "daily_sha256": "64c396322b0e358a5c5440eebe90483d65f18a2cc6461a9a28f2cb72711da4ec",
    "event_sha256": "4c0fcec9012fa46a7b68d3dd436e9e14881c44719f90def22490b8b6bc118acb",
    "membership_sha256": "5664a11fc7f4c61f3b6e8d4b0a465ed0d5c89447a38fc29cd12e966ab6340d0a",
    "daily_row_count": 3502132,
    "event_row_count": 5647,
    "membership_row_count": 27388,
}
EXPECTED_VERSIONS = [
    {
        "state_version_id": "r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8",
        "state_line": "S_PCT",
        "window_track_id": "W120",
        "W": "120",
        "K": "3",
        "qP": "0.2",
        "qC": "0.2",
        "qT": "0.25",
        "qV": "0.2",
        "d": "2",
        "g": "1",
        "source_candidate_cell_id": "r2_s_pct_w120_qt25_primary__d2__g1",
        "strict_core_source_candidate_cell_id": "r2_s_pct_w120_q20_shared__d2__g1",
        "strict_core_enabled": "True",
    },
    {
        "state_version_id": "r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8",
        "state_line": "S_PCVT",
        "window_track_id": "W120",
        "W": "120",
        "K": "3",
        "qP": "0.2",
        "qC": "0.2",
        "qT": "0.2",
        "qV": "0.3",
        "d": "2",
        "g": "1",
        "source_candidate_cell_id": "r2_s_pcvt_w120_qv30_primary__d2__g1",
        "strict_core_source_candidate_id": "r2_s_pcvt_w120_q20_shared__d2__g1",
        "strict_core_source_candidate_cell_id": "r2_s_pcvt_w120_q20_shared__d2__g1",
        "strict_core_enabled": "True",
    },
]
EXPECTED_TRANSITIONS = [
    {
        "machine": "confirmed_state",
        "from_state": "RAW_NOT_CONFIRMED",
        "to_state": "CONFIRMED_ACTIVE",
        "trigger": "continuous_K3_eligible_valid_raw_true",
        "reason_code": "k3_confirmation",
        "hard_break": "False",
    },
    {
        "machine": "confirmed_state",
        "from_state": "CONFIRMED_ACTIVE",
        "to_state": "CONFIRMED_ACTIVE",
        "trigger": "raw_true_eligible_valid",
        "reason_code": "confirmed_maintained",
        "hard_break": "False",
    },
    {
        "machine": "confirmed_state",
        "from_state": "CONFIRMED_ACTIVE",
        "to_state": "CONFIRMED_EXITED",
        "trigger": "raw_false",
        "reason_code": "natural_state_exit",
        "hard_break": "False",
    },
    {
        "machine": "confirmed_state",
        "from_state": "CONFIRMED_ACTIVE",
        "to_state": "CONFIRMED_EXITED",
        "trigger": "unknown_blocked_diagnostic_missing",
        "reason_code": "quality_interruption",
        "hard_break": "True",
    },
    {
        "machine": "event_zone",
        "from_state": "COMPONENT_FORMING",
        "to_state": "QUALIFIED_ACTIVE",
        "trigger": "confirmed_day_count_ge_d",
        "reason_code": "d_qualification",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "COMPONENT_FORMING",
        "to_state": "UNQUALIFIED_CLOSED",
        "trigger": "normal_exit_before_d",
        "reason_code": "normal_short_interval_drop",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "COMPONENT_FORMING",
        "to_state": "RIGHT_CENSORED",
        "trigger": "sample_end_before_d",
        "reason_code": "prequalification_right_censored",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "GAP_PENDING",
        "to_state": "FINALIZED",
        "trigger": "g_plus_1_raw_false_gap_day_observed",
        "reason_code": "raw_false_gap_exceeds_g",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "GAP_PENDING",
        "to_state": "FINALIZED_WITH_QUALITY_BREAK",
        "trigger": "unknown_blocked_diagnostic_ineligible_missing",
        "reason_code": "quality_break",
        "hard_break": "True",
    },
    {
        "machine": "event_zone",
        "from_state": "GAP_PENDING",
        "to_state": "REENTRY_PENDING_QUALIFICATION",
        "trigger": "confirmed_run_within_g",
        "reason_code": "reentry_pending",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "GAP_PENDING",
        "to_state": "REENTRY_PENDING_QUALIFICATION",
        "trigger": "unqualified_confirmed_interval_observed",
        "reason_code": "unqualified_reentry_observed",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "QUALIFIED_ACTIVE",
        "to_state": "GAP_PENDING",
        "trigger": "first_raw_false_or_preconfirmation_after_qualified_component",
        "reason_code": "gap_pending",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "REENTRY_PENDING_QUALIFICATION",
        "to_state": "QUALIFIED_ACTIVE",
        "trigger": "new_component_reaches_d",
        "reason_code": "reentry_reaches_d_merge",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "QUALIFIED_ACTIVE",
        "to_state": "GAP_PENDING",
        "trigger": "sample_end_after_qualified_component",
        "reason_code": "confirmed_active_sample_end_censoring",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "REENTRY_PENDING_QUALIFICATION",
        "to_state": "FINALIZED",
        "trigger": "g_plus_1_raw_false_gap_day_before_requalification",
        "reason_code": "raw_false_gap_exceeds_g",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "REENTRY_PENDING_QUALIFICATION",
        "to_state": "FINALIZED_WITH_QUALITY_BREAK",
        "trigger": "quality_break_before_requalification",
        "reason_code": "quality_break",
        "hard_break": "True",
    },
    {
        "machine": "event_zone",
        "from_state": "REENTRY_PENDING_QUALIFICATION",
        "to_state": "FINALIZED",
        "trigger": "unqualified_component_observed",
        "reason_code": "unqualified_reentry_blocks_merge",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "REENTRY_PENDING_QUALIFICATION",
        "to_state": "RIGHT_CENSORED",
        "trigger": "sample_end_before_requalification",
        "reason_code": "sample_end_before_requalification",
        "hard_break": "False",
    },
    {
        "machine": "event_zone",
        "from_state": "GAP_PENDING",
        "to_state": "RIGHT_CENSORED",
        "trigger": "sample_end",
        "reason_code": "sample_end_open_zone",
        "hard_break": "False",
    },
]
EXPECTED_WARNINGS = {
    "S_PCT×W120": {
        "affected_lift_deterioration_vs_baseline",
        "layer_q_complexity_added",
        "same_sample_formal_revalidation_only",
        "selection_path_not_independently_confirmed",
    },
    "S_PCVT×W120": {
        "V_security_negative_delta_share_material",
        "V_selectivity_reduced_but_guard_passed",
        "layer_q_complexity_added",
        "same_sample_formal_revalidation_only",
        "selection_path_not_independently_confirmed",
    },
}
EXPECTED_STATES = [
    "COMPONENT_FORMING",
    "UNQUALIFIED_CLOSED",
    "QUALIFIED_ACTIVE",
    "GAP_PENDING",
    "REENTRY_PENDING_QUALIFICATION",
    "FINALIZED",
    "FINALIZED_WITH_QUALITY_BREAK",
    "RIGHT_CENSORED",
]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _error(errors: list[str], condition: bool, code: str) -> None:
    if not condition:
        errors.append(code)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _as_transition_rows(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: str(row.get(key))
            for key in (
                "machine",
                "from_state",
                "to_state",
                "trigger",
                "reason_code",
                "hard_break",
            )
        }
        for row in value
    ]


def validate_documents(docs: dict[str, Any]) -> list[str]:
    """Validate parsed documents and return fail-closed error codes."""

    errors: list[str] = []
    state_rows = docs.get("state_registry", [])
    manifest = docs.get("final_manifest", {})
    version_count = manifest.get("frozen_version_count")
    if version_count == 0:
        _error(errors, state_rows == [], "zero_version_registry_not_empty")
        _error(
            errors,
            manifest.get("status") == "completed_no_frozen_version",
            "zero_version_status",
        )
        _error(
            errors,
            manifest.get("downstream_gates", {}).get("R2-T08_allowed_to_start")
            is False,
            "zero_version_t08_gate",
        )
        _error(
            errors,
            manifest.get("downstream_gates", {}).get("R3_allowed_to_start") is False,
            "zero_version_r3_gate",
        )
        return errors

    _error(errors, len(state_rows) == 2, "version_cardinality")
    for index, expected in enumerate(EXPECTED_VERSIONS):
        if index >= len(state_rows):
            errors.append(f"missing_version:{expected['state_version_id']}")
            continue
        row = state_rows[index]
        for key, expected_value in expected.items():
            if key == "strict_core_source_candidate_id":
                continue
            _error(errors, row.get(key) == expected_value, f"{key}_mismatch:{index}")
    ids = [row.get("state_version_id") for row in state_rows]
    _error(errors, len(ids) == len(set(ids)), "duplicate_state_version_id")
    _error(
        errors,
        not any("W250" in value or "w250" in value for value in ids if value),
        "W250_independent_version",
    )
    _error(
        errors,
        not any("parent" in value.lower() for value in ids if value),
        "PCT_parent_product",
    )
    _error(
        errors,
        not any(
            "shared" in value.lower() and "strict" not in value.lower()
            for value in ids
            if value
        ),
        "shared_q_independent_version",
    )

    interval = docs.get("interval_registry", {})
    rules = interval.get("rules", {})
    _error(
        errors,
        interval.get("contract_version") == CONTRACT_VERSION,
        "interval_contract_version",
    )
    _error(errors, rules.get("K") == 3, "K_mismatch")
    _error(
        errors,
        rules.get("d")
        == "selected d=2 confirmed trading days; qualification occurs on the second confirmed day",
        "d_mismatch",
    )
    _error(
        errors,
        rules.get("g")
        == "selected g=1 cumulative eligible valid raw-false gap days after a qualified component",
        "g_mismatch",
    )
    _error(
        errors,
        "third consecutive" in rules.get("confirmation", "")
        and "no backfill" in rules.get("confirmation", ""),
        "confirmation_rule_mismatch",
    )
    _error(
        errors,
        "g+1" in rules.get("raw_false_gap", "")
        and "irreversible" in rules.get("raw_false_gap", ""),
        "gap_rule_mismatch",
    )
    _error(
        errors,
        rules.get("preconfirmation_raw_true", "").startswith("does not increment"),
        "preconfirmation_rule_mismatch",
    )
    _error(
        errors,
        rules.get("unqualified_reentry", "").startswith("an unqualified confirmed"),
        "unqualified_reentry_rule_mismatch",
    )
    _error(
        errors,
        rules.get("release_claim_allowed") is False,
        "confirmed_exit_release_claim",
    )

    event = docs.get("event_registry", {})
    _error(errors, event.get("states") == EXPECTED_STATES, "state_machine_states")
    _error(
        errors,
        _as_transition_rows(event.get("transitions", [])) == EXPECTED_TRANSITIONS,
        "transition_registry_mismatch",
    )
    identity = event.get("event_identity_policy", {})
    _error(
        errors,
        identity.get("canonical_selected_state_event_id_generated") is False,
        "event_id_generation_policy",
    )
    _error(
        errors,
        identity.get("cross_state_line_identity_must_remain_distinct") is True,
        "cross_state_identity_policy",
    )
    time_semantics = event.get("time_semantics", {})
    _error(
        errors,
        "r2_t06_replayed_transition_ledger.trigger_trade_date"
        in time_semantics.get("non_authoritative", []),
        "trigger_trade_date_authority",
    )
    _error(
        errors,
        "confirmation_time" in time_semantics.get("authoritative", []),
        "authoritative_time_fields",
    )
    _error(
        errors,
        time_semantics.get("non_authoritative_fallback", "").startswith(
            "event start date only"
        ),
        "trigger_trade_date_fallback",
    )
    risk_policy = event.get("risk_set_policy", {})
    _error(
        errors,
        risk_policy.get("qualified_event_risk_set_eligible_rule")
        == "state_risk_set_eligible=true and component_qualified_as_of=true and event_zone_member=true and is_raw_false_bridge=false and is_preconfirmation_gap=false",
        "event_zone_as_risk_set",
    )

    decision = docs.get("decision_log", {})
    _error(
        errors,
        decision.get("decision_hash") == EXPECTED_T04["decision_hash"],
        "decision_hash_mismatch",
    )
    _error(
        errors,
        decision.get("freeze_decision_hash") == EXPECTED_T04["freeze_decision_hash"],
        "freeze_decision_hash_mismatch",
    )
    _error(
        errors,
        decision.get("freeze_plan_hash") == EXPECTED_T04["freeze_plan_hash"],
        "freeze_plan_hash_mismatch",
    )
    _error(
        errors,
        decision.get("automatic_recommendation_authoritative") is False,
        "automatic_recommendation_authority",
    )
    _error(
        errors,
        decision.get("selection_path")
        == "explicit_user_decision_not_automatic_recommendation",
        "selection_path_authority",
    )
    units = decision.get("decision_units", [])
    _error(errors, len(units) == 4, "decision_unit_cardinality")
    expected_units = {
        "S_PCT×W120": ("selected", True),
        "S_PCT×W250": ("reject_pair", False),
        "S_PCVT×W120": ("selected", True),
        "S_PCVT×W250": ("reject_pair", False),
    }
    for unit in units:
        name = unit.get("decision_unit")
        if name not in expected_units:
            errors.append(f"unknown_decision_unit:{name}")
            continue
        disposition, strict = expected_units[name]
        _error(
            errors,
            unit.get("pair_disposition") == disposition,
            f"decision_disposition:{name}",
        )
        _error(
            errors,
            unit.get("strict_core_enabled") is strict,
            f"decision_strict_core:{name}",
        )
        if name in EXPECTED_WARNINGS:
            _error(
                errors,
                set(unit.get("accepted_warnings", [])) == EXPECTED_WARNINGS[name],
                f"accepted_warnings:{name}",
            )
    _error(
        errors, decision.get("selected_version_count") == 2, "selected_version_count"
    )
    _error(
        errors, decision.get("strict_core_only_count") == 2, "strict_core_only_count"
    )
    _error(
        errors,
        decision.get("rejected_decision_unit_count") == 2,
        "rejected_decision_unit_count",
    )

    final = docs.get("final_manifest", {})
    _error(errors, final.get("task_id") == TASK_ID, "final_manifest_task_id")
    _error(errors, final.get("registry_freeze_only") is True, "registry_only_policy")
    _error(errors, final.get("replay_performed") is False, "replay_performed")
    _error(
        errors, final.get("frozen_version_count") == 2, "final_manifest_version_count"
    )
    _error(errors, final.get("status") == "completed", "final_manifest_status")
    _error(
        errors,
        final.get("downstream_gates", {}).get("R2-T08_allowed_to_start") is False,
        "R2-T08_gate",
    )
    _error(
        errors,
        final.get("downstream_gates", {}).get("R3_allowed_to_start") is False,
        "R3_gate",
    )
    t04 = final.get("upstream_bindings", {}).get("t04", {})
    for key, value in EXPECTED_T04.items():
        _error(errors, t04.get(key) == value, f"final_t04_binding:{key}")
    t05 = final.get("upstream_bindings", {}).get("t05", {})
    for key, value in EXPECTED_T05.items():
        _error(errors, t05.get(key) == value, f"final_t05_binding:{key}")
    t06 = final.get("upstream_bindings", {}).get("t06", {})
    for key, value in EXPECTED_T06.items():
        config_key = "formal_execution_commit" if key == "execution_commit" else key
        _error(errors, t06.get(config_key) == value, f"final_t06_binding:{key}")

    artifact_manifest = docs.get("output_manifest", {})
    artifact_bytes = docs.get("artifact_bytes", {})
    if artifact_manifest:
        artifacts = artifact_manifest.get("artifacts", [])
        _error(
            errors,
            artifact_manifest.get("artifact_hash_basis") == "committed_artifact_bytes",
            "output_manifest_hash_basis",
        )
        _error(
            errors,
            artifact_manifest.get("artifact_count") == len(artifacts),
            "output_manifest_count",
        )
        paths = [item.get("path") for item in artifacts]
        _error(errors, len(paths) == len(set(paths)), "output_manifest_duplicate_path")
        for item in artifacts:
            if item.get("path") in artifact_bytes:
                payload = artifact_bytes[item["path"]]
                _error(
                    errors,
                    _sha256(payload) == item.get("sha256"),
                    f"manifest_hash:{item.get('path')}",
                )
                _error(
                    errors,
                    len(payload) == item.get("size_bytes"),
                    f"manifest_size:{item.get('path')}",
                )
    return errors


def _read_documents(output_dir: Path) -> dict[str, Any]:
    def load_json(name: str) -> dict[str, Any]:
        with (output_dir / name).open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"json_not_object:{name}")
        return value

    docs = {
        "state_registry": _read_csv(output_dir / "r2_state_version_registry.csv"),
        "interval_registry": load_json("r2_interval_rule_registry.json"),
        "event_registry": load_json("r2_event_state_machine_registry.json"),
        "decision_log": load_json("r2_freeze_decision_log.json"),
        "final_manifest": load_json("r2_final_freeze_manifest.json"),
    }
    output_manifest = output_dir / "r2_t07_output_manifest.json"
    if output_manifest.exists():
        docs["output_manifest"] = load_json("r2_t07_output_manifest.json")
        artifact_bytes: dict[str, bytes] = {}
        for item in docs["output_manifest"].get("artifacts", []):
            path = item.get("path", "")
            rel = Path(path).relative_to(
                Path("data/generated/r2/r2_t07") / output_dir.name
            )
            artifact_bytes[path] = (output_dir / rel).read_bytes()
        docs["artifact_bytes"] = artifact_bytes
    return docs


def _write_manifest(output_dir: Path, run_id: str) -> None:
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
                "sha256": _sha256(payload),
                "size_bytes": len(payload),
            }
        )
    write_json(
        output_dir / "r2_t07_output_manifest.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed",
            "artifact_hash_basis": "committed_artifact_bytes",
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        },
    )


def validate_run(output_dir: Path) -> dict[str, Any]:
    run_id = output_dir.name
    try:
        docs = _read_documents(output_dir)
        errors = validate_documents(docs)
        status = "passed" if not errors else "failed"
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        errors = [f"unreadable_artifact:{exc}"]
        status = "failed"
    result = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": status,
        "failure_count": len(errors),
        "errors": errors,
        "checks": {
            "registry_contract": "passed"
            if not any("registry" in error or "version" in error for error in errors)
            else "failed",
            "decision_binding": "passed"
            if not any("decision" in error or "warning" in error for error in errors)
            else "failed",
            "event_policy": "passed"
            if not any("event" in error or "transition" in error for error in errors)
            else "failed",
            "manifest_binding": "passed"
            if not any("manifest" in error for error in errors)
            else "failed",
            "downstream_gates": "passed"
            if not any("gate" in error for error in errors)
            else "failed",
        },
        "registry_freeze_only": True,
        "replay_performed": False,
        "R2-T08_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t07_independent_validation.json", result)
    anomaly = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": status,
        "anomaly_count": len(errors),
        "anomalies": errors,
    }
    write_json(output_dir / "r2_t07_anomaly_scan.json", anomaly)
    write_markdown(
        output_dir / "r2_t07_result_analysis.md",
        f"# R2-T07 independent result analysis\n\nRun `{run_id}` status: `{status}`. "
        f"The independent validator found {len(errors)} failure(s). Registry/manifest freeze only was checked; no replay database was generated. "
        "T08 and R3 remain closed pending scientific review and later gates.\n",
    )
    write_json(
        output_dir / "r2_t07_experiment_summary.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed" if not errors else "failed",
            "registry_freeze_only": True,
            "frozen_version_count": 2 if not errors else None,
            "replay_performed": False,
        },
    )
    write_json(
        output_dir / "r2_t07_result_package.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "execution_status": "validated" if not errors else "validation_failed",
            "independent_validation_status": status,
            "anomaly_scan_status": status,
            "formal_task_completed": False,
            "scientific_review_status": "pending_independent_scientific_review",
            "R2-T07_allowed_to_start": False,
            "R2-T08_allowed_to_start": False,
            "R3_allowed_to_start": False,
            "output_manifest_path": f"data/generated/r2/r2_t07/{run_id}/r2_t07_output_manifest.json",
        },
    )
    _write_manifest(output_dir, run_id)
    return result


__all__ = [
    "EXPECTED_T04",
    "EXPECTED_T05",
    "EXPECTED_T06",
    "EXPECTED_VERSIONS",
    "validate_documents",
    "validate_run",
]
