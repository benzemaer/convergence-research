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
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--local-attestation", type=Path, required=True)
    parser.add_argument("--revision-config", type=Path, default=None)
    args = parser.parse_args()
    module = import_module("src.r0.r0_t15_author_revision")
    kwargs = {
        "run_dir": args.run_dir,
        "analysis_path": args.analysis,
        "evidence_path": args.evidence,
        "local_attestation_path": args.local_attestation,
    }
    if args.revision_config is not None:
        kwargs["revision_config_path"] = args.revision_config
    module.build_r0_t15_author_revision(**kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
