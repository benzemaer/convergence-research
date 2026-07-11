import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2.r2_t02_premerge_full_evidence import (  # noqa: E402
    build_premerge_full_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    args = parser.parse_args()
    build_premerge_full_evidence(
        runner_result_path=args.runner_result,
        output_path=args.output,
        tested_head=args.tested_head,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
