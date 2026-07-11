from __future__ import annotations

import argparse
from pathlib import Path

from .r1_t14_02_formal_structural_revalidation_validator import (
    validate_r1_t14_02_formal_structural_revalidation,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--require-author-package", action="store_true")
    args = parser.parse_args()
    result = validate_r1_t14_02_formal_structural_revalidation(
        run_dir=args.run_dir, require_author_package=args.require_author_package
    )
    return 0 if result["status"] == "passed" else 1
