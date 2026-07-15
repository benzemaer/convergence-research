"""Thin terminal validator entrypoint for R3-T01."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r3.r3_t01_final_validator import validate_final_run_dir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the terminal R3-T01 result package."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = validate_final_run_dir(args.run_dir, root=ROOT)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
