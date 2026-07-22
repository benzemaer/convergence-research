"""Thin entry point for the R2A-T05 formal input manifest builder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2a.r2a_t05_formal_input_manifest import (  # noqa: E402
    CONFIG_PATH,
    build_formal_input_manifest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the repository-local R2A-T05 formal authorized input manifest."
        )
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--score-db", type=Path)
    parser.add_argument("--source-commit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_formal_input_manifest(
        output_path=args.output,
        config_path=args.config,
        score_database_path=args.score_db,
        source_commit=args.source_commit,
    )
    print(
        json.dumps(
            {
                "manifest_version": payload["manifest_version"],
                "output": str(args.output),
                "source_commit": payload["source_commit"],
                "score_release_id": payload["score_database"]["score_release_id"],
                "request_order": [
                    item["logical_request_name"] for item in payload["requests"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
