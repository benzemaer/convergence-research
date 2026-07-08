from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r1.r1_t02_lineage_pit_audit_validator import (
    DEFAULT_EVIDENCE,
    validate_r1_t02_lineage_pit_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate R1-T02 evidence.")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--validation-output", type=Path, default=None)
    args = parser.parse_args(argv)
    result = validate_r1_t02_lineage_pit_audit(
        args.summary,
        args.evidence,
        output_path=args.validation_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
