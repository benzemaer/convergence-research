from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.common.canonical_io import write_json
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
    validate_runtime_gates(
        database, args.output_dir, Path(config["inputs"]["hard_gate_registry_path"])
    )
    validate_independently(database, args.output_dir)
    summary = json.loads(
        (args.output_dir / "r2_t03_experiment_summary.json").read_text(encoding="utf-8")
    )
    comparison_payload = {
        "execution_commit": summary["execution_commit"],
        "config_sha256": summary["config_sha256"],
        "database_fingerprint": summary["database_fingerprint"],
        "runtime_gate_results_sha256": _sha(
            args.output_dir / "r2_t03_runtime_gate_results.csv"
        ),
        "runtime_validation_canonical_sha256": _normalized_json_sha(
            args.output_dir / "r2_t03_runtime_gate_validation.json"
        ),
        "independent_recalculation_sha256": _sha(
            args.output_dir / "r2_t03_independent_recalculation.csv"
        ),
        "independent_validation_canonical_sha256": _normalized_json_sha(
            args.output_dir / "r2_t03_independent_validation.json"
        ),
        "source_readiness_sha256": summary["source_readiness_sha256"],
        "input_binding_sha256": summary["input_binding_sha256"],
    }
    post = {
        "task_id": "R2-T03",
        "run_id": args.output_dir.name,
        "execution_commit": summary["execution_commit"],
        "config_sha256": summary["config_sha256"],
        "database_fingerprint": summary["database_fingerprint"],
        "runtime_gate_results_sha256": _sha(
            args.output_dir / "r2_t03_runtime_gate_results.csv"
        ),
        "runtime_validation_sha256": _sha(
            args.output_dir / "r2_t03_runtime_gate_validation.json"
        ),
        "independent_recalculation_sha256": _sha(
            args.output_dir / "r2_t03_independent_recalculation.csv"
        ),
        "independent_validation_sha256": _sha(
            args.output_dir / "r2_t03_independent_validation.json"
        ),
        "source_readiness_sha256": summary["source_readiness_sha256"],
        "input_binding_sha256": summary["input_binding_sha256"],
        "comparison_fingerprint": _post_comparison_fingerprint(comparison_payload),
        "comparison_payload": comparison_payload,
    }
    write_json(args.output_dir / "r2_t03_post_validation_fingerprint.json", post)
    if summary.get("baseline_only"):
        baseline_path = args.output_dir / "r2_t03_single_worker_baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["post_validation_fingerprint"] = post
        write_json(baseline_path, baseline)
    if args.baseline_json:
        baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
        required = [
            "execution_commit",
            "config_sha256",
            "source_readiness_sha256",
            "input_binding_sha256",
            "database_fingerprint",
            "post_validation_comparison_fingerprint",
        ]
        formal = {
            **summary,
            "post_validation_comparison_fingerprint": post["comparison_fingerprint"],
        }
        baseline = {
            **baseline,
            "post_validation_comparison_fingerprint": baseline.get(
                "post_validation_fingerprint", {}
            ).get("comparison_fingerprint"),
        }
        for field in required:
            if baseline.get(field) != formal.get(field):
                raise RuntimeError(f"single_worker_baseline_{field}_mismatch")
    return 0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_json_sha(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    for key in ("run_id", "database_path", "output_dir"):
        value.pop(key, None)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _post_comparison_fingerprint(payload: dict[str, object]) -> str:
    """Hash only run-invariant validation content for baseline/formal equality."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
