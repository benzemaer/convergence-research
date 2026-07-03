from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/g0_universe_time_boundaries.schema.json"
CONFIG_PATH = ROOT / "configs/g0/universe_time_boundaries.v1.json"


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class G0ConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())

    def test_proposed_config_is_valid(self) -> None:
        self.validator.validate(self.config)

    def test_static_backfill_claim_boundary_is_explicit(self) -> None:
        universe = self.config["universe"]
        self.assertEqual(universe["historical_membership_mode"], "static_backfilled")
        self.assertGreater(len(universe["prohibited_claims"]), 0)

    def test_reserved_period_is_not_held_out_by_default(self) -> None:
        reserved = self.config["time_partitions"][
            "historical_reserved_evaluation_candidate"
        ]
        self.assertFalse(reserved["held_out_eligible"])
        self.assertEqual(
            reserved["eligibility_status"], "pending_information_exposure_audit"
        )

    def test_d0_eligibility_requires_verified_membership_evidence(self) -> None:
        changed = deepcopy(self.config)
        changed["decision_status"] = "accepted"
        changed["operational_status"] = "eligible_for_d0"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_verified_membership_status_requires_complete_evidence(self) -> None:
        changed = deepcopy(self.config)
        changed["universe"]["membership_evidence"]["status"] = "verified"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_fixed_partition_boundaries_cannot_drift(self) -> None:
        changed = deepcopy(self.config)
        changed["time_partitions"]["design"]["end"] = "2022-12-31"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_prospective_start_cannot_be_prefilled(self) -> None:
        changed = deepcopy(self.config)
        changed["time_partitions"]["prospective"]["start"] = "2026-07-01"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
