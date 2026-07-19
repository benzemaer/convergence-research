from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.r2a.r2a_t04_request_panel import build_request_panel


def test_supplemental_panel_uses_generated_q10_q20_identities() -> None:
    panel = {
        item["logical_request_name"]: item
        for item in build_request_panel()
        if item["logical_request_name"] in ("CA_q10_k5", "CA_q20_k5")
    }
    assert panel["CA_q10_k5"]["request_id"] == ("pcavt-dynreq-v1-d07aae4bbbd98f88")
    assert panel["CA_q20_k5"]["request_id"] == ("pcavt-dynreq-v1-21bd144aaed98d9e")
    assert [panel[name]["spec"]["q_by_dimension"] for name in panel] == [
        {"C": 1000, "A": 1000},
        {"C": 2000, "A": 2000},
    ]


def test_supplemental_receipt_schema_is_valid() -> None:
    schema = json.loads(
        Path("schemas/r2a/r2a_t04_ca_q10_q20_benchmark_receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
