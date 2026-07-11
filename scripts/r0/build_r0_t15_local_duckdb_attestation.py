from __future__ import annotations

import argparse
import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    module = import_module("src.r0.r0_t15_local_duckdb_attestation")
    result = module.build_r0_t15_local_duckdb_attestation(
        run_dir=args.run_dir,
        output_path=args.output,
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
