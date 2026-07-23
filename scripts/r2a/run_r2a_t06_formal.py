"""Future R2A-T06 formal runner; current preparation state fails closed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2a.r2a_t06_formal_execution import run_formal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.authorization is None:
        run_formal(None, manifest_bytes=None)
        return 0
    authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    manifest_bytes = None if args.manifest is None else args.manifest.read_bytes()
    result = run_formal(authorization, manifest_bytes=manifest_bytes)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
