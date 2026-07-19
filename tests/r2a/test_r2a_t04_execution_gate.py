from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.r2a import run_r2a_t04_real_data_audit as formal_cli
from src.r2a.r2a_t04_execution_gate import (
    R2AT04ExecutionGateError,
    validate_frozen_thread_benchmark_receipt,
    validate_score_formal_execution_gate,
)
from src.r2a.r2a_t04_request_panel import build_request_panel

AUTHORIZATION_HEAD = "b" * 40
REPAIR_HEAD = "a" * 40
TABLES = (
    "dynamic_request",
    "evaluation_scope",
    "daily_dimension_states",
    "daily_joint_states",
    "confirmed_intervals",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config() -> dict[str, object]:
    config = json.loads(
        Path("configs/r2a/r2a_t04_real_data_audit.v1.json").read_text(encoding="utf-8")
    )
    config.update(
        {
            "status": "authorized_not_started",
            "authorization_revision": 3,
            "reviewed_harness_head": REPAIR_HEAD,
            "formal_run_authorized": True,
            "formal_run_started": False,
            "formal_run_consumed": False,
            "authorization_effective_only_after_exact_head_quality_success": True,
            "supersedes_authorization_head": (
                "9d3c2dab43a10b12931db921ef730db6e8552ff1"
            ),
        }
    )
    return config


def _profile() -> dict[str, object]:
    return {
        "row_count": 0,
        "schema_fingerprint": "1" * 64,
        "canonical_fingerprint": "2" * 64,
        "fingerprint_algorithm": "arrow_ipc_fixed_logical_row_chunks.v1",
        "canonical_chunk_row_count": 65536,
        "canonical_chunk_count": 0,
        "canonical_chunk_fingerprints": [],
    }


def _comparison() -> dict[str, object]:
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


def _receipt() -> dict[str, object]:
    profiles = {name: _profile() for name in TABLES}
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
        "request_id": "pcavt-dynreq-v1-2937df4f84219640",
        "request_hash": (
            "2937df4f8421964007b5d479a6b1f959564096bbe5df18ffe35b91b325192722"
        ),
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
                "output_tables": deepcopy(profiles),
            }
            for threads in (4, 8, 16)
        ],
        "pairwise_comparisons": [
            {
                "left_threads": left,
                "right_threads": right,
                "status": "logically_equal",
                "tables": {name: _comparison() for name in TABLES},
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


def _write_receipt(path: Path, config: dict[str, object]) -> None:
    path.write_text(json.dumps(_receipt(), indent=2) + "\n", encoding="utf-8")
    preflight = config["thread_preflight"]
    preflight["thread_benchmark_receipt_sha256"] = _sha(path)
    preflight["thread_benchmark_receipt_byte_size"] = path.stat().st_size


def _identity(
    path: Path, *, expected_sha256: str, expected_byte_size: int
) -> dict[str, object]:
    return {
        "filename": path.name,
        "sha256": expected_sha256,
        "byte_size": expected_byte_size,
    }


def _benchmark(_path: Path, config: dict[str, object]) -> dict[str, object]:
    return {
        "thread_benchmark_fingerprint": config["thread_preflight"][
            "thread_benchmark_fingerprint"
        ]
    }


def _gate(tmp_path: Path, **overrides: object) -> dict[str, object]:
    config = _config()
    panel = build_request_panel(config)
    score = tmp_path / "score.duckdb"
    score.touch()
    arguments = {
        "config": config,
        "authorization_head": AUTHORIZATION_HEAD,
        "authorization_parent": REPAIR_HEAD,
        "score_database": score,
        "thread_benchmark_receipt_path": tmp_path / "benchmark.json",
        "panel": panel,
        "identity_verifier": _identity,
        "benchmark_validator": _benchmark,
    }
    arguments.update(overrides)
    return validate_score_formal_execution_gate(**arguments)


def test_score_formal_gate_accepts_only_frozen_contract(tmp_path: Path) -> None:
    receipt = _gate(tmp_path)
    assert receipt["status"] == "passed"
    assert receipt["duckdb_thread_count"] == 4
    assert receipt["request_count"] == 16


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("authorization_revision", 2, "formal_config_authorization_revision_mismatch"),
        (
            "formal_run_authorized",
            False,
            "formal_config_formal_run_authorized_mismatch",
        ),
        (
            "full_universe_request_concurrency",
            2,
            "formal_config_full_universe_request_concurrency_mismatch",
        ),
    ],
)
def test_score_formal_gate_rejects_config_mutations(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    config = _config()
    config[field] = value
    with pytest.raises(R2AT04ExecutionGateError, match=reason):
        _gate(tmp_path, config=config, panel=build_request_panel(config))


def test_score_formal_gate_rejects_wrong_head_and_parent(tmp_path: Path) -> None:
    with pytest.raises(R2AT04ExecutionGateError, match="authorization_head_invalid"):
        _gate(tmp_path, authorization_head="wrong")
    with pytest.raises(R2AT04ExecutionGateError, match="authorization_parent_mismatch"):
        _gate(tmp_path, authorization_parent="c" * 40)
    with pytest.raises(
        R2AT04ExecutionGateError, match="authorization_head_is_superseded"
    ):
        _gate(
            tmp_path,
            authorization_head="9d3c2dab43a10b12931db921ef730db6e8552ff1",
        )


def test_score_formal_gate_rejects_score_identity(tmp_path: Path) -> None:
    def reject_identity(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ValueError("bound_file_sha256_mismatch")

    with pytest.raises(ValueError, match="bound_file_sha256_mismatch"):
        _gate(tmp_path, identity_verifier=reject_identity)


def test_score_formal_gate_rejects_panel_count_and_threads(tmp_path: Path) -> None:
    config = _config()
    panel = build_request_panel(config)
    with pytest.raises(R2AT04ExecutionGateError, match="formal_panel_count_mismatch"):
        _gate(tmp_path, panel=panel[:-1])
    config["thread_preflight"]["duckdb_thread_count"] = 8
    with pytest.raises(
        R2AT04ExecutionGateError, match="formal_duckdb_thread_count_mismatch"
    ):
        _gate(tmp_path, config=config, panel=panel)


def test_formal_cli_accepts_only_five_frozen_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run",
            "--score-db",
            "score.duckdb",
            "--thread-benchmark-receipt",
            "benchmark.json",
            "--output-root",
            "formal",
            "--review-output",
            "review",
            "--formal-authorization-id",
            "authorization",
        ],
    )
    arguments = formal_cli.parse_args()
    assert set(vars(arguments)) == {
        "score_db",
        "thread_benchmark_receipt",
        "output_root",
        "review_output",
        "formal_authorization_id",
    }
    monkeypatch.setattr(sys, "argv", ["run", "--market-source-spec", "market.json"])
    with pytest.raises(SystemExit):
        formal_cli.parse_args()


