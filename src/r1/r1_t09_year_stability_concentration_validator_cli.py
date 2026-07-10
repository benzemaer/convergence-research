from __future__ import annotations

import argparse
from pathlib import Path

from .r1_t09_year_stability_concentration import CONFIG_PATH
from .r1_t09_year_stability_concentration_validator import validate_r1_t09_outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate_r1_t09_outputs(
        config_path=args.config, output_dir=args.output_dir, output_path=args.output
    )
    return 0 if result["validator_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
