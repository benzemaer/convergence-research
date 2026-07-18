from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import duckdb
import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.r2a.r2a_t04_execution_gate import (
    R2AT04ExecutionGateError,
    execute_bound_real_input_smoke,
    market_source_spec_identity,
    validate_formal_execution_gate,
    validate_frozen_thread_benchmark_receipt,
    validate_market_source_spec_identity,
)
from src.r2a.r2a_t04_real_data_audit import (
    R2AT04AuditError,
    validate_market_source,
)
from tests.r2a.r2a_t04_test_support import (
    MARKET_QUERY,
    create_market_database,
    create_score_database,
)

TABLES = (
    "dynamic_request",
    "evaluation_scope",
    "daily_dimension_states",
    "daily_joint_states",
    "confirmed_intervals",
)
AUTHORIZATION_HEAD = "b" * 40
REPAIR_HEAD = "a" * 40
REQUEST = {
    "request_id": "pcavt-dynreq-v1-2937df4f84219640",
    "request_hash": "2937df4f8421964007b5d479a6b1f959564096bbe5df18ffe35b91b325192722",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config() -> dict[str, object]:
    return json.loads(
        Path("configs/r2a/r2a_t04_real_data_audit.v1.json").read_text(encoding="utf-8")
    )


def _successor_config() -> dict[str, object]:
    config = _config()
    config.update(
        {
            "status": "authorized_not_started",
            "authorization_revision": 2,
            "reviewed_harness_head": REPAIR_HEAD,
            "formal_run_authorized": True,
            "formal_run_started": False,
            "formal_run_consumed": False,
            "authorization_effective_only_after_exact_head_quality_success": True,
        }
    )
    return config


def _table_profile() -> dict[str, object]:
    return {
        "row_count": 0,
        "schema_fingerprint": "1" * 64,
        "canonical_fingerprint": "2" * 64,
        "fingerprint_algorithm": "arrow_ipc_fixed_logical_row_chunks.v1",
        "canonical_chunk_row_count": 65536,
        "canonical_chunk_count": 0,
        "canonical_chunk_fingerprints": [],
    }


def _table_comparison() -> dict[str, object]:
    return {
        "status": "logically_equal",
        "schema_comparison": {"equal": True, "left": [], "right": []},
        "row_count_comparison": {"equal": True, "left": 0, "right": 0},
        "primary_key_comparison": {
            "left_only_key_count": 0,
            "right_only_key_count": 0,
            "first_mismatch_keys": [],
        },
        "value_comparison": {
            "value_mismatch_row_count": 0,
            "per_column_mismatch_count": {},
        },
    }


def _benchmark_receipt() -> dict[str, object]:
    output_tables = {name: _table_profile() for name in TABLES}
    return {
        "task_id": "R2A-T04",
        "status": "passed",
        "reason_code": "passed",
        "implementation_head": "01bf7e12f0cb19a31c71689ada32f7a78f8aec75",
        "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
        "score_database_sha256": (
            "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3"
        ),
        "score_database_byte_size": 4255395840,
        "request_id": REQUEST["request_id"],
        "request_hash": REQUEST["request_hash"],
        "security_ids": ["603345.SH", "603233.SH", "688220.SH", "300316.SZ"],
        "candidate_threads": [4, 8, 16],
        "fingerprint_algorithm": "arrow_ipc_fixed_logical_row_chunks.v1",
        "canonical_chunk_row_count": 65536,
        "runs": [
            {
                "duckdb_thread_count": threads,
                "wall_seconds": float(threads),
                "peak_rss_bytes": threads,
                "temporary_output_bytes": 1,
                "validator_status": "passed",
                "output_tables": deepcopy(output_tables),
            }
            for threads in (4, 8, 16)
        ],
        "pairwise_comparisons": [
            {
                "left_threads": left,
                "right_threads": right,
                "status": "logically_equal",
                "tables": {name: _table_comparison() for name in TABLES},
            }
            for left, right in ((4, 8), (4, 16), (8, 16))
        ],
        "selected_duckdb_thread_count": 4,
        "thread_benchmark_fingerprint": (
            "049eeca525592e9a3d9659b3d0a3ce1eccc322f0289f283d0e9d8fe647e82231"
        ),
        "failure_evidence_diagnostic_id": None,
        "failure_evidence_files": [],
        "formal_run_attempt_consumed": False,
        "formal_run_authorized": False,
    }


def _write_benchmark(
    path: Path,
    config: dict[str, object],
    value: dict[str, object] | None = None,
    *,
    update_binding: bool = True,
) -> None:
    path.write_text(
        json.dumps(value or _benchmark_receipt(), indent=2) + "\n", encoding="utf-8"
    )
    if update_binding:
        preflight = config["thread_preflight"]
        preflight["thread_benchmark_receipt_sha256"] = _sha(path)
        preflight["thread_benchmark_receipt_byte_size"] = path.stat().st_size


def _fake_benchmark_validator(
    path: Path, _config: dict[str, object]
) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("sha", "thread_benchmark_receipt_sha256_mismatch"),
        ("size", "thread_benchmark_receipt_size_mismatch"),
        (
            "fingerprint",
            "thread_benchmark_receipt_thread_benchmark_fingerprint_mismatch",
        ),
        ("request", "thread_benchmark_receipt_request_id_mismatch"),
        ("security_order", "thread_benchmark_receipt_security_ids_mismatch"),
        ("threads", "thread_benchmark_receipt_selected_duckdb_thread_count_mismatch"),
    ],
)
def test_frozen_benchmark_receipt_rejects_binding_mutations(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    config = _successor_config()
    receipt = _benchmark_receipt()
    path = tmp_path / "benchmark.json"
    _write_benchmark(path, config, receipt)
    if mutation == "sha":
        config["thread_preflight"]["thread_benchmark_receipt_sha256"] = "f" * 64
    elif mutation == "size":
        config["thread_preflight"]["thread_benchmark_receipt_byte_size"] += 1
    else:
        if mutation == "fingerprint":
            receipt["thread_benchmark_fingerprint"] = "f" * 64
        elif mutation == "request":
            receipt["request_id"] = "wrong-request"
        elif mutation == "security_order":
            receipt["security_ids"] = list(reversed(receipt["security_ids"]))
        elif mutation == "threads":
            receipt["selected_duckdb_thread_count"] = 8
        _write_benchmark(path, config, receipt)
    with pytest.raises(R2AT04ExecutionGateError, match=reason):
        validate_frozen_thread_benchmark_receipt(path, config)


def test_market_source_spec_raw_identity_rejects_sha_change(tmp_path: Path) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    spec_path = tmp_path / "market.json"
    create_score_database(score)
    spec = create_market_database(market, score)
    spec_path.write_text(json.dumps(spec) + "\n", encoding="utf-8")
    expected = market_source_spec_identity(spec_path)
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(
        R2AT04ExecutionGateError, match="market_source_spec_sha256_mismatch"
    ):
        validate_market_source_spec_identity(spec_path, expected)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "INSERT INTO market_data SELECT * FROM market_data LIMIT 1",
            "market_duplicate_key",
        ),
        (
            "UPDATE market_data SET raw_high=raw_close*0.5 "
            "WHERE rowid=(SELECT min(rowid) FROM market_data)",
            "market_value_integrity_failed",
        ),
        (
            "DELETE FROM market_data WHERE rowid=(SELECT min(rowid) FROM market_data)",
            "market_present_key_coverage_missing",
        ),
    ],
)
def test_full_market_validation_rejects_data_contract_failures(
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


def _fake_identity(path: Path, *, expected_sha256: str, expected_byte_size: int):
    return {
        "filename": path.name,
        "sha256": expected_sha256,
        "byte_size": expected_byte_size,
    }


def _fake_smoke_payload() -> dict[str, object]:
    return {
        "validator_status": "passed",
        "output_table_counts": {name: 1 for name in TABLES},
        "output_fingerprints": {name: "a" * 64 for name in TABLES},
        "interval_count": 0,
        "chart_count": 0,
        "zero_interval_smoke": True,
        "elapsed_seconds": 1.0,
        "temporary_bytes": 1,
    }


def _smoke_setup(tmp_path: Path):
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    spec_path = tmp_path / "market.json"
    score.touch()
    market.touch()
    spec = {
        "source_id": "synthetic-market-v1",
        "database_basename": market.name,
        "database_sha256": "3" * 64,
        "database_byte_size": 1,
        "source_snapshot_id": "snapshot-v1",
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
        "date_coverage": {"date_min": "2020-01-01", "date_max": "2020-01-02"},
        "security_coverage": {
            "security_count": 800,
            "scope": "accepted_score_spine_present_keys",
        },
    }
    spec_path.write_text(json.dumps(spec) + "\n", encoding="utf-8")
    config = _successor_config()
    benchmark_path = tmp_path / "benchmark.json"
    _write_benchmark(benchmark_path, config, update_binding=False)
    return config, score, market, spec_path, benchmark_path


def test_market_validation_precedes_evaluator(tmp_path: Path) -> None:
    config, score, market, spec_path, benchmark = _smoke_setup(tmp_path)
    events: list[str] = []

    def market_validator(**_kwargs):
        events.append("market")
        return {"validator_status": "passed", "present_key_missing_count": 0}

    def smoke_runner(**_kwargs):
        events.append("evaluator")
        return _fake_smoke_payload()

    receipt = execute_bound_real_input_smoke(
        config=config,
        authorization_head=AUTHORIZATION_HEAD,
        authorization_parent=REPAIR_HEAD,
        authorization_quality="123 / success",
        score_database=score,
        thread_benchmark_receipt_path=benchmark,
        market_source_spec_path=spec_path,
        market_database=market,
        canonical_request=REQUEST,
        scratch_directory=tmp_path / "scratch",
        receipt_path=tmp_path / "receipt.json",
        identity_verifier=_fake_identity,
        benchmark_validator=_fake_benchmark_validator,
        market_validator=market_validator,
        smoke_runner=smoke_runner,
    )
    assert receipt["status"] == "passed"
    assert events == ["market", "evaluator"]


def test_market_database_identity_mismatch_blocks_before_validation(
    tmp_path: Path,
) -> None:
    config, score, market, spec_path, benchmark = _smoke_setup(tmp_path)
    identity_calls = 0
    market_validator_called = False

    def identity_verifier(path: Path, *, expected_sha256: str, expected_byte_size: int):
        nonlocal identity_calls
        identity_calls += 1
        if path == market:
            raise R2AT04AuditError("bound_file_sha256_mismatch")
        return _fake_identity(
            path,
            expected_sha256=expected_sha256,
            expected_byte_size=expected_byte_size,
        )

    def market_validator(**_kwargs):
        nonlocal market_validator_called
        market_validator_called = True
        return {"validator_status": "passed", "present_key_missing_count": 0}

    receipt = execute_bound_real_input_smoke(
        config=config,
        authorization_head=AUTHORIZATION_HEAD,
        authorization_parent=REPAIR_HEAD,
        authorization_quality="123 / success",
        score_database=score,
        thread_benchmark_receipt_path=benchmark,
        market_source_spec_path=spec_path,
        market_database=market,
        canonical_request=REQUEST,
        scratch_directory=tmp_path / "scratch",
        receipt_path=tmp_path / "receipt.json",
        identity_verifier=identity_verifier,
        benchmark_validator=_fake_benchmark_validator,
        market_validator=market_validator,
        smoke_runner=lambda **_kwargs: _fake_smoke_payload(),
    )
    assert identity_calls == 2
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "bound_file_sha256_mismatch"
    assert receipt["error_stage"] == "market_database_identity"
    assert not market_validator_called


def test_failed_market_validation_blocks_evaluator_and_writes_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, score, market, spec_path, benchmark = _smoke_setup(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    evaluator_called = False
    cleanup_observations: list[bool] = []
    original_rmtree = shutil.rmtree

    def market_validator(**_kwargs):
        raise R2AT04AuditError("market_duplicate_key")

    def smoke_runner(**_kwargs):
        nonlocal evaluator_called
        evaluator_called = True
        return _fake_smoke_payload()

    def observed_rmtree(path, *args, **kwargs):
        cleanup_observations.append(receipt_path.is_file())
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("src.r2a.r2a_t04_execution_gate.shutil.rmtree", observed_rmtree)
    receipt = execute_bound_real_input_smoke(
        config=config,
        authorization_head=AUTHORIZATION_HEAD,
        authorization_parent=REPAIR_HEAD,
        authorization_quality="123 / success",
        score_database=score,
        thread_benchmark_receipt_path=benchmark,
        market_source_spec_path=spec_path,
        market_database=market,
        canonical_request=REQUEST,
        scratch_directory=tmp_path / "scratch",
        receipt_path=receipt_path,
        identity_verifier=_fake_identity,
        benchmark_validator=_fake_benchmark_validator,
        market_validator=market_validator,
        smoke_runner=smoke_runner,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "market_duplicate_key"
    assert not evaluator_called
    assert cleanup_observations == [True]
    assert str(tmp_path) not in receipt_path.read_text(encoding="utf-8")


def _formal_setup(tmp_path: Path):
    config, score, market, spec_path, benchmark = _smoke_setup(tmp_path)
    smoke_path = tmp_path / "smoke.json"
    execute_bound_real_input_smoke(
        config=config,
        authorization_head=AUTHORIZATION_HEAD,
        authorization_parent=REPAIR_HEAD,
        authorization_quality="123 / success",
        score_database=score,
        thread_benchmark_receipt_path=benchmark,
        market_source_spec_path=spec_path,
        market_database=market,
        canonical_request=REQUEST,
        scratch_directory=tmp_path / "scratch",
        receipt_path=smoke_path,
        identity_verifier=_fake_identity,
        benchmark_validator=_fake_benchmark_validator,
        market_validator=lambda **_kwargs: {
            "validator_status": "passed",
            "present_key_missing_count": 0,
        },
        smoke_runner=lambda **_kwargs: _fake_smoke_payload(),
    )
    return config, score, market, spec_path, benchmark, smoke_path


def test_formal_gate_accepts_only_fully_bound_successor_contract(
    tmp_path: Path,
) -> None:
    config, score, market, spec, benchmark, smoke = _formal_setup(tmp_path)
    result = validate_formal_execution_gate(
        config=config,
        authorization_head=AUTHORIZATION_HEAD,
        authorization_parent=REPAIR_HEAD,
        score_database=score,
        thread_benchmark_receipt_path=benchmark,
        real_input_smoke_receipt_path=smoke,
        market_source_spec_path=spec,
        market_database=market,
        canonical_request=REQUEST,
        identity_verifier=_fake_identity,
        benchmark_validator=_fake_benchmark_validator,
    )
    assert result["status"] == "passed"


def test_formal_gate_rejects_arbitrary_passed_json(tmp_path: Path) -> None:
    config, score, market, spec, benchmark, smoke = _formal_setup(tmp_path)
    smoke.write_text('{"status":"passed"}\n', encoding="utf-8")
    with pytest.raises(
        R2AT04ExecutionGateError, match="real_input_smoke_receipt_schema_invalid"
    ):
        validate_formal_execution_gate(
            config=config,
            authorization_head=AUTHORIZATION_HEAD,
            authorization_parent=REPAIR_HEAD,
            score_database=score,
            thread_benchmark_receipt_path=benchmark,
            real_input_smoke_receipt_path=smoke,
            market_source_spec_path=spec,
            market_database=market,
            canonical_request=REQUEST,
            identity_verifier=_fake_identity,
            benchmark_validator=_fake_benchmark_validator,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization_head", "c" * 40),
        ("thread_benchmark_receipt_sha256", "f" * 64),
        ("score_database_sha256", "f" * 64),
        ("market_source_spec_sha256", "f" * 64),
        ("market_database_sha256", "f" * 64),
        ("request_id", "wrong-request"),
        ("request_hash", "f" * 64),
        ("security_ids", ["300316.SZ", "688220.SH", "603233.SH", "603345.SH"]),
        ("market_validator_status", "failed"),
    ],
)
def test_formal_gate_rejects_mutated_smoke_bindings(
    tmp_path: Path, field: str, value: object
) -> None:
    config, score, market, spec, benchmark, smoke = _formal_setup(tmp_path)
    receipt = json.loads(smoke.read_text(encoding="utf-8"))
    receipt[field] = value
    smoke.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    with pytest.raises(R2AT04ExecutionGateError):
        validate_formal_execution_gate(
            config=config,
            authorization_head=AUTHORIZATION_HEAD,
            authorization_parent=REPAIR_HEAD,
            score_database=score,
            thread_benchmark_receipt_path=benchmark,
            real_input_smoke_receipt_path=smoke,
            market_source_spec_path=spec,
            market_database=market,
            canonical_request=REQUEST,
            identity_verifier=_fake_identity,
            benchmark_validator=_fake_benchmark_validator,
        )


def test_formal_gate_rejects_superseded_status(tmp_path: Path) -> None:
    config, score, market, spec, benchmark, smoke = _formal_setup(tmp_path)
    config["status"] = "formal_authorization_committed"
    with pytest.raises(R2AT04ExecutionGateError, match="authorization_status_mismatch"):
        validate_formal_execution_gate(
            config=config,
            authorization_head=AUTHORIZATION_HEAD,
            authorization_parent=REPAIR_HEAD,
            score_database=score,
            thread_benchmark_receipt_path=benchmark,
            real_input_smoke_receipt_path=smoke,
            market_source_spec_path=spec,
            market_database=market,
            canonical_request=REQUEST,
            identity_verifier=_fake_identity,
            benchmark_validator=_fake_benchmark_validator,
        )


def test_passed_and_blocked_receipts_validate_strict_schema(tmp_path: Path) -> None:
    config, score, market, spec_path, benchmark = _smoke_setup(tmp_path)
    schema = json.loads(
        Path("schemas/r2a/r2a_t04_real_input_smoke_receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    passed = execute_bound_real_input_smoke(
        config=config,
        authorization_head=AUTHORIZATION_HEAD,
        authorization_parent=REPAIR_HEAD,
        authorization_quality="123 / success",
        score_database=score,
        thread_benchmark_receipt_path=benchmark,
        market_source_spec_path=spec_path,
        market_database=market,
        canonical_request=REQUEST,
        scratch_directory=tmp_path / "passed-scratch",
        receipt_path=tmp_path / "passed.json",
        identity_verifier=_fake_identity,
        benchmark_validator=_fake_benchmark_validator,
        market_validator=lambda **_kwargs: {
            "validator_status": "passed",
            "present_key_missing_count": 0,
        },
        smoke_runner=lambda **_kwargs: _fake_smoke_payload(),
    )
    blocked = execute_bound_real_input_smoke(
        config=config,
        authorization_head=AUTHORIZATION_HEAD,
        authorization_parent=REPAIR_HEAD,
        authorization_quality="123 / success",
        score_database=score,
        thread_benchmark_receipt_path=benchmark,
        market_source_spec_path=spec_path,
        market_database=market,
        canonical_request=REQUEST,
        scratch_directory=tmp_path / "blocked-scratch",
        receipt_path=tmp_path / "blocked.json",
        identity_verifier=_fake_identity,
        benchmark_validator=_fake_benchmark_validator,
        market_validator=lambda **_kwargs: (_ for _ in ()).throw(
            R2AT04AuditError("market_duplicate_key")
        ),
        smoke_runner=lambda **_kwargs: _fake_smoke_payload(),
    )
    Draft202012Validator(schema).validate(passed)
    Draft202012Validator(schema).validate(blocked)


def test_smoke_receipt_schema_prohibits_absolute_paths(tmp_path: Path) -> None:
    config, score, market, spec, benchmark, smoke = _formal_setup(tmp_path)
    del config, score, market, spec, benchmark
    receipt = json.loads(smoke.read_text(encoding="utf-8"))
    receipt["market_source_spec_basename"] = str(tmp_path / "market.json")
    with pytest.raises(ValidationError):
        Draft202012Validator(
            json.loads(
                Path(
                    "schemas/r2a/r2a_t04_real_input_smoke_receipt.schema.json"
                ).read_text(encoding="utf-8")
            )
        ).validate(receipt)
