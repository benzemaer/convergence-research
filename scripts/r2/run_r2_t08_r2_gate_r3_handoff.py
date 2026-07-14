from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.r2.r2_t08_independent_validator import validate_run  # noqa: E402
from src.r2.r2_t08_r2_gate_r3_handoff import (  # noqa: E402
    finalize_formal,
    run_formal,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"output_dir_not_empty:{output_dir}")
    context = run_formal(args.config.resolve(), output_dir)
    first = validate_run(output_dir)
    if first["status"] != "passed":
        raise SystemExit("independent_validation_failed")
    finalize_formal(context)
    second = validate_run(output_dir)
    if second["status"] != "passed":
        raise SystemExit("independent_validation_failed_after_finalize")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
