from __future__ import annotations

# ruff: noqa: E501
import argparse
from datetime import UTC, datetime
from pathlib import Path

from .r1_t14_02_formal_structural_revalidation import (
    CONFIG_PATH,
    git_commit,
    run_r1_t14_02_formal_structural_revalidation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/generated/r1/r1_t14_02")
    )
    parser.add_argument("--run-id")
    parser.add_argument("--code-commit")
    parser.add_argument("--skip-input-hash-verification", action="store_true")
    parser.add_argument("--n-perm-override", type=int)
    args = parser.parse_args()
    run_id = args.run_id or f"R1-T14-02-{datetime.now(UTC).strftime('%Y%m%dT%H%MZ')}"
    run_r1_t14_02_formal_structural_revalidation(
        config_path=args.config,
        output_dir=args.output_root / run_id,
        run_id=run_id,
        code_commit=args.code_commit or git_commit(),
        verify_input_hashes=not args.skip_input_hash_verification,
        n_perm_override=args.n_perm_override,
    )
    return 0
