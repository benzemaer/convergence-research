from __future__ import annotations

# ruff: noqa: E501
import json
import tempfile
import unittest
from pathlib import Path

from src.r0.r0_t10_confirmation_interval_materialization_validator import (
    R0T10ConfirmationIntervalValidationError,
    validate_materialization,
)
from src.r0.r0_t10_confirmation_interval_materializer import (
    CONFIRMED_INTERVAL_DUCKDB_NAME,
    CONFIRMED_INTERVAL_TABLE_NAME,
    DAILY_CONFIRMATION_DUCKDB_NAME,
    DAILY_CONFIRMATION_TABLE_NAME,
    MANIFEST_NAME,
    R0T10ConfirmationIntervalMaterializationError,
    materialize_r0_t07_confirmation_intervals,
)
from src.r0.r0_t10_nested_state_materializer import NESTED_DAILY_TABLE_NAME
from src.r0.upstream_artifact_io import sha256_file

FULL_SHA = "20779147340fbeba8dc3fcdc5d95c71adde65c69"


class R0T10ConfirmationIntervalMaterializerTest(unittest.TestCase):
    def test_materializer_and_validator_pass_on_small_sample_with_max_workers_16(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_nested_source(root)
            evidence = _write_r0_t06_evidence(root, source)
            output = root / "out"

            summary = materialize_r0_t07_confirmation_intervals(
                r0_t06_evidence=evidence,
                nested_daily_state_duckdb=source,
                output_dir=output,
                run_id="R0-T10-04-test",
                code_commit=FULL_SHA,
                max_workers=16,
                duckdb_threads=1,
                duckdb_memory_limit_per_worker="1GB",
                chunk_size_securities=1,
                resume=True,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["R0-T10-05_allowed_to_start"], True)
            manifest = json.loads((output / MANIFEST_NAME).read_text())
            self.assertEqual(manifest["code_commit"], FULL_SHA)
            self.assertEqual(
                manifest["concurrency_policy"]["process_pool_context"], "spawn"
            )
            self.assertTrue((output / DAILY_CONFIRMATION_DUCKDB_NAME).is_file())
            self.assertTrue((output / CONFIRMED_INTERVAL_DUCKDB_NAME).is_file())

            result = validate_materialization(
                output,
                r0_t06_evidence=evidence,
                nested_daily_state_duckdb=source,
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["full_code_commit_check"], "passed")
            self.assertEqual(result["daily_recompute_mismatch_count"], 0)
            self.assertEqual(result["interval_recompute_mismatch_count"], 0)
            self.assertGreater(result["confirmed_true_sample_count"], 0)
            self.assertGreater(result["raw_false_sample_count"], 0)
            self.assertGreater(result["raw_non_ready_sample_count"], 0)

            import duckdb  # noqa: PLC0415

            conn = duckdb.connect(
                str(output / DAILY_CONFIRMATION_DUCKDB_NAME), read_only=True
            )
            try:
                s_p, s_pc = conn.execute(
                    f"""
                    SELECT
                      max(CASE WHEN state_name = 'S_P' THEN confirmed_state END),
                      max(CASE WHEN state_name = 'S_PC' THEN validity_status END)
                    FROM {DAILY_CONFIRMATION_TABLE_NAME}
                    WHERE security_id = '000004.SZ'
                      AND percentile_window_W = 120
                      AND abs(q - 0.10) < 1e-12
                      AND trading_date = '20260102'
                      AND confirmation_k = 2
                    """
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(s_p, True)
            self.assertEqual(s_pc, "unknown")

    def test_short_code_commit_and_excess_workers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_nested_source(root)
            evidence = _write_r0_t06_evidence(root, source)
            with self.assertRaises(R0T10ConfirmationIntervalMaterializationError):
                materialize_r0_t07_confirmation_intervals(
                    r0_t06_evidence=evidence,
                    nested_daily_state_duckdb=source,
                    output_dir=root / "short",
                    run_id="short",
                    code_commit="92dccee",
                )
            with self.assertRaises(R0T10ConfirmationIntervalMaterializationError):
                materialize_r0_t07_confirmation_intervals(
                    r0_t06_evidence=evidence,
                    nested_daily_state_duckdb=source,
                    output_dir=root / "workers",
                    run_id="workers",
                    code_commit=FULL_SHA,
                    max_workers=17,
                )

    def test_input_gate_and_hash_mismatch_block_without_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_nested_source(root)
            evidence = root / "evidence.md"
            evidence.write_text(
                "\n".join(
                    [
                        "`nested_daily_state_duckdb_sha256`: `bad`",
                        "`nested_daily_state_row_count`: 1",
                        "`security_count`: 1",
                        "`date_min`: 20260101",
                        "`date_max`: 20260102",
                        "`R0-T07_allowed_to_start`: true",
                    ]
                ),
                encoding="utf-8",
            )
            output = root / "blocked"

            summary = materialize_r0_t07_confirmation_intervals(
                r0_t06_evidence=evidence,
                nested_daily_state_duckdb=source,
                output_dir=output,
                run_id="blocked",
                code_commit=FULL_SHA,
            )

            self.assertEqual(summary["status"], "blocked")
            self.assertFalse((output / MANIFEST_NAME).exists())
            self.assertFalse((output / DAILY_CONFIRMATION_DUCKDB_NAME).exists())
            self.assertIn(
                "r0_t06_nested_daily_duckdb_hash_mismatch", summary["reason_codes"]
            )

    def test_validator_fails_on_daily_and_interval_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_nested_source(root)
            evidence = _write_r0_t06_evidence(root, source)
            output = root / "out"
            materialize_r0_t07_confirmation_intervals(
                r0_t06_evidence=evidence,
                nested_daily_state_duckdb=source,
                output_dir=output,
                run_id="tamper",
                code_commit=FULL_SHA,
                max_workers=2,
            )
            _rewrite_manifest_hashes(output)

            import duckdb  # noqa: PLC0415

            daily = output / DAILY_CONFIRMATION_DUCKDB_NAME
            conn = duckdb.connect(str(daily))
            try:
                conn.execute(
                    f"""
                    UPDATE {DAILY_CONFIRMATION_TABLE_NAME}
                    SET raw_streak = 999
                    WHERE state_name = 'S_P' AND confirmation_k = 2
                    """
                )
            finally:
                conn.close()
            _rewrite_manifest_hashes(output)
            with self.assertRaises(R0T10ConfirmationIntervalValidationError) as ctx:
                validate_materialization(
                    output,
                    r0_t06_evidence=evidence,
                    nested_daily_state_duckdb=source,
                )
            self.assertIn("daily_recompute_mismatch", str(ctx.exception))

            materialize_r0_t07_confirmation_intervals(
                r0_t06_evidence=evidence,
                nested_daily_state_duckdb=source,
                output_dir=output,
                run_id="tamper",
                code_commit=FULL_SHA,
                max_workers=2,
                resume=False,
            )
            interval = output / CONFIRMED_INTERVAL_DUCKDB_NAME
            conn = duckdb.connect(str(interval))
            try:
                conn.execute(
                    f"""
                    UPDATE {CONFIRMED_INTERVAL_TABLE_NAME}
                    SET raw_duration_observations = raw_duration_observations + 10
                    """
                )
            finally:
                conn.close()
            _rewrite_manifest_hashes(output)
            with self.assertRaises(R0T10ConfirmationIntervalValidationError) as ctx2:
                validate_materialization(
                    output,
                    r0_t06_evidence=evidence,
                    nested_daily_state_duckdb=source,
                )
            self.assertIn("interval_recompute_mismatch", str(ctx2.exception))

    def test_wrapper_scripts_remain_thin(self) -> None:
        for path in (
            Path("scripts/r0/run_r0_t10_04_materialize_confirmation_intervals.py"),
            Path("scripts/r0/validate_r0_t10_04_materialization.py"),
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn("from src.r0.", text)
            self.assertIn("raise SystemExit(main())", text)
            self.assertNotIn("duckdb.connect", text)
            self.assertNotIn("SELECT ", text)


def _write_nested_source(root: Path) -> Path:
    import duckdb  # noqa: PLC0415

    path = root / "r0_t06_nested_daily_state_results.duckdb"
    rows: list[tuple[object, ...]] = []
    for security_id, pattern in {
        "000001.SZ": ("p", "p", "none", "unknown"),
        "000002.SZ": ("p", "p", "unknown"),
        "000003.SZ": ("p", "p", "p"),
        "000004.SZ": ("p_c_unknown", "p_c_unknown", "p_c_unknown"),
    }.items():
        for window in (120, 250, 500):
            for q_value in (0.10, 0.20, 0.30):
                for index, state in enumerate(pattern, start=1):
                    rows.append(_nested_row(security_id, window, q_value, index, state))
    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            f"""
            CREATE TABLE {NESTED_DAILY_TABLE_NAME} (
              security_id VARCHAR,
              trading_date VARCHAR,
              percentile_window_W INTEGER,
              q DOUBLE,
              weak_delta DOUBLE,
              P_raw BOOLEAN,
              C_raw BOOLEAN,
              T_raw BOOLEAN,
              V_raw BOOLEAN,
              S_P_raw BOOLEAN,
              S_PC_raw BOOLEAN,
              S_PCT_raw BOOLEAN,
              S_PCVT_raw BOOLEAN,
              S_P_validity_status VARCHAR,
              S_PC_validity_status VARCHAR,
              S_PCT_validity_status VARCHAR,
              S_PCVT_validity_status VARCHAR,
              S_P_reason_codes VARCHAR[],
              S_PC_reason_codes VARCHAR[],
              S_PCT_reason_codes VARCHAR[],
              S_PCVT_reason_codes VARCHAR[],
              exclusive_state_layer VARCHAR,
              eligible_state BOOLEAN,
              validity_status VARCHAR,
              reason_codes VARCHAR[],
              state_engine_version VARCHAR
            )
            """
        )
        conn.executemany(
            f"INSERT INTO {NESTED_DAILY_TABLE_NAME} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    finally:
        conn.close()
    return path


def _nested_row(
    security_id: str, window: int, q_value: float, day: int, state: str
) -> tuple[object, ...]:
    trading_date = f"2026010{day}"
    if state == "p":
        values = (True, False, False, False, True, False, False, False)
        return (
            security_id,
            trading_date,
            window,
            q_value,
            0.10,
            *values,
            "valid",
            "valid",
            "valid",
            "valid",
            ["valid_no_blocker"],
            ["valid_no_blocker"],
            ["valid_no_blocker"],
            ["valid_no_blocker"],
            "P_ONLY",
            True,
            "valid",
            ["valid_no_blocker"],
            "r0_t06_weak_dimension_nested_state.v1",
        )
    if state == "none":
        values = (False, False, False, False, False, False, False, False)
        return (
            security_id,
            trading_date,
            window,
            q_value,
            0.10,
            *values,
            "valid",
            "valid",
            "valid",
            "valid",
            ["valid_no_blocker"],
            ["valid_no_blocker"],
            ["valid_no_blocker"],
            ["valid_no_blocker"],
            "NONE",
            True,
            "valid",
            ["valid_no_blocker"],
            "r0_t06_weak_dimension_nested_state.v1",
        )
    if state == "p_c_unknown":
        values = (True, None, None, None, True, None, None, None)
        return (
            security_id,
            trading_date,
            window,
            q_value,
            0.10,
            *values,
            "valid",
            "unknown",
            "unknown",
            "unknown",
            ["valid_no_blocker"],
            ["c2_unknown"],
            ["c2_unknown"],
            ["c2_unknown"],
            "UNKNOWN",
            False,
            "unknown",
            ["c2_unknown"],
            "r0_t06_weak_dimension_nested_state.v1",
        )
    values = (None, None, None, None, None, None, None, None)
    return (
        security_id,
        trading_date,
        window,
        q_value,
        0.10,
        *values,
        "unknown",
        "unknown",
        "unknown",
        "unknown",
        ["upstream_unknown"],
        ["upstream_unknown"],
        ["upstream_unknown"],
        ["upstream_unknown"],
        "UNKNOWN",
        False,
        "unknown",
        ["upstream_unknown"],
        "r0_t06_weak_dimension_nested_state.v1",
    )


def _write_r0_t06_evidence(root: Path, source: Path) -> Path:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(source), read_only=True)
    try:
        row_count, security_count, date_min, date_max = conn.execute(
            f"""
            SELECT count(*), count(DISTINCT security_id), min(trading_date), max(trading_date)
            FROM {NESTED_DAILY_TABLE_NAME}
            """
        ).fetchone()
    finally:
        conn.close()
    evidence = root / "r0_t06_evidence.md"
    evidence.write_text(
        "\n".join(
            [
                f"`nested_daily_state_duckdb_sha256`: `{sha256_file(source)}`",
                f"`nested_daily_state_row_count`: {row_count}",
                f"`security_count`: {security_count}",
                f"`date_min`: {date_min}",
                f"`date_max`: {date_max}",
                "`R0-T07_allowed_to_start`: true",
            ]
        ),
        encoding="utf-8",
    )
    return evidence


def _rewrite_manifest_hashes(output: Path) -> None:
    manifest_path = output / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hashes"]["daily_confirmation"] = sha256_file(
        output / DAILY_CONFIRMATION_DUCKDB_NAME
    )
    manifest["output_hashes"]["confirmed_interval"] = sha256_file(
        output / CONFIRMED_INTERVAL_DUCKDB_NAME
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
