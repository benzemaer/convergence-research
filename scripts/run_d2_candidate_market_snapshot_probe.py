from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN_PATH = (
    ROOT / "configs/d2/candidate_market_snapshot_probe_execution_plan.v1.json"
)
DEFAULT_MEMBERSHIP_PATH = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
)


class ProbeExecutionError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def security_id_to_baostock_code(security_id: str) -> str:
    parts = security_id.split(".")
    if len(parts) != 3 or parts[0] != "CN":
        raise ProbeExecutionError(f"Unsupported security_id format: {security_id}")
    exchange, symbol = parts[1], parts[2]
    if exchange == "SSE":
        return f"sh.{symbol}"
    if exchange == "SZSE":
        return f"sz.{symbol}"
    raise ProbeExecutionError(f"Unsupported exchange for BAOSTOCK probe: {exchange}")


def _membership_ids(membership_alignment: dict[str, Any]) -> set[str]:
    rows = membership_alignment.get("rows")
    if not isinstance(rows, list):
        raise ProbeExecutionError("Membership alignment rows are missing.")
    return {
        str(row["security_id"])
        for row in rows
        if isinstance(row, dict) and "security_id" in row
    }


def validate_sample_security_ids(
    plan: dict[str, Any], membership_alignment: dict[str, Any]
) -> None:
    allowed_ids = _membership_ids(membership_alignment)
    sample_ids = plan.get("sample_security_ids")
    if not isinstance(sample_ids, list) or not sample_ids:
        raise ProbeExecutionError("Plan sample_security_ids must be a non-empty list.")
    missing = sorted(str(item) for item in sample_ids if str(item) not in allowed_ids)
    if missing:
        raise ProbeExecutionError(
            "Plan sample_security_ids are not in D2 membership alignment: "
            + ", ".join(missing)
        )
    for security_id in sample_ids:
        security_id_to_baostock_code(str(security_id))


def source_snapshot_id(
    source_registry_id: str, security_id: str, adjustment_mode: str, retrieved_at: str
) -> str:
    digest = sha256_text(
        "|".join([source_registry_id, security_id, adjustment_mode, retrieved_at])
    )[:16]
    return f"{source_registry_id}:{security_id}:{adjustment_mode}:{digest}"


def _required_close(row: dict[str, Any], mode: str, security_id: str) -> float:
    close = row.get("close")
    if close is None or str(close).strip() == "":
        raise ProbeExecutionError(
            f"BAOSTOCK {mode} row is missing close for {security_id}."
        )
    try:
        return float(close)
    except (TypeError, ValueError) as exc:
        raise ProbeExecutionError(
            f"BAOSTOCK {mode} row has non-numeric close for {security_id}: {close}"
        ) from exc


