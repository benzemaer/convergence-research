from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.r1.r1_t02_lineage_pit_audit import run_r1_t02_lineage_pit_audit
from src.r1.r1_t02_lineage_pit_audit_validator import (
    R1T02LineagePitAuditValidationError,
    sha256_file,
    validate_r1_t02_lineage_pit_audit,
)

FULL_SHA = "1111111111111111111111111111111111111111"
R1_T01_CONFIG_PATH = "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"
R1_T01_EVIDENCE_PATH = (
    "docs/evidence/r1/R1-T01_validation_protocol_manifest_lock_evidence.md"
)
R0_INPUT_LOCK_SOURCE = f"{R1_T01_CONFIG_PATH}#/r0_input_package_lock"
R0_STRICT_PAST_EVIDENCE_PATH = (
    "docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md"
)


class R1T02LineagePitAuditContractTest(unittest.TestCase):
    def test_audit_and_validator_pass_on_synthetic_locked_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture_audit(root, fixture)
            self.assertEqual(summary["status"], "completed")
            evidence = _write_r1_t02_evidence(root, summary)
            result = validate_r1_t02_lineage_pit_audit(
                root / summary["summary_path"],
                evidence,
            )
            self.assertEqual(result["validator_status"], "passed")

    def test_future_field_in_manifest_blocks_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            full_grid = _load_json(fixture["full_grid_manifest"])
            full_grid["future_return"] = "forbidden"
            _write_json(fixture["full_grid_manifest"], full_grid)
            _refresh_r1_lock_hashes(fixture)
            summary = _run_fixture_audit(root, fixture)
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("full_grid_manifest_forbidden_token_check", summary["checks"])

    def test_forbidden_r2_decision_output_blocks_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            full_grid = _load_json(fixture["full_grid_manifest"])
            full_grid["R2_decision_matrix"] = "forbidden"
            _write_json(fixture["full_grid_manifest"], full_grid)
            _refresh_r1_lock_hashes(fixture)
            summary = _run_fixture_audit(root, fixture)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(
                summary["checks"]["forbidden_column_absence_check"], "blocked"
            )

    def test_artifact_hash_mismatch_blocks_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            target = root / (
                "data/generated/r0/full_grid/configs/"
                "R0_W120_Q10_K2_WEAK_D010/candidate_daily_state.parquet"
            )
            target.write_text("tampered\n", encoding="utf-8")
            summary = _run_fixture_audit(root, fixture)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["checks"]["config_artifact_hashes"], "blocked")

    def test_missing_strict_past_evidence_blocks_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            fixture["r0_strict_past_evidence"].unlink()
            summary = _run_fixture_audit(root, fixture)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(
                summary["checks"]["strict_past_evidence_chain_check"], "blocked"
            )

    def test_unknown_to_false_marker_blocks_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            full_grid = _load_json(fixture["full_grid_manifest"])
            full_grid["quality_note"] = "unknown_to_false"
            _write_json(fixture["full_grid_manifest"], full_grid)
            _refresh_r1_lock_hashes(fixture)
            summary = _run_fixture_audit(root, fixture)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(
                summary["checks"]["unknown_blocked_semantics_check"], "blocked"
            )

    def test_validator_rejects_missing_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture_audit(root, fixture)
            evidence = _write_r1_t02_evidence(
                root, summary, include_validation_result=False
            )
            with self.assertRaises(R1T02LineagePitAuditValidationError):
                validate_r1_t02_lineage_pit_audit(
                    root / summary["summary_path"], evidence
                )

    def test_validator_rejects_evidence_that_unblocks_r2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture_audit(root, fixture)
            evidence = _write_r1_t02_evidence(root, summary, r2_allowed="true")
            with self.assertRaises(R1T02LineagePitAuditValidationError):
                validate_r1_t02_lineage_pit_audit(
                    root / summary["summary_path"], evidence
                )


def _run_fixture_audit(root: Path, fixture: dict[str, Path]) -> dict[str, object]:
    return run_r1_t02_lineage_pit_audit(
        output_dir=root / "data/generated/r1/r1_t02/R1-T02-fixture",
        run_id="R1-T02-fixture",
        code_commit=FULL_SHA,
        root=root,
        config_path=fixture["config"],
        r1_t01_config_path=fixture["r1_config"],
        r1_t01_evidence_path=fixture["r1_evidence"],
        r0_t10_evidence_path=fixture["r0_t10_evidence"],
        r0_t11_evidence_path=fixture["r0_t11_evidence"],
        r0_strict_past_evidence_path=fixture["r0_strict_past_evidence"],
    )


