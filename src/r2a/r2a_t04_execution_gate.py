"""Fail-closed bindings for R2A-T04 smoke and formal execution."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from src.r2a.r2a_t04_real_data_audit import (
    R2AT04AuditError,
    load_market_source_spec,
    run_real_input_smoke,
    sha256_file,
    validate_market_source,
    verify_file_identity,
)

ROOT = Path(__file__).resolve().parents[2]
THREAD_RECEIPT_SCHEMA = (
    ROOT / "schemas/r2a/r2a_t04_thread_benchmark_receipt.schema.json"
)
SMOKE_RECEIPT_SCHEMA = ROOT / "schemas/r2a/r2a_t04_real_input_smoke_receipt.schema.json"
EXPECTED_REQUEST_ID = "pcavt-dynreq-v1-2937df4f84219640"
EXPECTED_REQUEST_HASH = (
    "2937df4f8421964007b5d479a6b1f959564096bbe5df18ffe35b91b325192722"
)


class R2AT04ExecutionGateError(ValueError):
    def __init__(self, reason_code: str, stage: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.stage = stage
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


def _schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_json(path: Path, schema_path: Path, reason_code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        schema = _schema(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise R2AT04ExecutionGateError(
            reason_code, "benchmark_receipt", type(error).__name__
        ) from error
    return dict(value)


def _require_equal(*, actual: Any, expected: Any, reason_code: str, stage: str) -> None:
    if actual != expected:
        raise R2AT04ExecutionGateError(reason_code, stage)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_frozen_thread_benchmark_receipt(
    receipt_path: str | Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the frozen benchmark file, schema, and every execution binding."""

    path = Path(receipt_path)
    preflight = config["thread_preflight"]
    if not path.is_file():
        raise R2AT04ExecutionGateError(
            "thread_benchmark_receipt_missing", "benchmark_receipt"
        )
    _require_equal(
        actual=path.stat().st_size,
        expected=int(preflight["thread_benchmark_receipt_byte_size"]),
        reason_code="thread_benchmark_receipt_size_mismatch",
        stage="benchmark_receipt",
    )
    _require_equal(
        actual=sha256_file(path),
        expected=str(preflight["thread_benchmark_receipt_sha256"]),
        reason_code="thread_benchmark_receipt_sha256_mismatch",
        stage="benchmark_receipt",
    )
    receipt = _validated_json(
        path,
        THREAD_RECEIPT_SCHEMA,
        "thread_benchmark_receipt_schema_invalid",
    )
    expected = {
        "status": "passed",
        "reason_code": "passed",
        "implementation_head": preflight["benchmark_execution_head"],
        "score_release_id": config["score_release"]["score_release_id"],
        "score_database_sha256": config["score_release"]["sha256"],
        "score_database_byte_size": config["score_release"]["byte_size"],
        "request_id": preflight["benchmark_request_id"],
        "request_hash": preflight["benchmark_request_hash"],
        "selected_duckdb_thread_count": preflight["duckdb_thread_count"],
        "thread_benchmark_fingerprint": preflight["thread_benchmark_fingerprint"],
        "security_ids": preflight["benchmark_security_ids"],
        "formal_run_attempt_consumed": False,
        "formal_run_authorized": False,
    }
    for field, expected_value in expected.items():
        _require_equal(
            actual=receipt.get(field),
            expected=expected_value,
            reason_code=f"thread_benchmark_receipt_{field}_mismatch",
            stage="benchmark_receipt",
        )
    return receipt


