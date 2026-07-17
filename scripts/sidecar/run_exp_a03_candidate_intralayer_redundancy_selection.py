"""Run the EXP-A03 synthetic package or an explicitly authorized formal run."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_BRANCH = "codex/exp-a-price-ma-attachment-program"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_a03_candidate_intralayer_redundancy_selection import (  # noqa: E402
    OUTPUT_FILES,
    build_analysis,
    build_anomaly_scan,
    build_result_analysis,
    write_outputs,
)
from src.sidecar.exp_a03_candidate_intralayer_redundancy_selection_validator import (  # noqa: E402
    CONFIG_PATH,
    cheap_validate_final_package,
    load_json,
    prepare_input_manifest,
    sha256_file,
    validate_package,
    validate_static_config,
)

TASK_ID = "EXP-A03"
RUN_ID_PATTERN = re.compile(r"^EXP-A03-[0-9]{8}T[0-9]{6}(?:[0-9]{3,6})?Z$")
SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_worktree_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_branch() -> str:
    return subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _artifact_row_count(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8") as handle:
            return max(0, sum(1 for _ in handle) - 1)
    if path.suffix.lower() == ".md":
        with path.open(encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    return 1


def _output_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for filename in OUTPUT_FILES.values():
        if filename == OUTPUT_FILES["manifest"]:
            continue
        path = root / filename
        if path.is_file():
            result[filename] = {
                "path": filename,
                "sha256": sha256_file(path),
                "row_count": _artifact_row_count(path),
            }
    return result


def _validate_exact_formal_gate(
    *, reviewed_sha: str | None, output_root: Path, run_id: str
) -> None:
    if not reviewed_sha or not SHA40_PATTERN.fullmatch(reviewed_sha):
        raise RuntimeError("formal run requires a 40-character lowercase reviewed SHA")
    if _git_head() != reviewed_sha:
        raise RuntimeError("formal reviewed SHA does not match git HEAD")
    if _git_branch() != EXPECTED_BRANCH:
        raise RuntimeError("formal run requires the approved EXP-A03 branch")
    if _git_worktree_status():
        raise RuntimeError("formal run requires a clean worktree")
    if output_root.exists():
        raise RuntimeError("formal output directory already exists")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise RuntimeError("invalid EXP-A03 run ID")


def _build_manifest(
    *,
    staging: Path,
    run_id: str,
    input_info: Mapping[str, Any],
    config: Mapping[str, Any],
    validator_status: str,
    anomaly_status: str,
    final_manifest: bool,
    reviewed_sha: str | None,
    input_hashes_before: Mapping[str, str],
    input_hashes_after: Mapping[str, str],
    input_hash_changed_count: int,
    preliminary_mismatch_count: int = 0,
) -> dict[str, Any]:
    synthetic = bool(input_info["synthetic_fixture"])
    handoff = input_info["handoff"]
    binding = input_info["manifest"]["cross_artifact_bindings"]
    return {
        "task_id": TASK_ID,
        "program_id": "EXP-A",
        "run_id": run_id,
        "phase": "implementation_synthetic_fixture" if synthetic else "formal_run",
        "synthetic_fixture": synthetic,
        "final_manifest": final_manifest,
        "formal_data_version": False,
        "formal_run_allowed": not synthetic,
        "formal_run_executed": not synthetic,
        "formal_artifacts_generated": not synthetic,
        "reviewed_implementation_sha": reviewed_sha,
        "accepted_upstream": {
            "task_id": "EXP-A02",
            "accepted_run_id": handoff["accepted_run_id"],
            "reviewed_implementation_sha": handoff["reviewed_implementation_sha"],
            "result_commit": handoff["result_commit"],
        },
        "input_manifest_path": str(input_info["manifest_path"]),
        "input_manifest_sha256": sha256_file(input_info["manifest_path"]),
        "input_hashes_before": dict(input_hashes_before),
        "input_hashes_after": dict(input_hashes_after),
        "input_hash_changed_count": input_hash_changed_count,
        "input_artifacts": {
            artifact_id: {
                "path": declaration["path"],
                "path_policy": declaration["path_policy"],
                "sha256": input_info["artifact_hashes"][artifact_id],
                "artifact_kind": declaration["artifact_kind"],
                "table": declaration.get("table"),
                "row_count": declaration.get("row_count"),
                "expected_key_count": declaration.get("expected_key_count"),
                "security_count": declaration.get("security_count"),
                "date_min": declaration.get("date_min"),
                "date_max": declaration.get("date_max"),
            }
            for artifact_id, declaration in input_info["declarations"].items()
        },
        "output_artifacts": _output_artifacts(staging),
        "validator_status": validator_status,
        "anomaly_status": anomaly_status,
        "preliminary_mismatch_count": preliminary_mismatch_count,
        "raw_row_count": binding["a01_raw_row_count"],
        "expected_key_count": binding["expected_key_count"],
        "triple_common_valid_count": binding["triple_common_valid_count"],
        "security_count": binding["security_count"],
        "date_min": binding["date_min"],
        "date_max": binding["date_max"],
        "A_layer_registered": False,
        "PCATV_created": False,
        "EXP_A04_started": False,
        "prohibited_outputs_generated": False,
        "started_at": input_info.get("started_at", _now()),
        "finished_at": _now(),
    }


def _failure_summary(
    *,
    run_id: str,
    stage: str,
    error: str,
    input_info: Mapping[str, Any] | None,
    reviewed_sha: str | None,
    synthetic: bool,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "run_status": "failed_synthetic_fixture_validation"
        if synthetic
        else "failed_formal_validation",
        "published": False,
        "usable_as_formal_result": False,
        "failure_stage": stage,
        "error": error,
        "upstream_raw_copied": False,
        "reviewed_implementation_sha": reviewed_sha,
        "input_hashes_before": input_info.get("input_hashes_before")
        if input_info
        else None,
        "input_hashes_after": input_info.get("input_hashes_after")
        if input_info
        else None,
        "input_hash_changed_count": input_info.get("input_hash_changed_count", 0)
        if input_info
        else 0,
        "diagnostic_only": True,
    }


def _run(args: argparse.Namespace, *, synthetic_fixture: bool) -> dict[str, Any]:
    run_id = str(args.run_id)
    output_root = Path(args.output_root).resolve()
    if output_root.name != run_id:
        raise RuntimeError("output-root basename must equal run-id")
    reviewed_sha = None if synthetic_fixture else args.reviewed_implementation_sha
    if synthetic_fixture:
        if not args.allow_synthetic_fixture or args.reviewed_implementation_sha:
            raise RuntimeError("synthetic mode requires only --allow-synthetic-fixture")
        if not RUN_ID_PATTERN.fullmatch(run_id) or output_root.exists():
            raise RuntimeError("invalid synthetic run ID or existing output")
    else:
        if not args.allow_formal_run:
            raise RuntimeError("formal mode requires --allow-formal-run")
        _validate_exact_formal_gate(
            reviewed_sha=reviewed_sha, output_root=output_root, run_id=run_id
        )
    config = load_json(Path(args.config).resolve())
    config_errors = validate_static_config(config)
    if config_errors:
        raise RuntimeError("A03 config validation failed: " + "; ".join(config_errors))
    input_info: dict[str, Any] | None = None
    failure_root = (
        Path(args.failure_root).resolve()
        if args.failure_root
        else output_root.parent / "formal-failures"
    )
    staging = output_root.parent / f"{run_id}.partial-{os.getpid()}"
    if staging.exists():
        raise RuntimeError("staging directory already exists")
    stage = "input_lineage"
    try:
        input_info = prepare_input_manifest(
            Path(args.input_manifest),
            input_root=Path(args.input_root).resolve() if args.input_root else None,
            allow_synthetic_fixture=synthetic_fixture,
            allow_formal_run=not synthetic_fixture,
            reviewed_implementation_sha=reviewed_sha,
        )
        input_info["started_at"] = _now()
        input_info["input_hashes_before"] = dict(input_info["artifact_hashes"])
        input_info["input_hashes_after"] = dict(input_info["artifact_hashes"])
        input_info["input_hash_changed_count"] = 0
        staging.mkdir(parents=True, exist_ok=False)
        stage = "aggregate_materialization"
        raw_path = input_info["paths"]["exp_a01_raw_metrics"]
        connection = duckdb.connect(str(raw_path), read_only=True)
        try:
            analysis = build_analysis(connection, config)
        finally:
            connection.close()
        analysis["candidate_disposition"]["run_id"] = run_id
        write_outputs(staging, analysis)
        (staging / OUTPUT_FILES["result_analysis"]).write_text(
            build_result_analysis(
                run_id,
                reviewed_sha or "",
                analysis,
                synthetic_fixture=synthetic_fixture,
            ),
            encoding="utf-8",
            newline="\n",
        )
        stage = "preliminary_manifest"
        _write_json(
            staging / OUTPUT_FILES["manifest"],
            _build_manifest(
                staging=staging,
                run_id=run_id,
                input_info=input_info,
                config=config,
                validator_status="pending",
                anomaly_status="pending",
                final_manifest=False,
                reviewed_sha=reviewed_sha,
                input_hashes_before=input_info["input_hashes_before"],
                input_hashes_after=input_info["input_hashes_after"],
                input_hash_changed_count=0,
            ),
        )
        stage = "core_validator"
        validator_result = validate_package(
            staging,
            config=config,
            input_manifest_path=Path(args.input_manifest),
            input_root=Path(args.input_root).resolve() if args.input_root else None,
            run_id=run_id,
            allow_synthetic_fixture=synthetic_fixture,
            allow_formal_run=not synthetic_fixture,
            reviewed_implementation_sha=reviewed_sha,
            require_final_manifest=False,
        )
        _write_json(staging / OUTPUT_FILES["validator_result"], validator_result)
        stage = "anomaly_scan"
        anomaly = build_anomaly_scan(
            analysis, validator_result, config, synthetic_fixture=synthetic_fixture
        )
        _write_json(staging / OUTPUT_FILES["anomaly_scan"], anomaly)
        if validator_result["status"] != "passed" or anomaly["status"] == "failed":
            _write_json(
                staging / OUTPUT_FILES["manifest"],
                _build_manifest(
                    staging=staging,
                    run_id=run_id,
                    input_info=input_info,
                    config=config,
                    validator_status=validator_result["status"],
                    anomaly_status=anomaly["status"],
                    final_manifest=False,
                    reviewed_sha=reviewed_sha,
                    input_hashes_before=input_info["input_hashes_before"],
                    input_hashes_after=input_info["input_hashes_after"],
                    input_hash_changed_count=len(validator_result.get("errors", [])),
                ),
            )
            raise RuntimeError("validator or blocking anomaly failed")
        stage = "result_analysis"
        (staging / OUTPUT_FILES["result_analysis"]).write_text(
            build_result_analysis(
                run_id,
                reviewed_sha or "",
                analysis,
                synthetic_fixture=synthetic_fixture,
                anomaly_status=anomaly["status"],
            ),
            encoding="utf-8",
            newline="\n",
        )
        stage = "input_hash_validation"
        after = {
            artifact_id: sha256_file(path)
            for artifact_id, path in input_info["paths"].items()
        }
        changed = sum(
            input_info["input_hashes_before"].get(key) != value
            for key, value in after.items()
        )
        input_info["input_hashes_after"], input_info["input_hash_changed_count"] = (
            after,
            changed,
        )
        if changed:
            _write_json(
                staging / OUTPUT_FILES["manifest"],
                _build_manifest(
                    staging=staging,
                    run_id=run_id,
                    input_info=input_info,
                    config=config,
                    validator_status=validator_result["status"],
                    anomaly_status=anomaly["status"],
                    final_manifest=False,
                    reviewed_sha=reviewed_sha,
                    input_hashes_before=input_info["input_hashes_before"],
                    input_hashes_after=after,
                    input_hash_changed_count=changed,
                ),
            )
            raise RuntimeError("input hash changed during run")
        stage = "final_manifest"
        _write_json(
            staging / OUTPUT_FILES["manifest"],
            _build_manifest(
                staging=staging,
                run_id=run_id,
                input_info=input_info,
                config=config,
                validator_status=validator_result["status"],
                anomaly_status=anomaly["status"],
                final_manifest=True,
                reviewed_sha=reviewed_sha,
                input_hashes_before=input_info["input_hashes_before"],
                input_hashes_after=after,
                input_hash_changed_count=0,
            ),
        )
        stage = "cheap_final_validation"
        cheap = cheap_validate_final_package(
            staging,
            run_id=run_id,
            input_manifest_sha256=sha256_file(Path(args.input_manifest)),
            input_hashes=input_info["artifact_hashes"],
            reviewed_implementation_sha=reviewed_sha,
            synthetic_fixture=synthetic_fixture,
        )
        if cheap["status"] != "passed":
            raise RuntimeError(
                "cheap final validation failed: " + ";".join(cheap["errors"])
            )
        stage = "publish"
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(output_root)
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed",
            "output_root": str(output_root),
            "failure_package": None,
            "validator_status": validator_result["status"],
            "anomaly_status": anomaly["status"],
            "core_validator_execution_count": 1,
            "anomaly_scan_execution_count": 1,
            "cheap_validation_execution_count": 1,
            "aggregate_recomputation_count": 1,
        }
    except Exception as exc:  # noqa: BLE001
        failure_package = failure_root / run_id / "package"
        if staging.exists():
            failure_package.parent.mkdir(parents=True, exist_ok=True)
            if failure_package.exists():
                raise RuntimeError(
                    "failure package destination already exists"
                ) from exc
            _write_json(
                staging / "failure_summary.json",
                _failure_summary(
                    run_id=run_id,
                    stage=stage,
                    error=str(exc),
                    input_info=input_info,
                    reviewed_sha=reviewed_sha,
                    synthetic=synthetic_fixture,
                ),
            )
            staging.rename(failure_package)
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "failed",
            "failure_stage": stage,
            "error": str(exc),
            "failure_package": str(failure_package)
            if failure_package.exists()
            else None,
            "output_root": str(output_root),
            "formal_artifacts_generated": False,
        }


def run_synthetic(args: argparse.Namespace) -> dict[str, Any]:
    return _run(args, synthetic_fixture=True)


def run_formal(args: argparse.Namespace) -> dict[str, Any]:
    return _run(args, synthetic_fixture=False)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--failure-root", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reviewed-implementation-sha")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--allow-synthetic-fixture", action="store_true")
    modes.add_argument("--allow-formal-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = (
            run_synthetic(args) if args.allow_synthetic_fixture else run_formal(args)
        )
    except Exception as exc:  # noqa: BLE001
        result = {"task_id": TASK_ID, "status": "failed", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
