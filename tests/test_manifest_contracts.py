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
ARTIFACT_TRACEABILITY_FIELDS = (
    "artifact_id",
    "artifact_type",
    "evidence_status",
    "stage",
    "step",
    "data_version",
    "state_definition_version",
    "code_commit",
    "config_hash",
    "environment_lock_hash",
    "run_id",
    "input_hashes",
    "output_hashes",
    "schema_version",
    "created_at",
    "owner",
    "review_record",
    "allowed_downstream_use",
)
DATASET_RELEASE_FIELDS = (
    "data_version",
    "schema_version",
    "source_snapshot_id",
    "input_hashes",
    "transformation_code_commit",
    "config_hash",
    "run_id",
    "created_at",
    "quality_report_path",
    "output_hashes",
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

    def test_missing_artifact_traceability_field_is_rejected(self) -> None:
        schema = load(ROOT / "schemas/artifact_manifest.schema.json")
        source = load(ROOT / "templates/artifact_manifest.example.json")
        for field in ARTIFACT_TRACEABILITY_FIELDS:
            with self.subTest(field=field):
                example = deepcopy(source)
                del example[field]
                with self.assertRaises(ValidationError):
                    self.validator(schema).validate(example)

    def test_missing_dataset_release_field_is_rejected(self) -> None:
        schema = load(ROOT / "schemas/dataset_manifest.schema.json")
        source = load(ROOT / "templates/dataset_manifest.example.json")
        for field in DATASET_RELEASE_FIELDS:
            with self.subTest(field=field):
                example = deepcopy(source)
                del example[field]
                with self.assertRaises(ValidationError):
                    self.validator(schema).validate(example)

    def test_invalid_hash_is_rejected(self) -> None:
        schema = load(ROOT / "schemas/dataset_manifest.schema.json")
        example = deepcopy(load(ROOT / "templates/dataset_manifest.example.json"))
        example["output_hashes"][0]["sha256"] = "not-a-sha256"
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
        example["evidence_status"] = "frozen"
        with self.assertRaises(ValidationError):
            self.validator(schema).validate(example)

    def test_artifact_lifecycle_and_evidence_must_align(self) -> None:
        schema = load(ROOT / "schemas/artifact_manifest.schema.json")
        example = deepcopy(load(ROOT / "templates/artifact_manifest.example.json"))
        example["evidence_status"] = "released"
        with self.assertRaises(ValidationError):
            self.validator(schema).validate(example)


if __name__ == "__main__":
    unittest.main()
