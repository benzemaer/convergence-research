from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_csi800_static_membership_reference.schema.json"
CONFIG_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_reference.v1.json"
MEMBERSHIP_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)
FIELD_ALIAS_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json"
)
REFERENCE_CONTRACT_PATH = (
    ROOT
    / "configs/d1/csi800_static_2026_06_security_mapping_reference_contract.v1.json"
)
OUTPUT_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_contract.v1.json"
)
OUTPUT_REPORT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_report.v1.json"
)

EXPECTED_MEMBER_FIELDS = {
    "member_ordinal",
    "universe_id",
    "membership_effective_date",
    "source_registry_id",
    "source_snapshot_id",
    "source_symbol",
    "ticker",
    "exchange",
    "security_id",
    "security_id_mapping_reference",
    "mapping_method",
    "mapping_status",
    "membership_status",
}
PROHIBITED_ROW_FIELDS = {
    "成份券名称",
    "Constituent Name",
    "指数名称",
    "Index Name",
    "交易所英文名称Exchange(Eng)",
    "weight",
    "open",
    "close",
    "volume",
    "industry",
    "corporate_action",
    "adjustment_factor",
}


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D1CSI800StaticMembershipReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.membership_contract = load(MEMBERSHIP_CONTRACT_PATH)
        cls.field_alias_contract = load(FIELD_ALIAS_CONTRACT_PATH)
        cls.reference_contract = load(REFERENCE_CONTRACT_PATH)
        cls.output_contract = load(OUTPUT_CONTRACT_PATH)
        cls.output_report = load(OUTPUT_REPORT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_schema_and_config_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_top_level_contract_chain_aligns(self) -> None:
        universe = self.membership_contract["universe"]
        evidence = self.membership_contract["source_evidence"]
        self.assertEqual(self.config["universe_id"], universe["universe_id"])
        self.assertEqual(self.config["index_code"], universe["index_code"])
        self.assertEqual(self.config["index_alias"], universe["index_alias"])
        self.assertEqual(
            self.config["membership_effective_date"],
            universe["membership_effective_date"],
        )
        self.assertEqual(
            self.config["source_registry_id"],
            evidence["source_registry_id"],
        )
        self.assertEqual(
            self.config["source_snapshot_id"],
            evidence["source_snapshot_id"],
        )
        self.assertEqual(
            self.config["raw_evidence_sha256"],
            evidence["raw_evidence_sha256"],
        )
        self.assertEqual(
            self.config["field_alias_contract_id"],
            self.field_alias_contract["contract_id"],
        )
        self.assertEqual(
            self.config["security_mapping_reference_contract_id"],
            self.reference_contract["contract_id"],
        )
        self.assertEqual(
            self.config["security_mapping_output_contract_id"],
            self.output_contract["contract_id"],
        )
        self.assertEqual(
            self.config["security_mapping_output_report_id"],
            self.output_report["report_id"],
        )
        self.assertEqual(self.output_report["report_status"], "passed")

    def test_member_count_and_ordinals_are_exact(self) -> None:
        members = self.config["members"]
        self.assertEqual(self.config["member_count"], 800)
        self.assertEqual(len(members), 800)
        self.assertEqual(
            [member["member_ordinal"] for member in members],
            list(range(1, 801)),
        )

    def test_all_member_rows_use_canonical_fields_and_constants(self) -> None:
        for member in self.config["members"]:
            with self.subTest(member_ordinal=member["member_ordinal"]):
                self.assertEqual(set(member), EXPECTED_MEMBER_FIELDS)
                self.assertEqual(member["universe_id"], "CSI800_STATIC_2026_06")
                self.assertEqual(member["membership_effective_date"], "2026-06-12")
                self.assertEqual(member["source_registry_id"], "CSINDEX_OFFICIAL")
                self.assertEqual(
                    member["source_snapshot_id"],
                    "CSINDEX_000906_20260703T100909Z",
                )
                self.assertEqual(member["mapping_status"], "mapped")
                self.assertEqual(
                    member["mapping_method"],
                    "ticker_exchange_effective_date_to_d1_security_master",
                )
                self.assertEqual(
                    member["membership_status"],
                    "active_static_member",
                )

    def test_security_identifiers_are_valid_and_unique(self) -> None:
        security_ids = set()
        membership_keys = set()
        source_symbol_keys = set()
        for member in self.config["members"]:
            ticker = member["ticker"]
            exchange = member["exchange"]
            security_id = member["security_id"]
            self.assertRegex(ticker, r"^[0-9]{6}$")
            self.assertIn(exchange, {"SSE", "SZSE"})
            self.assertEqual(security_id, f"CN.{exchange}.{ticker}")
            self.assertRegex(security_id, r"^CN\.(SSE|SZSE)\.[0-9]{6}$")
            security_ids.add(security_id)
            membership_keys.add(
                (
                    member["universe_id"],
                    member["membership_effective_date"],
                    security_id,
                )
            )
            source_symbol_keys.add(
                (member["source_symbol"], member["ticker"], member["exchange"])
            )
        self.assertEqual(len(security_ids), 800)
        self.assertEqual(len(membership_keys), 800)
        self.assertEqual(len(source_symbol_keys), 800)

    def test_no_raw_payload_or_market_fields_are_committed(self) -> None:
        for member in self.config["members"]:
            self.assertFalse(PROHIBITED_ROW_FIELDS & set(member))

    def test_no_duckdb_or_manifest_flags_are_false(self) -> None:
        self.assertTrue(self.config["row_level_membership_reference_committed"])
        self.assertFalse(self.config["raw_bytes_committed"])
        self.assertFalse(self.config["duckdb_written"])
        self.assertFalse(self.config["run_manifest_created"])
        self.assertFalse(self.config["dataset_manifest_created"])
        self.assertTrue(self.config["d2_usage_authorized"])

    def test_schema_rejects_extra_row_field(self) -> None:
        changed = deepcopy(self.config)
        changed["members"][0]["Constituent Name"] = "forbidden"
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_schema_rejects_invalid_ticker_exchange_or_security_id(self) -> None:
        changes = (
            ("ticker", "1"),
            ("exchange", "SH"),
            ("security_id", "000001.SZ"),
            ("mapping_status", "unmapped"),
            ("membership_status", "inactive"),
        )
        for field, value in changes:
            changed = deepcopy(self.config)
            changed["members"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_schema_rejects_wrong_member_count_or_flags(self) -> None:
        changes = (
            ("member_count", 799),
            ("raw_bytes_committed", True),
            ("duckdb_written", True),
            ("run_manifest_created", True),
            ("dataset_manifest_created", True),
            ("d2_usage_authorized", False),
        )
        for field, value in changes:
            changed = deepcopy(self.config)
            changed[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_source_symbols_are_not_market_data_values(self) -> None:
        for member in self.config["members"]:
            self.assertTrue(re.fullmatch(r"[0-9]{6}", member["source_symbol"]))


if __name__ == "__main__":
    unittest.main()
