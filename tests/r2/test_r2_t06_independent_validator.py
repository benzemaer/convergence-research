from __future__ import annotations

import copy
import unittest
from pathlib import Path

from src.r2.r2_t06_source_trigger_oracle import (
    OracleBundle,
    compare_source_oracle,
)

ROOT = Path(__file__).resolve().parents[2]


def _base_bundle() -> OracleBundle:
    event = {
        "state_version_id": "state",
        "event_id": "event",
        "security_id": "S1",
        "first_component_start_date": "2020-01-01",
        "first_qualification_time": "2020-01-02 15:00:00+08:00",
        "last_confirmed_end_date": "2020-01-04",
        "last_exit_observation_time": "2020-01-05 15:00:00+08:00",
        "zone_finalization_time": "2020-01-05 15:00:00+08:00",
        "zone_status": "FINALIZED_WITH_QUALITY_BREAK",
        "exit_reason": "quality_break",
        "left_censored": False,
        "right_censored": False,
        "component_interval_count": 2,
        "bridge_count": 1,
        "bridged_gap_days": 1,
        "zone_confirmed_day_count": 4,
        "zone_trading_span": 6,
        "confirmed_density": 4 / 6,
        "bridged_gap_ratio": 1 / 6,
        "zone_revision_count": 2,
    }
    memberships = [
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "trade_date": "2020-01-01",
            "confirmed_state": True,
            "component_member": True,
            "retrospective_component_member": True,
            "component_qualified_as_of": False,
            "event_zone_member": True,
            "is_prequalification_confirmed_day": True,
            "is_bridged_gap": False,
            "is_unqualified_reentry_day": False,
            "event_status_as_of": "COMPONENT_FORMING",
            "zone_revision": 0,
            "membership_available_time": "2020-01-02 15:00:00+08:00",
            "state_risk_set_eligible": True,
            "qualified_event_risk_set_eligible": False,
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "trade_date": "2020-01-02",
            "confirmed_state": True,
            "component_member": True,
            "retrospective_component_member": True,
            "component_qualified_as_of": True,
            "event_zone_member": True,
            "is_prequalification_confirmed_day": False,
            "is_bridged_gap": False,
            "is_unqualified_reentry_day": False,
            "event_status_as_of": "QUALIFIED_ACTIVE",
            "zone_revision": 0,
            "membership_available_time": "2020-01-02 15:00:00+08:00",
            "state_risk_set_eligible": True,
            "qualified_event_risk_set_eligible": True,
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "trade_date": "2020-01-03",
            "confirmed_state": False,
            "component_member": False,
            "retrospective_component_member": False,
            "component_qualified_as_of": False,
            "event_zone_member": True,
            "is_prequalification_confirmed_day": False,
            "is_bridged_gap": True,
            "is_unqualified_reentry_day": False,
            "event_status_as_of": "GAP_PENDING",
            "zone_revision": 0,
            "membership_available_time": "2020-01-04 15:00:00+08:00",
            "state_risk_set_eligible": False,
            "qualified_event_risk_set_eligible": False,
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "trade_date": "2020-01-04",
            "confirmed_state": True,
            "component_member": True,
            "retrospective_component_member": True,
            "component_qualified_as_of": True,
            "event_zone_member": True,
            "is_prequalification_confirmed_day": False,
            "is_bridged_gap": False,
            "is_unqualified_reentry_day": False,
            "event_status_as_of": "QUALIFIED_ACTIVE",
            "zone_revision": 1,
            "membership_available_time": "2020-01-04 15:00:00+08:00",
            "state_risk_set_eligible": True,
            "qualified_event_risk_set_eligible": True,
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "trade_date": "2020-01-05",
            "confirmed_state": False,
            "component_member": False,
            "retrospective_component_member": False,
            "component_qualified_as_of": False,
            "event_zone_member": False,
            "is_prequalification_confirmed_day": False,
            "is_bridged_gap": False,
            "is_unqualified_reentry_day": False,
            "event_status_as_of": "FINALIZED_WITH_QUALITY_BREAK",
            "zone_revision": 1,
            "membership_available_time": "2020-01-05 15:00:00+08:00",
            "state_risk_set_eligible": False,
            "qualified_event_risk_set_eligible": False,
        },
    ]
    transitions = [
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "from_state": "COMPONENT_FORMING",
            "to_state": "QUALIFIED_ACTIVE",
            "reason_code": "d_qualification",
            "trigger_trade_date": "2020-01-01",
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "from_state": "QUALIFIED_ACTIVE",
            "to_state": "GAP_PENDING",
            "reason_code": "gap_pending",
            "trigger_trade_date": "2020-01-01",
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "from_state": "GAP_PENDING",
            "to_state": "REENTRY_PENDING_QUALIFICATION",
            "reason_code": "reentry_pending",
            "trigger_trade_date": "2020-01-01",
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "from_state": "REENTRY_PENDING_QUALIFICATION",
            "to_state": "QUALIFIED_ACTIVE",
            "reason_code": "reentry_reaches_d_merge",
            "trigger_trade_date": "2020-01-01",
        },
        {
            "state_version_id": "state",
            "event_id": "event",
            "security_id": "S1",
            "from_state": "GAP_PENDING",
            "to_state": "FINALIZED_WITH_QUALITY_BREAK",
            "reason_code": "quality_break",
            "trigger_trade_date": "2020-01-01",
        },
    ]
    return OracleBundle(
        events=[event],
        memberships=memberships,
        transitions=transitions,
        accepted_reentry_count=1,
        unqualified_reentry_count=1,
        quality_break_count=1,
        right_censor_count=0,
    )