def _write_fixture(root: Path) -> dict[str, Path]:
    paths = {
        "config": root / "configs/r1/r1_t02_r0_lineage_pit_audit.v1.json",
        "r1_config": root
        / "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json",
        "r1_evidence": root
        / "docs/evidence/r1/R1-T01_validation_protocol_manifest_lock_evidence.md",
        "r0_t10_evidence": root
        / "docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md",
        "r0_t11_evidence": root
        / "docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md",
        "r0_strict_past_evidence": root / R0_STRICT_PAST_EVIDENCE_PATH,
        "authorized_manifest": root / "data/generated/r0/authorized.json",
        "full_grid_manifest": root / "data/generated/r0/full_grid/manifest.json",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(paths["config"], _r1_t02_config())
    authorized = {
        "manifest_type": "r0_t10_05_authorized_input_manifest",
        "authorized_r0_input": True,
        "row_payload_embedded": False,
        "forbidden_guards": {
            "no_future_fields": True,
            "no_backtest_fields": True,
            "no_portfolio_fields": True,
            "no_trade_signal_fields": True,
            "no_raw_external_marketdb_day_source": True,
            "no_synthetic_contract_grid": True,
            "no_return_fields": True,
            "no_legacy_v1": True,
        },
        "coverage": {
            "W": [120, 250, 500],
            "q": [0.1, 0.2, 0.3],
            "K": [2, 3, 5],
            "weak_delta": 0.1,
            "security_count": 800,
            "date_min": "20160104",
            "date_max": "20260630",
            "state_names": ["S_P", "S_PC", "S_PCT", "S_PCVT"],
        },
        "grid": {
            "selected_config_count": 27,
            "baseline_config_id": "R0_W250_Q20_K3_WEAK_D010",
        },
    }
    full_grid = _full_grid_manifest(root)
    _write_json(paths["authorized_manifest"], authorized)
    _write_json(paths["full_grid_manifest"], full_grid)
    r1_config = {
        "downstream_authorization": {
            "R1_T02_allowed_to_start_when_validator_status_passed": True,
            "downstream_R2_allowed_to_start": False,
        },
        "r0_input_package_lock": {
            "authorized_input_manifest_path": _rel(root, paths["authorized_manifest"]),
            "authorized_input_manifest_sha256": sha256_file(
                paths["authorized_manifest"]
            ),
            "full_grid_manifest_path": _rel(root, paths["full_grid_manifest"]),
            "full_grid_manifest_sha256": sha256_file(paths["full_grid_manifest"]),
            "selected_config_count": 27,
        },
    }
    _write_json(paths["r1_config"], r1_config)
    _write_evidence(
        paths["r1_evidence"],
        {
            "task_id": "R1-T01",
            "status": "completed",
            "validator_status": "passed",
            "R1-T02_allowed_to_start": "true",
        },
    )
    _write_evidence(
        paths["r0_t10_evidence"],
        {
            "task_id": "R0-T10-05",
            "status": "completed",
            "validator_status": "passed",
            "authorized_input_manifest_path": _rel(root, paths["authorized_manifest"]),
            "authorized_input_manifest_sha256": sha256_file(
                paths["authorized_manifest"]
            ),
            "global_manifest_path": _rel(root, paths["full_grid_manifest"]),
            "global_manifest_sha256": sha256_file(paths["full_grid_manifest"]),
        },
    )
    _write_evidence(
        paths["r0_t11_evidence"],
        {
            "task_id": "R0-T11",
            "status": "completed",
            "validator_status": "passed",
            "R1_allowed_to_start": "true",
            "R0-T10-05_evidence_path": _rel(root, paths["r0_t10_evidence"]),
            "R0-T10-05_evidence_sha256": sha256_file(paths["r0_t10_evidence"]),
        },
    )
    _write_evidence(
        paths["r0_strict_past_evidence"],
        {
            "task_id": "R0-T10-02",
            "status": "completed",
            "validator_status": "passed",
            "strict_past_percentile_check": "passed",
        },
    )
    return paths


def _r1_t02_config() -> dict[str, object]:
    return {
        "task_id": "R1-T02",
        "r1_t01_config_path": R1_T01_CONFIG_PATH,
        "r1_t01_evidence_path": R1_T01_EVIDENCE_PATH,
        "r0_input_package_lock_source": R0_INPUT_LOCK_SOURCE,
        "required_checks": [
            "r1_t01_gate",
            "r0_evidence_chain_hash",
            "strict_past_evidence_chain_check",
            "strict_past_artifact_field_check",
            "unknown_blocked_semantics_check",
            "confirmation_time_backfill_check",
            "forbidden_column_absence_check",
            "row_payload_absence_check",
            "validation_result_path_hash_check",
            "locked_manifest_hashes",
            "config_artifact_hashes",
            "zero_interval_consistency",
        ],
        "zero_interval_policy": {
            "confirmed_interval_row_count_total_zero_handling": (
                "treat_as_input_fact_and_do_not_backfill"
            ),
            "confirmation_time_backfill_allowed": False,
            "daily_confirmed_true_count_total_must_be_zero": True,
            "all_config_zero_interval_required": True,
        },
        "strict_artifacts": {
            "hash_check": True,
            "path_existence_check": True,
            "row_payload_embedding_allowed": False,
            "field_level_strict_past_check": "evidence_chain_only",
        },
    }


def _full_grid_manifest(root: Path) -> dict[str, object]:
    configs = []
    selected_ids = []
    artifacts = {}
    daily_rows = {}
    interval_rows = {}
    true_rows = {}
    for w in (120, 250, 500):
        for q_label, q_value in (("10", 0.1), ("20", 0.2), ("30", 0.3)):
            for k in (2, 3, 5):
                config_id = f"R0_W{w}_Q{q_label}_K{k}_WEAK_D010"
                selected_ids.append(config_id)
                configs.append(
                    {
                        "candidate_config_id": config_id,
                        "percentile_window_W": w,
                        "low_quantile_q": q_value,
                        "confirmation_days_K": k,
                        "dimension_rule": "weak",
                        "weak_delta": 0.1,
                        "is_baseline_config": config_id == "R0_W250_Q20_K3_WEAK_D010",
                    }
                )
                artifacts[config_id] = _write_artifacts(root, config_id)
                daily_rows[config_id] = 10
                interval_rows[config_id] = 0
                true_rows[config_id] = 0
    return {
        "manifest_type": "r0_t10_05_full_grid_manifest",
        "status": "completed",
        "row_payload_embedded": False,
        "selected_config_count": 27,
        "completed_config_count": 27,
        "failed_config_count": 0,
        "candidate_configs": configs,
        "selected_config_ids": selected_ids,
        "artifacts_by_config": artifacts,
        "daily_row_count_by_config": daily_rows,
        "confirmed_interval_row_count_by_config": interval_rows,
        "daily_confirmed_true_count_by_config": true_rows,
        "daily_candidate_row_count_total": 270,
        "confirmed_interval_row_count_total": 0,
        "daily_confirmed_true_count_total": 0,
        "confirmed_interval_zero_config_count": 27,
        "baseline_config_id": "R0_W250_Q20_K3_WEAK_D010",
        "zero_interval_reason": "no_confirmed_segments_in_r0_t07_input",
    }


def _write_artifacts(root: Path, config_id: str) -> dict[str, str]:
    base = root / "data/generated/r0/full_grid/configs" / config_id
    base.mkdir(parents=True, exist_ok=True)
    for name in (
        "DONE.json",
        "candidate_config_snapshot.json",
        "candidate_daily_state.duckdb",
        "candidate_daily_state.parquet",
        "candidate_confirmed_interval.duckdb",
        "candidate_confirmed_interval.parquet",
    ):
        path = base / name
        path.write_text(f"{config_id}:{name}\n", encoding="utf-8")
    return {
        "DONE_path": _rel(root, base / "DONE.json"),
        "config_snapshot_path": _rel(root, base / "candidate_config_snapshot.json"),
        "daily_duckdb_path": _rel(root, base / "candidate_daily_state.duckdb"),
        "daily_duckdb_sha256": sha256_file(base / "candidate_daily_state.duckdb"),
        "daily_parquet_path": _rel(root, base / "candidate_daily_state.parquet"),
        "daily_parquet_sha256": sha256_file(base / "candidate_daily_state.parquet"),
        "interval_duckdb_path": _rel(
            root, base / "candidate_confirmed_interval.duckdb"
        ),
        "interval_duckdb_sha256": sha256_file(
            base / "candidate_confirmed_interval.duckdb"
        ),
        "interval_parquet_path": _rel(
            root, base / "candidate_confirmed_interval.parquet"
        ),
        "interval_parquet_sha256": sha256_file(
            base / "candidate_confirmed_interval.parquet"
        ),
    }


def _write_r1_t02_evidence(
    root: Path,
    summary: dict[str, object],
    *,
    r2_allowed: str = "false",
    include_validation_result: bool = True,
) -> Path:
    path = root / "docs/evidence/r1/R1-T02_r0_lineage_pit_audit_evidence.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_path = root / str(summary["summary_path"])
    validation_result_path = root / "data/generated/r1/r1_t02/validation_result.json"
    if include_validation_result:
        _write_json(
            validation_result_path,
            {
                "task_id": "R1-T02",
                "validator_status": "passed",
                "summary_path": _display_path(summary_path),
                "summary_sha256": sha256_file(summary_path),
                "errors": [],
            },
        )
    fields = {
        "task_id": "R1-T02",
        "status": "completed",
        "validator_status": "passed",
        "code_commit": FULL_SHA,
        "summary_path": _display_path(summary_path),
        "summary_sha256": sha256_file(summary_path),
        "authorized_input_manifest_path": summary["authorized_input_manifest_path"],
        "authorized_input_manifest_sha256": summary["authorized_input_manifest_sha256"],
        "full_grid_manifest_path": summary["full_grid_manifest_path"],
        "full_grid_manifest_sha256": summary["full_grid_manifest_sha256"],
        "r1_t01_evidence_path": summary["r1_t01_evidence_path"],
        "r1_t01_evidence_sha256": summary["r1_t01_evidence_sha256"],
        "r0_t10_05_evidence_path": summary["r0_t10_05_evidence_path"],
        "r0_t10_05_evidence_sha256": summary["r0_t10_05_evidence_sha256"],
        "r0_t11_evidence_path": summary["r0_t11_evidence_path"],
        "r0_t11_evidence_sha256": summary["r0_t11_evidence_sha256"],
        "r0_strict_past_evidence_path": summary["r0_strict_past_evidence_path"],
        "r0_strict_past_evidence_sha256": summary["r0_strict_past_evidence_sha256"],
        "row_payload_embedded": "false",
        "forbidden_input_check": "passed",
        "forbidden_output_check": "passed",
        "no_future_label_check": "passed",
        "no_backtest_check": "passed",
        "no_trading_signal_check": "passed",
        "config_artifact_hash_check": "passed",
        "zero_interval_consistency_check": "passed",
        "strict_past_evidence_chain_check": "passed",
        "strict_past_artifact_field_check": "evidence_chain_only",
        "unknown_blocked_semantics_check": "passed",
        "confirmation_time_backfill_check": "skipped_zero_interval_input_fact",
        "forbidden_column_absence_check": "passed",
        "row_payload_absence_check": "passed",
        "R1-T03_allowed_to_start": "true",
        "R1-T07_allowed_to_start": "false",
        "R2_allowed_to_start": r2_allowed,
    }
    if include_validation_result:
        fields["validation_result_path"] = _display_path(validation_result_path)
        fields["validation_result_sha256"] = sha256_file(validation_result_path)
    _write_evidence(path, fields)
    return path


def _write_evidence(path: Path, fields: dict[str, object]) -> None:
    path.write_text(
        "\n".join(f"`{key}`: {value}" for key, value in fields.items()) + "\n",
        encoding="utf-8",
    )


def _refresh_r1_lock_hashes(paths: dict[str, Path]) -> None:
    r1_config = _load_json(paths["r1_config"])
    lock = r1_config["r0_input_package_lock"]
    lock["authorized_input_manifest_sha256"] = sha256_file(paths["authorized_manifest"])
    lock["full_grid_manifest_sha256"] = sha256_file(paths["full_grid_manifest"])
    _write_json(paths["r1_config"], r1_config)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


if __name__ == "__main__":
    unittest.main()
