"""Run the local-only frozen R2A-T04 thread benchmark contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t04_real_data_audit import (  # noqa: E402
    run_thread_benchmark,
    verify_file_identity,
)
from src.r2a.r2a_t04_request_panel import (  # noqa: E402
    build_request_panel,
    canonical_envelope,
    load_audit_config,
    request_by_name,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local-only R2A-T04 thread benchmark."
    )
    parser.add_argument("mode", choices=("thread-benchmark",))
    parser.add_argument("--score-db", type=Path, required=True)
    parser.add_argument("--preflight-root", type=Path, required=True)
    return parser.parse_args()


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _result_exit_code(result: dict[str, object]) -> int:
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    args = parse_args()
    before_status = _git_status()
    if before_status:
        raise RuntimeError("preflight_worktree_not_clean")
    config = load_audit_config()
    panel = build_request_panel(config)
    request = canonical_envelope(request_by_name("D05_PCAVT_q15_k3", panel))
    verify_file_identity(
        args.score_db,
        expected_sha256=config["score_release"]["sha256"],
        expected_byte_size=config["score_release"]["byte_size"],
    )
    result = run_thread_benchmark(
        score_database=args.score_db,
        score_release_id=config["score_release"]["score_release_id"],
        canonical_request=request,
        scratch_directory=args.preflight_root / ".thread-benchmark-scratch",
        receipt_path=args.preflight_root / "thread_benchmark_receipt.json",
        failure_evidence_root=(
            args.preflight_root / "thread-benchmark-failure-evidence"
        ),
        implementation_head=_git_head(),
    )
    if _git_status() != before_status:
        raise RuntimeError("preflight_modified_git_worktree")
    print(json.dumps(result, sort_keys=True))
    return _result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
