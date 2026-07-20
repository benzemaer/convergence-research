"""Synthetic-only support for R2A-T04 tests."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import duckdb

from tests.r2a.r2a_t03_test_support import create_source

MARKET_QUERY = """
SELECT
  security_id::VARCHAR security_id,
  trading_date::DATE trading_date,
  raw_open::DOUBLE raw_open,
  raw_high::DOUBLE raw_high,
  raw_low::DOUBLE raw_low,
  raw_close::DOUBLE raw_close,
  adj_open::DOUBLE adj_open,
  adj_high::DOUBLE adj_high,
  adj_low::DOUBLE adj_low,
  adj_close::DOUBLE adj_close,
  volume_shares::DOUBLE volume_shares,
  amount_yuan::DOUBLE amount_yuan,
  turnover_float::DOUBLE turnover_float,
  tradable_flag::BOOLEAN tradable_flag,
  is_suspended::BOOLEAN is_suspended,
  price_limit_status::VARCHAR price_limit_status
FROM market_data
""".strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_score_database(path: Path) -> None:
    connection = create_source(str(path))
    connection.execute(
        "CREATE TABLE daily_component_scores AS "
        "SELECT security_id,trading_date,dimension_id,component_id,"
        "score_dimension raw_value,score_dimension percentile,"
        "score_dimension score,eligible_dimension eligible,validity_status,"
        "reason_codes FROM daily_dimension_scores "
        "CROSS JOIN (VALUES ('A'),('B')) components(component_id)"
    )
    connection.execute(
        "CREATE TABLE securities AS SELECT DISTINCT security_id "
        "FROM security_observation_spine"
    )
    connection.execute("CHECKPOINT")
    connection.close()


def create_market_database(path: Path, score_path: Path) -> dict[str, object]:
    market = duckdb.connect(str(path))
    market.execute(
        "CREATE TABLE market_data(security_id VARCHAR,trading_date DATE,"
        "raw_open DOUBLE,raw_high DOUBLE,raw_low DOUBLE,raw_close DOUBLE,"
        "adj_open DOUBLE,adj_high DOUBLE,adj_low DOUBLE,adj_close DOUBLE,"
        "volume_shares DOUBLE,amount_yuan DOUBLE,turnover_float DOUBLE,"
        "tradable_flag BOOLEAN,is_suspended BOOLEAN,price_limit_status VARCHAR)"
    )
    with duckdb.connect(str(score_path), read_only=True) as score:
        rows = score.execute(
            "SELECT security_id,trading_date FROM security_observation_spine "
            "WHERE expected_observation_status='present' ORDER BY 1,2"
        ).fetchall()
    expanded: list[tuple[object, ...]] = []
    by_security: dict[str, list[object]] = {}
    for security_id, trading_date in rows:
        by_security.setdefault(str(security_id), []).append(trading_date)
    for security_id, dates in by_security.items():
        first = min(dates)
        full_dates = [first + timedelta(days=index) for index in range(50)]
        for index, trading_date in enumerate(full_dates):
            price = 10.0 + index * 0.02
            expanded.append(
                (
                    security_id,
                    trading_date,
                    price,
                    price * 1.01,
                    price * 0.99,
                    price,
                    price,
                    price * 1.01,
                    price * 0.99,
                    price,
                    1_000_000.0 - index * 1_000,
                    price * (1_000_000.0 - index * 1_000),
                    0.01,
                    True,
                    False,
                    "none",
                )
            )
    market.executemany(
        "INSERT INTO market_data VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", expanded
    )
    market.execute("CHECKPOINT")
    market.close()
    return {
        "source_id": "synthetic-market-v1",
        "database_basename": path.name,
        "database_sha256": _sha256(path),
        "database_byte_size": path.stat().st_size,
        "source_snapshot_id": "synthetic-snapshot-v1",
        "source_query": MARKET_QUERY,
        "column_mapping": {
            name: name
            for name in (
                "security_id",
                "trading_date",
                "raw_open",
                "raw_high",
                "raw_low",
                "raw_close",
                "adj_open",
                "adj_high",
                "adj_low",
                "adj_close",
                "volume_shares",
                "amount_yuan",
                "turnover_float",
                "tradable_flag",
                "is_suspended",
                "price_limit_status",
            )
        },
        "unit_mapping": {
            "price": "CNY_per_share",
            "volume_shares": "shares",
            "amount_yuan": "CNY",
            "turnover_float": "ratio",
        },
        "date_coverage": {
            "date_min": str(min(row[1] for row in expanded)),
            "date_max": str(max(row[1] for row in expanded)),
        },
        "security_coverage": {
            "security_count": 800,
            "scope": "accepted_score_spine_present_keys",
        },
    }
