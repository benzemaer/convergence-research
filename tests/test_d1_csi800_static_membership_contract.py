from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_csi800_static_membership_contract.schema.json"
CONFIG_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
G0_CONFIG_PATH = ROOT / "configs/g0/universe_time_boundaries.v1.json"
D0_CONTRACT_PATH = ROOT / "configs/d0/data_product_contracts.v1.json"

EXPECTED_IMPLEMENTATION_EXCLUSIONS = {
    "no_loader",
    "no_external_api_call",
    "no_real_data_import",
    "no_market_data_import",
    "no_duckdb_entity_data",
    "no_committed_duckdb_file",
    "no_network_access",
    "no_manifest",
    "no_membership_rows_materialized",
}
EXPECTED_FIELD_TYPES = {
    "data_version": "TEXT",
    "universe_id": "TEXT",
    "time_segment_id": "TEXT",
    "security_id": "TEXT",
    "index_code": "TEXT",
    "membership_effective_date": "DATE",
    "membership_mode": "TEXT",
    "membership_source": "TEXT",
    "source_registry_id": "TEXT",
    "source_snapshot_id": "TEXT",
    "run_id": "TEXT",
}


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def d0_membership_contract() -> dict[str, object]:
    d0_contract = load(D0_CONTRACT_PATH)
    for table in d0_contract["tables"]:
        if table["table_name"] == "d2.membership_alignment":
            return table
    raise AssertionError("missing d2.membership_alignment in D0 contract")


