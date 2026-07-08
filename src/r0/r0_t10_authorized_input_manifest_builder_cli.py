from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from src.r0.r0_t10_authorized_input_manifest_builder import (
    R0T10AuthorizedInputManifestError,
    build_authorized_input_manifest,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the R0-T10-05 artifact-backed authorized input manifest."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--r0-t04-evidence",
        type=Path,
        default=Path(
            "docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md"
        ),
    )
    parser.add_argument(
        "--r0-t05-evidence",
        type=Path,
        default=Path(
            "docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md"
        ),
    )
    parser.add_argument(
        "--r0-t06-evidence",
        type=Path,
        default=Path(
            "docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md"
        ),
    )
    parser.add_argument(
        "--r0-t07-evidence",
        type=Path,
        default=Path(
            "docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = build_authorized_input_manifest(
            output_dir=args.output_dir,
            run_id=args.run_id,
            code_commit=args.code_commit,
            r0_t04_evidence=args.r0_t04_evidence,
            r0_t05_evidence=args.r0_t05_evidence,
            r0_t06_evidence=args.r0_t06_evidence,
            r0_t07_evidence=args.r0_t07_evidence,
        )
    except R0T10AuthorizedInputManifestError as exc:
        print(f"blocked: {exc}")
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
