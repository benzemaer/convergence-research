from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d0_source_registry.schema.json"
CONFIG_PATH = ROOT / "configs/d0/source_registry.v1.json"
REQUIRED_SOURCE_IDS = {
    "CSINDEX_OFFICIAL",
    "A_STOCK_DATA_RECON",
    "HITHINK_FINANCIAL_API",
    "BAOSTOCK",
}


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D0SourceRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def source(self, source_registry_id: str) -> dict[str, object]:
        for source in self.config["sources"]:
            if source["source_registry_id"] == source_registry_id:
                return source
        self.fail(f"missing source {source_registry_id}")

    def test_source_registry_config_is_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.config)

    def test_required_sources_are_registered(self) -> None:
        source_ids = {source["source_registry_id"] for source in self.config["sources"]}
        self.assertTrue(REQUIRED_SOURCE_IDS.issubset(source_ids))

    def test_source_registry_ids_are_unique(self) -> None:
        source_ids = [source["source_registry_id"] for source in self.config["sources"]]
        self.assertEqual(len(source_ids), len(set(source_ids)))

    def test_every_source_requires_raw_snapshot_and_hash(self) -> None:
        for source in self.config["sources"]:
            with self.subTest(source=source["source_registry_id"]):
                self.assertTrue(source["raw_snapshot_required"])
                self.assertTrue(source["hash_required"])

    def test_csindex_is_limited_to_membership_evidence(self) -> None:
        source = self.source("CSINDEX_OFFICIAL")
        self.assertEqual(
            source["qualification_status"],
            "approved_limited_g0_evidence",
        )
        self.assertIn("universe_membership_evidence", source["allowed_uses"])
        self.assertIn("market_price_source", source["prohibited_uses"])
        self.assertNotIn("market_prices", source["covered_fact_domains"])

    def test_a_stock_data_is_not_a_formal_data_source(self) -> None:
        source = self.source("A_STOCK_DATA_RECON")
        self.assertEqual(source["source_kind"], "wrapper_or_endpoint_recon_tool")
        self.assertEqual(source["qualification_status"], "endpoint_research_only")
        self.assertEqual(source["candidate_tables"], [])
        self.assertIn("formal_data_source", source["prohibited_uses"])

    def test_hithink_is_blocked_until_terms_and_revision_review(self) -> None:
        source = self.source("HITHINK_FINANCIAL_API")
        self.assertTrue(source["authentication_required"])
        self.assertEqual(source["terms_review_status"], "pending")
        self.assertEqual(
            source["qualification_status"],
            "formal_candidate_pending_terms_review",
        )
        self.assertIn(
            "formal_data_ingestion_before_terms_approval",
            source["prohibited_uses"],
        )
        self.assertIn("revision", source["revision_policy"].lower())

    def test_baostock_is_backup_or_cross_validation_candidate(self) -> None:
        source = self.source("BAOSTOCK")
        self.assertFalse(source["authentication_required"])
        self.assertEqual(
            source["qualification_status"],
            "backup_candidate_pending_review",
        )
        self.assertIn("cross_validation_candidate", source["allowed_uses"])
        self.assertIn(
            "sole_formal_primary_source_before_revision_review",
            source["prohibited_uses"],
        )

    def test_missing_required_field_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        del changed["sources"][0]["revision_policy"]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_wrapper_cannot_be_promoted_by_config_only(self) -> None:
        changed = deepcopy(self.config)
        for source in changed["sources"]:
            if source["source_registry_id"] == "A_STOCK_DATA_RECON":
                source["qualification_status"] = "formal_candidate_pending_terms_review"
                break
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_formal_candidates_must_keep_review_gate(self) -> None:
        changed = deepcopy(self.config)
        for source in changed["sources"]:
            if source["source_registry_id"] == "HITHINK_FINANCIAL_API":
                source["review_required_before_use"] = False
                break
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
