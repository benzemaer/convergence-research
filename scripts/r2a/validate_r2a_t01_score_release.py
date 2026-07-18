"""Independently validate an actual R2A-T01 synthetic release package."""

from __future__ import annotations

import argparse

from src.r2a.r2a_t01_validator import validate_score_release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_dir")
    parser.add_argument("--authorized-input-manifest", required=True)
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args()
    receipt = validate_score_release(
        args.package_dir,
        authorized_input_manifest=args.authorized_input_manifest,
        formal=args.formal,
    )
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
