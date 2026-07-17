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
    existing_package: Path | None = None,
    diagnostic_output_dir: Path | None = None,
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
    if output_dir is not None and existing_package is not None:
        errors.append("output_dir_and_existing_package_are_mutually_exclusive")
    formal_result = None
    validation_mode = "config_only"
    validation_root = output_dir
    allow_failed_package_files = False
    if existing_package is not None:
        validation_mode = "existing_failed_package_read_only"
        validation_root = existing_package.resolve()
        allow_failed_package_files = True
    if validation_root is not None:
        formal_result = validate_formal_result(
            validation_root,
            config_path=config_path,
            schema_path=schema_path,
            input_manifest_path=input_manifest_path,
            input_root=input_root,
            reviewed_implementation_sha=reviewed_implementation_sha,
            require_final_manifest=existing_package is None,
            allow_failed_package_files=allow_failed_package_files,
        )
        errors.extend(formal_result.get("errors", []))
    result = {
        "task_id": "EXP-A01",
        "status": "passed" if not errors else "failed",
        "valid": not errors,
        "validation_mode": validation_mode,
        "published": False if existing_package is not None else None,
        "usable_as_formal_result": False if existing_package is not None else None,
        "formal_approval": (
            "not_permitted_existing_package_diagnostic"
            if existing_package is not None
            else None
        ),
        "formal_output_contract": list(EXPECTED_FORMAL_FILES),
        "errors": list(dict.fromkeys(errors)),
        "config": str(config_path),
        "schema": str(schema_path),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "existing_package": (
            str(existing_package.resolve()) if existing_package is not None else None
        ),
    }
    if formal_result is not None:
        result["formal_result"] = formal_result
    if existing_package is not None:
        diagnostic_dir = (
            diagnostic_output_dir.resolve()
            if diagnostic_output_dir is not None
            else existing_package.resolve().parent
            / f"{existing_package.name}.validation"
        )
        if diagnostic_dir.exists():
            raise RuntimeError(
                f"diagnostic output directory must be new and absent: {diagnostic_dir}"
            )
        diagnostic_dir.mkdir(parents=True)
        diagnostic_path = diagnostic_dir / "exp_a01_existing_package_validation.json"
        result["diagnostic_output"] = str(diagnostic_path)
        diagnostic_path.write_text(
            json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    output_modes = parser.add_mutually_exclusive_group()
    output_modes.add_argument("--output-dir", type=Path)
    output_modes.add_argument("--existing-package", type=Path)
    parser.add_argument("--diagnostic-output-dir", type=Path)
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
            (
                args.existing_package.resolve()
                if args.existing_package is not None
                else None
            ),
            args.diagnostic_output_dir,
        )
    except Exception as exc:  # noqa: BLE001
        result = {"task_id": "EXP-A01", "status": "failed", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