class SourceTriggerMutationTest(unittest.TestCase):
    def _assert_mutation(self, check: str, mutate) -> None:
        expected = _base_bundle()
        actual = copy.deepcopy(expected)
        mutate(actual)
        checks = compare_source_oracle(expected, actual)
        self.assertGreater(checks[check], 0, check)

    def test_g_plus_one_finalization_delayed(self) -> None:
        self._assert_mutation(
            "source_trigger_finalization_time_mismatch",
            lambda bundle: bundle.events[0].__setitem__(
                "zone_finalization_time", "2020-01-06 15:00:00+08:00"
            ),
        )

    def test_g_plus_one_finalization_advanced(self) -> None:
        self._assert_mutation(
            "source_trigger_finalization_time_mismatch",
            lambda bundle: bundle.events[0].__setitem__(
                "zone_finalization_time", "2020-01-04 15:00:00+08:00"
            ),
        )

    def test_hard_break_merges_later_component(self) -> None:
        self._assert_mutation(
            "source_trigger_maximal_partition_mismatch",
            lambda bundle: bundle.events[0].__setitem__("component_interval_count", 3),
        )

    def test_accepted_reentry_first_day_is_qualified(self) -> None:
        self._assert_mutation(
            "source_trigger_membership_flag_mismatch",
            lambda bundle: bundle.memberships[2].__setitem__(
                "component_qualified_as_of", True
            ),
        )

    def test_accepted_reentry_d_day_not_merged(self) -> None:
        self._assert_mutation(
            "source_trigger_accepted_reentry_mismatch",
            lambda bundle: setattr(bundle, "accepted_reentry_count", 0),
        )

    def test_unqualified_reentry_is_merged(self) -> None:
        self._assert_mutation(
            "source_trigger_unqualified_reentry_mismatch",
            lambda bundle: setattr(bundle, "unqualified_reentry_count", 0),
        )

    def test_unqualified_reentry_is_marked_bridge(self) -> None:
        self._assert_mutation(
            "source_trigger_membership_flag_mismatch",
            lambda bundle: bundle.memberships[4].__setitem__("is_bridged_gap", True),
        )

    def test_bridge_availability_is_backfilled(self) -> None:
        self._assert_mutation(
            "source_trigger_membership_availability_mismatch",
            lambda bundle: bundle.memberships[2].__setitem__(
                "membership_available_time", "2020-01-02 15:00:00+08:00"
            ),
        )

    def test_preconfirmation_row_is_marked_bridge(self) -> None:
        self._assert_mutation(
            "source_trigger_membership_flag_mismatch",
            lambda bundle: bundle.memberships[0].__setitem__("is_bridged_gap", True),
        )

    def test_right_censored_zone_has_fake_finalization(self) -> None:
        def mutate(bundle: OracleBundle) -> None:
            bundle.events[0]["right_censored"] = True
            bundle.events[0]["zone_status"] = "RIGHT_CENSORED"
            bundle.events[0]["zone_finalization_time"] = None
            bundle.right_censor_count = 1

        self._assert_mutation("source_trigger_right_censor_mismatch", mutate)

    def test_quality_break_is_marked_natural_exit(self) -> None:
        def mutate(bundle: OracleBundle) -> None:
            bundle.events[0]["zone_status"] = "FINALIZED"
            bundle.events[0]["exit_reason"] = "raw_false_gap_exceeds_g"
            bundle.quality_break_count = 0

        self._assert_mutation("source_trigger_quality_break_mismatch", mutate)

    def test_maximal_event_is_split(self) -> None:
        def mutate(bundle: OracleBundle) -> None:
            second = copy.deepcopy(bundle.events[0])
            second["event_id"] = "event-2"
            bundle.events.append(second)

        self._assert_mutation("source_trigger_event_partition_mismatch", mutate)

    def test_separate_events_are_merged(self) -> None:
        expected = _base_bundle()
        second = copy.deepcopy(expected.events[0])
        second["event_id"] = "event-2"
        expected.events.append(second)
        actual = _base_bundle()
        checks = compare_source_oracle(expected, actual)
        self.assertGreater(checks["source_trigger_event_partition_mismatch"], 0)

    def test_transition_trigger_date_changes(self) -> None:
        self._assert_mutation(
            "source_trigger_transition_time_mismatch",
            lambda bundle: bundle.transitions[0].__setitem__(
                "trigger_trade_date", "2020-01-02"
            ),
        )

    def test_terminal_membership_availability_changes(self) -> None:
        self._assert_mutation(
            "source_trigger_membership_availability_mismatch",
            lambda bundle: bundle.memberships[4].__setitem__(
                "membership_available_time", "2020-01-04 15:00:00+08:00"
            ),
        )

    def test_zone_revision_changes(self) -> None:
        self._assert_mutation(
            "source_trigger_membership_flag_mismatch",
            lambda bundle: bundle.memberships[3].__setitem__("zone_revision", 0),
        )

    def test_oracle_does_not_import_production_fsm(self) -> None:
        source = (ROOT / "src/r2/r2_t06_source_trigger_oracle.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "r2_t06_independent_fsm",
            "r2_t06_dual_state_machine_replay",
            "r2_t02_protocol_freeze",
            "r2_t03_event_zone_scan",
            "r2_t05_canonical_materialization",
        ):
            self.assertNotIn(f"import {forbidden}", source)


if __name__ == "__main__":
    unittest.main()
