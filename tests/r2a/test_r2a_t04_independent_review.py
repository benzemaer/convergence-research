# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from scripts.review import review_r2a_t04_real_data_audit as independent
from src.r2a import r2a_t04_audit_validator as bundle_validator
from src.r2a.r2a_t04_request_panel import build_request_panel
from src.r2a.r2a_t04_score_audit import run_score_formal_audit
from tests.r2a.test_r2a_t04_score_audit import _create_score_database


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def _refresh_bundle_file(bundle: Path, filename: str) -> None:
    summary_path = bundle / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    entry = next(item for item in summary["files"] if item["relative_path"] == filename)
    path = bundle / filename
    entry["sha256"] = _sha(path)
    entry["byte_size"] = path.stat().st_size
    _write_json(summary_path, summary)


@pytest.fixture(scope="module")
def score_only_package(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Path | dict[str, object]]:
    root = tmp_path_factory.mktemp("independent-review-base")
    score = root / "score.duckdb"
    _create_score_database(score)
    config = json.loads(
        Path("configs/r2a/r2a_t04_real_data_audit.v1.json").read_text(encoding="utf-8")
    )
    config.update(
        {
            "status": "authorized_not_started",
            "authorization_revision": 4,
            "formal_run_authorized": True,
            "formal_run_started": False,
            "formal_run_consumed": False,
        }
    )
    config["score_release"]["security_count"] = 3
    panel = build_request_panel(config)
    formal_root = root / "R2A-T04-20260719T000000000Z"
    bundle = root / "review"
    import src.r2a.r2a_t04_score_audit as score_audit

    patch = pytest.MonkeyPatch()
    patch.setattr(
        score_audit,
        "verify_file_identity",
        lambda path, **_kwargs: {
            "filename": Path(path).name,
            "sha256": independent.EXPECTED_SCORE_IDENTITY["sha256"],
            "byte_size": independent.EXPECTED_SCORE_IDENTITY["byte_size"],
        },
    )
    patch.setattr(score_audit, "free_disk_gate", lambda *_args: 10**12)
    try:
        run_score_formal_audit(
            config=config,
            panel=panel,
            score_database=score,
            output_root=formal_root,
            review_output=bundle,
            execution_gate={"status": "passed"},
        )
    finally:
        patch.undo()
    actual_identity: dict[str, object] = {
        "score_release_id": independent.EXPECTED_SCORE_IDENTITY["score_release_id"],
        "sha256": _sha(score),
        "byte_size": score.stat().st_size,
    }
    _write_json(
        formal_root / "score_source_identity.json",
        {"filename": score.name, **actual_identity},
    )
    _write_json(bundle / "score_source_identity.json", actual_identity)
    summary = json.loads((bundle / "run_summary.json").read_text(encoding="utf-8"))
    summary["score_source"] = actual_identity
    _write_json(bundle / "run_summary.json", summary)
    _refresh_bundle_file(bundle, "score_source_identity.json")
    schema = json.loads(
        Path("schemas/r2a/r2a_t04_review_bundle.schema.json").read_text(
            encoding="utf-8"
        )
    )
    score_schema = schema["properties"]["score_source"]["properties"]
    score_schema["sha256"]["const"] = actual_identity["sha256"]
    score_schema["byte_size"]["const"] = actual_identity["byte_size"]
    schema_path = root / "synthetic-review-schema.json"
    _write_json(schema_path, schema)
    return {
        "root": root,
        "score": score,
        "formal_root": formal_root,
        "bundle": bundle,
        "identity": actual_identity,
        "schema": schema_path,
    }