def market_source_spec_identity(spec_path: str | Path) -> dict[str, Any]:
    """Validate a local market spec and bind its raw file and query identities."""

    path = Path(spec_path)
    if not path.is_file():
        raise R2AT04ExecutionGateError(
            "market_source_spec_missing", "market_source_spec"
        )
    try:
        spec = load_market_source_spec(path)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise R2AT04ExecutionGateError(
            "market_source_spec_schema_invalid",
            "market_source_spec",
            type(error).__name__,
        ) from error
    return {
        "basename": path.name,
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "source_id": spec["source_id"],
        "database_basename": spec["database_basename"],
        "database_sha256": spec["database_sha256"],
        "database_byte_size": spec["database_byte_size"],
        "source_snapshot_id": spec["source_snapshot_id"],
        "source_query_sha256": hashlib.sha256(
            str(spec["source_query"]).encode("utf-8")
        ).hexdigest(),
        "spec": spec,
    }


def validate_market_source_spec_identity(
    spec_path: str | Path, expected: Mapping[str, Any]
) -> dict[str, Any]:
    identity = market_source_spec_identity(spec_path)
    for field in (
        "basename",
        "sha256",
        "byte_size",
        "source_id",
        "database_basename",
        "database_sha256",
        "database_byte_size",
        "source_snapshot_id",
        "source_query_sha256",
    ):
        _require_equal(
            actual=identity[field],
            expected=expected[field],
            reason_code=f"market_source_spec_{field}_mismatch",
            stage="market_source_spec",
        )
    return identity


def _receipt_envelope(
    *,
    config: Mapping[str, Any],
    authorization_head: str,
    authorization_quality: str,
    canonical_request: Mapping[str, Any],
) -> dict[str, Any]:
    preflight = config["thread_preflight"]
    securities = list(preflight["benchmark_security_ids"])
    return {
        "task_id": "R2A-T04",
        "receipt_version": "r2a_t04_real_input_smoke_receipt.v1",
        "status": "blocked",
        "reason_code": "unexpected_error",
        "error_stage": "unexpected",
        "formal_authorization_id": config["formal_authorization_id"],
        "authorization_revision": config.get("authorization_revision", 2),
        "authorization_head": authorization_head,
        "reviewed_harness_head": config["reviewed_harness_head"],
        "authorization_quality": authorization_quality,
        "thread_benchmark_receipt_sha256": preflight["thread_benchmark_receipt_sha256"],
        "thread_benchmark_receipt_byte_size": preflight[
            "thread_benchmark_receipt_byte_size"
        ],
        "thread_benchmark_fingerprint": preflight["thread_benchmark_fingerprint"],
        "benchmark_execution_head": preflight["benchmark_execution_head"],
        "selected_duckdb_thread_count": preflight["duckdb_thread_count"],
        "benchmark_security_ids": securities,
        "score_release_id": config["score_release"]["score_release_id"],
        "score_database_sha256": config["score_release"]["sha256"],
        "score_database_byte_size": config["score_release"]["byte_size"],
        "score_source_unchanged": None,
        "market_source_spec_basename": None,
        "market_source_spec_sha256": None,
        "market_source_spec_byte_size": None,
        "market_source_query_sha256": None,
        "market_source_id": None,
        "market_source_snapshot_id": None,
        "market_database_basename": None,
        "market_database_sha256": None,
        "market_database_byte_size": None,
        "market_validator_status": "not_started",
        "market_present_key_missing_count": None,
        "market_source_unchanged": None,
        "request_id": canonical_request["request_id"],
        "request_hash": canonical_request["request_hash"],
        "security_ids": securities,
        "duckdb_thread_count": preflight["duckdb_thread_count"],
        "validator_status": "not_started",
        "output_table_counts": {},
        "output_fingerprints": {},
        "interval_count": None,
        "chart_count": None,
        "zero_interval_smoke": None,
        "elapsed_seconds": None,
        "temporary_bytes": None,
        "formal_run_started": False,
        "formal_run_attempt_consumed": False,
        "full_universe_request_count": 0,
    }


