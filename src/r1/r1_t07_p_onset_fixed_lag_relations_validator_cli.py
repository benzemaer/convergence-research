from __future__ import annotations

import argparse
from pathlib import Path

from src.r1.r1_t07_p_onset_fixed_lag_relations_validator import (
    validate_r1_t07_p_onset_fixed_lag_relations,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--result-package", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    validate_r1_t07_p_onset_fixed_lag_relations(
        summary_path=args.summary,
        result_package_path=args.result_package,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
