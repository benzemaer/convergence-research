from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_SQL_PATH = ROOT / "sql/duckdb/schema.sql"
DEFAULT_DB_PATH = ROOT / "data/interim/duckdb/convergence.duckdb"


def load_schema_sql(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"schema SQL file does not exist: {path}")
    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        raise ValueError(f"schema SQL file is empty: {path}")
    return sql


def list_tables(connection: duckdb.DuckDBPyConnection) -> list[str]:
    rows = connection.execute(
        """
        SELECT table_schema || '.' || table_name AS table_name
        FROM information_schema.tables
        WHERE table_schema IN ('meta', 'd0', 'd1', 'd2', 'd3')
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name
        """
    ).fetchall()
    return [row[0] for row in rows]


def create_empty_duckdb(
    db_path: Path,
    schema_sql_path: Path = DEFAULT_SCHEMA_SQL_PATH,
    *,
    overwrite: bool = True,
) -> list[str]:
    schema_sql = load_schema_sql(schema_sql_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and db_path.exists():
        db_path.unlink()
    wal_path = db_path.with_name(f"{db_path.name}.wal")
    if overwrite and wal_path.exists():
        wal_path.unlink()

    with duckdb.connect(str(db_path)) as connection:
        connection.execute(schema_sql)
        return list_tables(connection)


def check_schema_sql(schema_sql_path: Path = DEFAULT_SCHEMA_SQL_PATH) -> list[str]:
    schema_sql = load_schema_sql(schema_sql_path)
    with duckdb.connect(":memory:") as connection:
        connection.execute(schema_sql)
        return list_tables(connection)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an empty DuckDB warehouse schema without loading data."
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Output DuckDB path. Defaults to data/interim/duckdb/convergence.duckdb.",
    )
    parser.add_argument(
        "--schema-sql-path",
        type=Path,
        default=DEFAULT_SCHEMA_SQL_PATH,
        help="Schema SQL file to execute.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate schema SQL in memory without creating a database file.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Keep an existing database file and apply the schema if missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        tables = check_schema_sql(args.schema_sql_path)
        target = ":memory:"
    else:
        tables = create_empty_duckdb(
            args.db_path,
            args.schema_sql_path,
            overwrite=not args.no_overwrite,
        )
        target = str(args.db_path)

    print(f"duckdb_schema_target={target}")
    print("duckdb_tables=")
    for table in tables:
        print(f"- {table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
