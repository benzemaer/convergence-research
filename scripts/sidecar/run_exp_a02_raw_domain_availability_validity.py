"""Run the EXP-A02 synthetic or authorized formal aggregate package."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_a02_raw_domain_availability_validity import (  # noqa: E402
    A01_IMPLEMENTATION_SHA,
    A01_RESULT_COMMIT,
    A01_RUN_ID,
    OUTPUT_FILES,
    TASK_ID,
    build_anomaly_scan,
    build_profiles,
    build_result_analysis,
    write_profiles,
)
from src.sidecar.exp_a02_raw_domain_availability_validity_validator import (  # noqa: E402
    CONFIG_PATH,
    _validate_raw_input_manifest_metadata,
    cheap_validate_final_package,
    load_json,
    prepare_input_manifest,
    sha256_file,
    validate_package,
    validate_static_config,
)

RUN_ID_PATTERN = re.compile(r"^EXP-A02-[0-9]{8}T[0-9]{6}(?:[0-9]{3,6})?Z$")
SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_worktree_status() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _validate_exact_formal_gate(
    *, reviewed_implementation_sha: str | None, output_root: Path, run_id: str
) -> None:
    if not reviewed_implementation_sha or not SHA40_PATTERN.fullmatch(
        reviewed_implementation_sha
    ):
        raise RuntimeError("formal mode requires a 40-character lowercase reviewed SHA")
    if _git_head() != reviewed_implementation_sha:
        raise RuntimeError("formal reviewed SHA does not match git HEAD")
    if _git_worktree_status():
        raise RuntimeError("formal run requires a clean worktree")
    if output_root.exists():
        raise RuntimeError(f"output directory must not already exist: {output_root}")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise RuntimeError(f"invalid EXP-A02 formal run id: {run_id}")


def _input_hash_changed_count(
    before: Mapping[str, str], after: Mapping[str, str]
) -> int:
    return sum(
        before.get(artifact_id) != after.get(artifact_id) for artifact_id in before
    )


def _formal_analysis_with_readiness(analysis: str, anomaly_status: str) -> str:
    readiness = (
        "ready_for_user_formal_result_review"
        if anomaly_status == "passed"
        else "needs_investigation_before_user_review"
    )
    lines = analysis.rstrip("\n").splitlines()
    if not lines:
        raise RuntimeError("result analysis is empty")
    lines[-1] = readiness
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
        if not path.is_file():
            continue
        result[filename] = {
            "path": filename,
            "sha256": sha256_file(path),
            "row_count": _artifact_row_count(path),
        }
    return result


def _build_manifest(
    *,
    staging: Path,
    run_id: str,
    input_info: dict[str, Any],
    validator_status: str,
    anomaly_status: str,
    final_manifest: bool,
    synthetic_fixture: bool,
    reviewed_implementation_sha: str | None,
    input_hashes_before: Mapping[str, str],
    input_hashes_after: Mapping[str, str],
    input_hash_changed_count: int,
) -> dict[str, Any]:
    input_artifacts = {}
    for artifact_id, path in input_info["paths"].items():
        declaration = input_info["declarations"][artifact_id]
        metadata = input_info["metadata"].get(artifact_id, {})
        input_artifacts[artifact_id] = {
            "path": declaration["path"],
            "path_policy": declaration["path_policy"],
            "sha256": sha256_file(path),
            "artifact_kind": declaration["artifact_kind"],
            "table": declaration.get("table"),
            "row_count": declaration.get("row_count"),
            "actual_key_count": metadata.get("key_count"),
            "security_count": metadata.get("security_count"),
            "date_min": metadata.get("date_min"),
            "date_max": metadata.get("date_max"),
        }
    raw_metadata = input_info["metadata"]["exp_a01_raw_metrics"]
    formal = not synthetic_fixture
    return {
        "task_id": TASK_ID,
        "program_id": "EXP-A",
        "run_id": run_id,
        "phase": "implementation_synthetic_fixture"
        if synthetic_fixture
        else "formal_run",
        "synthetic_fixture": synthetic_fixture,
        "final_manifest": final_manifest,
        "formal_data_version": False,
        "formal_run_allowed": formal,
        "formal_run_executed": formal,
        "formal_artifacts_generated": formal,
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "accepted_upstream": {
            "task_id": "EXP-A01",
            "accepted_run_id": A01_RUN_ID,
            "implementation_sha": A01_IMPLEMENTATION_SHA,
            "result_commit": A01_RESULT_COMMIT,
        },
        "input_manifest_path": str(input_info["manifest_path"]),
        "input_manifest_sha256": input_info["manifest_sha256"],
        "input_hashes_before": dict(input_hashes_before),
        "input_hashes_after": dict(input_hashes_after),
        "input_hash_changed_count": input_hash_changed_count,
        "input_artifacts": input_artifacts,
        "output_artifacts": _output_artifacts(staging),
        "validator_status": validator_status,
        "anomaly_status": anomaly_status,
        "validation_strategy": "r0_t10_artifact_bound_full_aggregate_recompute_v1",
        "core_validator_execution_count": 1,
        "prohibited_outputs_generated": False,
        "raw_row_count": raw_metadata["row_count"],
        "expected_key_count": raw_metadata["key_count"],
        "security_count": raw_metadata["security_count"],
        "date_min": raw_metadata["date_min"],
        "date_max": raw_metadata["date_max"],
        "EXP_A03_started": False,
        "A_layer_registered": False,
        "PCATV_created": False,
        "started_at": input_info.get("started_at", _now()),
        "finished_at": _now(),
    }


def _failure_summary(
    *,
    run_id: str,
    stage: str,
    error: str,
    input_info: dict[str, Any] | None,
    synthetic_fixture: bool,
    reviewed_implementation_sha: str | None,
) -> dict[str, Any]:
    input_hashes_before = input_info.get("input_hashes_before") if input_info else None
    input_hashes_after = input_info.get("input_hashes_after") if input_info else None
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "run_status": (
            "failed_synthetic_fixture_validation"
            if synthetic_fixture
            else "failed_formal_validation"
        ),
        "published": False,
        "formal_artifacts_generated": False,
        "formal_data_version": False,
        "usable_as_formal_result": False,
        "synthetic_fixture": synthetic_fixture,
        "failure_stage": stage,
        "error": error,
        "upstream_raw_copied": False,
        "input_manifest_sha256": (
            input_info.get("manifest_sha256") if input_info else None
        ),
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "input_hashes_before": input_hashes_before,
        "input_hashes_after": input_hashes_after,
        "input_hash_changed_count": (
            input_info.get("input_hash_changed_count", 0) if input_info else 0
        ),
        "diagnostic_only": True,
    }


def _run(args: argparse.Namespace, *, synthetic_fixture: bool) -> dict[str, Any]:
    run_id = str(args.run_id)
    output_root = Path(args.output_root).resolve()
    if output_root.name != run_id:
        raise RuntimeError("output-root basename must equal run-id")
    reviewed_implementation_sha = (
        None
        if synthetic_fixture
        else getattr(args, "reviewed_implementation_sha", None)
    )
    if synthetic_fixture:
        if not getattr(args, "allow_synthetic_fixture", False):
            raise RuntimeError("synthetic mode requires --allow-synthetic-fixture")
        if getattr(args, "reviewed_implementation_sha", None) is not None:
            raise RuntimeError("synthetic mode must not receive a reviewed SHA")
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise RuntimeError(f"invalid EXP-A02 synthetic run id: {run_id}")
        if output_root.exists():
            raise RuntimeError(
                f"output directory must not already exist: {output_root}"
            )
    else:
        if not getattr(args, "allow_formal_run", False):
            raise RuntimeError("formal mode requires --allow-formal-run")
        _validate_exact_formal_gate(
            reviewed_implementation_sha=reviewed_implementation_sha,
            output_root=output_root,
            run_id=run_id,
        )
    config_path = Path(args.config).resolve()
    config = load_json(config_path)
    config_errors = validate_static_config(config)
    if config_errors:
        raise RuntimeError("A02 config validation failed: " + "; ".join(config_errors))
    failure_root = (
        Path(args.failure_root).resolve()
        if args.failure_root
        else output_root.parent / "formal-failures"
    )
    manifest_path = Path(args.input_manifest).resolve()
    input_root = (
        Path(args.input_root).resolve() if getattr(args, "input_root", None) else None
    )
    stage = "input_lineage"
    input_info: dict[str, Any] | None = None
    staging = output_root.parent / f"{run_id}.partial-{os.getpid()}"
    if staging.exists():
        raise RuntimeError(f"staging directory already exists: {staging}")
    try:
        input_info = prepare_input_manifest(
            manifest_path,
            input_root=input_root,
            allow_synthetic_fixture=synthetic_fixture,
            allow_formal_run=not synthetic_fixture,
            reviewed_implementation_sha=reviewed_implementation_sha,
        )
        input_info["started_at"] = _now()
        input_info["input_hashes_before"] = dict(input_info["artifact_hashes"])
        input_info["input_hashes_after"] = dict(input_info["artifact_hashes"])
        input_info["input_hash_changed_count"] = 0
        input_info = _validate_raw_input_manifest_metadata(input_info)
        staging.mkdir(parents=True, exist_ok=False)
        stage = "aggregate_materialization"
        raw_path = input_info["paths"]["exp_a01_raw_metrics"]
        connection = duckdb.connect(str(raw_path), read_only=True)
        try:
            profiles = build_profiles(
                connection,
                expected_row_count=input_info["metadata"]["exp_a01_raw_metrics"][
                    "key_count"
                ],
            )
        finally:
            connection.close()
        write_profiles(staging, profiles)
        stage = "preliminary_manifest"
        _write_json(
            staging / OUTPUT_FILES["manifest"],
            _build_manifest(
                staging=staging,
                run_id=run_id,
                input_info=input_info,
                validator_status="pending",
                anomaly_status="pending",
                final_manifest=False,
                synthetic_fixture=synthetic_fixture,
                reviewed_implementation_sha=reviewed_implementation_sha,
                input_hashes_before=input_info["input_hashes_before"],
                input_hashes_after=input_info["input_hashes_after"],
                input_hash_changed_count=0,
            ),
        )
        stage = "core_validation"
        validator_result = validate_package(
            staging,
            config=config,
            input_manifest_path=manifest_path,
            run_id=run_id,
            require_final_manifest=False,
            allow_synthetic_fixture=synthetic_fixture,
            require_diagnostics=False,
            input_root=input_root,
            allow_formal_run=not synthetic_fixture,
            reviewed_implementation_sha=reviewed_implementation_sha,
        )
        validator_result["input_hashes_before"] = dict(
            input_info["input_hashes_before"]
        )
        validator_result["input_hashes_after"] = dict(input_info["input_hashes_after"])
        validator_result["input_hash_changed_count"] = 0
        _write_json(staging / OUTPUT_FILES["validator_result"], validator_result)
        stage = "anomaly_scan"
        anomaly_scan = build_anomaly_scan(profiles, validator_result)
        anomaly_scan["run_id"] = run_id
        _write_json(staging / OUTPUT_FILES["anomaly_scan"], anomaly_scan)
        if validator_result["status"] != "passed":
            raise RuntimeError(
                "core validator failed: "
                + "; ".join(validator_result.get("errors", []))
            )
        if anomaly_scan["status"] == "failed":
            raise RuntimeError("anomaly scan failed")
        stage = "result_analysis"
        analysis = build_result_analysis(
            run_id=run_id,
            reviewed_implementation_sha=reviewed_implementation_sha or "",
            handoff=input_info["handoff"],
            input_bindings=input_info["declarations"],
            profiles=profiles,
            validator_result=validator_result,
            anomaly_scan=anomaly_scan,
            synthetic_fixture=synthetic_fixture,
        )
        if not synthetic_fixture:
            analysis = _formal_analysis_with_readiness(analysis, anomaly_scan["status"])
        (staging / OUTPUT_FILES["result_analysis"]).write_text(
            analysis, encoding="utf-8", newline="\n"
        )
        stage = "input_hash_validation"
        input_hashes_after = {
            artifact_id: sha256_file(path)
            for artifact_id, path in input_info["paths"].items()
        }
        input_hash_changed_count = _input_hash_changed_count(
            input_info["input_hashes_before"], input_hashes_after
        )
        input_info["input_hashes_after"] = input_hashes_after
        input_info["input_hash_changed_count"] = input_hash_changed_count
        validator_result["input_hashes_before"] = dict(
            input_info["input_hashes_before"]
        )
        validator_result["input_hashes_after"] = dict(input_hashes_after)
        validator_result["input_hash_changed_count"] = input_hash_changed_count
        _write_json(staging / OUTPUT_FILES["validator_result"], validator_result)
        if input_hash_changed_count:
            _write_json(
                staging / OUTPUT_FILES["manifest"],
                _build_manifest(
                    staging=staging,
                    run_id=run_id,
                    input_info=input_info,
                    validator_status=validator_result["status"],
                    anomaly_status=anomaly_scan["status"],
                    final_manifest=False,
                    synthetic_fixture=synthetic_fixture,
                    reviewed_implementation_sha=reviewed_implementation_sha,
                    input_hashes_before=input_info["input_hashes_before"],
                    input_hashes_after=input_hashes_after,
                    input_hash_changed_count=input_hash_changed_count,
                ),
            )
            raise RuntimeError("input artifact hash changed before final manifest")
        stage = "final_manifest"
        final_manifest = _build_manifest(
            staging=staging,
            run_id=run_id,
            input_info=input_info,
            validator_status=validator_result["status"],
            anomaly_status=anomaly_scan["status"],
            final_manifest=True,
            synthetic_fixture=synthetic_fixture,
            reviewed_implementation_sha=reviewed_implementation_sha,
            input_hashes_before=input_info["input_hashes_before"],
            input_hashes_after=input_info["input_hashes_after"],
            input_hash_changed_count=input_info["input_hash_changed_count"],
        )
        _write_json(staging / OUTPUT_FILES["manifest"], final_manifest)
        stage = "cheap_final_package_validation"
        cheap_result = cheap_validate_final_package(
            staging,
            input_manifest_sha256=input_info["manifest_sha256"],
            run_id=run_id,
            synthetic_fixture=synthetic_fixture,
            reviewed_implementation_sha=reviewed_implementation_sha,
        )
        if cheap_result["status"] != "passed":
            raise RuntimeError("cheap final package validation failed")
        stage = "publish"
        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(output_root)
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed",
            "execution_mode": (
                "synthetic_fixture_only" if synthetic_fixture else "formal_run"
            ),
            "formal_run_executed": not synthetic_fixture,
            "formal_artifacts_generated": not synthetic_fixture,
            "output_root": str(output_root),
            "failure_package": None,
            "validator_status": validator_result["status"],
            "anomaly_status": anomaly_scan["status"],
            "core_validator_execution_count": 1,
            "aggregate_recomputation_count": 1,
        }
    except Exception as exc:  # noqa: BLE001
        failure_package = failure_root / run_id / "package"
        if staging.exists():
            failure_package.parent.mkdir(parents=True, exist_ok=True)
            if failure_package.exists():
                raise RuntimeError(
                    f"failed package destination already exists: {failure_package}"
                ) from exc
            _write_json(
                staging / "failure_summary.json",
                _failure_summary(
                    run_id=run_id,
                    stage=stage,
                    error=str(exc),
                    input_info=input_info,
                    synthetic_fixture=synthetic_fixture,
                    reviewed_implementation_sha=reviewed_implementation_sha,
                ),
            )
            staging.rename(failure_package)
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "failed",
            "execution_mode": (
                "synthetic_fixture_only" if synthetic_fixture else "formal_run"
            ),
            "formal_run_executed": False,
            "formal_artifacts_generated": False,
            "error": str(exc),
            "failure_stage": stage,
            "failure_package": (
                str(failure_package) if failure_package.exists() else None
            ),
            "output_root": str(output_root),
        }


def run_synthetic(args: argparse.Namespace) -> dict[str, Any]:
    return _run(args, synthetic_fixture=True)


def run_formal(args: argparse.Namespace) -> dict[str, Any]:
    return _run(args, synthetic_fixture=False)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = (
            run_synthetic(args) if args.allow_synthetic_fixture else run_formal(args)
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"task_id": TASK_ID, "status": "failed", "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--failure-root", type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--allow-synthetic-fixture", action="store_true")
    modes.add_argument("--allow-formal-run", action="store_true")
    parser.add_argument("--reviewed-implementation-sha")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
