from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.r0.main_grid_materialization_runner import (
    MAX_WORKERS_DEFAULT,
    R0T09MaterializationError,
    run_main_grid_materialization,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run R0-T09 main-grid candidate artifact materialization."
    )
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS_DEFAULT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only-config")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--code-commit")
    parser.add_argument(
        "--repository",
        default="benzemaer/convergence-research",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_main_grid_materialization(
            input_manifest=args.input_manifest,
            output_dir=args.output_dir,
            max_workers=args.max_workers,
            resume=args.resume,
            only_config=args.only_config,
            dry_run=args.dry_run,
            run_id=args.run_id,
            code_commit=args.code_commit,
            repository=args.repository,
        )
    except R0T09MaterializationError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
