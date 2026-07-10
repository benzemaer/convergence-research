from __future__ import annotations

import argparse
from pathlib import Path

from .r_formal_experiment_package_validator import validate_formal_experiment_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an R1-R6 formal experiment result package."
    )
    parser.add_argument("--result-package", required=True)
    parser.add_argument("--mode", choices=("author-draft", "final-gate"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    validate_formal_experiment_package(
        result_package_path=Path(args.result_package),
        mode=args.mode,
        output_path=Path(args.output),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
