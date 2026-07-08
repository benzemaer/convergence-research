from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r1.r1_t03_27_grid_light_profile import (
    run_r1_t03_27_grid_light_profile,
    sha256_file,
)
from src.r1.r1_t03_27_grid_light_profile_validator import (
    R1T03LightProfileValidationError,
    validate_r1_t03_27_grid_light_profile,
)

FULL_SHA = "2222222222222222222222222222222222222222"
R1_T02_EVIDENCE_PATH = "docs/evidence/r1/R1-T02_r0_lineage_pit_audit_evidence.md"
FIXTURE_SUMMARY_PATH = (
    "data/generated/r1/r1_t03/R1-T03-fixture/r1_t03_27_grid_light_profile_summary.json"
)


class R1T03LightProfileContractTest(unittest.TestCase):
    def test_complete_synthetic_27_config_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture(root, fixture)
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["profile_row_count"], 108)
            evidence = _write_evidence(root, summary)
            result = validate_r1_t03_27_grid_light_profile(
                root / summary["summary_path"],
                evidence,
                root=root,
            )
            self.assertEqual(result["validator_status"], "passed")

    def test_missing_r1_t02_evidence_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            fixture["r1_t02_evidence"].unlink()
            summary = _run_fixture(root, fixture)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["checks"]["r1_t02_gate"], "blocked")

    def test_r1_t02_validator_status_not_passed_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            evidence = _parse_evidence(fixture["r1_t02_evidence"])
            evidence["validator_status"] = "failed"
            _write_evidence_fields(fixture["r1_t02_evidence"], evidence)
            summary = _run_fixture(root, fixture)
            self.assertEqual(summary["status"], "blocked")

    def test_r1_t03_allowed_false_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            evidence = _parse_evidence(fixture["r1_t02_evidence"])
            evidence["R1-T03_allowed_to_start"] = "false"
            _write_evidence_fields(fixture["r1_t02_evidence"], evidence)
            summary = _run_fixture(root, fixture)
            self.assertEqual(summary["status"], "blocked")

    def test_max_workers_gt_3_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture(root, fixture, max_workers=4)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["checks"]["parallelism_contract"], "blocked")

    def test_duckdb_threads_gt_1_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            config = _load_json(fixture["config"])
            config["parallelism"]["duckdb_threads_per_worker"] = 2
            _write_json(fixture["config"], config)
            summary = _run_fixture(root, fixture)
            self.assertEqual(summary["status"], "blocked")

    def test_grid_mismatch_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            config = _load_json(fixture["config"])
            config["grid"]["K"] = [1, 2, 3]
            _write_json(fixture["config"], config)
            summary = _run_fixture(root, fixture)
            self.assertEqual(summary["status"], "blocked")

    def test_missing_baseline_config_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            manifest = _load_json(fixture["full_grid_manifest"])
            manifest["baseline_config_id"] = "missing"
            _write_json(fixture["full_grid_manifest"], manifest)
            _refresh_hashes(root, fixture)
            summary = _run_fixture(root, fixture)
            self.assertEqual(summary["status"], "blocked")

    def test_missing_s_pct_or_s_pcvt_blocks_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture(root, fixture)
            profile_path = (
                root / summary["output_paths"]["profile_by_config_state_json"]["path"]
            )
            rows = [
                row for row in _load_json(profile_path) if row["state_name"] != "S_PCVT"
            ]
            _write_json(profile_path, rows)
            summary["output_paths"]["profile_by_config_state_json"]["sha256"] = (
                sha256_file(profile_path)
            )
            _write_json(root / summary["summary_path"], summary)
            evidence = _write_evidence(root, summary)
            with self.assertRaises(R1T03LightProfileValidationError):
                validate_r1_t03_27_grid_light_profile(
                    root / summary["summary_path"], evidence, root=root
                )

    def test_future_return_column_blocks_validator(self) -> None:
        self._forbidden_profile_column_blocks("future_return")

    def test_jointlift_column_blocks_validator(self) -> None:
        self._forbidden_profile_column_blocks("JointLift")

    def test_best_config_field_blocks_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture(root, fixture)
            relative_path = (
                root / summary["output_paths"]["relative_to_baseline_profile"]["path"]
            )
            relative = _load_json(relative_path)
            relative[0]["best_config"] = True
            _write_json(relative_path, relative)
            summary["output_paths"]["relative_to_baseline_profile"]["sha256"] = (
                sha256_file(relative_path)
            )
            _write_json(root / summary["summary_path"], summary)
            evidence = _write_evidence(root, summary)
            with self.assertRaises(R1T03LightProfileValidationError):
                validate_r1_t03_27_grid_light_profile(
                    root / summary["summary_path"], evidence, root=root
                )

    def test_denominator_zero_retention_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root, all_raw_false=True)
            summary = _run_fixture(root, fixture)
            retention = _load_json(
                root / summary["output_paths"]["retention_profile"]["path"]
            )
            self.assertTrue(retention[0]["C_given_P_raw_denominator_zero"])
            self.assertIsNone(retention[0]["C_given_P_raw"])

    def test_zero_confirmed_interval_marked_input_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture(root, fixture)
            profile = _load_json(
                root / summary["output_paths"]["profile_by_config_state_json"]["path"]
            )
            self.assertEqual(
                profile[0]["confirmed_interval_status"], "zero_confirmed_input_fact"
            )

    def test_relative_ratio_null_when_baseline_denominator_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root, all_raw_false=True)
            summary = _run_fixture(root, fixture)
            relative = _load_json(
                root / summary["output_paths"]["relative_to_baseline_profile"]["path"]
            )
            self.assertIsNone(relative[0]["raw_coverage_ratio_to_baseline"])

    def test_wrappers_are_thin_and_pr_fast_includes_r1_t03(self) -> None:
        wrapper = Path("scripts/r1/run_r1_t03_27_grid_light_profile.py").read_text(
            encoding="utf-8"
        )
        validator = Path(
            "scripts/r1/validate_r1_t03_27_grid_light_profile.py"
        ).read_text(encoding="utf-8")
        profile = Path("configs/ci/unittest_profiles.v1.json").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "from src.r1.r1_t03_27_grid_light_profile_cli import main", wrapper
        )
        self.assertIn(
            "from src.r1.r1_t03_27_grid_light_profile_validator_cli import main",
            validator,
        )
        self.assertNotIn("duckdb", wrapper.lower())
        self.assertIn("tests/r1/test_r1_t03_27_grid_light_profile_contract.py", profile)

    def _forbidden_profile_column_blocks(self, column: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = _write_fixture(root)
            summary = _run_fixture(root, fixture)
            csv_path = (
                root / summary["output_paths"]["profile_by_config_state_csv"]["path"]
            )
            text = csv_path.read_text(encoding="utf-8")
            lines = text.splitlines()
            lines[0] += f",{column}"
            lines[1:] = [line + ",1" for line in lines[1:]]
            csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            summary["output_paths"]["profile_by_config_state_csv"]["sha256"] = (
                sha256_file(csv_path)
            )
            _write_json(root / summary["summary_path"], summary)
            evidence = _write_evidence(root, summary)
            with self.assertRaises(R1T03LightProfileValidationError):
                validate_r1_t03_27_grid_light_profile(
                    root / summary["summary_path"], evidence, root=root
                )


def _run_fixture(
    root: Path, fixture: dict[str, Path], max_workers: int = 1
) -> dict[str, object]:
    return run_r1_t03_27_grid_light_profile(
        config_path=fixture["config"],
        r1_t02_evidence_path=fixture["r1_t02_evidence"],
        r1_t02_summary_path=fixture["r1_t02_summary"],
        output_dir=root / "data/generated/r1/r1_t03/R1-T03-fixture",
        run_id="R1-T03-fixture",
        code_commit=FULL_SHA,
        max_workers=max_workers,
        root=root,
    )


def _write_fixture(root: Path, all_raw_false: bool = False) -> dict[str, Path]:
    paths = {
        "config": root / "configs/r1/r1_t03_27_grid_light_profile.v1.json",
        "r1_t02_evidence": root
        / "docs/evidence/r1/R1-T02_r0_lineage_pit_audit_evidence.md",
        "r1_t02_summary": root / "data/generated/r1/r1_t02/summary.json",
        "r1_t02_validation": root / "data/generated/r1/r1_t02/validation.json",
        "full_grid_manifest": root / "data/generated/r0/full_grid_manifest.json",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _full_grid_manifest(root, all_raw_false)
    _write_json(paths["full_grid_manifest"], manifest)
    config = _config(
        _rel(root, paths["full_grid_manifest"]),
        sha256_file(paths["full_grid_manifest"]),
    )
    _write_json(paths["config"], config)
    summary = {
        "task_id": "R1-T02",
        "status": "completed",
        "full_grid_manifest_path": _rel(root, paths["full_grid_manifest"]),
        "full_grid_manifest_sha256": sha256_file(paths["full_grid_manifest"]),
        "counts": {"confirmed_interval_row_count_total": 0},
    }
    _write_json(paths["r1_t02_summary"], summary)
    _write_json(
        paths["r1_t02_validation"], {"task_id": "R1-T02", "validator_status": "passed"}
    )
    _write_evidence_fields(
        paths["r1_t02_evidence"],
        {
            "task_id": "R1-T02",
            "status": "completed",
            "validator_status": "passed",
            "summary_path": _rel(root, paths["r1_t02_summary"]),
            "summary_sha256": sha256_file(paths["r1_t02_summary"]),
            "validation_result_path": _rel(root, paths["r1_t02_validation"]),
            "validation_result_sha256": sha256_file(paths["r1_t02_validation"]),
            "R1-T03_allowed_to_start": "true",
            "R1-T07_allowed_to_start": "false",
            "R2_allowed_to_start": "false",
        },
    )
    return paths


def _full_grid_manifest(root: Path, all_raw_false: bool) -> dict[str, object]:
    candidates = []
    artifacts = {}
    for w in (120, 250, 500):
        for q_label, q in (("10", 0.1), ("20", 0.2), ("30", 0.3)):
            for k in (2, 3, 5):
                config_id = f"R0_W{w}_Q{q_label}_K{k}_WEAK_D010"
                candidates.append(
                    {
                        "candidate_config_id": config_id,
                        "percentile_window_W": w,
                        "low_quantile_q": q,
                        "confirmation_days_K": k,
                        "weak_delta": 0.1,
                        "dimension_rule": "weak",
                    }
                )
                artifacts[config_id] = _write_config_artifacts(
                    root, config_id, w, q, k, all_raw_false
                )
    return {
        "manifest_type": "r0_t10_05_full_grid_manifest",
        "status": "completed",
        "row_payload_embedded": False,
        "selected_config_count": 27,
        "completed_config_count": 27,
        "failed_config_count": 0,
        "baseline_config_id": "R0_W250_Q20_K3_WEAK_D010",
        "candidate_configs": candidates,
        "selected_config_ids": [item["candidate_config_id"] for item in candidates],
        "artifacts_by_config": artifacts,
    }


def _write_config_artifacts(
    root: Path, config_id: str, w: int, q: float, k: int, all_raw_false: bool
) -> dict[str, str]:
    base = root / "data/generated/r0/configs" / config_id
    base.mkdir(parents=True, exist_ok=True)
    daily = base / "candidate_daily_state.parquet"
    interval = base / "candidate_confirmed_interval.parquet"
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE daily(
          security_id VARCHAR,
          trading_date VARCHAR,
          candidate_config_id VARCHAR,
          percentile_window_W INTEGER,
          low_quantile_q DOUBLE,
          confirmation_days_K INTEGER,
          state_name VARCHAR,
          raw_state BOOLEAN,
          confirmed_state BOOLEAN,
          validity_status VARCHAR
        )
        """
    )
    for security in ("A", "B"):
        for date in ("20200101", "20200102", "20210101", "20210102"):
            for state in ("S_P", "S_PC", "S_PCT", "S_PCVT"):
                raw = False if all_raw_false else state in ("S_P", "S_PC", "S_PCT")
                con.execute(
                    "INSERT INTO daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [security, date, config_id, w, q, k, state, raw, False, "valid"],
                )
    con.execute(f"COPY daily TO '{str(daily).replace(chr(92), '/')}' (FORMAT PARQUET)")
    con.execute(
        """
        CREATE TABLE interval(
          security_id VARCHAR,
          state_level VARCHAR,
          candidate_config_id VARCHAR,
          confirmed_length INTEGER,
          confirmation_time VARCHAR
        )
        """
    )
    con.execute(
        f"COPY interval TO '{str(interval).replace(chr(92), '/')}' (FORMAT PARQUET)"
    )
    con.close()
    return {
        "daily_parquet_path": _rel(root, daily),
        "daily_parquet_sha256": sha256_file(daily),
        "interval_parquet_path": _rel(root, interval),
        "interval_parquet_sha256": sha256_file(interval),
    }


def _config(manifest_path: str, manifest_sha: str) -> dict[str, object]:
    return {
        "task_id": "R1-T03",
        "stage": "R1",
        "protocol_version": "r1_t03_27_grid_light_profile.v1",
        "depends_on_task": "R1-T02",
        "r1_t02_evidence_path": R1_T02_EVIDENCE_PATH,
        "r1_t02_summary_path": "data/generated/r1/r1_t02/summary.json",
        "r1_t02_validation_result_path": "data/generated/r1/r1_t02/validation.json",
        "r0_full_grid_manifest_path": manifest_path,
        "r0_full_grid_manifest_sha256": manifest_sha,
        "grid": {
            "W": [120, 250, 500],
            "q": [0.1, 0.2, 0.3],
            "K": [2, 3, 5],
            "config_count": 27,
            "weak_delta": 0.1,
            "dimension_rule": "weak",
        },
        "state_names": ["S_P", "S_PC", "S_PCT", "S_PCVT"],
        "baseline_config_id": "R0_W250_Q20_K3_WEAK_D010",
        "parallelism": {"max_workers": 3, "duckdb_threads_per_worker": 1},
    }


def _write_evidence(root: Path, summary: dict[str, object]) -> Path:
    path = root / "docs/evidence/r1/R1-T03_27_grid_light_profile_evidence.md"
    validation_path = root / "data/generated/r1/r1_t03/R1-T03-fixture/validation.json"
    _write_json(
        validation_path,
        {"task_id": "R1-T03", "validator_status": "passed", "errors": []},
    )
    fields = {
        "task_id": "R1-T03",
        "status": "completed",
        "run_id": summary["run_id"],
        "code_commit": FULL_SHA,
        "profile_summary_path": summary["input_full_grid_manifest_path"].replace(
            "data/generated/r0/full_grid_manifest.json",
            "data/generated/r1/r1_t03/R1-T03-fixture/r1_t03_27_grid_light_profile_summary.json",
        ),
        "profile_summary_sha256": sha256_file(root / FIXTURE_SUMMARY_PATH),
        "validation_result_path": _rel(root, validation_path),
        "validation_result_sha256": sha256_file(validation_path),
        "validator_status": "passed",
        "no_zero_model_check": "passed",
        "no_parameter_selection_check": "passed",
        "row_payload_absence_check": "passed",
        "R1-T04_allowed_to_start": "true",
        "R1-T07_allowed_to_start": "false",
        "R2_allowed_to_start": "false",
    }
    _write_evidence_fields(path, fields)
    return path


def _parse_evidence(path: Path) -> dict[str, str]:
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key_end = line.find("`:")
        if line.startswith("`") and key_end >= 0:
            fields[line[1:key_end]] = line[key_end + 2 :].strip().replace("`", "")
    return fields


def _write_evidence_fields(path: Path, fields: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"`{key}`: {value}" for key, value in fields.items()) + "\n",
        encoding="utf-8",
    )


def _refresh_hashes(root: Path, fixture: dict[str, Path]) -> None:
    config = _load_json(fixture["config"])
    config["r0_full_grid_manifest_sha256"] = sha256_file(fixture["full_grid_manifest"])
    _write_json(fixture["config"], config)
    summary = _load_json(fixture["r1_t02_summary"])
    summary["full_grid_manifest_sha256"] = sha256_file(fixture["full_grid_manifest"])
    _write_json(fixture["r1_t02_summary"], summary)
    evidence = _parse_evidence(fixture["r1_t02_evidence"])
    evidence["summary_sha256"] = sha256_file(fixture["r1_t02_summary"])
    _write_evidence_fields(fixture["r1_t02_evidence"], evidence)


def _load_json(path: Path) -> dict[str, object] | list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


if __name__ == "__main__":
    unittest.main()
