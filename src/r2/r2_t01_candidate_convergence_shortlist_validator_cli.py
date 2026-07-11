from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2.r2_t01_candidate_convergence_shortlist_validator import validate_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--config")
    args = parser.parse_args(argv)
    result = validate_output(
        Path(args.output), Path(args.config) if args.config else None
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
