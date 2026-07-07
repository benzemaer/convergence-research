from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from src.r0.r0_t10_full_grid_materializer import (
    DEFAULT_DUCKDB_MEMORY_LIMIT,
    DEFAULT_DUCKDB_THREADS,
    DEFAULT_MAX_WORKERS,
    R0T10FullGridMaterializationError,
    materialize_full_grid,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run R0-T10-05 artifact-backed 27-config full-grid materialization."
    )
    parser.add_argument("--authorized-input-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--duckdb-threads", type=int, default=DEFAULT_DUCKDB_THREADS)
    parser.add_argument(
        "--duckdb-memory-limit-per-worker", default=DEFAULT_DUCKDB_MEMORY_LIMIT
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = materialize_full_grid(
            authorized_input_manifest=args.authorized_input_manifest,
            output_dir=args.output_dir,
            run_id=args.run_id,
            code_commit=args.code_commit,
            max_workers=args.max_workers,
            duckdb_threads=args.duckdb_threads,
            duckdb_memory_limit_per_worker=args.duckdb_memory_limit_per_worker,
            resume=args.resume,
        )
    except R0T10FullGridMaterializationError as exc:
        print(f"failed: {exc}")
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
