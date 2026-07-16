"""Validate EXP-A01 configuration or a persisted formal output directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_a01_price_ma_attachment_validator import (  # noqa: E402
    EXPECTED_FORMAL_FILES,
    load_json,
    validate_formal_result,
    validate_static_config,
)

DEFAULT_CONFIG = (
    ROOT / "configs" / "sidecar" / "exp_a01_price_ma_attachment_candidates.v1.json"
)
DEFAULT_SCHEMA = (
    ROOT / "schemas" / "sidecar" / "exp_a01_price_ma_attachment_candidates.schema.json"
)


def validate(
    config_path: Path,
    schema_path: Path,
    output_dir: Path | None,
    input_manifest_path: Path | None = None,
    input_root: Path | None = None,
    reviewed_implementation_sha: str | None = None,
) -> dict[str, Any]:
    config = load_json(config_path)
    errors = validate_static_config(config)
    schema = load_json(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
        errors.extend(
            f"schema:{error.message}"
            for error in Draft202012Validator(
                schema, format_checker=FormatChecker()
            ).iter_errors(config)
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"schema_validation_error:{exc}")
    formal_result = None
    if output_dir is not None:
        formal_result = validate_formal_result(
            output_dir,
            config_path=config_path,
            schema_path=schema_path,
            input_manifest_path=input_manifest_path,
            input_root=input_root,
            reviewed_implementation_sha=reviewed_implementation_sha,
            require_final_manifest=True,
        )
        errors.extend(formal_result.get("errors", []))
    result = {
        "task_id": "EXP-A01",
        "status": "passed" if not errors else "failed",
        "valid": not errors,
        "formal_output_contract": list(EXPECTED_FORMAL_FILES),
        "errors": list(dict.fromkeys(errors)),
        "config": str(config_path),
        "schema": str(schema_path),
        "output_dir": str(output_dir) if output_dir is not None else None,
    }
    if formal_result is not None:
        result["formal_result"] = formal_result
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--reviewed-implementation-sha")
    args = parser.parse_args(argv)
    try:
        result = validate(
            args.config.resolve(),
            args.schema.resolve(),
            args.output_dir.resolve() if args.output_dir is not None else None,
            args.input_manifest.resolve() if args.input_manifest is not None else None,
            args.input_root.resolve() if args.input_root is not None else None,
            args.reviewed_implementation_sha,
        )
    except Exception as exc:  # noqa: BLE001
        result = {"task_id": "EXP-A01", "status": "failed", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