def normalize_baostock_rows(
    mode: str, security_id: str, rows: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    close_key_by_mode = {
        "raw": "raw_close",
        "qfq": "qfq_close",
        "hfq": "hfq_close",
    }
    if mode not in close_key_by_mode:
        raise ProbeExecutionError(f"Unsupported BAOSTOCK adjustment mode: {mode}")
    close_key = close_key_by_mode[mode]
    normalized = []
    for row in rows:
        trading_date = row.get("date")
        if trading_date is None or str(trading_date).strip() == "":
            raise ProbeExecutionError(
                f"BAOSTOCK {mode} row is missing date for {security_id}."
            )
        normalized.append(
            {
                "security_id": security_id,
                "trading_date": str(trading_date),
                close_key: _required_close(row, mode, security_id),
            }
        )
    return normalized


def attach_implied_factors(
    raw_rows: Sequence[dict[str, Any]],
    qfq_rows: Sequence[dict[str, Any]],
    hfq_rows: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    raw_by_key = _rows_by_key(raw_rows)
    adjusted_specs = [
        (qfq_rows, "qfq_close", "implied_qfq_factor"),
        (hfq_rows, "hfq_close", "implied_hfq_factor"),
    ]
    normalized_adjusted: list[list[dict[str, Any]]] = []
    for adjusted_rows, close_key, factor_key in adjusted_specs:
        with_factors = []
        for row in adjusted_rows:
            key = (str(row.get("security_id")), str(row.get("trading_date")))
            raw_row = raw_by_key.get(key)
            adjusted_row = dict(row)
            if raw_row is not None:
                raw_close = float(raw_row["raw_close"])
                if raw_close > 0:
                    adjusted_row[factor_key] = float(row[close_key]) / raw_close
            with_factors.append(adjusted_row)
        normalized_adjusted.append(with_factors)
    return {
        "raw": list(raw_rows),
        "qfq": normalized_adjusted[0],
        "hfq": normalized_adjusted[1],
    }


def build_environment_blocked_report(
    plan: dict[str, Any], source_registry_id: str = "BAOSTOCK"
) -> dict[str, Any]:
    return {
        "config_version": "1.0.0",
        "report_id": "D2_CANDIDATE_MARKET_SNAPSHOT_PROBE_EXECUTION_REPORT_V1",
        "task_id": "D2-T06",
        "execution_status": "not_executed_environment_blocked",
        "source_registry_id": source_registry_id,
        "sample_security_count": len(plan["sample_security_ids"]),
        "sample_trading_day_window": {
            "start": plan["sample_date_start"],
            "end": plan["sample_date_end"],
            "max_trading_day_count": plan["max_trading_day_count"],
        },
        "raw_snapshot_written_local": False,
        "raw_snapshot_committed": False,
        "data_external_committed": False,
        "duckdb_written": False,
        "official_dataset_materialized": False,
        "formal_ingestion_authorized": False,
        "d1_raw_market_prices_generated": False,
        "d2_adjusted_market_prices_generated": False,
        "d3_daily_observations_generated": False,
        "run_manifest_created": False,
        "dataset_manifest_created": False,
        "source_snapshot_manifest_created": False,
        "redacted_report_only": True,
        "raw_response_sha256_count": 0,
        "source_snapshot_id_count": 0,
        "retrieved_at_min": None,
        "retrieved_at_max": None,
        "field_coverage_summary": {
            "status": "not_executed_environment_blocked",
            "row_level_prices_committed": False,
            "formal_point_in_time_supported": False,
        },
        "raw_ohlcv_coverage": "not_executed",
        "qfq_coverage": "not_executed",
        "hfq_coverage": "not_executed",
        "vendor_adjustment_factor_coverage": "not_executed",
        "factor_as_of_time_coverage": "not_executed",
        "revision_timestamp_coverage": "not_executed",
        "implied_qfq_factor_check": {
            "status": "not_executed",
            "checked_count": 0,
            "mismatch_count": 0,
        },
        "implied_hfq_factor_check": {
            "status": "not_executed",
            "checked_count": 0,
            "mismatch_count": 0,
        },
        "history_revision_class": "unknown",
        "research_use_tier": "exploration_only",
        "formal_use_blocking_reasons": [
            "environment_not_authorized_for_external_api",
            "source_terms_pending_for_formal_ingestion",
            "factor_as_of_time_not_verified",
            "revision_comparison_not_run",
            "formal_d1_d2_materialization_not_authorized",
            "d3_not_authorized",
        ],
        "recommended_next_decision": "run_probe_locally_with_authorized_environment",
    }


def _rows_by_key(
    rows: Iterable[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row["security_id"]), str(row["trading_date"])): row
        for row in rows
        if "security_id" in row and "trading_date" in row
    }


def _factor_check(
    raw_rows: Sequence[dict[str, Any]],
    adjusted_rows: Sequence[dict[str, Any]],
    adjusted_close_key: str,
    implied_factor_key: str,
) -> dict[str, int | str]:
    raw_by_key = _rows_by_key(raw_rows)
    checked_count = 0
    mismatch_count = 0
    adjusted_by_key = _rows_by_key(adjusted_rows)
    if not adjusted_rows:
        return {"status": "fail", "checked_count": 0, "mismatch_count": 0}
    if not adjusted_by_key:
        return {
            "status": "fail",
            "checked_count": 0,
            "mismatch_count": len(adjusted_rows),
        }
    for key, adjusted_row in adjusted_by_key.items():
        raw_row = raw_by_key.get(key)
        if raw_row is None:
            mismatch_count += 1
            continue
        raw_close = float(raw_row["raw_close"])
        adjusted_close = float(adjusted_row[adjusted_close_key])
        checked_count += 1
        if raw_close <= 0 or implied_factor_key not in adjusted_row:
            mismatch_count += 1
            continue
        implied_factor = float(adjusted_row[implied_factor_key])
        if abs(adjusted_close / raw_close - implied_factor) > 1e-10:
            mismatch_count += 1
    status = "pass" if checked_count > 0 and mismatch_count == 0 else "fail"
    return {
        "status": status,
        "checked_count": checked_count,
        "mismatch_count": mismatch_count,
    }


def build_redacted_report_from_synthetic_responses(
    plan: dict[str, Any],
    source_registry_id: str,
    responses: dict[str, Sequence[dict[str, Any]]],
    retrieved_at_values: Sequence[str] | None = None,
) -> dict[str, Any]:
    raw_rows = list(responses.get("raw", []))
    qfq_rows = list(responses.get("qfq", []))
    hfq_rows = list(responses.get("hfq", []))
    retrieved = list(retrieved_at_values or [])
    qfq_check = _factor_check(raw_rows, qfq_rows, "qfq_close", "implied_qfq_factor")
    hfq_check = _factor_check(raw_rows, hfq_rows, "hfq_close", "implied_hfq_factor")
    hashes = [
        sha256_text(json.dumps({"mode": mode, "rows": rows}, sort_keys=True))
        for mode, rows in responses.items()
        if rows
    ]
    report = build_environment_blocked_report(plan, source_registry_id)
    report.update(
        {
            "execution_status": "executed_small_sample",
            "raw_snapshot_written_local": True,
            "raw_response_sha256_count": len(hashes),
            "source_snapshot_id_count": len(hashes),
            "retrieved_at_min": min(retrieved) if retrieved else None,
            "retrieved_at_max": max(retrieved) if retrieved else None,
            "field_coverage_summary": {
                "status": "executed_small_sample",
                "row_level_prices_committed": False,
                "formal_point_in_time_supported": False,
            },
            "raw_ohlcv_coverage": "pass" if raw_rows else "fail",
            "qfq_coverage": "pass" if qfq_rows else "fail",
            "hfq_coverage": "pass" if hfq_rows else "fail",
            "vendor_adjustment_factor_coverage": "fail",
            "factor_as_of_time_coverage": "fail",
            "revision_timestamp_coverage": "fail",
            "implied_qfq_factor_check": qfq_check,
            "implied_hfq_factor_check": hfq_check,
            "history_revision_class": plan["history_revision_class_default"],
            "research_use_tier": plan["research_use_tier_default"],
            "recommended_next_decision": "review_redacted_probe_metrics_only",
        }
    )
    return report


def _write_raw_snapshot(
    rows: Sequence[dict[str, Any]],
    output_path: Path,
    fieldnames: Sequence[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def execute_baostock_probe(plan: dict[str, Any]) -> dict[str, Any]:
    if os.environ.get("D2_PROBE_ALLOW_EXTERNAL_API") != "1":
        raise ProbeExecutionError("External candidate probe is not authorized here.")
    import baostock as bs  # type: ignore[import-not-found]

    run_id = "d2_t06_candidate_probe_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = ROOT / plan["raw_output_root"] / run_id
    rows_by_mode: dict[str, list[dict[str, Any]]] = {"raw": [], "qfq": [], "hfq": []}
    normalized_by_mode: dict[str, list[dict[str, Any]]] = {
        "raw": [],
        "qfq": [],
        "hfq": [],
    }
    login = bs.login()
    if login.error_code != "0":
        raise ProbeExecutionError(f"BAOSTOCK login failed: {login.error_msg}")
    try:
        for security_id in plan["sample_security_ids"]:
            code = security_id_to_baostock_code(security_id)
            for mode in plan["adjustment_modes_requested"]:
                flag = plan["baostock_adjustment_flag_mapping"][mode]
                result = bs.query_history_k_data_plus(
                    code,
                    "date,code,open,high,low,close,volume,amount",
                    start_date=plan["sample_date_start"],
                    end_date=plan["sample_date_end"],
                    frequency="d",
                    adjustflag=flag,
                )
                mode_rows = []
                while result.next():
                    values = result.get_row_data()
                    mode_rows.append(dict(zip(result.fields, values, strict=True)))
                rows_by_mode[mode].extend(mode_rows)
                normalized_by_mode[mode].extend(
                    normalize_baostock_rows(mode, security_id, mode_rows)
                )
                _write_raw_snapshot(
                    mode_rows,
                    output_root / mode / f"{security_id}.csv",
                    result.fields,
                )
    finally:
        bs.logout()
    retrieved_at = datetime.now(UTC).isoformat()
    check_rows = attach_implied_factors(
        normalized_by_mode["raw"],
        normalized_by_mode["qfq"],
        normalized_by_mode["hfq"],
    )
    return build_redacted_report_from_synthetic_responses(
        plan, "BAOSTOCK", check_rows, [retrieved_at]
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--membership", type=Path, default=DEFAULT_MEMBERSHIP_PATH)
    parser.add_argument("--source", choices=["BAOSTOCK"], default="BAOSTOCK")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--execute", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    plan = load_json(args.plan)
    membership = load_json(args.membership)
    validate_sample_security_ids(plan, membership)
    if args.execute:
        report = execute_baostock_probe(plan)
    else:
        report = build_environment_blocked_report(plan, args.source)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeExecutionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
