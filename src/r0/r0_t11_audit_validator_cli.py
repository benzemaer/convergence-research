from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r0.r0_t11_audit_validator import (
    R0T11AuditValidationError,
    validate_r0_t11_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate R0-T11 audit handoff.")
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    args = parser.parse_args(argv)
    try:
        result = validate_r0_t11_audit(Path(args.repo_root).resolve())
    except R0T11AuditValidationError as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
