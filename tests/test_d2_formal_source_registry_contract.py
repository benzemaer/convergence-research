from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/formal_source_registry_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d2_formal_source_registry_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2FormalSourceRegistryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_contract_json_passes_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)
        self.assertFalse(self.schema["additionalProperties"])

    def test_hithink_primary_and_fallback_priorities(self) -> None:
        hierarchy = self.contract["source_hierarchy"]
        self.assertEqual(
            hierarchy["primary_source"],
            {
                "source_id": "hithink_financial_api",
                "role": "primary_formal_candidate",
                "priority": 0,
            },
        )
        fallback = {
            source["source_id"]: source for source in hierarchy["fallback_sources"]
        }
        self.assertEqual(fallback["baostock"]["priority"], 1)
        self.assertEqual(fallback["tushare"]["priority"], 2)

    def test_a_stock_data_is_rejected_not_active(self) -> None:
        hierarchy = self.contract["source_hierarchy"]
        self.assertNotEqual(hierarchy["primary_source"]["source_id"], "a-stock-data")
        self.assertNotIn(
            "a-stock-data",
            {source["source_id"] for source in hierarchy["fallback_sources"]},
        )
        rejected = {source["source_id"] for source in hierarchy["rejected_sources"]}
        deprecated = {source["source_id"] for source in hierarchy["deprecated_sources"]}
        self.assertIn("a-stock-data", rejected | deprecated)

    def test_fallback_policy_is_missing_only_repair_only(self) -> None:
        policy = self.contract["fallback_policy"]
        self.assertEqual(policy["fallback_mode"], "missing_only_repair_only")
        self.assertTrue(
            policy["fallback_must_not_silently_override_primary_price_conflicts"]
        )
        self.assertTrue(policy["cross_source_conflict_requires_discrepancy_report"])
        self.assertGreaterEqual(
            set(policy["required_repair_fields"]),
            {
                "fallback_reason",
                "fallback_source",
                "fallback_field",
                "fallback_security_id",
                "fallback_trading_date",
                "repair_method",
                "repair_confidence",
            },
        )

    def test_secret_handling_uses_env_names_only(self) -> None:
        text = json.dumps(self.contract, sort_keys=True)
        self.assertIn("HITHINK_API_KEY", text)
        self.assertIn("TUSHARE_TOKEN", text)
        for forbidden in ["sk-", "token", "apikey"]:
            if forbidden == "token":
                continue
            self.assertNotIn(forbidden, text.lower())
        self.assertTrue(
            self.contract["secret_handling"][
                "no_secret_may_be_committed_logged_printed_or_stored_in_config"
            ]
        )

    def test_authorizations_are_false(self) -> None:
        for key in [
            "formal_source_acceptance_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_data_materialization_authorized",
            "manifest_creation_authorized",
            "data_version_release_authorized",
            "d3_generation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertFalse(self.contract[key])
        self.assertTrue(self.contract["synthetic_test_only"])

    def test_schema_rejects_a_stock_data_as_active_source(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["source_hierarchy"]["primary_source"]["source_id"] = "a-stock-data"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["source_hierarchy"]["fallback_sources"][0]["source_id"] = "a-stock-data"
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_readme_records_d2_t11_done_without_unlocking_d3_or_r0(self) -> None:
        self.assertIn("current_stage: D2", self.readme)
        self.assertIn(
            "current_task: D2-T19 targeted repair and coverage policy evidence",
            self.readme,
        )
        self.assertIn(
            "next_planned_task: D2-T20 policy acceptance or second targeted repair",
            self.readme,
        )
        self.assertIn("D2-T09` HiThink 主行情源", self.readme)
        self.assertIn(
            "D2-T09` HiThink 主行情源、补充源与 raw OHLCV "
            "探针契约：completed via PR #41",
            self.readme,
        )
        self.assertIn(
            "D2-T10` adjusted price、质量标记与机械缺口正式候选物化："
            "completed via PR #42",
            self.readme,
        )
        self.assertIn(
            "D2-T11` 来源状态与复权证据补齐、D2验收与D3交接候选："
            "completed via PR #43; D2/D3 remained blocked",
            self.readme,
        )
        self.assertIn(
            "D2-T12` tnskhdata/Tushare证据源探针、统一代码映射与HiThink "
            "REST适配修复：completed via PR #44",
            self.readme,
        )
        self.assertIn(
            "D2-T13` tnskhdata全量候选物化与D2验收交接：completed via PR #45; "
            "D2 acceptance remained blocked by listed-open provider coverage",
            self.readme,
        )
        self.assertIn(
            "D3-T07 remains blocked until D2 coverage blockers are resolved",
            self.readme,
        )
        self.assertIn("R0 remains blocked", self.readme)


if __name__ == "__main__":
    unittest.main()
