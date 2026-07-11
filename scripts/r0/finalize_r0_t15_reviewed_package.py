from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r0.r0_t15_final_gate import finalize_r0_t15_reviewed_package  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--review-record", type=Path, required=True)
    parser.add_argument("--review-markdown", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--readme", type=Path, default=ROOT / "docs/tasks/README.md")
    args = parser.parse_args()
    finalize_r0_t15_reviewed_package(
        run_dir=args.run_dir,
        review_record_path=args.review_record,
        review_markdown_path=args.review_markdown,
        analysis_path=args.analysis,
        evidence_path=args.evidence,
        readme_path=args.readme,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
