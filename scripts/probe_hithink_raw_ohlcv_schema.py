"""Local-only HiThink raw OHLCV schema and coverage probe for D2-T09."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


class HiThinkProbeError(ValueError):
    """Raised when the local probe cannot run under the stage-1 contract."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise HiThinkProbeError(f"explicit input path does not exist: {path}")
    try:
        import pandas as pd

        frame = pd.read_parquet(path)
        return frame.to_dict(orient="records")
    except Exception as exc:
        try:
            text = path.read_text(encoding="utf-8")
            loaded = json.loads(text)
            if isinstance(loaded, list):
                return [dict(item) for item in loaded]
            if isinstance(loaded, dict) and isinstance(loaded.get("rows"), list):
                return [dict(item) for item in loaded["rows"]]
        except Exception:
            pass
        raise HiThinkProbeError(
            "parquet read failed and synthetic JSON fallback was not available"
        ) from exc


def _columns(records: list[dict[str, Any]]) -> list[str]:
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


def _date_range(
    records: list[dict[str, Any]], date_field: str | None
) -> dict[str, Any]:
    if not date_field:
        return {
            "status": "failed",
            "trading_date_min": None,
            "trading_date_max": None,
            "parseable": False,
        }
    parsed = sorted(
        parsed_date
        for row in records
        if (parsed_date := _parse_date(row.get(date_field))) is not None
    )
    return {
        "status": "passed" if parsed else "failed",
        "trading_date_min": parsed[0].isoformat() if parsed else None,
        "trading_date_max": parsed[-1].isoformat() if parsed else None,
        "parseable": bool(parsed),
    }


def _security_count(records: list[dict[str, Any]], security_field: str | None) -> int:
    if not security_field:
        return 0
    return len({row.get(security_field) for row in records if row.get(security_field)})


def _schema_report(
    records: list[dict[str, Any]],
    required_fields: list[str],
    aliases: dict[str, list[str]],
) -> dict[str, Any]:
    columns = _columns(records)
    resolved, missing = _resolve_fields(columns, required_fields, aliases)
    return {
        "status": "passed" if records and not missing else "warning",
        "row_count": len(records),
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


def _unit_report(raw_columns: list[str]) -> dict[str, Any]:
    return {
        "status": "warning",
        "amount_present": "amount" in raw_columns,
        "volume_present": "volume" in raw_columns,
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

    raw_records = _read_records(raw_k_path)
    adjustment_records = _read_records(adjustment_events_path)
    raw_report = _schema_report(
        raw_records,
        probe_contract["raw_ohlcv_required_semantic_fields"],
        probe_contract["raw_ohlcv_field_aliases"],
    )
    adjustment_report = _schema_report(
        adjustment_records,
        probe_contract["adjustment_event_expected_semantic_fields"],
        probe_contract["adjustment_event_field_aliases"],
    )
    raw_columns = raw_report["columns"]
    raw_resolved = raw_report["resolved_fields"]
    adjustment_resolved = adjustment_report["resolved_fields"]
    raw_dates = _date_range(raw_records, raw_resolved.get("trading_date"))

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
            "status": "passed" if raw_records else "failed",
            "row_count": len(raw_records),
            "security_count": _security_count(
                raw_records, raw_resolved.get("security_code_or_thscode")
            ),
            "trading_date_min": raw_dates["trading_date_min"],
            "trading_date_max": raw_dates["trading_date_max"],
        },
        "unit_inference_report": _unit_report(raw_columns),
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
