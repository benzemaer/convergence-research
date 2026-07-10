from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from src.r1.r1_t07_p_onset_fixed_lag_relations import (
    CONFIG_PATH,
    ROOT,
    run_r1_t07_p_onset_fixed_lag_relations,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--code-commit")
    parser.add_argument("--skip-input-hash-check", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id or f"R1-T07-{datetime.now(UTC).strftime('%Y%m%dT%H%MZ')}"
    output_dir = args.output_dir or ROOT / "data/generated/r1/r1_t07" / run_id
    code_commit = args.code_commit or _git_commit()
    run_r1_t07_p_onset_fixed_lag_relations(
        config_path=args.config,
        output_dir=output_dir,
        run_id=run_id,
        code_commit=code_commit,
        verify_input_hashes=not args.skip_input_hash_check,
    )
    print(output_dir)
    return 0


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
