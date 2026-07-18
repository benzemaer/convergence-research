"""Generate R2A-T01 result analysis from validated actual artifacts."""

from __future__ import annotations

import argparse

from src.r2a.r2a_t01_result_analysis import analyze_score_release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir")
    args = parser.parse_args()
    analyze_score_release(args.package_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
