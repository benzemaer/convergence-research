from __future__ import annotations

import argparse
from pathlib import Path

from .r0_t15_layer_q_vector_materialization_validator import (
    validate_r0_t15_layer_q_vector_materialization,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--require-author-package", action="store_true")
    parser.add_argument("--require-author-revision", action="store_true")
    args = parser.parse_args()
    result = validate_r0_t15_layer_q_vector_materialization(
        run_dir=args.run_dir,
        require_author_package=args.require_author_package,
        require_author_revision=args.require_author_revision,
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
