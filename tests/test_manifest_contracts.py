from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("dataset_manifest", "dataset_manifest.example.json"),
    ("run_manifest", "run_manifest.json"),
    ("artifact_manifest", "artifact_manifest.example.json"),
)


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class ManifestContractTest(unittest.TestCase):
    @staticmethod
    def validator(schema: object) -> Draft202012Validator:
        return Draft202012Validator(schema, format_checker=FormatChecker())

    def test_schemas_and_examples_are_valid(self) -> None:
        for schema_name, example_name in CASES:
            with self.subTest(schema=schema_name):
                schema = load(ROOT / f"schemas/{schema_name}.schema.json")
                Draft202012Validator.check_schema(schema)
                self.validator(schema).validate(
                    load(ROOT / f"templates/{example_name}")
                )

    def test_missing_required_field_is_rejected(self) -> None:
        schema = load(ROOT / "schemas/artifact_manifest.schema.json")
        example = deepcopy(load(ROOT / "templates/artifact_manifest.example.json"))
        del example["artifact_id"]
        with self.assertRaises(ValidationError):
            self.validator(schema).validate(example)

    def test_invalid_hash_is_rejected(self) -> None:
        schema = load(ROOT / "schemas/dataset_manifest.schema.json")
        example = deepcopy(load(ROOT / "templates/dataset_manifest.example.json"))
        example["files"][0]["sha256"] = "not-a-sha256"
        with self.assertRaises(ValidationError):
            self.validator(schema).validate(example)

    def test_invalid_timestamp_is_rejected(self) -> None:
        schema = load(ROOT / "schemas/run_manifest.schema.json")
        example = deepcopy(load(ROOT / "templates/run_manifest.json"))
        example["started_at"] = "not-a-timestamp"
        with self.assertRaises(ValidationError):
            self.validator(schema).validate(example)

    def test_frozen_artifact_requires_approved_review(self) -> None:
        schema = load(ROOT / "schemas/artifact_manifest.schema.json")
        example = deepcopy(load(ROOT / "templates/artifact_manifest.example.json"))
        example["lifecycle"] = "frozen"
        example["evidence_level"] = "frozen"
        with self.assertRaises(ValidationError):
            self.validator(schema).validate(example)

    def test_artifact_lifecycle_and_evidence_must_align(self) -> None:
        schema = load(ROOT / "schemas/artifact_manifest.schema.json")
        example = deepcopy(load(ROOT / "templates/artifact_manifest.example.json"))
        example["evidence_level"] = "released"
        with self.assertRaises(ValidationError):
            self.validator(schema).validate(example)


if __name__ == "__main__":
    unittest.main()
