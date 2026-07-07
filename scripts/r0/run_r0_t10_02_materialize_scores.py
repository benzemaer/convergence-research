from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r0.r0_t10_score_materializer import (  # noqa: E402
    DEFAULT_CHUNK_SIZE_SECURITIES,
    DEFAULT_DUCKDB_MEMORY_LIMIT,
    DEFAULT_DUCKDB_THREADS,
    DEFAULT_MAX_WORKERS,
    R0T10ScoreMaterializationError,
    materialize_r0_t05_scores,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Materialize formal R0-T05 strict-past score artifacts."
    )
    parser.add_argument("--r0-t04-evidence", type=Path, required=True)
    parser.add_argument("--r0-t04-duckdb", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
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
        summary = materialize_r0_t05_scores(
            r0_t04_evidence=args.r0_t04_evidence,
            r0_t04_duckdb=args.r0_t04_duckdb,
            output_dir=args.output_dir,
            run_id=args.run_id,
            code_commit=args.code_commit,
            max_workers=args.max_workers,
            duckdb_threads=args.duckdb_threads,
            duckdb_memory_limit_per_worker=args.duckdb_memory_limit_per_worker,
            chunk_size_securities=args.chunk_size_securities,
            resume=args.resume,
        )
    except R0T10ScoreMaterializationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary.get("status") in {"completed", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
