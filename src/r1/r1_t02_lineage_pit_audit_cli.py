from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from src.r1.r1_t02_lineage_pit_audit import ROOT, run_r1_t02_lineage_pit_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run R1-T02 R0 lineage and point-in-time audit."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data/generated/r1/r1_t02",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--code-commit", default=None)
    parser.add_argument(
        "--no-strict-artifact-hashes",
        action="store_true",
        help="Skip per-config artifact hash recomputation.",
    )
    args = parser.parse_args(argv)
    code_commit = args.code_commit or _git_head()
    summary = run_r1_t02_lineage_pit_audit(
        output_dir=args.output_dir,
        run_id=args.run_id,
        code_commit=code_commit,
        strict_artifact_hashes=not args.no_strict_artifact_hashes,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] == "completed" else 2


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
