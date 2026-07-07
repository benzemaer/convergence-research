from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from src.r0.r0_t10_confirmation_interval_materialization_validator import (
    R0T10ConfirmationIntervalValidationError,
    validate_materialization,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate formal R0-T07 confirmation and interval artifacts."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--r0-t06-evidence", type=Path, required=True)
    parser.add_argument("--nested-daily-state-duckdb", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_materialization(
            args.output_dir,
            r0_t06_evidence=args.r0_t06_evidence,
            nested_daily_state_duckdb=args.nested_daily_state_duckdb,
        )
    except R0T10ConfirmationIntervalValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
