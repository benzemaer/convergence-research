"""Probe D3 field availability for R0 input needs without computing PCVT."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TASK_ID = "D3-T10"
DEFAULT_CONTRACT = (
    ROOT / "configs/d3/d3_t10_field_availability_probe_gap_fill_contract.v1.json"
)
DEFAULT_TABLE = "d3_candidate_daily_observation"

FIELD_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "open": {"required_by": "D3", "indicators": ["P1_NATR14", "P2_LogRange20"]},
    "high": {"required_by": "D3", "indicators": ["P1_NATR14", "P2_LogRange20"]},
    "low": {"required_by": "D3", "indicators": ["P1_NATR14", "P2_LogRange20"]},
    "close": {"required_by": "D3", "indicators": ["P1_NATR14"]},
    "adjusted_open": {"required_by": "R0", "indicators": []},
    "adjusted_high": {
        "required_by": "R0",
        "indicators": ["P1_NATR14", "P2_LogRange20"],
    },
    "adjusted_low": {"required_by": "R0", "indicators": ["P1_NATR14", "P2_LogRange20"]},
    "adjusted_close": {
        "required_by": "R0",
        "indicators": ["P1_NATR14", "C1_LogMASpread_5_60", "T1_ER20", "T2_AbsTrendT20"],
    },
    "effective_adj_factor": {"required_by": "D3", "indicators": []},
    "adjustment_factor_status": {"required_by": "D3", "indicators": []},
    "trading_status": {"required_by": "R0", "indicators": ["all"]},
    "price_limit_status": {"required_by": "R0", "indicators": ["all"]},
    "limit_status": {"required_by": "D3-T10", "indicators": []},
    "corporate_action_flag": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V1_VolShrink20_60"],
    },
    "vol": {"required_by": "R0", "indicators": ["V1_VolShrink20_60"]},
    "volume": {
        "required_by": "R0",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V1_VolShrink20_60"],
    },
    "volume_unit": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V1_VolShrink20_60"],
    },
    "volume_shares": {
        "required_by": "D3-T10",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V1_VolShrink20_60"],
    },
    "amount": {
        "required_by": "R0",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V2_AmountLevel20Pct"],
    },
    "amount_unit": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V2_AmountLevel20Pct"],
    },
    "amount_yuan": {
        "required_by": "D3-T10",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V2_AmountLevel20Pct"],
    },
    "amount_volume_unit_status": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60"],
    },
    "daily_vwap": {"required_by": "R0", "indicators": ["C2_AdjVWAPSpread_5_60"]},
    "daily_vwap_range_status": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60"],
    },
    "zero_volume_flag": {"required_by": "R0-T02", "indicators": ["V1_VolShrink20_60"]},
    "zero_amount_flag": {
        "required_by": "D3-T10",
        "indicators": ["V2_AmountLevel20Pct"],
    },
    "total_share_raw": {"required_by": "D3-T10", "indicators": []},
    "total_share_unit": {"required_by": "D3-T10", "indicators": []},
    "total_share_shares": {"required_by": "D3-T10", "indicators": []},
    "float_share_raw": {"required_by": "D3-T10", "indicators": []},
    "float_share_unit": {"required_by": "D3-T10", "indicators": []},
    "float_share_shares": {"required_by": "D3-T10", "indicators": []},
    "free_share_raw": {"required_by": "D3-T10", "indicators": []},
    "free_share_unit": {"required_by": "D3-T10", "indicators": []},
    "free_share_shares": {"required_by": "D3-T10", "indicators": []},
    "turnover_rate": {"required_by": "D3-T10", "indicators": []},
    "turnover_rate_f": {"required_by": "D3-T10", "indicators": []},
    "turnover_float": {"required_by": "D3-T10", "indicators": []},
    "turnover_free": {"required_by": "D3-T10", "indicators": []},
    "turnover_field_status": {"required_by": "D3-T10", "indicators": []},
    "share_field_status": {"required_by": "D3-T10", "indicators": []},
    "total_mv": {"required_by": "D3-T10", "indicators": []},
    "circ_mv": {"required_by": "D3-T10", "indicators": []},
    "corporate_action_types_in_window": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60", "V1_VolShrink20_60"],
    },
    "share_comparability_corporate_action_in_window": {
        "required_by": "R0-T02",
        "indicators": ["V1_VolShrink20_60"],
    },
    "adjusted_vwap_policy": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60"],
    },
    "adjusted_volume": {"required_by": "R0-T02", "indicators": ["V1_VolShrink20_60"]},
    "common_corporate_action_basis_policy": {
        "required_by": "R0-T02",
        "indicators": ["C2_AdjVWAPSpread_5_60"],
    },
    "common_share_basis_policy": {
        "required_by": "R0-T02",
        "indicators": ["V1_VolShrink20_60"],
    },
    "volume_comparability_policy": {
        "required_by": "R0-T02",
        "indicators": ["V1_VolShrink20_60"],
    },
}

INDICATOR_REQUIREMENTS = {
    "P1_NATR14": {"adjusted_high", "adjusted_low", "adjusted_close"},
    "P2_LogRange20": {"adjusted_high", "adjusted_low"},
    "C1_LogMASpread_5_60": {"adjusted_close"},
    "C2_AdjVWAPSpread_5_60": {
        "amount_yuan",
        "volume_shares",
        "daily_vwap",
        "daily_vwap_range_status",
        "adjusted_vwap_policy",
    },
    "T1_ER20": {"adjusted_close"},
    "T2_AbsTrendT20": {"adjusted_close"},
    "V1_VolShrink20_60": {
        "volume_shares",
        "volume_unit",
        "volume_comparability_policy",
    },
    "V2_AmountLevel20Pct": {"amount_yuan", "amount_unit"},
}


class D3T10FieldProbeError(ValueError):
    """Raised when a D3-T10 field probe cannot proceed."""


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def guard_probe_path(path: Path) -> None:
    normalized = _norm(path)
    if any(
        pattern in normalized
        for pattern in (
            "data/raw",
            "data/external",
            "marketdb",
            ".day",
            "data/generated/d1",
            "data/generated/d2",
        )
    ):
        raise D3T10FieldProbeError(
            "probe input must stay inside D3 generated/schema boundary"
        )
    if path.suffix.lower() == ".duckdb" and "data/generated/d3/" not in normalized:
        raise D3T10FieldProbeError(
            "D3 DuckDB probe input must be under data/generated/d3/"
        )


def available_fields_from_duckdb(path: Path, table: str = DEFAULT_TABLE) -> set[str]:
    guard_probe_path(path)
    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    finally:
        conn.close()
    return {row[1] for row in rows}


def available_fields_from_contract(path: Path) -> set[str]:
    guard_probe_path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields: set[str] = set()
    for value in payload.get("value_field_groups", {}).values():
        if isinstance(value, list):
            fields.update(str(item) for item in value)
    alias_map = {
        "raw_open": "open",
        "raw_high": "high",
        "raw_low": "low",
        "raw_close": "close",
        "adj_open": "adjusted_open",
        "adj_high": "adjusted_high",
        "adj_low": "adjusted_low",
        "adj_close": "adjusted_close",
    }
    fields.update(alias for field, alias in alias_map.items() if field in fields)
    return fields


def build_field_matrix(available_fields: set[str], source: str) -> list[dict[str, Any]]:
    rows = []
    for field_name, meta in sorted(FIELD_REQUIREMENTS.items()):
        present = field_name in available_fields
        policy_field = field_name.endswith("_policy") or field_name in {
            "corporate_action_flag",
            "daily_vwap_range_status",
            "volume_comparability_policy",
        }
        status = "present" if present else "missing"
        blocking_reason = "" if present else "field_not_available_in_current_d3_layer"
        if present and policy_field and field_name in {"corporate_action_flag"}:
            status = "present_but_policy_insufficient"
            blocking_reason = "requires window-level policy validation"
        rows.append(
            {
                "field_name": field_name,
                "required_by": meta["required_by"],
                "required_for_indicator": ",".join(meta["indicators"]),
                "current_status": status,
                "source_table_or_file": source,
                "unit_status": "known_by_d3_t10_contract"
                if field_name.endswith(("_unit", "_shares", "_yuan"))
                else "",
                "quality_status": "requires_quality_rule"
                if not present
                else "schema_present",
                "blocking_reason": blocking_reason,
                "suggested_fix": ""
                if present
                else "add D3 generic observation field or policy",
            }
        )
    return rows


def indicator_status(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_field = {row["field_name"]: row for row in matrix}
    results = []
    for indicator, fields in sorted(INDICATOR_REQUIREMENTS.items()):
        missing = sorted(
            field for field in fields if by_field[field]["current_status"] == "missing"
        )
        policy_insufficient = sorted(
            field
            for field in fields
            if by_field[field]["current_status"] == "present_but_policy_insufficient"
        )
        results.append(
            {
                "indicator_id": indicator,
                "ready_by_schema": not missing and not policy_insufficient,
                "missing_fields": missing,
                "policy_insufficient_fields": policy_insufficient,
                "not_required_but_useful_fields": [
                    "turnover_float",
                    "turnover_free",
                ]
                if indicator.startswith("V")
                else [],
            }
        )
    return results


def write_matrix_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_probe(
    *,
    d3_duckdb: Path | None,
    contract: Path,
    table: str,
    output_json: Path | None = None,
    output_csv: Path | None = None,
) -> dict[str, Any]:
    if d3_duckdb is not None:
        fields = available_fields_from_duckdb(d3_duckdb, table)
        source = f"{d3_duckdb}:{table}"
    else:
        fields = available_fields_from_contract(contract)
        source = str(contract)
    matrix = build_field_matrix(fields, source)
    summary = {
        "task_id": TASK_ID,
        "remote_provider_called": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "field_matrix": matrix,
        "indicator_status": indicator_status(matrix),
    }
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if output_csv:
        write_matrix_csv(output_csv, matrix)
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d3-duckdb", type=Path)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-csv", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = run_probe(
        d3_duckdb=args.d3_duckdb,
        contract=args.contract,
        table=args.table,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "field_matrix"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
