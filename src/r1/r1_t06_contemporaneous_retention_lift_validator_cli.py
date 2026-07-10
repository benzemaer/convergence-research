from __future__ import annotations

import argparse
from pathlib import Path

from src.r1.r1_t06_contemporaneous_retention_lift_validator import (
    validate_r1_t06_contemporaneous_retention_lift,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate R1-T06 contemporaneous retention and lift artifacts."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--result-package", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    validate_r1_t06_contemporaneous_retention_lift(
        summary_path=args.summary,
        result_package_path=args.result_package,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
