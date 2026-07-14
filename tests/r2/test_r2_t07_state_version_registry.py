# ruff: noqa: E501

from __future__ import annotations

import copy
import hashlib
import unittest

from src.r2.r2_t07_committed_artifact_validator import validate_manifest_records
from src.r2.r2_t07_independent_validator import (
    EXPECTED_STATES,
    EXPECTED_T04,
    EXPECTED_T05,
    EXPECTED_T06,
    EXPECTED_TRANSITIONS,
    EXPECTED_VERSIONS,
    EXPECTED_WARNINGS,
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


if __name__ == "__main__":
    unittest.main()
