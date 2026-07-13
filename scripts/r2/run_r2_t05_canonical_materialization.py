from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.r2.r2_t05_canonical_materialization import run_formal


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R2-T05 selected-only canonical materialization")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or ROOT / "data/generated/r2/r2_t05" / f"R2-T05-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    print(run_formal(args.config.resolve(), output.resolve(), ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
