"""Validate JSON schemas and committed manifest examples."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("dataset_manifest", ROOT / "templates/dataset_manifest.example.json"),
    ("run_manifest", ROOT / "templates/run_manifest.json"),
    ("artifact_manifest", ROOT / "templates/artifact_manifest.example.json"),
)
SIDECAR_PAIRS = (
    (
        ROOT / "schemas/sidecar/exp_a01_accepted_result_handoff.schema.json",
        ROOT
        / "data/generated/sidecar/exp_a01/EXP-A01-20260717T040145984Z"
        / "exp_a01_accepted_result_handoff.json",
    ),
)
SCHEMA_ONLY = (
    ROOT / "schemas/sidecar/exp_a02_authorized_input_manifest.schema.json",
    ROOT / "schemas/sidecar/exp_a02_raw_domain_availability_validity.schema.json",
    ROOT / "schemas/sidecar/exp_a02_accepted_result_handoff.schema.json",
    ROOT / "schemas/sidecar/exp_a03_authorized_input_manifest.schema.json",
)


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    for schema_path in SCHEMA_ONLY:
        Draft202012Validator.check_schema(load_json(schema_path))
        print(f"validated schema {schema_path.relative_to(ROOT)}")
    for name, example_path in PAIRS:
        schema_path = ROOT / f"schemas/{name}.schema.json"
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(example_path)
        )
        print(f"validated {example_path.relative_to(ROOT)}")
    for schema_path, example_path in SIDECAR_PAIRS:
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(example_path)
        )
        print(f"validated {example_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
