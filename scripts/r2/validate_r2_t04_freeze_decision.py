from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2.r2_t04_freeze_decision import validate_phase_a


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = validate_phase_a(args.output_dir)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