def _validate_successor_authorization(
    config: Mapping[str, Any], authorization_head: str, authorization_parent: str
) -> None:
    expected = {
        "status": "authorized_not_started",
        "authorization_revision": 2,
        "formal_run_authorized": True,
        "formal_run_started": False,
        "formal_run_consumed": False,
        "authorization_effective_only_after_exact_head_quality_success": True,
    }
    for field, value in expected.items():
        _require_equal(
            actual=config.get(field),
            expected=value,
            reason_code=f"authorization_{field}_mismatch",
            stage="authorization",
        )
    _require_equal(
        actual=authorization_parent,
        expected=config["reviewed_harness_head"],
        reason_code="authorization_parent_not_reviewed_harness",
        stage="authorization",
    )
    if len(authorization_head) != 40:
        raise R2AT04ExecutionGateError("authorization_head_invalid", "authorization")


def execute_bound_real_input_smoke(
    *,
    config: Mapping[str, Any],
    authorization_head: str,
    authorization_parent: str,
    authorization_quality: str,
    score_database: Path,
    thread_benchmark_receipt_path: Path,
    market_source_spec_path: Path,
    market_database: Path,
    canonical_request: Mapping[str, Any],
    scratch_directory: Path,
    receipt_path: Path,
    identity_verifier: Callable[..., dict[str, Any]] = verify_file_identity,
    benchmark_validator: Callable[..., dict[str, Any]] = (
        validate_frozen_thread_benchmark_receipt
    ),
    market_validator: Callable[..., dict[str, Any]] = validate_market_source,
    smoke_runner: Callable[..., dict[str, Any]] = run_real_input_smoke,
) -> dict[str, Any]:
    """Execute a bound smoke and persist passed/blocked evidence before cleanup."""

    receipt = _receipt_envelope(
        config=config,
        authorization_head=authorization_head,
        authorization_quality=authorization_quality,
        canonical_request=canonical_request,
    )
    stage = "authorization"
    created_scratch = False
    score_before: dict[str, Any] | None = None
    market_before: dict[str, Any] | None = None
    try:
        _validate_successor_authorization(
            config, authorization_head, authorization_parent
        )
        _require_equal(
            actual=canonical_request.get("request_id"),
            expected=EXPECTED_REQUEST_ID,
            reason_code="real_smoke_request_id_mismatch",
            stage="authorization",
        )
        _require_equal(
            actual=canonical_request.get("request_hash"),
            expected=EXPECTED_REQUEST_HASH,
            reason_code="real_smoke_request_hash_mismatch",
            stage="authorization",
        )
        if scratch_directory.exists():
            raise R2AT04ExecutionGateError(
                "real_smoke_scratch_already_exists", "authorization"
            )
        scratch_directory.mkdir(parents=True)
        created_scratch = True

        stage = "score_identity"
        score_before = identity_verifier(
            score_database,
            expected_sha256=str(config["score_release"]["sha256"]),
            expected_byte_size=int(config["score_release"]["byte_size"]),
        )
        receipt["score_source_unchanged"] = True

        stage = "benchmark_receipt"
        benchmark_validator(thread_benchmark_receipt_path, config)

        stage = "market_source_spec"
        market_spec_identity = market_source_spec_identity(market_source_spec_path)
        receipt.update(
            {
                "market_source_spec_basename": market_spec_identity["basename"],
                "market_source_spec_sha256": market_spec_identity["sha256"],
                "market_source_spec_byte_size": market_spec_identity["byte_size"],
                "market_source_query_sha256": market_spec_identity[
                    "source_query_sha256"
                ],
                "market_source_id": market_spec_identity["source_id"],
                "market_source_snapshot_id": market_spec_identity["source_snapshot_id"],
                "market_database_basename": market_spec_identity["database_basename"],
                "market_database_sha256": market_spec_identity["database_sha256"],
                "market_database_byte_size": market_spec_identity["database_byte_size"],
            }
        )

        stage = "market_database_identity"
        market_before = identity_verifier(
            market_database,
            expected_sha256=str(market_spec_identity["database_sha256"]),
            expected_byte_size=int(market_spec_identity["database_byte_size"]),
        )
        _require_equal(
            actual=market_database.name,
            expected=market_spec_identity["database_basename"],
            reason_code="market_database_basename_mismatch",
            stage="market_database_identity",
        )
        receipt["market_source_unchanged"] = True

        stage = "market_validation"
        market_validation = market_validator(
            score_database=score_database,
            market_database=market_database,
            source_spec=market_spec_identity["spec"],
            scratch_directory=scratch_directory / "market-validation",
        )
        receipt["market_validator_status"] = market_validation["validator_status"]
        receipt["market_present_key_missing_count"] = market_validation[
            "present_key_missing_count"
        ]

        stage = "smoke_evaluator"
        core_payload = smoke_runner(
            config=config,
            score_database=score_database,
            market_database=market_database,
            market_source_spec=market_spec_identity["spec"],
            canonical_request=canonical_request,
            benchmark_receipt=json.loads(
                thread_benchmark_receipt_path.read_text(encoding="utf-8")
            ),
            scratch_directory=scratch_directory / "core-smoke",
            receipt_path=scratch_directory / "core-smoke-receipt.json",
        )
        receipt.update(
            {
                "validator_status": core_payload["validator_status"],
                "output_table_counts": core_payload["output_table_counts"],
                "output_fingerprints": core_payload["output_fingerprints"],
                "interval_count": core_payload["interval_count"],
                "chart_count": core_payload["chart_count"],
                "zero_interval_smoke": core_payload["zero_interval_smoke"],
                "elapsed_seconds": core_payload["elapsed_seconds"],
                "temporary_bytes": core_payload["temporary_bytes"],
            }
        )

        stage = "source_reconciliation"
        score_after = identity_verifier(
            score_database,
            expected_sha256=str(score_before["sha256"]),
            expected_byte_size=int(score_before["byte_size"]),
        )
        market_after = identity_verifier(
            market_database,
            expected_sha256=str(market_before["sha256"]),
            expected_byte_size=int(market_before["byte_size"]),
        )
        receipt["score_source_unchanged"] = score_after == score_before
        receipt["market_source_unchanged"] = market_after == market_before
        if not receipt["score_source_unchanged"]:
            raise R2AT04ExecutionGateError(
                "score_source_mutated_during_real_smoke", stage
            )
        if not receipt["market_source_unchanged"]:
            raise R2AT04ExecutionGateError(
                "market_source_mutated_during_real_smoke", stage
            )
        receipt.update(
            {"status": "passed", "reason_code": "passed", "error_stage": "none"}
        )
    except (R2AT04ExecutionGateError, R2AT04AuditError) as error:
        receipt["status"] = "blocked"
        receipt["reason_code"] = error.reason_code
        receipt["error_stage"] = getattr(error, "stage", stage)
        if stage == "market_validation":
            receipt["market_validator_status"] = "failed"
        elif stage in {"smoke_evaluator", "source_reconciliation"}:
            receipt["validator_status"] = "failed"
    except Exception:
        receipt.update(
            {
                "status": "blocked",
                "reason_code": "real_input_smoke_unexpected_error",
                "error_stage": "unexpected",
            }
        )

    stage = "receipt_write"
    schema = _schema(SMOKE_RECEIPT_SCHEMA)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    _atomic_write_json(receipt_path, receipt)
    if created_scratch and scratch_directory.exists():
        shutil.rmtree(scratch_directory)
    return receipt


