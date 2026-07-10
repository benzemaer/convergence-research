from __future__ import annotations

# ruff: noqa: E501
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r1.r1_t14_02_author_package import build_r1_t14_02_author_package  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    build_r1_t14_02_author_package(
        run_dir=args.run_dir, analysis_path=args.analysis, evidence_path=args.evidence
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
