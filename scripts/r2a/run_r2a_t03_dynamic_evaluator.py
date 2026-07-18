"""Run one R2A-T03 canonical dynamic-state request."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.r2a.r2a_t02_request_identity import load_canonical_request
from src.r2a.r2a_t03_dynamic_evaluator import evaluate_dynamic_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate one accepted canonical PCAVT dynamic request."
    )
    parser.add_argument("--score-db", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-db", required=True, type=Path)
    parser.add_argument("--security-id", action="append", dest="security_ids")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request = load_canonical_request(args.request)
    summary = evaluate_dynamic_request(
        score_database=args.score_db,
        canonical_request=request,
        output_database=args.output_db,
        security_ids=args.security_ids,
    )
    result = asdict(summary)
    result["output_database"] = str(args.output_db)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
