from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from src.r2a.r2a_t03_dynamic_evaluator import evaluate_dynamic_request
from src.r2a.r2a_t04_request_panel import build_request_panel
from src.r2a.r2a_t04_score_audit import (
    deterministic_interval_samples,
    initialize_score_audit_database,
    run_ca_q_response_checks_sql,
    run_score_formal_audit,
)

DIMENSIONS = ("P", "C", "A", "V", "T")
COMPONENTS = {dimension: (f"{dimension}1", f"{dimension}2") for dimension in DIMENSIONS}


def _score_value(sequence: int, dimension: str) -> float:
    blocks: list[tuple[int, int, dict[str, float] | float]] = [
        (0, 9, 0.95),
        (11, 20, 0.87),
        (22, 31, 0.82),
        (33, 42, 0.77),
        (44, 53, {"P": 0.95}),
        (55, 64, {"P": 0.95, "A": 0.95}),
        (66, 75, {"P": 0.95, "C": 0.95, "A": 0.95}),
        (77, 86, {"P": 0.95, "C": 0.95, "A": 0.95, "V": 0.95}),
    ]
    for start, end, values in blocks:
        if start <= sequence <= end:
            return float(
                values if isinstance(values, float) else values.get(dimension, 0.5)
            )
    for offset, target in enumerate(DIMENSIONS):
        start = 88 + offset * 10
        if start <= sequence <= start + 7:
            return 0.80 if dimension == target else 0.95
    return 0.5


def _create_score_database(path: Path) -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    first = date(2025, 1, 2)
    securities = ("S1", "S2", "S3")
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE security_observation_spine(score_release_id VARCHAR,"
            "security_id VARCHAR,trading_date DATE,observation_sequence BIGINT,"
            "expected_observation_status VARCHAR,"
            "observation_available_time TIMESTAMP WITH TIME ZONE)"
        )
        connection.execute(
            "CREATE TABLE daily_dimension_scores(score_release_id VARCHAR,"
            "security_id VARCHAR,trading_date DATE,observation_sequence BIGINT,"
            "dimension_id VARCHAR,score_dimension DOUBLE,"
            "score_dimension_min DOUBLE,eligible_dimension BOOLEAN,"
            "validity_status VARCHAR,reason_codes VARCHAR[],"
            "available_time TIMESTAMP WITH TIME ZONE)"
        )
        spine_rows: list[tuple[object, ...]] = []
        dimension_rows: list[tuple[object, ...]] = []
        for security_id in securities:
            for sequence in range(138):
                trading_date = first + timedelta(days=sequence)
                available = datetime.combine(trading_date, time(15), timezone)
                spine_rows.append(
                    (
                        "pcavt-score-w120-v1-c7e04f11a2cd09aa",
                        security_id,
                        trading_date,
                        sequence,
                        "present",
                        available,
                    )
                )
                for dimension in DIMENSIONS:
                    score = _score_value(sequence, dimension)
                    dimension_rows.append(
                        (
                            "pcavt-score-w120-v1-c7e04f11a2cd09aa",
                            security_id,
                            trading_date,
                            sequence,
                            dimension,
                            score,
                            score,
                            True,
                            "valid",
                            [],
                            available,
                        )
                    )
        connection.executemany(
            "INSERT INTO security_observation_spine VALUES (?,?,?,?,?,?)",
            spine_rows,
        )
        connection.executemany(
            "INSERT INTO daily_dimension_scores VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            dimension_rows,
        )
        connection.execute(
            "CREATE TABLE daily_component_scores AS SELECT d.security_id,"
            "d.trading_date,d.dimension_id,c.component_id,d.score_dimension raw_value,"
            "d.score_dimension percentile,d.score_dimension score,"
            "d.eligible_dimension eligible,d.validity_status,d.reason_codes "
            "FROM daily_dimension_scores d JOIN (VALUES "
            "('P','P1'),('P','P2'),('C','C1'),('C','C2'),('A','A1'),('A','A2'),"
            "('V','V1'),('V','V2'),('T','T1'),('T','T2')) c(dimension_id,component_id) "
            "USING(dimension_id)"
        )
        connection.execute(
            "CREATE TABLE securities AS SELECT DISTINCT security_id "
            "FROM security_observation_spine"
        )
        connection.execute("CHECKPOINT")


def _authorized_config() -> dict[str, object]:
    config = json.loads(
        Path("configs/r2a/r2a_t04_real_data_audit.v1.json").read_text(encoding="utf-8")
    )
    config.update(
        {
            "status": "authorized_not_started",
            "authorization_revision": 6,
            "formal_run_authorized": True,
            "formal_run_started": False,
            "formal_run_consumed": False,
        }
    )
    config["score_release"]["security_count"] = 3
    return config


def _accepted_identity(path: Path, **_kwargs: object) -> dict[str, object]:
    return {
        "filename": path.name,
        "sha256": "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3",
        "byte_size": 4255395840,
    }


def test_score_audit_database_has_no_market_tables() -> None:
    with duckdb.connect(":memory:") as audit:
        initialize_score_audit_database(audit)
        tables = {
            row[0]
            for row in audit.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main'"
            ).fetchall()
        }
    assert tables == {
        "request_metrics_records",
        "year_metrics_records",
        "termination_metrics_records",
        "response_daily",
        "response_checks",
        "interval_inventory",
        "score_dimension_structure",
        "score_component_structure",
    }
    assert not any("market" in name for name in tables)


