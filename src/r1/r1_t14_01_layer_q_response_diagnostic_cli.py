from __future__ import annotations

import argparse
from pathlib import Path

from .r1_t14_01_layer_q_response_diagnostic import (
    CONFIG_PATH,
    git_commit,
    run_r1_t14_01_layer_q_response_diagnostic,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", default=None)
    parser.add_argument("--skip-input-hash-verification", action="store_true")
    args = parser.parse_args()
    run_r1_t14_01_layer_q_response_diagnostic(
        config_path=args.config,
        output_dir=args.output_dir,
        run_id=args.run_id,
        code_commit=args.code_commit or git_commit(),
        verify_input_hashes=not args.skip_input_hash_verification,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
