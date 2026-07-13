from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.r2.r2_t04_freeze_decision import validate_phase_a
from src.r2.r2_t04_independent_validator import validate_phase_b


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase-b", action="store_true")
    args = parser.parse_args()
    report = (
        validate_phase_b(args.output_dir)
        if args.phase_b
        else validate_phase_a(args.output_dir)
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
