import json
import tempfile
import unittest
from pathlib import Path

from src.r2 import r2_t02_independent_validator as independent
from src.r2 import r2_t02_premerge_full_evidence as premerge
from src.r2 import r2_t02_protocol_freeze as r2_t02

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT / "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v8.json"
)
RUN_DIR = ROOT / "data/generated/r2/r2_t02/R2-T02-20260712T1700Z"
SHORTLIST_PATH = (
    ROOT
    / "data/generated/r2/r2_t01/R2-T01-20260712T0020Z"
    / "r2_t01_shortlist_registry.csv"
)


class R2T02ProtocolFreezeTest(unittest.TestCase):
    def test_config_freezes_author_stage_scope(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(config["task_type"], "protocol_freeze")
        self.assertEqual(config["candidate_contract"]["primary_cell_count"], 36)
        self.assertEqual(
            config["candidate_contract"]["shared_q_sidecar_cell_count"], 36
        )
        self.assertFalse(config["candidate_contract"]["actual_scan_executed"])
        self.assertFalse(config["author_stage_gate_state"]["formal_task_completed"])
        self.assertFalse(config["author_stage_gate_state"]["R2-T03_allowed_to_start"])

    def test_t03_registry_is_36_primary_36_sidecar_contract_only(self):
        shortlist = r2_t02.read_csv(SHORTLIST_PATH)
        rows = r2_t02.t03_cell_registry(shortlist)
        self.assertEqual(len(rows), 72)
        self.assertEqual(sum(row["candidate_role"] == "primary" for row in rows), 36)
        self.assertEqual(
            sum(row["candidate_role"] == "strict_core_reference" for row in rows), 36
        )
        self.assertTrue(all(row["actual_scan_executed"] is False for row in rows))
        self.assertTrue(
            all(row["execution_status"] == "not_executed_contract_only" for row in rows)
        )

    def test_state_machine_replay_enforces_k3_no_backfill(self):
        rows = [
            r2_t02.DailyInput(
                "S1", "2026-01-02", "2026-01-02T15:01:00+08:00", True, "valid", True
            ),
            r2_t02.DailyInput(
                "S1", "2026-01-03", "2026-01-03T15:01:00+08:00", True, "valid", True
            ),
            r2_t02.DailyInput(
                "S1", "2026-01-04", "2026-01-04T15:01:00+08:00", True, "valid", True
            ),
        ]
        timeline, ledger = r2_t02.replay_confirmation(
            rows, ["2026-01-02", "2026-01-03", "2026-01-04"]
        )
        self.assertEqual(
            [row["confirmed_state"] for row in timeline], [False, False, True]
        )
        self.assertEqual(ledger[0]["reason_code"], "k3_confirmation")

    def test_missing_expected_row_fails_closed(self):
        rows = [
            r2_t02.DailyInput(
                "S1", "2026-01-02", "2026-01-02T15:01:00+08:00", True, "valid", True
            )
        ]
        with self.assertRaises(r2_t02.MissingExpectedRowError):
            r2_t02.replay_confirmation(rows, ["2026-01-02", "2026-01-03"])

    def test_k3_g0_does_not_merge_after_raw_false_exit(self):
        timeline, intervals, _components, zones, ledger = self._run_rows(
            [True, True, True, False, True, True, True], d=1, g=0
        )
        self.assertEqual(len(zones), 2)
        self.assertEqual(zones[0]["component_count"], 1)
        self.assertEqual(
            zones[0]["zone_finalization_time"], timeline[3]["available_time"]
        )
        self.assertIn("raw_false_gap_exceeds_g", [row["reason_code"] for row in ledger])
        self.assertEqual(len(intervals), 2)

    def test_k3_g1_merges_one_raw_false_and_two_preconfirmation_rows(self):
        _timeline, _intervals, _components, zones, _ledger = self._run_rows(
            [True, True, True, False, True, True, True], d=1, g=1
        )
        zone = zones[0]
        members = zone["membership_rows"]
        self.assertEqual(zone["component_count"], 2)
        self.assertEqual(zone["raw_false_bridged_day_count"], 1)
        self.assertEqual(zone["preconfirmation_gap_day_count"], 2)
        self.assertEqual(zone["total_nonconfirmed_gap_day_count"], 3)
        self.assertEqual(sum(row["is_raw_false_bridge"] for row in members), 1)
        self.assertEqual(sum(row["is_preconfirmation_gap"] for row in members), 2)
        self.assertFalse(
            any(
                row["is_bridged_gap"]
                for row in members
                if row["is_preconfirmation_gap"]
            )
        )
        bridge_and_preconfirmation = [
            row
            for row in members
            if row["is_raw_false_bridge"] or row["is_preconfirmation_gap"]
        ]
        self.assertTrue(bridge_and_preconfirmation)
        self.assertEqual(
            {row["zone_status_as_of"] for row in bridge_and_preconfirmation},
            {"GAP_PENDING"},
        )

    def test_component_membership_uses_daily_asof_status(self):
        _timeline, _intervals, _components, zones, _ledger = self._run_rows(
            [True, True, True, True, False, True, True, True, True],
            d=2,
            g=1,
        )
        members = zones[0]["membership_rows"]
        first_component = members[:2]
        reentry_component = members[-2:]
        self.assertEqual(
            [row["zone_status_as_of"] for row in first_component],
            ["COMPONENT_FORMING", "QUALIFIED_ACTIVE"],
        )
        self.assertEqual(
            [row["prequalification_member"] for row in first_component],
            [True, False],
        )
        self.assertEqual(
            [row["zone_status_as_of"] for row in reentry_component],
            ["REENTRY_PENDING_QUALIFICATION", "QUALIFIED_ACTIVE"],
        )
        self.assertEqual(
            [row["prequalification_member"] for row in reentry_component],
            [True, False],
        )

    def test_raw_true_preconfirmation_does_not_reset_raw_false_g(self):
        timeline, _intervals, _components, zones, _ledger = self._run_rows(
            [True, True, True, False, True, True, False, True, True, True],
            d=1,
            g=1,
        )
        self.assertEqual(
            zones[0]["zone_finalization_time"], timeline[6]["available_time"]
        )
        _timeline, _intervals, _components, g2_zones, _ledger = self._run_rows(
            [True, True, True, False, True, True, False, True, True, True],
            d=1,
            g=2,
        )
        self.assertEqual(g2_zones[0]["component_count"], 2)
        self.assertEqual(g2_zones[0]["raw_false_bridged_day_count"], 2)
        self.assertEqual(g2_zones[0]["preconfirmation_gap_day_count"], 4)

    def test_unqualified_reentry_state_risk_independent_of_event_membership(self):
        _timeline, _intervals, _components, zones, _ledger = self._run_rows(
            [True, True, True, True, True, False, True, True, True, False],
            d=3,
            g=2,
        )
        members = [row for zone in zones for row in zone["membership_rows"]]
        unqualified = [row for row in members if row["unqualified_reentry_member"]]
        self.assertTrue(unqualified)
        self.assertTrue(any(row["state_risk_set_eligible"] for row in unqualified))
        self.assertFalse(
            any(row["qualified_event_risk_set_eligible"] for row in unqualified)
        )
        self.assertFalse(any(row["event_zone_member"] for row in unqualified))

    def test_g_plus_one_before_unqualified_reentry_finalizes_at_earliest_day(self):
        timeline, _intervals, _components, zones, ledger = self._run_rows(
            [True, True, True, True, True, False, False, True, True, True, False],
            d=3,
            g=0,
        )
        self.assertEqual(zones[0]["status"], "FINALIZED")
        self.assertEqual(
            zones[0]["zone_finalization_time"], timeline[5]["available_time"]
        )
        self.assertIn("raw_false_gap_exceeds_g", [row["reason_code"] for row in ledger])

    def test_unqualified_reentry_quality_break_finalizes_with_quality_break(self):
        raws = [True, True, True, True, True, False, True, True]
        qualities = ["valid"] * len(raws)
        qualities[-1] = "diagnostic_required"
        _timeline, _intervals, _components, zones, ledger = self._run_rows(
            raws, d=3, g=2, qualities=qualities
        )
        self.assertEqual(zones[0]["status"], "FINALIZED_WITH_QUALITY_BREAK")
        self.assertIn("quality_break", [row["reason_code"] for row in ledger])

    def test_qualified_gap_uses_earliest_raw_false_before_later_quality_break(self):
        raws = [True, True, True, False, True, True, True, True]
        qualities = ["valid"] * len(raws)
        qualities[4] = "diagnostic_required"
        timeline, _intervals, _components, zones, ledger = self._run_rows(
            raws, d=1, g=0, qualities=qualities
        )
        self.assertEqual(zones[0]["status"], "FINALIZED")
        self.assertEqual(
            zones[0]["zone_finalization_time"], timeline[3]["available_time"]
        )
        self.assertEqual(
            [
                row["reason_code"]
                for row in ledger
                if row["from_state"] == "GAP_PENDING"
            ][0],
            "raw_false_gap_exceeds_g",
        )

    def test_trailing_gap_uses_earliest_raw_false_before_later_quality_break(self):
        raws = [True, True, True, False, True]
        qualities = ["valid"] * len(raws)
        qualities[4] = "diagnostic_required"
        timeline, _intervals, _components, zones, ledger = self._run_rows(
            raws, d=1, g=0, qualities=qualities
        )
        self.assertEqual(zones[0]["status"], "FINALIZED")
        self.assertEqual(
            zones[0]["zone_finalization_time"], timeline[3]["available_time"]
        )
        self.assertEqual(ledger[-1]["reason_code"], "raw_false_gap_exceeds_g")

    def test_synthetic_registry_is_actual_replay_not_empty(self):
        registry, results, fixtures = r2_t02.synthetic_case_payloads()
        self.assertGreaterEqual(len(registry), 40)
        self.assertEqual(len(registry), len(results))
        self.assertTrue(all(row["status"] == "passed" for row in results))
        self.assertTrue(all(int(row["transition_count"]) > 0 for row in results))
        by_case = {row["case_id"]: row for row in fixtures}
        self.assertEqual(
            {
                case_id
                for case_id, row in by_case.items()
                if row["evidence_role"] == "core_scientific_oracle"
            },
            r2_t02.CORE_SCIENTIFIC_ORACLE_CASES,
        )
        for case_id, row in by_case.items():
            with self.subTest(case_id=case_id):
                if case_id in r2_t02.CORE_SCIENTIFIC_ORACLE_CASES:
                    self.assertTrue(set(row["hand_authored_oracle"]) - {"d", "g"})
                    self.assertNotIn("named_semantic_fact", row["hand_authored_oracle"])
                else:
                    self.assertEqual(row["evidence_role"], "regression_only")
                    self.assertEqual(row["hand_authored_oracle"], {})

    def test_independent_core_trace_detects_observed_mutation(self):
        _, _, fixtures = r2_t02.synthetic_case_payloads()
        fixture = next(row for row in fixtures if row["case_id"] == "k3_no_backfill")
        replay = independent._independent_fixture_replay(fixture)
        self.assertEqual(
            independent._independent_core_trace_errors(
                "k3_no_backfill", fixture, replay, r2_t02.CONTRACT_VERSION
            ),
            [],
        )
        mutated = json.loads(json.dumps(fixture))
        mutated["observed_state_timeline"][2]["confirmed_state"] = False
        errors = independent._independent_core_trace_errors(
            "k3_no_backfill", mutated, replay, r2_t02.CONTRACT_VERSION
        )
        self.assertIn(
            "independent_core_trace_mismatch:k3_no_backfill:timeline:2026-01-04:confirmed_state",
            errors,
        )

        bridge = next(
            row for row in fixtures if row["case_id"] == "bridge_membership_delayed"
        )
        bridge_replay = independent._independent_fixture_replay(bridge)
        mutations = [
            ("observed_zone_ledger", 0, "status", "RIGHT_CENSORED", "zone"),
            (
                "observed_zone_ledger",
                0,
                "zone_finalization_time",
                "2099-01-01T00:00:00+08:00",
                "zone",
            ),
            (
                "observed_zone_ledger",
                0,
                "raw_false_bridged_day_count",
                99,
                "zone",
            ),
            (
                "observed_membership_rows",
                1,
                "membership_available_time",
                "2099-01-01T00:00:00+08:00",
                "membership",
            ),
            (
                "observed_membership_rows",
                1,
                "is_raw_false_bridge",
                False,
                "membership",
            ),
            (
                "observed_risk_set_rows",
                0,
                "state_risk_set_eligible",
                False,
                "risk_set",
            ),
            (
                "observed_risk_set_rows",
                0,
                "qualified_event_risk_set_eligible",
                False,
                "risk_set",
            ),
        ]
        for table, index, field, value, entity in mutations:
            changed = json.loads(json.dumps(bridge))
            changed[table][index][field] = value
            with self.subTest(table=table, field=field):
                errors = independent._independent_core_trace_errors(
                    "bridge_membership_delayed",
                    changed,
                    bridge_replay,
                    r2_t02.CONTRACT_VERSION,
                )
                self.assertTrue(
                    any(
                        f":{entity}:" in error and error.endswith(f":{field}")
                        for error in errors
                    ),
                    errors,
                )

    def test_metric_and_hard_gate_evaluators_have_pass_fail_semantics(self):
        zone_rows = [
            {
                "scan_event_id": "e1",
                "security_id": "S1",
                "confirmed_day_count": 7,
                "upstream_confirmed_day_count": 10,
                "bridged_day_count": 2,
                "raw_false_bridged_day_count": 2,
                "total_nonconfirmed_gap_day_count": 3,
                "zone_span_days": 10,
                "component_count": 2,
                "status": "RIGHT_CENSORED",
                "duration": 10,
                "upstream_atomic_duration_q95": 5,
                "first_qualified_component_start_date": "2025-01-01",
            },
            {
                "scan_event_id": "e2",
                "security_id": "S2",
                "confirmed_day_count": 3,
                "upstream_confirmed_day_count": 10,
                "bridged_day_count": 0,
                "raw_false_bridged_day_count": 0,
                "total_nonconfirmed_gap_day_count": 1,
                "zone_span_days": 5,
                "component_count": 1,
                "status": "FINALIZED",
                "duration": 5,
                "upstream_atomic_duration_q95": 5,
                "first_qualified_component_start_date": "2026-01-01",
            },
        ]
        self.assertEqual(
            r2_t02._metric_evaluator(zone_rows, "qualified_event_count")["value"], 2
        )
        self.assertAlmostEqual(
            r2_t02._metric_evaluator(zone_rows, "bridged_day_ratio")["value"],
            2 / 15,
        )
        self.assertEqual(
            r2_t02._metric_evaluator(zone_rows, "merge_ratio")["value"], 0.5
        )
        self.assertEqual(
            r2_t02._metric_evaluator(zone_rows, "open_event_ratio")["value"], 0.5
        )
        self.assertGreater(
            r2_t02._metric_evaluator(zone_rows, "duration_q95_ratio")["value"], 1.0
        )
        self.assertTrue(r2_t02._hard_gate_evaluator(0.5, ">=", 0.35))
        self.assertFalse(r2_t02._hard_gate_evaluator(0.2, ">=", 0.35))
        self.assertTrue(r2_t02._hard_gate_evaluator(0.2, "<=", 0.35))
        self.assertFalse(r2_t02._hard_gate_evaluator(0.5, "<=", 0.35))
        self.assertTrue(r2_t02._zero_tolerance_evaluator([]))
        self.assertFalse(
            r2_t02._zero_tolerance_evaluator(["raw_false_gap_days_exceed_g"])
        )

    def test_reference_metrics_are_exact_and_fail_closed(self):
        rows = [
            {
                "scan_event_id": "e1",
                "security_id": "S1",
                "status": "RIGHT_CENSORED",
                "raw_false_bridged_day_count": 2,
                "zone_span_days": 10,
                "component_count": 2,
                "first_qualified_component_start_date": "2025-01-01",
                "upstream_atomic_duration_q95": 5,
            },
            {
                "scan_event_id": "e2",
                "security_id": "S2",
                "status": "FINALIZED",
                "raw_false_bridged_day_count": 0,
                "zone_span_days": 5,
                "component_count": 1,
                "first_qualified_component_start_date": "2026-01-01",
                "upstream_atomic_duration_q95": 5,
            },
        ]
        expected = {
            "qualified_event_count": 2,
            "unique_securities": 2,
            "bridged_day_ratio": 2 / 15,
            "merge_ratio": 0.5,
            "open_event_ratio": 0.5,
            "nonzero_years": 2,
            "max_year_share": 0.5,
            "duration_q95_ratio": 2.0,
        }
        for metric_id, value in expected.items():
            with self.subTest(metric_id=metric_id):
                self.assertAlmostEqual(
                    r2_t02._metric_evaluator(rows, metric_id)["value"], value
                )

        required = {
            "qualified_event_count": "status",
            "unique_securities": "security_id",
            "bridged_day_ratio": "raw_false_bridged_day_count",
            "merge_ratio": "component_count",
            "open_event_ratio": "status",
            "nonzero_years": "first_qualified_component_start_date",
            "max_year_share": "first_qualified_component_start_date",
            "duration_q95_ratio": "upstream_atomic_duration_q95",
        }
        for metric_id, missing in required.items():
            incomplete = [
                {key: value for key, value in rows[0].items() if key != missing}
            ]
            with self.subTest(metric_id=metric_id, missing=missing):
                with self.assertRaisesRegex(
                    ValueError,
                    f"metric_required_input_missing:{metric_id}:{missing}",
                ):
                    r2_t02._metric_evaluator(incomplete, metric_id)

        count_metrics = {"qualified_event_count", "unique_securities", "nonzero_years"}
        for metric_id in expected:
            result = r2_t02._metric_evaluator([], metric_id)
            if metric_id in count_metrics:
                self.assertEqual(result["value"], 0)
            else:
                self.assertIsNone(result["value"])
                self.assertEqual(result["null_reason"], "zero_denominator")

    def test_hard_gate_component_population_metrics_are_exact_and_fail_closed(self):
        retained_rows = [
            {"confirmed_day_count": 7, "qualified": True},
            {"confirmed_day_count": 3, "qualified": False},
        ]
        retained = r2_t02._metric_evaluator(
            retained_rows, "retained_confirmed_day_ratio"
        )
        self.assertEqual((retained["numerator"], retained["denominator"]), (7, 10))
        self.assertEqual(retained["value"], 0.7)
        all_unqualified = r2_t02._metric_evaluator(
            [{"confirmed_day_count": 4, "qualified": False}],
            "retained_confirmed_day_ratio",
        )
        self.assertEqual(all_unqualified["value"], 0)
        empty_retained = r2_t02._metric_evaluator([], "retained_confirmed_day_ratio")
        self.assertIsNone(empty_retained["value"])
        self.assertEqual(empty_retained["null_reason"], "zero_denominator")

        exit_rows = [
            {
                "termination_reason": "natural_state_exit",
                "confirmed_day_count": 1,
                "d": 2,
            },
            {
                "termination_reason": "natural_state_exit",
                "confirmed_day_count": 3,
                "d": 2,
            },
            {
                "termination_reason": "quality_interruption",
                "confirmed_day_count": 1,
                "d": 2,
            },
            {
                "termination_reason": "sample_end_censoring",
                "confirmed_day_count": 1,
                "d": 2,
            },
        ]
        drop = r2_t02._metric_evaluator(exit_rows, "short_interval_drop_rate")
        self.assertEqual((drop["numerator"], drop["denominator"]), (1, 2))
        self.assertEqual(drop["value"], 0.5)
        no_normal_exit = r2_t02._metric_evaluator(
            exit_rows[2:], "short_interval_drop_rate"
        )
        self.assertIsNone(no_normal_exit["value"])
        self.assertEqual(no_normal_exit["null_reason"], "zero_denominator")
        self.assertFalse(r2_t02._hard_gate_evaluator(None, ">=", 0.25))
        for metric_id, row in [
            ("retained_confirmed_day_ratio", {"confirmed_day_count": 1}),
            ("short_interval_drop_rate", {"confirmed_day_count": 1, "d": 2}),
        ]:
            with self.subTest(metric_id=metric_id):
                with self.assertRaisesRegex(
                    ValueError, f"metric_required_input_missing:{metric_id}"
                ):
                    r2_t02._metric_evaluator([row], metric_id)

    def test_metric_counts_denominators_and_nearest_order_q95_are_exact(self):
        rows = [
            {
                "scan_event_id": "e1",
                "security_id": "S1",
                "bridged_day_count": 7,
                "raw_false_bridged_day_count": 5,
                "preconfirmation_gap_day_count": 2,
                "total_nonconfirmed_gap_day_count": 7,
                "zone_revision": 3,
                "status": "RIGHT_CENSORED",
                "status_as_of": "GAP_PENDING",
                "unqualified_reentry_count": 4,
                "confirmed_day_count": 6,
                "eligible_valid_daily_row_count": 20,
                "zone_span_days": 11,
                "baseline_q95": 10,
            },
            {
                "scan_event_id": "e2",
                "security_id": "S2",
                "bridged_day_count": 1,
                "raw_false_bridged_day_count": 1,
                "preconfirmation_gap_day_count": 4,
                "total_nonconfirmed_gap_day_count": 5,
                "zone_revision": 2,
                "status": "FINALIZED",
                "status_as_of": "QUALIFIED_ACTIVE",
                "unqualified_reentry_count": 2,
                "confirmed_day_count": 3,
                "eligible_valid_daily_row_count": 10,
                "zone_span_days": 4,
                "baseline_q95": 10,
            },
        ]
        expected_counts = {
            "bridged_day_count": 8,
            "raw_false_bridged_day_count": 6,
            "preconfirmation_gap_day_count": 6,
            "total_nonconfirmed_gap_day_count": 12,
            "zone_revision_count": 5,
            "active_zone_count": 1,
            "gap_pending_zone_count": 1,
            "unqualified_reentry_count": 6,
        }
        for metric_id, expected in expected_counts.items():
            with self.subTest(metric_id=metric_id):
                self.assertEqual(
                    r2_t02._metric_evaluator(rows, metric_id)["value"], expected
                )
        coverage = r2_t02._metric_evaluator(rows, "confirmed_event_coverage")
        self.assertEqual(coverage["numerator"], 9)
        self.assertEqual(coverage["denominator"], 30)
        self.assertEqual(coverage["value"], 0.3)
        durations = [
            {"zone_span_days": value, "confirmed_day_count": 100 - value}
            for value in [1, 2, 3, 4, 100]
        ]
        self.assertEqual(
            r2_t02._metric_evaluator(durations, "duration_q95")["value"], 100
        )

    def test_hard_gate_registry_resolves_dynamic_thresholds_and_exact_ids(self):
        context = {"upstream_confirmed_interval_count": 6000}
        threshold = "max(250,ceil(0.05*upstream_confirmed_interval_count))"
        self.assertTrue(r2_t02._hard_gate_evaluator(300, ">=", threshold, context))
        self.assertFalse(r2_t02._hard_gate_evaluator(299, ">=", threshold, context))
        self.assertFalse(r2_t02._hard_gate_evaluator(999, ">=", threshold, {}))
        self.assertIsNone(
            r2_t02.resolve_metric_evaluator("r2_t02_metric_eval__does_not_exist")
        )
        self.assertIsNone(
            r2_t02.resolve_hard_gate_evaluator(
                "r2_t02_zero_tolerance_eval__does_not_exist"
            )
        )
        detector = r2_t02.resolve_violation_detector(
            "r2_t02_violation_detector__status_asof_timeline_gap"
        )
        self.assertIsNotNone(detector)
        self.assertEqual(
            len(
                detector(
                    [
                        {
                            "status_as_of": "GAP_PENDING",
                            "expected_status_as_of": "FINALIZED",
                        }
                    ]
                )
            ),
            1,
        )
        with self.assertRaisesRegex(ValueError, "violation_detector_input_missing"):
            detector([{}])

    def test_metric_and_gate_implementation_stage_partition_is_complete(self):
        metrics = r2_t02.metric_dictionary_rows()
        gates = r2_t02.hard_gate_rows()
        allowed = {
            "r2_t02_reference_executable",
            "r2_t03_runtime_required",
        }
        self.assertEqual(len(metrics), 78)
        self.assertTrue(all(row["implementation_stage"] in allowed for row in metrics))
        self.assertTrue(all(row["implementation_stage"] in allowed for row in gates))
        reference_metrics = {
            row["metric_id"]
            for row in metrics
            if row["implementation_stage"] == "r2_t02_reference_executable"
        }
        self.assertEqual(reference_metrics, r2_t02.REFERENCE_EXECUTABLE_METRICS)
        reference_structure_gates = {
            row["gate_id"]
            for row in gates
            if row["zero_tolerance"] is True
            and row["implementation_stage"] == "r2_t02_reference_executable"
        }
        self.assertEqual(
            reference_structure_gates,
            r2_t02.REFERENCE_EXECUTABLE_STRUCTURE_GATES,
        )

    def test_t03_contract_has_strict_row_schemas_and_integer_profiles(self):
        contracts = r2_t02.t03_table_contracts()
        profile_fields = {
            row["name"]: row for row in contracts["dg_event_zone_profile"]["fields"]
        }
        self.assertEqual(profile_fields["d"]["type"], "integer")
        self.assertEqual(profile_fields["g"]["type"], "integer")
        self.assertEqual(profile_fields["qualified_event_count"]["type"], "integer")
        membership = contracts["event_zone_membership_daily"]
        self.assertFalse(membership["row_schema"]["additionalProperties"])
        membership_names = {row["name"] for row in membership["fields"]}
        self.assertTrue(
            {"evaluation_time", "eligible", "quality_state"} <= membership_names
        )
        bridge = contracts["event_zone_bridge_segment"]
        self.assertFalse(bridge["row_schema"]["additionalProperties"])
        status = next(
            row for row in membership["fields"] if row["name"] == "zone_status_as_of"
        )
        self.assertIn("REENTRY_PENDING_QUALIFICATION", status["enum_values"])

    def test_bridge_segment_bounds_are_executable(self):
        baseline = {
            "K": 3,
            "d": 2,
            "g": 2,
            "merge_accepted": True,
            "raw_false_gap_day_count": 2,
            "preconfirmation_gap_day_count": 4,
            "total_nonconfirmed_gap_day_count": 6,
        }
        self.assertEqual(r2_t02._detect_raw_false_gap_days_exceed_g([baseline]), [])
        self.assertEqual(r2_t02._detect_preconfirmation_bound([baseline]), [])
        self.assertEqual(r2_t02._detect_total_gap_bound([baseline]), [])
        mutation = {
            **baseline,
            "preconfirmation_gap_day_count": 5,
            "total_nonconfirmed_gap_day_count": 7,
        }
        self.assertEqual(len(r2_t02._detect_preconfirmation_bound([mutation])), 1)
        self.assertEqual(len(r2_t02._detect_total_gap_bound([mutation])), 1)

    def test_reference_structure_detectors_have_baseline_mutation_and_missing_input(
        self,
    ):
        fixtures = {
            "missing_expected_trading_row": (
                {"observed_trading_row_count": 2, "expected_trading_row_count": 2},
                {"observed_trading_row_count": 1, "expected_trading_row_count": 2},
            ),
            "unknown_bridge": (
                {"quality_state": "valid", "merge_accepted": True},
                {"quality_state": "unknown", "merge_accepted": True},
            ),
            "blocked_bridge": (
                {"quality_state": "valid", "merge_accepted": True},
                {"quality_state": "blocked", "merge_accepted": True},
            ),
            "diagnostic_required_bridge": (
                {"quality_state": "valid", "merge_accepted": True},
                {"quality_state": "diagnostic_required", "merge_accepted": True},
            ),
            "ineligible_bridge": (
                {"eligible": True, "merge_accepted": True},
                {"eligible": False, "merge_accepted": True},
            ),
            "raw_false_gap_days_exceed_g": (
                {"raw_false_gap_day_count": 1, "g": 1, "merge_accepted": True},
                {"raw_false_gap_day_count": 2, "g": 1, "merge_accepted": True},
            ),
            "preconfirmation_days_exceed_k_minus_one_bound": (
                {
                    "preconfirmation_gap_day_count": 2,
                    "raw_false_gap_day_count": 1,
                    "K": 3,
                    "merge_accepted": True,
                },
                {
                    "preconfirmation_gap_day_count": 3,
                    "raw_false_gap_day_count": 1,
                    "K": 3,
                    "merge_accepted": True,
                },
            ),
            "total_nonconfirmed_gap_days_exceed_k_bound": (
                {
                    "raw_false_gap_day_count": 1,
                    "preconfirmation_gap_day_count": 2,
                    "total_nonconfirmed_gap_day_count": 3,
                    "K": 3,
                    "g": 1,
                    "merge_accepted": True,
                },
                {
                    "raw_false_gap_day_count": 1,
                    "preconfirmation_gap_day_count": 2,
                    "total_nonconfirmed_gap_day_count": 4,
                    "K": 3,
                    "g": 1,
                    "merge_accepted": True,
                },
            ),
            "risk_set_violation": (
                {
                    "qualified_event_risk_set_eligible": True,
                    "state_risk_set_eligible": True,
                    "component_qualified_as_of": True,
                    "event_zone_member": True,
                    "unqualified_reentry_member": False,
                },
                {
                    "qualified_event_risk_set_eligible": True,
                    "state_risk_set_eligible": False,
                    "component_qualified_as_of": True,
                    "event_zone_member": True,
                    "unqualified_reentry_member": False,
                },
            ),
            "availability_backfill": (
                {
                    "membership_available_time": "2026-01-02T15:00:00+08:00",
                    "available_time": "2026-01-02T15:00:00+08:00",
                },
                {
                    "membership_available_time": "2026-01-01T15:00:00+08:00",
                    "available_time": "2026-01-02T15:00:00+08:00",
                },
            ),
            "event_id_instability": (
                {"scan_event_id": "a", "recomputed_scan_event_id": "a"},
                {"scan_event_id": "a", "recomputed_scan_event_id": "b"},
            ),
            "transition_closure_violation": (
                {"transition_to_state": "A", "next_transition_from_state": "A"},
                {"transition_to_state": "A", "next_transition_from_state": "B"},
            ),
            "duplicate_primary_key": ({"primary_key": ["a"]}, {"primary_key": ["a"]}),
        }
        for gate_id, (baseline, mutation) in fixtures.items():
            detector = r2_t02.resolve_violation_detector(
                f"r2_t02_violation_detector__{gate_id}"
            )
            with self.subTest(gate_id=gate_id):
                self.assertIsNotNone(detector)
                baseline_rows = [baseline]
                mutation_rows = [mutation]
                if gate_id == "duplicate_primary_key":
                    mutation_rows = [baseline, mutation]
                self.assertEqual(detector(baseline_rows), [])
                self.assertGreaterEqual(len(detector(mutation_rows)), 1)
                with self.assertRaisesRegex(
                    ValueError, f"violation_detector_input_missing:{gate_id}"
                ):
                    detector([{}])

    def test_window_metrics_use_full_exact_keys(self):
        rows = [
            {
                "window": window,
                "state_line": "primary",
                "candidate_role": "primary",
                "security_id": security,
                "trade_date": date,
                "confirmed_state": True,
            }
            for window, security, date in [
                ("W120", "S1", "2026-01-01"),
                ("W120", "S2", "2026-01-01"),
                ("W250", "S1", "2026-01-01"),
                ("W250", "S3", "2026-01-01"),
            ]
        ]
        self.assertEqual(
            r2_t02._metric_evaluator(rows, "intersection_confirmed_days")["value"], 1
        )
        self.assertEqual(
            r2_t02._metric_evaluator(rows, "W120_only_confirmed_days")["value"], 1
        )
        self.assertEqual(
            r2_t02._metric_evaluator(rows, "W250_only_confirmed_days")["value"], 1
        )

    def test_external_github_review_attestation_requires_exact_head_and_pass_marker(
        self,
    ):
        head = "a" * 40
        reviews = [
            {
                "id": 123,
                "commit_id": head,
                "state": "COMMENTED",
                "body": "[R2-T02 scientific PASS] independent review passed",
                "submitted_at": "2026-07-12T08:00:00Z",
                "user": {"login": "scientific-reviewer"},
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"
            path.write_text(json.dumps(reviews), encoding="utf-8")
            selected = premerge._select_exact_head_scientific_pass(path, head)
            self.assertEqual(selected["id"], 123)
            with self.assertRaisesRegex(ValueError, "exact_head"):
                premerge._select_exact_head_scientific_pass(path, "b" * 40)

    def test_premerge_formal_surface_uses_registered_v3_config_sources(self):
        paths = set(premerge._formal_surface_paths(ROOT))
        for required in {
            "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v8.json",
            "docs/stages/R2_参数、事件规则与状态版本冻结.md",
            "schemas/r2/r2_t02_t03_output_contract.schema.json",
            "scripts/validate_text_contract.py",
            "scripts/validate_configs.py",
            "scripts/validate_manifests.py",
            "scripts/r2/run_r2_t02_protocol_freeze.py",
            "src/common/canonical_io.py",
            "src/r2/r2_t02_protocol_freeze.py",
            ".github/workflows/quality.yml",
        }:
            self.assertIn(required, paths)

    def test_premerge_heavy_ids_are_canonicalized_to_full_discovery_ids(self):
        dynamic_id = (
            "_unittest_profile_convergence-research_tests_r0_"
            "test_r0_t10_score_materializer.R0T10ScoreMaterializerTest."
            "test_uses_spawn_process_pool"
        )
        discovered_id = (
            "r0.test_r0_t10_score_materializer.R0T10ScoreMaterializerTest."
            "test_uses_spawn_process_pool"
        )
        self.assertEqual(premerge._canonical_test_id(dynamic_id), discovered_id)
        self.assertEqual(premerge._canonical_test_id(discovered_id), discovered_id)

    def _run_rows(self, raw_values, *, d, g, qualities=None):
        dates = [f"2026-01-{day:02d}" for day in range(2, 2 + len(raw_values))]
        qualities = qualities or ["valid"] * len(raw_values)
        rows = [
            r2_t02.DailyInput(
                "S1",
                date,
                f"{date}T15:00:00+08:00",
                True,
                quality,
                raw,
            )
            for date, quality, raw in zip(dates, qualities, raw_values)
        ]
        timeline, _ledger = r2_t02.replay_confirmation(rows, dates)
        intervals = r2_t02.atomic_intervals(timeline)
        components, zones, event_ledger = r2_t02.group_event_zones(
            timeline, intervals, d, g, candidate_cell_id="test_cell"
        )
        return timeline, intervals, components, zones, event_ledger

    def test_generated_package_if_present_keeps_downstream_closed(self):
        if not RUN_DIR.is_dir():
            self.skipTest("formal R2-T02 package has not been generated yet")
        validation = r2_t02.validate_output(RUN_DIR, CONFIG_PATH)
        package = json.loads(
            (RUN_DIR / "r2_t02_result_package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validation["status"], "passed")
        self.assertFalse(package["formal_task_completed"])
        self.assertFalse(package["R2-T03_allowed_to_start"])
        self.assertFalse(package["R3_allowed_to_start"])


if __name__ == "__main__":
    unittest.main()
