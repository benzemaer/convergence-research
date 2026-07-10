from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .r1_t04_state_line_profiles import run_r1_t04_state_line_profiles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run R1-T04 pre-registered state-line profiles."
    )
    parser.add_argument(
        "--config", default="configs/r1/r1_t04_state_line_profiles.v1.json"
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--code-commit")
    args = parser.parse_args(argv)
    commit = (
        args.code_commit
        or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    )
    run_id = args.run_id or "R1-T04-" + datetime.now(UTC).strftime("%Y%m%dT%H%MZ")
    summary = run_r1_t04_state_line_profiles(
        config_path=Path(args.config),
        output_dir=Path(args.output_dir),
        run_id=run_id,
        code_commit=commit,
    )
    print(
        summary["summary_path"]
        if "summary_path" in summary
        else Path(args.output_dir) / "r1_t04_experiment_summary.json"
    )
    return 0 if summary["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
