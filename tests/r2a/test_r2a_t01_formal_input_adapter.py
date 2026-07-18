from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest

import src.r2a.r2a_t01_score_release as score_release_module
from src.r2a.r2a_t01_artifact_manifest import build_manifest, write_schema
from src.r2a.r2a_t01_formal_input_adapter import (
    FORMAL_INPUT_ORDER,
    FormalInputAdapter,
    FormalInputError,
    inspect_relation,
)
from src.r2a.r2a_t01_input_manifest import sha256_file, write_json_atomic
from src.r2a.r2a_t01_score_release import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_POLICY_PATH,
    ScoreReleaseError,
    _load_json,
    _materialize_staged_release,
    _stage_formal_inputs,
    _validate_staging,
    compute_score_release_id,
)
from src.r2a.r2a_t01_validator import validate_score_release
from tests.r2a._fixtures import synthetic_inputs


def _formal_fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    synthetic_manifest, json_paths = synthetic_inputs(tmp_path / "json-inputs")
    del synthetic_manifest
    database_paths: dict[str, Path] = {}
    entries: dict[str, dict[str, Any]] = {}
    database = tmp_path / "formal-inputs" / "accepted_sources.duckdb"
    database.parent.mkdir(parents=True, exist_ok=True)
    for name in FORMAL_INPUT_ORDER:
        rows = json.loads(json_paths[name].read_text(encoding="utf-8"))
        logical_table = f"bound_{name}"
        if name == "pcvt_component_scores":
            real_rows = []
            for row in rows:
                base = {
                    key: value
                    for key, value in row.items()
                    if key
                    not in {
                        "observation_sequence",
                        "dimension_id",
                        "component_id",
                        "source_run_id",
                    }
                }
                base["indicator_id"] = row["component_id"]
                for window in (120, 250, 500):
                    real_rows.append(dict(base, percentile_window_W=window))
            rows = real_rows
        elif name == "pcvt_dimension_scores":
            real_rows = []
            for row in rows:
                base = {
                    key: value
                    for key, value in row.items()
                    if key not in {"observation_sequence", "dimension_id"}
                }
                base["dimension"] = row["dimension_id"]
                for window in (120, 250, 500):
                    real_rows.append(dict(base, percentile_window_W=window))
            rows = real_rows
        elif name == "a_raw_observations":
            real_rows = []
            for row in rows:
                base = {
                    key: value
                    for key, value in row.items()
                    if key not in {"component_id", "reason_codes", "source_run_id"}
                }
                base.update(
                    indicator_id=row["component_id"],
                    reason_codes_json=json.dumps(row["reason_codes"]),
                    run_id=row["source_run_id"],
                )
                real_rows.append(base)
                if row["component_id"].startswith("A2_"):
                    real_rows.append(
                        dict(base, indicator_id="A2b_BodyToMACloudGapMean20_5_60")
                    )
            rows = real_rows
        elif name == "pcvt_validation_raw":
            real_rows = []
            for row in rows:
                indicator = (
                    "V2_LogAmount20_base"
                    if row["component_id"] == "V2_AmountLevel20Pct"
                    else row["component_id"]
                )
                base = {
                    key: value
                    for key, value in row.items()
                    if key
                    not in {"observation_sequence", "dimension_id", "component_id"}
                }
                real_rows.append(dict(base, indicator_id=indicator))
            rows = real_rows
        with duckdb.connect(str(database)) as connection:
            connection.register("fixture_rows", pa.Table.from_pylist(rows))
            connection.execute(
                f'CREATE TABLE "{logical_table}" AS SELECT * FROM fixture_rows'
            )
            connection.unregister("fixture_rows")
            connection.execute("CHECKPOINT")
        database_paths[name] = database
    for name in FORMAL_INPUT_ORDER:
        entries[name] = _entry_for(name, database, f"bound_{name}")
    manifest = tmp_path / "formal-inputs" / "authorized_input_manifest.local.json"
    write_json_atomic(
        manifest,
        {
            "manifest_version": "r2a_t01_authorized_input_manifest.v1",
            "manifest_type": "r2a_t01_formal_authorized_input",
            "run_id": "R2A-T01-FORMAL-LIKE-TEST",
            "synthetic_only": False,
            "created_at": "2026-07-18T00:00:00Z",
            "source_commit": "0" * 40,
            "formal_authorization_id": "FORMAL-LIKE-LOCAL-TEST-ONLY",
            "universe_id": "CSI800_FROZEN_TEST",
            "inputs": entries,
        },
    )
    return manifest, database_paths


