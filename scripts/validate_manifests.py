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
    (
        ROOT / "schemas/sidecar/exp_a03_accepted_result_handoff.schema.json",
        ROOT / "data/generated/sidecar/exp_a03/exp_a03_accepted_result_handoff.json",
    ),
    (
        ROOT / "schemas/sidecar/exp_a04_pcvt_raw_accepted_handoff.schema.json",
        ROOT / "data/generated/sidecar/exp_a04/exp_a04_pcvt_raw_accepted_handoff.json",
    ),
    (
        ROOT / "schemas/sidecar/exp_a_final_research_handoff.schema.json",
        ROOT / "data/generated/sidecar/exp_a/exp_a_final_research_handoff.json",
    ),
)
R2A_PAIRS = (
    (
        ROOT / "schemas/r2a/r2a_t01_accepted_result_handoff.schema.json",
        ROOT
        / "data/generated/r2a/r2a_t01/R2A-T01-20260718T103110891Z"
        / "r2a_t01_accepted_result_handoff.json",
    ),
    (
        ROOT / "schemas/r2a/r2a_t02_accepted_protocol_handoff.schema.json",
        ROOT
        / "data/generated/r2a/r2a_t02/pcavt_dynamic_state_protocol.v1"
        / "r2a_t02_accepted_protocol_handoff.json",
    ),
    (
        ROOT / "schemas/r2a/r2a_t03_accepted_implementation_handoff.schema.json",
        ROOT
        / "data/generated/r2a/r2a_t03/r2a_t03_dynamic_evaluator.v1"
        / "r2a_t03_accepted_implementation_handoff.json",
    ),
)
SCHEMA_ONLY = (
    ROOT / "schemas/r2a/r2a_t02_dynamic_request_spec.schema.json",
    ROOT / "schemas/r2a/r2a_t02_dynamic_request.schema.json",
    ROOT / "schemas/r2a/r2a_t03_dynamic_evaluator.schema.json",
    ROOT / "schemas/r2a/r2a_t04_local_source_manifest.schema.json",
    ROOT / "schemas/r2a/r2a_t04_real_input_smoke_receipt.schema.json",
    ROOT / "schemas/r2a/r2a_t04_review_bundle.schema.json",
    ROOT / "schemas/r2a/r2a_t04_thread_benchmark_receipt.schema.json",
    ROOT / "schemas/r2a/r2a_t04_ca_set_based_benchmark_receipt.schema.json",
    ROOT / "schemas/sidecar/exp_a02_authorized_input_manifest.schema.json",
    ROOT / "schemas/sidecar/exp_a02_raw_domain_availability_validity.schema.json",
    ROOT / "schemas/sidecar/exp_a02_accepted_result_handoff.schema.json",
    ROOT / "schemas/sidecar/exp_a03_authorized_input_manifest.schema.json",
    ROOT / "schemas/sidecar/exp_a03_accepted_result_handoff.schema.json",
    ROOT / "schemas/sidecar/exp_a04_authorized_input_manifest.schema.json",
    ROOT / "schemas/sidecar/exp_a04_pcvt_raw_accepted_handoff.schema.json",
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
    for schema_path, example_path in (*SIDECAR_PAIRS, *R2A_PAIRS):
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(example_path)
        )
        print(f"validated {example_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
