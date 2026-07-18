from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.r2a.r2a_t04_audit_validator import (
    R2AT04ValidationError,
    recompute_path_metrics,
    validate_marginal_dimension_rows,
    validate_response_rows,
    validate_review_bundle,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_smoke_bundle(bundle: Path, artifact: Path) -> dict[str, object]:
    summary: dict[str, object] = {
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
                "relative_path": artifact.relative_to(bundle).as_posix(),
                "sha256": _sha256(artifact),
                "byte_size": artifact.stat().st_size,
            }
        ],
    }
    (bundle / "run_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    return summary


def _response_fixture() -> list[dict[str, object]]:
    universe = [("S1", f"2026-01-{day:02d}") for day in range(1, 7)]
    raw_sets = {
        "Q01_PCAVT_q10_k3": {0},
        "D05_PCAVT_q15_k3": {0, 1},
        "Q02_PCAVT_q20_k3": {0, 1, 2},
        "Q03_PCAVT_q25_k3": {0, 1, 2, 3},
        "K01_PCAVT_q15_k2": {0, 1},
        "K02_PCAVT_q15_k5": {0, 1},
        "K03_PCAVT_q15_k7": {0, 1},
        "D04_PCAV_q15_k3": {0, 1, 2},
        "D03_PCA_q15_k3": {0, 1, 2, 3},
        "D02_PA_q15_k3": {0, 1, 2, 3, 4},
        "D01_P_q15_k3": {0, 1, 2, 3, 4, 5},
    }
    confirmed_sets = {
        "Q01_PCAVT_q10_k3": {0},
        "D05_PCAVT_q15_k3": {0, 1},
        "Q02_PCAVT_q20_k3": {0, 1, 2},
        "Q03_PCAVT_q25_k3": {0, 1, 2, 3},
        "K01_PCAVT_q15_k2": {0, 1, 2},
        "K02_PCAVT_q15_k5": {0, 1},
        "K03_PCAVT_q15_k7": {0},
        "D04_PCAV_q15_k3": {0, 1, 2},
        "D03_PCA_q15_k3": {0, 1, 2, 3},
        "D02_PA_q15_k3": {0, 1, 2, 3, 4},
        "D01_P_q15_k3": {0, 1, 2, 3, 4, 5},
    }
    rows = []
    for name, raw_indices in raw_sets.items():
        for index, (security_id, trading_date) in enumerate(universe):
            rows.append(
                {
                    "logical_request_name": name,
                    "security_id": security_id,
                    "trading_date": trading_date,
                    "joint_ready": True,
                    "raw_state": index in raw_indices,
                    "confirmed_state": index in confirmed_sets[name],
                }
            )
    return rows


def test_response_subset_k_equality_and_non_degeneracy() -> None:
    checks = validate_response_rows(_response_fixture())
    assert all(check["passed"] for check in checks)


def test_response_subset_violation_is_blocking() -> None:
    rows = _response_fixture()
    next(
        row
        for row in rows
        if row["logical_request_name"] == "Q01_PCAVT_q10_k3"
        and row["trading_date"] == "2026-01-06"
    )["raw_state"] = True
    with pytest.raises(R2AT04ValidationError, match="q_raw_subset"):
        validate_response_rows(rows)


def test_marginal_non_target_invariance_and_target_superset() -> None:
    baseline = []
    candidate = []
    for dimension in ("P", "A"):
        for day in range(2):
            row = {
                "security_id": "S1",
                "trading_date": f"2026-01-0{day + 1}",
                "dimension_id": dimension,
                "q_bp": 1500,
                "main_threshold": 0.85,
                "weak_threshold": 0.75,
                "dimension_ready": True,
                "dimension_active": day == 0,
            }
            baseline.append(row)
            changed = dict(row)
            if dimension == "P":
                changed["q_bp"] = 2500
                changed["main_threshold"] = 0.75
                changed["weak_threshold"] = 0.65
                changed["dimension_active"] = True
            candidate.append(changed)
    result = validate_marginal_dimension_rows(baseline, candidate, target_dimension="P")
    assert result["strict_target_expansion"] is True


def test_observation_offset_path_metrics_and_censoring() -> None:
    first = date(2026, 1, 1)
    observations = [
        {
            "trading_date": first + timedelta(days=index),
            "adj_close": 10 + index,
            "adj_high": 10.5 + index,
            "adj_low": 9.5 + index,
        }
        for index in range(25)
    ]
    metrics = recompute_path_metrics(observations, anchor_index=0, horizon=20)
    assert metrics["horizon_available"] is True
    assert metrics["time_to_peak"] == 20
    assert metrics["time_to_trough"] == 1
    censored = recompute_path_metrics(observations, anchor_index=10, horizon=20)
    assert censored["horizon_available"] is False


def test_review_bundle_rejects_done_and_absolute_paths(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    artifact = bundle / "receipt.json"
    artifact.write_text("{}\n", encoding="utf-8")
    summary = _write_smoke_bundle(bundle, artifact)
    (bundle / "DONE").write_text("forbidden\n", encoding="utf-8")
    with pytest.raises(R2AT04ValidationError, match="t04_done_forbidden"):
        validate_review_bundle(bundle)
    (bundle / "DONE").unlink()
    summary["files"][0]["relative_path"] = "C:/outside.json"
    (bundle / "run_summary.json").write_text(
        json.dumps(summary) + "\n", encoding="utf-8"
    )
    with pytest.raises(R2AT04ValidationError, match="absolute_path_in_bundle"):
        validate_review_bundle(bundle)


def test_review_bundle_rejects_large_artifact_and_missing_chart(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    artifact = bundle / "large.bin"
    with artifact.open("wb") as handle:
        handle.truncate(61 * 1024 * 1024)
    _write_smoke_bundle(bundle, artifact)
    with pytest.raises(R2AT04ValidationError, match="review_bundle_exceeds_60_mb"):
        validate_review_bundle(bundle)
    artifact.unlink()
    artifact = bundle / "receipt.json"
    artifact.write_text("{}\n", encoding="utf-8")
    _write_smoke_bundle(bundle, artifact)
    (bundle / "chart_sample_registry.csv").write_text(
        "chart_path\ncharts/missing.png\n", encoding="utf-8"
    )
    with pytest.raises(R2AT04ValidationError, match="chart_file_missing"):
        validate_review_bundle(bundle)
