from __future__ import annotations

# Synthetic SQL fixtures intentionally keep the selected columns visible.
# ruff: noqa: E501
import csv
import hashlib
import json
import math
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

import scripts.sidecar.run_exp_a01_price_ma_attachment as runner_module
import src.sidecar.exp_a01_price_ma_attachment_validator as validator_module
from scripts.sidecar.run_exp_a01_price_ma_attachment import (
    FORMAL_SOURCE_PATHS,
    run_formal,
)
from scripts.sidecar.validate_exp_a01_price_ma_attachment import (
    validate as validate_cli,
)
from src.sidecar.exp_a01_price_ma_attachment import (
    A1_ID,
    A2_ID,
    A2B_ID,
    INDEX_SOURCE_CONTRACT,
    build_dense_price_rows,
    compute_a01_metrics,
)
from src.sidecar.exp_a01_price_ma_attachment_formal import (
    materialize_raw_metrics,
    write_compact_csvs,
)
from src.sidecar.exp_a01_price_ma_attachment_validator import (
    _validate_stratified_independent_oracle,
    load_json,
    validate_formal_result,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"
CONFIG_SCHEMA_PATH = (
    ROOT / "schemas/sidecar/exp_a01_price_ma_attachment_candidates.schema.json"
)

# Frozen from the real 601077.SH sequence 461..539 boundary reproduction.  The
# fixture keeps the test independent of the permanent formal-input directory.
_BOUNDARY_ROWS = (
    (461, "20210915", 4.3758, 4.38685),
    (462, "20210916", 4.38685, 4.34265),
    (463, "20210917", 4.3537, 4.34265),
    (464, "20210922", 4.2874, 4.29845),
    (465, "20210923", 4.3095, 4.3316),
    (466, "20210924", 4.3316, 4.29845),
    (467, "20210927", 4.2874, 4.2653),
    (468, "20210928", 4.2653, 4.29845),
    (469, "20210929", 4.27635, 4.2874),
    (470, "20210930", 4.2874, 4.2653),
    (471, "20211008", 4.27635, 4.32055),
    (472, "20211011", 4.32055, 4.34265),
    (473, "20211012", 4.3316, 4.2874),
    (474, "20211013", 4.2874, 4.3095),
    (475, "20211014", 4.29845, 4.27635),
    (476, "20211015", 4.2874, 4.2653),
    (477, "20211018", 4.2653, 4.25425),
    (478, "20211019", 4.25425, 4.2653),
    (479, "20211020", 4.27635, 4.21005),
    (480, "20211021", 4.2211, 4.2432),
    (481, "20211022", 4.2432, 4.2432),
    (482, "20211025", 4.23215, 4.2432),
    (483, "20211026", 4.2432, 4.2432),
    (484, "20211027", 4.2432, 4.21005),
    (485, "20211028", 4.199, 4.1769),
    (486, "20211029", 4.199, 4.2211),
    (487, "20211101", 4.2211, 4.25425),
    (488, "20211102", 4.25425, 4.21005),
    (489, "20211103", 4.21005, 4.21005),
    (490, "20211104", 4.2211, 4.21005),
    (491, "20211105", 4.199, 4.18795),
    (492, "20211108", 4.18795, 4.199),
    (493, "20211109", 4.199, 4.199),
    (494, "20211110", 4.199, 4.199),
    (495, "20211111", 4.199, 4.2432),
    (496, "20211112", 4.23215, 4.2211),
    (497, "20211115", 4.2211, 4.23215),
    (498, "20211116", 4.23215, 4.23215),
    (499, "20211117", 4.2211, 4.23215),
    (500, "20211118", 4.2211, 4.21005),
    (501, "20211119", 4.2211, 4.2432),
    (502, "20211122", 4.23215, 4.23215),
    (503, "20211123", 4.23215, 4.2432),
    (504, "20211124", 4.2432, 4.2432),
    (505, "20211125", 4.2432, 4.23215),
    (506, "20211126", 4.23215, 4.23215),
    (507, "20211129", 4.21005, 4.2211),
    (508, "20211130", 4.2211, 4.2211),
    (509, "20211201", 4.2211, 4.23215),
    (510, "20211202", 4.23215, 4.2432),
    (511, "20211203", 4.2432, 4.2432),
    (512, "20211206", 4.25425, 4.25425),
    (513, "20211207", 4.2653, 4.2653),
    (514, "20211208", 4.27635, 4.2653),
    (515, "20211209", 4.25425, 4.2874),
    (516, "20211210", 4.27635, 4.2653),
    (517, "20211213", 4.25425, 4.2432),
    (518, "20211214", 4.23215, 4.23215),
    (519, "20211215", 4.2211, 4.2211),
    (520, "20211216", 4.23215, 4.23215),
    (521, "20211217", 4.23215, 4.23215),
    (522, "20211220", 4.2211, 4.2211),
    (523, "20211221", 4.21005, 4.2653),
    (524, "20211222", 4.2653, 4.25425),
    (525, "20211223", 4.2653, 4.25425),
    (526, "20211224", 4.25425, 4.2432),
    (527, "20211227", 4.25425, 4.25425),
    (528, "20211228", 4.2432, 4.2432),
    (529, "20211229", 4.2432, 4.25425),
    (530, "20211230", 4.2432, 4.2432),
    (531, "20211231", 4.2432, 4.25425),
    (532, "20220104", 4.25425, 4.27635),
    (533, "20220105", 4.27635, 4.29845),
    (534, "20220106", 4.2874, 4.2874),
    (535, "20220107", 4.2874, 4.34265),
    (536, "20220110", 4.3537, 4.36475),
    (537, "20220111", 4.36475, 4.40895),
    (538, "20220112", 4.3979, 4.38685),
    (539, "20220113", 4.38685, 4.38685),
)


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
                    11: "listed_open_resolved_daily",
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
                "schema_version": "exp_a01_authorized_input_manifest.v2",
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
                "input_governance": {
                    "d3_t08_required": False,
                    "owner_override": True,
                    "override_reason": "D3-T08 is not required for the EXP-A01 four-artifact contract.",
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
                    "expected_index_sha256": declarations[
                        "expected_price_observation_index"
                    ]["sha256"],
                },
            },
        )
        return manifest_path, paths

    def _make_boundary_fixture(
        self, root: Path
    ) -> tuple[Path, Path, list[dict[str, object]]]:
        candidate_path = root / "d3_t07_candidate_daily_observation.duckdb"
        index_path = root / "expected_price_observation_index.duckdb"
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
            candidate.executemany(
                "INSERT INTO d3_candidate_daily_observation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "601077.SH",
                        trade_date,
                        adjusted_open,
                        adjusted_close,
                        "listed_open_resolved_daily",
                        "resolved",
                        1.105,
                        "resolved",
                        False,
                        "D2-T20",
                        "D3-T07",
                        f"fixture:601077.SH:{sequence}",
                    )
                    for sequence, trade_date, adjusted_open, adjusted_close in _BOUNDARY_ROWS
                ],
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
                        "601077.SH",
                        date.fromisoformat(
                            f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
                        ),
                        sequence,
                        "present",
                        INDEX_SOURCE_CONTRACT,
                        f"fixture:601077.SH:{sequence}",
                    )
                    for sequence, trade_date, _open, _close in _BOUNDARY_ROWS
                ],
            )
        finally:
            index.close()

        history = [
            {
                "security_id": "601077.SH",
                "trading_date": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",
                "observation_sequence": sequence,
                "expected_observation_status": "present",
                "adjusted_open": adjusted_open,
                "adjusted_close": adjusted_close,
                "trading_status": "listed_open_resolved_daily",
                "daily_status": "resolved",
                "effective_adj_factor": 1.105,
                "adjustment_factor_status": "resolved",
                "is_listing_pause": False,
                "row_provenance": f"fixture:601077.SH:{sequence}",
                "source_contract": INDEX_SOURCE_CONTRACT,
                "source_ref": f"fixture:601077.SH:{sequence}",
            }
            for sequence, trade_date, adjusted_open, adjusted_close in _BOUNDARY_ROWS
        ]
        return candidate_path, index_path, history

    def test_real_601077_boundary_fixture_matches_production_and_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            candidate_path, index_path, history = self._make_boundary_fixture(root)
            raw_path = root / "raw.duckdb"
            metadata = materialize_raw_metrics(
                candidate_path=candidate_path,
                candidate_table="d3_candidate_daily_observation",
                index_path=index_path,
                index_table="expected_price_observation_index",
                output_path=raw_path,
                run_id="EXP-A01-BOUNDARY-FIXTURE",
                duckdb_threads=12,
                memory_limit="12GB",
            )
            self.assertEqual(metadata["expected_row_count"], 79 * 3)

            connection = duckdb.connect(str(candidate_path), read_only=True)
            try:
                connection.execute(
                    "ATTACH '"
                    + str(index_path).replace("'", "''")
                    + "' AS expected (READ_ONLY)"
                )
                boundary = connection.execute(
                    """
                    WITH ordered AS (
                      SELECT i.observation_sequence, c.adjusted_open, c.adjusted_close
                      FROM d3_candidate_daily_observation AS c
                      JOIN expected.expected_price_observation_index AS i
                        ON i.security_id = c.ts_code
                       AND i.trading_date = try_strptime(c.trade_date, '%Y%m%d')::DATE
                    ), averages AS (
                      SELECT *,
                        AVG(adjusted_close) OVER (ORDER BY observation_sequence ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5,
                        AVG(adjusted_close) OVER (ORDER BY observation_sequence ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS ma10,
                        AVG(adjusted_close) OVER (ORDER BY observation_sequence ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                        AVG(adjusted_close) OVER (ORDER BY observation_sequence ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS ma30,
                        AVG(adjusted_close) OVER (ORDER BY observation_sequence ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60
                      FROM ordered
                    ), cloud AS (
                      SELECT *,
                        (LN(adjusted_open) + LN(adjusted_close)) / 2.0 AS body,
                        LEAST(LN(ma5), LN(ma10), LN(ma20), LN(ma30), LN(ma60)) AS cloud_low,
                        GREATEST(LN(ma5), LN(ma10), LN(ma20), LN(ma30), LN(ma60)) AS cloud_high
                      FROM averages
                    )
                    SELECT body, cloud_low, cloud_high,
                      body < cloud_low - (8.0 * 2.220446049250313e-16 * GREATEST(1.0, ABS(body), ABS(cloud_low)))
                      OR body > cloud_high + (8.0 * 2.220446049250313e-16 * GREATEST(1.0, ABS(body), ABS(cloud_high)))
                    FROM cloud
                    WHERE observation_sequence = 527
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(boundary)
            self.assertFalse(bool(boundary[3]))

            oracle_boundary = validator_module._independent_cloud_point(history, 66)
            self.assertFalse(
                validator_module._independent_outside(*oracle_boundary[:3])
            )

            connection = duckdb.connect(str(raw_path), read_only=True)
            try:
                production = {
                    row[0]: {"raw_value": row[1], "validity_status": row[2]}
                    for row in connection.execute(
                        "SELECT indicator_id, raw_value, validity_status FROM exp_a01_raw_metrics WHERE observation_sequence = 539"
                    ).fetchall()
                }
            finally:
                connection.close()
            oracle = {
                row["indicator_id"]: row
                for row in validator_module._independent_metrics(
                    history, run_id="EXP-A01-BOUNDARY-FIXTURE"
                )
            }
            self.assertEqual(production[A2_ID]["validity_status"], "valid")
            self.assertEqual(oracle[A2_ID]["validity_status"], "valid")
            self.assertEqual(round(float(production[A2_ID]["raw_value"]) * 20), 13)
            self.assertEqual(round(float(oracle[A2_ID]["raw_value"]) * 20), 13)
            self.assertEqual(float(production[A2_ID]["raw_value"]), 0.65)
            self.assertEqual(float(oracle[A2_ID]["raw_value"]), 0.65)
            for indicator_id in (A1_ID, A2B_ID):
                self.assertTrue(
                    math.isclose(
                        float(production[indicator_id]["raw_value"]),
                        float(oracle[indicator_id]["raw_value"]),
                        rel_tol=1e-9,
                        abs_tol=1e-12,
                    )
                )

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
            duckdb_threads=12,
            memory_limit="12GB",
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
            patch(
                "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
                return_value=self._source_bindings(),
            ),
        ):
            result = run_formal(args)
        self.assertEqual(result["status"], "passed")
        self.assertFalse((root / "formal-failures" / run_id / "package").exists())
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

    def test_duckdb_thread_profiles_preserve_scientific_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _manifest, paths = self._make_inputs(root)
            raw_one = root / "thread-one.duckdb"
            raw_twelve = root / "thread-twelve.duckdb"
            for output_path, threads in ((raw_one, 1), (raw_twelve, 12)):
                materialize_raw_metrics(
                    candidate_path=paths["d3_t07_candidate_daily_observation"],
                    candidate_table="d3_candidate_daily_observation",
                    index_path=paths["expected_price_observation_index"],
                    index_table="expected_price_observation_index",
                    output_path=output_path,
                    run_id="EXP-A01-20260716T120000000Z",
                    duckdb_threads=threads,
                    memory_limit="12GB",
                )
            profiles_one = root / "profiles-one"
            profiles_twelve = root / "profiles-twelve"
            profiles_one.mkdir()
            profiles_twelve.mkdir()
            write_compact_csvs(
                output_dir=profiles_one,
                raw_duckdb=raw_one,
                duckdb_threads=1,
                memory_limit="12GB",
            )
            write_compact_csvs(
                output_dir=profiles_twelve,
                raw_duckdb=raw_twelve,
                duckdb_threads=12,
                memory_limit="12GB",
            )

            raw_query = (
                "SELECT run_id, security_id, trading_date, observation_sequence, "
                "expected_observation_status, indicator_id, raw_metric_name, raw_value, "
                "validity_status, reason_codes_json, input_window_start, input_window_end, "
                "required_observation_count, actual_valid_observation_count, "
                "metric_engine_version, source_ref FROM exp_a01_raw_metrics "
                "ORDER BY security_id, observation_sequence, indicator_id"
            )
            raw_rows: list[list[tuple[object, ...]]] = []
            for path in (raw_one, raw_twelve):
                connection = duckdb.connect(str(path), read_only=True)
                try:
                    raw_rows.append(connection.execute(raw_query).fetchall())
                finally:
                    connection.close()
            self.assertEqual(len(raw_rows[0]), len(raw_rows[1]))
            for first, second in zip(raw_rows[0], raw_rows[1], strict=True):
                self.assertEqual(first[:7], second[:7])
                if first[7] is None or second[7] is None:
                    self.assertEqual(first[7], second[7])
                else:
                    self.assertAlmostEqual(first[7], second[7], delta=1e-12)
                self.assertEqual(first[8:], second[8:])

            for filename in (
                "exp_a01_metric_profile.csv",
                "exp_a01_validity_profile.csv",
                "exp_a01_year_coverage.csv",
                "exp_a01_security_coverage.csv",
            ):
                with (
                    (profiles_one / filename).open(
                        encoding="utf-8", newline=""
                    ) as first_handle,
                    (profiles_twelve / filename).open(
                        encoding="utf-8", newline=""
                    ) as second_handle,
                ):
                    first_rows = list(csv.DictReader(first_handle))
                    second_rows = list(csv.DictReader(second_handle))
                self.assertEqual(len(first_rows), len(second_rows))
                for first, second in zip(first_rows, second_rows, strict=True):
                    self.assertEqual(set(first), set(second))
                    for field in first:
                        if first[field] == second[field]:
                            continue
                        try:
                            left = float(first[field])
                            right = float(second[field])
                        except (TypeError, ValueError):
                            self.assertEqual(first[field], second[field])
                        else:
                            tolerance = 1e-12 * max(1.0, abs(left), abs(right))
                            self.assertLessEqual(abs(left - right), tolerance)

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

    def test_large_input_strategy_uses_deterministic_sample_without_full_stream(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _result, manifest, output = self._run_synthetic(root, "003")
            config = load_json(CONFIG_PATH)
            paths = {
                "d3_t07_candidate_daily_observation": root
                / "d3_t07_candidate_daily_observation.duckdb",
                "expected_price_observation_index": root
                / "expected_price_observation_index.duckdb",
            }
            results = []
            for _ in range(2):
                connection = duckdb.connect(str(output / "exp_a01_raw_metrics.duckdb"))
                try:
                    errors: list[str] = []
                    mismatches = {"oracle_sample_mismatch": 0}
                    result = _validate_stratified_independent_oracle(
                        connection,
                        candidate_path=paths["d3_t07_candidate_daily_observation"],
                        index_path=paths["expected_price_observation_index"],
                        expected_index_table="expected_price_observation_index",
                        expected_index_row_count=100001,
                        run_id="EXP-A01-20260716T120000003Z",
                        config=config,
                        errors=errors,
                        mismatch_counts=mismatches,
                    )
                finally:
                    connection.close()
                self.assertEqual(errors, [])
                self.assertEqual(mismatches["oracle_sample_mismatch"], 0)
                results.append(result)
            first, second = results
            self.assertEqual(first["oracle_mode"], "deterministic_stratified_sample")
            self.assertLessEqual(first["oracle_target_observation_count"], 10000)
            self.assertEqual(
                first["oracle_compared_raw_row_count"],
                first["oracle_target_observation_count"] * 3,
            )
            self.assertEqual(
                first["oracle_sample_target_fingerprint"],
                second["oracle_sample_target_fingerprint"],
            )
            self.assertEqual(first["oracle_sample_security_count"], 1)

    def test_small_input_full_oracle_is_not_capped_by_sample_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _result, _manifest, output = self._run_synthetic(root, "004")
            paths = {
                "d3_t07_candidate_daily_observation": root
                / "d3_t07_candidate_daily_observation.duckdb",
                "expected_price_observation_index": root
                / "expected_price_observation_index.duckdb",
            }
            connection = duckdb.connect(str(output / "exp_a01_raw_metrics.duckdb"))
            try:
                errors: list[str] = []
                mismatches = {"oracle_sample_mismatch": 0}
                with patch.object(validator_module, "ORACLE_SAMPLE_TARGET_LIMIT", 0):
                    result = _validate_stratified_independent_oracle(
                        connection,
                        candidate_path=paths["d3_t07_candidate_daily_observation"],
                        index_path=paths["expected_price_observation_index"],
                        expected_index_table="expected_price_observation_index",
                        expected_index_row_count=20368,
                        run_id="EXP-A01-20260716T120000004Z",
                        config=load_json(CONFIG_PATH),
                        errors=errors,
                        mismatch_counts=mismatches,
                    )
            finally:
                connection.close()
            self.assertEqual(errors, [])
            self.assertEqual(mismatches["oracle_sample_mismatch"], 0)
            self.assertEqual(result["oracle_mode"], "full_small_input")
            self.assertEqual(
                result["oracle_compared_raw_row_count"],
                result["oracle_target_observation_count"] * 3,
            )

    def test_runner_executes_core_validator_once_and_cheap_final_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest, _paths = self._make_inputs(root)
            args = self._formal_args(root, manifest, "EXP-A01-20260716T123000Z")
            with (
                self._git_context(),
                patch.object(
                    runner_module,
                    "validate_formal_result",
                    wraps=runner_module.validate_formal_result,
                ) as core_mock,
                patch.object(
                    runner_module,
                    "_validate_final_package_bindings",
                    wraps=runner_module._validate_final_package_bindings,
                ) as final_mock,
            ):
                runner_module.run_formal(args)
            self.assertEqual(core_mock.call_count, 1)
            self.assertEqual(final_mock.call_count, 1)

    def test_standalone_cli_replays_lineage_and_fails_on_manifest_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _result, manifest, output = self._run_synthetic(root, "002")
            with patch(
                "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
                return_value=self._source_bindings(),
            ):
                passed = validate_cli(
                    CONFIG_PATH,
                    CONFIG_SCHEMA_PATH,
                    output,
                    manifest,
                    root,
                    "a" * 40,
                )
            self.assertEqual(passed["status"], "passed")
            self.assertEqual(passed["formal_result"]["status"], "passed")

            mutated = root / "cli-mutated"
            shutil.copytree(output, mutated)
            formal_manifest = json.loads(
                (mutated / "exp_a01_manifest.json").read_text(encoding="utf-8")
            )
            formal_manifest["input_manifest_sha256"] = "0" * 64
            _write_json(mutated / "exp_a01_manifest.json", formal_manifest)
            with patch(
                "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
                return_value=self._source_bindings(),
            ):
                failed = validate_cli(
                    CONFIG_PATH,
                    CONFIG_SCHEMA_PATH,
                    mutated,
                    manifest,
                    root,
                    "a" * 40,
                )
            self.assertEqual(failed["status"], "failed")
            self.assertTrue(failed["formal_result"]["errors"])

            for label, mutate in (
                (
                    "authorization",
                    lambda payload: payload["authorization"].update(
                        {"authorization_status": "tampered"}
                    ),
                ),
                (
                    "cross-binding",
                    lambda payload: payload["cross_artifact_bindings"].update(
                        {"d3_t07_candidate_sha256": "0" * 64}
                    ),
                ),
            ):
                with self.subTest(lineage_mutation=label):
                    mutated_manifest = root / f"{label}-manifest.json"
                    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
                    mutate(manifest_payload)
                    _write_json(mutated_manifest, manifest_payload)
                    mutated_output = root / f"cli-{label}"
                    shutil.copytree(output, mutated_output)
                    mutated_formal_manifest = json.loads(
                        (mutated_output / "exp_a01_manifest.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    mutated_formal_manifest["input_manifest_path"] = str(
                        mutated_manifest.resolve()
                    )
                    mutated_formal_manifest["input_manifest_sha256"] = _sha(
                        mutated_manifest
                    )
                    _write_json(
                        mutated_output / "exp_a01_manifest.json",
                        mutated_formal_manifest,
                    )
                    with patch(
                        "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
                        return_value=self._source_bindings(),
                    ):
                        lineage_failed = validate_cli(
                            CONFIG_PATH,
                            CONFIG_SCHEMA_PATH,
                            mutated_output,
                            mutated_manifest,
                            root,
                            "a" * 40,
                        )
                    self.assertEqual(lineage_failed["status"], "failed")
                    self.assertTrue(lineage_failed["formal_result"]["errors"])

            source_mutation = root / "cli-source-binding"
            shutil.copytree(output, source_mutation)
            source_manifest = json.loads(
                (source_mutation / "exp_a01_manifest.json").read_text(encoding="utf-8")
            )
            first_source = FORMAL_SOURCE_PATHS[0]
            source_manifest["source_bindings"][first_source]["git_blob_sha"] = "0" * 40
            _write_json(source_mutation / "exp_a01_manifest.json", source_manifest)
            with patch(
                "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
                return_value=self._source_bindings(),
            ):
                source_failed = validate_cli(
                    CONFIG_PATH,
                    CONFIG_SCHEMA_PATH,
                    source_mutation,
                    manifest,
                    root,
                    "a" * 40,
                )
            self.assertEqual(source_failed["status"], "failed")
            self.assertTrue(source_failed["formal_result"]["errors"])

    def test_existing_package_validation_is_read_only_and_not_formal_approval(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _result, manifest, output = self._run_synthetic(root, "003")
            failed_package = root / "failed-package"
            shutil.copytree(output, failed_package)
            _write_json(
                failed_package / "failure_summary.json",
                {
                    "task_id": "EXP-A01",
                    "run_id": "EXP-A01-20260716T120000003Z",
                    "status": "failed",
                    "published": False,
                    "formal_artifacts_generated": False,
                    "formal_data_version": False,
                    "usable_as_formal_result": False,
                },
            )
            raw_before = _sha(failed_package / "exp_a01_raw_metrics.duckdb")
            diagnostic_dir = root / "existing-package-diagnostic"
            with patch(
                "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
                return_value=self._source_bindings(),
            ):
                result = validate_cli(
                    CONFIG_PATH,
                    CONFIG_SCHEMA_PATH,
                    None,
                    manifest,
                    root,
                    "a" * 40,
                    existing_package=failed_package,
                    diagnostic_output_dir=diagnostic_dir,
                )
            self.assertEqual(
                result["validation_mode"], "existing_failed_package_read_only"
            )
            self.assertFalse(result["published"])
            self.assertFalse(result["usable_as_formal_result"])
            self.assertEqual(
                result["formal_approval"],
                "not_permitted_existing_package_diagnostic",
            )
            self.assertTrue(
                (diagnostic_dir / "exp_a01_existing_package_validation.json").is_file()
            )
            self.assertEqual(
                raw_before, _sha(failed_package / "exp_a01_raw_metrics.duckdb")
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

    def test_failure_preserves_unpublished_package_and_raw_diagnostics(self) -> None:
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
                failed_package = root / "formal-failures" / args.run_id / "package"
                self.assertTrue(failed_package.is_dir())
                self.assertTrue((failed_package / "failure_summary.json").is_file())
                failure_summary = json.loads(
                    (failed_package / "failure_summary.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertFalse(failure_summary["published"])
                self.assertFalse(failure_summary["formal_artifacts_generated"])
                self.assertFalse(failure_summary["usable_as_formal_result"])
                if function_name != "materialize_raw_metrics":
                    self.assertTrue(
                        (failed_package / "exp_a01_raw_metrics.duckdb").is_file()
                    )
                self.assertEqual(
                    input_hashes, {name: _sha(path) for name, path in paths.items()}
                )

    def test_preliminary_anomaly_failure_stops_before_final_replay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest, _paths = self._make_inputs(root)
            args = self._formal_args(root, manifest, "EXP-A01-20260716T122000Z")
            validation = {"status": "passed", "errors": [], "warnings": []}
            anomaly = {
                "status": "failed",
                "blocking_anomalies": ["no_valid_rows:test"],
            }
            with (
                self._git_context(),
                patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment.validate_formal_result",
                    return_value=validation,
                ) as validate_mock,
                patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment.scan_persisted_anomalies",
                    return_value=anomaly,
                ) as anomaly_mock,
                patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment._build_result_analysis"
                ) as analysis_mock,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "preliminary formal-result anomaly scan failed"
                ):
                    run_formal(args)
            self.assertEqual(validate_mock.call_count, 1)
            self.assertEqual(anomaly_mock.call_count, 1)
            analysis_mock.assert_not_called()
            self.assertFalse(Path(args.output_root).exists())
            self.assertEqual(
                list(root.glob(f"{Path(args.output_root).name}.partial-*")), []
            )
            failed_package = root / "formal-failures" / args.run_id / "package"
            self.assertTrue(failed_package.is_dir())
            self.assertTrue((failed_package / "exp_a01_raw_metrics.duckdb").is_file())
            self.assertTrue((failed_package / "failure_summary.json").is_file())

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
                with patch(
                    "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
                    return_value=self._source_bindings(),
                ):
                    validation = validate_formal_result(
                        mutated,
                        config_path=CONFIG_PATH,
                        input_manifest_path=manifest,
                        input_root=root,
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
            duckdb_threads=12,
            memory_limit="12GB",
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
        stack.enter_context(
            patch(
                "src.sidecar.exp_a01_price_ma_attachment_validator._validate_formal_source_bindings",
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
