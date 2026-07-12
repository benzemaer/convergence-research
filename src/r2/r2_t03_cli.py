from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2.r2_t03_event_zone_scan import run_scan
from src.r2.r2_t03_independent_validator import validate_independently
from src.r2.r2_t03_result_analysis import (
    build_result_package,
    validate_committed_artifacts,
)
from src.r2.r2_t03_runtime_gates import validate_runtime_gates


def run_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker-count", type=int)
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    run_scan(
        args.config,
        args.output_dir,
        worker_count=args.worker_count,
        baseline_only=args.baseline_only,
    )
    return 0


def validate_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-json", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    database = args.output_dir / config["runtime"]["output_database_name"]
    if args.baseline_json:
        baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
        summary = json.loads(
            (args.output_dir / "r2_t03_experiment_summary.json").read_text(
                encoding="utf-8"
            )
        )
        if baseline["database_fingerprint"] != summary["database_fingerprint"]:
            raise RuntimeError("single_worker_baseline_fingerprint_mismatch")
    validate_runtime_gates(
        database, args.output_dir, Path(config["inputs"]["hard_gate_registry_path"])
    )
    validate_independently(database, args.output_dir)
    return 0


def analyze_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    build_result_package(args.output_dir)
    return 0


def committed_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_committed_artifacts(args.output_dir)
    return 0
