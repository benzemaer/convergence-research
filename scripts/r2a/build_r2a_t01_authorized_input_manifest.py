"""Build a synthetic or local-only formal R2A-T01 authorized input manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.r2a.r2a_t01_input_manifest import (
    INPUT_NAMES,
    build_formal_input_manifest,
    build_synthetic_input_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--synthetic-root")
    parser.add_argument("--formal-source-spec")
    parser.add_argument("--source-commit")
    parser.add_argument("--formal-authorization-id")
    parser.add_argument("--universe-id")
    for name in INPUT_NAMES:
        parser.add_argument(f"--{name.replace('_', '-')}")
    args = parser.parse_args()
    if args.formal_source_spec:
        required = {
            "source_commit": args.source_commit,
            "formal_authorization_id": args.formal_authorization_id,
            "universe_id": args.universe_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error("formal mode missing: " + ", ".join(missing))
        spec = json.loads(Path(args.formal_source_spec).read_text(encoding="utf-8"))
        if not isinstance(spec, dict) or set(spec) != {"inputs"}:
            parser.error("formal source spec must contain exactly one inputs object")
        build_formal_input_manifest(
            output_path=args.output,
            run_id=args.run_id,
            source_commit=args.source_commit,
            formal_authorization_id=args.formal_authorization_id,
            universe_id=args.universe_id,
            inputs=spec["inputs"],
        )
        return 0
    if not args.synthetic_root:
        parser.error("synthetic mode requires --synthetic-root")
    inputs = {name: getattr(args, name) for name in INPUT_NAMES}
    missing_inputs = [name for name, value in inputs.items() if not value]
    if missing_inputs:
        parser.error("synthetic mode missing inputs: " + ", ".join(missing_inputs))
    build_synthetic_input_manifest(
        output_path=args.output,
        run_id=args.run_id,
        synthetic_root=args.synthetic_root,
        inputs=inputs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
