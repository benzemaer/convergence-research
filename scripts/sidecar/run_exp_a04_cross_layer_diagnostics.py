# ruff: noqa: E501

"""Run EXP-A04 synthetic diagnostics or an explicitly authorized formal run."""

from __future__ import annotations

import argparse
import json
import re
import shutil
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

from src.sidecar.exp_a04_cross_layer_diagnostics import (  # noqa: E402
    OUTPUT_FILES,
    build_analysis,
    build_anomaly_scan,
    build_result_analysis,
    write_outputs,
)
from src.sidecar.exp_a04_cross_layer_diagnostics_validator import (  # noqa: E402
    cheap_validate_final_package,
    sha256_file,
    validate_authorized_manifest,
    validate_formal_result,
    validate_lineage_inputs,
)

TASK_ID = "EXP-A04"
RUN_ID_PATTERN = re.compile(r"^(?:EXP-A04|SYNTH-A04)-[0-9]{8}T[0-9]{9}Z$")
SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _row_count(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return max(0, sum(1 for _ in handle) - 1)
    if path.suffix.lower() == ".md":
        with path.open(encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    return 1


def _output_artifacts(package_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for filename in OUTPUT_FILES:
        if filename == "exp_a04_manifest.json":
            continue
        path = package_root / filename
        if path.is_file():
            result[filename] = {
                "path": filename,
                "sha256": sha256_file(path),
                "row_count": _row_count(path),
            }
    return result


def _manifest_artifacts(path: Path) -> dict[str, Mapping[str, Any]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("input_artifacts", {})


def _preflight(
    args: argparse.Namespace, config: Mapping[str, Any]
) -> tuple[Path, Path, bool]:
    formal = bool(args.allow_formal_run)
    synthetic = bool(args.allow_synthetic_fixture)
    if formal == synthetic:
        raise RuntimeError("exactly one execution mode is required")
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise RuntimeError("invalid EXP-A04 run ID")
    if args.output_dir.exists():
        raise RuntimeError("output directory must not exist")
    if not args.a01_raw.is_file() or not args.pcvt_raw.is_file():
        raise RuntimeError("raw input path missing")
    if synthetic:
        return args.a01_raw, args.pcvt_raw, True
    if not args.reviewed_implementation_sha or not SHA40_PATTERN.fullmatch(
        args.reviewed_implementation_sha
    ):
        raise RuntimeError("formal run requires lowercase reviewed implementation SHA")
    if _git("rev-parse", "HEAD") != args.reviewed_implementation_sha:
        raise RuntimeError("formal reviewed SHA does not match HEAD")
    if _git("branch", "--show-current") != EXPECTED_BRANCH:
        raise RuntimeError("formal branch mismatch")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("formal worktree is not clean")
    if not args.input_manifest:
        raise RuntimeError("formal run requires canonical input manifest")
    manifest_errors = validate_authorized_manifest(
        ROOT, args.input_manifest, reviewed_sha=args.reviewed_implementation_sha
    )
    if manifest_errors:
        raise RuntimeError("authorized manifest gate: " + ";".join(manifest_errors))
    lineage_errors = validate_lineage_inputs(
        ROOT,
        config,
        manifest_path=args.input_manifest,
        reviewed_sha=args.reviewed_implementation_sha,
    )
    if lineage_errors:
        raise RuntimeError("lineage gate: " + ";".join(lineage_errors))
    artifacts = _manifest_artifacts(args.input_manifest)
    a_decl = artifacts.get("exp_a01_raw_metrics", {})
    p_decl = artifacts.get("pcvt_raw_metrics", {})
    if (
        Path(str(a_decl.get("path"))).resolve() != args.a01_raw.resolve()
        or Path(str(p_decl.get("path"))).resolve() != args.pcvt_raw.resolve()
    ):
        raise RuntimeError("raw paths are not the exact manifest declarations")
    return args.a01_raw, args.pcvt_raw, False


def _final_manifest(
    args: argparse.Namespace,
    config: Mapping[str, Any],
    package_root: Path,
    *,
    formal: bool,
    input_manifest: Path | None,
    input_hashes_before: Mapping[str, str],
    input_hashes_after: Mapping[str, str],
    validator_status: str,
    anomaly_status: str,
) -> dict[str, Any]:
    artifacts = _manifest_artifacts(input_manifest) if input_manifest else {}
    return {
        "task_id": TASK_ID,
        "program_id": "EXP-A",
        "run_id": args.run_id,
        "phase": "formal_run" if formal else "synthetic_fixture",
        "final_manifest": True,
        "synthetic_fixture": not formal,
        "formal_data_version": False,
        "formal_run_allowed": formal,
        "formal_run_executed": formal,
        "formal_artifacts_generated": formal,
        "reviewed_implementation_sha": args.reviewed_implementation_sha
        if formal
        else None,
        "input_manifest_path": str(input_manifest) if input_manifest else None,
        "input_manifest_sha256": sha256_file(input_manifest)
        if input_manifest
        else None,
        "input_hashes_before": dict(input_hashes_before),
        "input_hashes_after": dict(input_hashes_after),
        "input_hash_changed_count": sum(
            input_hashes_before.get(key) != input_hashes_after.get(key)
            for key in set(input_hashes_before) | set(input_hashes_after)
        ),
        "input_artifacts": artifacts,
        "validator_status": validator_status,
        "anomaly_status": anomaly_status,
        "output_artifacts": _output_artifacts(package_root),
        "EXP_A05_started": False,
        "A_layer_registered": False,
        "PCATV_created": False,
        "prohibited_outputs_generated": False,
    }


def run(args: argparse.Namespace) -> int:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    staging = args.output_dir.parent / f".{args.output_dir.name}.{args.run_id}.staging"
    failure_root = args.failure_root / args.run_id / "package"
    raw_connections: list[Any] = []
    try:
        a_path, p_path, synthetic = _preflight(args, config)
        staging.mkdir(parents=True, exist_ok=False)
        before = {
            "exp_a01_raw_metrics": sha256_file(a_path),
            "pcvt_raw_metrics": sha256_file(p_path),
        }
        a_conn = duckdb.connect(str(a_path), read_only=True, config={"threads": "1"})
        p_conn = duckdb.connect(str(p_path), read_only=True, config={"threads": "1"})
        raw_connections.extend([a_conn, p_conn])
        analysis = build_analysis(
            a_conn,
            p_conn,
            config,
            a_table=args.a01_table,
            pcvt_table=args.pcvt_table,
            pcvt_path=p_path,
        )
        write_outputs(staging, analysis, run_id=args.run_id)
        core_result = validate_formal_result(
            staging,
            config=config,
            a_raw_path=a_path,
            pcvt_raw_path=p_path,
            a_table=args.a01_table,
            pcvt_table=args.pcvt_table,
            repo_root=ROOT if not synthetic else None,
            input_manifest_path=args.input_manifest,
            reviewed_sha=args.reviewed_implementation_sha,
            run_id=args.run_id,
            synthetic_fixture=synthetic,
            require_final_manifest=False,
        )
        _write_json(staging / "exp_a04_validator_result.json", core_result)
        if core_result["status"] != "passed":
            raise RuntimeError(
                "core_validator_failed:" + ";".join(core_result.get("errors", []))
            )
        anomaly = build_anomaly_scan(
            analysis,
            config,
            synthetic_fixture=synthetic,
            blocking=core_result.get("errors", []),
        )
        _write_json(staging / "exp_a04_anomaly_scan.json", anomaly)
        if anomaly["status"] == "failed":
            raise RuntimeError(
                "blocking_anomaly:" + ";".join(anomaly.get("blocking_anomalies", []))
            )
        (staging / "exp_a04_result_analysis.md").write_text(
            build_result_analysis(
                args.run_id,
                args.reviewed_implementation_sha or "",
                anomaly["status"],
                synthetic_fixture=synthetic,
            ),
            encoding="utf-8",
            newline="\n",
        )
        after = {
            "exp_a01_raw_metrics": sha256_file(a_path),
            "pcvt_raw_metrics": sha256_file(p_path),
        }
        if before != after:
            raise RuntimeError("input_hash_changed")
        final_manifest = _final_manifest(
            args,
            config,
            staging,
            formal=not synthetic,
            input_manifest=args.input_manifest,
            input_hashes_before=before,
            input_hashes_after=after,
            validator_status=core_result["status"],
            anomaly_status=anomaly["status"],
        )
        _write_json(staging / "exp_a04_manifest.json", final_manifest)
        cheap = cheap_validate_final_package(
            staging, run_id=args.run_id, synthetic_fixture=synthetic
        )
        if cheap["status"] != "passed":
            raise RuntimeError(
                "cheap_final_validation_failed:" + ";".join(cheap["errors"])
            )
        for connection in raw_connections:
            connection.close()
        raw_connections.clear()
        staging.replace(args.output_dir)
        print(
            json.dumps(
                {
                    "task_id": TASK_ID,
                    "run_id": args.run_id,
                    "status": "published",
                    "output_dir": str(args.output_dir),
                    "formal": not synthetic,
                    "validator_status": core_result["status"],
                    "anomaly_status": anomaly["status"],
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        for connection in raw_connections:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass
        if staging.is_dir():
            failure_root.mkdir(parents=True, exist_ok=True)
            for path in staging.iterdir():
                if path.suffix.lower() not in {".duckdb", ".parquet"}:
                    target = failure_root / path.name
                    if path.is_file():
                        shutil.copy2(path, target)
            shutil.rmtree(staging, ignore_errors=True)
        failure_root.mkdir(parents=True, exist_ok=True)
        _write_json(
            failure_root.parent / "failure_summary.json",
            {
                "task_id": TASK_ID,
                "run_id": args.run_id,
                "status": "failed",
                "usable_as_formal_result": False,
                "error": str(exc),
                "raw_duckdb_copied": False,
            },
        )
        print(
            json.dumps(
                {
                    "task_id": TASK_ID,
                    "run_id": args.run_id,
                    "status": "failed",
                    "failure_package": str(failure_root),
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--allow-synthetic-fixture", action="store_true")
    mode.add_argument("--allow-formal-run", action="store_true")
    parser.add_argument("--reviewed-implementation-sha")
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--a01-raw", type=Path, required=True)
    parser.add_argument("--pcvt-raw", type=Path, required=True)
    parser.add_argument("--a01-table", default="exp_a01_raw_metrics")
    parser.add_argument("--pcvt-table", default="r0_t04_raw_metric_results")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--failure-root",
        type=Path,
        default=ROOT / "data/generated/sidecar/exp_a04/failures",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
