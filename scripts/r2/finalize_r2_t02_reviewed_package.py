import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.r2.r2_t02_final_gate import finalize_r2_t02_reviewed_package  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--review-record", type=Path, required=True)
    p.add_argument("--reviewed-head", required=True)
    p.add_argument("--task-index", type=Path, default=ROOT / "docs/tasks/README.md")
    p.add_argument("--premerge-full-evidence", type=Path, required=True)
    a = p.parse_args()
    finalize_r2_t02_reviewed_package(
        output_dir=a.output_dir,
        review_record_path=a.review_record,
        reviewed_head=a.reviewed_head,
        task_index_path=a.task_index,
        premerge_full_evidence_path=a.premerge_full_evidence,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
