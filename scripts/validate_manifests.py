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


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    for name, example_path in PAIRS:
        schema_path = ROOT / f"schemas/{name}.schema.json"
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(example_path)
        )
        print(f"validated {example_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
