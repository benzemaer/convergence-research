from __future__ import annotations

import argparse
from pathlib import Path

from .r1_t08_global_nested_null_models import CONFIG_PATH
from .r1_t08_global_nested_null_models_validator import (
    validate_r1_t08_global_nested_null_models,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--skip-offset-plan-check", action="store_true")
    args = parser.parse_args()
    validate_r1_t08_global_nested_null_models(
        output_dir=args.output_dir,
        config_path=args.config,
        verify_offset_plans=not args.skip_offset_plan_check,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
