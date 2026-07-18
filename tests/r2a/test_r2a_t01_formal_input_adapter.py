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
    for name in FORMAL_INPUT_ORDER:
        rows = json.loads(json_paths[name].read_text(encoding="utf-8"))
        database = tmp_path / "formal-inputs" / f"{name}.duckdb"
        database.parent.mkdir(parents=True, exist_ok=True)
        logical_table = f"bound_{name}"
        with duckdb.connect(str(database)) as connection:
            connection.register("fixture_rows", pa.Table.from_pylist(rows))
            connection.execute(
                f'CREATE TABLE "{logical_table}" AS SELECT * FROM fixture_rows'
            )
            connection.unregister("fixture_rows")
            connection.execute("CHECKPOINT")
        database_paths[name] = database
        entries[name] = _entry_for(name, database, logical_table)
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
        "input_role": "validation_only"
        if name == "pcvt_validation_raw"
        else "materialization",
    }


def _refresh_entry(manifest_path: Path, name: str) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous = payload["inputs"][name]
    refreshed = _entry_for(
        name, Path(previous["actual_path"]), previous["logical_table_name"]
    )
    payload["inputs"][name] = refreshed
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
    _stage_formal_inputs(FormalInputAdapter(manifest), staging)
    with pytest.raises(ScoreReleaseError, match=expected):
        _validate_staging(staging)


def test_swapped_source_table_fails_closed(tmp_path: Path) -> None:
    manifest, _ = _formal_fixture(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["inputs"]["pcvt_component_scores"] = dict(
        payload["inputs"]["pcvt_validation_raw"], input_role="materialization"
    )
    write_json_atomic(manifest, payload)
    staging = tmp_path / "swapped.duckdb"
    _stage_formal_inputs(FormalInputAdapter(manifest), staging)
    with pytest.raises(
        ScoreReleaseError, match="staging_schema_missing:pcvt_component_scores"
    ):
        _validate_staging(staging)
