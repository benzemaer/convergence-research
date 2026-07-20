"""Controlled R2A-T05 formal entry; no arbitrary request parameters are accepted."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t05_formal_execution import (  # noqa: E402
    FORMAL_CONFIG_PATH,
    FormalExecutionError,
    preflight_formal_execution,
    run_formal_execution,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or preflight the fixed R2A-T05 formal execution contract."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=FORMAL_CONFIG_PATH)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--operator-authorized",
        action="store_true",
        help="Required by the future owner-authorized execution path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.preflight_only:
            result = preflight_formal_execution(
                manifest_path=args.manifest,
                config_path=args.config,
                verify_manifest_files=False,
            )
        else:
            result = run_formal_execution(
                manifest_path=args.manifest,
                config_path=args.config,
                operator_authorized=args.operator_authorized,
            )
    except FormalExecutionError as error:
        print(f"formal_execution_status=blocked reason={error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
