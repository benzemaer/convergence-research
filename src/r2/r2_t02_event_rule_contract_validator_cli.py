from __future__ import annotations

import argparse
from pathlib import Path

from src.r2.r2_t02_event_rule_contract_validator import validate_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_contract(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
