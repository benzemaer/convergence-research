"""Validate JSON schemas and committed manifest examples."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    (
        ROOT / "schemas/dataset_manifest.schema.json",
        ROOT / "templates/dataset_manifest.example.json",
    ),
    (ROOT / "schemas/run_manifest.schema.json", ROOT / "templates/run_manifest.json"),
    (
        ROOT / "schemas/artifact_manifest.schema.json",
        ROOT / "templates/artifact_manifest.example.json",
    ),
    (
        ROOT / "schemas/governance/formal_result_submission.schema.json",
        ROOT / "configs/governance/formal_result_submission.example.json",
    ),
)


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    for schema_path, example_path in PAIRS:
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(example_path)
        )
        print(f"validated {example_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
