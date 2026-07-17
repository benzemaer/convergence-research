"""Synthetic-only implementation runner for EXP-A02.

The formal gate is intentionally closed in this implementation phase.  The
runner exists to exercise the artifact-bound, set-based aggregate package on
temporary synthetic fixtures and to test failed-package preservation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    cheap_validate_final_package,
    load_json,
    sha256_file,
    validate_input_manifest,
    validate_package,
    validate_static_config,
)

RUN_ID_PATTERN = re.compile(r"^EXP-A02-[0-9]{8}T[0-9]{6}(?:[0-9]{3,6})?Z$")


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
        }
    return {
        "task_id": TASK_ID,
        "program_id": "EXP-A",
        "run_id": run_id,
        "phase": "implementation_synthetic_fixture",
        "synthetic_fixture": True,
        "final_manifest": final_manifest,
        "formal_data_version": False,
        "formal_run_allowed": False,
        "formal_run_executed": False,
        "formal_artifacts_generated": False,
        "accepted_upstream": {
            "task_id": "EXP-A01",
            "accepted_run_id": A01_RUN_ID,
            "implementation_sha": A01_IMPLEMENTATION_SHA,
            "result_commit": A01_RESULT_COMMIT,
        },
        "input_manifest_path": str(input_info["manifest_path"]),
        "input_manifest_sha256": input_info["manifest_sha256"],
        "input_artifacts": input_artifacts,
        "output_artifacts": _output_artifacts(staging),
        "validator_status": validator_status,
        "anomaly_status": anomaly_status,
        "validation_strategy": "r0_t10_artifact_bound_full_aggregate_recompute_v1",
        "core_validator_execution_count": 1,
        "prohibited_outputs_generated": False,
        "started_at": input_info.get("started_at", _now()),
        "finished_at": _now(),
    }


def _failure_summary(
    *,
    run_id: str,
    stage: str,
    error: str,
    input_info: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "run_status": "failed_synthetic_fixture_validation",
        "published": False,
        "formal_artifacts_generated": False,
        "formal_data_version": False,
        "usable_as_formal_result": False,
        "synthetic_fixture": True,
        "failure_stage": stage,
        "error": error,
        "upstream_raw_copied": False,
        "input_manifest_sha256": (
            input_info.get("manifest_sha256") if input_info else None
        ),
        "diagnostic_only": True,
    }


def run_synthetic(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config).resolve()
    config = load_json(config_path)
    config_errors = validate_static_config(config)
    if config_errors:
        raise RuntimeError("A02 config validation failed: " + "; ".join(config_errors))
    if not args.allow_synthetic_fixture:
        raise RuntimeError(
            "formal_run_not_implemented_in_implementation_phase; "
            "use --allow-synthetic-fixture"
        )
    run_id = str(args.run_id)
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise RuntimeError(f"invalid EXP-A02 synthetic run id: {run_id}")
    output_root = Path(args.output_root).resolve()
    if output_root.name != run_id:
        raise RuntimeError("output-root basename must equal run-id")
    if output_root.exists():
        raise RuntimeError(f"output directory must not already exist: {output_root}")
    failure_root = (
        Path(args.failure_root).resolve()
        if args.failure_root
        else output_root.parent / "formal-failures"
    )
    manifest_path = Path(args.input_manifest).resolve()
    stage = "input_lineage"
    input_info: dict[str, Any] | None = None
    staging = output_root.parent / f"{run_id}.partial-{os.getpid()}"
    if staging.exists():
        raise RuntimeError(f"staging directory already exists: {staging}")
    try:
        input_info = validate_input_manifest(
            manifest_path, allow_synthetic_fixture=True
        )
        input_info["started_at"] = _now()
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
            ),
        )
        stage = "core_validation"
        validator_result = validate_package(
            staging,
            config=config,
            input_manifest_path=manifest_path,
            run_id=run_id,
            require_final_manifest=False,
            allow_synthetic_fixture=True,
            require_diagnostics=False,
        )
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
            reviewed_implementation_sha="",
            handoff=input_info["handoff"],
            input_bindings=input_info["declarations"],
            profiles=profiles,
            validator_result=validator_result,
            anomaly_scan=anomaly_scan,
            synthetic_fixture=True,
        )
        (staging / OUTPUT_FILES["result_analysis"]).write_text(
            analysis, encoding="utf-8", newline="\n"
        )
        stage = "final_manifest"
        final_manifest = _build_manifest(
            staging=staging,
            run_id=run_id,
            input_info=input_info,
            validator_status=validator_result["status"],
            anomaly_status=anomaly_scan["status"],
            final_manifest=True,
        )
        _write_json(staging / OUTPUT_FILES["manifest"], final_manifest)
        stage = "cheap_final_package_validation"
        cheap_result = cheap_validate_final_package(
            staging,
            input_manifest_sha256=input_info["manifest_sha256"],
            run_id=run_id,
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
            "execution_mode": "synthetic_fixture_only",
            "formal_run_executed": False,
            "formal_artifacts_generated": False,
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
                ),
            )
            staging.rename(failure_package)
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "failed",
            "execution_mode": "synthetic_fixture_only",
            "formal_run_executed": False,
            "formal_artifacts_generated": False,
            "error": str(exc),
            "failure_stage": stage,
            "failure_package": (
                str(failure_package) if failure_package.exists() else None
            ),
            "output_root": str(output_root),
        }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_synthetic(args)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"task_id": TASK_ID, "status": "failed", "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--failure-root", type=Path)
    parser.add_argument("--allow-synthetic-fixture", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
