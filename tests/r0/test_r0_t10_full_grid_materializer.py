from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.r0.r0_t10_authorized_input_manifest_builder import (
    AUTHORIZED_MANIFEST_NAME,
    R0T10AuthorizedInputManifestError,
    build_authorized_input_manifest,
)
from src.r0.r0_t10_full_grid_materializer import (
    GLOBAL_MANIFEST_NAME,
    R0T10FullGridMaterializationError,
    materialize_full_grid,
)
from src.r0.r0_t10_full_grid_validator import (
    R0T10FullGridValidationError,
    validate_full_grid,
)
from src.r0.upstream_artifact_io import sha256_file

FULL_SHA = "4f50d1d8d343b4b35fbb21c97d3a7a03b8c80292"


class R0T10FullGridMaterializerTest(unittest.TestCase):
    def test_authorized_manifest_and_full_grid_pass_on_small_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = _write_upstream_artifacts(root, include_interval=True)
            evidence = _write_evidence_set(root, artifacts)
            manifest_summary = build_authorized_input_manifest(
                output_dir=root / "manifest",
                run_id="R0-T10-05-test",
                code_commit=FULL_SHA,
                r0_t04_evidence=evidence["t04"],
                r0_t05_evidence=evidence["t05"],
                r0_t06_evidence=evidence["t06"],
                r0_t07_evidence=evidence["t07"],
            )
            manifest_path = Path(manifest_summary["authorized_input_manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["authorized_r0_input"])
            self.assertFalse(manifest["row_payload_embedded"])
            self.assertEqual(manifest["grid"]["selected_config_count"], 27)
            self.assertEqual(
                manifest["coverage"]["indicator_coverage"],
                ["P1_NATR14", "P2_LogRange20"],
            )
            self.assertIn(
                "R0_W250_Q20_K3_WEAK_D010", manifest["grid"]["selected_config_ids"]
            )

            summary = materialize_full_grid(
                authorized_input_manifest=manifest_path,
                output_dir=root / "full_grid",
                run_id="R0-T10-05-test",
                code_commit=FULL_SHA,
                max_workers=16,
                duckdb_threads=1,
                duckdb_memory_limit_per_worker="1GB",
                resume=True,
            )
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["completed_config_count"], 27)
            self.assertEqual(summary["FAILED_marker_count"], 0)
            global_manifest = json.loads(
                (root / "full_grid" / GLOBAL_MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                global_manifest["concurrency_policy"]["process_pool_context"], "spawn"
            )
            self.assertFalse(
                global_manifest["concurrency_policy"]["monolithic_json_payload_mode"]
            )

            result = validate_full_grid(
                authorized_input_manifest=manifest_path,
                output_dir=root / "full_grid",
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["selected_config_count"], 27)
            self.assertEqual(result["full_code_commit_check"], "passed")
            self.assertEqual(result["source_evidence_check"], "passed")
            self.assertEqual(result["input_artifact_hash_check"], "passed")
            self.assertEqual(result["synthetic_input_check"], "passed")
            self.assertEqual(result["raw_external_source_check"], "passed")

            resume_summary = materialize_full_grid(
                authorized_input_manifest=manifest_path,
                output_dir=root / "full_grid",
                run_id="R0-T10-05-test",
                code_commit=FULL_SHA,
                max_workers=2,
                resume=True,
            )
            self.assertEqual(resume_summary["skipped_config_count"], 27)

    def test_short_sha_and_excess_workers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = _write_upstream_artifacts(root, include_interval=False)
            evidence = _write_evidence_set(root, artifacts)
            with self.assertRaises(R0T10AuthorizedInputManifestError) as ctx:
                build_authorized_input_manifest(
                    output_dir=root / "manifest",
                    run_id="short",
                    code_commit="4f50d1d",
                    r0_t04_evidence=evidence["t04"],
                    r0_t05_evidence=evidence["t05"],
                    r0_t06_evidence=evidence["t06"],
                    r0_t07_evidence=evidence["t07"],
                )
            self.assertIn("short_code_commit_forbidden", str(ctx.exception))

            manifest_summary = build_authorized_input_manifest(
                output_dir=root / "manifest2",
                run_id="workers",
                code_commit=FULL_SHA,
                r0_t04_evidence=evidence["t04"],
                r0_t05_evidence=evidence["t05"],
                r0_t06_evidence=evidence["t06"],
                r0_t07_evidence=evidence["t07"],
            )
            with self.assertRaises(R0T10FullGridMaterializationError):
                materialize_full_grid(
                    authorized_input_manifest=manifest_summary[
                        "authorized_input_manifest_path"
                    ],
                    output_dir=root / "out",
                    run_id="workers",
                    code_commit=FULL_SHA,
                    max_workers=17,
                )

    def test_missing_hash_mismatch_and_synthetic_payload_block_authorization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = _write_upstream_artifacts(root, include_interval=False)
            evidence = _write_evidence_set(root, artifacts)
            with evidence["t04"].open("a", encoding="utf-8") as handle:
                handle.write("\n`status`: passed\n")
            Path(artifacts["t04"]).write_text("tamper", encoding="utf-8")
            summary = build_authorized_input_manifest(
                output_dir=root / "blocked",
                run_id="blocked",
                code_commit=FULL_SHA,
                r0_t04_evidence=evidence["t04"],
                r0_t05_evidence=evidence["t05"],
                r0_t06_evidence=evidence["t06"],
                r0_t07_evidence=evidence["t07"],
            )
            self.assertEqual(summary["status"], "blocked")
            self.assertFalse((root / "blocked" / AUTHORIZED_MANIFEST_NAME).exists())
            self.assertIn(
                "r0_t04_raw_metric_artifact_hash_mismatch", summary["reason_codes"]
            )

    def test_zero_interval_is_legal_only_when_daily_confirmed_true_is_zero(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = _write_upstream_artifacts(root, include_interval=False)
            evidence = _write_evidence_set(root, artifacts)
            manifest_summary = build_authorized_input_manifest(
                output_dir=root / "manifest",
                run_id="zero",
                code_commit=FULL_SHA,
                r0_t04_evidence=evidence["t04"],
                r0_t05_evidence=evidence["t05"],
                r0_t06_evidence=evidence["t06"],
                r0_t07_evidence=evidence["t07"],
            )
            materialize_full_grid(
                authorized_input_manifest=manifest_summary[
                    "authorized_input_manifest_path"
                ],
                output_dir=root / "full_grid",
                run_id="zero",
                code_commit=FULL_SHA,
                max_workers=1,
            )
            result = validate_full_grid(
                authorized_input_manifest=manifest_summary[
                    "authorized_input_manifest_path"
                ],
                output_dir=root / "full_grid",
            )
            self.assertEqual(
                result["zero_interval_reason_if_any"],
                "no_confirmed_segments_in_r0_t07_input",
            )

            import duckdb  # noqa: PLC0415

            daily = (
                root
                / "full_grid"
                / "configs"
                / "R0_W120_Q10_K2_WEAK_D010"
                / "candidate_daily_state.duckdb"
            )
            conn = duckdb.connect(str(daily))
            try:
                conn.execute(
                    """
                    UPDATE candidate_daily_state
                    SET confirmed_state = true
                    WHERE security_id = '000001.SZ' AND state_name = 'S_P'
                    """
                )
            finally:
                conn.close()
            done = (
                root
                / "full_grid"
                / "configs"
                / "R0_W120_Q10_K2_WEAK_D010"
                / "DONE.json"
            )
            marker = json.loads(done.read_text(encoding="utf-8"))
            marker["daily_duckdb_hash"] = sha256_file(daily)
            done.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
            with self.assertRaises(R0T10FullGridValidationError) as ctx:
                validate_full_grid(
                    authorized_input_manifest=manifest_summary[
                        "authorized_input_manifest_path"
                    ],
                    output_dir=root / "full_grid",
                )
            self.assertIn("daily_confirmed_true_without_interval", str(ctx.exception))

    def test_validator_rechecks_authorized_manifest_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, output_dir = _completed_small_full_grid(root)

            cases = (
                (
                    "source_evidence_hash_mismatch",
                    lambda manifest: manifest["source_evidence"]["R0-T04"].update(
                        {"sha256": "0" * 64}
                    ),
                    "source_evidence_hash_mismatch:R0-T04",
                ),
                (
                    "source_evidence_file_missing",
                    lambda manifest: manifest["source_evidence"]["R0-T05"].update(
                        {"path": str(root / "missing_evidence.md")}
                    ),
                    "source_evidence_file_missing:R0-T05",
                ),
                (
                    "input_artifact_hash_mismatch",
                    lambda manifest: manifest["input_artifacts"][
                        "r0_t07_daily_confirmation"
                    ].update({"sha256": "1" * 64}),
                    "input_artifact_hash_mismatch:r0_t07_daily_confirmation",
                ),
                (
                    "synthetic_marker",
                    lambda manifest: manifest.update(
                        {"production_marker": "synthetic_contract-grid"}
                    ),
                    "synthetic_contract_grid_marker_forbidden",
                ),
                (
                    "raw_external_lineage",
                    lambda manifest: manifest.update(
                        {"lineage_probe": "data/raw/MarketDB/foo.day"}
                    ),
                    "raw_external",
                ),
            )
            for name, mutate, expected in cases:
                case_manifest = root / f"{name}.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest)
                _write_json(case_manifest, manifest)
                with self.subTest(name=name):
                    with self.assertRaises(R0T10FullGridValidationError) as ctx:
                        validate_full_grid(
                            authorized_input_manifest=case_manifest,
                            output_dir=output_dir,
                        )
                    self.assertIn(expected, str(ctx.exception))

    def test_wrappers_remain_thin(self) -> None:
        for path in (
            Path("scripts/r0/build_r0_t10_05_authorized_input_manifest.py"),
            Path("scripts/r0/run_r0_t10_05_full_grid.py"),
            Path("scripts/r0/validate_r0_t10_05_full_grid.py"),
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn("from src.r0.", text)
            self.assertIn("raise SystemExit(main())", text)
            self.assertNotIn("duckdb.connect", text)
            self.assertNotIn("SELECT ", text)


def _write_upstream_artifacts(root: Path, *, include_interval: bool) -> dict[str, str]:
    import duckdb  # noqa: PLC0415

    artifacts: dict[str, str] = {}
    for name, table in {
        "t04": "r0_t04_raw_metric_results",
        "t05i": "r0_t05_indicator_score_results",
        "t05d": "r0_t05_dimension_score_results",
        "t05c": "r0_t05_common_eligible_sample_results",
        "t06i": "r0_t06_indicator_state_results",
        "t06d": "r0_t06_dimension_state_results",
        "t06n": "r0_t06_nested_daily_state_results",
    }.items():
        path = root / f"{name}.duckdb"
        conn = duckdb.connect(str(path))
        try:
            conn.execute(
                f"""
                CREATE TABLE {table} AS
                SELECT '000001.SZ' AS security_id, '20260101' AS trading_date
                """
            )
        finally:
            conn.close()
        artifacts[name] = str(path)

    daily = root / "t07daily.duckdb"
    conn = duckdb.connect(str(daily))
    try:
        rows = []
        for w in (120, 250, 500):
            for q in (0.10, 0.20, 0.30):
                for k in (2, 3, 5):
                    for state in ("S_P", "S_PC", "S_PCT", "S_PCVT"):
                        confirmed = (
                            include_interval
                            and w == 120
                            and q == 0.10
                            and k == 2
                            and state == "S_P"
                        )
                        rows.append(
                            (
                                "000001.SZ",
                                "20260101",
                                w,
                                q,
                                0.10,
                                state,
                                k,
                                confirmed,
                                2 if confirmed else 0,
                                confirmed,
                                "valid",
                            )
                        )
        conn.execute(
            """
            CREATE TABLE r0_t07_daily_confirmation_results(
              security_id TEXT, trading_date TEXT, percentile_window_W INTEGER,
              q DOUBLE, weak_delta DOUBLE, state_name TEXT, confirmation_k INTEGER,
              raw_state BOOLEAN, raw_streak INTEGER, confirmed_state BOOLEAN,
              validity_status TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO r0_t07_daily_confirmation_results
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        for ddl in (
            "ADD COLUMN raw_streak_start_date TEXT",
            "ADD COLUMN confirmation_start_date TEXT",
            "ADD COLUMN confirmation_date TEXT",
            "ADD COLUMN reason_codes TEXT DEFAULT '[]'",
            "ADD COLUMN confirmation_engine_version TEXT DEFAULT 'test'",
        ):
            conn.execute(f"ALTER TABLE r0_t07_daily_confirmation_results {ddl}")
    finally:
        conn.close()
    artifacts["t07daily"] = str(daily)

    interval = root / "t07interval.duckdb"
    conn = duckdb.connect(str(interval))
    try:
        conn.execute(
            """
            CREATE TABLE r0_t07_confirmed_interval_results(
              interval_id TEXT, security_id TEXT, percentile_window_W INTEGER,
              q DOUBLE, weak_delta DOUBLE, state_name TEXT, confirmation_k INTEGER,
              raw_start_date TEXT, confirmation_date TEXT, confirmed_start_date TEXT,
              interval_end_date TEXT, last_observed_date TEXT,
              raw_duration_observations INTEGER,
              confirmed_duration_observations INTEGER,
              is_open_interval BOOLEAN, termination_reason TEXT,
              validity_status TEXT, reason_codes TEXT,
              confirmation_engine_version TEXT
            )
            """
        )
        if include_interval:
            conn.execute(
                """
                INSERT INTO r0_t07_confirmed_interval_results
                VALUES ('i1','000001.SZ',120,0.10,0.10,'S_P',2,'20260101',
                '20260101','20260101',NULL,'20260101',2,1,true,NULL,'valid','[]','test')
                """
            )
    finally:
        conn.close()
    artifacts["t07interval"] = str(interval)
    return artifacts


def _completed_small_full_grid(root: Path) -> tuple[Path, Path]:
    artifacts = _write_upstream_artifacts(root, include_interval=True)
    evidence = _write_evidence_set(root, artifacts)
    manifest_summary = build_authorized_input_manifest(
        output_dir=root / "manifest",
        run_id="lineage",
        code_commit=FULL_SHA,
        r0_t04_evidence=evidence["t04"],
        r0_t05_evidence=evidence["t05"],
        r0_t06_evidence=evidence["t06"],
        r0_t07_evidence=evidence["t07"],
    )
    manifest_path = Path(manifest_summary["authorized_input_manifest_path"])
    output_dir = root / "full_grid"
    materialize_full_grid(
        authorized_input_manifest=manifest_path,
        output_dir=output_dir,
        run_id="lineage",
        code_commit=FULL_SHA,
        max_workers=1,
    )
    validate_full_grid(
        authorized_input_manifest=manifest_path,
        output_dir=output_dir,
    )
    return manifest_path, output_dir


def _write_evidence_set(root: Path, artifacts: dict[str, str]) -> dict[str, Path]:
    paths = {
        "t04": root / "t04_evidence.md",
        "t05": root / "t05_evidence.md",
        "t06": root / "t06_evidence.md",
        "t07": root / "t07_evidence.md",
    }
    paths["t04"].write_text(
        _lines(
            task_id="R0-T10-01",
            gate="R0-T05_allowed_to_start",
            code_commit=FULL_SHA,
            output_duckdb=artifacts["t04"],
            output_duckdb_sha256=sha256_file(artifacts["t04"]),
            row_count="1",
        ),
        encoding="utf-8",
    )
    paths["t05"].write_text(
        _lines(
            task_id="R0-T10-02",
            gate="R0-T06_allowed_to_start",
            code_commit=FULL_SHA,
            indicator_score_duckdb=artifacts["t05i"],
            indicator_score_duckdb_sha256=sha256_file(artifacts["t05i"]),
            dimension_score_duckdb=artifacts["t05d"],
            dimension_score_duckdb_sha256=sha256_file(artifacts["t05d"]),
            common_eligible_duckdb=artifacts["t05c"],
            common_eligible_duckdb_sha256=sha256_file(artifacts["t05c"]),
            indicator_score_row_count="1",
            dimension_score_row_count="1",
            common_eligible_row_count="1",
        ),
        encoding="utf-8",
    )
    paths["t06"].write_text(
        _lines(
            task_id="R0-T10-03",
            gate="R0-T07_allowed_to_start",
            run_code_commit_argument="92dccee",
            pr_head_commit=FULL_SHA,
            indicator_state_duckdb_path=artifacts["t06i"],
            indicator_state_duckdb_sha256=sha256_file(artifacts["t06i"]),
            dimension_state_duckdb_path=artifacts["t06d"],
            dimension_state_duckdb_sha256=sha256_file(artifacts["t06d"]),
            nested_daily_state_duckdb_path=artifacts["t06n"],
            nested_daily_state_duckdb_sha256=sha256_file(artifacts["t06n"]),
            indicator_state_row_count="1",
            dimension_state_row_count="1",
            nested_daily_state_row_count="1",
        ),
        encoding="utf-8",
    )
    paths["t07"].write_text(
        _lines(
            task_id="R0-T10-04",
            gate="R0-T10-05_allowed_to_start",
            code_commit=FULL_SHA,
            daily_confirmation_duckdb_path=artifacts["t07daily"],
            daily_confirmation_duckdb_sha256=sha256_file(artifacts["t07daily"]),
            confirmed_interval_duckdb_path=artifacts["t07interval"],
            confirmed_interval_duckdb_sha256=sha256_file(artifacts["t07interval"]),
            daily_confirmation_row_count="108",
            confirmed_interval_row_count="1",
        ),
        encoding="utf-8",
    )
    return paths


def _lines(task_id: str, gate: str, **fields: str) -> str:
    base = {
        "task_id": task_id,
        "status": "completed",
        "validator_status": "passed",
        "security_count": "1",
        "date_min": "20260101",
        "date_max": "20260101",
        "indicator_coverage": "`P1_NATR14`, `P2_LogRange20`",
        gate: "true",
    }
    base.update(fields)
    lines = []
    for key, value in base.items():
        if "`" in value:
            lines.append(f"`{key}`: {value}")
        else:
            lines.append(f"`{key}`: `{value}`")
    return "\n".join(lines)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
