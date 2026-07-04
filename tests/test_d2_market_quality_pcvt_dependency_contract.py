from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/market_quality_pcvt_dependency_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d2_market_quality_pcvt_dependency_contract.schema.json"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2MarketQualityPCVTDependencyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(CONTRACT_PATH)
        cls.schema = load(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)

    def test_authorizations_are_all_false(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_data_materialization_authorized",
            "d3_generation_authorized",
            "r0_indicator_calculation_authorized",
        ]:
            self.assertFalse(self.contract[key])
        self.assertTrue(self.contract["synthetic_test_only"])

    def test_contract_has_exactly_eight_pcvt_candidates(self) -> None:
        matrix = self.contract["pcvt_dependency_matrix"]
        ids = {item["indicator_id"] for item in matrix}
        self.assertEqual(len(matrix), 8)
        self.assertEqual(
            ids,
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
        for item in matrix:
            self.assertEqual(item["r0_status"], "pcvt_candidate_not_r0_finalized")

    def test_readiness_groups_are_declared(self) -> None:
        by_id = {
            item["indicator_id"]: item
            for item in self.contract["pcvt_dependency_matrix"]
        }
        for indicator_id in [
            "P1_NATR14",
            "P2_LogRange20",
            "C1_LogMASpread_5_60",
            "T1_ER20",
            "T2_AbsTrendT20",
        ]:
            self.assertEqual(
                by_id[indicator_id]["exploration_readiness"],
                "ready_after_full_window_pull",
            )
            self.assertTrue(
                by_id[indicator_id]["formal_readiness"].startswith("blocked_")
            )
        self.assertEqual(
            by_id["C2_AdjVWAPSpread_5_60"]["exploration_readiness"],
            "partial_pending_amount_volume_unit_validation_and_adjusted_vwap_policy",
        )
        self.assertEqual(
            by_id["V1_VolShrink20_60"]["exploration_readiness"],
            "partial_pending_volume_unit_validation_and_adjusted_volume_policy",
        )
        self.assertEqual(
            by_id["V2_AmountLevel20Pct"]["exploration_readiness"],
            "ready_after_amount_unit_validation_and_history_window_pull",
        )
        self.assertIn(
            "strict_past_history_missing",
            by_id["V2_AmountLevel20Pct"]["unknown_conditions"],
        )

    def test_schema_rejects_authorization_or_missing_candidate(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["formal_ingestion_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["d3_generation_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["pcvt_dependency_matrix"] = changed["pcvt_dependency_matrix"][:-1]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
