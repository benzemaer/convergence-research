"""Fail-closed Score-only execution bindings for R2A-T04."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from src.r2a.r2a_t04_real_data_audit import (
    R2AT04AuditError,
    sha256_file,
    verify_file_identity,
)

ROOT = Path(__file__).resolve().parents[2]
THREAD_RECEIPT_SCHEMA = (
    ROOT / "schemas/r2a/r2a_t04_thread_benchmark_receipt.schema.json"
)
OPTIMIZED_RECEIPT_SCHEMA = (
    ROOT / "schemas/r2a/r2a_t04_ca_set_based_benchmark_receipt.schema.json"
)
EXPECTED_CA_REQUESTS = (
    (
        "CA_q15_k5",
        "pcavt-dynreq-v1-cf420e9c025374d1",
        "cf420e9c025374d19bbc4e83bd75fee96d10d0c322605826ae5cffcf4029674f",
    ),
    (
        "CA_q25_k5",
        "pcavt-dynreq-v1-b210f9e5211c46db",
        "b210f9e5211c46db6cbc41ca1da9ff340018b4ef69e56df07ae22cecafbad3e9",
    ),
)
EXPECTED_REQUEST_ID = "pcavt-dynreq-v1-2937df4f84219640"
EXPECTED_REQUEST_HASH = (
    "2937df4f8421964007b5d479a6b1f959564096bbe5df18ffe35b91b325192722"
)
EXPECTED_SECURITY_IDS = (
    "603345.SH",
    "603233.SH",
    "688220.SH",
    "300316.SZ",
)


class R2AT04ExecutionGateError(ValueError):
    """Stable fail-closed execution-gate error."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")


def _require_equal(*, actual: Any, expected: Any, reason_code: str) -> None:
    if actual != expected:
        raise R2AT04ExecutionGateError(reason_code)


