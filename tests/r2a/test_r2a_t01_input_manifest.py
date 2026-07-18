from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.r2a.r2a_t01_input_manifest import (
    InputManifestError,
    build_synthetic_input_manifest,
    load_bound_inputs,
)
from tests.r2a._fixtures import synthetic_inputs, write_json


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