def _entry_for(name: str, database: Path, logical_table: str) -> dict[str, Any]:
    with duckdb.connect() as connection:
        quoted = str(database).replace("'", "''")
        connection.execute(f"ATTACH '{quoted}' AS exact_source (READ_ONLY)")
        metadata = inspect_relation(connection, "exact_source", logical_table, name)
    return {
        "actual_path": str(database.resolve()),
        "sha256": sha256_file(database),
        "byte_size": database.stat().st_size,
        "logical_table_name": logical_table,
        **metadata,
        "source_artifact_id": f"accepted-test-artifact:{name}",
        "source_manifest_sha256": "a" * 64,
        "source_acceptance_status": "accepted",
        "source_run_id": f"accepted-run:{name}",
        "source_contract_id": f"accepted-contract:{name}",
        "input_role": "validation_only"
        if name == "pcvt_validation_raw"
        else "materialization",
    }


def _refresh_entry(manifest_path: Path, name: str) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed_path = Path(payload["inputs"][name]["actual_path"]).resolve()
    for input_name, previous in list(payload["inputs"].items()):
        if Path(previous["actual_path"]).resolve() != changed_path:
            continue
        refreshed = _entry_for(input_name, changed_path, previous["logical_table_name"])
        refreshed["source_run_id"] = previous["source_run_id"]
        refreshed["source_contract_id"] = previous["source_contract_id"]
        payload["inputs"][input_name] = refreshed
    write_json_atomic(manifest_path, payload)


def _build_formal_like_package(
    tmp_path: Path,
    manifest_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> Path:
    package = tmp_path / "formal-like-package"
    package.mkdir()
    staging = package / "staging.duckdb"
    adapter = FormalInputAdapter(manifest_path)
    if monkeypatch is not None:
        monkeypatch.setattr(
            score_release_module,
            "load_bound_inputs",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("formal path called JSON-array loader")
            ),
        )
    summary = _stage_formal_inputs(adapter, staging)
    _validate_staging(staging)
    config = _load_json(DEFAULT_CONFIG_PATH)
    input_manifest = _load_json(manifest_path)
    release_id, preimage_hash = compute_score_release_id(
        config=config,
        availability_policy_path=DEFAULT_POLICY_PATH,
        input_manifest=input_manifest,
    )
    shards = package / "a_score_shards"
    _materialize_staged_release(
        staging_path=staging,
        database_path=package / "score_data.duckdb",
        shard_dir=shards,
        score_release_id=release_id,
        worker_count=2,
    )
    staging.unlink()
    shutil.rmtree(shards)
    write_schema(package / "schema.json")
    build_manifest(
        package_dir=package,
        run_id="R2A-T01-FORMAL-LIKE-TEST",
        score_release_id=release_id,
        score_release_preimage_sha256=preimage_hash,
        authorized_input_manifest=manifest_path,
        input_summary=summary,
        formal_authorization_id=adapter.authorization_id,
        config_path=DEFAULT_CONFIG_PATH,
        availability_policy_path=DEFAULT_POLICY_PATH,
        worker_count=2,
        synthetic_only=False,
        execution_commit=None,
    )
    return package


def test_formal_adapter_attaches_exact_tables_and_depathizes_summary(
    tmp_path: Path,
) -> None:
    manifest, _ = _formal_fixture(tmp_path)
    adapter = FormalInputAdapter(manifest)
    with duckdb.connect() as connection:
        relations = adapter.attach_and_validate(connection)
        assert tuple(relations) == FORMAL_INPUT_ORDER
        assert all("READ_ONLY" not in relation for relation in relations.values())
    summary = adapter.depathized_summary()
    assert all("actual_path" not in entry for entry in summary.values())
    assert summary["pcvt_validation_raw"]["input_role"] == "validation_only"


def test_formal_projection_matches_real_contract_shapes(tmp_path: Path) -> None:
    manifest, databases = _formal_fixture(tmp_path)
    assert len({path.resolve() for path in databases.values()}) == 1
    source = next(iter(databases.values()))
    with duckdb.connect(str(source), read_only=True) as connection:
        component_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('bound_pcvt_component_scores')"
            ).fetchall()
        }
        dimension_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('bound_pcvt_dimension_scores')"
            ).fetchall()
        }
        a_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('bound_a_raw_observations')"
            ).fetchall()
        }
        assert {"indicator_id", "percentile_window_W"} <= component_columns
        assert (
            not {"component_id", "dimension_id", "observation_sequence"}
            & component_columns
        )
        assert (
            "dimension" in dimension_columns
            and "observation_sequence" not in dimension_columns
        )
        assert {"indicator_id", "reason_codes_json", "run_id"} <= a_columns
    staging = tmp_path / "projection.duckdb"
    _stage_formal_inputs(FormalInputAdapter(manifest), staging)
    with duckdb.connect(str(staging), read_only=True) as connection:
        assert connection.execute(
            "SELECT list(DISTINCT percentile_window_W) FROM stage_pcvt_component_scores"
        ).fetchone()[0] == [120]
        assert (
            connection.execute(
                "SELECT count(*) FROM stage_a_raw_observations "
                "WHERE component_id LIKE 'A2b%'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM stage_pcvt_validation_raw "
                "WHERE component_id='V2_AmountLevel20Pct'"
            ).fetchone()[0]
            > 0
        )
        assert connection.execute(
            "SELECT min(observation_sequence),max(observation_sequence) "
            "FROM stage_security_observation_spine"
        ).fetchone() == (0, 122)
        reference_types = dict(
            connection.execute(
                "SELECT column_name,data_type FROM information_schema.columns "
                "WHERE table_name='stage_pcvt_component_scores'"
            ).fetchall()
        )
        assert reference_types["reference_window_start"] == "DATE"
        assert reference_types["reference_window_end"] == "DATE"


