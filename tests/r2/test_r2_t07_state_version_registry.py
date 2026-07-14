# ruff: noqa: E501

from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path

from src.r2.r2_t07_committed_artifact_validator import validate_manifest_records
from src.r2.r2_t07_independent_validator import (
    EXPECTED_STATES,
    EXPECTED_T04,
    EXPECTED_T05,
    EXPECTED_T06,
    EXPECTED_TRANSITIONS,
    EXPECTED_VERSIONS,
    EXPECTED_WARNINGS,
    _read_documents,
    validate_documents,
)


def _valid_documents() -> dict:
    rows = [dict(item) for item in EXPECTED_VERSIONS]
    for row in rows:
        row["contract_version"] = (
            "r2_t02_confirmed_event_zone_state_machine_contract.v8"
        )
        row["source_run_id"] = "R2-T05-20260713T154957Z"
        row["freeze_decision_hash"] = EXPECTED_T04["freeze_decision_hash"]
        row["freeze_plan_hash"] = EXPECTED_T04["freeze_plan_hash"]
        row.pop("strict_core_source_candidate_id", None)
    units = []
    for name, disposition, strict in (
        ("S_PCT×W120", "selected", True),
        ("S_PCT×W250", "reject_pair", False),
        ("S_PCVT×W120", "selected", True),
        ("S_PCVT×W250", "reject_pair", False),
    ):
        unit = {
            "decision_unit": name,
            "pair_disposition": disposition,
            "strict_core_enabled": strict,
            "accepted_warnings": sorted(EXPECTED_WARNINGS.get(name, set())),
        }
        units.append(unit)
    return {
        "state_registry": rows,
        "interval_registry": {
            "contract_version": "r2_t02_confirmed_event_zone_state_machine_contract.v8",
            "rules": {
                "K": 3,
                "d": "selected d=2 confirmed trading days; qualification occurs on the second confirmed day",
                "g": "selected g=1 cumulative eligible valid raw-false gap days after a qualified component",
                "confirmation": "third consecutive eligible valid raw-true trading row is first confirmed; no backfill",
                "raw_false_gap": "g+1 raw-false gap day is visible and causes irreversible finalization",
                "preconfirmation_raw_true": "does not increment or reset g and is not a raw-false bridge",
                "unqualified_reentry": "an unqualified confirmed reentry blocks merge and is not swallowed as a false gap",
                "release_claim_allowed": False,
            },
        },
        "event_registry": {
            "states": EXPECTED_STATES,
            "transitions": copy.deepcopy(EXPECTED_TRANSITIONS),
            "event_identity_policy": {
                "canonical_selected_state_event_id_generated": False,
                "cross_state_line_identity_must_remain_distinct": True,
            },
            "time_semantics": {
                "authoritative": ["confirmation_time"],
                "non_authoritative": [
                    "r2_t06_replayed_transition_ledger.trigger_trade_date"
                ],
                "non_authoritative_fallback": "event start date only when no authoritative finalization or membership time is available; never a causal transition timestamp",
            },
            "risk_set_policy": {
                "qualified_event_risk_set_eligible_rule": "state_risk_set_eligible=true and component_qualified_as_of=true and event_zone_member=true and is_raw_false_bridge=false and is_preconfirmation_gap=false"
            },
        },
        "decision_log": {
            "decision_hash": EXPECTED_T04["decision_hash"],
            "freeze_decision_hash": EXPECTED_T04["freeze_decision_hash"],
            "freeze_plan_hash": EXPECTED_T04["freeze_plan_hash"],
            "automatic_recommendation_authoritative": False,
            "selection_path": "explicit_user_decision_not_automatic_recommendation",
            "decision_units": units,
            "selected_version_count": 2,
            "strict_core_only_count": 2,
            "rejected_decision_unit_count": 2,
        },
        "final_manifest": {
            "task_id": "R2-T07",
            "status": "completed",
            "registry_freeze_only": True,
            "replay_performed": False,
            "frozen_version_count": 2,
            "downstream_gates": {
                "R2-T08_allowed_to_start": False,
                "R3_allowed_to_start": False,
            },
            "upstream_bindings": {
                "t04": dict(EXPECTED_T04),
                "t05": dict(EXPECTED_T05),
                "t06": {
                    "merge_commit": EXPECTED_T06["merge_commit"],
                    "reviewed_head": EXPECTED_T06["reviewed_head"],
                    "scientific_review_id": EXPECTED_T06["scientific_review_id"],
                    "compatibility_review_id": EXPECTED_T06["compatibility_review_id"],
                    "authoritative_run": EXPECTED_T06["authoritative_run"],
                    "formal_execution_commit": EXPECTED_T06["execution_commit"],
                    "validator_commit": EXPECTED_T06["validator_commit"],
                    "artifact_commit": EXPECTED_T06["artifact_commit"],
                    "duckdb_sha256": EXPECTED_T06["duckdb_sha256"],
                },
            },
        },
    }


