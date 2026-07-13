from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.r2.r2_t05_independent_validator import validate_formal_output  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the independent R2-T05 validator")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    result = validate_formal_output(args.run_dir.resolve(), ROOT)
    print(result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
