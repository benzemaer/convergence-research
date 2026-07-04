"""Local-only HiThink raw OHLCV schema and coverage probe for D2-T09."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


class HiThinkProbeError(ValueError):
    """Raised when the local probe cannot run under the stage-1 contract."""


@dataclass(frozen=True)
class TableSummary:
    columns: list[str]
    row_count: int
    security_values: list[Any]
    date_values: list[Any]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _read_json_summary(
    path: Path,
    security_field: str | None,
    date_field: str | None,
) -> TableSummary:
    text = path.read_text(encoding="utf-8")
    loaded = json.loads(text)
    if isinstance(loaded, list):
        records = [dict(item) for item in loaded]
    elif isinstance(loaded, dict) and isinstance(loaded.get("rows"), list):
        records = [dict(item) for item in loaded["rows"]]
    else:
        raise HiThinkProbeError("synthetic JSON fallback must be a row list")
    columns = _columns_from_records(records)
    return TableSummary(
        columns=columns,
        row_count=len(records),
        security_values=[
            row.get(security_field)
            for row in records
            if security_field and row.get(security_field)
        ],
        date_values=[row.get(date_field) for row in records if date_field],
    )


def _read_parquet_summary(
    path: Path,
    columns: list[str],
    security_field: str | None,
    date_field: str | None,
) -> TableSummary:
    import pandas as pd
    import pyarrow.parquet as pq

    parquet_file = pq.ParquetFile(path)
    schema_columns = list(parquet_file.schema.names)
    row_count = parquet_file.metadata.num_rows if parquet_file.metadata else 0
    selected_columns = [
        column
        for column in dict.fromkeys([*columns, security_field, date_field])
        if column and column in schema_columns
    ]
    frame = pd.read_parquet(path, columns=selected_columns)
    return TableSummary(
        columns=schema_columns,
        row_count=row_count,
        security_values=frame[security_field].dropna().tolist()
        if security_field in frame
        else [],
        date_values=frame[date_field].dropna().tolist() if date_field in frame else [],
    )


def _read_table_summary(
    path: Path,
    required_fields: list[str],
    aliases: dict[str, list[str]],
    optional_fields: list[str] | None = None,
) -> TableSummary:
    if not path.exists():
        raise HiThinkProbeError(f"explicit input path does not exist: {path}")
    try:
        import pyarrow.parquet as pq

        parquet_file = pq.ParquetFile(path)
        schema_columns = list(parquet_file.schema.names)
        resolved, _missing = _resolve_fields(schema_columns, required_fields, aliases)
        selected_columns = list(resolved.values())
        selected_columns.extend(
            field for field in (optional_fields or []) if field in schema_columns
        )
        return _read_parquet_summary(
            path=path,
            columns=selected_columns,
            security_field=resolved.get("security_code_or_thscode"),
            date_field=resolved.get("trading_date") or resolved.get("event_date"),
        )
    except Exception as exc:
        try:
            summary = _read_json_summary(path, None, None)
            resolved, _missing = _resolve_fields(
                summary.columns, required_fields, aliases
            )
            return _read_json_summary(
                path,
                resolved.get("security_code_or_thscode"),
                resolved.get("trading_date") or resolved.get("event_date"),
            )
        except Exception:
            pass
        raise HiThinkProbeError(
            "parquet schema probe failed and synthetic JSON fallback was not available"
        ) from exc


def _columns_from_records(records: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in records:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _resolve_fields(
    columns: list[str],
    semantic_fields: list[str],
    aliases: dict[str, list[str]],
) -> tuple[dict[str, str], list[str]]:
    column_set = set(columns)
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for semantic_field in semantic_fields:
        candidates = [semantic_field, *aliases.get(semantic_field, [])]
        match = next(
            (candidate for candidate in candidates if candidate in column_set), None
        )
        if match:
            resolved[semantic_field] = match
        else:
            missing.append(semantic_field)
    return resolved, missing


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _date_range(values: list[Any]) -> dict[str, Any]:
    if not values:
        return {
            "status": "failed",
            "trading_date_min": None,
            "trading_date_max": None,
            "parseable": False,
        }
    parsed = sorted(
        parsed_date for value in values if (parsed_date := _parse_date(value))
    )
    return {
        "status": "passed" if parsed else "failed",
        "trading_date_min": parsed[0].isoformat() if parsed else None,
        "trading_date_max": parsed[-1].isoformat() if parsed else None,
        "parseable": bool(parsed),
    }


def _security_count(values: list[Any]) -> int:
    return len({value for value in values if value})


def _schema_report(
    summary: TableSummary,
    required_fields: list[str],
    aliases: dict[str, list[str]],
) -> dict[str, Any]:
    columns = summary.columns
    resolved, missing = _resolve_fields(columns, required_fields, aliases)
    return {
        "status": "passed" if summary.row_count > 0 and not missing else "warning",
        "row_count": summary.row_count,
        "columns": columns,
        "resolved_fields": resolved,
        "missing_semantic_fields": missing,
    }


def _optional_report(columns: list[str], optional_fields: list[str]) -> dict[str, Any]:
    present = [field for field in optional_fields if field in columns]
    missing = [field for field in optional_fields if field not in columns]
    return {
        "status": "passed" if not missing else "warning",
        "present_optional_fields": present,
        "missing_optional_fields": missing,
        "missing_fields_are_not_defaulted": True,
    }


def _validate_active_sources(source_registry: dict[str, Any]) -> None:
    hierarchy = source_registry["source_hierarchy"]
    active = [hierarchy["primary_source"]["source_id"]]
    active.extend(source["source_id"] for source in hierarchy["fallback_sources"])
    if "a-stock-data" in active:
        raise HiThinkProbeError("a-stock-data must not be an active source")


def _fallback_readiness(source_registry: dict[str, Any]) -> dict[str, Any]:
    fallback_sources = source_registry["source_hierarchy"]["fallback_sources"]
    return {
        "status": "passed",
        "fallback_sources": [
            {
                "source_id": source["source_id"],
                "priority": source["priority"],
                "role": source["role"],
            }
            for source in fallback_sources
        ],
        "fallback_mode": source_registry["fallback_policy"]["fallback_mode"],
        "conflict_policy": "discrepancy_report_required_no_silent_override",
    }


def _unit_report(raw_resolved: dict[str, str]) -> dict[str, Any]:
    return {
        "status": "warning",
        "amount_present": "amount" in raw_resolved,
        "volume_present": "volume" in raw_resolved,
        "amount_source_column": raw_resolved.get("amount"),
        "volume_source_column": raw_resolved.get("volume"),
        "amount_unit": "unknown",
        "volume_unit": "unknown",
        "unit_values_are_not_defaulted": True,
    }


def probe_hithink_raw_ohlcv_schema(
    raw_k_path: Path,
    adjustment_events_path: Path,
    contracts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    probe_contract = contracts["probe_contract"]
    source_registry = contracts["source_registry"]
    _validate_active_sources(source_registry)

    raw_summary = _read_table_summary(
        raw_k_path,
        probe_contract["raw_ohlcv_required_semantic_fields"],
        probe_contract["raw_ohlcv_field_aliases"],
        probe_contract["candidate_optional_fields"],
    )
    adjustment_summary = _read_table_summary(
        adjustment_events_path,
        probe_contract["adjustment_event_expected_semantic_fields"],
        probe_contract["adjustment_event_field_aliases"],
    )
    raw_report = _schema_report(
        raw_summary,
        probe_contract["raw_ohlcv_required_semantic_fields"],
        probe_contract["raw_ohlcv_field_aliases"],
    )
    adjustment_report = _schema_report(
        adjustment_summary,
        probe_contract["adjustment_event_expected_semantic_fields"],
        probe_contract["adjustment_event_field_aliases"],
    )
    raw_columns = raw_report["columns"]
    raw_resolved = raw_report["resolved_fields"]
    adjustment_resolved = adjustment_report["resolved_fields"]
    raw_dates = _date_range(raw_summary.date_values)

    raw_missing = [
        {"section": "raw_k", "semantic_field": field}
        for field in raw_report["missing_semantic_fields"]
    ]
    adjustment_missing = [
        {"section": "adjustment_events", "semantic_field": field}
        for field in adjustment_report["missing_semantic_fields"]
    ]

    optional = _optional_report(
        raw_columns, probe_contract["candidate_optional_fields"]
    )
    time_missing = [
        field
        for field in [
            "event_date",
            "ex_date",
            "announcement_date",
            "factor_as_of_time",
            "adjustment_revision",
        ]
        if field not in adjustment_resolved
    ]
    return {
        "raw_k_schema_report": raw_report,
        "adjustment_event_schema_report": adjustment_report,
        "coverage_report": {
            "status": "passed" if raw_summary.row_count > 0 else "failed",
            "row_count": raw_summary.row_count,
            "security_count": _security_count(raw_summary.security_values),
            "trading_date_min": raw_dates["trading_date_min"],
            "trading_date_max": raw_dates["trading_date_max"],
        },
        "unit_inference_report": _unit_report(raw_resolved),
        "time_semantics_report": {
            "status": "passed" if not time_missing else "warning",
            "missing_time_semantic_fields": time_missing,
        },
        "missing_field_report": {
            "status": "passed"
            if not raw_missing and not adjustment_missing
            else "warning",
            "missing_fields": raw_missing + adjustment_missing,
        },
        "fallback_readiness_report": _fallback_readiness(source_registry),
        "a_stock_data_removal_report": {
            "status": "passed",
            "a_stock_data_active": False,
            "a_stock_data_rejected_or_deprecated": True,
        },
        "probe_diagnostics": {
            "raw_k_path_explicit": str(raw_k_path),
            "adjustment_events_path_explicit": str(adjustment_events_path),
            "default_scan_data_raw": False,
            "duckdb_written": False,
            "manifest_created": False,
            "data_version_published": False,
            "raw_rows_emitted": False,
            "optional_field_report": optional,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--source-registry", required=True, type=Path)
    parser.add_argument("--raw-k-path", required=True, type=Path)
    parser.add_argument("--adjustment-events-path", required=True, type=Path)
    parser.add_argument(
        "--enable-api-probe",
        action="store_true",
        help="Reserved for a later explicit connectivity probe; not implemented.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.enable_api_probe:
        raise HiThinkProbeError("API connectivity probe is not implemented in stage 1")
    report = probe_hithink_raw_ohlcv_schema(
        raw_k_path=args.raw_k_path,
        adjustment_events_path=args.adjustment_events_path,
        contracts={
            "probe_contract": _load_json(args.contract),
            "source_registry": _load_json(args.source_registry),
        },
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
