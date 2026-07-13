from __future__ import annotations

import argparse
from pathlib import Path

from src.r2.r2_t06_dual_state_machine_replay import run_formal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_formal(args.config.resolve(), args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