def test_interval_sample_is_deterministic_and_bounded(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.duckdb"
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    with duckdb.connect(str(audit_path)) as audit:
        initialize_score_audit_database(audit)
        audit.executemany(
            "INSERT INTO interval_inventory VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "R01",
                    "request",
                    "a" * 64,
                    f"S{index:03d}",
                    index,
                    date(2026, 1, 1),
                    date(2026, 1, 3),
                    date(2026, 1, 4),
                    date(2026, 1, 5),
                    "raw_false",
                    2,
                    False,
                )
                for index in range(30)
            ],
        )
        rows_a = deterministic_interval_samples(audit, review_directory=first)
        rows_b = deterministic_interval_samples(audit, review_directory=second)
    assert rows_a == rows_b
    assert len(rows_a) == 20
    assert all(
        row["sample_hash"]
        == hashlib.sha256(
            (
                f"{row['request_hash']}:{row['security_id']}:"
                f"{row['confirmation_date']}:{row['interval_ordinal']}"
            ).encode()
        ).hexdigest()
        for row in rows_a
    )


def test_synthetic_four_request_formal_execution_is_serial_and_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    score = tmp_path / "score.duckdb"
    _create_score_database(score)
    config = _authorized_config()
    panel = build_request_panel(config)
    events: list[tuple[str, str]] = []
    names = {item["request_id"]: item["logical_request_name"] for item in panel}

    def evaluator(**kwargs: object):
        request = kwargs["canonical_request"]
        name = names[request["request_id"]]
        events.append(("start", name))
        summary = evaluate_dynamic_request(
            score_database=kwargs["score_database"],
            canonical_request=request,
            output_database=kwargs["output_database"],
            security_ids=kwargs["security_ids"],
        )
        events.append(("end", name))
        output = kwargs["output_database"]
        return summary, 0.01, 1, output.stat().st_size

    monkeypatch.setattr(
        "src.r2a.r2a_t04_score_audit.verify_file_identity", _accepted_identity
    )
    monkeypatch.setattr(
        "src.r2a.r2a_t04_score_audit.free_disk_gate", lambda *_args: 10**12
    )
    output = tmp_path / "R2A-T04-20260719T000000000Z"
    review = tmp_path / "review"
    result = run_score_formal_audit(
        config=config,
        panel=panel,
        score_database=score,
        output_root=output,
        review_output=review,
        execution_gate={"status": "passed"},
        evaluator=evaluator,
    )
    assert result["status"] == "score_audit_completed_pending_result_review"
    assert events == [
        event
        for item in panel
        for event in (
            ("start", item["logical_request_name"]),
            ("end", item["logical_request_name"]),
        )
    ]
    assert not list((output / "request-results").glob("*.duckdb"))
    with duckdb.connect(str(output / "audit_metrics.duckdb"), read_only=True) as audit:
        assert (
            audit.execute("SELECT count(*) FROM request_metrics_records").fetchone()[0]
            == 4
        )
        assert (
            audit.execute("SELECT count(*) FROM interval_inventory").fetchone()[0]
            == audit.execute(
                "SELECT sum(CAST(json_extract(metrics_json,"
                "'$.confirmed_interval_count') "
                "AS BIGINT)) FROM request_metrics_records"
            ).fetchone()[0]
        )
        endpoint_count = audit.execute(
            "SELECT sum((raw_start_date IS NOT NULL)::INT+"
            "(confirmation_date IS NOT NULL)::INT+"
            "(last_confirmed_end_date IS NOT NULL)::INT+"
            "(termination_date IS NOT NULL)::INT) FROM interval_inventory"
        ).fetchone()[0]
        assert (
            audit.execute("SELECT count(*) FROM score_dimension_structure").fetchone()[
                0
            ]
            == endpoint_count * 5
        )
        assert (
            audit.execute("SELECT count(*) FROM score_component_structure").fetchone()[
                0
            ]
            == endpoint_count * 10
        )
        assert (
            audit.execute(
                "SELECT count(*) FROM response_checks WHERE passed=false"
            ).fetchone()[0]
            == 0
        )
    summary = json.loads((review / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["authorization_revision"] == 6
    assert (
        json.loads((output / "score_source_identity.json").read_text(encoding="utf-8"))[
            "score_release_id"
        ]
        == "pcavt-score-w120-v1-c7e04f11a2cd09aa"
    )
    assert (
        json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))[
            "authorization_revision"
        ]
        == 6
    )
    assert summary["review_boundary"] == {
        "automated_recommendation": "continue_to_owner_result_review",
        "owner_result_review": "pending",
        "R2A_T04_DONE": "absent",
        "R2A_T05_allowed_to_start": False,
    }
    analysis = (review / "result_analysis.md").read_text(encoding="utf-8")
    assert "does not select q" in analysis
    assert "Raw-state q response ladder" in analysis
    assert not any(path.suffix == ".png" for path in review.rglob("*"))


def test_response_degeneracy_blocks_formal_result() -> None:
    config = _authorized_config()
    with duckdb.connect(":memory:") as audit:
        initialize_score_audit_database(audit)
        audit.executemany(
            "INSERT INTO response_daily VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    item["logical_request_name"],
                    "S1",
                    date(2026, 1, 1),
                    True,
                    False,
                    False,
                    None,
                    False,
                )
                for item in build_request_panel(config)
            ],
        )
        run_ca_q_response_checks_sql(audit)
        assert (
            audit.execute(
                "SELECT passed FROM response_checks "
                "WHERE check_id='ca_q_ladder_non_degenerate'"
            ).fetchone()[0]
            is False
        )
