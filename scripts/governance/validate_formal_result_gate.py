from __future__ import annotations

import argparse
from pathlib import Path

from src.governance.formal_result_gate import validate_formal_result_gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a generic formal-result gate."
    )
    parser.add_argument("--submission-manifest", required=True, type=Path)
    parser.add_argument("--github-reviews-json", required=True, type=Path)
    parser.add_argument("--full-profile-result", required=True, type=Path)
    parser.add_argument("--current-head-sha", required=True)
    parser.add_argument("--pull-request-number", required=True, type=int)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = validate_formal_result_gate(
        submission_manifest=args.submission_manifest,
        github_reviews_json=args.github_reviews_json,
        full_profile_result=args.full_profile_result,
        current_head_sha=args.current_head_sha,
        pull_request_number=args.pull_request_number,
        repository=args.repository,
        output=args.output,
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