def _validated_json(path: Path, schema_path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise R2AT04ExecutionGateError(
            "thread_benchmark_receipt_schema_invalid", type(error).__name__
        ) from error
    return dict(value)


def validate_frozen_thread_benchmark_receipt(
    receipt_path: str | Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the frozen benchmark file, schema, and execution bindings."""

    path = Path(receipt_path)
    preflight = config["thread_preflight"]
    if not path.is_file():
        raise R2AT04ExecutionGateError("thread_benchmark_receipt_missing")
    _require_equal(
        actual=path.stat().st_size,
        expected=int(preflight["thread_benchmark_receipt_byte_size"]),
        reason_code="thread_benchmark_receipt_size_mismatch",
    )
    _require_equal(
        actual=sha256_file(path),
        expected=str(preflight["thread_benchmark_receipt_sha256"]),
        reason_code="thread_benchmark_receipt_sha256_mismatch",
    )
    receipt = _validated_json(path, THREAD_RECEIPT_SCHEMA)
    expected = {
        "status": "passed",
        "reason_code": "passed",
        "implementation_head": preflight["benchmark_execution_head"],
        "score_release_id": config["score_release"]["score_release_id"],
        "score_database_sha256": config["score_release"]["sha256"],
        "score_database_byte_size": config["score_release"]["byte_size"],
        "request_id": EXPECTED_REQUEST_ID,
        "request_hash": EXPECTED_REQUEST_HASH,
        "selected_duckdb_thread_count": 4,
        "thread_benchmark_fingerprint": preflight["thread_benchmark_fingerprint"],
        "security_ids": list(EXPECTED_SECURITY_IDS),
        "formal_run_attempt_consumed": False,
        "formal_run_authorized": False,
    }
    for field, expected_value in expected.items():
        _require_equal(
            actual=receipt.get(field),
            expected=expected_value,
            reason_code=f"thread_benchmark_receipt_{field}_mismatch",
        )
    return receipt


def validate_ca_set_based_benchmark_receipt(
    config: Mapping[str, Any],
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the committed equivalence and full-universe performance evidence."""

    optimized = config["optimized_benchmark"]
    path = receipt_path or ROOT / str(optimized["receipt_path"])
    if not path.is_file():
        raise R2AT04ExecutionGateError("optimized_benchmark_receipt_missing")
    _require_equal(
        actual=sha256_file(path),
        expected=optimized["receipt_sha256"],
        reason_code="optimized_benchmark_receipt_sha256_mismatch",
    )
    receipt = _validated_json(path, OPTIMIZED_RECEIPT_SCHEMA)
    expected = {
        "status": "passed",
        "implementation_head": optimized["implementation_head"],
        "implementation_quality": optimized["implementation_quality"],
        "scope_id": config["scope_id"],
        "panel_id": config["panel_id"],
        "request_count": 2,
        "score_release_id": config["score_release"]["score_release_id"],
        "score_database_sha256": config["score_release"]["sha256"],
        "score_database_byte_size": config["score_release"]["byte_size"],
        "formal_run_started": False,
        "formal_attempt_consumed": False,
        "scientific_result_generated": False,
        "contains_absolute_paths": False,
        "source_database_modified": False,
        "residual_output_count": 0,
    }
    for field, expected_value in expected.items():
        _require_equal(
            actual=receipt.get(field),
            expected=expected_value,
            reason_code=f"optimized_benchmark_receipt_{field}_mismatch",
        )
    identities = tuple(
        (
            item.get("logical_request_name"),
            item.get("request_id"),
            item.get("request_hash"),
        )
        for item in receipt["requests"]
    )
    _require_equal(
        actual=identities,
        expected=EXPECTED_CA_REQUESTS,
        reason_code="optimized_benchmark_request_identity_mismatch",
    )
    equivalence = receipt["equivalence"]
    _require_equal(
        actual=equivalence.get("all_tables_logically_equal"),
        expected=True,
        reason_code="optimized_benchmark_equivalence_failed",
    )
    _require_equal(
        actual=equivalence.get("canonical_profiles_equal"),
        expected=True,
        reason_code="optimized_benchmark_profile_equivalence_failed",
    )
    _require_equal(
        actual=len(equivalence.get("request_results", [])),
        expected=2,
        reason_code="optimized_benchmark_equivalence_request_count_mismatch",
    )
    for item in equivalence["request_results"]:
        _require_equal(
            actual=item.get("comparison_status"),
            expected="logically_equal",
            reason_code="optimized_benchmark_logical_comparison_failed",
        )
        if any(int(value) for value in item.get("mismatch_counts", {}).values()):
            raise R2AT04ExecutionGateError("optimized_benchmark_mismatch_nonzero")
    full = receipt["full_universe"]
    _require_equal(
        actual=full.get("performance_gate_passed"),
        expected=True,
        reason_code="optimized_benchmark_performance_failed",
    )
    _require_equal(
        actual=len(full.get("request_results", [])),
        expected=2,
        reason_code="optimized_benchmark_full_request_count_mismatch",
    )
    for item in full["request_results"]:
        if (
            item.get("validator_status") != "passed"
            or int(item.get("evaluated_security_count", 0)) != 800
            or float(item.get("wall_seconds", float("inf"))) > 600
            or int(item.get("peak_rss_bytes", 2**63)) > 6_442_450_944
        ):
            raise R2AT04ExecutionGateError("optimized_benchmark_request_gate_failed")
    if float(full.get("combined_wall_seconds", float("inf"))) > 1200:
        raise R2AT04ExecutionGateError("optimized_benchmark_combined_wall_failed")
    return receipt


def validate_score_formal_execution_gate(
    *,
    config: Mapping[str, Any],
    authorization_head: str,
    authorization_parent: str,
    score_database: Path,
    thread_benchmark_receipt_path: Path,
    panel: Sequence[Mapping[str, Any]],
    identity_verifier: Callable[..., dict[str, Any]] = verify_file_identity,
    benchmark_validator: Callable[..., dict[str, Any]] = (
        validate_frozen_thread_benchmark_receipt
    ),
    optimized_benchmark_validator: Callable[..., dict[str, Any]] = (
        validate_ca_set_based_benchmark_receipt
    ),
) -> dict[str, Any]:
    """Validate all Score-only bindings before an output root may be created."""

    expected_config = {
        "scope_id": "r2a_t04_ca_q15_q25_k5_response_audit.v1",
        "status": "authorized_not_started",
        "authorization_revision": 5,
        "formal_run_authorized": True,
        "formal_run_started": False,
        "formal_run_consumed": False,
        "authorization_effective_only_after_exact_head_quality_success": True,
        "panel_id": "r2a_t04_ca_q15_q25_k5_panel.v1",
        "request_panel_count": 2,
        "full_universe_request_concurrency": 1,
    }
    for field, expected in expected_config.items():
        _require_equal(
            actual=config.get(field),
            expected=expected,
            reason_code=f"formal_config_{field}_mismatch",
        )
    _require_equal(
        actual=authorization_parent,
        expected=config.get("reviewed_harness_head"),
        reason_code="authorization_parent_mismatch",
    )
    if not re.fullmatch(r"[0-9a-f]{40}", authorization_head):
        raise R2AT04ExecutionGateError("authorization_head_invalid")
    if authorization_head == config.get("supersedes_authorization_head"):
        raise R2AT04ExecutionGateError("authorization_head_is_superseded")
    if len(panel) != 2:
        raise R2AT04ExecutionGateError("formal_panel_count_mismatch")
    logical_names = [str(item.get("logical_request_name")) for item in panel]
    if tuple(logical_names) != tuple(item[0] for item in EXPECTED_CA_REQUESTS):
        raise R2AT04ExecutionGateError("formal_panel_identity_not_unique")
    preflight = config["thread_preflight"]
    _require_equal(
        actual=preflight.get("duckdb_thread_count"),
        expected=4,
        reason_code="formal_duckdb_thread_count_mismatch",
    )
    score_identity = identity_verifier(
        score_database,
        expected_sha256=str(config["score_release"]["sha256"]),
        expected_byte_size=int(config["score_release"]["byte_size"]),
    )
    try:
        benchmark = benchmark_validator(thread_benchmark_receipt_path, config)
    except R2AT04AuditError as error:
        raise R2AT04ExecutionGateError(error.reason_code) from error
    optimized_benchmark = optimized_benchmark_validator(config)
    return {
        "status": "passed",
        "authorization_head": authorization_head,
        "authorization_parent": authorization_parent,
        "authorization_revision": 5,
        "scope_id": config["scope_id"],
        "score_identity": score_identity,
        "benchmark_receipt_sha256": preflight["thread_benchmark_receipt_sha256"],
        "benchmark_fingerprint": benchmark["thread_benchmark_fingerprint"],
        "optimized_benchmark_receipt_sha256": config["optimized_benchmark"][
            "receipt_sha256"
        ],
        "optimized_evaluator_head": optimized_benchmark["implementation_head"],
        "duckdb_thread_count": 4,
        "panel_id": config["panel_id"],
        "request_count": 2,
        "full_universe_request_concurrency": 1,
        "formal_run_started": False,
        "formal_run_consumed": False,
    }
