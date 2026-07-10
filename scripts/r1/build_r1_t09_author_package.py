from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--engineering-validation", type=Path, required=True)
    args = parser.parse_args()
    task = import_module("src.r1.r1_t09_year_stability_concentration")
    task.build_author_draft_result_package(
        run_dir=args.run_dir,
        analysis_path=args.analysis,
        evidence_path=args.evidence,
        engineering_validation_path=args.engineering_validation,
        readme_path=ROOT / "docs/tasks/README.md",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
