from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.r2.r2_t04_repository_final_gate_handoff import (
    HANDOFF_REL,
    VALIDATION_REL,
    create_handoff,
    validate_handoff,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true")
    mode.add_argument("--validate", action="store_true")
    parser.add_argument("--handoff-commit", default="HEAD")
    args = parser.parse_args()
    if args.create:
        result = create_handoff(Path(HANDOFF_REL))
    else:
        result = validate_handoff(Path(HANDOFF_REL), handoff_commit=args.handoff_commit)
        path = Path(VALIDATION_REL)
        path.write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if result["status"] != "passed":
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
