from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from src.r0.r0_t10_full_grid_validator import (
    R0T10FullGridValidationError,
    validate_full_grid,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate R0-T10-05 full-grid output.")
    parser.add_argument("--authorized-input-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_full_grid(
            authorized_input_manifest=args.authorized_input_manifest,
            output_dir=args.output_dir,
        )
    except R0T10FullGridValidationError as exc:
        print(f"blocked: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
