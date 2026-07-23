"""Future R2A-T06 formal runner; blocked during implementation review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2a.r2a_t06_formal_execution import run_formal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authorization", type=Path)
    args = parser.parse_args()
    authorization = None
    if args.authorization is not None:
        authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    run_formal(authorization)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
