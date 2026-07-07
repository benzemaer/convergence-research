from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r0.r0_t10_raw_metric_materializer import (  # noqa: E402
    DEFAULT_CHUNK_SIZE_SECURITIES,
    DEFAULT_DUCKDB_MEMORY_LIMIT,
    DEFAULT_DUCKDB_THREADS,
    DEFAULT_MAX_WORKERS,
    DEFAULT_SOURCE_TABLE,
    R0T10MaterializationError,
    materialize_r0_t04_raw_metrics,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize R0-T04 raw metrics from authorized D3 observations."
    )
    parser.add_argument("--d3-duckdb", type=Path, required=True)
    parser.add_argument("--source-table", default=DEFAULT_SOURCE_TABLE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="R0-T10 materializer workers only; allowed range is 1..8.",
    )
    parser.add_argument("--duckdb-threads", type=int, default=DEFAULT_DUCKDB_THREADS)
    parser.add_argument(
        "--duckdb-memory-limit-per-worker",
        default=DEFAULT_DUCKDB_MEMORY_LIMIT,
    )
    parser.add_argument(
        "--chunk-size-securities",
        type=int,
        default=DEFAULT_CHUNK_SIZE_SECURITIES,
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = materialize_r0_t04_raw_metrics(
            d3_duckdb=args.d3_duckdb,
            source_table=args.source_table,
            output_dir=args.output_dir,
            run_id=args.run_id,
            code_commit=args.code_commit,
            max_workers=args.max_workers,
            duckdb_threads=args.duckdb_threads,
            duckdb_memory_limit_per_worker=args.duckdb_memory_limit_per_worker,
            chunk_size_securities=args.chunk_size_securities,
            resume=args.resume,
        )
    except R0T10MaterializationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
