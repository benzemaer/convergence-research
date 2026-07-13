from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.r2.r2_t05_independent_validator import validate_committed_artifacts  # noqa: E402, I001


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate committed R2-T05 compact artifacts"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--commit")
    args = parser.parse_args()
    result = validate_committed_artifacts(args.run_dir.resolve(), ROOT, args.commit)
    print(result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
