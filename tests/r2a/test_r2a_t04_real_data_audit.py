from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest
from jsonschema import Draft202012Validator

from src.r2a.r2a_t04_audit_validator import validate_review_bundle
from src.r2a.r2a_t04_charting import render_diagnostic_chart
from src.r2a.r2a_t04_real_data_audit import (
    R2AT04AuditError,
    canonical_table_profiles,
    evaluate_request_with_threads,
    initialize_audit_database,
    record_request_result,
    record_score_structure,
    request_metrics,
    termination_metrics,
    validate_market_source,
    verify_file_identity,
    year_metrics,
)
from tests.r2a.r2a_t03_test_support import canonical_request
from tests.r2a.r2a_t04_test_support import (
    create_market_database,
    create_score_database,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_score_identity_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "score_data.duckdb"
    path.write_bytes(b"not-the-accepted-score")
    with pytest.raises(R2AT04AuditError, match="bound_file_sha256_mismatch"):
        verify_file_identity(
            path,
            expected_sha256="0" * 64,
            expected_byte_size=path.stat().st_size,
        )


def test_market_source_full_present_coverage_and_integrity(tmp_path: Path) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    create_score_database(score)
    spec = create_market_database(market, score)
    result = validate_market_source(
        score_database=score,
        market_database=market,
        source_spec=spec,
        scratch_directory=tmp_path / "market-validation",
    )
    assert result["validator_status"] == "passed"
    assert result["present_key_missing_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "INSERT INTO market_data SELECT * FROM market_data LIMIT 1",
            "market_duplicate_key",
        ),
        (
            "UPDATE market_data SET raw_high=raw_close*0.5 WHERE rowid="
            "(SELECT min(rowid) FROM market_data)",
            "market_value_integrity_failed",
        ),
        (
            "DELETE FROM market_data WHERE rowid=(SELECT min(rowid) FROM market_data)",
            "market_present_key_coverage_missing",
        ),
    ],
)
def test_market_source_fail_closed_mutations(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    create_score_database(score)
    spec = create_market_database(market, score)
    with duckdb.connect(str(market)) as connection:
        connection.execute(mutation)
        connection.execute("CHECKPOINT")
    spec["database_sha256"] = _sha(market)
    spec["database_byte_size"] = market.stat().st_size
    with pytest.raises(R2AT04AuditError, match=reason):
        validate_market_source(
            score_database=score,
            market_database=market,
            source_spec=spec,
            scratch_directory=tmp_path / "market-validation",
        )


def test_market_unit_mapping_schema_rejects_wrong_units(tmp_path: Path) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    create_score_database(score)
    spec = create_market_database(market, score)
    spec["unit_mapping"]["volume_shares"] = "lots"
    schema = json.loads(
        Path("schemas/r2a/r2a_t04_local_source_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema).iter_errors(spec))


def test_synthetic_end_to_end_smoke(tmp_path: Path) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    create_score_database(score)
    spec = create_market_database(market, score)
    audit_path = tmp_path / "audit.duckdb"
    chart = tmp_path / "smoke.png"
    with duckdb.connect(str(audit_path)) as audit:
        initialize_audit_database(
            audit,
            market_database=market,
            source_query=str(spec["source_query"]),
        )
        outputs: list[tuple[str, Path]] = []
        for name, request in (
            ("D05_PCAVT_q15_k3", canonical_request()),
            ("ZERO_EVENT", canonical_request(confirmation_k=7)),
        ):
            output = tmp_path / f"{name}.duckdb"
            summary, wall, peak, size = evaluate_request_with_threads(
                score_database=score,
                canonical_request=request,
                output_database=output,
                duckdb_thread_count=4,
                security_ids=["S1", "S2", "S3"],
            )
            with duckdb.connect(str(output), read_only=True) as result:
                profiles = canonical_table_profiles(result)
                assert request_metrics(result)["spine_observation_count"] == 32
                assert year_metrics(result)
                assert termination_metrics(result) or name == "ZERO_EVENT"
            record_request_result(
                audit,
                logical_name=name,
                result_database=output,
                summary=summary,
                profiles=profiles,
                wall_seconds=wall,
                peak_rss_bytes=peak,
                temporary_output_bytes=size,
            )
            record_score_structure(
                audit,
                logical_name=name,
                result_database=output,
                score_database=score,
            )
            outputs.append((name, output))
        counts = dict(
            audit.execute(
                "SELECT logical_request_name,"
                "CAST(json_extract(metrics_json,'$.confirmed_interval_count') "
                "AS BIGINT) "
                "FROM request_metrics_records"
            ).fetchall()
        )
        assert counts["D05_PCAVT_q15_k3"] >= 1
        assert counts["ZERO_EVENT"] == 0
        path_row = audit.execute(
            "SELECT close_return_5,mfe5,mae5,horizon20_available "
            "FROM interval_path_metrics LIMIT 1"
        ).fetchone()
        assert path_row[0] is not None and path_row[1] >= path_row[2]
        context = (
            audit.execute(
                "SELECT trading_date,adj_high,adj_low,adj_close,ma5,ma10,ma20,"
                "ma30,ma60,volume_shares,volume_ma20,volume_ma60,amount_yuan,"
                "amount_ma20,amount_ma60,0 raw_state_numeric,0 confirmed_state_numeric "
                "FROM market_features WHERE security_id='S1' ORDER BY trading_date"
            )
            .fetch_arrow_table()
            .to_pylist()
        )
        render_diagnostic_chart(
            path=chart,
            title="SYNTHETIC END TO END SMOKE",
            rows=context,
            markers={"confirmation": str(context[2]["trading_date"])},
        )
    assert chart.read_bytes().startswith(b"\x89PNG")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    receipt = bundle / "smoke_receipt.json"
    receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
    summary = {
        "task_id": "R2A-T04",
        "bundle_mode": "synthetic_smoke",
        "status": "real_data_run_completed_pending_result_review",
        "formal_run_id": "R2A-T04-20260719T000000000Z",
        "formal_authorization_id": "R2A-T04-REAL-AUDIT-AUTH-20260719",
        "panel_id": "r2a_t04_representative_panel.v1",
        "request_count": 2,
        "score_source": {
            "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
            "sha256": (
                "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3"
            ),
            "byte_size": 4255395840,
        },
        "market_source": {"source_id": "synthetic", "sha256": "0" * 64, "byte_size": 1},
        "execution": {
            "full_universe_request_concurrency": 1,
            "duckdb_thread_count": 4,
            "chart_worker_count": 1,
            "formal_run_consumed": False,
        },
        "validation": {
            "request_validator_failure_count": 0,
            "response_violation_count": 0,
            "blocking_anomaly_count": 0,
            "status": "passed",
        },
        "review_boundary": {
            "automated_recommendation": "smoke_passed",
            "owner_visual_review": "not_applicable_smoke",
            "R2A_T04_DONE": "absent",
            "R2A_T05_allowed_to_start": False,
        },
        "files": [
            {
                "relative_path": "smoke_receipt.json",
                "sha256": _sha(receipt),
                "byte_size": receipt.stat().st_size,
            }
        ],
    }
    (bundle / "run_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    assert validate_review_bundle(bundle)["status"] == "passed"
