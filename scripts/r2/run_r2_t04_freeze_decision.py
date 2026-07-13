from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.r2.r2_t04_freeze_decision import run_phase_a
from src.r2.r2_t04_phase_b import run_phase_b


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phase-b", action="store_true")
    parser.add_argument("--decision-time-utc")
    args = parser.parse_args()
    if args.phase_b:
        run_phase_b(args.output_dir, decision_time_utc=args.decision_time_utc)
    else:
        run_phase_a(args.config, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