class D1CSI800StaticMembershipContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.g0_config = load(G0_CONFIG_PATH)
        cls.d0_table = d0_membership_contract()
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_csi800_static_membership_contract_config_is_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_universe_values_match_g0_approved_config(self) -> None:
        universe = self.config["universe"]
        g0_universe = self.g0_config["universe"]
        g0_evidence = g0_universe["membership_evidence"]

        self.assertEqual(universe["universe_id"], "CSI800_STATIC_2026_06")
        self.assertEqual(universe["universe_id"], g0_universe["universe_id"])
        self.assertEqual(universe["index_code"], g0_evidence["index_code"])
        self.assertEqual(universe["index_alias"], "CSI800")
        self.assertEqual(universe["membership_mode"], "static_cohort")
        self.assertFalse(universe["historical_membership_claim_allowed"])
        self.assertEqual(
            universe["membership_effective_date"],
            g0_evidence["effective_date"],
        )
        self.assertEqual(universe["expected_member_count"], 800)

    def test_source_evidence_matches_g0_reviewed_evidence(self) -> None:
        evidence = self.config["source_evidence"]
        g0_evidence = self.g0_config["universe"]["membership_evidence"]

        self.assertEqual(self.g0_config["operational_status"], "eligible_for_d0")
        self.assertEqual(self.g0_config["g0_review"]["status"], "approved")
        self.assertEqual(g0_evidence["status"], "verified")
        self.assertEqual(evidence["source_registry_id"], "CSINDEX_OFFICIAL")
        self.assertEqual(evidence["raw_evidence_path"], g0_evidence["file_path"])
        self.assertEqual(evidence["raw_evidence_sha256"], g0_evidence["file_sha256"])
        self.assertEqual(
            evidence["review_commit"],
            self.g0_config["g0_review"]["review_commit"],
        )

    def test_membership_alignment_fields_match_d0_contract(self) -> None:
        alignment = self.config["membership_alignment_contract"]
        self.assertEqual(alignment["target_table"], "d2.membership_alignment")
        self.assertEqual(
            set(alignment["field_semantics"]),
            set(self.d0_table["required_fields"]),
        )
        self.assertEqual(alignment["primary_key"], self.d0_table["primary_key"])
        self.assertEqual(self.d0_table["nullable_fields"], [])

    def test_membership_alignment_field_types_are_explicit(self) -> None:
        fields = self.config["membership_alignment_contract"]["field_semantics"]
        self.assertEqual(set(EXPECTED_FIELD_TYPES), set(fields))
        for field_name, expected_type in EXPECTED_FIELD_TYPES.items():
            with self.subTest(field=field_name):
                self.assertEqual(fields[field_name]["type"], expected_type)
                self.assertFalse(fields[field_name]["nullable"])

    def test_required_mapping_fields_are_declared_without_inventing_security_id(
        self,
    ) -> None:
        alignment = self.config["membership_alignment_contract"]
        self.assertEqual(
            set(alignment["required_mapping_fields"]),
            {
                "source_symbol",
                "ticker",
                "exchange",
                "security_id_mapping_reference",
            },
        )
        non_goals = "\n".join(alignment["non_goals"])
        self.assertIn("Do not expand the universe", non_goals)
        self.assertIn("Do not process security_master details", non_goals)

    def test_source_registry_boundaries_are_csindex_only(self) -> None:
        requirements = self.config["source_registry_requirements"]
        self.assertEqual(
            requirements["allowed_source_registry_ids"],
            ["CSINDEX_OFFICIAL"],
        )
        self.assertIn(
            "HITHINK_FINANCIAL_API", requirements["prohibited_source_registry_ids"]
        )
        self.assertIn("BAOSTOCK", requirements["prohibited_source_registry_ids"])
        self.assertIn(
            "A_STOCK_DATA_RECON", requirements["prohibited_source_registry_ids"]
        )
        self.assertFalse(requirements["formal_ingestion_authorized"])
        self.assertFalse(requirements["materialization_authorized"])
        self.assertEqual(
            set(requirements["csindex_official_authorized_domains"]),
            {"universe_membership_evidence", "d2.membership_alignment"},
        )

    def test_csindex_is_not_authorized_for_other_fact_domains(self) -> None:
        prohibited_domains = set(
            self.config["source_registry_requirements"]["prohibited_fact_domains"]
        )
        self.assertTrue(
            {
                "market_prices",
                "trading_status",
                "corporate_actions",
                "adjustment_factors",
            }.issubset(prohibited_domains)
        )

    def test_static_cohort_bias_warning_and_d3_boundary_are_explicit(self) -> None:
        warnings = "\n".join(self.config["bias_and_scope_warnings"])
        self.assertIn("static research cohort", warnings)
        self.assertIn("not historical point-in-time", warnings)
        self.assertIn("Survivorship", warnings)
        self.assertIn("D3", self.config["downstream_boundary"]["d3_entry_rule"])
        self.assertIn(
            "must not read raw G0 evidence",
            self.config["downstream_boundary"]["d3_entry_rule"],
        )

    def test_implementation_exclusions_block_loader_network_and_duckdb(self) -> None:
        self.assertEqual(
            set(self.config["implementation_exclusions"]),
            EXPECTED_IMPLEMENTATION_EXCLUSIONS,
        )
        self.assertFalse(self.config["member_rows_materialized"])
        self.assertFalse(self.config["materialization_authorized"])
        self.assertIn("ignored data/external", self.config["blocked_reason"])
        self.assertIn(
            "no reviewable, reproducible materialization input",
            self.config["blocked_reason"],
        )
        self.assertIn("run manifest", self.config["source_evidence"]["run_id_policy"])

    def test_allowing_a_stock_data_as_source_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["source_registry_requirements"]["allowed_source_registry_ids"].append(
            "A_STOCK_DATA_RECON"
        )
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_allowing_hithink_or_baostock_as_source_is_rejected(self) -> None:
        for source_id in ("HITHINK_FINANCIAL_API", "BAOSTOCK"):
            changed = deepcopy(self.config)
            changed["source_registry_requirements"][
                "allowed_source_registry_ids"
            ].append(source_id)
            with self.subTest(source_id=source_id):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_claiming_historical_index_membership_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["universe"]["membership_mode"] = "historical_index_membership"
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_removing_static_cohort_bias_warning_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["bias_and_scope_warnings"] = [
            warning
            for warning in changed["bias_and_scope_warnings"]
            if "static research cohort" not in warning
        ]
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_authorizing_materialization_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["materialization_authorized"] = True
        changed["source_registry_requirements"]["materialization_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_removing_loader_network_or_membership_row_boundary_is_rejected(
        self,
    ) -> None:
        for exclusion in (
            "no_loader",
            "no_network_access",
            "no_manifest",
            "no_membership_rows_materialized",
        ):
            changed = deepcopy(self.config)
            changed["implementation_exclusions"] = [
                value
                for value in changed["implementation_exclusions"]
                if value != exclusion
            ]
            with self.subTest(exclusion=exclusion):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_authorizing_csindex_for_price_or_status_domains_is_rejected(self) -> None:
        for domain in ("market_prices", "corporate_actions", "trading_status"):
            changed = deepcopy(self.config)
            changed["source_registry_requirements"][
                "csindex_official_authorized_domains"
            ].append(domain)
            with self.subTest(domain=domain):
                with self.assertRaises(ValidationError):
                    self.validate(changed)


if __name__ == "__main__":
    unittest.main()
