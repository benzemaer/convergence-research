from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import duckdb
import pytest

from src.r2a.r2a_t01_formal_input_adapter import FormalInputAdapter, FormalInputError
from src.r2a.r2a_t01_input_manifest import (
    FORMAL_SOURCE_FIELDS,
    InputManifestError,
    build_formal_input_manifest,
    build_synthetic_input_manifest,
    load_bound_inputs,
)
from tests.r2a._fixtures import synthetic_inputs, write_json
from tests.r2a.test_r2a_t01_formal_input_adapter import _formal_fixture


def _formal_sources(manifest_path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        name: {field: entry[field] for field in FORMAL_SOURCE_FIELDS}
        for name, entry in payload["inputs"].items()
    }


def _build_formal_manifest(
    output: Path, sources: dict[str, dict[str, object]]
) -> dict[str, object]:
    return build_formal_input_manifest(
        output_path=output,
        run_id="R2A-T01-FORMAL-BUILDER-TEST",
        source_commit="1" * 40,
        formal_authorization_id="LOCAL-TEST-AUTHORIZATION",
        universe_id="STAGGERED-TEST-UNIVERSE",
        inputs=sources,
    )


def test_builder_binds_only_complete_synthetic_input_set(tmp_path: Path) -> None:
    manifest, paths = synthetic_inputs(tmp_path / "synthetic")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["synthetic_only"] is True
    assert set(payload["inputs"]) == set(paths)
    assert len(load_bound_inputs(manifest)["securities"]) == 1


def test_builder_rejects_input_outside_synthetic_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.json"
    write_json(outside, [])
    paths = {
        name: root / f"{name}.json"
        for name in (
            "securities",
            "trading_sessions",
            "security_observation_spine",
            "pcvt_component_scores",
            "pcvt_dimension_scores",
            "a_raw_observations",
            "pcvt_validation_raw",
        )
    }
    for path in paths.values():
        write_json(path, [])
    paths["securities"] = outside
    with pytest.raises(InputManifestError, match="outside_synthetic_root"):
        build_synthetic_input_manifest(
            output_path=root / "manifest.json",
            run_id="synthetic",
            synthetic_root=root,
            inputs=paths,
        )


def test_loader_fails_closed_on_tampered_input(tmp_path: Path) -> None:
    manifest, paths = synthetic_inputs(tmp_path / "synthetic")
    write_json(paths["securities"], [{"security_id": "tampered"}])
    with pytest.raises(InputManifestError, match="input_hash_mismatch:securities"):
        load_bound_inputs(manifest)


def test_formal_builder_inspects_same_file_relations_and_adapter_accepts(
    tmp_path: Path,
) -> None:
    template, databases = _formal_fixture(tmp_path)
    sources = _formal_sources(template)
    output = tmp_path / "local-only-formal-manifest.json"
    payload = _build_formal_manifest(output, sources)
    assert set(payload["inputs"]) == {
        "security_observation_spine",
        "pcvt_component_scores",
        "pcvt_dimension_scores",
        "a_raw_observations",
        "pcvt_validation_raw",
    }
    assert len({Path(item["actual_path"]) for item in payload["inputs"].values()}) == 1
    assert next(iter(payload["inputs"].values()))["sha256"]
    assert payload["inputs"]["pcvt_validation_raw"]["input_role"] == "validation_only"
    assert payload["inputs"]["security_observation_spine"]["row_count"] == 123
    assert all(path == next(iter(databases.values())) for path in databases.values())
    with duckdb.connect() as connection:
        relations = FormalInputAdapter(output).attach_and_validate(connection)
    assert set(relations) == set(payload["inputs"])


def test_formal_builder_normalizes_accepted_r0_compact_dates(tmp_path: Path) -> None:
    template, databases = _formal_fixture(tmp_path)
    database = databases["pcvt_component_scores"]
    payload = json.loads(template.read_text(encoding="utf-8"))
    compact_date_roles = (
        "pcvt_component_scores",
        "pcvt_dimension_scores",
        "pcvt_validation_raw",
    )
    with duckdb.connect(str(database)) as connection:
        for role in compact_date_roles:
            table = payload["inputs"][role]["logical_table_name"]
            connection.execute(
                f"UPDATE \"{table}\" SET trading_date=replace(trading_date,'-','')"
            )
        connection.execute("CHECKPOINT")

    output = tmp_path / "compact-date-formal-manifest.json"
    built = _build_formal_manifest(output, _formal_sources(template))
    for role in compact_date_roles:
        assert built["inputs"][role]["date_min"] == "2020-01-01"
        assert built["inputs"][role]["date_max"] == "2020-05-02"
    with duckdb.connect() as connection:
        relations = FormalInputAdapter(output).attach_and_validate(connection)
    assert set(relations) == set(built["inputs"])


def test_formal_builder_rejects_wrong_table_and_source_metadata(tmp_path: Path) -> None:
    template, _ = _formal_fixture(tmp_path)
    sources = _formal_sources(template)
    wrong_table = deepcopy(sources)
    wrong_table["pcvt_component_scores"]["logical_table_name"] = "missing_table"
    with pytest.raises(InputManifestError, match="logical_table_missing"):
        _build_formal_manifest(tmp_path / "wrong-table.json", wrong_table)

    missing = deepcopy(sources)
    del missing["a_raw_observations"]["source_contract_id"]
    with pytest.raises(InputManifestError, match="formal_source_metadata_mismatch"):
        _build_formal_manifest(tmp_path / "missing-metadata.json", missing)

    wrong_role = deepcopy(sources)
    wrong_role["pcvt_validation_raw"]["input_role"] = "materialization"
    with pytest.raises(InputManifestError, match="input_role_mismatch"):
        _build_formal_manifest(tmp_path / "wrong-role.json", wrong_role)


def test_formal_builder_rejects_derived_metadata_override(tmp_path: Path) -> None:
    template, _ = _formal_fixture(tmp_path)
    sources = _formal_sources(template)
    sources["pcvt_component_scores"]["row_count"] = 1
    with pytest.raises(InputManifestError, match="formal_source_metadata_mismatch"):
        _build_formal_manifest(tmp_path / "override.json", sources)


def test_formal_builder_manifest_detects_later_source_tampering(tmp_path: Path) -> None:
    template, databases = _formal_fixture(tmp_path)
    sources = _formal_sources(template)
    output = tmp_path / "tamper-bound.json"
    payload = _build_formal_manifest(output, sources)
    table = payload["inputs"]["pcvt_component_scores"]["logical_table_name"]
    with duckdb.connect(str(databases["pcvt_component_scores"])) as connection:
        connection.execute(f'UPDATE "{table}" SET raw_value=raw_value+1 WHERE rowid=0')
        connection.execute("CHECKPOINT")
    with duckdb.connect() as connection:
        with pytest.raises(FormalInputError, match="input_(byte_size|sha256)_mismatch"):
            FormalInputAdapter(output).attach_and_validate(connection)
