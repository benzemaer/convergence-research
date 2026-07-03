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
GLOBAL_FIELDS = {
    "data_version",
    "universe_id",
    "time_segment_id",
    "source_registry_id",
    "source_snapshot_id",
    "run_id",
}
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


def load_contract_tables() -> dict[str, dict[str, object]]:
    with CONTRACT_PATH.open(encoding="utf-8") as handle:
        contract = json.load(handle)
    return {table["table_name"]: table for table in contract["tables"]}


class DuckDBSchemaContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract_tables = load_contract_tables()
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
        schema, table = table_name.split(".", maxsplit=1)
        rows = self.connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = ?
              AND table_name = ?
            """,
            [schema, table],
        ).fetchall()
        return {row[0] for row in rows}

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

    def test_tables_cover_contract_required_fields_and_primary_keys(self) -> None:
        for table_name, contract in self.contract_tables.items():
            with self.subTest(table=table_name):
                columns = self.table_columns(table_name)
                required_fields = set(contract["required_fields"])
                primary_key = set(contract["primary_key"])
                self.assertTrue(required_fields.issubset(columns))
                self.assertTrue(primary_key.issubset(columns))
                self.assertTrue(GLOBAL_FIELDS.issubset(columns))
                self.assertEqual(self.primary_key_columns(table_name), primary_key)

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
