from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from src.r2a.r2a_t01_artifact_manifest import TABLE_COLUMNS, TABLE_ORDER

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
    assert config["formal_run_allowed"] is False
    assert config["dimension_order"] == ["P", "C", "A", "V", "T"]
    assert "A2b" not in json.dumps(config)


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
