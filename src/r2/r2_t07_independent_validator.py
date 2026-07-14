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
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import (
    canonical_json_sha256,
    write_csv,
    write_json,
    write_markdown,
)

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

STATE_REGISTRY_HEADER = [
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
NEW_ALLOWED_USES = [
    "T08_R2_final_acceptance_input",
    "T08_R3_handoff_source",
    "canonical_daily_state_consumption",
    "canonical_event_zone_consumption",
    "canonical_event_membership_consumption",
    "state_risk_set_consumption",
    "qualified_event_risk_set_consumption",
    "R3_contract_design_only",
]
NEW_FORBIDDEN_USES = [
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
NEW_FORBIDDEN_REINTERPRETATIONS = [
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
NEW_AUTHORITATIVE_TIMES = [
    "confirmation_time",
    "first_qualification_time",
    "last_exit_observation_time",
    "zone_finalization_time",
    "membership_available_time",
]
NEW_EXPECTED_ROWS = [
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
        "t04_decision_unit": "S_PCT×W120",
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
        "strict_core_source_candidate_cell_id": "r2_s_pcvt_w120_q20_shared__d2__g1",
        "t04_decision_unit": "S_PCVT×W120",
    },
]
NEW_EXPECTED_WARNINGS = {
    "S_PCT": [
        "affected_lift_deterioration_vs_baseline",
        "layer_q_complexity_added",
        "same_sample_formal_revalidation_only",
        "selection_path_not_independently_confirmed",
    ],
    "S_PCVT": [
        "V_security_negative_delta_share_material",
        "V_selectivity_reduced_but_guard_passed",
        "layer_q_complexity_added",
        "same_sample_formal_revalidation_only",
        "selection_path_not_independently_confirmed",
    ],
}

SUCCESSOR_CHECK_KEYS = [
    "state_registry_header_mismatch",
    "state_registry_row_mismatch",
    "state_registry_formula_binding_mismatch",
    "state_registry_r1_handoff_mismatch",
    "state_registry_warning_mismatch",
    "state_registry_use_policy_mismatch",
    "interval_registry_mismatch",
    "event_state_registry_mismatch",
    "zone_revision_policy_mismatch",
    "canonical_field_mapping_mismatch",
    "canonical_risk_set_policy_mismatch",
    "time_authority_mismatch",
    "decision_log_mismatch",
    "decision_unit_count_mismatch",
    "rejected_decision_unit_mismatch",
    "selection_path_flag_mismatch",
    "core_artifact_missing_count",
    "core_artifact_path_mismatch_count",
    "core_artifact_sha256_mismatch_count",
    "core_artifact_size_mismatch_count",
    "core_artifact_output_manifest_mismatch_count",
    "canonical_hash_mismatch",
    "frozen_version_id_mismatch",
    "forbidden_reinterpretation_mismatch",
    "unexpected_field_violation",
    "forbidden_field_violation",
    "readme_t05_status_mismatch",
    "downstream_gate_violation",
]

CORE_ARTIFACTS = {
    "state_version_registry": "r2_state_version_registry.csv",
    "interval_rule_registry": "r2_interval_rule_registry.json",
    "event_state_machine_registry": "r2_event_state_machine_registry.json",
    "freeze_decision_log": "r2_freeze_decision_log.json",
}
DECISION_SOURCE_COMMIT = "12cd31d125e31762e62f8b1db5a808d189c7c732"
DECISION_SOURCE_PATH = (
    "data/generated/r2/r2_t04/R2-T04-20260713T120000Z/r2_t04_user_decision_record.json"
)
EXPECTED_EVALUATION_TIME_RULE = (
    "consume the already materialized canonical as-of and risk-set fields; "
    "visibility must not be reconstructed from trade_date alone"
)
EXPECTED_VISIBILITY_FIELDS = [
    "confirmation_time",
    "first_qualification_time",
    "zone_finalization_time",
    "membership_available_time",
]
EXPECTED_DAILY_RISK_CONTRACT = {
    "table": "r2_canonical_daily_state",
    "authoritative_field": "qualified_event_risk_set_eligible",
    "audit_implications": [
        "qualified_event_risk_set_eligible_implies_state_risk_set_eligible",
        "qualified_event_risk_set_eligible_implies_confirmed_state",
        "qualified_event_risk_set_eligible_implies_component_qualified_as_of",
        "qualified_event_risk_set_eligible_implies_active_event_id_as_of_not_null",
    ],
    "forbidden_derivation": [
        "do_not_derive_from_event_zone_member_alone",
        "do_not_use_source_only_gap_aliases",
    ],
}
EXPECTED_MEMBERSHIP_RISK_CONTRACT = {
    "table": "r2_canonical_event_membership",
    "authoritative_field": "qualified_event_risk_set_eligible",
    "audit_formula": {
        "all_of": [
            "state_risk_set_eligible",
            "confirmed_state",
            "component_qualified_as_of",
            "event_zone_member",
        ],
        "all_false": [
            "is_bridged_gap",
            "is_prequalification_confirmed_day",
            "is_unqualified_reentry_day",
        ],
    },
    "permitted_non_risk_membership": [
        "raw_false_bridge",
        "prequalification_confirmed_day",
        "unqualified_reentry_day",
        "terminal_membership",
    ],
}


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


def _is_successor_documents(docs: dict[str, Any]) -> bool:
    return docs.get(
        "state_registry_header"
    ) == STATE_REGISTRY_HEADER or "state_version_registry" in docs.get(
        "final_manifest", {}
    )


def _new_error(errors: list[str], condition: bool, code: str) -> None:
    if not condition:
        errors.append(code)


def _json_array(value: Any) -> list[str] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return (
        parsed
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed)
        else None
    )


def _new_key_error(
    errors: list[str], obj: dict[str, Any], expected: set[str], code: str
) -> None:
    _new_error(errors, set(obj) == expected, code)


def _successor_core_artifact_checks(docs: dict[str, Any]) -> dict[str, int]:
    """Compare the four core files with both manifests and their actual bytes."""

    counts = {
        "core_artifact_missing_count": 0,
        "core_artifact_path_mismatch_count": 0,
        "core_artifact_sha256_mismatch_count": 0,
        "core_artifact_size_mismatch_count": 0,
        "core_artifact_output_manifest_mismatch_count": 0,
    }
    final = docs.get("final_manifest", {})
    run_id = str(final.get("run_id", ""))
    expected_base = f"data/generated/r2/r2_t07/{run_id}"
    artifact_bytes = docs.get("artifact_bytes", {})
    manifest = docs.get("output_manifest", {})
    records = {
        item.get("path"): item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and item.get("path")
    }
    for field, filename in CORE_ARTIFACTS.items():
        expected_path = f"{expected_base}/{filename}"
        ref = final.get(field)
        if not isinstance(ref, dict):
            counts["core_artifact_missing_count"] += 1
            counts["core_artifact_path_mismatch_count"] += 1
            counts["core_artifact_sha256_mismatch_count"] += 1
            counts["core_artifact_size_mismatch_count"] += 1
            counts["core_artifact_output_manifest_mismatch_count"] += 1
            continue
        payload = artifact_bytes.get(expected_path)
        record = records.get(expected_path)
        if payload is None or record is None:
            counts["core_artifact_missing_count"] += 1
        actual_sha = _sha256(payload) if payload is not None else None
        actual_size = len(payload) if payload is not None else None
        if ref.get("path") != expected_path or record is None:
            counts["core_artifact_path_mismatch_count"] += 1
        if payload is None or ref.get("sha256") != actual_sha:
            counts["core_artifact_sha256_mismatch_count"] += 1
        if payload is None or ref.get("size_bytes") != actual_size:
            counts["core_artifact_size_mismatch_count"] += 1
        if (
            record is None
            or record.get("path") != expected_path
            or record.get("sha256") != actual_sha
            or record.get("size_bytes") != actual_size
            or record.get("sha256") != ref.get("sha256")
            or record.get("size_bytes") != ref.get("size_bytes")
        ):
            counts["core_artifact_output_manifest_mismatch_count"] += 1
    return counts


def _committed_decision_units() -> tuple[bytes, list[dict[str, Any]]]:
    root = Path(__file__).resolve().parents[2]
    blob = subprocess.run(
        ["git", "show", f"{DECISION_SOURCE_COMMIT}:{DECISION_SOURCE_PATH}"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    record = json.loads(blob.decode("utf-8"))
    return blob, record["decision_units"]


def _successor_check_counts(docs: dict[str, Any]) -> dict[str, int]:
    """Return numeric fail-closed checks for every successor contract gate."""

    counts = {key: 0 for key in SUCCESSOR_CHECK_KEYS}

    def bad(key: str, condition: bool, amount: int = 1) -> None:
        if not condition:
            counts[key] += amount

    rows = docs.get("state_registry", [])
    header = docs.get("state_registry_header", [])
    bad("state_registry_header_mismatch", header == STATE_REGISTRY_HEADER)
    bad("state_registry_row_mismatch", len(rows) == 2)
    expected_ids = {item["state_version_id"] for item in NEW_EXPECTED_ROWS}
    bad(
        "frozen_version_id_mismatch",
        {row.get("state_version_id") for row in rows} == expected_ids,
    )
    for index, expected in enumerate(NEW_EXPECTED_ROWS):
        row = rows[index] if index < len(rows) else {}
        bad(
            "state_registry_row_mismatch",
            all(row.get(key) == value for key, value in expected.items()),
        )
        bad(
            "state_registry_formula_binding_mismatch",
            len(row.get("state_formula_binding_sha256", "")) == 64,
        )
        bad(
            "state_registry_r1_handoff_mismatch",
            len(row.get("r1_handoff_row_sha256", "")) == 64,
        )
        bad(
            "state_registry_warning_mismatch",
            _json_array(row.get("warning_codes"))
            == NEW_EXPECTED_WARNINGS[expected["state_line"]],
        )
        bad(
            "state_registry_use_policy_mismatch",
            _json_array(row.get("allowed_uses")) == NEW_ALLOWED_USES
            and _json_array(row.get("forbidden_uses")) == NEW_FORBIDDEN_USES,
        )
    bad(
        "frozen_version_id_mismatch",
        not any("W250" in str(row.get("state_version_id")) for row in rows),
    )
    bad(
        "frozen_version_id_mismatch",
        not any("parent" in str(row.get("state_version_id")).lower() for row in rows),
    )
    bad(
        "frozen_version_id_mismatch",
        not any(
            "shared" in str(row.get("source_candidate_cell_id")).lower() for row in rows
        ),
    )

    interval = docs.get("interval_registry", {})
    expected_interval_keys = {
        "task_id",
        "registry_id",
        "contract_version",
        "applicable_state_version_ids",
        "K",
        "confirmation_rule",
        "confirmation_backfill_allowed",
        "atomic_interval_rule",
        "termination_reason_mapping",
        "d",
        "d_operator",
        "d_count_unit",
        "g",
        "g_count_unit",
        "raw_false_gap_rule",
        "preconfirmation_raw_true_rule",
        "hard_break_reasons",
        "g_plus_one_finalization_rule",
        "unqualified_reentry_policy",
        "transitive_merge_policy",
        "anti_percolation_policy",
        "left_censor_policy",
        "right_censor_policy",
        "open_zone_policy",
        "qualification_time_rule",
        "finalization_time_rule",
        "membership_available_time_rule",
        "source_bindings",
    }
    bad("unexpected_field_violation", set(interval) == expected_interval_keys)
    bad(
        "interval_registry_mismatch",
        interval.get("task_id") == TASK_ID
        and interval.get("contract_version") == CONTRACT_VERSION
        and interval.get("applicable_state_version_ids")
        == [item["state_version_id"] for item in NEW_EXPECTED_ROWS]
        and interval.get("K") == 3
        and interval.get("confirmation_backfill_allowed") is False
        and interval.get("d") == 2
        and interval.get("d_operator") == ">="
        and interval.get("d_count_unit") == "confirmed_trading_day"
        and interval.get("g") == 1
        and interval.get("g_count_unit") == "eligible_valid_raw_false_trading_day"
        and set(interval.get("hard_break_reasons", []))
        == {
            "unknown",
            "blocked",
            "diagnostic_required",
            "ineligible",
            "missing_observation",
            "missing_expected_trading_row",
            "intervening_unqualified_confirmed_interval",
        }
        and "g+1" in interval.get("g_plus_one_finalization_rule", "")
        and "irreversible" in interval.get("g_plus_one_finalization_rule", ""),
    )

    event = docs.get("event_registry", {})
    expected_event_keys = {
        "task_id",
        "registry_id",
        "contract_version",
        "applicable_state_version_ids",
        "states",
        "transitions",
        "transition_registry_sha256",
        "event_identity_policy",
        "zone_revision_policy",
        "exit_policy",
        "quality_break_policy",
        "censor_policy",
        "time_semantics",
        "source_contract_risk_set_policy",
        "canonical_consumer_mapping",
        "canonical_risk_set_policy",
        "daily_risk_set_contract",
        "membership_risk_set_contract",
        "source_bindings",
    }
    bad("unexpected_field_violation", set(event) == expected_event_keys)
    bad(
        "event_state_registry_mismatch",
        event.get("task_id") == TASK_ID
        and event.get("contract_version") == CONTRACT_VERSION
        and event.get("states") == EXPECTED_STATES
        and _as_transition_rows(event.get("transitions", [])) == EXPECTED_TRANSITIONS
        and len(event.get("transition_registry_sha256", "")) == 64,
    )
    identity = event.get("event_identity_policy", {})
    revision = event.get("zone_revision_policy", {})
    bad(
        "zone_revision_policy_mismatch",
        identity.get("event_id_fixed_at_first_qualified_component") is True
        and identity.get("reentry_does_not_change_event_id") is True
        and identity.get("cross_state_version_merge_allowed") is False
        and revision.get("event_id_fixed_at_first_qualified_component") is True
        and revision.get("reentry_does_not_change_event_id") is True
        and revision.get("revision_increments_or_stays_non_decreasing") is True
        and revision.get("no_cross_state_version_merge") is True
        and revision.get("membership_availability_not_before_source_fact") is True,
    )
    time = event.get("time_semantics", {})
    bad(
        "time_authority_mismatch",
        time.get("authoritative_time_fields") == NEW_AUTHORITATIVE_TIMES
        and time.get("non_authoritative_time_fields")
        == ["r2_t06_replayed_transition_ledger.trigger_trade_date"]
        and time.get("trigger_trade_date_is_causal") is False
        and time.get("trigger_trade_date_is_release_anchor") is False,
    )
    mapping = event.get("canonical_consumer_mapping", {})
    expected_mapping = {
        "eligible": "r2_canonical_daily_state.eligible_state",
        "quality_state": "r2_canonical_daily_state.quality_state",
        "confirmed_state": "r2_canonical_daily_state.confirmed_state",
        "event_status_as_of": "r2_canonical_daily_state.event_status_as_of",
        "active_event_id_as_of": "r2_canonical_daily_state.active_event_id_as_of",
        "event_zone_member": "r2_canonical_event_membership.event_zone_member",
        "retrospective_component_member": "r2_canonical_event_membership.retrospective_component_member",
        "component_qualified_as_of": "r2_canonical_daily_state.component_qualified_as_of",
        "membership_available_time": "r2_canonical_event_membership.membership_available_time",
        "state_risk_set_eligible": "r2_canonical_daily_state.state_risk_set_eligible",
        "qualified_event_risk_set_eligible": "r2_canonical_daily_state.qualified_event_risk_set_eligible",
        "source_to_canonical_aliases": {
            "is_raw_false_bridge": "is_bridged_gap",
            "is_preconfirmation_gap": "is_prequalification_confirmed_day",
        },
    }
    evaluation = mapping.get("evaluation_time", {})
    bad(
        "canonical_field_mapping_mismatch",
        all(mapping.get(key) == value for key, value in expected_mapping.items())
        and evaluation.get("canonical_status") == "not_exposed_as_standalone_field"
        and evaluation.get("consumer_rule") == EXPECTED_EVALUATION_TIME_RULE
        and evaluation.get("authoritative_visibility_fields")
        == EXPECTED_VISIBILITY_FIELDS
        and mapping.get("raw_false_gap_ordinal_as_of", {}).get("canonical_status")
        == "audit_only_not_exposed_to_R3"
        and mapping.get("raw_false_gap_count_as_of", {}).get("canonical_status")
        == "audit_only_not_exposed_to_R3",
    )
    risk = event.get("canonical_risk_set_policy", {})
    bad(
        "canonical_risk_set_policy_mismatch",
        risk.get("state_risk_set_eligible")
        == "direct canonical daily field; not derived from event_zone_member"
        and risk.get("qualified_event_risk_set_eligible")
        == "direct canonical daily/membership field; event_zone_member alone is insufficient"
        and risk.get("daily_audit_formula", "").startswith(
            "qualified_event_risk_set_eligible is the authoritative canonical daily field"
        )
        and risk.get("membership_audit_formula", "").startswith(
            "the closed membership_risk_set_contract is authoritative"
        ),
    )
    bad(
        "canonical_risk_set_policy_mismatch",
        event.get("daily_risk_set_contract") == EXPECTED_DAILY_RISK_CONTRACT,
    )
    bad(
        "canonical_risk_set_policy_mismatch",
        event.get("membership_risk_set_contract") == EXPECTED_MEMBERSHIP_RISK_CONTRACT,
    )

    decision = docs.get("decision_log", {})
    expected_decision_keys = {
        "task_id",
        "user_decision_record_path",
        "user_decision_record_sha256",
        "decision_unit_count",
        "selected_decision_unit_count",
        "rejected_decision_unit_count",
        "strict_core_only_count",
        "selection_path_not_independently_confirmed",
        "decision_hash",
        "freeze_decision_hash",
        "freeze_plan_hash",
        "decision_authority",
        "automatic_recommendation_authoritative",
        "selection_path",
        "decision_units",
    }
    bad("unexpected_field_violation", set(decision) == expected_decision_keys)
    units = decision.get("decision_units", [])
    bad(
        "decision_unit_count_mismatch",
        decision.get("decision_unit_count") == 4 and len(units) == 4,
    )
    bad(
        "decision_unit_count_mismatch",
        decision.get("selected_decision_unit_count") == 2
        and decision.get("strict_core_only_count") == 2,
    )
    bad(
        "rejected_decision_unit_mismatch",
        decision.get("rejected_decision_unit_count") == 2,
    )
    bad(
        "selection_path_flag_mismatch",
        decision.get("selection_path_not_independently_confirmed") is True
        and decision.get("automatic_recommendation_authoritative") is False
        and decision.get("selection_path")
        == "explicit_user_decision_not_automatic_recommendation",
    )
    try:
        source_blob, source_units = _committed_decision_units()
        unit_keys = {
            "accepted_event_zone_tradeoffs",
            "accepted_warnings",
            "automatic_recommendation",
            "automatic_recommendation_authoritative",
            "decision_authority",
            "decision_time",
            "decision_unit",
            "evidence_refs",
            "evidence_values",
            "github_identity",
            "override",
            "override_justification",
            "pair_disposition",
            "paired_primary_candidate",
            "paired_shared_candidate",
            "primary_disposition",
            "primary_reason_code",
            "rejected_alternatives",
            "reviewer_identity",
            "secondary_reason_codes",
            "selected_candidate_cell_id",
            "selected_d",
            "selected_g",
            "shared_disposition",
            "strict_core_enabled",
            "user_disposition",
            "source_decision_unit_sha256",
        }
        units_match = len(units) == len(source_units)
        if units_match:
            for actual, source in zip(units, source_units):
                candidate = dict(actual)
                source_hash = candidate.pop("source_decision_unit_sha256", None)
                units_match = units_match and set(actual) == unit_keys
                units_match = units_match and candidate == source
                units_match = units_match and source_hash == canonical_json_sha256(
                    source
                )
        bad("decision_log_mismatch", units_match)
        bad(
            "decision_log_mismatch",
            decision.get("user_decision_record_sha256") == _sha256(source_blob),
        )
    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ):
        bad("decision_log_mismatch", False)
    bad(
        "decision_log_mismatch",
        decision.get("decision_hash") == EXPECTED_T04["decision_hash"]
        and decision.get("freeze_decision_hash") == EXPECTED_T04["freeze_decision_hash"]
        and decision.get("freeze_plan_hash") == EXPECTED_T04["freeze_plan_hash"]
        and decision.get("decision_authority") == "user_explicit_instruction",
    )
    bad(
        "rejected_decision_unit_mismatch",
        {unit.get("decision_unit") for unit in units}
        == {"S_PCT×W120", "S_PCT×W250", "S_PCVT×W120", "S_PCVT×W250"}
        and all(
            unit.get("pair_disposition") == "reject_pair"
            for unit in units
            if "W250" in str(unit.get("decision_unit"))
        ),
    )

    final = docs.get("final_manifest", {})
    expected_final_keys = {
        "task_id",
        "run_id",
        "status",
        "execution_commit",
        "registry_freeze_only",
        "replay_performed",
        "state_version_registry",
        "interval_rule_registry",
        "event_state_machine_registry",
        "freeze_decision_log",
        "t02_contract_version",
        "t04_run_id",
        "t04_decision_hash",
        "t04_freeze_decision_hash",
        "t04_freeze_plan_hash",
        "t04_user_decision_record_sha256",
        "t05_run_id",
        "t05_database_sha256",
        "canonical_daily_state_sha256",
        "canonical_event_zone_sha256",
        "canonical_event_membership_sha256",
        "canonical_daily_row_count",
        "canonical_event_row_count",
        "canonical_membership_row_count",
        "t06_run_id",
        "t06_merge_commit",
        "t06_reviewed_head",
        "t06_scientific_review_id",
        "t06_artifact_commit",
        "t06_replay_database_sha256",
        "frozen_version_count",
        "frozen_state_version_ids",
        "selection_path_not_independently_confirmed",
        "authoritative_time_fields",
        "non_authoritative_time_fields",
        "allowed_uses",
        "forbidden_reinterpretations",
        "downstream_gates",
    }
    bad("unexpected_field_violation", set(final) == expected_final_keys)
    bad(
        "canonical_hash_mismatch",
        final.get("t05_run_id") == EXPECTED_T05["run_id"]
        and final.get("t05_database_sha256") == EXPECTED_T05["database_sha256"]
        and final.get("canonical_daily_state_sha256") == EXPECTED_T05["daily_sha256"]
        and final.get("canonical_event_zone_sha256") == EXPECTED_T05["event_sha256"]
        and final.get("canonical_event_membership_sha256")
        == EXPECTED_T05["membership_sha256"]
        and final.get("canonical_daily_row_count") == EXPECTED_T05["daily_row_count"]
        and final.get("canonical_event_row_count") == EXPECTED_T05["event_row_count"]
        and final.get("canonical_membership_row_count")
        == EXPECTED_T05["membership_row_count"],
    )
    bad(
        "frozen_version_id_mismatch",
        final.get("frozen_version_count") == 2
        and final.get("frozen_state_version_ids") == sorted(expected_ids),
    )
    bad(
        "decision_log_mismatch",
        final.get("t04_decision_hash") == EXPECTED_T04["decision_hash"]
        and final.get("t04_freeze_decision_hash")
        == EXPECTED_T04["freeze_decision_hash"]
        and final.get("t04_freeze_plan_hash") == EXPECTED_T04["freeze_plan_hash"],
    )
    bad(
        "time_authority_mismatch",
        final.get("authoritative_time_fields") == NEW_AUTHORITATIVE_TIMES
        and final.get("non_authoritative_time_fields")
        == ["r2_t06_replayed_transition_ledger.trigger_trade_date"],
    )
    bad(
        "forbidden_reinterpretation_mismatch",
        final.get("forbidden_reinterpretations") == NEW_FORBIDDEN_REINTERPRETATIONS,
    )
    bad(
        "downstream_gate_violation",
        final.get("downstream_gates")
        == {"R2-T08_allowed_to_start": False, "R3_allowed_to_start": False},
    )
    counts.update(_successor_core_artifact_checks(docs))

    audit = docs.get("forbidden_use_audit")
    bad(
        "forbidden_field_violation",
        isinstance(audit, dict)
        and audit.get("status") == "passed"
        and audit.get("failure_count") == 0
        and isinstance(audit.get("scanned_json_artifacts"), list)
        and isinstance(audit.get("scanned_csv_artifacts"), list)
        and isinstance(audit.get("scanned_csv_headers"), list)
        and audit.get("required_guards")
        == {
            "forbidden_reinterpretations": True,
            "downstream_gates": True,
            "time_authority": True,
            "state_registry_header_closed": True,
        },
    )
    root = Path(__file__).resolve().parents[2]
    readme = root / "docs/tasks/README.md"
    try:
        readme_text = readme.read_text(encoding="utf-8")
    except OSError:
        readme_text = ""
    bad(
        "readme_t05_status_mismatch",
        "R2-T05" in readme_text and "completed" in readme_text.lower(),
    )
    return counts


def _validate_successor_documents(docs: dict[str, Any]) -> list[str]:
    """Validate the successor contract independently of the T07 generator."""

    errors: list[str] = []
    rows = docs.get("state_registry", [])
    header = docs.get("state_registry_header", [])
    _new_error(
        errors, header == STATE_REGISTRY_HEADER, "state_registry_header_mismatch"
    )
    _new_error(errors, len(rows) == 2, "state_registry_row_mismatch")
    expected_ids = {item["state_version_id"] for item in NEW_EXPECTED_ROWS}
    _new_error(
        errors,
        {row.get("state_version_id") for row in rows} == expected_ids,
        "frozen_version_id_mismatch",
    )
    for index, expected in enumerate(NEW_EXPECTED_ROWS):
        if index >= len(rows):
            errors.append("state_registry_row_mismatch")
            continue
        row = rows[index]
        for key, value in expected.items():
            _new_error(
                errors,
                row.get(key) == value,
                f"state_registry_row_mismatch:{key}:{index}",
            )
        _new_error(
            errors,
            row.get("freeze_status") == "frozen",
            "state_registry_row_mismatch:freeze_status",
        )
        _new_error(
            errors,
            row.get("strict_core_enabled") == "True",
            "state_registry_row_mismatch:strict_core_enabled",
        )
        _new_error(
            errors,
            len(row.get("state_formula_binding_sha256", "")) == 64,
            "state_registry_formula_binding_mismatch",
        )
        _new_error(
            errors,
            len(row.get("r1_handoff_row_sha256", "")) == 64,
            "state_registry_r1_handoff_mismatch",
        )
        _new_error(
            errors,
            row.get("confirmed_state_contract_id") == CONTRACT_VERSION,
            "state_registry_row_mismatch:contract",
        )
        _new_error(
            errors,
            row.get("selection_path_not_independently_confirmed") == "True",
            "selection_path_flag_mismatch",
        )
        warnings = _json_array(row.get("warning_codes"))
        _new_error(
            errors,
            warnings == NEW_EXPECTED_WARNINGS[expected["state_line"]],
            "state_registry_warning_mismatch",
        )
        _new_error(
            errors,
            _json_array(row.get("allowed_uses")) == NEW_ALLOWED_USES
            and _json_array(row.get("forbidden_uses")) == NEW_FORBIDDEN_USES,
            "state_registry_use_policy_mismatch",
        )
    _new_error(
        errors,
        not any("W250" in str(row.get("state_version_id")) for row in rows),
        "W250_independent_version",
    )
    _new_error(
        errors,
        not any("parent" in str(row.get("state_version_id")).lower() for row in rows),
        "PCT_parent_product",
    )
    _new_error(
        errors,
        not any(
            "shared" in str(row.get("source_candidate_cell_id")).lower() for row in rows
        ),
        "shared_q_independent_version",
    )

    interval = docs.get("interval_registry", {})
    _new_key_error(
        errors,
        interval,
        {
            "task_id",
            "registry_id",
            "contract_version",
            "applicable_state_version_ids",
            "K",
            "confirmation_rule",
            "confirmation_backfill_allowed",
            "atomic_interval_rule",
            "termination_reason_mapping",
            "d",
            "d_operator",
            "d_count_unit",
            "g",
            "g_count_unit",
            "raw_false_gap_rule",
            "preconfirmation_raw_true_rule",
            "hard_break_reasons",
            "g_plus_one_finalization_rule",
            "unqualified_reentry_policy",
            "transitive_merge_policy",
            "anti_percolation_policy",
            "left_censor_policy",
            "right_censor_policy",
            "open_zone_policy",
            "qualification_time_rule",
            "finalization_time_rule",
            "membership_available_time_rule",
            "source_bindings",
        },
        "unexpected_field_violation",
    )
    _new_error(
        errors,
        interval.get("task_id") == TASK_ID
        and interval.get("contract_version") == CONTRACT_VERSION,
        "interval_registry_mismatch",
    )
    _new_error(
        errors,
        interval.get("applicable_state_version_ids")
        == [item["state_version_id"] for item in NEW_EXPECTED_ROWS],
        "interval_registry_mismatch",
    )
    _new_error(
        errors,
        interval.get("K") == 3
        and interval.get("confirmation_backfill_allowed") is False
        and interval.get("d") == 2
        and interval.get("d_operator") == ">="
        and interval.get("d_count_unit") == "confirmed_trading_day"
        and interval.get("g") == 1
        and interval.get("g_count_unit") == "eligible_valid_raw_false_trading_day",
        "interval_registry_mismatch",
    )
    _new_error(
        errors,
        set(interval.get("hard_break_reasons", []))
        == {
            "unknown",
            "blocked",
            "diagnostic_required",
            "ineligible",
            "missing_observation",
            "missing_expected_trading_row",
            "intervening_unqualified_confirmed_interval",
        },
        "interval_registry_mismatch",
    )
    _new_error(
        errors,
        "g+1" in interval.get("g_plus_one_finalization_rule", "")
        and "irreversible" in interval.get("g_plus_one_finalization_rule", ""),
        "interval_registry_mismatch",
    )

    event = docs.get("event_registry", {})
    _new_key_error(
        errors,
        event,
        {
            "task_id",
            "registry_id",
            "contract_version",
            "applicable_state_version_ids",
            "states",
            "transitions",
            "transition_registry_sha256",
            "event_identity_policy",
            "zone_revision_policy",
            "exit_policy",
            "quality_break_policy",
            "censor_policy",
            "time_semantics",
            "source_contract_risk_set_policy",
            "canonical_consumer_mapping",
            "canonical_risk_set_policy",
            "daily_risk_set_contract",
            "membership_risk_set_contract",
            "source_bindings",
        },
        "unexpected_field_violation",
    )
    _new_error(
        errors,
        event.get("task_id") == TASK_ID
        and event.get("contract_version") == CONTRACT_VERSION
        and event.get("states") == EXPECTED_STATES,
        "event_state_registry_mismatch",
    )
    _new_error(
        errors,
        _as_transition_rows(event.get("transitions", [])) == EXPECTED_TRANSITIONS,
        "event_state_registry_mismatch",
    )
    _new_error(
        errors,
        len(event.get("transition_registry_sha256", "")) == 64,
        "event_state_registry_mismatch",
    )
    identity = event.get("event_identity_policy", {})
    revision = event.get("zone_revision_policy", {})
    _new_error(
        errors,
        identity.get("event_id_fixed_at_first_qualified_component") is True
        and identity.get("reentry_does_not_change_event_id") is True
        and identity.get("cross_state_version_merge_allowed") is False,
        "zone_revision_policy_mismatch",
    )
    _new_error(
        errors,
        revision.get("event_id_fixed_at_first_qualified_component") is True
        and revision.get("reentry_does_not_change_event_id") is True
        and revision.get("revision_increments_or_stays_non_decreasing") is True
        and revision.get("no_cross_state_version_merge") is True
        and revision.get("membership_availability_not_before_source_fact") is True,
        "zone_revision_policy_mismatch",
    )
    time = event.get("time_semantics", {})
    _new_error(
        errors,
        time.get("authoritative_time_fields") == NEW_AUTHORITATIVE_TIMES
        and time.get("non_authoritative_time_fields")
        == ["r2_t06_replayed_transition_ledger.trigger_trade_date"]
        and time.get("trigger_trade_date_is_causal") is False
        and time.get("trigger_trade_date_is_release_anchor") is False,
        "time_authority_mismatch",
    )
    mapping = event.get("canonical_consumer_mapping", {})
    _new_error(
        errors,
        mapping.get("eligible") == "r2_canonical_daily_state.eligible_state"
        and mapping.get("confirmed_state") == "r2_canonical_daily_state.confirmed_state"
        and mapping.get("event_zone_member")
        == "r2_canonical_event_membership.event_zone_member"
        and mapping.get("state_risk_set_eligible")
        == "r2_canonical_daily_state.state_risk_set_eligible"
        and mapping.get("qualified_event_risk_set_eligible")
        == "r2_canonical_daily_state.qualified_event_risk_set_eligible"
        and mapping.get("raw_false_gap_ordinal_as_of", {}).get("canonical_status")
        == "audit_only_not_exposed_to_R3",
        "canonical_field_mapping_mismatch",
    )
    risk = event.get("canonical_risk_set_policy", {})
    _new_error(
        errors,
        risk.get("state_risk_set_eligible", "").startswith(
            "direct canonical daily field"
        )
        and risk.get("qualified_event_risk_set_eligible", "").startswith(
            "direct canonical daily/membership field"
        )
        and "event_zone_member alone is insufficient"
        in risk.get("qualified_event_risk_set_eligible", "")
        and "membership_risk_set_contract" in risk.get("membership_audit_formula", ""),
        "canonical_risk_set_policy_mismatch",
    )

    decision = docs.get("decision_log", {})
    _new_error(
        errors,
        decision.get("decision_unit_count") == 4
        and decision.get("selected_decision_unit_count") == 2
        and decision.get("rejected_decision_unit_count") == 2
        and decision.get("strict_core_only_count") == 2,
        "decision_unit_count_mismatch",
    )
    _new_error(
        errors,
        decision.get("selection_path_not_independently_confirmed") is True,
        "selection_path_flag_mismatch",
    )
    _new_error(
        errors,
        decision.get("decision_hash") == EXPECTED_T04["decision_hash"]
        and decision.get("freeze_decision_hash") == EXPECTED_T04["freeze_decision_hash"]
        and decision.get("freeze_plan_hash") == EXPECTED_T04["freeze_plan_hash"],
        "decision_log_mismatch",
    )
    _new_error(
        errors,
        decision.get("automatic_recommendation_authoritative") is False
        and decision.get("selection_path")
        == "explicit_user_decision_not_automatic_recommendation",
        "decision_log_mismatch",
    )
    units = decision.get("decision_units", [])
    _new_error(errors, len(units) == 4, "decision_unit_count_mismatch")
    dispositions = {
        "S_PCT×W120": ("selected", True),
        "S_PCT×W250": ("reject_pair", False),
        "S_PCVT×W120": ("selected", True),
        "S_PCVT×W250": ("reject_pair", False),
    }
    for unit in units:
        name = unit.get("decision_unit")
        if name not in dispositions:
            errors.append("decision_log_mismatch")
            continue
        disposition, strict = dispositions[name]
        _new_error(
            errors,
            unit.get("pair_disposition") == disposition
            and unit.get("strict_core_enabled") is strict,
            "decision_log_mismatch",
        )
        if name in {"S_PCT×W120", "S_PCVT×W120"}:
            _new_error(
                errors,
                sorted(unit.get("accepted_warnings", []))
                == NEW_EXPECTED_WARNINGS[name.split("×")[0]],
                "decision_log_mismatch",
            )
    _new_error(
        errors,
        decision.get("user_decision_record_sha256")
        and len(decision.get("user_decision_record_sha256", "")) == 64,
        "decision_log_mismatch",
    )

    final = docs.get("final_manifest", {})
    final_keys = {
        "task_id",
        "run_id",
        "status",
        "execution_commit",
        "registry_freeze_only",
        "replay_performed",
        "state_version_registry",
        "interval_rule_registry",
        "event_state_machine_registry",
        "freeze_decision_log",
        "t02_contract_version",
        "t04_run_id",
        "t04_decision_hash",
        "t04_freeze_decision_hash",
        "t04_freeze_plan_hash",
        "t04_user_decision_record_sha256",
        "t05_run_id",
        "t05_database_sha256",
        "canonical_daily_state_sha256",
        "canonical_event_zone_sha256",
        "canonical_event_membership_sha256",
        "canonical_daily_row_count",
        "canonical_event_row_count",
        "canonical_membership_row_count",
        "t06_run_id",
        "t06_merge_commit",
        "t06_reviewed_head",
        "t06_scientific_review_id",
        "t06_artifact_commit",
        "t06_replay_database_sha256",
        "frozen_version_count",
        "frozen_state_version_ids",
        "selection_path_not_independently_confirmed",
        "authoritative_time_fields",
        "non_authoritative_time_fields",
        "allowed_uses",
        "forbidden_reinterpretations",
        "downstream_gates",
    }
    _new_key_error(errors, final, final_keys, "unexpected_field_violation")
    _new_error(
        errors,
        final.get("status")
        == "completed_author_draft_pending_independent_scientific_review"
        and final.get("registry_freeze_only") is True
        and final.get("replay_performed") is False,
        "decision_log_mismatch",
    )
    _new_error(
        errors,
        final.get("frozen_version_count") == 2
        and final.get("frozen_state_version_ids") == sorted(expected_ids),
        "frozen_version_id_mismatch",
    )
    _new_error(
        errors,
        final.get("t04_decision_hash") == EXPECTED_T04["decision_hash"]
        and final.get("t04_freeze_decision_hash")
        == EXPECTED_T04["freeze_decision_hash"]
        and final.get("t04_freeze_plan_hash") == EXPECTED_T04["freeze_plan_hash"],
        "decision_log_mismatch",
    )
    _new_error(
        errors,
        final.get("t05_run_id") == EXPECTED_T05["run_id"]
        and final.get("t05_database_sha256") == EXPECTED_T05["database_sha256"]
        and final.get("canonical_daily_state_sha256") == EXPECTED_T05["daily_sha256"]
        and final.get("canonical_event_zone_sha256") == EXPECTED_T05["event_sha256"]
        and final.get("canonical_event_membership_sha256")
        == EXPECTED_T05["membership_sha256"],
        "canonical_hash_mismatch",
    )
    _new_error(
        errors,
        final.get("canonical_daily_row_count") == EXPECTED_T05["daily_row_count"]
        and final.get("canonical_event_row_count") == EXPECTED_T05["event_row_count"]
        and final.get("canonical_membership_row_count")
        == EXPECTED_T05["membership_row_count"],
        "canonical_hash_mismatch",
    )
    _new_error(
        errors,
        final.get("t06_run_id") == EXPECTED_T06["authoritative_run"]
        and final.get("t06_merge_commit") == EXPECTED_T06["merge_commit"]
        and final.get("t06_reviewed_head") == EXPECTED_T06["reviewed_head"]
        and final.get("t06_scientific_review_id")
        == EXPECTED_T06["scientific_review_id"]
        and final.get("t06_artifact_commit") == EXPECTED_T06["artifact_commit"]
        and final.get("t06_replay_database_sha256") == EXPECTED_T06["duckdb_sha256"],
        "decision_log_mismatch",
    )
    _new_error(
        errors,
        final.get("authoritative_time_fields") == NEW_AUTHORITATIVE_TIMES
        and final.get("non_authoritative_time_fields")
        == ["r2_t06_replayed_transition_ledger.trigger_trade_date"],
        "time_authority_mismatch",
    )
    _new_error(
        errors,
        final.get("allowed_uses") == NEW_ALLOWED_USES
        and final.get("forbidden_reinterpretations") == NEW_FORBIDDEN_REINTERPRETATIONS,
        "forbidden_reinterpretation_mismatch",
    )
    gates = final.get("downstream_gates", {})
    _new_error(
        errors,
        gates.get("R2-T08_allowed_to_start") is False
        and gates.get("R3_allowed_to_start") is False,
        "downstream_gate_violation",
    )
    for name in (
        "state_version_registry",
        "interval_rule_registry",
        "event_state_machine_registry",
        "freeze_decision_log",
    ):
        ref = final.get(name, {})
        _new_error(
            errors,
            set(ref) == {"path", "sha256", "size_bytes"}
            and len(ref.get("sha256", "")) == 64
            and isinstance(ref.get("size_bytes"), int),
            "core_artifact_reference_mismatch",
        )

    manifest = docs.get("output_manifest", {})
    if manifest:
        artifacts = manifest.get("artifacts", [])
        _new_error(
            errors,
            manifest.get("artifact_hash_basis") == "committed_artifact_bytes"
            and manifest.get("artifact_count") == len(artifacts),
            "core_artifact_hash_mismatch",
        )
        for item in artifacts:
            payload = docs.get("artifact_bytes", {}).get(item.get("path"))
            if (
                payload is None
                or _sha256(payload) != item.get("sha256")
                or len(payload) != item.get("size_bytes")
            ):
                errors.append("core_artifact_hash_mismatch")
    if docs.get("registry_reconciliation"):
        _new_error(
            errors,
            docs["registry_reconciliation"].get("status") == "passed"
            and docs["registry_reconciliation"].get("failure_count") == 0,
            "registry_reconciliation_failed",
        )
    if docs.get("forbidden_use_audit"):
        _new_error(
            errors,
            docs["forbidden_use_audit"].get("status") == "passed"
            and docs["forbidden_use_audit"].get("failure_count") == 0,
            "forbidden_field_violation",
        )
    checks = _successor_check_counts(docs)
    errors.extend(key for key, value in checks.items() if value)
    return sorted(set(errors))


def validate_documents(docs: dict[str, Any]) -> list[str]:
    if _is_successor_documents(docs):
        return _validate_successor_documents(docs)
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

    with (output_dir / "r2_state_version_registry.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        reader = csv.DictReader(handle)
        state_rows = list(reader)
        state_header = list(reader.fieldnames or [])
    docs = {
        "state_registry": state_rows,
        "state_registry_header": state_header,
        "interval_registry": load_json("r2_interval_rule_registry.json"),
        "event_registry": load_json("r2_event_state_machine_registry.json"),
        "decision_log": load_json("r2_freeze_decision_log.json"),
        "final_manifest": load_json("r2_final_freeze_manifest.json"),
    }
    optional_json = {
        "supersession_record": "r2_t07_supersession_record.json",
        "source_readiness": "r2_t07_source_readiness.json",
        "input_binding": "r2_t07_input_binding.json",
        "canonical_artifact_binding": "r2_t07_canonical_artifact_binding.json",
        "registry_reconciliation": "r2_t07_registry_reconciliation.json",
        "forbidden_use_audit": "r2_t07_forbidden_use_audit.json",
    }
    for key, name in optional_json.items():
        path = output_dir / name
        if path.exists():
            docs[key] = load_json(name)
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


def _write_successor_audits(
    output_dir: Path, docs: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = docs.get("state_registry", [])
    final = docs.get("final_manifest", {})
    decision = docs.get("decision_log", {})
    selected = [row for row in rows if row.get("freeze_status") == "frozen"]
    checks = [
        ("frozen_version_count", 2, len(selected), "r2_state_version_registry.csv"),
        (
            "W250_independent_version_count",
            0,
            sum("W250" in row.get("state_version_id", "") for row in rows),
            "r2_state_version_registry.csv",
        ),
        (
            "shared_q_independent_version_count",
            0,
            sum(
                "shared" in row.get("source_candidate_cell_id", "").lower()
                for row in rows
            ),
            "r2_state_version_registry.csv",
        ),
        (
            "PCT_parent_product_count",
            0,
            sum("parent" in row.get("state_version_id", "").lower() for row in rows),
            "r2_state_version_registry.csv",
        ),
        (
            "additional_state_version_count",
            0,
            max(0, len(rows) - 2),
            "r2_state_version_registry.csv",
        ),
        (
            "selected_decision_unit_count",
            2,
            decision.get("selected_decision_unit_count"),
            "r2_freeze_decision_log.json",
        ),
        (
            "decision_unit_count",
            4,
            decision.get("decision_unit_count"),
            "r2_freeze_decision_log.json",
        ),
        (
            "rejected_decision_unit_count",
            2,
            decision.get("rejected_decision_unit_count"),
            "r2_freeze_decision_log.json",
        ),
        (
            "strict_core_only_count",
            2,
            decision.get("strict_core_only_count"),
            "r2_freeze_decision_log.json",
        ),
        (
            "warning_mismatch_count",
            0,
            sum(
                row.get("warning_codes")
                != json.dumps(
                    NEW_EXPECTED_WARNINGS.get(row.get("state_line"), []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                for row in rows
            ),
            "r2_state_version_registry.csv",
        ),
        (
            "canonical_hash_mismatch_count",
            0,
            sum(
                final.get(key) != value
                for key, value in {
                    "canonical_daily_state_sha256": EXPECTED_T05["daily_sha256"],
                    "canonical_event_zone_sha256": EXPECTED_T05["event_sha256"],
                    "canonical_event_membership_sha256": EXPECTED_T05[
                        "membership_sha256"
                    ],
                }.items()
            ),
            "r2_final_freeze_manifest.json",
        ),
        (
            "core_artifact_missing_count",
            0,
            _successor_core_artifact_checks(docs)["core_artifact_missing_count"],
            "r2_final_freeze_manifest.json",
        ),
        (
            "core_artifact_path_mismatch_count",
            0,
            _successor_core_artifact_checks(docs)["core_artifact_path_mismatch_count"],
            "r2_final_freeze_manifest.json",
        ),
        (
            "core_artifact_sha256_mismatch_count",
            0,
            _successor_core_artifact_checks(docs)[
                "core_artifact_sha256_mismatch_count"
            ],
            "r2_final_freeze_manifest.json",
        ),
        (
            "core_artifact_size_mismatch_count",
            0,
            _successor_core_artifact_checks(docs)["core_artifact_size_mismatch_count"],
            "r2_final_freeze_manifest.json",
        ),
        (
            "core_artifact_output_manifest_mismatch_count",
            0,
            _successor_core_artifact_checks(docs)[
                "core_artifact_output_manifest_mismatch_count"
            ],
            "r2_t07_output_manifest.json",
        ),
        (
            "core_artifact_hash_mismatch_count",
            0,
            sum(_successor_core_artifact_checks(docs).values()),
            "r2_final_freeze_manifest.json",
        ),
    ]
    reconciliation = []
    for check_id, expected, observed, evidence in checks:
        mismatch = 0 if expected == observed else 1
        reconciliation.append(
            {
                "check_id": check_id,
                "expected": expected,
                "observed": observed,
                "mismatch_count": mismatch,
                "status": "passed" if mismatch == 0 else "failed",
                "evidence_source": evidence,
            }
        )
    write_csv(
        output_dir / "r2_t07_registry_reconciliation.csv",
        reconciliation,
        [
            "check_id",
            "expected",
            "observed",
            "mismatch_count",
            "status",
            "evidence_source",
        ],
    )
    recon_result = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "passed"
        if all(row["status"] == "passed" for row in reconciliation)
        else "failed",
        "failure_count": sum(row["mismatch_count"] for row in reconciliation),
        "checks": reconciliation,
    }
    write_json(output_dir / "r2_t07_registry_reconciliation.json", recon_result)

    forbidden_tokens = {
        "future_return",
        "future_direction",
        "future_volatility",
        "future_path",
        "release_label",
        "precision",
        "recall",
        "backtest",
        "trading_result",
        "pnl",
        "sharpe",
        "target_price",
        "expected_return",
    }
    failures: list[str] = []
    scanned_json: list[str] = []
    scanned_csv: list[str] = []
    scanned_csv_headers: list[str] = []

    def scan(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key).lower()
                if key_text in forbidden_tokens:
                    failures.append(f"forbidden_field_key:{path}.{key}")
                scan(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{path}[{index}]")
        elif isinstance(value, str):
            text = value.lower()
            legal_negative_guard = any(
                marker in text
                for marker in (
                    "no_",
                    "not ",
                    "never ",
                    "forbidden",
                    "without ",
                    "must not",
                    "is not",
                )
            )
            if (
                any(token in text for token in forbidden_tokens)
                and not legal_negative_guard
            ):
                failures.append(f"forbidden_authoritative_claim:{path}")

    for path in sorted(output_dir.glob("*.json")):
        if path.name == "r2_t07_forbidden_use_audit.json":
            continue
        scanned_json.append(path.name)
        scan(json.loads(path.read_text(encoding="utf-8")), path.name)
    for path in sorted(output_dir.glob("*.csv")):
        scanned_csv.append(path.name)
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            scanned_csv_headers.append(f"{path.name}:{','.join(header)}")
            if (
                path.name == "r2_state_version_registry.csv"
                and header != STATE_REGISTRY_HEADER
            ):
                failures.append("unexpected_csv_column:r2_state_version_registry.csv")
            for row_index, row in enumerate(reader, start=2):
                scan(row, f"{path.name}[{row_index}]")
    required_guards = {
        "forbidden_reinterpretations": final.get("forbidden_reinterpretations")
        == NEW_FORBIDDEN_REINTERPRETATIONS,
        "downstream_gates": final.get("downstream_gates")
        == {"R2-T08_allowed_to_start": False, "R3_allowed_to_start": False},
        "time_authority": final.get("non_authoritative_time_fields")
        == ["r2_t06_replayed_transition_ledger.trigger_trade_date"],
        "state_registry_header_closed": docs.get("state_registry_header")
        == STATE_REGISTRY_HEADER,
    }
    failures.extend(
        f"required_forbidden_guard_missing:{key}"
        for key, ok in required_guards.items()
        if not ok
    )
    forbidden_result = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "scanned_json_artifacts": scanned_json,
        "scanned_csv_artifacts": scanned_csv,
        "scanned_csv_headers": scanned_csv_headers,
        "required_guards": required_guards,
    }
    write_json(output_dir / "r2_t07_forbidden_use_audit.json", forbidden_result)
    return reconciliation, forbidden_result


def _write_successor_result_analysis(
    output_dir: Path, docs: dict[str, Any], result: dict[str, Any]
) -> None:
    rows = docs.get("state_registry", [])
    final = docs.get("final_manifest", {})
    interval = docs.get("interval_registry", {})
    event = docs.get("event_registry", {})
    decision = docs.get("decision_log", {})
    core_checks = _successor_core_artifact_checks(docs)
    forbidden_audit = docs.get("forbidden_use_audit", {})
    lines = [
        "# R2-T07 successor independent result analysis",
        "",
        f"- Run: `{output_dir.name}`",
        f"- Execution commit: `{final.get('execution_commit')}`",
        "- Scope: registry/freeze only; no replay performed.",
        f"- Independent validation: `{result['status']}` with `{result['failure_count']}` failures.",
        "",
        "## Frozen state versions",
        "",
        "| state_version_id | line | W | K | qP | qC | qT | qV | d | g | strict core | source cell | strict-core cell | formula binding | R1 row | warnings |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('state_version_id')} | {row.get('state_line')} | {row.get('W')} | {row.get('K')} | {row.get('qP')} | {row.get('qC')} | {row.get('qT')} | {row.get('qV')} | {row.get('d')} | {row.get('g')} | {row.get('strict_core_enabled')} | {row.get('source_candidate_cell_id')} | {row.get('strict_core_source_candidate_cell_id')} | `{row.get('state_formula_binding_sha256')}` | `{row.get('r1_handoff_row_id')}` / `{row.get('r1_handoff_row_sha256')}` | `{row.get('warning_codes')}` |"
        )
    lines.extend(
        [
            "",
            "## Upstream and canonical bindings",
            "",
            f"- T04: `{final.get('t04_run_id')}`; decision `{final.get('t04_decision_hash')}`; freeze decision `{final.get('t04_freeze_decision_hash')}`; freeze plan `{final.get('t04_freeze_plan_hash')}`.",
            f"- T05: `{final.get('t05_run_id')}`; database `{final.get('t05_database_sha256')}`; daily `{final.get('canonical_daily_state_sha256')}` ({final.get('canonical_daily_row_count')} rows); event `{final.get('canonical_event_zone_sha256')}` ({final.get('canonical_event_row_count')} rows); membership `{final.get('canonical_event_membership_sha256')}` ({final.get('canonical_membership_row_count')} rows).",
            f"- T06: `{final.get('t06_run_id')}`; merge `{final.get('t06_merge_commit')}`; reviewed `{final.get('t06_reviewed_head')}`; review `{final.get('t06_scientific_review_id')}`; artifact `{final.get('t06_artifact_commit')}`; replay database `{final.get('t06_replay_database_sha256')}`.",
            f"- Core artifact refs: state registry `{final.get('state_version_registry')}`; interval registry `{final.get('interval_rule_registry')}`; event registry `{final.get('event_state_machine_registry')}`; decision log `{final.get('freeze_decision_log')}`.",
            f"- State registry header ({len(docs.get('state_registry_header', []))} columns): `{docs.get('state_registry_header')}`.",
            f"- Core artifact byte checks: `{core_checks}`; aggregate `{sum(core_checks.values())}`.",
            f"- Full T04 decision units: `{json.dumps(decision.get('decision_units', []), ensure_ascii=False, sort_keys=True)}`.",
            f"- Decision-unit source SHA binding: `{decision.get('user_decision_record_sha256')}`; source path `{decision.get('user_decision_record_path')}`.",
            "",
            "## Rule and consumer contracts",
            "",
            f"- Interval registry `{interval.get('registry_id')}`: K={interval.get('K')}, confirmation backfill={interval.get('confirmation_backfill_allowed')}, d={interval.get('d')} `{interval.get('d_count_unit')}`, g={interval.get('g')} `{interval.get('g_count_unit')}`; hard breaks `{interval.get('hard_break_reasons')}`.",
            f"- Event registry `{event.get('registry_id')}`: states={len(event.get('states', []))}, transitions={len(event.get('transitions', []))}, transition registry SHA `{event.get('transition_registry_sha256')}`.",
            f"- Canonical risk policies: `{event.get('canonical_risk_set_policy')}`.",
            f"- Daily risk-set contract: `{event.get('daily_risk_set_contract')}`.",
            f"- Membership risk-set contract: `{event.get('membership_risk_set_contract')}`.",
            f"- Source-to-canonical aliases: `{event.get('canonical_consumer_mapping', {}).get('source_to_canonical_aliases')}`.",
            f"- Evaluation-time consumer rule: `{event.get('canonical_consumer_mapping', {}).get('evaluation_time')}`.",
            f"- Authoritative times: `{final.get('authoritative_time_fields')}`; non-authoritative: `{final.get('non_authoritative_time_fields')}`.",
            f"- Allowed uses: `{final.get('allowed_uses')}`.",
            f"- Forbidden reinterpretations: `{final.get('forbidden_reinterpretations')}`.",
            "",
            "## Reconciliation and gates",
            "",
            "- Registry reconciliation is computed from the actual registry, decision log and final manifest; no missing-audit passed placeholder is accepted.",
            "- Forbidden-use scan recursively inspected generated JSON keys/values and required negative guards.",
            f"- Forbidden-use scan scope: JSON `{len(forbidden_audit.get('scanned_json_artifacts', []))}`, CSV `{len(forbidden_audit.get('scanned_csv_artifacts', []))}`, CSV headers `{len(forbidden_audit.get('scanned_csv_headers', []))}`.",
            f"- Numeric independent checks: `{json.dumps(result.get('checks', {}), sort_keys=True)}`; failure count is the integer sum.",
            f"- Final downstream gates: `{final.get('downstream_gates')}`.",
            f"- Result: `{result['status']}`; formal task remains author-stage incomplete and scientific review remains pending.",
        ]
    )
    write_markdown(output_dir / "r2_t07_result_analysis.md", "\n".join(lines))


def validate_run(output_dir: Path) -> dict[str, Any]:
    run_id = output_dir.name
    successor = False
    try:
        docs = _read_documents(output_dir)
        successor = _is_successor_documents(docs)
        if successor:
            _write_successor_audits(output_dir, docs)
            docs = _read_documents(output_dir)
        checks = (
            _successor_check_counts(docs)
            if successor
            else {key: 0 for key in SUCCESSOR_CHECK_KEYS}
        )
        errors = validate_documents(docs)
        status = "passed" if not errors and sum(checks.values()) == 0 else "failed"
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        errors = [f"unreadable_artifact:{exc}"]
        checks = {key: 1 for key in SUCCESSOR_CHECK_KEYS}
        status = "failed"
    result = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": status,
        "failure_count": sum(checks.values()) if successor else len(errors),
        "errors": errors,
        "checks": checks if successor else {},
        "summary_checks": {
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
        "anomaly_count": sum(checks.values()) if successor else len(errors),
        "anomalies": errors,
    }
    write_json(output_dir / "r2_t07_anomaly_scan.json", anomaly)
    if successor:
        _write_successor_result_analysis(output_dir, docs, result)
    else:
        write_markdown(
            output_dir / "r2_t07_result_analysis.md",
            f"# R2-T07 independent result analysis\n\nRun `{run_id}` status: `{status}`. The independent validator found {len(errors)} failure(s).\n",
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
    if successor:
        refreshed = _read_documents(output_dir)
        final_errors = validate_documents(refreshed)
        if final_errors:
            result["errors"] = sorted(set(result["errors"] + final_errors))
            result["failure_count"] = sum(_successor_check_counts(refreshed).values())
            result["status"] = "failed"
            write_json(output_dir / "r2_t07_independent_validation.json", result)
            write_json(
                output_dir / "r2_t07_anomaly_scan.json",
                {
                    "task_id": TASK_ID,
                    "run_id": run_id,
                    "status": "failed",
                    "anomaly_count": len(result["errors"]),
                    "anomalies": result["errors"],
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
