import json
import unittest
from pathlib import Path

from src.r2 import r2_t02_protocol_freeze as r2_t02

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT / "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v2.json"
)
RUN_DIR = ROOT / "data/generated/r2/r2_t02/R2-T02-20260712T1100Z"
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

    def test_synthetic_registry_is_actual_replay_not_empty(self):
        registry, results = r2_t02.synthetic_case_artifacts()
        self.assertGreaterEqual(len(registry), 40)
        self.assertEqual(len(registry), len(results))
        self.assertTrue(all(row["status"] == "passed" for row in results))
        self.assertTrue(all(int(row["transition_count"]) > 0 for row in results))

    def _run_rows(self, raw_values, *, d, g):
        dates = [f"2026-01-{day:02d}" for day in range(2, 2 + len(raw_values))]
        rows = [
            r2_t02.DailyInput(
                "S1",
                date,
                f"{date}T15:00:00+08:00",
                True,
                "valid",
                raw,
            )
            for date, raw in zip(dates, raw_values)
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
