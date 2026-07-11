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
    parser.add_argument("--review-record", type=Path, required=True)
    parser.add_argument("--review-markdown", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    task = import_module("src.r1.r1_t14_01_layer_q_response_diagnostic")
    task.finalize_reviewed_result_package(
        run_dir=args.run_dir,
        review_record_path=args.review_record,
        review_markdown_path=args.review_markdown,
        evidence_path=args.evidence,
        readme_path=ROOT / "docs/tasks/README.md",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
