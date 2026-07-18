from __future__ import annotations

import json
from pathlib import Path

from src.r2a.r2a_t01_result_analysis import analyze_score_release
from src.r2a.r2a_t01_validator import validate_score_release
from tests.r2a._fixtures import build_package


def test_synthetic_formal_shape_smoke_without_formal_authorization(
    tmp_path: Path,
) -> None:
    package, input_manifest, _ = build_package(
        tmp_path, security_ids=("000001.SZ", "000002.SZ")
    )
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_commit"] is None
    assert manifest["formal_source_bindings"] == {}
    assert len(manifest["environment_lock_sha256"]) == 64
    assert not (package / "validation_receipt.json").exists()
    assert not (package / "result_analysis.md").exists()
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["status"] == "passed"
    analysis = analyze_score_release(package)
    assert analysis.is_file()
    assert not (package / "DONE").exists()
    assert sorted(path.name for path in package.iterdir()) == [
        "manifest.json",
        "result_analysis.md",
        "schema.json",
        "score_data.duckdb",
        "validation_receipt.json",
    ]
