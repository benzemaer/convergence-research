from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from src.r0.r0_t10_nested_state_materialization_validator import (
    R0T10NestedStateValidationError,
    validate_materialization,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate R0-T10-03 generated R0-T06 nested state artifacts."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--r0-t05-evidence", type=Path, required=True)
    parser.add_argument("--indicator-score-duckdb", type=Path, required=True)
    parser.add_argument("--dimension-score-duckdb", type=Path, required=True)
    parser.add_argument("--common-eligible-duckdb", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_materialization(
            output_dir=args.output_dir,
            r0_t05_evidence=args.r0_t05_evidence,
            indicator_score_duckdb=args.indicator_score_duckdb,
            dimension_score_duckdb=args.dimension_score_duckdb,
            common_eligible_duckdb=args.common_eligible_duckdb,
        )
    except R0T10NestedStateValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
