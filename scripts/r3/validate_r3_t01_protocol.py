"""Thin entrypoint for the independent R3-T01 validator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r3.r3_t01_validator import validate_run_dir  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an R3-T01 formal run directory."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    run_dir = args.run_dir if args.run_dir.is_absolute() else ROOT / args.run_dir
    report = validate_run_dir(run_dir, root=ROOT)
    print(
        json.dumps(
            {
                "status": "passed" if report.passed else "failed",
                "errors": report.errors,
                "synthetic_case_results": report.synthetic_case_results,
                "double_rebuild_hash": report.double_rebuild_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
