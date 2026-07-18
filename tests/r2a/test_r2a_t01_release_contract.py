from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from src.r2a.r2a_t01_artifact_manifest import (
    PRIMARY_KEYS,
    TABLE_COLUMNS,
    TABLE_ORDER,
    schema_descriptor,
)
from src.r2a.r2a_t01_score_release import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_POLICY_PATH,
    compute_score_release_id,
)
from tests.r2a._fixtures import synthetic_inputs

ROOT = Path(__file__).resolve().parents[2]


def test_configs_and_standalone_schemas_validate() -> None:
    pairs = (
        (
            ROOT / "configs/r2a/r2a_t01_pcavt_score_release.v1.json",
            ROOT / "schemas/r2a/r2a_t01_pcavt_score_release_config.schema.json",
        ),
        (
            ROOT / "configs/r2a/r2a_t01_eod_availability_policy.v1.json",
            ROOT / "schemas/r2a/r2a_t01_eod_availability_policy.schema.json",
        ),
    )
    for config_path, schema_path in pairs:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(config)
    for schema_path in sorted((ROOT / "schemas/r2a").glob("*.schema.json")):
        Draft202012Validator.check_schema(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )


def test_release_contract_has_only_score_fields_and_seven_tables() -> None:
    assert tuple(TABLE_COLUMNS) == TABLE_ORDER
    forbidden = re.compile(
        r"(^|_)(q|k|state|streak|confirmation|interval)(_|$)", re.IGNORECASE
    )
    assert not [
        f"{table}.{column}"
        for table, columns in TABLE_COLUMNS.items()
        for column in columns
        if forbidden.search(column)
    ]
    config = json.loads(
        (ROOT / "configs/r2a/r2a_t01_pcavt_score_release.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert config["percentile_window"] == 120
    assert config["formal_run_allowed"] is True
    assert config["dimension_order"] == ["P", "C", "A", "V", "T"]
    assert "A2b" not in json.dumps(config)
    assert all(columns[0] == "score_release_id" for columns in TABLE_COLUMNS.values())
    assert all(key[0] == "score_release_id" for key in PRIMARY_KEYS.values())
    descriptor = schema_descriptor()
    assert descriptor["sequence_domains"] == {
        "trading_sessions.session_sequence": {
            "scope": "global_unique_trading_date",
            "order_by": ["trading_date"],
            "zero_based_contiguous": True,
        },
        "security_observation_spine.observation_sequence": {
            "scope": "security_id",
            "order_by": ["trading_date"],
            "zero_based_contiguous": True,
            "independent_of": "trading_sessions.session_sequence",
        },
    }
    for table in TABLE_ORDER:
        contract = descriptor["tables"][table]
        assert all(
            set(column) == {"name", "type", "nullable"}
            for column in contract["columns"]
        )
        assert set(contract) == {
            "columns",
            "primary_key",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
            "enum_domains",
            "canonical_order",
        }


def test_availability_manifest_contract_is_frozen() -> None:
    policy = json.loads(
        (ROOT / "configs/r2a/r2a_t01_eod_availability_policy.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy == {
        "$schema": "../../schemas/r2a/r2a_t01_eod_availability_policy.schema.json",
        "policy_id": "r2a_t01_eod_close_1500_asia_shanghai.v1",
        "policy_version": "1.0.0",
        "timezone": "Asia/Shanghai",
        "utc_offset": "+08:00",
        "market_information_cutoff": "15:00:00",
        "policy_class": "research_logical_availability_time",
        "physical_ingestion_timestamp_required": False,
        "same_timestamp_execution_assumed": False,
        "row_available_time": "trading_date + 15:00:00 Asia/Shanghai",
        "semantic_note": (
            "Logical research information availability at market close; not physical "
            "ingestion time and not an assumption of execution at the same timestamp."
        ),
    }


def test_score_release_id_is_canonical_and_input_sensitive(tmp_path: Path) -> None:
    manifest_path, _ = synthetic_inputs(tmp_path / "inputs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    first = compute_score_release_id(
        config=config,
        availability_policy_path=DEFAULT_POLICY_PATH,
        input_manifest=manifest,
    )
    second = compute_score_release_id(
        config=deepcopy(config),
        availability_policy_path=DEFAULT_POLICY_PATH,
        input_manifest=deepcopy(manifest),
    )
    assert first == second
    changed_input = deepcopy(manifest)
    changed_input["inputs"]["security_observation_spine"]["sha256"] = "f" * 64
    assert (
        compute_score_release_id(
            config=config,
            availability_policy_path=DEFAULT_POLICY_PATH,
            input_manifest=changed_input,
        )[0]
        != first[0]
    )
    changed_derived_fixture = deepcopy(manifest)
    changed_derived_fixture["inputs"]["securities"]["sha256"] = "e" * 64
    assert (
        compute_score_release_id(
            config=config,
            availability_policy_path=DEFAULT_POLICY_PATH,
            input_manifest=changed_derived_fixture,
        )[0]
        == first[0]
    )
    changed_protocol = deepcopy(config)
    changed_protocol["dimension_definition_version"] = "changed-definition"
    assert (
        compute_score_release_id(
            config=changed_protocol,
            availability_policy_path=DEFAULT_POLICY_PATH,
            input_manifest=manifest,
        )[0]
        != first[0]
    )
