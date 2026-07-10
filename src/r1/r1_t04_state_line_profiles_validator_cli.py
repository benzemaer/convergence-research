from __future__ import annotations

import argparse
from pathlib import Path

from .r1_t04_state_line_profiles_validator import validate_r1_t04_state_line_profiles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate R1-T04 state-line profile artifacts.")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--result-package")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    validate_r1_t04_state_line_profiles(summary_path=Path(args.summary), result_package_path=Path(args.result_package) if args.result_package else None, output_path=Path(args.output) if args.output else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
