from __future__ import annotations

import argparse
from pathlib import Path

from src.r1.r1_t05_indicator_intralayer_diagnostics import (
    CONFIG_PATH,
    ROOT,
    run_r1_t05_indicator_intralayer_diagnostics,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run R1-T05 indicator intralayer diagnostics."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--skip-input-hash-check",
        action="store_true",
        help="Only for synthetic/local tests; formal runs must verify input hashes.",
    )
    args = parser.parse_args(argv)
    run_r1_t05_indicator_intralayer_diagnostics(
        config_path=args.config,
        output_dir=args.output_dir,
        run_id=args.run_id,
        code_commit=args.code_commit,
        root=ROOT,
        verify_input_hashes=not args.skip_input_hash_check,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
