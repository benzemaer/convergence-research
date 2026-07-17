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
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-synthetic-fixture", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.allow_synthetic_fixture:
        result = {
            "task_id": "EXP-A02",
            "status": "failed",
            "valid": False,
            "errors": [
                "implementation phase accepts synthetic fixtures only; "
                "pass --allow-synthetic-fixture"
            ],
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
            allow_synthetic_fixture=True,
            require_diagnostics=True,
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
