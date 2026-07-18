"""Run a synthetic R2A-T01 score release; formal execution is fail-closed."""

from __future__ import annotations

import argparse

from src.r2a.r2a_t01_score_release import materialize_score_release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorized-input-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--score-release-id", required=True)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--execution-commit")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic", action="store_true")
    mode.add_argument("--formal", action="store_true")
    args = parser.parse_args()
    materialize_score_release(
        authorized_input_manifest=args.authorized_input_manifest,
        output_dir=args.output_dir,
        run_id=args.run_id,
        score_release_id=args.score_release_id,
        worker_count=args.worker_count,
        synthetic_only=args.synthetic,
        execution_commit=args.execution_commit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
