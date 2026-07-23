"""Run R2A-T06 against an explicitly marked synthetic JSON fixture only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2a.r2a_t06_consecutive_failure_exit import (
    T06Error,
    build_t06_candidate,
    candidate_to_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    payload = json.loads(args.synthetic_fixture.read_text(encoding="utf-8"))
    if payload.get("synthetic_fixture") is not True:
        raise T06Error("implementation_runner_requires_synthetic_fixture")
    candidate = build_t06_candidate(
        payload["source_by_request"], worker_count=args.workers
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(candidate_to_json(candidate), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