def validate_real_input_smoke_receipt(
    *, receipt_path: Path, config: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        return _validated_json(
            receipt_path,
            SMOKE_RECEIPT_SCHEMA,
            "real_input_smoke_receipt_schema_invalid",
        )
    except R2AT04ExecutionGateError as error:
        error.stage = "authorization"
        raise


def validate_formal_execution_gate(
    *,
    config: Mapping[str, Any],
    authorization_head: str,
    authorization_parent: str,
    score_database: Path,
    thread_benchmark_receipt_path: Path,
    real_input_smoke_receipt_path: Path,
    market_source_spec_path: Path,
    market_database: Path,
    canonical_request: Mapping[str, Any],
    identity_verifier: Callable[..., dict[str, Any]] = verify_file_identity,
    benchmark_validator: Callable[..., dict[str, Any]] = (
        validate_frozen_thread_benchmark_receipt
    ),
) -> dict[str, Any]:
    """Validate every formal binding before a formal output root can be created."""

    _validate_successor_authorization(config, authorization_head, authorization_parent)
    benchmark = benchmark_validator(thread_benchmark_receipt_path, config)
    receipt = validate_real_input_smoke_receipt(
        receipt_path=real_input_smoke_receipt_path, config=config
    )
    required_receipt = {
        "status": "passed",
        "reason_code": "passed",
        "formal_run_started": False,
        "formal_run_attempt_consumed": False,
        "full_universe_request_count": 0,
        "authorization_head": authorization_head,
        "formal_authorization_id": config["formal_authorization_id"],
        "reviewed_harness_head": config["reviewed_harness_head"],
        "authorization_revision": 2,
        "thread_benchmark_receipt_sha256": config["thread_preflight"][
            "thread_benchmark_receipt_sha256"
        ],
        "thread_benchmark_receipt_byte_size": config["thread_preflight"][
            "thread_benchmark_receipt_byte_size"
        ],
        "thread_benchmark_fingerprint": config["thread_preflight"][
            "thread_benchmark_fingerprint"
        ],
        "benchmark_execution_head": config["thread_preflight"][
            "benchmark_execution_head"
        ],
        "selected_duckdb_thread_count": config["thread_preflight"][
            "duckdb_thread_count"
        ],
        "benchmark_security_ids": config["thread_preflight"]["benchmark_security_ids"],
        "score_release_id": config["score_release"]["score_release_id"],
        "score_database_sha256": config["score_release"]["sha256"],
        "score_database_byte_size": config["score_release"]["byte_size"],
        "score_source_unchanged": True,
        "request_id": canonical_request["request_id"],
        "request_hash": canonical_request["request_hash"],
        "security_ids": config["thread_preflight"]["benchmark_security_ids"],
        "duckdb_thread_count": config["thread_preflight"]["duckdb_thread_count"],
        "market_validator_status": "passed",
        "market_present_key_missing_count": 0,
        "market_source_unchanged": True,
        "validator_status": "passed",
    }
    for field, value in required_receipt.items():
        _require_equal(
            actual=receipt.get(field),
            expected=value,
            reason_code=f"formal_smoke_receipt_{field}_mismatch",
            stage="authorization",
        )
    _require_equal(
        actual=benchmark["security_ids"],
        expected=receipt["security_ids"],
        reason_code="formal_benchmark_security_binding_mismatch",
        stage="authorization",
    )

    identity_verifier(
        score_database,
        expected_sha256=str(config["score_release"]["sha256"]),
        expected_byte_size=int(config["score_release"]["byte_size"]),
    )
    market_spec = market_source_spec_identity(market_source_spec_path)
    market_identity = identity_verifier(
        market_database,
        expected_sha256=str(market_spec["database_sha256"]),
        expected_byte_size=int(market_spec["database_byte_size"]),
    )
    current_market = {
        "market_source_spec_basename": market_spec["basename"],
        "market_source_spec_sha256": market_spec["sha256"],
        "market_source_spec_byte_size": market_spec["byte_size"],
        "market_source_query_sha256": market_spec["source_query_sha256"],
        "market_source_id": market_spec["source_id"],
        "market_source_snapshot_id": market_spec["source_snapshot_id"],
        "market_database_basename": market_spec["database_basename"],
        "market_database_sha256": market_identity["sha256"],
        "market_database_byte_size": market_identity["byte_size"],
    }
    for field, value in current_market.items():
        _require_equal(
            actual=receipt.get(field),
            expected=value,
            reason_code=f"formal_smoke_receipt_{field}_mismatch",
            stage="authorization",
        )
    return receipt
