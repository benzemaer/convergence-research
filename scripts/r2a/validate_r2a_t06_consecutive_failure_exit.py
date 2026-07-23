"""Independently validate an R2A-T06 synthetic candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2a.r2a_t06_validator import validate_t06_candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-fixture", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.synthetic_fixture.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    receipt = validate_t06_candidate(fixture["source_by_request"], candidate)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
