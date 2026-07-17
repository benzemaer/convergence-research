# ruff: noqa: E501, E402

"""Standalone independent validator for an EXP-A04 compact package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_a04_cross_layer_diagnostics_validator import (
    validate_formal_result,  # noqa: E402
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--a01-raw", type=Path, required=True)
    parser.add_argument("--pcvt-raw", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--reviewed-implementation-sha")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--a01-table", default="exp_a01_raw_metrics")
    parser.add_argument("--pcvt-table", default="r0_t04_raw_metric_results")
    parser.add_argument("--synthetic-fixture", action="store_true")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json",
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = validate_formal_result(
        args.package_dir,
        config=config,
        a_raw_path=args.a01_raw,
        pcvt_raw_path=args.pcvt_raw,
        a_table=args.a01_table,
        pcvt_table=args.pcvt_table,
        repo_root=None if args.synthetic_fixture else ROOT,
        input_manifest_path=args.input_manifest,
        reviewed_sha=args.reviewed_implementation_sha,
        run_id=args.run_id,
        synthetic_fixture=args.synthetic_fixture,
        require_final_manifest=True,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