@pytest.fixture
def package(
    tmp_path: Path,
    score_only_package: dict[str, Path | dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path | dict[str, object]]:
    score = tmp_path / "score.duckdb"
    shutil.copy2(score_only_package["score"], score)
    formal_root = tmp_path / "R2A-T04-20260719T000000000Z"
    bundle = tmp_path / "review"
    shutil.copytree(score_only_package["formal_root"], formal_root)
    shutil.copytree(score_only_package["bundle"], bundle)
    monkeypatch.setattr(bundle_validator, "REVIEW_SCHEMA", score_only_package["schema"])
    return {
        "score": score,
        "formal_root": formal_root,
        "bundle": bundle,
        "identity": score_only_package["identity"],
    }


def _review(package: dict[str, Path | dict[str, object]]) -> dict[str, object]:
    return independent.run_independent_review(
        score_db=package["score"],
        run_root=package["formal_root"],
        review_bundle=package["bundle"],
        expected_score_identity=package["identity"],
    )


def test_cli_has_exactly_three_required_arguments() -> None:
    arguments = independent.parse_args(
        ["--score-db", "score", "--run-root", "run", "--review-bundle", "bundle"]
    )
    assert isinstance(arguments, argparse.Namespace)
    assert set(vars(arguments)) == {"score_db", "run_root", "review_bundle"}


def test_cli_source_has_no_legacy_non_score_dependencies() -> None:
    source = Path(independent.__file__).read_text(encoding="utf-8")
    forbidden = (
        "ACCEPTED_SCORE",
        "R2A_T04_MARKET_DB",
        "_market_path",
        "recompute_path_metrics",
        "chart_sample_registry",
    )
    assert not any(value in source for value in forbidden)


def test_valid_score_only_formal_root_and_bundle_pass(
    package: dict[str, Path | dict[str, object]],
) -> None:
    receipt = _review(package)
    assert receipt["status"] == "passed", receipt["mismatches"][:3]
    assert receipt["compact_bundle_status"] == "passed"
    assert (package["formal_root"] / "independent_review_receipt.json").is_file()


def test_wrong_score_identity_fails(
    package: dict[str, Path | dict[str, object]],
) -> None:
    package["score"].write_bytes(b"wrong")
    receipt = _review(package)
    assert receipt["status"] == "failed"
    assert receipt["score_identity_status"] == "failed"


def test_wrong_authorization_revision_fails(
    package: dict[str, Path | dict[str, object]],
) -> None:
    authorization = json.loads(
        (package["formal_root"] / "authorization.json").read_text(encoding="utf-8")
    )
    authorization["authorization_revision"] = 3
    _write_json(package["formal_root"] / "authorization.json", authorization)
    receipt = _review(package)
    assert any(
        item["check_id"] == "authorization_revision" for item in receipt["mismatches"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_check"),
    [
        ("panel", "run_root_vs_compact"),
        ("request", "request_envelope"),
        ("missing", "independent_review_exception"),
        ("residual", "residual_request_results"),
        ("source_manifest", "forbidden_root_files"),
        ("forbidden_table", "forbidden_tables"),
    ],
)
def test_root_contract_mutations_fail(
    package: dict[str, Path | dict[str, object]], mutation: str, expected_check: str
) -> None:
    root = package["formal_root"]
    if mutation == "panel":
        panel = json.loads((root / "request_panel.json").read_text(encoding="utf-8"))
        panel[0]["request_hash"] = "0" * 64
        _write_json(root / "request_panel.json", panel)
    elif mutation == "request":
        path = sorted((root / "requests").glob("*.json"))[0]
        value = json.loads(path.read_text(encoding="utf-8"))
        value["request_hash"] = "0" * 64
        _write_json(path, value)
    elif mutation == "missing":
        (root / "run_manifest.json").unlink()
    elif mutation == "residual":
        (root / "request-results" / "residual.duckdb").touch()
    elif mutation == "source_manifest":
        _write_json(root / "source_manifest.json", {})
    else:
        with duckdb.connect(str(root / "audit_metrics.duckdb")) as connection:
            connection.execute("CREATE TABLE market_prices(value INTEGER)")
    receipt = _review(package)
    assert receipt["status"] == "failed"
    assert any(item["check_id"] == expected_check for item in receipt["mismatches"])


@pytest.mark.parametrize(
    ("target", "sql", "counter"),
    [
        (
            "request",
            "UPDATE request_metrics_records SET metrics_json=json_merge_patch(metrics_json,'{\"raw_true_count\":999}') WHERE logical_request_name='D01_P_q15_k3'",
            "request_metric_mismatch_count",
        ),
        (
            "year",
            "UPDATE year_metrics_records SET metrics_json=json_merge_patch(metrics_json,'{\"confirmation_events\":999}') WHERE logical_request_name='D01_P_q15_k3'",
            "year_metric_mismatch_count",
        ),
        (
            "termination",
            "UPDATE termination_metrics_records SET count=count+1 WHERE logical_request_name='D01_P_q15_k3'",
            "termination_metric_mismatch_count",
        ),
        (
            "response_subset",
            "UPDATE response_daily SET raw_state=false WHERE rowid=(SELECT min(rowid) FROM response_daily WHERE logical_request_name='Q02_PCAVT_q20_k3' AND raw_state=true)",
            "response_check_mismatch_count",
        ),
        (
            "marginal",
            "UPDATE dimension_response_profiles SET row_fingerprint='wrong' WHERE logical_request_name='M01_P25' AND dimension_id='C'",
            "response_check_mismatch_count",
        ),
        (
            "interval_count",
            "UPDATE request_metrics_records SET metrics_json=json_merge_patch(metrics_json,'{\"confirmed_interval_count\":999}') WHERE logical_request_name='D01_P_q15_k3'",
            "interval_inventory_mismatch_count",
        ),
        (
            "dimension",
            "DELETE FROM score_dimension_structure WHERE rowid IN (SELECT rowid FROM score_dimension_structure LIMIT 1)",
            "dimension_endpoint_mismatch_count",
        ),
        (
            "component",
            "DELETE FROM score_component_structure WHERE rowid IN (SELECT rowid FROM score_component_structure LIMIT 1)",
            "component_endpoint_mismatch_count",
        ),
    ],
)
def test_audit_database_mutations_fail(
    package: dict[str, Path | dict[str, object]], target: str, sql: str, counter: str
) -> None:
    del target
    with duckdb.connect(
        str(package["formal_root"] / "audit_metrics.duckdb")
    ) as connection:
        connection.execute(sql)
    receipt = _review(package)
    assert receipt["status"] == "failed"
    assert receipt[counter] > 0


def test_duplicate_interval_key_fails(
    package: dict[str, Path | dict[str, object]],
) -> None:
    path = package["formal_root"] / "audit_metrics.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE replacement AS SELECT * FROM interval_inventory UNION ALL (SELECT * FROM interval_inventory LIMIT 1)"
        )
        connection.execute("DROP TABLE interval_inventory")
        connection.execute("ALTER TABLE replacement RENAME TO interval_inventory")
    receipt = _review(package)
    assert receipt["interval_inventory_mismatch_count"] > 0


def test_parquet_and_security_distribution_mismatch_fail(
    package: dict[str, Path | dict[str, object]],
) -> None:
    (package["formal_root"] / "interval_inventory.parquet").write_bytes(b"bad parquet")
    receipt = _review(package)
    assert receipt["status"] == "failed"


def test_security_distribution_mismatch_fails(
    package: dict[str, Path | dict[str, object]],
) -> None:
    rows = (package["formal_root"] / "interval_security_distribution.csv").read_text(
        encoding="utf-8"
    )
    (package["formal_root"] / "interval_security_distribution.csv").write_text(
        rows.replace(",1,", ",999,", 1), encoding="utf-8"
    )
    receipt = _review(package)
    assert receipt["status"] == "failed"


@pytest.mark.parametrize(
    ("filename", "old", "new", "counter"),
    [
        (
            "score_dimension_endpoint_summary.csv",
            ",1.0,",
            ",0.123,",
            "dimension_endpoint_mismatch_count",
        ),
        (
            "score_component_endpoint_summary.csv",
            ",1.0,",
            ",0.123,",
            "component_endpoint_mismatch_count",
        ),
        (
            "interval_samples.csv",
            "raw_false",
            "BROKEN",
            "interval_sample_mismatch_count",
        ),
    ],
)
def test_compact_recomputed_outputs_mismatch_fail(
    package: dict[str, Path | dict[str, object]],
    filename: str,
    old: str,
    new: str,
    counter: str,
) -> None:
    path = package["bundle"] / filename
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    _refresh_bundle_file(package["bundle"], filename)
    receipt = _review(package)
    assert receipt["status"] == "failed"
    assert receipt[counter] > 0


def test_interval_sample_order_and_hash_fail(
    package: dict[str, Path | dict[str, object]],
) -> None:
    path = package["bundle"] / "interval_samples.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    _refresh_bundle_file(package["bundle"], path.name)
    receipt = _review(package)
    assert receipt["interval_sample_mismatch_count"] > 0
    rows = path.read_text(encoding="utf-8")
    path.write_text(
        rows.replace(rows.splitlines()[1].split(",")[-1], "0" * 64, 1),
        encoding="utf-8",
        newline="\n",
    )
    _refresh_bundle_file(package["bundle"], path.name)
    receipt = _review(package)
    assert receipt["status"] == "failed"


def test_failed_review_always_writes_receipt(
    package: dict[str, Path | dict[str, object]],
) -> None:
    (package["formal_root"] / "authorization.json").unlink()
    receipt = _review(package)
    persisted = json.loads(
        (package["formal_root"] / "independent_review_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["status"] == persisted["status"] == "failed"
