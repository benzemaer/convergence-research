from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.r2a.r2a_t04_audit_validator import (
    REQUIRED_COMPACT_FILES,
    R2AT04ValidationError,
    validate_response_rows,
    validate_review_bundle,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _response_fixture() -> list[dict[str, object]]:
    universe = [("S1", f"2026-01-{day:02d}") for day in range(1, 7)]
    raw_sets = {"CA_q15_k5": {0, 1}, "CA_q25_k5": {0, 1, 2, 3}}
    confirmed_sets = {
        "CA_q15_k5": {0},
        "CA_q25_k5": {0, 1},
    }
    return [
        {
            "logical_request_name": name,
            "security_id": security_id,
            "trading_date": trading_date,
            "joint_ready": True,
            "raw_state": index in raw_indices,
            "confirmed_state": index in confirmed_sets[name],
        }
        for name, raw_indices in raw_sets.items()
        for index, (security_id, trading_date) in enumerate(universe)
    ]


def test_ca_response_subset_readiness_and_non_degeneracy() -> None:
    assert all(check["passed"] for check in validate_response_rows(_response_fixture()))


def test_response_subset_violation_and_degeneracy_are_blocking() -> None:
    rows = _response_fixture()
    next(
        row
        for row in rows
        if row["logical_request_name"] == "CA_q15_k5"
        and row["trading_date"] == "2026-01-06"
    )["raw_state"] = True
    with pytest.raises(R2AT04ValidationError, match="ca_q_raw_subset"):
        validate_response_rows(rows)
    degenerate = _response_fixture()
    for row in degenerate:
        row["raw_state"] = False
        row["confirmed_state"] = False
    with pytest.raises(R2AT04ValidationError, match="blocked_ca_q_response_degenerate"):
        validate_response_rows(degenerate)


def _write_csv(
    path: Path, headers: list[str], rows: list[list[object]] | None = None
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows or [])


def _valid_bundle(bundle: Path) -> dict[str, object]:
    bundle.mkdir()
    for name in REQUIRED_COMPACT_FILES:
        path = bundle / name
        if name == "request_output_profiles.json":
            path.write_text(
                json.dumps({f"R{i:02d}": {} for i in range(2)}) + "\n",
                encoding="utf-8",
            )
        elif name == "request_panel.json":
            path.write_text(json.dumps([{}] * 2) + "\n", encoding="utf-8")
        elif name == "score_source_identity.json":
            path.write_text(
                json.dumps(
                    {
                        "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
                        "sha256": (
                            "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462"
                            "ce61c3f176403a3"
                        ),
                        "byte_size": 4255395840,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        elif name == "validation_receipt.json":
            path.write_text('{"status":"passed"}\n', encoding="utf-8")
        elif name == "result_analysis.md":
            path.write_text("# Score-only review\n", encoding="utf-8")
        elif name == "interval_samples.csv":
            _write_csv(
                path,
                [
                    "logical_request_name",
                    "request_hash",
                    "security_id",
                    "confirmation_date",
                    "interval_ordinal",
                    "sample_hash",
                ],
            )
        elif name == "score_dimension_endpoint_summary.csv":
            _write_csv(path, ["logical_request_name", "anchor_type", "dimension_id"])
        elif name == "score_component_endpoint_summary.csv":
            _write_csv(
                path,
                [
                    "logical_request_name",
                    "anchor_type",
                    "dimension_id",
                    "component_id",
                ],
            )
        else:
            _write_csv(path, ["logical_request_name"])
    files = [
        {
            "relative_path": name,
            "sha256": _sha(bundle / name),
            "byte_size": (bundle / name).stat().st_size,
        }
        for name in sorted(REQUIRED_COMPACT_FILES)
    ]
    summary: dict[str, object] = {
        "task_id": "R2A-T04",
        "bundle_mode": "formal_review",
        "scope_id": "r2a_t04_ca_q15_q25_k5_response_audit.v1",
        "status": "score_audit_completed_pending_result_review",
        "formal_run_id": "R2A-T04-20260719T000000000Z",
        "formal_authorization_id": "R2A-T04-CA-Q-AUDIT-AUTH-20260720-R5",
        "authorization_revision": 5,
        "panel_id": "r2a_t04_ca_q15_q25_k5_panel.v1",
        "request_count": 2,
        "score_source": {
            "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
            "sha256": (
                "d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3"
            ),
            "byte_size": 4255395840,
        },
        "execution": {
            "full_universe_request_concurrency": 1,
            "duckdb_thread_count": 4,
            "formal_run_consumed": True,
        },
        "validation": {
            "request_validator_failure_count": 0,
            "response_violation_count": 0,
            "scope_security_count_mismatch_count": 0,
            "interval_reconciliation_failure_count": 0,
            "score_endpoint_reconciliation_failure_count": 0,
            "blocking_anomaly_count": 0,
            "status": "passed",
        },
        "review_boundary": {
            "automated_recommendation": "continue_to_owner_result_review",
            "owner_result_review": "pending",
            "R2A_T04_DONE": "absent",
            "R2A_T05_allowed_to_start": False,
        },
        "files": files,
    }
    (bundle / "run_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    return summary


def test_review_bundle_exact_score_only_inventory(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _valid_bundle(bundle)
    receipt = validate_review_bundle(bundle)
    assert receipt["status"] == "passed"
    assert not (bundle / "charts").exists()


def test_review_bundle_rejects_done_absolute_and_forbidden_fields(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    summary = _valid_bundle(bundle)
    (bundle / "DONE").write_text("forbidden\n", encoding="utf-8")
    with pytest.raises(R2AT04ValidationError, match="t04_done_forbidden"):
        validate_review_bundle(bundle)
    (bundle / "DONE").unlink()
    summary["files"][0]["relative_path"] = "C:/outside.csv"
    (bundle / "run_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    with pytest.raises(R2AT04ValidationError):
        validate_review_bundle(bundle)
    summary = _valid_bundle(tmp_path / "forbidden")
    summary["market_source"] = {"sha256": "0" * 64}
    (tmp_path / "forbidden" / "run_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    with pytest.raises(R2AT04ValidationError):
        validate_review_bundle(tmp_path / "forbidden")


def test_review_bundle_rejects_sample_hash_and_extra_file(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _valid_bundle(bundle)
    _write_csv(
        bundle / "interval_samples.csv",
        [
            "logical_request_name",
            "request_hash",
            "security_id",
            "confirmation_date",
            "interval_ordinal",
            "sample_hash",
        ],
        [["R", "a" * 64, "S1", "2026-01-01", 1, "0" * 64]],
    )
    summary = json.loads((bundle / "run_summary.json").read_text(encoding="utf-8"))
    item = next(
        item
        for item in summary["files"]
        if item["relative_path"] == "interval_samples.csv"
    )
    item.update(
        {
            "sha256": _sha(bundle / "interval_samples.csv"),
            "byte_size": (bundle / "interval_samples.csv").stat().st_size,
        }
    )
    (bundle / "run_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    with pytest.raises(R2AT04ValidationError, match="interval_sample_hash_mismatch"):
        validate_review_bundle(bundle)
    (bundle / "unexpected.png").write_bytes(b"PNG")
    with pytest.raises(R2AT04ValidationError):
        validate_review_bundle(bundle)
