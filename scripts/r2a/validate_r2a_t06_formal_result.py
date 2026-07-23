"""Validate a persisted R2A-T06 result package and artifact analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2a.r2a_t06_formal_result_analysis import analyze_persisted_formal_artifacts
from src.r2a.r2a_t06_validator import validate_t06_result_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    package = json.loads(
        (args.run_root / "result_package.json").read_text(encoding="utf-8")
    )
    validate_t06_result_package(package)
    analysis = analyze_persisted_formal_artifacts(args.run_root / "scientific")
    if analysis["result_analysis_status"] != package["result_analysis_status"]:
        raise RuntimeError("result_analysis_status_mismatch")
    print(json.dumps(analysis, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
