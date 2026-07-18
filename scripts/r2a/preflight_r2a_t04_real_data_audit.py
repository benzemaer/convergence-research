"""Local-only thread benchmark and real-input smoke for R2A-T04."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t04_execution_gate import (  # noqa: E402
    execute_bound_real_input_smoke,
    market_source_spec_identity,
)
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
    parser = argparse.ArgumentParser(description="Run local-only R2A-T04 preflight.")
    parser.add_argument("mode", choices=("thread-benchmark", "real-input-smoke"))
    parser.add_argument("--score-db", type=Path, required=True)
    parser.add_argument("--preflight-root", type=Path, required=True)
    parser.add_argument("--market-source-spec", type=Path)
    parser.add_argument("--thread-benchmark-receipt", type=Path)
    parser.add_argument("--authorization-quality")
    return parser.parse_args()


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _market_database(spec_path: Path, basename: str) -> Path:
    environment = os.environ.get("R2A_T04_MARKET_DB")
    candidates = [Path(environment)] if environment else []
    candidates.append(spec_path.parent / basename)
    sibling = Path(__file__).resolve().parents[2].parent / "convergence-research-inputs"
    if sibling.is_dir():
        candidates.extend(sibling.rglob(basename))
    unique = {path.resolve() for path in candidates if path.is_file()}
    if len(unique) != 1:
        raise RuntimeError(f"market_context_source_not_uniquely_bound:{len(unique)}")
    return unique.pop()


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
    if args.mode == "thread-benchmark":
        verify_file_identity(
            args.score_db,
            expected_sha256=config["score_release"]["sha256"],
            expected_byte_size=config["score_release"]["byte_size"],
        )
        destination = args.preflight_root / "thread_benchmark_receipt.json"
        result = run_thread_benchmark(
            score_database=args.score_db,
            score_release_id=config["score_release"]["score_release_id"],
            canonical_request=request,
            scratch_directory=args.preflight_root / ".thread-benchmark-scratch",
            receipt_path=destination,
            failure_evidence_root=(
                args.preflight_root / "thread-benchmark-failure-evidence"
            ),
            implementation_head=_git_head(),
        )
    else:
        if (
            args.market_source_spec is None
            or args.thread_benchmark_receipt is None
            or args.authorization_quality is None
        ):
            raise RuntimeError("market_source_spec_required")
        spec_identity = market_source_spec_identity(args.market_source_spec)
        destination = args.preflight_root / "real_input_smoke_receipt.json"
        result = execute_bound_real_input_smoke(
            config=config,
            authorization_head=_git_head(),
            authorization_parent=subprocess.check_output(
                ["git", "rev-parse", "HEAD^"], text=True
            ).strip(),
            authorization_quality=args.authorization_quality,
            score_database=args.score_db,
            thread_benchmark_receipt_path=args.thread_benchmark_receipt,
            market_source_spec_path=args.market_source_spec,
            market_database=_market_database(
                args.market_source_spec, str(spec_identity["database_basename"])
            ),
            canonical_request=request,
            scratch_directory=args.preflight_root / ".real-smoke-scratch",
            receipt_path=destination,
        )
    if _git_status() != before_status:
        raise RuntimeError("preflight_modified_git_worktree")
    print(json.dumps(result, sort_keys=True))
    return _result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
