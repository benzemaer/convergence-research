from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from .r1_t08_global_nested_null_models import (
    CONFIG_PATH,
    ROOT,
    git_commit,
    run_r1_t08_global_nested_null_models,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--code-commit")
    parser.add_argument("--n-perm", type=int)
    parser.add_argument("--skip-input-hash-check", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id or f"R1-T08-{datetime.now(UTC).strftime('%Y%m%dT%H%MZ')}"
    output_dir = args.output_dir or ROOT / "data/generated/r1/r1_t08" / run_id
    run_r1_t08_global_nested_null_models(
        config_path=args.config,
        output_dir=output_dir,
        run_id=run_id,
        code_commit=args.code_commit or git_commit(),
        verify_input_hashes=not args.skip_input_hash_check,
        n_perm_override=args.n_perm,
    )
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
