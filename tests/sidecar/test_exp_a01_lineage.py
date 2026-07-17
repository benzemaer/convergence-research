from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from argparse import Namespace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import duckdb

from scripts.sidecar.run_exp_a01_price_ma_attachment import (
    _validate_d3_t07_evidence,
    inspect_input_artifact,
    resolve_declared_input_path,
    run_formal,
    validate_expected_index_reconciliation,
    validate_formal_gate,
)
from src.sidecar.exp_a01_price_ma_attachment_validator import (
    AUTHORIZED_MANIFEST_SCHEMA,
    _inspect_independent_input_artifact,
    _validate_cross_artifact_bindings_independent,
    _validate_d3_t07_evidence_independent,
    _validate_expected_index_reconciliation_independent,
    _validate_json_schema,
    canonical_text_errors,
    load_json,
    validate_static_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_bytes(
        (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
    )


def _create_candidate(
    path: Path,
    *,
    extra_row: bool = False,
    listing_pause: bool = False,
    trade_dates: list[str] | None = None,
) -> int:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
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
        count = 4 if extra_row else 3
        trade_dates = trade_dates or [
            (date(2020, 1, 1) + timedelta(days=index)).strftime("%Y%m%d")
            for index in range(count)
        ]
        if len(trade_dates) != count:
            raise AssertionError("trade_dates must match candidate row count")
        for index in range(count):
            rows.append(
                (
                    "SEC001",
                    trade_dates[index],
                    100.0,
                    100.0,
                    "normal_trading",
                    "resolved",
                    1.0,
                    "resolved",
                    listing_pause and index == 1,
                    "D2-T20",
                    "D3-T07",
                    f"d3-t07:SEC001:{index}",
                )
            )
        connection.executemany(
            "INSERT INTO d3_candidate_daily_observation "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        return count
    finally:
        connection.close()


def _create_index(
    path: Path,
    *,
    duplicate_sequence: bool = False,
    empty_ref: bool = False,
    date_type: str = "DATE",
    date_values: list[object] | None = None,
) -> int:
    sql_date_type = {"DATE": "DATE", "VARCHAR": "VARCHAR"}[date_type]
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            f"""
            CREATE TABLE expected_price_observation_index (
              security_id VARCHAR,
              trading_date {sql_date_type},
              observation_sequence BIGINT,
              expected_observation_status VARCHAR,
              source_contract VARCHAR,
              source_ref VARCHAR
            )
            """
        )
        rows = []
        date_values = date_values or [
            (date(2020, 1, 1) + timedelta(days=index))
            if date_type == "DATE"
            else (date(2020, 1, 1) + timedelta(days=index)).strftime("%Y%m%d")
            for index in range(3)
        ]
        if len(date_values) != 3:
            raise AssertionError("date_values must contain exactly three rows")
        for index in range(3):
            sequence = 1 if duplicate_sequence and index == 2 else index
            rows.append(
                (
                    "SEC001",
                    date_values[index],
                    sequence,
                    "present",
                    "EXP_A01_EXPECTED_PRICE_OBSERVATION_INDEX_V1",
                    "" if empty_ref and index == 1 else f"calendar-v1:SEC001:{index}",
                )
            )
        connection.executemany(
            "INSERT INTO expected_price_observation_index VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        return len(rows)
    finally:
        connection.close()


def _reports(
    temp_dir: Path,
    *,
    t07_decision: str = "accepted_candidate_observation",
) -> dict[str, Path]:
    t07_quality = temp_dir / "d3_t07_quality_report.json"
    t07_handoff = temp_dir / "d3_t07_handoff_candidate_report.json"
    _write_json(
        t07_quality,
        {
            "task_id": "D3-T07",
            "source_task_id": "D2-T20",
            "candidate_observation_generated": True,
            "candidate_generation_decision": t07_decision,
            "duplicate_observation_key_count": 0,
            "null_ohlc_count": 0,
            "non_positive_price_count": 0,
            "high_low_violation_count": 0,
            "missing_effective_adj_factor_count": 0,
            "factor_interval_unresolved_count": 0,
        },
    )
    _write_json(
        t07_handoff,
        {
            "task_id": "D3-T07",
            "source_task_id": "D2-T20",
            "d3_t07_generation_decision": t07_decision,
            "d3_candidate_observation_generated": True,
            "formal_data_version_published": False,
            "labels_generated": False,
            "returns_generated": False,
            "pcvt_values_generated": False,
            "r0_state_generated": False,
        },
    )
    return {
        "d3_t07_quality_report": t07_quality,
        "d3_t07_handoff_report": t07_handoff,
    }


def _fixture(
    temp_dir: Path,
    *,
    t07_decision: str = "accepted_candidate_observation",
) -> tuple[dict[str, object], Path, dict[str, Path]]:
    config = load_json(CONFIG_PATH)
    artifacts = config["input_contract"]["artifacts"]
    candidate = temp_dir / "d3_t07_candidate_daily_observation.duckdb"
    index = temp_dir / "expected_price_observation_index.duckdb"
    candidate_count = _create_candidate(candidate)
    index_count = _create_index(index)
    report_paths = _reports(temp_dir, t07_decision=t07_decision)
    paths = {
        "d3_t07_candidate_daily_observation": candidate,
        "expected_price_observation_index": index,
        **report_paths,
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
            declaration.update(
                {
                    "table": artifact["table"],
                    "row_count": candidate_count
                    if artifact_id.startswith("d3_t07")
                    else index_count,
                    "required_columns": list(artifact["required_columns"]),
                }
            )
        declarations[artifact_id] = declaration
    manifest = temp_dir / "authorized_input_manifest.json"
    _write_json(
        manifest,
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
                "authorization_evidence": "synthetic fixture",
            },
            "input_governance": {
                "d3_t08_required": False,
                "owner_override": True,
                "override_reason": (
                    "D3-T08 is not required for the EXP-A01 four-artifact contract."
                ),
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
    return config, manifest, paths


class ExpA01LineageTest(unittest.TestCase):
    def test_config_and_manifest_text_are_canonical(self) -> None:
        config = load_json(CONFIG_PATH)
        self.assertEqual(validate_static_config(config), [])
        self.assertEqual(canonical_text_errors(CONFIG_PATH.read_bytes()), [])
        with tempfile.TemporaryDirectory() as raw:
            _config, manifest, _paths = _fixture(Path(raw))
            self.assertEqual(canonical_text_errors(manifest.read_bytes()), [])

    def test_execution_profile_rejects_out_of_range_and_mismatched_resources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = Namespace(
                allow_formal_run=True,
                reviewed_implementation_sha="a" * 40,
                config=CONFIG_PATH,
                input_manifest=None,
                input_root=root,
                output_root=root / "EXP-A01-20260716T000099Z",
                run_id="EXP-A01-20260716T000099Z",
                duckdb_threads=13,
                memory_limit="12GB",
            )
            with self.assertRaisesRegex(RuntimeError, "between 1 and 12"):
                validate_formal_gate(base)

            mismatched_threads = copy.copy(base)
            mismatched_threads.duckdb_threads = 1
            with self.assertRaisesRegex(RuntimeError, "match the governed config"):
                with patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment._current_git_sha",
                    return_value="a" * 40,
                ):
                    validate_formal_gate(mismatched_threads)

            mismatched_memory = copy.copy(base)
            mismatched_memory.duckdb_threads = 12
            mismatched_memory.memory_limit = "8GB"
            with self.assertRaisesRegex(RuntimeError, "match the governed config"):
                with patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment._current_git_sha",
                    return_value="a" * 40,
                ):
                    validate_formal_gate(mismatched_memory)

    def test_four_artifact_manifest_contract_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _config, manifest, _paths = _fixture(Path(raw))
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(
                set(payload["input_artifacts"]),
                {
                    "d3_t07_candidate_daily_observation",
                    "d3_t07_handoff_report",
                    "d3_t07_quality_report",
                    "expected_price_observation_index",
                },
            )
            self.assertEqual(
                _validate_json_schema(payload, AUTHORIZED_MANIFEST_SCHEMA, "manifest"),
                [],
            )

            extra = copy.deepcopy(payload)
            extra["input_artifacts"]["d3_t08_quality_report"] = {}
            self.assertTrue(
                _validate_json_schema(extra, AUTHORIZED_MANIFEST_SCHEMA, "manifest")
            )
            for artifact_id in (
                "d3_t07_quality_report",
                "d3_t07_handoff_report",
                "expected_price_observation_index",
            ):
                missing = copy.deepcopy(payload)
                missing["input_artifacts"].pop(artifact_id)
                self.assertTrue(
                    _validate_json_schema(
                        missing, AUTHORIZED_MANIFEST_SCHEMA, "manifest"
                    ),
                    artifact_id,
                )

    def test_runtime_does_not_open_d3_t08_artifacts(self) -> None:
        runner_text = (
            ROOT / "scripts/sidecar/run_exp_a01_price_ma_attachment.py"
        ).read_text(encoding="utf-8")
        validator_text = (
            ROOT / "src/sidecar/exp_a01_price_ma_attachment_validator.py"
        ).read_text(encoding="utf-8")
        for text in (runner_text, validator_text):
            self.assertNotIn("d3_t08_quality_report", text)
            self.assertNotIn("d3_t08_handoff_report", text)
            self.assertNotIn("_validate_d3_t08", text)

    def test_independent_cross_artifact_binding_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            _config, manifest, _paths = _fixture(temp_dir)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            _validate_cross_artifact_bindings_independent(
                payload, payload["input_artifacts"]
            )
            mutated = copy.deepcopy(payload)
            mutated["cross_artifact_bindings"]["d3_t07_candidate_sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "binding mismatch"):
                _validate_cross_artifact_bindings_independent(
                    mutated, mutated["input_artifacts"]
                )

    def test_absolute_manifest_path_resolves_without_recursive_search(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            config, manifest, paths = _fixture(temp_dir)
            artifact = config["input_contract"]["artifacts"][
                "expected_price_observation_index"
            ]
            declaration = config  # keep the assertion below tied to the fixture path
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            actual_declaration = manifest_payload["input_artifacts"][
                "expected_price_observation_index"
            ]
            resolved = resolve_declared_input_path(
                manifest, temp_dir, actual_declaration, artifact
            )
            self.assertEqual(
                resolved, paths["expected_price_observation_index"].resolve()
            )
            self.assertIsNotNone(declaration)

    def test_hash_table_row_count_and_columns_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            config, manifest, paths = _fixture(temp_dir)
            artifact = config["input_contract"]["artifacts"][
                "d3_t07_candidate_daily_observation"
            ]
            declaration = json.loads(manifest.read_text(encoding="utf-8"))[
                "input_artifacts"
            ]["d3_t07_candidate_daily_observation"]
            metadata = inspect_input_artifact(
                paths["d3_t07_candidate_daily_observation"], artifact, declaration
            )
            self.assertEqual(metadata["source_full_row_count"], 3)
            independent_metadata = _inspect_independent_input_artifact(
                paths["d3_t07_candidate_daily_observation"], artifact, declaration
            )
            self.assertEqual(independent_metadata["source_full_row_count"], 3)
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                inspect_input_artifact(
                    paths["d3_t07_candidate_daily_observation"],
                    artifact,
                    {**declaration, "sha256": "0" * 64},
                )
            with self.assertRaisesRegex(RuntimeError, "sha256 mismatch"):
                _inspect_independent_input_artifact(
                    paths["d3_t07_candidate_daily_observation"],
                    artifact,
                    {**declaration, "sha256": "0" * 64},
                )
            with self.assertRaisesRegex(RuntimeError, "row count mismatch"):
                inspect_input_artifact(
                    paths["d3_t07_candidate_daily_observation"],
                    artifact,
                    {**declaration, "row_count": 2},
                )
            with self.assertRaisesRegex(RuntimeError, "row_count mismatch"):
                _inspect_independent_input_artifact(
                    paths["d3_t07_candidate_daily_observation"],
                    artifact,
                    {**declaration, "row_count": 2},
                )
            with self.assertRaisesRegex(RuntimeError, "required columns mismatch"):
                inspect_input_artifact(
                    paths["d3_t07_candidate_daily_observation"],
                    artifact,
                    {
                        **declaration,
                        "required_columns": list(artifact["required_columns"])[1:],
                    },
                )
            with self.assertRaisesRegex(RuntimeError, "required columns"):
                _inspect_independent_input_artifact(
                    paths["d3_t07_candidate_daily_observation"],
                    artifact,
                    {
                        **declaration,
                        "required_columns": list(artifact["required_columns"])[1:],
                    },
                )
            with self.assertRaisesRegex(RuntimeError, "source_contract mismatch"):
                inspect_input_artifact(
                    paths["d3_t07_candidate_daily_observation"],
                    artifact,
                    {**declaration, "source_contract": "wrong"},
                )

    def test_expected_index_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            config, _manifest, paths = _fixture(temp_dir)
            candidate_artifact = config["input_contract"]["artifacts"][
                "d3_t07_candidate_daily_observation"
            ]
            index_artifact = config["input_contract"]["artifacts"][
                "expected_price_observation_index"
            ]
            dense = config["dense_window_contract"]
            for duplicate_sequence, empty_ref, message in (
                (True, False, "duplicate_index_security_sequence"),
                (False, True, "empty_index_source_ref"),
            ):
                mutation = temp_dir / f"mutation-{message}.duckdb"
                _create_index(
                    mutation, duplicate_sequence=duplicate_sequence, empty_ref=empty_ref
                )
                with self.assertRaisesRegex(
                    RuntimeError, "expected_index_reconcile_failed"
                ) as context:
                    validate_expected_index_reconciliation(
                        candidate_path=paths["d3_t07_candidate_observation"]
                        if "d3_t07_candidate_observation" in paths
                        else paths["d3_t07_candidate_daily_observation"],
                        candidate_artifact=candidate_artifact,
                        index_path=mutation,
                        index_artifact=index_artifact,
                        dense_contract=dense,
                    )
                self.assertIn(message, str(context.exception))

            missing_main = temp_dir / "missing-main.duckdb"
            _create_candidate(missing_main, extra_row=True)
            with self.assertRaisesRegex(
                RuntimeError, "expected_index_reconcile_failed"
            ):
                validate_expected_index_reconciliation(
                    candidate_path=missing_main,
                    candidate_artifact=candidate_artifact,
                    index_path=paths["expected_price_observation_index"],
                    index_artifact=index_artifact,
                    dense_contract=dense,
                )

            listing = temp_dir / "listing.duckdb"
            _create_candidate(listing, listing_pause=True)
            with self.assertRaisesRegex(
                RuntimeError, "expected_index_reconcile_failed"
            ):
                validate_expected_index_reconciliation(
                    candidate_path=listing,
                    candidate_artifact=candidate_artifact,
                    index_path=paths["expected_price_observation_index"],
                    index_artifact=index_artifact,
                    dense_contract=dense,
                )

    def test_d3_t07_evidence_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            config, _manifest, paths = _fixture(temp_dir)
            payloads = {
                name: load_json(path)
                for name, path in paths.items()
                if name.endswith("report")
            }
            t07_quality = payloads["d3_t07_quality_report"]
            with self.assertRaisesRegex(RuntimeError, "blocker is nonzero"):
                mutated = copy.deepcopy(t07_quality)
                mutated["null_ohlc_count"] = 1
                _validate_d3_t07_evidence(
                    candidate_path=paths["d3_t07_candidate_daily_observation"],
                    candidate_artifact=config["input_contract"]["artifacts"][
                        "d3_t07_candidate_daily_observation"
                    ],
                    quality=mutated,
                    handoff=payloads["d3_t07_handoff_report"],
                    gate=config["d3_t07_evidence_gate"],
                )

    def test_d3_t07_accepted_with_warnings_and_blocked_mutations(self) -> None:
        for decision in (
            "accepted_candidate_observation",
            "accepted_candidate_observation_with_warnings",
        ):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as raw:
                temp_dir = Path(raw)
                config, _manifest, paths = _fixture(temp_dir, t07_decision=decision)
                payloads = {
                    name: load_json(path)
                    for name, path in paths.items()
                    if name.endswith("report")
                }
                _validate_d3_t07_evidence(
                    candidate_path=paths["d3_t07_candidate_daily_observation"],
                    candidate_artifact=config["input_contract"]["artifacts"][
                        "d3_t07_candidate_daily_observation"
                    ],
                    quality=payloads["d3_t07_quality_report"],
                    handoff=payloads["d3_t07_handoff_report"],
                    gate=config["d3_t07_evidence_gate"],
                )
                _validate_d3_t07_evidence_independent(
                    candidate_path=paths["d3_t07_candidate_daily_observation"],
                    candidate_artifact=config["input_contract"]["artifacts"][
                        "d3_t07_candidate_daily_observation"
                    ],
                    quality=payloads["d3_t07_quality_report"],
                    handoff=payloads["d3_t07_handoff_report"],
                    gate=config["d3_t07_evidence_gate"],
                )

        for decision in (
            "blocked_pending_quality_resolution",
            "blocked_pending_factor_interval_resolution",
            "blocked_pending_d2_t20_handoff",
        ):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as raw:
                temp_dir = Path(raw)
                config, _manifest, paths = _fixture(temp_dir)
                payloads = {
                    name: load_json(path)
                    for name, path in paths.items()
                    if name.endswith("report")
                }
                mutated_quality = copy.deepcopy(payloads["d3_t07_quality_report"])
                mutated_handoff = copy.deepcopy(payloads["d3_t07_handoff_report"])
                mutated_quality["candidate_generation_decision"] = decision
                mutated_handoff["d3_t07_generation_decision"] = decision
                with self.assertRaisesRegex(RuntimeError, "generation decision"):
                    _validate_d3_t07_evidence(
                        candidate_path=paths["d3_t07_candidate_daily_observation"],
                        candidate_artifact=config["input_contract"]["artifacts"][
                            "d3_t07_candidate_daily_observation"
                        ],
                        quality=mutated_quality,
                        handoff=mutated_handoff,
                        gate=config["d3_t07_evidence_gate"],
                    )
                with self.assertRaisesRegex(RuntimeError, "generation decision"):
                    _validate_d3_t07_evidence_independent(
                        candidate_path=paths["d3_t07_candidate_daily_observation"],
                        candidate_artifact=config["input_contract"]["artifacts"][
                            "d3_t07_candidate_daily_observation"
                        ],
                        quality=mutated_quality,
                        handoff=mutated_handoff,
                        gate=config["d3_t07_evidence_gate"],
                    )

        for field, payload_name in (
            ("d3_candidate_observation_generated", "d3_t07_handoff_report"),
            ("candidate_observation_generated", "d3_t07_quality_report"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw:
                temp_dir = Path(raw)
                config, _manifest, paths = _fixture(temp_dir)
                payloads = {
                    name: load_json(path)
                    for name, path in paths.items()
                    if name.endswith("report")
                }
                mutated_quality = copy.deepcopy(payloads["d3_t07_quality_report"])
                mutated_handoff = copy.deepcopy(payloads["d3_t07_handoff_report"])
                if payload_name == "d3_t07_handoff_report":
                    mutated_handoff[field] = False
                else:
                    mutated_quality[field] = False
                with self.assertRaisesRegex(RuntimeError, "must be true"):
                    _validate_d3_t07_evidence(
                        candidate_path=paths["d3_t07_candidate_daily_observation"],
                        candidate_artifact=config["input_contract"]["artifacts"][
                            "d3_t07_candidate_daily_observation"
                        ],
                        quality=mutated_quality,
                        handoff=mutated_handoff,
                        gate=config["d3_t07_evidence_gate"],
                    )

        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            config, _manifest, paths = _fixture(temp_dir)
            payloads = {
                name: load_json(path)
                for name, path in paths.items()
                if name.endswith("report")
            }
            for blocker in config["d3_t07_evidence_gate"]["quality_blockers"]:
                with self.subTest(blocker=blocker):
                    mutated_quality = copy.deepcopy(payloads["d3_t07_quality_report"])
                    mutated_quality[blocker] = 1
                    with self.assertRaisesRegex(RuntimeError, "blocker is nonzero"):
                        _validate_d3_t07_evidence(
                            candidate_path=paths["d3_t07_candidate_daily_observation"],
                            candidate_artifact=config["input_contract"]["artifacts"][
                                "d3_t07_candidate_daily_observation"
                            ],
                            quality=mutated_quality,
                            handoff=payloads["d3_t07_handoff_report"],
                            gate=config["d3_t07_evidence_gate"],
                        )

    def test_reconciliation_normalizes_candidate_and_index_date_forms(self) -> None:
        for label, candidate_dates, index_type, index_dates in (
            (
                "text-yyyymmdd-date",
                ["20200101", "20200102", "20200103"],
                "DATE",
                None,
            ),
            (
                "text-iso-varchar-yyyymmdd",
                ["2020-01-01", "2020-01-02", "2020-01-03"],
                "VARCHAR",
                ["20200101", "20200102", "20200103"],
            ),
            (
                "text-yyyymmdd-varchar-iso",
                ["20200101", "20200102", "20200103"],
                "VARCHAR",
                ["2020-01-01", "2020-01-02", "2020-01-03"],
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                temp_dir = Path(raw)
                config = load_json(CONFIG_PATH)
                candidate = temp_dir / "candidate.duckdb"
                index = temp_dir / "index.duckdb"
                _create_candidate(candidate, trade_dates=candidate_dates)
                _create_index(index, date_type=index_type, date_values=index_dates)
                result = validate_expected_index_reconciliation(
                    candidate_path=candidate,
                    candidate_artifact=config["input_contract"]["artifacts"][
                        "d3_t07_candidate_daily_observation"
                    ],
                    index_path=index,
                    index_artifact=config["input_contract"]["artifacts"][
                        "expected_price_observation_index"
                    ],
                    dense_contract=config["dense_window_contract"],
                )
                independent_result = (
                    _validate_expected_index_reconciliation_independent(
                        candidate_path=candidate,
                        candidate_artifact=config["input_contract"]["artifacts"][
                            "d3_t07_candidate_daily_observation"
                        ],
                        index_path=index,
                        index_artifact=config["input_contract"]["artifacts"][
                            "expected_price_observation_index"
                        ],
                        dense_contract=config["dense_window_contract"],
                    )
                )
                self.assertEqual(result["main_key_not_present_index"], 0)
                self.assertEqual(result["present_index_key_missing_main"], 0)
                self.assertEqual(result["main_duplicate_security_date"], 0)
                self.assertEqual(independent_result["main_key_not_present_index"], 0)
                self.assertEqual(
                    independent_result["present_index_key_missing_main"], 0
                )
                self.assertEqual(independent_result["main_duplicate_security_date"], 0)

    def test_reconciliation_rejects_invalid_and_canonical_duplicate_dates(self) -> None:
        config = load_json(CONFIG_PATH)
        candidate_artifact = config["input_contract"]["artifacts"][
            "d3_t07_candidate_daily_observation"
        ]
        index_artifact = config["input_contract"]["artifacts"][
            "expected_price_observation_index"
        ]
        for label, candidate_dates, index_type, index_dates, message in (
            (
                "invalid-main-slash",
                ["2020/01/01", "20200102", "20200103"],
                "DATE",
                None,
                "invalid_main_date",
            ),
            (
                "invalid-main-calendar",
                ["20200230", "20200102", "20200103"],
                "DATE",
                None,
                "invalid_main_date",
            ),
            (
                "invalid-index-calendar",
                ["20200101", "20200102", "20200103"],
                "VARCHAR",
                ["2020-02-30", "2020-01-02", "2020-01-03"],
                "invalid_index_date",
            ),
            (
                "canonical-index-duplicate",
                ["20200101", "20200102", "20200103"],
                "VARCHAR",
                ["20200101", "2020-01-01", "20200102"],
                "duplicate_index_security_date",
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                temp_dir = Path(raw)
                candidate = temp_dir / "candidate.duckdb"
                index = temp_dir / "index.duckdb"
                _create_candidate(candidate, trade_dates=candidate_dates)
                _create_index(index, date_type=index_type, date_values=index_dates)
                with self.assertRaisesRegex(
                    RuntimeError, "expected_index_reconcile_failed"
                ) as context:
                    validate_expected_index_reconciliation(
                        candidate_path=candidate,
                        candidate_artifact=candidate_artifact,
                        index_path=index,
                        index_artifact=index_artifact,
                        dense_contract=config["dense_window_contract"],
                    )
                self.assertIn(message, str(context.exception))
                with self.assertRaisesRegex(
                    RuntimeError, "expected_index_reconcile_failed"
                ) as independent_context:
                    _validate_expected_index_reconciliation_independent(
                        candidate_path=candidate,
                        candidate_artifact=candidate_artifact,
                        index_path=index,
                        index_artifact=index_artifact,
                        dense_contract=config["dense_window_contract"],
                    )
                self.assertIn(message, str(independent_context.exception))

    def test_formal_context_wrong_sha_dirty_output_and_missing_manifest_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            output = temp_dir / "EXP-A01-20260716T000000Z"
            base = Namespace(
                allow_formal_run=True,
                reviewed_implementation_sha="0" * 40,
                config=CONFIG_PATH,
                input_manifest=temp_dir / "missing.json",
                input_root=temp_dir,
                output_root=output,
                run_id=output.name,
            )
            with self.assertRaisesRegex(
                RuntimeError, "does not equal|reviewed_implementation_sha"
            ):
                run_formal(base)

            config, manifest, _paths = _fixture(temp_dir)
            clean_args = Namespace(
                allow_formal_run=True,
                reviewed_implementation_sha="a" * 40,
                config=CONFIG_PATH,
                input_manifest=manifest,
                input_root=temp_dir,
                output_root=output,
                run_id=output.name,
            )
            with (
                patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment._current_git_sha",
                    return_value="a" * 40,
                ),
                patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment.subprocess.run",
                    return_value=SimpleNamespace(stdout=" M dirty", returncode=0),
                ),
                patch(
                    "scripts.sidecar.run_exp_a01_price_ma_attachment._validate_committed_source_bindings",
                    return_value={},
                ),
                self.assertRaisesRegex(RuntimeError, "clean worktree"),
            ):
                validate_formal_gate(clean_args)
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
                    return_value={},
                ),
            ):
                result = validate_formal_gate(clean_args)
            self.assertEqual(result["formal_run_executed"], False)
            output.mkdir()
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
                    return_value={},
                ),
                self.assertRaisesRegex(RuntimeError, "output directory"),
            ):
                validate_formal_gate(clean_args)

            missing_manifest_args = copy.copy(clean_args)
            missing_manifest_args.output_root = temp_dir / "EXP-A01-20260716T000001Z"
            missing_manifest_args.run_id = missing_manifest_args.output_root.name
            missing_manifest_args.input_manifest = temp_dir / "does-not-exist.json"
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
                    return_value={},
                ),
                self.assertRaisesRegex(RuntimeError, "not a file"),
            ):
                validate_formal_gate(missing_manifest_args)
            self.assertTrue(config)

    def test_missing_expected_index_and_actual_required_column_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            config, manifest, paths = _fixture(temp_dir)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            del payload["input_artifacts"]["expected_price_observation_index"]
            missing = temp_dir / "missing-index-manifest.json"
            _write_json(missing, payload)
            args = Namespace(
                allow_formal_run=True,
                reviewed_implementation_sha="a" * 40,
                config=CONFIG_PATH,
                input_manifest=missing,
                input_root=temp_dir,
                output_root=temp_dir / "EXP-A01-20260716T000002Z",
                run_id="EXP-A01-20260716T000002Z",
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
                    return_value={},
                ),
                self.assertRaisesRegex(
                    RuntimeError, "authorized input manifest schema validation failed"
                ),
            ):
                validate_formal_gate(args)

            bad_dir = temp_dir / "bad-candidate"
            bad_dir.mkdir()
            bad_candidate = bad_dir / "d3_t07_candidate_daily_observation.duckdb"
            connection = duckdb.connect(str(bad_candidate))
            try:
                connection.execute(
                    "CREATE TABLE d3_candidate_daily_observation (ts_code VARCHAR)"
                )
            finally:
                connection.close()
            artifact = config["input_contract"]["artifacts"][
                "d3_t07_candidate_daily_observation"
            ]
            declaration = payload["input_artifacts"][
                "d3_t07_candidate_daily_observation"
            ]
            declaration = {
                **declaration,
                "path": str(bad_candidate),
                "sha256": _sha(bad_candidate),
                "row_count": 0,
            }
            with self.assertRaisesRegex(RuntimeError, "required columns are missing"):
                inspect_input_artifact(bad_candidate, artifact, declaration)

    def test_formal_runner_never_creates_output_without_authorization(self) -> None:
        output_dir = ROOT / "data/generated/sidecar/exp_a01/test-no-formal-output"
        if output_dir.exists():
            raise AssertionError(f"unexpected test output exists: {output_dir}")
        args = Namespace(
            allow_formal_run=False,
            reviewed_implementation_sha="",
            config=CONFIG_PATH,
            input_manifest=None,
            input_root=None,
            output_root=output_dir,
            run_id=output_dir.name,
        )
        with self.assertRaisesRegex(RuntimeError, "formal_run_not_allowed"):
            run_formal(args)
        self.assertFalse(output_dir.exists())

    def test_no_formal_output_directory_and_no_duckdb_import_in_core(self) -> None:
        self.assertFalse((ROOT / "data/generated/sidecar/exp_a01").exists())
        core_text = (ROOT / "src/sidecar/exp_a01_price_ma_attachment.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import duckdb", core_text)


if __name__ == "__main__":
    unittest.main()
