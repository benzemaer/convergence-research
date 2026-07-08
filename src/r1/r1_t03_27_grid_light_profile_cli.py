from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from src.r1.r1_t03_27_grid_light_profile import (
    ROOT,
    run_r1_t03_27_grid_light_profile,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run R1-T03 27-grid light profile.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--r1-t02-evidence", type=Path, required=True)
    parser.add_argument("--r1-t02-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", default=None)
    parser.add_argument("--max-workers", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args(argv)
    summary = run_r1_t03_27_grid_light_profile(
        config_path=args.config,
        r1_t02_evidence_path=args.r1_t02_evidence,
        r1_t02_summary_path=args.r1_t02_summary,
        output_dir=args.output_dir,
        run_id=args.run_id,
        code_commit=args.code_commit or _git_head(),
        max_workers=args.max_workers,
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
