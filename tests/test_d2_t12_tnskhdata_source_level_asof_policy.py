from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from scripts.run_d2_t12_provider_remediation_probe import (
    source_level_factor_as_of_time,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = (
    ROOT / "configs/d2/tnskhdata_source_level_asof_snapshot_revision_policy.v1.json"
)
SCHEMA = (
    ROOT / "schemas/d2_tnskhdata_source_level_asof_snapshot_revision_policy.schema.json"
)


class D2T12TnskhdataSourceLevelAsofPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = json.loads(POLICY.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.validator = Draft202012Validator(cls.schema)

    def test_policy_passes_schema_and_accepts_source_level_asof(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.policy)
        self.assertEqual(
            self.policy["as_of_policy"]["adj_factor_source_level_as_of_time"],
            "trade_date 09:20:00 Asia/Shanghai",
        )
        self.assertFalse(
            self.policy["as_of_policy"]["row_level_factor_as_of_time_available"]
        )
        self.assertEqual(
            self.policy["revision_policy"]["revision_class"],
            "snapshot_level_revision",
        )
        self.assertEqual(
            self.policy["point_in_time_policy"]["eligibility_class"],
            "source_level_asof_snapshot_revision",
        )

    def test_schema_rejects_row_level_revision_claim(self) -> None:
        changed = copy.deepcopy(self.policy)
        changed["revision_policy"]["provider_row_level_revision_available"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_asof_time_uses_trade_date_0920_shanghai(self) -> None:
        self.assertEqual(
            source_level_factor_as_of_time("2026-07-02"),
            "20260702 09:20:00 Asia/Shanghai",
        )


if __name__ == "__main__":
    unittest.main()
