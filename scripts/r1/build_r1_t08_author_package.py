from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r1.r1_t08_global_nested_null_models import (  # noqa: E402
    build_author_draft_result_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(
        build_author_draft_result_package(
            output_dir=args.output_dir,
            analysis_path=args.analysis,
            evidence_path=args.evidence,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
