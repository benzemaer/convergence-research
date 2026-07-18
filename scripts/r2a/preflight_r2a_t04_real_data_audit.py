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

from src.r2a.r2a_t04_real_data_audit import (  # noqa: E402
    load_market_source_spec,
    run_real_input_smoke,
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
    return parser.parse_args()


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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
    if args.mode == "thread-benchmark":
        result = run_thread_benchmark(
            score_database=args.score_db,
            score_release_id=config["score_release"]["score_release_id"],
            canonical_request=request,
            scratch_directory=args.preflight_root / ".thread-benchmark-scratch",
        )
        destination = args.preflight_root / "thread_benchmark_receipt.json"
    else:
        if args.market_source_spec is None:
            raise RuntimeError("market_source_spec_required")
        benchmark = json.loads(
            (args.preflight_root / "thread_benchmark_receipt.json").read_text(
                encoding="utf-8"
            )
        )
        spec = load_market_source_spec(args.market_source_spec)
        destination = args.preflight_root / "real_input_smoke_receipt.json"
        result = run_real_input_smoke(
            config=config,
            score_database=args.score_db,
            market_database=_market_database(
                args.market_source_spec, str(spec["database_basename"])
            ),
            market_source_spec=spec,
            canonical_request=request,
            benchmark_receipt=benchmark,
            scratch_directory=args.preflight_root / ".real-smoke-scratch",
            receipt_path=destination,
        )
    _write(destination, result)
    if _git_status() != before_status:
        raise RuntimeError("preflight_modified_git_worktree")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
