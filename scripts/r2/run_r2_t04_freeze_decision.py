from __future__ import annotations

import argparse
from pathlib import Path

from src.r2.r2_t04_freeze_decision import run_phase_a


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_phase_a(args.config, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