class TestR2T07MutationGates(unittest.TestCase):
    def assert_fails(self, mutate, expected_code: str) -> None:
        docs = _valid_documents()
        mutate(docs)
        errors = validate_documents(docs)
        self.assertIn(expected_code, errors)

    def test_third_frozen_version(self):
        self.assert_fails(
            lambda d: d["state_registry"].append(dict(d["state_registry"][0])),
            "version_cardinality",
        )

    def test_revive_w250(self):
        self.assert_fails(
            lambda d: d["state_registry"].append(
                {"state_version_id": "r2_s_pct_W250_revived"}
            ),
            "version_cardinality",
        )

    def test_shared_q_independent_version(self):
        self.assert_fails(
            lambda d: d["state_registry"][0].__setitem__(
                "source_candidate_cell_id", "r2_s_pct_w120_q20_shared__d2__g1"
            ),
            "source_candidate_cell_id_mismatch:0",
        )

    def test_add_pct_parent(self):
        self.assert_fails(
            lambda d: d["state_registry"].append(
                {"state_version_id": "pct_parent_product"}
            ),
            "version_cardinality",
        )

    def test_modify_state_version_id(self):
        self.assert_fails(
            lambda d: d["state_registry"][0].__setitem__("state_version_id", "changed"),
            "state_version_id_mismatch:0",
        )

    def test_modify_q_vector(self):
        self.assert_fails(
            lambda d: d["state_registry"][0].__setitem__("qT", "0.2"), "qT_mismatch:0"
        )

    def test_modify_k_d_g(self):
        self.assert_fails(
            lambda d: d["state_registry"][0].__setitem__("K", "2"), "K_mismatch:0"
        )

    def test_cross_state_strict_core_pair(self):
        self.assert_fails(
            lambda d: d["state_registry"][0].__setitem__(
                "strict_core_source_candidate_cell_id",
                "r2_s_pcvt_w120_q20_shared__d2__g1",
            ),
            "strict_core_source_candidate_cell_id_mismatch:0",
        )

    def test_delete_accepted_warning(self):
        self.assert_fails(
            lambda d: d["decision_log"]["decision_units"][0]["accepted_warnings"].pop(),
            "accepted_warnings:S_PCT×W120",
        )

    def test_selection_path_not_user_authoritative(self):
        self.assert_fails(
            lambda d: d["decision_log"].__setitem__("selection_path", "automatic"),
            "selection_path_authority",
        )

    def test_modify_transition_registry(self):
        self.assert_fails(
            lambda d: d["event_registry"]["transitions"].pop(),
            "transition_registry_mismatch",
        )

    def test_modify_event_id_revision_policy(self):
        self.assert_fails(
            lambda d: d["event_registry"]["event_identity_policy"].__setitem__(
                "canonical_selected_state_event_id_generated", True
            ),
            "event_id_generation_policy",
        )

    def test_modify_canonical_semantic_hash(self):
        self.assert_fails(
            lambda d: d["final_manifest"]["upstream_bindings"]["t05"].__setitem__(
                "daily_sha256", "changed"
            ),
            "final_t05_binding:daily_sha256",
        )

    def test_modify_t04_decision_hash(self):
        self.assert_fails(
            lambda d: d["decision_log"].__setitem__("decision_hash", "changed"),
            "decision_hash_mismatch",
        )

    def test_delete_rejected_decision_unit(self):
        self.assert_fails(
            lambda d: d["decision_log"]["decision_units"].pop(),
            "decision_unit_cardinality",
        )

    def test_automatic_recommendation_authoritative(self):
        self.assert_fails(
            lambda d: d["decision_log"].__setitem__(
                "automatic_recommendation_authoritative", True
            ),
            "automatic_recommendation_authority",
        )

    def test_trigger_trade_date_authoritative(self):
        self.assert_fails(
            lambda d: d["event_registry"]["time_semantics"].__setitem__(
                "non_authoritative", []
            ),
            "trigger_trade_date_authority",
        )

    def test_confirmed_exit_as_release(self):
        self.assert_fails(
            lambda d: d["interval_registry"]["rules"].__setitem__(
                "release_claim_allowed", True
            ),
            "confirmed_exit_release_claim",
        )

    def test_event_zone_as_risk_set(self):
        self.assert_fails(
            lambda d: d["event_registry"]["risk_set_policy"].__setitem__(
                "qualified_event_risk_set_eligible_rule", "event_zone_member=true"
            ),
            "event_zone_as_risk_set",
        )

    def test_r3_gate_true(self):
        self.assert_fails(
            lambda d: d["final_manifest"]["downstream_gates"].__setitem__(
                "R3_allowed_to_start", True
            ),
            "R3_gate",
        )

    def test_manifest_referenced_file_hash_mismatch(self):
        docs = _valid_documents()
        payload = b"committed payload"
        docs["output_manifest"] = {
            "artifact_hash_basis": "committed_artifact_bytes",
            "artifact_count": 1,
            "artifacts": [{"path": "x", "sha256": "wrong", "size_bytes": len(payload)}],
        }
        docs["artifact_bytes"] = {"x": payload}
        self.assertIn("manifest_hash:x", validate_documents(docs))

    def test_committed_artifact_bytes_vs_manifest_mismatch(self):
        payload = b"committed payload"
        item = {
            "sha256": hashlib.sha256(b"different").hexdigest(),
            "size_bytes": len(payload),
        }
        self.assertIn(
            "committed_byte_sha256_mismatch", validate_manifest_records(item, payload)
        )

    def test_state_line_mutation(self):
        self.assert_fails(
            lambda d: d["state_registry"][1].__setitem__("state_line", "S_PCT"),
            "state_line_mismatch:1",
        )

    def test_window_mutation(self):
        self.assert_fails(
            lambda d: d["state_registry"][0].__setitem__("W", "250"), "W_mismatch:0"
        )

    def test_downstream_t08_gate_true(self):
        self.assert_fails(
            lambda d: d["final_manifest"]["downstream_gates"].__setitem__(
                "R2-T08_allowed_to_start", True
            ),
            "R2-T08_gate",
        )


