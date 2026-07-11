import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2.r2_t01_final_gate import (  # noqa: E402
    finalize_r2_t01_reviewed_package,
    validate_r2_t01_final_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--review-record", required=True, type=Path)
    parser.add_argument("--review-markdown", required=True, type=Path)
    parser.add_argument("--final-evidence", required=True, type=Path)
    parser.add_argument("--task-index", default="docs/tasks/README.md", type=Path)
    args = parser.parse_args()
    package = finalize_r2_t01_reviewed_package(
        output_dir=args.output,
        review_record_path=args.review_record,
        review_markdown_path=args.review_markdown,
        final_evidence_path=args.final_evidence,
        task_index_path=args.task_index,
    )
    validation = validate_r2_t01_final_gate(output_dir=args.output)
    print(
        json.dumps({"package": package, "validation": validation}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
