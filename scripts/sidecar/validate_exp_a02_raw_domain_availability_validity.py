"""Standalone independent validator for an EXP-A02 compact package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_a02_raw_domain_availability_validity_validator import (  # noqa: E402
    CONFIG_PATH,
    load_json,
    validate_package,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--allow-synthetic-fixture", action="store_true")
    modes.add_argument("--allow-formal-run", action="store_true")
    parser.add_argument("--reviewed-implementation-sha")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.allow_formal_run and not args.reviewed_implementation_sha:
        result = {
            "task_id": "EXP-A02",
            "status": "failed",
            "valid": False,
            "errors": ["--reviewed-implementation-sha is required for formal mode"],
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    try:
        result = validate_package(
            args.package_dir,
            config=load_json(args.config),
            input_manifest_path=args.input_manifest,
            run_id=args.run_id,
            require_final_manifest=True,
            allow_synthetic_fixture=args.allow_synthetic_fixture,
            require_diagnostics=True,
            input_root=args.input_root,
            allow_formal_run=args.allow_formal_run,
            reviewed_implementation_sha=args.reviewed_implementation_sha,
        )
    except Exception as exc:  # noqa: BLE001
        result = {
            "task_id": "EXP-A02",
            "run_id": args.run_id,
            "status": "failed",
            "valid": False,
            "errors": [str(exc)],
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