class TestR2T07ZeroVersion(unittest.TestCase):
    def test_valid_zero_version_synthetic(self):
        docs = {
            "state_registry": [],
            "final_manifest": {
                "frozen_version_count": 0,
                "status": "completed_no_frozen_version",
                "downstream_gates": {
                    "R2-T08_allowed_to_start": False,
                    "R3_allowed_to_start": False,
                },
            },
        }
        self.assertEqual(validate_documents(docs), [])


def _successor_fixture() -> dict | None:
    root = Path(__file__).resolve().parents[2]
    runs = sorted(
        (root / "data/generated/r2/r2_t07").glob(
            "R2-T07-*/r2_final_freeze_manifest.json"
        )
    )
    runs = [path for path in runs if "20260714T015043Z" not in path.as_posix()]
    return _read_documents(runs[-1].parent) if runs else None


@unittest.skipUnless(
    _successor_fixture() is not None,
    "successor formal artifacts are added after the execution commit",
)
class TestR2T07SuccessorMutationGates(unittest.TestCase):
    def assert_successor_fails(self, mutate, code: str) -> None:
        docs = copy.deepcopy(_successor_fixture())
        mutate(docs)
        self.assertIn(code, validate_documents(docs))

    def test_header_mutation(self):
        self.assert_successor_fails(
            lambda d: d.__setitem__(
                "state_registry_header", d["state_registry_header"][:-1]
            ),
            "state_registry_header_mismatch",
        )

    def test_row_cardinality_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"].pop(), "state_registry_row_mismatch"
        )

    def test_version_id_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("state_version_id", "changed"),
            "frozen_version_id_mismatch",
        )

    def test_candidate_cell_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__(
                "source_candidate_cell_id", "changed"
            ),
            "state_registry_row_mismatch:source_candidate_cell_id:0",
        )

    def test_strict_core_pair_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__(
                "strict_core_source_candidate_cell_id", "changed"
            ),
            "state_registry_row_mismatch:strict_core_source_candidate_cell_id:0",
        )

    def test_state_line_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][1].__setitem__("state_line", "S_PCT"),
            "state_registry_row_mismatch:state_line:1",
        )

    def test_window_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("W", "250"),
            "state_registry_row_mismatch:W:0",
        )

    def test_k_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("K", "2"),
            "state_registry_row_mismatch:K:0",
        )

    def test_q_vector_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("qT", "0.2"),
            "state_registry_row_mismatch:qT:0",
        )

    def test_d_g_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("d", "3"),
            "state_registry_row_mismatch:d:0",
        )

    def test_formula_binding_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__(
                "state_formula_binding_sha256", "changed"
            ),
            "state_registry_formula_binding_mismatch",
        )

    def test_r1_handoff_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__(
                "r1_handoff_row_sha256", "changed"
            ),
            "state_registry_r1_handoff_mismatch",
        )

    def test_warning_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("warning_codes", "[]"),
            "state_registry_warning_mismatch",
        )

    def test_allowed_use_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("allowed_uses", "[]"),
            "state_registry_use_policy_mismatch",
        )

    def test_forbidden_use_mutation(self):
        self.assert_successor_fails(
            lambda d: d["state_registry"][0].__setitem__("forbidden_uses", "[]"),
            "state_registry_use_policy_mismatch",
        )

    def test_interval_cardinality_mutation(self):
        self.assert_successor_fails(
            lambda d: d["interval_registry"].__setitem__("K", 2),
            "interval_registry_mismatch",
        )

    def test_interval_d_operator_mutation(self):
        self.assert_successor_fails(
            lambda d: d["interval_registry"].__setitem__("d_operator", "="),
            "interval_registry_mismatch",
        )

    def test_interval_hard_break_mutation(self):
        self.assert_successor_fails(
            lambda d: d["interval_registry"]["hard_break_reasons"].pop(),
            "interval_registry_mismatch",
        )

    def test_transition_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["transitions"].pop(),
            "event_state_registry_mismatch",
        )

    def test_event_identity_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["event_identity_policy"].__setitem__(
                "reentry_does_not_change_event_id", False
            ),
            "zone_revision_policy_mismatch",
        )

    def test_revision_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["zone_revision_policy"].__setitem__(
                "no_cross_state_version_merge", False
            ),
            "zone_revision_policy_mismatch",
        )

    def test_canonical_mapping_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["canonical_consumer_mapping"].__setitem__(
                "state_risk_set_eligible", "event.member"
            ),
            "canonical_field_mapping_mismatch",
        )

    def test_risk_policy_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["canonical_risk_set_policy"].__setitem__(
                "state_risk_set_eligible", "event-derived"
            ),
            "canonical_risk_set_policy_mismatch",
        )

    def test_time_authority_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["time_semantics"].__setitem__(
                "trigger_trade_date_is_causal", True
            ),
            "time_authority_mismatch",
        )

    def test_decision_count_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"].__setitem__("decision_unit_count", 3),
            "decision_unit_count_mismatch",
        )

    def test_rejected_count_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"].__setitem__("rejected_decision_unit_count", 1),
            "decision_unit_count_mismatch",
        )

    def test_t04_binding_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"].__setitem__(
                "t04_freeze_plan_hash", "changed"
            ),
            "decision_log_mismatch",
        )

    def test_canonical_hash_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"].__setitem__(
                "canonical_daily_state_sha256", "changed"
            ),
            "canonical_hash_mismatch",
        )

    def test_core_reference_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"]["state_version_registry"].__setitem__(
                "sha256", "changed"
            ),
            "core_artifact_reference_mismatch",
        )

    def test_forbidden_reinterpretation_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"].__setitem__(
                "forbidden_reinterpretations", []
            ),
            "forbidden_reinterpretation_mismatch",
        )

    def test_downstream_gate_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"]["downstream_gates"].__setitem__(
                "R3_allowed_to_start", True
            ),
            "downstream_gate_violation",
        )

    def test_numeric_checks_are_closed_and_zero(self):
        from src.r2.r2_t07_independent_validator import (
            SUCCESSOR_CHECK_KEYS,
            _successor_check_counts,
        )

        docs = _successor_fixture()
        if any(_successor_check_counts(docs).values()):
            self.skipTest(
                "pre-revision successor artifacts are not the current fixture"
            )
        self.assertEqual(
            _successor_check_counts(docs), {key: 0 for key in SUCCESSOR_CHECK_KEYS}
        )

    def test_core_valid_format_sha_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"]["state_version_registry"].__setitem__(
                "sha256", "0" * 64
            ),
            "core_artifact_sha256_mismatch_count",
        )

    def test_core_size_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"]["interval_rule_registry"].__setitem__(
                "size_bytes",
                d["final_manifest"]["interval_rule_registry"]["size_bytes"] + 1,
            ),
            "core_artifact_size_mismatch_count",
        )

    def test_core_path_mutation(self):
        self.assert_successor_fails(
            lambda d: d["final_manifest"]["event_state_machine_registry"].__setitem__(
                "path",
                "data/generated/r2/r2_t07/other/r2_event_state_machine_registry.json",
            ),
            "core_artifact_path_mismatch_count",
        )

    def test_core_output_manifest_mutation(self):
        def mutate(d):
            for item in d["output_manifest"]["artifacts"]:
                if item["path"].endswith("r2_freeze_decision_log.json"):
                    item["sha256"] = "0" * 64

        self.assert_successor_fails(
            mutate, "core_artifact_output_manifest_mismatch_count"
        )

    def test_core_actual_bytes_mutation(self):
        def mutate(d):
            path = d["final_manifest"]["state_version_registry"]["path"]
            d["artifact_bytes"][path] = b"changed committed bytes"

        self.assert_successor_fails(mutate, "core_artifact_sha256_mismatch_count")

    def test_core_refs_swapped(self):
        def mutate(d):
            left = d["final_manifest"]["state_version_registry"]
            right = d["final_manifest"]["interval_rule_registry"]
            d["final_manifest"]["state_version_registry"] = right
            d["final_manifest"]["interval_rule_registry"] = left

        self.assert_successor_fails(mutate, "core_artifact_path_mismatch_count")

    def test_core_output_manifest_missing_core(self):
        self.assert_successor_fails(
            lambda d: d["output_manifest"].__setitem__(
                "artifacts",
                [
                    item
                    for item in d["output_manifest"]["artifacts"]
                    if not item["path"].endswith("r2_state_version_registry.csv")
                ],
            ),
            "core_artifact_missing_count",
        )

    def test_daily_consumer_formula_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]
            .setdefault("daily_risk_set_contract", {"forbidden_derivation": []})[
                "forbidden_derivation"
            ]
            .append("event_zone_member"),
            "canonical_risk_set_policy_mismatch",
        )

    def test_membership_consumer_source_alias_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]
            .setdefault(
                "membership_risk_set_contract",
                {"audit_formula": {"all_of": ["x"], "all_false": ["y"]}},
            )["audit_formula"]["all_of"]
            .__setitem__(0, "is_raw_false_bridge"),
            "canonical_risk_set_policy_mismatch",
        )

    def test_membership_consumer_unqualified_reentry_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]
            .setdefault(
                "membership_risk_set_contract",
                {"audit_formula": {"all_of": ["x"], "all_false": ["y"]}},
            )["audit_formula"]["all_false"]
            .pop(),
            "canonical_risk_set_policy_mismatch",
        )

    def test_evaluation_rule_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["canonical_consumer_mapping"][
                "evaluation_time"
            ].__setitem__("consumer_rule", "use daily.available_time"),
            "canonical_field_mapping_mismatch",
        )

    def test_alias_nonexistent_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["canonical_consumer_mapping"]
            .setdefault("source_to_canonical_aliases", {})
            .__setitem__("is_raw_false_bridge", "does_not_exist"),
            "canonical_field_mapping_mismatch",
        )

    def test_qualified_risk_event_member_mutation(self):
        self.assert_successor_fails(
            lambda d: d["event_registry"]["canonical_risk_set_policy"].__setitem__(
                "qualified_event_risk_set_eligible", "event_zone_member"
            ),
            "canonical_risk_set_policy_mismatch",
        )

    def test_decision_override_justification_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].pop(
                "override_justification", None
            ),
            "decision_log_mismatch",
        )

    def test_decision_evidence_refs_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].pop("evidence_refs", None),
            "decision_log_mismatch",
        )

    def test_decision_rejected_alternatives_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].pop(
                "rejected_alternatives", None
            ),
            "decision_log_mismatch",
        )

    def test_decision_selected_d_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].__setitem__(
                "selected_d", 3
            ),
            "decision_log_mismatch",
        )

    def test_decision_primary_reason_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].pop(
                "primary_reason_code", None
            ),
            "decision_log_mismatch",
        )

    def test_decision_source_hash_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].__setitem__(
                "source_decision_unit_sha256", "0" * 64
            ),
            "decision_log_mismatch",
        )

    def test_decision_delete_w250_unit_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"].pop(),
            "decision_unit_count_mismatch",
        )

    def test_decision_auto_recommendation_authoritative_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].__setitem__(
                "automatic_recommendation_authoritative", True
            ),
            "decision_log_mismatch",
        )

    def test_decision_tradeoff_mutation(self):
        self.assert_successor_fails(
            lambda d: d["decision_log"]["decision_units"][0].pop(
                "accepted_event_zone_tradeoffs", None
            ),
            "decision_log_mismatch",
        )


if __name__ == "__main__":
    unittest.main()
