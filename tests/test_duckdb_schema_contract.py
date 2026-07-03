from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import duckdb

from scripts.create_duckdb_schema import (
    create_empty_duckdb,
    list_tables,
    load_schema_sql,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d0/data_product_contracts.v1.json"
SCHEMA_SQL_PATH = ROOT / "sql/duckdb/schema.sql"
EXPECTED_SCHEMAS = {"meta", "d0", "d1", "d2", "d3"}
D3_SOURCE_FIELDS = {
    "price_fact_source",
    "corporate_action_source",
    "membership_source",
    "calendar_source",
    "revision_policy",
    "observed_at_rule",
}
PROHIBITED_FIELD_NAMES = {
    "raw_bytes",
    "raw_response",
    "api_response",
    "response_body",
    "vendor_payload",
    "payload_blob",
}
PROHIBITED_TABLE_TOKENS = {
    "raw_bytes",
    "raw_response",
    "vendor_payload",
    "api_response_body",
}


def load_contract() -> dict[str, object]:
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


class DuckDBSchemaContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_contract()
        cls.contract_tables = {
            table["table_name"]: table for table in cls.contract["tables"]
        }
        cls.global_fields = set(
            cls.contract["global_requirements"]["required_in_all_formal_tables"]
        )
        cls.schema_sql = load_schema_sql(SCHEMA_SQL_PATH)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "empty.duckdb"
        tables = create_empty_duckdb(self.db_path, SCHEMA_SQL_PATH)
        self.connection = duckdb.connect(str(self.db_path))
        self.addCleanup(self.connection.close)
        self.created_tables = set(tables)

    def table_columns(self, table_name: str) -> set[str]:
        return set(self.table_column_nullability(table_name))

    def table_column_nullability(self, table_name: str) -> dict[str, str]:
        schema, table = table_name.split(".", maxsplit=1)
        rows = self.connection.execute(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = ?
              AND table_name = ?
            """,
            [schema, table],
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def primary_key_columns(self, table_name: str) -> set[str]:
        schema, table = table_name.split(".", maxsplit=1)
        rows = self.connection.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
             AND tc.table_name = kcu.table_name
            WHERE tc.table_schema = ?
              AND tc.table_name = ?
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """,
            [schema, table],
        ).fetchall()
        return {row[0] for row in rows}

    def test_schema_sql_executes_and_creates_contract_tables(self) -> None:
        self.assertTrue(self.db_path.is_file())
        self.assertEqual(self.created_tables, set(self.contract_tables))
        self.assertEqual(set(list_tables(self.connection)), set(self.contract_tables))

    def test_required_schemas_exist(self) -> None:
        rows = self.connection.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            """
        ).fetchall()
        schemas = {row[0] for row in rows}
        self.assertTrue(EXPECTED_SCHEMAS.issubset(schemas))

    def test_tables_cover_contract_required_fields_and_primary_keys(self) -> None:
        for table_name, contract in self.contract_tables.items():
            with self.subTest(table=table_name):
                columns = self.table_columns(table_name)
                required_fields = set(contract["required_fields"])
                primary_key = set(contract["primary_key"])
                self.assertTrue(required_fields.issubset(columns))
                self.assertTrue(primary_key.issubset(columns))
                self.assertTrue(self.global_fields.issubset(columns))
                self.assertEqual(self.primary_key_columns(table_name), primary_key)

    def test_tables_do_not_add_columns_outside_contract_required_fields(self) -> None:
        for table_name, contract in self.contract_tables.items():
            with self.subTest(table=table_name):
                self.assertEqual(
                    self.table_columns(table_name),
                    set(contract["required_fields"]),
                )

    def test_required_non_nullable_contract_fields_are_not_null(self) -> None:
        for table_name, contract in self.contract_tables.items():
            with self.subTest(table=table_name):
                nullability = self.table_column_nullability(table_name)
                required_fields = set(contract["required_fields"])
                nullable_fields = set(contract["nullable_fields"])
                not_null_fields = required_fields - nullable_fields

                for field in not_null_fields:
                    self.assertEqual(nullability[field], "NO")
                for field in nullable_fields:
                    self.assertIn(nullability[field], {"YES", "NO"})

    def test_d3_daily_market_observations_has_r0_entry_source_fields(self) -> None:
        columns = self.table_columns("d3.daily_market_observations")
        self.assertTrue(D3_SOURCE_FIELDS.issubset(columns))

    def test_schema_has_no_raw_byte_or_vendor_payload_storage(self) -> None:
        normalized_sql = self.schema_sql.lower()
        for token in PROHIBITED_FIELD_NAMES | PROHIBITED_TABLE_TOKENS:
            with self.subTest(token=token):
                self.assertNotRegex(normalized_sql, rf"\b{re.escape(token)}\b")

        for table_name in self.created_tables:
            with self.subTest(table=table_name):
                self.assertFalse(PROHIBITED_TABLE_TOKENS.intersection(table_name))
                self.assertFalse(
                    PROHIBITED_FIELD_NAMES.intersection(self.table_columns(table_name))
                )

    def test_empty_schema_contains_no_entity_rows(self) -> None:
        for table_name in self.contract_tables:
            with self.subTest(table=table_name):
                count = self.connection.execute(
                    f"SELECT COUNT(*) FROM {table_name}"
                ).fetchone()[0]
                self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
