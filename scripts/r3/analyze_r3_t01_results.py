"""Thin entrypoint for post-validator R3-T01 result analysis."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r3.r3_t01_result_analysis import (  # noqa: E402
    ResultAnalysisError,
    analyze_run_dir,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a validated R3-T01 run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--reviewed-implementation-sha", required=True)
    parser.add_argument("--formal-execution-sha", required=True)
    args = parser.parse_args(argv)
    try:
        analysis_path = analyze_run_dir(
            args.run_dir,
            args.config,
            args.fixture,
            reviewed_implementation_sha=args.reviewed_implementation_sha,
            formal_execution_sha=args.formal_execution_sha,
            root=ROOT,
        )
    except ResultAnalysisError as exc:
        print(f"result_analysis_status=failed error={exc}", file=sys.stderr)
        return 1
    print(f"result_analysis_status=passed path={analysis_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
