from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from src.r3.r3_t01_protocol import (
    ProtocolContractError,
    build_contract_bundle,
    build_landmarks,
    enumerate_exit_attempts,
    event_balanced_weights,
    validate_event_split_assignments,
)
from src.r3.r3_t01_validator import validate_attempt_registry, validate_in_memory

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json"
FIXTURE_PATH = ROOT / "tests/r3/fixtures/r3_t01/cases.json"


class R3T01ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_independent_validator_accepts_config_and_all_declared_cases(self) -> None:
        report = validate_in_memory(self.config, self.fixture, root=ROOT)
        self.assertTrue(report.passed, report.errors)
        self.assertEqual(len(report.synthetic_case_results), 22)
        self.assertIsNotNone(report.double_rebuild_hash)

    def test_anchor_and_primary_unit_are_frozen(self) -> None:
        self.assertEqual(
            self.config["anchor_decision"]["selected_anchor"],
            "natural_exit_attempt",
        )
        unit = self.config["analysis_unit_contract"]
        self.assertEqual(
            unit["primary_unit"], ["state_version_id", "event_id", "exit_attempt_id"]
        )
        self.assertTrue(unit["all_legal_exit_attempts_are_primary"])
        self.assertFalse(unit["first_attempt_only"])
        self.assertFalse(unit["later_attempts_are_sidecar"])

    def test_s01_s02_s03_ids_ordinals_and_unqualified_reentry(self) -> None:
        for case in self.fixture["cases"][:3]:
            attempts, rejections = enumerate_exit_attempts(
                case["rows"],
                case["event_zones"],
                case["membership_rows"],
                self.config,
            )
            expected = case["expected"]
            self.assertEqual(len(attempts), expected["attempt_count"], case["case_id"])
            self.assertEqual(
                [item["exit_attempt_id"] for item in attempts],
                [item["exit_attempt_id"] for item in expected["attempts"]],
                case["case_id"],
            )
            self.assertEqual(
                [item["exit_attempt_ordinal"] for item in attempts],
                [item["exit_attempt_ordinal"] for item in expected["attempts"]],
            )
            self.assertEqual(
                sorted(item["code"] for item in rejections),
                sorted(expected["rejection_codes"]),
            )
        s03_attempts, _ = enumerate_exit_attempts(
            self.fixture["cases"][2]["rows"],
            self.fixture["cases"][2]["event_zones"],
            self.fixture["cases"][2]["membership_rows"],
            self.config,
        )
        self.assertGreater(
            s03_attempts[1]["source_component_ordinal"],
            s03_attempts[1]["component_count_as_of_exit"],
        )
        self.assertTrue(s03_attempts[1]["unqualified_reentry"])

    def test_later_event_lifecycle_fields_do_not_change_t0_identity(self) -> None:
        case = copy.deepcopy(self.fixture["cases"][0])
        before, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        case["event_zones"][0]["zone_finalization_time"] = "2024-02-01T15:00:00+08:00"
        case["event_zones"][0]["component_interval_count"] = 9
        case["event_zones"][0]["same_zone_requalified"] = True
        after, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertEqual(before[0]["exit_attempt_id"], after[0]["exit_attempt_id"])

    def test_state_version_and_security_namespaces_do_not_cross_lag(self) -> None:
        source = self.fixture["cases"][0]

        def relabel(
            case: dict[str, object], state: str, event: str, security: str
        ) -> dict[str, object]:
            clone = copy.deepcopy(case)
            for row in clone["rows"]:
                row["state_version_id"] = state
                row["security_id"] = security
                if row.get("active_event_id_as_of") is not None:
                    row["active_event_id_as_of"] = event
            for row in clone["membership_rows"]:
                row["state_version_id"] = state
                row["event_id"] = event
                row["security_id"] = security
            for row in clone["event_zones"]:
                row["state_version_id"] = state
                row["event_id"] = event
                row["security_id"] = security
            return clone

        second_state = relabel(
            source,
            self.config["frozen_inputs"]["state_versions"][1]["state_version_id"],
            "EV2",
            "SEC_A",
        )
        combined = {
            "rows": source["rows"] + second_state["rows"],
            "event_zones": source["event_zones"] + second_state["event_zones"],
            "membership_rows": source["membership_rows"]
            + second_state["membership_rows"],
        }
        attempts, _ = enumerate_exit_attempts(
            combined["rows"],
            combined["event_zones"],
            combined["membership_rows"],
            self.config,
        )
        self.assertEqual(len(attempts), 2)
        self.assertEqual(
            {item["state_version_id"] for item in attempts},
            set(
                item["state_version_id"]
                for item in self.config["frozen_inputs"]["state_versions"]
            ),
        )
        self.assertNotEqual(
            attempts[0]["exit_attempt_id"], attempts[1]["exit_attempt_id"]
        )

        second_security = relabel(
            source, source["rows"][0]["state_version_id"], "EV2", "SEC_B"
        )
        combined_security = {
            "rows": source["rows"] + second_security["rows"],
            "event_zones": source["event_zones"] + second_security["event_zones"],
            "membership_rows": source["membership_rows"]
            + second_security["membership_rows"],
        }
        security_attempts, _ = enumerate_exit_attempts(
            combined_security["rows"],
            combined_security["event_zones"],
            combined_security["membership_rows"],
            self.config,
        )
        self.assertEqual(
            {item["security_id"] for item in security_attempts}, {"SEC_A", "SEC_B"}
        )

    def test_landmarks_and_horizons_count_valid_expected_rows(self) -> None:
        version = self.config["frozen_inputs"]["state_versions"][0]["state_version_id"]
        rows = []
        for day in range(1, 41):
            rows.append(
                {
                    "state_version_id": version,
                    "security_id": "SEC_L",
                    "trade_date": f"2024-01-{day:02d}",
                    "expected_row_present": True,
                    "eligible_state": day not in {6, 12},
                    "quality_state": "invalid" if day in {3, 18} else "valid",
                    "raw_state": True,
                    "confirmed_state": True,
                }
            )
        landmarks = build_landmarks(rows, "2024-01-01")
        self.assertEqual(landmarks["T0"]["ordinal"], 0)
        self.assertEqual(landmarks["T1"]["trade_date"], "2024-01-02")
        self.assertEqual(landmarks["T2"]["trade_date"], "2024-01-04")
        self.assertEqual(landmarks["T2"]["intervening_unobservable_row_count"], 1)
        self.assertIn(
            "QUALITY_NOT_VALID", landmarks["T2"]["intervening_unobservable_reason_set"]
        )
        self.assertTrue(landmarks["H5"]["available"])
        self.assertTrue(landmarks["H10"]["available"])
        self.assertTrue(landmarks["H20"]["available"])
        self.assertTrue(landmarks["H30"]["available"])
        self.assertEqual(
            self.config["landmark_horizon_contract"]["primary_horizon"], "H20"
        )

    def test_event_split_and_event_balanced_weight(self) -> None:
        case = self.fixture["cases"][1]
        attempts, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        validate_event_split_assignments(attempts, {"EV1": "design"})
        with self.assertRaises(ProtocolContractError) as context:
            validate_event_split_assignments(
                attempts, {"EV1": ["design", "validation"]}
            )
        self.assertEqual(context.exception.code, "EVENT_SPLIT_LEAKAGE")
        self.assertEqual(event_balanced_weights(attempts), {"EV1": 0.5})

    def test_attempt_registry_duplicate_and_ordinal_fail_closed(self) -> None:
        case = self.fixture["cases"][1]
        attempts, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        duplicate_errors = validate_attempt_registry(
            attempts + [copy.deepcopy(attempts[0])]
        )
        self.assertIn("DUPLICATE_EXIT_ATTEMPT_ID", duplicate_errors)
        broken = copy.deepcopy(attempts)
        broken[1]["exit_attempt_ordinal"] = 1
        self.assertIn("ORDINAL_NOT_CONTIGUOUS", validate_attempt_registry(broken))

    def test_contract_bundle_contains_only_contract_sidecars(self) -> None:
        bundle = build_contract_bundle(self.config)
        self.assertNotIn("r3_t01_path_label.json", bundle)
        self.assertFalse(any("return" in name for name in bundle))
        self.assertFalse(any("boundary" in name for name in bundle))
        self.assertNotIn("duckdb.connect", json.dumps(bundle).lower())


if __name__ == "__main__":
    unittest.main()
