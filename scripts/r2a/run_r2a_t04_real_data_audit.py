"""Run the single authorized R2A-T04 full-universe audit."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from src.r2a.r2a_t04_real_data_audit import (
    load_market_source_spec,
    run_formal_audit,
)
from src.r2a.r2a_t04_request_panel import (
    build_request_panel,
    load_audit_config,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the authorized R2A-T04 audit.")
    parser.add_argument("--score-db", type=Path, required=True)
    parser.add_argument("--market-source-spec", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--formal-authorization-id", required=True)
    return parser.parse_args()


def _market_database(spec_path: Path, basename: str) -> Path:
    candidates: list[Path] = []
    environment = os.environ.get("R2A_T04_MARKET_DB")
    if environment:
        candidates.append(Path(environment))
    local = spec_path.parent / basename
    if local.is_file():
        candidates.append(local)
    sibling_root = (
        Path(__file__).resolve().parents[2].parent / "convergence-research-inputs"
    )
    if sibling_root.is_dir():
        candidates.extend(sibling_root.rglob(basename))
    unique = {path.resolve() for path in candidates if path.is_file()}
    if len(unique) != 1:
        raise RuntimeError(f"market_context_source_not_uniquely_bound:{len(unique)}")
    return unique.pop()


def _git_output(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], text=True).strip()


def main() -> int:
    args = parse_args()
    config = load_audit_config()
    if args.formal_authorization_id != config["formal_authorization_id"]:
        raise RuntimeError("formal_authorization_id_mismatch")
    if _git_output("status", "--porcelain"):
        raise RuntimeError("formal_worktree_not_clean")
    head = _git_output("rev-parse", "HEAD")
    parent = _git_output("rev-parse", "HEAD^")
    if parent != config["reviewed_harness_head"]:
        raise RuntimeError("authorization_parent_not_reviewed_harness")
    spec = load_market_source_spec(args.market_source_spec)
    receipt_path = (
        args.market_source_spec.parent / "preflight/real_input_smoke_receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    result = run_formal_audit(
        config=config,
        panel=build_request_panel(config),
        score_database=args.score_db,
        market_database=_market_database(
            args.market_source_spec, str(spec["database_basename"])
        ),
        market_source_spec=spec,
        output_root=args.output_root,
        review_output=args.review_output,
        preflight_receipt=receipt,
    )
    print(json.dumps({"execution_head": head, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