def test_formal_like_path_is_bounded_and_never_uses_json_array_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, _ = _formal_fixture(tmp_path)
    package = _build_formal_like_package(tmp_path, manifest, monkeypatch=monkeypatch)
    receipt = validate_score_release(
        package, authorized_input_manifest=manifest, formal=True
    )
    assert receipt["status"] == "failed"
    assert receipt["reason_codes"] == [
        "formal_calendar_year_domain",
        "formal_security_count_800",
    ]
    source = Path(score_release_module.__file__).read_text(encoding="utf-8")
    assert ".executemany(" not in source
    assert "ProcessPoolExecutor" in source
    assert "write_table" in source
    assert not list(package.rglob("*.parquet"))


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("wrong_table", "logical_table_missing:pcvt_component_scores"),
        ("declared_row_count", "row_count_mismatch:pcvt_component_scores"),
        ("declared_security_count", "security_count_mismatch:pcvt_component_scores"),
        ("declared_date_coverage", "date_min_mismatch:pcvt_component_scores"),
    ],
)
def test_formal_adapter_declared_metadata_mismatches_fail_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    manifest, _ = _formal_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entry = payload["inputs"]["pcvt_component_scores"]
    if mutation == "wrong_table":
        entry["logical_table_name"] = "not_the_bound_table"
    elif mutation == "declared_row_count":
        entry["row_count"] += 1
    elif mutation == "declared_security_count":
        entry["security_count"] += 1
    else:
        entry["date_min"] = "1999-01-01"
    write_json_atomic(manifest, payload)
    with duckdb.connect() as connection:
        with pytest.raises(FormalInputError, match=expected):
            FormalInputAdapter(manifest).attach_and_validate(connection)


def test_formal_adapter_rejects_truncated_file(tmp_path: Path) -> None:
    manifest, databases = _formal_fixture(tmp_path)
    database = databases["pcvt_component_scores"]
    with database.open("r+b") as handle:
        handle.truncate(max(1, database.stat().st_size // 2))
    with duckdb.connect() as connection:
        with pytest.raises(FormalInputError, match="input_byte_size_mismatch"):
            FormalInputAdapter(manifest).attach_and_validate(connection)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("extra_key", "extra_or_invalid_source_key:pcvt_component_scores"),
        ("missing_key", "present_source_row_missing:pcvt_component_scores"),
    ],
)
def test_formal_source_extra_or_missing_key_fails_closed(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    manifest, databases = _formal_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    table = payload["inputs"]["pcvt_component_scores"]["logical_table_name"]
    with duckdb.connect(str(databases["pcvt_component_scores"])) as connection:
        if mutation == "extra_key":
            connection.execute(
                f"UPDATE \"{table}\" SET security_id='EXTRA.SECURITY' WHERE rowid="
                f'(SELECT min(rowid) FROM "{table}")'
            )
        else:
            connection.execute(
                f'DELETE FROM "{table}" WHERE rowid=(SELECT min(rowid) FROM "{table}")'
            )
        connection.execute("CHECKPOINT")
    _refresh_entry(manifest, "pcvt_component_scores")
    staging = tmp_path / "staging.duckdb"
    with pytest.raises(ScoreReleaseError, match=expected):
        _stage_formal_inputs(FormalInputAdapter(manifest), staging)
        _validate_staging(staging)


def test_swapped_source_table_fails_closed(tmp_path: Path) -> None:
    manifest, _ = _formal_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["inputs"]["pcvt_component_scores"] = dict(
        payload["inputs"]["pcvt_validation_raw"], input_role="materialization"
    )
    write_json_atomic(manifest, payload)
    staging = tmp_path / "swapped.duckdb"
    with pytest.raises(Exception, match="percentile_window_W"):
        _stage_formal_inputs(FormalInputAdapter(manifest), staging)
