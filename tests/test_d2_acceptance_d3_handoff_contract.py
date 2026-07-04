from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/d2_acceptance_d3_handoff_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d2_acceptance_d3_handoff_contract.schema.json"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2AcceptanceD3HandoffContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(CONTRACT_PATH)
        cls.schema = load(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)

    def test_all_d2_t08_authorizations_are_false(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_data_materialization_authorized",
            "d3_generation_authorized",
            "r0_generation_authorized",
        ]:
            self.assertFalse(self.contract[key])
        self.assertTrue(self.contract["synthetic_test_only"])

    def test_contract_depends_on_d2_gates_and_membership(self) -> None:
        depends_on = set(self.contract["depends_on"])
        self.assertIn(
            "D2_RAW_MARKET_PRICES_BLOCKED_PENDING_SOURCE_AUTHORIZATION_V1",
            depends_on,
        )
        self.assertIn(
            "D2_ADJUSTMENT_FACTOR_ASOF_BLOCKED_PENDING_SOURCE_AUTHORIZATION_V1",
            depends_on,
        )
        self.assertIn("D2_CONTINUOUS_PRICE_CONSTRUCTION_CONTRACT_V1", depends_on)
        self.assertIn(
            "D2_CANDIDATE_MARKET_SNAPSHOT_PROBE_EXECUTION_REPORT_V1",
            depends_on,
        )
        self.assertIn("D2_MARKET_QUALITY_PCVT_DEPENDENCY_CONTRACT_V1", depends_on)
        self.assertIn(
            "D2_CSI800_STATIC_2026_06_MEMBERSHIP_ALIGNMENT_V1",
            depends_on,
        )

    def test_d3_target_and_generation_boundary(self) -> None:
        target = self.contract["d3_handoff_target"]
        self.assertEqual(target["target_table"], "d3.daily_market_observations")
        self.assertFalse(target["d3_generation_authorized_by_this_pr"])
        self.assertFalse(self.contract["d3_generation_authorized"])
        self.assertFalse(self.contract["r0_generation_authorized"])

    def test_d3_required_component_refs_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["d3_required_component_refs"]),
            {
                "raw_price_ref",
                "adjusted_price_ref",
                "trading_constraint_ref",
                "market_price_quality_ref",
                "mechanical_gap_ref",
                "pcvt_input_readiness_ref",
                "membership_ref",
                "calendar_ref",
                "source_snapshot_ref",
                "run_ref",
            },
        )

    def test_pcvt_handoff_contains_eight_proposed_candidates(self) -> None:
        policy = self.contract["pcvt_handoff_policy"]
        self.assertEqual(
            policy["pcvt_candidate_set_status"], "proposed_not_r0_finalized"
        )
        self.assertFalse(policy["pcvt_values_generated_by_this_pr"])
        self.assertFalse(policy["r0_thresholds_defined_by_this_pr"])
        self.assertFalse(policy["r0_state_machine_defined_by_this_pr"])
        candidates = policy["candidate_dependencies"]
        self.assertEqual(len(candidates), 8)
        self.assertEqual(
            {item["indicator_id"] for item in candidates},
            {
                "P1_NATR14",
                "P2_LogRange20",
                "C1_LogMASpread_5_60",
                "C2_AdjVWAPSpread_5_60",
                "T1_ER20",
                "T2_AbsTrendT20",
                "V1_VolShrink20_60",
                "V2_AmountLevel20Pct",
            },
        )

    def test_schema_rejects_authorization(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "d3_generation_authorized",
            "r0_generation_authorized",
        ]:
            changed = copy.deepcopy(self.contract)
            changed[key] = True
            with self.assertRaises(ValidationError):
                self.validator.validate(changed)

    def test_schema_rejects_missing_component_or_pcvt_candidate(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["d3_required_component_refs"].remove("source_snapshot_ref")
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["pcvt_handoff_policy"]["candidate_dependencies"] = changed[
            "pcvt_handoff_policy"
        ]["candidate_dependencies"][:-1]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
