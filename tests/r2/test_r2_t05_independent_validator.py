from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class R2T05IndependentValidatorContractTest(unittest.TestCase):
    def test_validator_does_not_import_production_materializer(self) -> None:
        tree = ast.parse(
            (ROOT / "src/r2/r2_t05_independent_validator.py").read_text(
                encoding="utf-8"
            )
        )
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        self.assertNotIn("src.r2.r2_t05_canonical_materialization", imports)
        self.assertNotIn("r2_t05_canonical_materialization", imports)

    def test_config_maps_source_membership_fields_explicitly(self) -> None:
        config = json.loads(
            (
                ROOT
                / "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json"
            ).read_text(encoding="utf-8")
        )
        mapping = config["mapping"]
        self.assertIn(
            "event_zone_membership_daily.retrospective_component_member",
            mapping["retrospective_component_member"],
        )
        self.assertIn(
            "prequalification_member", mapping["is_prequalification_confirmed_day"]
        )
        self.assertIn(
            "unqualified_reentry_member", mapping["is_unqualified_reentry_day"]
        )
        self.assertIn("is_raw_false_bridge", mapping["is_bridged_gap"])

    def test_no_future_or_trading_efficacy_fields_in_public_contract(self) -> None:
        text = (
            (
                ROOT
                / "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json"
            )
            .read_text(encoding="utf-8")
            .lower()
        )
        for token in (
            "future_return",
            "future_direction",
            "release_label",
            "backtest",
            "trading_efficacy",
        ):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
