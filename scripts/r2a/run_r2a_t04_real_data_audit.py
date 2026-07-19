"""Run the single authorized R2A-T04 Score-only full-universe audit."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t04_execution_gate import (  # noqa: E402
    validate_score_formal_execution_gate,
)
from src.r2a.r2a_t04_request_panel import (  # noqa: E402
    build_request_panel,
    load_audit_config,
)
from src.r2a.r2a_t04_score_audit import run_score_formal_audit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the authorized R2A-T04 Score-only audit."
    )
    parser.add_argument("--score-db", type=Path, required=True)
    parser.add_argument("--thread-benchmark-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--formal-authorization-id", required=True)
    return parser.parse_args()


def _git_output(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], text=True).strip()


def main() -> int:
    args = parse_args()
    if _git_output("status", "--porcelain"):
        raise RuntimeError("formal_worktree_not_clean")
    head = _git_output("rev-parse", "HEAD")
    parent = _git_output("rev-parse", "HEAD^")
    config = load_audit_config()
    if args.formal_authorization_id != config["formal_authorization_id"]:
        raise RuntimeError("formal_authorization_id_mismatch")
    panel = build_request_panel(config)
    gate = validate_score_formal_execution_gate(
        config=config,
        authorization_head=head,
        authorization_parent=parent,
        score_database=args.score_db,
        thread_benchmark_receipt_path=args.thread_benchmark_receipt,
        panel=panel,
    )
    result = run_score_formal_audit(
        config=config,
        panel=panel,
        score_database=args.score_db,
        output_root=args.output_root,
        review_output=args.review_output,
        execution_gate=gate,
    )
    print(json.dumps({"execution_head": head, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