def test_formal_cli_gate_failure_precedes_output_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "formal"
    review = tmp_path / "review"
    config = _config()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run",
            "--score-db",
            str(tmp_path / "score.duckdb"),
            "--thread-benchmark-receipt",
            str(tmp_path / "benchmark.json"),
            "--output-root",
            str(output),
            "--review-output",
            str(review),
            "--formal-authorization-id",
            str(config["formal_authorization_id"]),
        ],
    )
    monkeypatch.setattr(formal_cli, "load_audit_config", lambda: config)
    monkeypatch.setattr(
        formal_cli,
        "_git_output",
        lambda *args: "" if args[0] == "status" else "b" * 40,
    )
    with pytest.raises(R2AT04ExecutionGateError):
        formal_cli.main()
    assert not output.exists()
    assert not review.exists()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("sha", "thread_benchmark_receipt_sha256_mismatch"),
        ("size", "thread_benchmark_receipt_size_mismatch"),
        (
            "fingerprint",
            "thread_benchmark_receipt_thread_benchmark_fingerprint_mismatch",
        ),
        ("threads", "thread_benchmark_receipt_selected_duckdb_thread_count_mismatch"),
    ],
)
def test_frozen_benchmark_receipt_rejects_mutations(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    config = _config()
    path = tmp_path / "benchmark.json"
    _write_receipt(path, config)
    if mutation == "sha":
        config["thread_preflight"]["thread_benchmark_receipt_sha256"] = "f" * 64
    elif mutation == "size":
        config["thread_preflight"]["thread_benchmark_receipt_byte_size"] += 1
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "fingerprint":
            value["thread_benchmark_fingerprint"] = "f" * 64
        else:
            value["selected_duckdb_thread_count"] = 8
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        config["thread_preflight"]["thread_benchmark_receipt_sha256"] = _sha(path)
        config["thread_preflight"]["thread_benchmark_receipt_byte_size"] = (
            path.stat().st_size
        )
    with pytest.raises(R2AT04ExecutionGateError, match=reason):
        validate_frozen_thread_benchmark_receipt(path, config)
