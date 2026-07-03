"""Validate committed governance configurations."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = (
    (
        ROOT / "schemas/g0_universe_time_boundaries.schema.json",
        ROOT / "configs/g0/universe_time_boundaries.v1.json",
    ),
    (
        ROOT / "schemas/d0_source_registry.schema.json",
        ROOT / "configs/d0/source_registry.v1.json",
    ),
)


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    for schema_path, config_path in CONFIGS:
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(config_path)
        )
        print(f"validated {config_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
