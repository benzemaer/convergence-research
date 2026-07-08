from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r1.r1_t01_manifest_lock_validator import (
    R1T01ManifestLockValidationError,
    validate_r1_t01_manifest_lock,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate R1-T01 manifest lock.")
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    args = parser.parse_args(argv)
    try:
        result = validate_r1_t01_manifest_lock(Path(args.repo_root).resolve())
    except R1T01ManifestLockValidationError as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
