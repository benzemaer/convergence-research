from __future__ import annotations

# Synthetic SQL fixtures intentionally keep the selected columns visible.
# ruff: noqa: E501
import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from argparse import Namespace
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb

from scripts.sidecar.run_exp_a01_price_ma_attachment import (
    FORMAL_SOURCE_PATHS,
    run_formal,
)
from src.sidecar.exp_a01_price_ma_attachment import (
    A1_ID,
    A2_ID,
    INDEX_SOURCE_CONTRACT,
    build_dense_price_rows,
    compute_a01_metrics,
)
from src.sidecar.exp_a01_price_ma_attachment_formal import materialize_raw_metrics
from src.sidecar.exp_a01_price_ma_attachment_validator import (
    load_json,
    validate_formal_result,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


class ExpA01FormalTest(unittest.TestCase):
    def _make_inputs(
        self, root: Path, *, count: int = 120
    ) -> tuple[Path, dict[str, Path]]:
        config = load_json(CONFIG_PATH)
        artifacts = config["input_contract"]["artifacts"]
        candidate_path = (
            root / artifacts["d3_t07_candidate_daily_observation"]["filename"]
        )
        index_path = root / artifacts["expected_price_observation_index"]["filename"]
        base = date(2020, 1, 1)
        placeholder_indices = {2: "listing_pause", 3: "missing", 4: "unresolved"}

        candidate = duckdb.connect(str(candidate_path))
        try:
            candidate.execute(
                """
                CREATE TABLE d3_candidate_daily_observation (
                  ts_code VARCHAR,
                  trade_date TEXT,
                  adjusted_open DOUBLE,
                  adjusted_close DOUBLE,
                  trading_status VARCHAR,
                  daily_status VARCHAR,
                  effective_adj_factor DOUBLE,
                  adjustment_factor_status VARCHAR,
                  is_listing_pause BOOLEAN,
                  source_task_id VARCHAR,
                  generated_by_task VARCHAR,
                  row_provenance VARCHAR
                )
                """
            )
            rows = []
            for index in range(count):
                if index in placeholder_indices:
                    continue
                current_date = base + timedelta(days=index)
                trade_date = (
                    current_date.strftime("%Y-%m-%d")
                    if index % 3 == 0
                    else current_date.strftime("%Y%m%d")
                )
                status = {
                    5: "suspended",
                    6: "reopen_after_suspension",
                    7: "limit_up",
                    8: "limit_down",
                    9: "one_price_limit_up",
                    10: "one_price_limit_down",
                }.get(index, "normal_trading")
                rows.append(
                    (
                        "SEC001",
                        trade_date,
                        100.0 + index * 0.17,
                        100.2 + index * 0.23 + (index % 7) * 0.03,
                        status,
                        "resolved",
                        1.0,
                        "resolved",
                        False,
                        "D2-T20",
                        "D3-T07",
                        f"d3-t07:SEC001:{index}",
                    )
                )
            candidate.executemany(
                "INSERT INTO d3_candidate_daily_observation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        finally:
            candidate.close()

        index = duckdb.connect(str(index_path))
        try:
            index.execute(
                """
                CREATE TABLE expected_price_observation_index (
                  security_id VARCHAR,
                  trading_date DATE,
                  observation_sequence BIGINT,
                  expected_observation_status VARCHAR,
                  source_contract VARCHAR,
                  source_ref VARCHAR
                )
                """
            )
            index.executemany(
                "INSERT INTO expected_price_observation_index VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        "SEC001",
                        base + timedelta(days=position),
                        position,
                        placeholder_indices.get(position, "present"),
                        INDEX_SOURCE_CONTRACT,
                        f"calendar-v1:SEC001:{position}",
                    )
                    for position in range(count)
                ],
            )
        finally:
            index.close()

        reports = {
            "d3_t07_quality_report": root / "d3_t07_quality_report.json",
            "d3_t07_handoff_report": root / "d3_t07_handoff_candidate_report.json",
            "d3_t08_quality_report": root / "d3_t08_quality_report.json",
            "d3_t08_handoff_report": root / "d3_t08_handoff_candidate_report.json",
        }
        _write_json(
            reports["d3_t07_quality_report"],
            {
                "task_id": "D3-T07",
                "source_task_id": "D2-T20",
                "candidate_observation_generated": True,
                "candidate_generation_decision": "accepted_candidate_observation_with_warnings",
                "duplicate_observation_key_count": 0,
                "null_ohlc_count": 0,
                "non_positive_price_count": 0,
                "high_low_violation_count": 0,
                "missing_effective_adj_factor_count": 0,
                "factor_interval_unresolved_count": 0,
            },
        )
        _write_json(
            reports["d3_t07_handoff_report"],
            {
                "task_id": "D3-T07",
                "source_task_id": "D2-T20",
                "d3_t07_generation_decision": "accepted_candidate_observation_with_warnings",
                "d3_candidate_observation_generated": True,
                "formal_data_version_published": False,
                "labels_generated": False,
                "returns_generated": False,
                "pcvt_values_generated": False,
                "r0_state_generated": False,
            },
        )
        t08_quality = {
            "task_id": "D3-T08",
            "source_task_id": "D3-T07",
            "d3_t08_generation_decision": "accepted_research_dataset_registry",
            "research_dataset_registry_generated": True,
            "duplicate_observation_key_count": 0,
            "adjusted_ohlc_invalid_count": 0,
            "effective_adj_factor_invalid_count": 0,
            "adjusted_factor_mismatch_count": 0,
            "listing_pause_row_count": 0,
            "is_listing_pause_true_count": 0,
            "source_task_id_invalid_count": 0,
            "generated_by_task_invalid_count": 0,
            "row_provenance_missing_count": 0,
        }
        _write_json(reports["d3_t08_quality_report"], t08_quality)
        _write_json(
            reports["d3_t08_handoff_report"],
            {
                **t08_quality,
                "formal_data_version_published": False,
                "labels_generated": False,
                "returns_generated": False,
                "pcvt_values_generated": False,
                "r0_state_generated": False,
            },
        )

        paths = {
            "d3_t07_candidate_daily_observation": candidate_path,
            "expected_price_observation_index": index_path,
            **reports,
        }
        declarations: dict[str, dict[str, object]] = {}
        for artifact_id in config["input_contract"]["manifest_artifact_names"]:
            artifact = artifacts[artifact_id]
            path = paths[artifact_id]
            declaration: dict[str, object] = {
                "artifact_id": artifact_id,
                "path": str(path),
                "filename": artifact["filename"],
                "sha256": _sha(path),
                "source_contract": artifact["source_contract"],
                "source_role": artifact["source_role"],
                "formal_data_version": False,
            }
            if artifact["artifact_kind"] == "duckdb_table":
                connection = duckdb.connect(str(path), read_only=True)
                try:
                    row_count = int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {artifact['table']}"
                        ).fetchone()[0]
                    )
                finally:
                    connection.close()
                declaration.update(
                    {
                        "table": artifact["table"],
                        "row_count": row_count,
                        "required_columns": list(artifact["required_columns"]),
                    }
                )
            else:
                declaration["required_json_fields"] = list(
                    artifact["required_json_fields"]
                )
            declarations[artifact_id] = declaration

        manifest_path = root / "authorized_input_manifest.json"
        _write_json(
            manifest_path,
            {
                "manifest_type": "exp_a01_authorized_input_manifest",
                "schema_version": "exp_a01_authorized_input_manifest.v1",
                "task_id": "EXP-A01",
                "authorized_for_task": "EXP-A01",
                "authorized_research_candidate_input": True,
                "formal_data_version": False,
                "authorization": {
                    "authorization_status": "authorized_for_exp_a01",
                    "authorized_by": "synthetic-test",
                    "authorized_at": "2026-07-16T00:00:00Z",
                    "authorization_evidence": "synthetic formal package fixture",
                },
                "input_artifacts": declarations,
                "cross_artifact_bindings": {
                    "d3_t07_candidate_sha256": declarations[
                        "d3_t07_candidate_daily_observation"
                    ]["sha256"],
                    "d3_t07_quality_sha256": declarations["d3_t07_quality_report"][
                        "sha256"
                    ],
                    "d3_t07_handoff_sha256": declarations["d3_t07_handoff_report"][
                        "sha256"
                    ],
                    "d3_t08_quality_sha256": declarations["d3_t08_quality_report"][
                        "sha256"
                    ],
                    "d3_t08_handoff_sha256": declarations["d3_t08_handoff_report"][
                        "sha256"
                    ],
                    "expected_index_sha256": declarations[
                        "expected_price_observation_index"
                    ]["sha256"],
                },
                "d3_t08_source_binding": {
                    "source_task_id": "D3-T07",
                    "source_candidate_artifact_id": "d3_t07_candidate_daily_observation",
                    "source_candidate_sha256": declarations[
                        "d3_t07_candidate_daily_observation"
                    ]["sha256"],
                },
            },
        )
        return manifest_path, paths

    @staticmethod
    def _source_bindings() -> dict[str, dict[str, object]]:
        return {
            relative: {
                "source_commit": "a" * 40,
                "git_blob_sha": "b" * 40,
                "committed_byte_sha256": "c" * 64,
                "normalized_text_sha256": "d" * 64,
                "encoding": "UTF-8",
                "line_ending": "LF",
                "BOM": False,
                "final_LF_count": 1,
            }
            for relative in FORMAL_SOURCE_PATHS
        }

    def _run_synthetic(
        self, root: Path, run_suffix: str
    ) -> tuple[dict[str, object], Path, Path]:
        manifest, paths = self._make_inputs(root)
        run_id = f"EXP-A01-20260716T120000{run_suffix}Z"
        output = root / run_id
        args = Namespace(
            allow_formal_run=True,
            reviewed_implementation_sha="a" * 40,
            config=CONFIG_PATH,
            input_manifest=manifest,
            input_root=root,
            output_root=output,
            run_id=run_id,
            memory_limit="8GB",
        )
        with (
            patch(
                "scripts.sidecar.run_exp_a01_price_ma_attachment._current_git_sha",
                return_value="a" * 40,
            ),
            patch(
                "scripts.sidecar.run_exp_a01_price_ma_attachment.subprocess.run",
                return_value=SimpleNamespace(stdout="", returncode=0),
            ),
            patch(
                "scripts.sidecar.run_exp_a01_price_ma_attachment._validate_committed_source_bindings",
                return_value=self._source_bindings(),
            ),
        ):
            result = run_formal(args)
        self.assertEqual(result["status"], "passed")
        return result, manifest, output

    def test_set_based_sql_matches_python_oracle_for_dense_edge_cases(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest, paths = self._make_inputs(root)
            del manifest
            output = root / "raw.duckdb"
            metadata = materialize_raw_metrics(
                candidate_path=paths["d3_t07_candidate_daily_observation"],
                candidate_table="d3_candidate_daily_observation",
                index_path=paths["expected_price_observation_index"],
                index_table="expected_price_observation_index",
                output_path=output,
                run_id="EXP-A01-20260716T120000000Z",
            )
            self.assertEqual(metadata["expected_row_count"], 360)

            connection = duckdb.connect(
                str(paths["expected_price_observation_index"]), read_only=True
            )
            try:
                expected_rows = [
                    dict(
                        zip(
                            (
                                "security_id",
                                "trading_date",
                                "observation_sequence",
                                "expected_observation_status",
                                "source_contract",
                                "source_ref",
                            ),
                            row,
                            strict=True,
                        )
                    )
                    for row in connection.execute(
                        "SELECT security_id, trading_date, observation_sequence, expected_observation_status, source_contract, source_ref FROM expected_price_observation_index ORDER BY security_id, observation_sequence"
                    ).fetchall()
                ]
            finally:
                connection.close()
            connection = duckdb.connect(
                str(paths["d3_t07_candidate_daily_observation"]), read_only=True
            )
            try:
                observed_rows = [
                    dict(
                        zip(
                            (
                                "security_id",
                                "trade_date",
                                "adjusted_open",
                                "adjusted_close",
                                "trading_status",
                                "daily_status",
                                "effective_adj_factor",
                                "adjustment_factor_status",
                                "is_listing_pause",
                                "row_provenance",
                            ),
                            row,
                            strict=True,
                        )
                    )
                    for row in connection.execute(
                        "SELECT ts_code, trade_date, adjusted_open, adjusted_close, trading_status, daily_status, effective_adj_factor, adjustment_factor_status, is_listing_pause, row_provenance FROM d3_candidate_daily_observation ORDER BY ts_code, COALESCE(try_strptime(trade_date, '%Y-%m-%d'), try_strptime(trade_date, '%Y%m%d'))"
                    ).fetchall()
                ]
            finally:
                connection.close()
            dense = build_dense_price_rows(expected_rows, observed_rows)
            dense_by_key = {
                (row["security_id"], row["trading_date"]): row for row in dense
            }
            oracle = {}
            for row in compute_a01_metrics(dense):
                context = dense_by_key[(row["security_id"], row["trading_date"])]
                oracle[
                    (row["security_id"], row["trading_date"], row["indicator_id"])
                ] = {
                    **row,
                    "observation_sequence": context["observation_sequence"],
                    "expected_observation_status": context[
                        "expected_observation_status"
                    ],
                    "source_ref": context["source_ref"],
                }
            connection = duckdb.connect(str(output), read_only=True)
            try:
                persisted = connection.execute(
                    "SELECT security_id, trading_date, observation_sequence, expected_observation_status, indicator_id, raw_metric_name, raw_value, validity_status, reason_codes_json, input_window_start, input_window_end, required_observation_count, actual_valid_observation_count, metric_engine_version FROM exp_a01_raw_metrics ORDER BY security_id, observation_sequence, CASE indicator_id WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END",
                    [A1_ID, A2_ID],
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(len(persisted), len(oracle) * 1)
            for row in persisted:
                key = (str(row[0]), row[1].isoformat(), str(row[4]))
                expected = oracle[key]
                self.assertEqual(row[2], expected["observation_sequence"])
                self.assertEqual(row[3], expected["expected_observation_status"])
                self.assertEqual(row[5], expected["raw_metric_name"])
                if expected["raw_value"] is None:
                    self.assertIsNone(row[6])
                else:
                    self.assertAlmostEqual(row[6], expected["raw_value"], delta=1e-12)
                self.assertEqual(row[7], expected["validity_status"])
                self.assertEqual(json.loads(row[8]), expected["reason_codes"])
                self.assertEqual(
                    row[9].isoformat() if row[9] is not None else None,
                    expected["input_window_start"],
                )
                self.assertEqual(row[10].isoformat(), expected["input_window_end"])
                self.assertEqual(row[11], expected["required_observation_count"])
                self.assertEqual(row[12], expected["actual_valid_observation_count"])
                self.assertEqual(row[13], expected["metric_engine_version"])

    def test_synthetic_end_to_end_publishes_nine_files_and_readback_passes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result, manifest, output = self._run_synthetic(Path(raw), "001")
            del result
            self.assertTrue(output.is_dir())
            self.assertFalse(Path(f"{output}.partial-").exists())
            expected_files = {
                "exp_a01_raw_metrics.duckdb",
                "exp_a01_metric_profile.csv",
                "exp_a01_validity_profile.csv",
                "exp_a01_year_coverage.csv",
                "exp_a01_security_coverage.csv",
                "exp_a01_manifest.json",
                "exp_a01_validator_result.json",
                "exp_a01_anomaly_scan.json",
                "exp_a01_result_analysis.md",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected_files)
            self.assertEqual(list(output.parent.glob(f"{output.name}.partial-*")), [])
            validator = json.loads(
                (output / "exp_a01_validator_result.json").read_text(encoding="utf-8")
            )
            anomaly = json.loads(
                (output / "exp_a01_anomaly_scan.json").read_text(encoding="utf-8")
            )
            self.assertEqual(validator["status"], "passed")
            self.assertTrue(validator["valid"])
            self.assertTrue(
                all(value == 0 for value in validator["mismatch_counts"].values())
            )
            self.assertIn(
                anomaly["status"], {"passed", "passed_with_investigation_items"}
            )
            self.assertEqual(anomaly["blocking_anomalies"], [])
            self.assertEqual(
                json.loads(
                    (output / "exp_a01_manifest.json").read_text(encoding="utf-8")
                )["input_manifest_sha256"],
                _sha(manifest),
            )
            self.assertNotIn(
                "return",
                (output / "exp_a01_result_analysis.md")
                .read_text(encoding="utf-8")
                .lower(),
            )

    def test_same_inputs_have_deterministic_scientific_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest, _paths = self._make_inputs(root)
            first_args = self._formal_args(root, manifest, "EXP-A01-20260716T120001Z")
            second_args = self._formal_args(root, manifest, "EXP-A01-20260716T120002Z")
            with self._git_context():
                run_formal(first_args)
            with self._git_context():
                run_formal(second_args)
            first = Path(first_args.output_root)
            second = Path(second_args.output_root)
            for filename in (
                "exp_a01_metric_profile.csv",
                "exp_a01_validity_profile.csv",
                "exp_a01_year_coverage.csv",
                "exp_a01_security_coverage.csv",
            ):
                self.assertEqual(
                    (first / filename).read_bytes(), (second / filename).read_bytes()
                )
            for output in (first, second):
                connection = duckdb.connect(
                    str(output / "exp_a01_raw_metrics.duckdb"), read_only=True
                )
                try:
                    rows = connection.execute(
                        "SELECT security_id, trading_date, observation_sequence, expected_observation_status, indicator_id, raw_metric_name, raw_value, validity_status, reason_codes_json, input_window_start, input_window_end, required_observation_count, actual_valid_observation_count, metric_engine_version, source_ref FROM exp_a01_raw_metrics ORDER BY security_id, observation_sequence, indicator_id"
                    ).fetchall()
                finally:
                    connection.close()
                if output == first:
                    first_rows = rows
                else:
                    self.assertEqual(first_rows, rows)

    def test_failure_cleanup_removes_partial_and_final_output(self) -> None:
        failure_points = (
            "materialize_raw_metrics",
            "write_compact_csvs",
            "validate_formal_result",
            "scan_persisted_anomalies",
            "_build_result_analysis",
        )
        for position, function_name in enumerate(failure_points):
            with (
                self.subTest(function_name=function_name),
                tempfile.TemporaryDirectory() as raw,
            ):
                root = Path(raw)
                manifest, paths = self._make_inputs(root)
                input_hashes = {name: _sha(path) for name, path in paths.items()}
                args = self._formal_args(
                    root, manifest, f"EXP-A01-20260716T1201{position:02d}Z"
                )
                target = (
                    f"scripts.sidecar.run_exp_a01_price_ma_attachment.{function_name}"
                )
                with (
                    self._git_context(),
                    patch(target, side_effect=RuntimeError("synthetic failure")),
                ):
                    with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                        run_formal(args)
                self.assertFalse(Path(args.output_root).exists())
                self.assertEqual(
                    list(root.glob(f"{Path(args.output_root).name}.partial-*")), []
                )
                self.assertEqual(
                    input_hashes, {name: _sha(path) for name, path in paths.items()}
                )

    def test_validator_catches_persisted_artifact_mutations(self) -> None:
        mutations = (
            "raw_value",
            "validity_status",
            "reason_code",
            "observation_sequence",
            "indicator_id",
            "raw_table_row_count",
            "metric_profile_count",
            "metric_profile_quantile",
            "validity_profile_count",
            "year_coverage_count",
            "security_coverage_count",
            "artifact_sha",
            "manifest_input_sha",
            "analysis_section",
        )
        for position, mutation in enumerate(mutations):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                manifest, paths = self._make_inputs(root)
                args = self._formal_args(
                    root, manifest, f"EXP-A01-20260716T1210{position:02d}Z"
                )
                with self._git_context():
                    run_formal(args)
                source = Path(args.output_root)
                mutated = root / f"mutated-{mutation}"
                shutil.copytree(source, mutated)
                if mutation == "raw_value":
                    connection = duckdb.connect(
                        str(mutated / "exp_a01_raw_metrics.duckdb")
                    )
                    try:
                        connection.execute(
                            "UPDATE exp_a01_raw_metrics SET raw_value = raw_value + 0.25 WHERE validity_status='valid' AND indicator_id=?",
                            [A1_ID],
                        )
                    finally:
                        connection.close()
                elif mutation == "validity_status":
                    connection = duckdb.connect(
                        str(mutated / "exp_a01_raw_metrics.duckdb")
                    )
                    try:
                        connection.execute(
                            "UPDATE exp_a01_raw_metrics SET validity_status='blocked' WHERE indicator_id=? AND validity_status='valid'",
                            [A1_ID],
                        )
                    finally:
                        connection.close()
                elif mutation == "reason_code":
                    connection = duckdb.connect(
                        str(mutated / "exp_a01_raw_metrics.duckdb")
                    )
                    try:
                        connection.execute(
                            "UPDATE exp_a01_raw_metrics SET reason_codes_json='[\"unknown_reason\"]' WHERE indicator_id=? AND validity_status='valid'",
                            [A1_ID],
                        )
                    finally:
                        connection.close()
                elif mutation == "observation_sequence":
                    connection = duckdb.connect(
                        str(mutated / "exp_a01_raw_metrics.duckdb")
                    )
                    try:
                        connection.execute(
                            "UPDATE exp_a01_raw_metrics SET observation_sequence=999 WHERE indicator_id=? AND observation_sequence=0",
                            [A1_ID],
                        )
                    finally:
                        connection.close()
                elif mutation == "indicator_id":
                    connection = duckdb.connect(
                        str(mutated / "exp_a01_raw_metrics.duckdb")
                    )
                    try:
                        connection.execute(
                            "UPDATE exp_a01_raw_metrics SET indicator_id='unregistered_indicator' WHERE indicator_id=? AND validity_status='valid'",
                            [A1_ID],
                        )
                    finally:
                        connection.close()
                elif mutation == "raw_table_row_count":
                    connection = duckdb.connect(
                        str(mutated / "exp_a01_raw_metrics.duckdb")
                    )
                    try:
                        connection.execute(
                            "DELETE FROM exp_a01_raw_metrics WHERE indicator_id=? AND observation_sequence=0",
                            [A1_ID],
                        )
                    finally:
                        connection.close()
                elif mutation == "metric_profile_count":
                    csv_path = mutated / "exp_a01_metric_profile.csv"
                    with csv_path.open(encoding="utf-8", newline="") as handle:
                        rows = list(csv.reader(handle))
                    header = {name: index for index, name in enumerate(rows[0])}
                    field = header["valid_count"]
                    rows[1][field] = str(int(rows[1][field]) + 1)
                    with csv_path.open("w", encoding="utf-8", newline="") as handle:
                        csv.writer(handle, lineterminator="\n").writerows(rows)
                elif mutation == "metric_profile_quantile":
                    csv_path = mutated / "exp_a01_metric_profile.csv"
                    with csv_path.open(encoding="utf-8", newline="") as handle:
                        rows = list(csv.reader(handle))
                    header = {name: index for index, name in enumerate(rows[0])}
                    field = header["median_value"]
                    rows[1][field] = str(float(rows[1][field]) + 1.0)
                    with csv_path.open("w", encoding="utf-8", newline="") as handle:
                        csv.writer(handle, lineterminator="\n").writerows(rows)
                elif mutation in {
                    "validity_profile_count",
                    "year_coverage_count",
                    "security_coverage_count",
                }:
                    filename = {
                        "validity_profile_count": "exp_a01_validity_profile.csv",
                        "year_coverage_count": "exp_a01_year_coverage.csv",
                        "security_coverage_count": "exp_a01_security_coverage.csv",
                    }[mutation]
                    csv_path = mutated / filename
                    with csv_path.open(encoding="utf-8", newline="") as handle:
                        rows = list(csv.reader(handle))
                    header = {name: index for index, name in enumerate(rows[0])}
                    field = header["row_count"]
                    rows[1][field] = str(int(rows[1][field]) + 1)
                    with csv_path.open("w", encoding="utf-8", newline="") as handle:
                        csv.writer(handle, lineterminator="\n").writerows(rows)
                elif mutation == "artifact_sha":
                    payload = json.loads(
                        (mutated / "exp_a01_manifest.json").read_text(encoding="utf-8")
                    )
                    payload["output_artifacts"]["exp_a01_raw_metrics.duckdb"][
                        "sha256"
                    ] = "0" * 64
                    _write_json(mutated / "exp_a01_manifest.json", payload)
                elif mutation == "manifest_input_sha":
                    payload = json.loads(
                        (mutated / "exp_a01_manifest.json").read_text(encoding="utf-8")
                    )
                    payload["input_manifest_sha256"] = "0" * 64
                    _write_json(mutated / "exp_a01_manifest.json", payload)
                else:
                    analysis = mutated / "exp_a01_result_analysis.md"
                    analysis.write_text(
                        analysis.read_text(encoding="utf-8").replace(
                            "## 10. Reason-code profile", "## removed"
                        ),
                        encoding="utf-8",
                        newline="\n",
                    )
                config = load_json(CONFIG_PATH)
                metadata = self._input_metadata(config, paths)
                validation = validate_formal_result(
                    mutated,
                    config=config,
                    input_manifest=json.loads(manifest.read_text(encoding="utf-8")),
                    input_manifest_path=manifest,
                    input_paths=paths,
                    input_metadata=metadata,
                    expected_index_row_count=120,
                    reviewed_implementation_sha="a" * 40,
                )
                self.assertEqual(validation["status"], "failed")
                self.assertTrue(validation["errors"])

    def test_validator_source_import_isolation_is_explicit(self) -> None:
        source = (
            ROOT / "src/sidecar/exp_a01_price_ma_attachment_validator.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("from src.sidecar.exp_a01_price_ma_attachment import", source)
        self.assertNotIn(
            "from src.sidecar.exp_a01_price_ma_attachment_formal import", source
        )
        self.assertNotIn(
            "from scripts.sidecar.run_exp_a01_price_ma_attachment import", source
        )

    @staticmethod
    def _formal_args(root: Path, manifest: Path, run_id: str) -> Namespace:
        return Namespace(
            allow_formal_run=True,
            reviewed_implementation_sha="a" * 40,
            config=CONFIG_PATH,
            input_manifest=manifest,
            input_root=root,
            output_root=root / run_id,
            run_id=run_id,
            memory_limit="8GB",
        )

    def _git_context(self):
        stack = ExitStack()
        stack.enter_context(
            patch(
                "scripts.sidecar.run_exp_a01_price_ma_attachment._current_git_sha",
                return_value="a" * 40,
            )
        )
        stack.enter_context(
            patch(
                "scripts.sidecar.run_exp_a01_price_ma_attachment.subprocess.run",
                return_value=SimpleNamespace(stdout="", returncode=0),
            )
        )
        stack.enter_context(
            patch(
                "scripts.sidecar.run_exp_a01_price_ma_attachment._validate_committed_source_bindings",
                return_value=self._source_bindings(),
            )
        )
        return stack

    def _input_metadata(
        self, config: dict[str, object], paths: dict[str, Path]
    ) -> dict[str, dict[str, object]]:
        metadata: dict[str, dict[str, object]] = {}
        for artifact_id in config["input_contract"]["manifest_artifact_names"]:
            artifact = config["input_contract"]["artifacts"][artifact_id]
            path = paths[artifact_id]
            if artifact["artifact_kind"] == "evidence_json":
                metadata[artifact_id] = {
                    "path": str(path),
                    "sha256": _sha(path),
                    "json": json.loads(path.read_text(encoding="utf-8")),
                }
            else:
                connection = duckdb.connect(str(path), read_only=True)
                try:
                    columns = [
                        str(row[1])
                        for row in connection.execute(
                            f"PRAGMA table_info('{artifact['table']}')"
                        ).fetchall()
                    ]
                    count = int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {artifact['table']}"
                        ).fetchone()[0]
                    )
                finally:
                    connection.close()
                metadata[artifact_id] = {
                    "path": str(path),
                    "sha256": _sha(path),
                    "actual_columns": columns,
                    "source_full_row_count": count,
                    "table": artifact["table"],
                }
        return metadata


if __name__ == "__main__":
    unittest.main()
