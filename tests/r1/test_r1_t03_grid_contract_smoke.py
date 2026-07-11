from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from src.r0.candidate_artifact_engine import build_candidate_configs
from src.r1.r1_t03_27_grid_light_profile import (
    BASELINE_CONFIG_ID,
    FORBIDDEN_TOKENS,
    ProfileContext,
    _check_config,
    _find_forbidden_tokens,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r1/r1_t03_27_grid_light_profile.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t03_27_grid_light_profile.schema.json"


class R1T03GridContractSmokeTest(unittest.TestCase):
    def test_grid_has_baseline_boundary_and_stable_cartesian_count(self) -> None:
        configs = build_candidate_configs()
        by_id = {config.candidate_config_id: config for config in configs}
        self.assertEqual(len(configs), 27)
        self.assertEqual(len(by_id), 27)
        self.assertIn(BASELINE_CONFIG_ID, by_id)
        boundary = by_id["R0_W120_Q10_K2_WEAK_D010"]
        self.assertEqual(boundary.percentile_window_W, 120)
        self.assertEqual(boundary.low_quantile_q, 0.10)
        self.assertEqual(boundary.confirmation_days_K, 2)

    def test_config_schema_and_required_fields_pass(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
        self.assertEqual(config["grid"]["config_count"], 27)
        self.assertEqual(config["baseline_config_id"], BASELINE_CONFIG_ID)
        self.assertEqual(config["state_names"], ["S_P", "S_PC", "S_PCT", "S_PCVT"])

    def test_illegal_grid_fails_closed(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["grid"]["K"] = [1, 2, 3]
        ctx = ProfileContext(ROOT)
        _check_config(ctx, config, max_workers=1)
        self.assertEqual(ctx.checks["config_contract"], "blocked")
        self.assertIn("config_contract:K_grid_mismatch", ctx.errors)

    def test_future_and_downstream_fields_are_forbidden(self) -> None:
        payload = {
            "future_return": 0.1,
            "backtest": {"portfolio_signal": True},
        }
        found = _find_forbidden_tokens(payload)
        self.assertTrue({"future_return", "backtest", "portfolio", "signal"} & found)
        self.assertIn("future_return", FORBIDDEN_TOKENS)
        self.assertIn("portfolio", FORBIDDEN_TOKENS)


if __name__ == "__main__":
    unittest.main()
