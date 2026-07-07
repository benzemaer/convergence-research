from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.r0.candidate_artifact_engine import (
    LEGACY_V1_FIELD_NAMES,
    build_candidate_configs,
)
from src.r0.main_grid_materialization_runner import (
    BASELINE_CANDIDATE_CONFIG_ID,
    R0T09MaterializationError,
    load_authorized_input,
    run_main_grid_materialization,
    sha256_file,
    should_skip_config,
    validate_r0_t09_payload_coverage,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests/fixtures/r0/r0_t09_smoke"
FULL_GRID_FIXTURE_MANIFEST = FIXTURE_DIR / "full_grid_authorized_input_manifest.json"
BASELINE_FIXTURE_MANIFEST = FIXTURE_DIR / "baseline_authorized_input_manifest.json"
SECURITY_ID = "000001.SZ"
TRADING_DATE = "2026-02-03"
LINEAGE = [
    "synthetic_in_memory_r0_grid_inputs",
    "r0_t04_raw_metric_engine",
    "r0_t05_strict_past_percentile_score",
    "r0_t06_weak_dimension_nested_state",
    "r0_t07_confirmation_streak_interval",
]


def raw_metric(indicator_id: str, value: float) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "indicator_id": indicator_id,
        "raw_value": value,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def indicator_score(
    indicator_id: str, percentile: float, *, window: int = 250
) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "indicator_id": indicator_id,
        "raw_value": percentile,
        "eligible": True,
        "percentile": percentile,
        "score": percentile,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def dimension_score(dimension: str, *, window: int = 250) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "dimension": dimension,
        "score_dimension": 0.82,
        "score_dimension_min": 0.74,
        "eligible_dimension": True,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def nested_state(*, window: int = 250, q: float = 0.20) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "q": q,
        "weak_delta": 0.10,
        "P_raw": True,
        "C_raw": True,
        "T_raw": True,
        "V_raw": True,
        "S_P_raw": True,
        "S_PC_raw": True,
        "S_PCT_raw": True,
        "S_PCVT_raw": True,
        "exclusive_state_layer": "PCVT",
        "eligible_state": True,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def confirmation(
    state_name: str, *, window: int = 250, q: float = 0.20, k: int = 3
) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "q": q,
        "weak_delta": 0.10,
        "confirmation_k": k,
        "state_name": state_name,
        "raw_state": True,
        "raw_streak": 3,
        "raw_streak_start_date": "2026-02-01",
        "confirmed_state": True,
        "confirmation_start_date": "2026-02-01",
        "confirmation_date": TRADING_DATE,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def interval(*, window: int = 250, q: float = 0.20, k: int = 3) -> dict[str, object]:
    return {
        "security_id": SECURITY_ID,
        "percentile_window_W": window,
        "q": q,
        "weak_delta": 0.10,
        "confirmation_k": k,
        "state_name": "S_PCVT",
        "interval_id": f"{SECURITY_ID}|W250|q0.20|d0.10|K3|S_PCVT|2026-02-03|0001",
        "raw_start_date": "2026-02-01",
        "confirmation_date": "2026-02-03",
        "confirmed_start_date": "2026-02-03",
        "interval_end_date": "2026-02-05",
        "last_observed_date": "2026-02-06",
        "duration_raw_days": 5,
        "duration_confirmed_days": 3,
        "is_open_interval": False,
        "termination_reason": "raw_state_false",
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def synthetic_payload() -> dict[str, object]:
    return {
        "raw_metric_results": [
            raw_metric("P1_NATR14", 0.11),
            raw_metric("P2_LogRange20", 0.12),
            raw_metric("C1_LogMASpread_5_60", 0.13),
            raw_metric("C2_AdjVWAPSpread_5_60", 0.14),
            raw_metric("T1_ER20", 0.15),
            raw_metric("T2_AbsTrendT20", 0.16),
            raw_metric("V1_TurnoverShrink20_60", 0.17),
            raw_metric("V2_LogAmount20_base", 0.18),
        ],
        "indicator_score_results": [
            indicator_score("P1_NATR14", 0.71),
            indicator_score("P2_LogRange20", 0.72),
            indicator_score("C1_LogMASpread_5_60", 0.73),
            indicator_score("C2_AdjVWAPSpread_5_60", 0.74),
            indicator_score("T1_ER20", 0.75),
            indicator_score("T2_AbsTrendT20", 0.76),
            indicator_score("V1_TurnoverShrink20_60", 0.77),
            indicator_score("V2_AmountLevel20Pct", 0.21),
        ],
        "dimension_score_results": [
            dimension_score(dimension) for dimension in ("P", "C", "T", "V")
        ],
        "nested_daily_state_results": [nested_state()],
        "daily_confirmation_results": [
            confirmation(state_name)
            for state_name in ("S_P", "S_PC", "S_PCT", "S_PCVT")
        ],
        "confirmed_interval_results": [interval()],
    }


def full_grid_payload() -> dict[str, object]:
    windows = (120, 250, 500)
    quantiles = (0.10, 0.20, 0.30)
    confirmation_ks = (2, 3, 5)
    state_names = ("S_P", "S_PC", "S_PCT", "S_PCVT")
    payload = synthetic_payload()
    payload["indicator_score_results"] = [
        indicator_score(indicator_id, percentile, window=window)
        for window in windows
        for indicator_id, percentile in (
            ("P1_NATR14", 0.71),
            ("P2_LogRange20", 0.72),
            ("C1_LogMASpread_5_60", 0.73),
            ("C2_AdjVWAPSpread_5_60", 0.74),
            ("T1_ER20", 0.75),
            ("T2_AbsTrendT20", 0.76),
            ("V1_TurnoverShrink20_60", 0.77),
            ("V2_AmountLevel20Pct", 0.21),
        )
    ]
    payload["dimension_score_results"] = [
        dimension_score(dimension, window=window)
        for window in windows
        for dimension in ("P", "C", "T", "V")
    ]
    payload["nested_daily_state_results"] = [
        nested_state(window=window, q=q) for window in windows for q in quantiles
    ]
    payload["daily_confirmation_results"] = [
        confirmation(state_name, window=window, q=q, k=k)
        for window in windows
        for q in quantiles
        for k in confirmation_ks
        for state_name in state_names
    ]
    payload["confirmed_interval_results"] = [
        interval(window=120, q=0.10, k=2),
        interval(window=250, q=0.20, k=3),
        interval(window=500, q=0.30, k=5),
    ]
    return payload


def write_authorized_input(
    directory: Path, payload: dict[str, object] | None = None
) -> Path:
    payload = payload or synthetic_payload()
    payload_path = directory / "payload.json"
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "input_data_version": "synthetic-r0-t09-v1",
        "input_schema_version": "r0_t09_synthetic_upstream_payload.v1",
        "input_content_hash": sha256_file(payload_path),
        "input_row_counts": {
            "raw_metric_results": len(payload.get("raw_metric_results", ())),
            "indicator_score_results": len(payload.get("indicator_score_results", ())),
            "dimension_score_results": len(payload.get("dimension_score_results", ())),
            "nested_daily_state_results": len(
                payload.get("nested_daily_state_results", ())
            ),
            "daily_confirmation_results": len(
                payload.get("daily_confirmation_results", ())
            ),
            "confirmed_interval_results": len(
                payload.get("confirmed_interval_results", ())
            ),
        },
        "source_lineage": LINEAGE,
        "authorized_r0_input": True,
        "code_commit_or_data_build_id": "synthetic-commit",
        "input_payload_path": "payload.json",
    }
    manifest_path = directory / "authorized_input_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path


def read_csv_gz_rows(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def baseline_artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "done": output_dir / "status" / f"{BASELINE_CANDIDATE_CONFIG_ID}.DONE.json",
        "failed": output_dir / "status" / f"{BASELINE_CANDIDATE_CONFIG_ID}.FAILED.json",
        "daily_csv": output_dir
        / "daily_states"
        / f"{BASELINE_CANDIDATE_CONFIG_ID}.daily_states.csv.gz",
        "daily_duckdb": output_dir
        / "daily_states"
        / f"{BASELINE_CANDIDATE_CONFIG_ID}.daily_states.duckdb",
        "interval_csv": output_dir
        / "confirmed_intervals"
        / f"{BASELINE_CANDIDATE_CONFIG_ID}.confirmed_intervals.csv.gz",
        "interval_duckdb": output_dir
        / "confirmed_intervals"
        / f"{BASELINE_CANDIDATE_CONFIG_ID}.confirmed_intervals.duckdb",
        "manifest": output_dir / "manifest.json",
        "audit_report": output_dir / "audit_report.md",
        "r1_handoff": output_dir / "r1_handoff.md",
    }


class R0T09MainGridRunnerTest(unittest.TestCase):
    def test_fixture_full_grid_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_main_grid_materialization(
                input_manifest=FULL_GRID_FIXTURE_MANIFEST,
                output_dir=Path(tmp) / "dry_run_out",
                max_workers=6,
                dry_run=True,
                run_id="R0-T09-FIXTURE-DRY-RUN",
                code_commit="fixture-commit",
            )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["candidate_config_count"], 27)
        self.assertEqual(result["selected_config_count"], 27)
        self.assertEqual(result["run_scope"], "full_grid")
        self.assertFalse(result["artifacts_written"])
        self.assertIn(BASELINE_CANDIDATE_CONFIG_ID, result["tasks"])
        self.assertFalse(any("_K1_" in config_id for config_id in result["tasks"]))
        self.assertEqual(
            result["input_payload_coverage_guard"]["validity_status"], "valid"
        )

    def test_fixture_baseline_materialization_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "baseline_out"
            result = run_main_grid_materialization(
                input_manifest=BASELINE_FIXTURE_MANIFEST,
                output_dir=output_dir,
                max_workers=1,
                only_config=BASELINE_CANDIDATE_CONFIG_ID,
                resume=True,
                run_id="R0-T09-FIXTURE-BASELINE",
                code_commit="fixture-commit",
            )
            paths = baseline_artifact_paths(output_dir)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["run_scope"], "single_config")
            self.assertEqual(result["selected_config_count"], 1)
            self.assertEqual(result["completed_config_count"], 1)
            self.assertEqual(result["failed_config_count"], 0)
            self.assertEqual(result["pending_config_count"], 0)
            self.assertEqual(
                result["baseline_candidate_config_id"], BASELINE_CANDIDATE_CONFIG_ID
            )
            self.assertTrue(paths["done"].is_file())
            self.assertFalse(paths["failed"].exists())
            self.assertTrue(paths["daily_duckdb"].is_file())
            self.assertTrue(paths["daily_csv"].is_file())
            self.assertTrue(paths["interval_duckdb"].is_file())
            self.assertTrue(paths["interval_csv"].is_file())
            self.assertTrue(paths["manifest"].is_file())
            self.assertFalse(paths["audit_report"].exists())
            self.assertFalse(paths["r1_handoff"].exists())

            row = read_csv_gz_rows(paths["daily_csv"])[0]
            self.assertIn("TurnoverShrink20_60_raw", row)
            self.assertIn("AmountLevel20Pct", row)
            self.assertNotIn("AmountLevel20Pct_raw", row)
            serialized = json.dumps(result, sort_keys=True)
            serialized += gzip.open(paths["daily_csv"], "rt", encoding="utf-8").read()
            for legacy_name in LEGACY_V1_FIELD_NAMES:
                self.assertNotIn(legacy_name, serialized)

    def test_fixture_baseline_resume_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "baseline_out"
            kwargs = {
                "input_manifest": BASELINE_FIXTURE_MANIFEST,
                "output_dir": output_dir,
                "max_workers": 1,
                "only_config": BASELINE_CANDIDATE_CONFIG_ID,
                "resume": True,
                "run_id": "R0-T09-FIXTURE-BASELINE",
                "code_commit": "fixture-commit",
            }
            run_main_grid_materialization(**kwargs)
            resumed = run_main_grid_materialization(**kwargs)

        self.assertEqual(resumed["skipped_config_count"], 1)
        self.assertEqual(
            resumed["per_config_status"][BASELINE_CANDIDATE_CONFIG_ID]["status"],
            "skipped",
        )

    def test_dry_run_expands_grid_and_excludes_k1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = write_authorized_input(Path(tmp), full_grid_payload())
            result = run_main_grid_materialization(
                input_manifest=manifest_path,
                output_dir=Path(tmp) / "out",
                dry_run=True,
            )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["candidate_config_count"], 27)
        self.assertEqual(result["selected_config_count"], 27)
        self.assertEqual(result["run_scope"], "full_grid")
        self.assertFalse(result["artifacts_written"])
        self.assertIn(BASELINE_CANDIDATE_CONFIG_ID, result["tasks"])
        self.assertFalse(any("_K1_" in config_id for config_id in result["tasks"]))
        self.assertEqual(result["max_workers"], 6)

    def test_rejects_more_than_six_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = write_authorized_input(Path(tmp))
            with self.assertRaises(R0T09MaterializationError):
                run_main_grid_materialization(
                    input_manifest=manifest_path,
                    output_dir=Path(tmp) / "out",
                    max_workers=7,
                )

    def test_materializes_single_config_outputs_done_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root, full_grid_payload())
            output_dir = root / "out"
            result = run_main_grid_materialization(
                input_manifest=manifest_path,
                output_dir=output_dir,
                max_workers=1,
                only_config=BASELINE_CANDIDATE_CONFIG_ID,
                run_id="R0-T09-TEST",
                code_commit="abcdef",
            )

            done_path = (
                output_dir / "status" / f"{BASELINE_CANDIDATE_CONFIG_ID}.DONE.json"
            )
            failed_path = (
                output_dir / "status" / f"{BASELINE_CANDIDATE_CONFIG_ID}.FAILED.json"
            )
            daily_csv = (
                output_dir
                / "daily_states"
                / f"{BASELINE_CANDIDATE_CONFIG_ID}.daily_states.csv.gz"
            )
            interval_csv = (
                output_dir
                / "confirmed_intervals"
                / f"{BASELINE_CANDIDATE_CONFIG_ID}.confirmed_intervals.csv.gz"
            )
            daily_duckdb = daily_csv.with_suffix("").with_suffix(".duckdb")
            interval_duckdb = interval_csv.with_suffix("").with_suffix(".duckdb")

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["candidate_config_count"], 27)
            self.assertEqual(result["completed_config_count"], 1)
            self.assertEqual(result["pending_config_count"], 0)
            self.assertEqual(
                result["baseline_candidate_config_id"], BASELINE_CANDIDATE_CONFIG_ID
            )
            self.assertEqual(result["run_scope"], "single_config")
            self.assertEqual(result["selected_config_count"], 1)
            self.assertEqual(
                result["selected_config_ids"], [BASELINE_CANDIDATE_CONFIG_ID]
            )
            self.assertTrue(done_path.is_file())
            self.assertFalse(failed_path.exists())
            self.assertTrue(daily_csv.is_file())
            self.assertTrue(interval_csv.is_file())
            self.assertTrue(daily_duckdb.is_file())
            self.assertTrue(interval_duckdb.is_file())
            self.assertFalse((output_dir / "audit_report.md").exists())
            self.assertFalse((output_dir / "r1_handoff.md").exists())

            done = json.loads(done_path.read_text(encoding="utf-8"))
            self.assertEqual(done["status"], "completed")
            self.assertEqual(done["daily_content_hash"], sha256_file(daily_csv))
            self.assertEqual(done["interval_content_hash"], sha256_file(interval_csv))
            self.assertEqual(done["daily_duckdb_hash"], sha256_file(daily_duckdb))
            self.assertEqual(done["daily_csv_hash"], sha256_file(daily_csv))
            self.assertEqual(done["interval_duckdb_hash"], sha256_file(interval_duckdb))
            self.assertEqual(done["interval_csv_hash"], sha256_file(interval_csv))
            self.assertEqual(done["daily_row_count"], 1)
            self.assertEqual(done["interval_row_count"], 1)

            daily_rows = read_csv_gz_rows(daily_csv)
            self.assertEqual(daily_rows[0]["TurnoverShrink20_60_raw"], "0.17")
            self.assertEqual(daily_rows[0]["AmountLevel20Pct"], "0.21")
            self.assertNotIn("AmountLevel20Pct_raw", daily_rows[0])
            serialized = json.dumps(result, sort_keys=True)
            serialized += gzip.open(daily_csv, "rt", encoding="utf-8").read()
            for legacy_name in LEGACY_V1_FIELD_NAMES:
                self.assertNotIn(legacy_name, serialized)

    def test_resume_requires_all_artifact_hashes_and_rejects_partials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root)
            output_dir = root / "out"
            first = run_main_grid_materialization(
                input_manifest=manifest_path,
                output_dir=output_dir,
                max_workers=1,
                only_config=BASELINE_CANDIDATE_CONFIG_ID,
                run_id="R0-T09-TEST",
            )
            self.assertEqual(first["completed_config_count"], 1)

            resumed = run_main_grid_materialization(
                input_manifest=manifest_path,
                output_dir=output_dir,
                max_workers=1,
                only_config=BASELINE_CANDIDATE_CONFIG_ID,
                resume=True,
                run_id="R0-T09-TEST",
            )
            self.assertEqual(resumed["skipped_config_count"], 1)
            self.assertEqual(
                resumed["per_config_status"][BASELINE_CANDIDATE_CONFIG_ID]["status"],
                "skipped",
            )

            config = next(
                item.as_dict()
                for item in build_candidate_configs()
                if item.candidate_config_id == BASELINE_CANDIDATE_CONFIG_ID
            )
            authorized = load_authorized_input(manifest_path)
            self.assertTrue(
                should_skip_config(
                    config=config,
                    output_dir=output_dir,
                    input_manifest_hash=authorized.manifest_hash,
                )
            )
            partial = (
                output_dir
                / "daily_states"
                / f"{BASELINE_CANDIDATE_CONFIG_ID}.daily_states.partial.duckdb"
            )
            partial.write_text("incomplete", encoding="utf-8")
            self.assertFalse(
                should_skip_config(
                    config=config,
                    output_dir=output_dir,
                    input_manifest_hash=authorized.manifest_hash,
                )
            )

        mutations = (
            "corrupt_daily_duckdb",
            "remove_daily_duckdb_hash",
            "delete_daily_duckdb",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path = write_authorized_input(root)
                output_dir = root / "out"
                run_main_grid_materialization(
                    input_manifest=manifest_path,
                    output_dir=output_dir,
                    max_workers=1,
                    only_config=BASELINE_CANDIDATE_CONFIG_ID,
                    run_id="R0-T09-TEST",
                )
                config = next(
                    item.as_dict()
                    for item in build_candidate_configs()
                    if item.candidate_config_id == BASELINE_CANDIDATE_CONFIG_ID
                )
                authorized = load_authorized_input(manifest_path)
                daily_duckdb = (
                    output_dir
                    / "daily_states"
                    / f"{BASELINE_CANDIDATE_CONFIG_ID}.daily_states.duckdb"
                )
                done_path = (
                    output_dir / "status" / f"{BASELINE_CANDIDATE_CONFIG_ID}.DONE.json"
                )
                if mutation == "corrupt_daily_duckdb":
                    with daily_duckdb.open("ab") as handle:
                        handle.write(b"corrupt")
                elif mutation == "remove_daily_duckdb_hash":
                    done = json.loads(done_path.read_text(encoding="utf-8"))
                    del done["daily_duckdb_hash"]
                    done_path.write_text(json.dumps(done), encoding="utf-8")
                elif mutation == "delete_daily_duckdb":
                    daily_duckdb.unlink()

                self.assertFalse(
                    should_skip_config(
                        config=config,
                        output_dir=output_dir,
                        input_manifest_hash=authorized.manifest_hash,
                    )
                )

    def test_full_grid_smoke_materializes_all_configs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root, full_grid_payload())
            output_dir = root / "out"
            result = run_main_grid_materialization(
                input_manifest=manifest_path,
                output_dir=output_dir,
                max_workers=2,
                run_id="R0-T09-FULL-GRID-TEST",
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["run_scope"], "full_grid")
            self.assertEqual(result["candidate_config_count"], 27)
            self.assertEqual(result["selected_config_count"], 27)
            self.assertEqual(result["completed_config_count"], 27)
            self.assertEqual(result["failed_config_count"], 0)
            self.assertEqual(result["pending_config_count"], 0)
            self.assertFalse((output_dir / "audit_report.md").exists())
            self.assertFalse((output_dir / "r1_handoff.md").exists())

            serialized_manifest = json.dumps(result, sort_keys=True)
            self.assertNotIn("_K1_", serialized_manifest)
            for legacy_name in LEGACY_V1_FIELD_NAMES:
                self.assertNotIn(legacy_name, serialized_manifest)

            for config in build_candidate_configs():
                config_id = config.candidate_config_id
                done_path = output_dir / "status" / f"{config_id}.DONE.json"
                daily_csv = (
                    output_dir / "daily_states" / f"{config_id}.daily_states.csv.gz"
                )
                daily_duckdb = (
                    output_dir / "daily_states" / f"{config_id}.daily_states.duckdb"
                )
                interval_csv = (
                    output_dir
                    / "confirmed_intervals"
                    / f"{config_id}.confirmed_intervals.csv.gz"
                )
                interval_duckdb = (
                    output_dir
                    / "confirmed_intervals"
                    / f"{config_id}.confirmed_intervals.duckdb"
                )
                self.assertTrue(done_path.is_file(), config_id)
                self.assertTrue(daily_csv.is_file(), config_id)
                self.assertTrue(daily_duckdb.is_file(), config_id)
                self.assertTrue(interval_csv.is_file(), config_id)
                self.assertTrue(interval_duckdb.is_file(), config_id)

            baseline_csv = (
                output_dir
                / "daily_states"
                / f"{BASELINE_CANDIDATE_CONFIG_ID}.daily_states.csv.gz"
            )
            self.assertIn("TurnoverShrink20_60_raw", read_csv_gz_rows(baseline_csv)[0])

    def test_full_grid_payload_coverage_guard_blocks_incomplete_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root)
            output_dir = root / "out"
            with self.assertRaisesRegex(
                R0T09MaterializationError,
                "input_payload_grid_coverage_incomplete",
            ):
                run_main_grid_materialization(
                    input_manifest=manifest_path,
                    output_dir=output_dir,
                    max_workers=1,
                )
            self.assertFalse(output_dir.exists())

        guard = validate_r0_t09_payload_coverage(
            synthetic_payload(),
            [config.as_dict() for config in build_candidate_configs()],
        )
        self.assertEqual(guard["validity_status"], "blocked")
        self.assertIn("input_payload_grid_coverage_incomplete", guard["reason_codes"])

    def test_payload_coverage_guard_blocks_grid_outside_confirmation_k1(self) -> None:
        payload = full_grid_payload()
        payload["daily_confirmation_results"].append(confirmation("S_PCVT", k=1))
        selected = [config.as_dict() for config in build_candidate_configs()]
        guard = validate_r0_t09_payload_coverage(payload, selected)
        self.assertEqual(guard["validity_status"], "blocked")
        self.assertIn("input_payload_grid_coverage_incomplete", guard["reason_codes"])

    def test_failed_config_writes_failed_marker_without_done(self) -> None:
        bad_payload = synthetic_payload()
        bad_payload["raw_metric_results"] = ["bad"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root, bad_payload)
            output_dir = root / "out"
            result = run_main_grid_materialization(
                input_manifest=manifest_path,
                output_dir=output_dir,
                max_workers=1,
                only_config=BASELINE_CANDIDATE_CONFIG_ID,
                run_id="R0-T09-TEST",
            )

            failed_path = (
                output_dir / "status" / f"{BASELINE_CANDIDATE_CONFIG_ID}.FAILED.json"
            )
            done_path = (
                output_dir / "status" / f"{BASELINE_CANDIDATE_CONFIG_ID}.DONE.json"
            )
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual(result["failed_config_count"], 1)
            self.assertTrue(failed_path.is_file())
            self.assertFalse(done_path.exists())
            failed = json.loads(failed_path.read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "failed")
            self.assertIn("retry_command", failed)

    def test_input_manifest_gate_blocks_hash_mismatch_and_forbidden_lineage(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["input_content_hash"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(R0T09MaterializationError, "hash mismatch"):
                load_authorized_input(manifest_path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_lineage"] = ["data/raw/vendor.csv"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(R0T09MaterializationError, "lineage"):
                load_authorized_input(manifest_path)

    def test_cli_smoke_dry_run_and_worker_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = write_authorized_input(root, full_grid_payload())
            command = [
                sys.executable,
                "scripts/r0/run_r0_t09_main_grid.py",
                "--input-manifest",
                str(manifest_path),
                "--output-dir",
                str(root / "out"),
                "--dry-run",
            ]
            ok = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)["status"], "dry_run")

            blocked = subprocess.run(
                [*command, "--max-workers", "7"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("max_workers", blocked.stderr)


if __name__ == "__main__":
    unittest.main()
