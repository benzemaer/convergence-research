from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r1.r1_t14_02_final_gate import (  # noqa: E402
    finalize_r1_t14_02,
    validate_r1_t14_02_final_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--review-record", type=Path, required=True)
    parser.add_argument("--review-markdown", type=Path, required=True)
    parser.add_argument("--final-evidence", type=Path, required=True)
    parser.add_argument("--task-index", type=Path, required=True)
    args = parser.parse_args()
    finalize_r1_t14_02(
        run_dir=args.run_dir,
        review_record_path=args.review_record,
        review_markdown_path=args.review_markdown,
        final_evidence_path=args.final_evidence,
        task_index_path=args.task_index,
    )
    validate_r1_t14_02_final_gate(run_dir=args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
