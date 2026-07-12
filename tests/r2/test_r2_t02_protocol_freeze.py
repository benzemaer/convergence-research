import json
import tempfile
import unittest
from pathlib import Path

from src.r2 import r2_t02_premerge_full_evidence as premerge
from src.r2 import r2_t02_protocol_freeze as r2_t02

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT / "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v4.json"
)
RUN_DIR = ROOT / "data/generated/r2/r2_t02/R2-T02-20260712T1300Z"
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
        registry, results = r2_t02.synthetic_case_artifacts()
        self.assertGreaterEqual(len(registry), 40)
        self.assertEqual(len(registry), len(results))
        self.assertTrue(all(row["status"] == "passed" for row in results))
        self.assertTrue(all(int(row["transition_count"]) > 0 for row in results))

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
                "baseline_q95": 5,
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
                "baseline_q95": 5,
            },
        ]
        self.assertEqual(
            r2_t02._metric_evaluator(zone_rows, "qualified_event_count")["value"], 2
        )
        self.assertEqual(
            r2_t02._metric_evaluator(zone_rows, "retained_confirmed_day_ratio")[
                "value"
            ],
            0.5,
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
        self.assertEqual(len(detector([{"status_asof_timeline_gap": True}, {}])), 1)

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
        status = next(
            row for row in membership["fields"] if row["name"] == "zone_status_as_of"
        )
        self.assertIn("REENTRY_PENDING_QUALIFICATION", status["enum_values"])

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
            "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v4.json",
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
