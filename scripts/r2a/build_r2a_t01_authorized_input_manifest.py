"""Build an R2A-T01 authorized manifest for temporary synthetic JSON inputs."""

from __future__ import annotations

import argparse

from src.r2a.r2a_t01_input_manifest import INPUT_NAMES, build_synthetic_input_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--synthetic-root", required=True)
    for name in INPUT_NAMES:
        parser.add_argument(f"--{name.replace('_', '-')}", required=True)
    args = parser.parse_args()
    inputs = {name: getattr(args, name) for name in INPUT_NAMES}
    build_synthetic_input_manifest(
        output_path=args.output,
        run_id=args.run_id,
        synthetic_root=args.synthetic_root,
        inputs=inputs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
