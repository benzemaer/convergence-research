"""Thin entrypoint for the post-approval R3-T01 formal run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r3.r3_t01_protocol import (  # noqa: E402, I001
    ProtocolContractError,
    execute_formal_run,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run R3-T01 after implementation approval."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--reviewed-implementation-sha", required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        run_dir = execute_formal_run(
            args.config,
            args.reviewed_implementation_sha,
            root=ROOT,
            run_id=args.run_id,
        )
    except ProtocolContractError as exc:
        print(f"formal_run_status=blocked error={exc}", file=sys.stderr)
        return 1
    print(f"formal_run_status=completed run_dir={run_dir.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
