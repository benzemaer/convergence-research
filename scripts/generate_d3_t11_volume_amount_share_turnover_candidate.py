"""Generate D3-T11 volume/amount/share/turnover candidate fields."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Protocol

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.d3_t10_field_standardization import (  # noqa: E402
    combine_standardized_fields,
    forbidden_output_names,
)
from scripts.generate_d3_t07_candidate_daily_observation import (  # noqa: E402
    generate_d3_t07_candidate_daily_observation,
)
from scripts.resolve_security_provider_codes import (  # noqa: E402
    resolve_security_provider_codes,
)

TASK_ID = "D3-T11"
SOURCE_TASK_ID = "D3-T07"
DEFAULT_CONTRACT = (
    ROOT / "configs/d3/d3_t11_volume_amount_share_turnover_candidate_contract.v1.json"
)
DEFAULT_SECURITY_UNIVERSE = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
)
DEFAULT_START_DATE = "20160101"
DEFAULT_END_DATE = "20260630"
DEFAULT_D3_T07_DUCKDB = (
    ROOT
    / "data/generated/d3/d3_t07_candidate_daily_observation/"
    / "d3_t07_candidate_daily_observation.duckdb"
)
DEFAULT_D2_T20_DUCKDB = (
    ROOT
    / "data/generated/d2/d2_t20_fast_coverage_policy_candidate/"
    / "d2_t15_tnskhdata_staging.duckdb"
)
DEFAULT_D2_T20_ACCEPTANCE_REPORT = (
    ROOT
    / "data/generated/d2/d2_t20_fast_coverage_policy_candidate/"
    / "d2_t20_acceptance_candidate_report.json"
)
DEFAULT_D2_T20_HANDOFF_REPORT = (
    ROOT
    / "data/generated/d2/d2_t20_fast_coverage_policy_candidate/"
    / "d2_t20_handoff_candidate_report.json"
)
DEFAULT_OUTPUT_DIR = (
    ROOT / "data/generated/d3/d3_t11_volume_amount_share_turnover_candidate"
)
OUTPUT_DUCKDB_NAME = "d3_t11_volume_amount_share_turnover_candidate.duckdb"
OUTPUT_TABLE = "d3_t11_volume_amount_share_turnover_candidate"
SOURCE_TABLE = "d3_candidate_daily_observation"
TOKEN_ENV_NAMES = ("TNSKHDATA_TOKEN", "TUSHARE_TOKEN", "TNS_TOKEN")
MIN_RESOLVED_SECURITY_COUNT = 790
FORBIDDEN_OUTPUT_FILES = {
    "data_version.json",
    "formal_manifest.json",
    "manifest.json",
    "labels.csv",
    "returns.csv",
    "future_labels.csv",
    "future_returns.csv",
    "breakout_direction.csv",
    "backtest.csv",
    "portfolio.csv",
    "pcvt_values.csv",
    "pcvt_scores.csv",
    "pcvt_states.csv",
    "state_intervals.csv",
    "r0_state.csv",
}


class D3T11GenerationError(ValueError):
    """Raised when D3-T11 generation cannot proceed."""


class TnskhdataClient(Protocol):
    def daily_basic(self, *, ts_code: str, start_date: str, end_date: str) -> Any: ...


def _utc_run_id() -> str:
    return "D3-T11-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rows_as_dicts(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _records(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    if hasattr(payload, "to_dict"):
        return [dict(row) for row in payload.to_dict("records")]
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, list):
            return [dict(row) for row in data]
    return []


def token_from_env() -> str | None:
    for name in TOKEN_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            return value
    return None


def load_env_file(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    allowed = set(TOKEN_ENV_NAMES)
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in allowed or os.environ.get(key):
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def real_tnskhdata_client(token: str) -> TnskhdataClient:
    try:
        import tnskhdata as ts  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("tnskhdata package is not available") from exc
    if hasattr(ts, "pro_api"):
        return ts.pro_api(token)
    if hasattr(ts, "set_token"):
        ts.set_token(token)
    return ts.pro_api()


def ensure_allowed_output_dir(path: Path) -> None:
    normalized = _norm(path)
    if "data/raw" in normalized or "data/external" in normalized:
        raise D3T11GenerationError("output-dir must not be under raw/external data")
    if "marketdb" in normalized or ".day" in normalized:
        raise D3T11GenerationError("output-dir must not target provider storage")
    if ".duckdb" in normalized:
        raise D3T11GenerationError("output-dir must be a directory")
    if "data/generated/d3/" not in normalized:
        raise D3T11GenerationError("output-dir must be under data/generated/d3/")


def guard_d3_t07_duckdb(path: Path) -> None:
    normalized = _norm(path)
    if path.suffix.lower() != ".duckdb":
        raise D3T11GenerationError("d3-t07-duckdb must be a DuckDB file")
    if path.name != "d3_t07_candidate_daily_observation.duckdb":
        raise D3T11GenerationError("d3-t07-duckdb filename is not a D3-T07 candidate")
    forbidden_patterns = (
        "data/raw",
        "data/external",
        "marketdb",
        ".day",
        "data/generated/d1",
        "data/generated/d2",
    )
    if any(pattern in normalized for pattern in forbidden_patterns):
        raise D3T11GenerationError("d3-t07-duckdb path is outside D3 boundaries")
    if "data/generated/d3/d3_t07_candidate_daily_observation/" not in normalized:
        raise D3T11GenerationError("d3-t07-duckdb must be under D3-T07 output")


def guard_security_universe_path(path: Path) -> None:
    normalized = _norm(path)
    forbidden_patterns = (
        "data/raw",
        "data/external",
        "marketdb",
        ".day",
        "data/generated/d1",
        "data/generated/d2",
    )
    if any(pattern in normalized for pattern in forbidden_patterns):
        raise D3T11GenerationError("security universe path is outside config boundary")
    if "configs/d2/" not in normalized:
        raise D3T11GenerationError("security universe must be a D2 config artifact")


def remove_previous_outputs(output_dir: Path, *, resume: bool) -> None:
    if resume or not output_dir.exists():
        return
    for name in (
        OUTPUT_DUCKDB_NAME,
        "d3_t11_generation_summary.json",
        "d3_t11_field_coverage_report.json",
        "d3_t11_quality_report.json",
        "d3_t11_provider_call_summary.json",
        "d3_t11_missing_by_security.csv",
        "d3_t11_missing_by_field.csv",
        "d3_t11_turnover_crosscheck_summary.csv",
        "d3_t11_daily_vwap_range_summary.csv",
        "d3_t11_r0_handoff_report.json",
        "d3_t11_file_hash_summary.json",
    ):
        target = output_dir / name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def read_security_list(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        payload = json.loads(stripped)
        rows = payload if isinstance(payload, list) else payload.get("securities", [])
        result = []
        for row in rows:
            if isinstance(row, str):
                result.append(row)
            elif isinstance(row, dict):
                value = row.get("ts_code") or row.get("security_id")
                if value:
                    result.append(str(value))
        return sorted(set(result))
    result = []
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        result.append(value.split(",")[0].strip())
    return sorted(set(result))


def resolve_security_universe(path: Path) -> tuple[list[str], dict[str, Any]]:
    guard_security_universe_path(path)
    payload = _load_json(path)
    rows = payload.get("rows", [])
    resolved: list[str] = []
    unresolved: list[dict[str, Any]] = []
    for row in rows:
        security_id = str(row.get("security_id", "")).strip()
        mapping = resolve_security_provider_codes(security_id)
        if mapping.mapping_status == "resolved" and mapping.tnskhdata_ts_code:
            resolved.append(mapping.tnskhdata_ts_code)
        else:
            unresolved.append(
                {
                    "security_id": security_id,
                    "mapping_status": mapping.mapping_status,
                    "mapping_blocking_reasons": mapping.mapping_blocking_reasons,
                }
            )
    unique_resolved = sorted(set(resolved))
    summary = {
        "security_universe": str(path),
        "configured_security_count": len(rows),
        "resolved_tnskhdata_security_count": len(unique_resolved),
        "unresolved_security_count": len(unresolved),
        "unresolved_mappings": unresolved,
    }
    return unique_resolved, summary


def read_security_universe_as_tnskhdata_codes(path: Path) -> list[str]:
    codes, _summary = resolve_security_universe(path)
    return codes


def resolve_input_securities(
    *, securities_file: Path | None, security_universe: Path
) -> tuple[list[str], dict[str, Any]]:
    if securities_file is not None:
        codes = read_security_list(securities_file)
        return codes, {
            "security_universe": str(securities_file),
            "configured_security_count": len(codes),
            "resolved_tnskhdata_security_count": len(codes),
            "unresolved_security_count": 0,
            "unresolved_mappings": [],
        }
    return resolve_security_universe(security_universe)


def source_rows(
    d3_t07_duckdb: Path,
    *,
    securities: list[str],
    start_date: str,
    end_date: str,
    sample_securities: int | None,
) -> list[dict[str, Any]]:
    guard_d3_t07_duckdb(d3_t07_duckdb)
    selected = securities[:sample_securities] if sample_securities else securities
    if not selected:
        return []
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in selected)
    conn = duckdb.connect(str(d3_t07_duckdb), read_only=True)
    try:
        return _rows_as_dicts(
            conn,
            f"""
            SELECT ts_code, trade_date, open, high, low, close, vol, amount,
                   trading_status, price_limit_status, is_limit_up, is_limit_down,
                   is_listing_pause, source_task_id, generated_by_task, row_provenance
            FROM {SOURCE_TABLE}
            WHERE ts_code IN ({quoted})
              AND trade_date BETWEEN '{start_date}' AND '{end_date}'
            ORDER BY ts_code, trade_date
            """,
        )
    finally:
        conn.close()


def fetch_daily_basic_rows(
    client: TnskhdataClient,
    securities: list[str],
    *,
    start_date: str,
    end_date: str,
    max_retries: int,
    sleep_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    for ts_code in securities:
        attempts = 0
        last_error: str | None = None
        while attempts <= max_retries:
            attempts += 1
            try:
                payload = client.daily_basic(
                    ts_code=ts_code, start_date=start_date, end_date=end_date
                )
                fetched = _records(payload)
                rows.extend(fetched)
                calls.append(
                    {
                        "endpoint": "daily_basic",
                        "ts_code": ts_code,
                        "status": "succeeded",
                        "attempt_count": attempts,
                        "row_count": len(fetched),
                    }
                )
                break
            except Exception as exc:  # pragma: no cover - provider-only branch.
                last_error = type(exc).__name__
                if attempts > max_retries:
                    calls.append(
                        {
                            "endpoint": "daily_basic",
                            "ts_code": ts_code,
                            "status": "failed",
                            "attempt_count": attempts,
                            "error_type": last_error,
                            "row_count": 0,
                        }
                    )
                elif sleep_seconds > 0:
                    time.sleep(sleep_seconds)
    return rows, calls


def create_output_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (
          ts_code TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          open DOUBLE,
          high DOUBLE,
          low DOUBLE,
          close DOUBLE,
          vol DOUBLE,
          amount DOUBLE,
          volume_raw DOUBLE,
          volume_unit TEXT,
          volume_shares DOUBLE,
          amount_raw DOUBLE,
          amount_unit TEXT,
          amount_yuan DOUBLE,
          amount_volume_unit_status TEXT,
          daily_vwap DOUBLE,
          daily_vwap_range_status TEXT,
          zero_volume_flag BOOLEAN,
          zero_amount_flag BOOLEAN,
          daily_basic_close DOUBLE,
          turnover_rate DOUBLE,
          turnover_rate_f DOUBLE,
          volume_ratio DOUBLE,
          total_share_raw DOUBLE,
          total_share_unit TEXT,
          total_share_shares DOUBLE,
          float_share_raw DOUBLE,
          float_share_unit TEXT,
          float_share_shares DOUBLE,
          free_share_raw DOUBLE,
          free_share_unit TEXT,
          free_share_shares DOUBLE,
          total_mv DOUBLE,
          circ_mv DOUBLE,
          limit_status TEXT,
          turnover_float DOUBLE,
          turnover_free DOUBLE,
          derived_turnover_rate_pct DOUBLE,
          derived_turnover_rate_f_pct DOUBLE,
          provider_turnover_crosscheck_status TEXT,
          share_field_status TEXT,
          turnover_field_status TEXT,
          corporate_action_flag TEXT,
          corporate_action_types_in_window TEXT,
          share_comparability_corporate_action_in_window TEXT,
          adjusted_vwap_policy TEXT,
          common_corporate_action_basis_policy TEXT,
          common_share_basis_policy TEXT,
          volume_comparability_policy TEXT,
          trading_status TEXT,
          price_limit_status TEXT,
          is_limit_up BOOLEAN,
          is_limit_down BOOLEAN,
          is_listing_pause BOOLEAN,
          source_task_id TEXT,
          d3_source_duckdb TEXT,
          generated_by_task TEXT,
          row_provenance TEXT,
          provider_source TEXT,
          source_snapshot_id TEXT,
          run_id TEXT,
          code_commit TEXT,
          PRIMARY KEY (ts_code, trade_date)
        )
        """
    )


def build_candidate_rows(
    *,
    d3_rows: list[dict[str, Any]],
    daily_basic_rows: list[dict[str, Any]],
    d3_source_duckdb: Path,
    provider_source: str,
    run_id: str,
    code_commit: str,
) -> list[dict[str, Any]]:
    basic_by_key = {
        (row.get("ts_code"), row.get("trade_date")): row for row in daily_basic_rows
    }
    results: list[dict[str, Any]] = []
    for row in d3_rows:
        key = (row["ts_code"], row["trade_date"])
        basic = basic_by_key.get(key, {})
        standardized = combine_standardized_fields(row, basic)
        results.append(
            {
                **{key: row.get(key) for key in ("ts_code", "trade_date")},
                **{
                    key: row.get(key)
                    for key in ("open", "high", "low", "close", "vol", "amount")
                },
                **standardized,
                "volume_ratio": basic.get("volume_ratio"),
                "corporate_action_flag": "unknown",
                "corporate_action_types_in_window": "unknown",
                "share_comparability_corporate_action_in_window": "policy_pending",
                "adjusted_vwap_policy": "policy_pending",
                "common_corporate_action_basis_policy": "policy_pending",
                "common_share_basis_policy": "policy_pending",
                "volume_comparability_policy": "policy_pending",
                "trading_status": row.get("trading_status"),
                "price_limit_status": row.get("price_limit_status"),
                "is_limit_up": row.get("is_limit_up"),
                "is_limit_down": row.get("is_limit_down"),
                "is_listing_pause": row.get("is_listing_pause"),
                "source_task_id": row.get("source_task_id"),
                "d3_source_duckdb": str(d3_source_duckdb),
                "generated_by_task": TASK_ID,
                "row_provenance": (
                    f"d3_t11:{row.get('ts_code')}:{row.get('trade_date')}:"
                    f"{provider_source}:daily_basic"
                ),
                "provider_source": provider_source,
                "source_snapshot_id": f"{TASK_ID}:{run_id}:candidate",
                "run_id": run_id,
                "code_commit": code_commit,
            }
        )
    return results


def insert_candidate_rows(
    conn: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]]
) -> None:
    if not rows:
        return
    columns = [
        desc[1]
        for desc in conn.execute(f"PRAGMA table_info('{OUTPUT_TABLE}')").fetchall()
    ]
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT OR REPLACE INTO {OUTPUT_TABLE} ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        [[row.get(column) for column in columns] for row in rows],
    )


def rate(rows: list[dict[str, Any]], predicate: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(predicate) == "valid") / len(rows)


def build_reports(
    *,
    output_dir: Path,
    output_duckdb: Path,
    rows: list[dict[str, Any]],
    source_row_count: int,
    daily_basic_rows: list[dict[str, Any]],
    provider_calls: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    row_count = len(rows)
    field_names = [
        "volume_shares",
        "amount_yuan",
        "daily_vwap",
        "float_share_shares",
        "free_share_shares",
        "turnover_float",
        "turnover_free",
        "limit_status",
    ]
    field_coverage = {
        field: (sum(1 for row in rows if row.get(field) not in (None, "")) / row_count)
        if row_count
        else 0.0
        for field in field_names
    }
    status_counts = {
        status_field: {
            str(value): sum(1 for row in rows if row.get(status_field) == value)
            for value in sorted({row.get(status_field) for row in rows}, key=str)
        }
        for status_field in (
            "amount_volume_unit_status",
            "daily_vwap_range_status",
            "share_field_status",
            "turnover_field_status",
            "provider_turnover_crosscheck_status",
        )
    }
    blocking_reasons = [
        field
        for field in (
            "amount_volume_unit_status",
            "share_field_status",
            "turnover_field_status",
            "provider_turnover_crosscheck_status",
        )
        if any(row.get(field) == "fail" for row in rows)
    ]
    quality = {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "source_row_count": source_row_count,
        "generated_candidate_row_count": row_count,
        "daily_basic_row_count": len(daily_basic_rows),
        "zero_volume_row_count": sum(1 for row in rows if row.get("zero_volume_flag")),
        "zero_amount_row_count": sum(1 for row in rows if row.get("zero_amount_flag")),
        "status_counts": status_counts,
        "daily_vwap_valid_rate": rate(rows, "daily_vwap_range_status"),
        "share_field_valid_rate": rate(rows, "share_field_status"),
        "turnover_crosscheck_valid_rate": rate(
            rows, "provider_turnover_crosscheck_status"
        ),
        "blocking_reasons": blocking_reasons,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }
    coverage = {
        "task_id": TASK_ID,
        "field_coverage": field_coverage,
        "row_count": row_count,
        "security_count": len({row.get("ts_code") for row in rows}),
    }
    provider_summary = {
        "task_id": TASK_ID,
        "provider_raw_payload_committed": False,
        "credential_committed": False,
        "remote_provider_called": bool(provider_calls),
        "call_count": len(provider_calls),
        "succeeded_call_count": sum(
            1 for call in provider_calls if call["status"] == "succeeded"
        ),
        "failed_call_count": sum(
            1 for call in provider_calls if call["status"] == "failed"
        ),
        "calls": provider_calls,
    }
    r0_ready = not blocking_reasons and row_count > 0
    no_research_outputs_key = (
        "d3_t11_does_not_generate_percentiles_scores_states_intervals_"
        "labels_returns_backtest_or_portfolio"
    )
    handoff = {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "r0_ready_candidate": r0_ready,
        "field_coverage_by_indicator": {
            "C2_AdjVWAPSpread_5_60": min(
                field_coverage["amount_yuan"],
                field_coverage["volume_shares"],
                field_coverage["daily_vwap"],
            ),
            "V1_VolShrink20_60": field_coverage["volume_shares"],
            "V2_AmountLevel20Pct": field_coverage["amount_yuan"],
        },
        "unknown_due_to_missing_field_estimate": sum(
            1
            for row in rows
            if row.get("share_field_status") != "valid"
            or row.get("turnover_field_status") != "valid"
        ),
        "c2_ready_field_coverage": min(
            field_coverage["amount_yuan"],
            field_coverage["volume_shares"],
            field_coverage["daily_vwap"],
        ),
        "v1_ready_field_coverage": field_coverage["volume_shares"],
        "v2_ready_field_coverage": field_coverage["amount_yuan"],
        "turnover_float_coverage": field_coverage["turnover_float"],
        "turnover_free_coverage": field_coverage["turnover_free"],
        "daily_vwap_valid_rate": quality["daily_vwap_valid_rate"],
        "share_field_valid_rate": quality["share_field_valid_rate"],
        "turnover_crosscheck_valid_rate": quality["turnover_crosscheck_valid_rate"],
        "limit_status_non_null_rate": field_coverage["limit_status"],
        "blocking_reasons": blocking_reasons,
        "d3_t11_does_not_calculate_pcvt_values": True,
        no_research_outputs_key: True,
        "r0_baseline": "V1_VolShrink20_60 + V2_AmountLevel20Pct",
        "turnover_based_v_metrics_policy": (
            "future alternatives for R0-T09 / R1 sensitivity"
        ),
        "next_planned_task": "R0-T03 PCVT raw metric engine 与合成测试",
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }
    summary = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "d3_t11_generation_decision": (
            "accepted_candidate" if r0_ready else "candidate_generated_with_warnings"
        ),
        "candidate_duckdb": str(output_duckdb),
        "candidate_row_count": row_count,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }
    _write_json(output_dir / "d3_t11_generation_summary.json", summary)
    _write_json(output_dir / "d3_t11_field_coverage_report.json", coverage)
    _write_json(output_dir / "d3_t11_quality_report.json", quality)
    _write_json(output_dir / "d3_t11_provider_call_summary.json", provider_summary)
    _write_json(output_dir / "d3_t11_r0_handoff_report.json", handoff)
    write_csv_reports(output_dir, rows=rows)
    write_hash_summary(output_dir)
    return summary


def write_csv_reports(output_dir: Path, *, rows: list[dict[str, Any]]) -> None:
    missing_by_security = []
    for ts_code in sorted({row["ts_code"] for row in rows}):
        subset = [row for row in rows if row["ts_code"] == ts_code]
        missing_by_security.append(
            {
                "ts_code": ts_code,
                "row_count": len(subset),
                "missing_daily_basic_count": sum(
                    1 for row in subset if row.get("daily_basic_close") is None
                ),
            }
        )
    _write_csv(
        output_dir / "d3_t11_missing_by_security.csv",
        missing_by_security,
        ["ts_code", "row_count", "missing_daily_basic_count"],
    )
    _write_csv(
        output_dir / "d3_t11_missing_by_field.csv",
        [
            {
                "field_name": field,
                "missing_count": sum(1 for row in rows if row.get(field) in (None, "")),
            }
            for field in (
                "volume_shares",
                "amount_yuan",
                "daily_vwap",
                "daily_basic_close",
                "float_share_shares",
                "free_share_shares",
                "turnover_float",
                "turnover_free",
                "limit_status",
            )
        ],
        ["field_name", "missing_count"],
    )
    _write_csv(
        output_dir / "d3_t11_turnover_crosscheck_summary.csv",
        [
            {
                "provider_turnover_crosscheck_status": status,
                "row_count": sum(
                    1
                    for row in rows
                    if row.get("provider_turnover_crosscheck_status") == status
                ),
            }
            for status in sorted(
                {row.get("provider_turnover_crosscheck_status") for row in rows},
                key=str,
            )
        ],
        ["provider_turnover_crosscheck_status", "row_count"],
    )
    _write_csv(
        output_dir / "d3_t11_daily_vwap_range_summary.csv",
        [
            {
                "daily_vwap_range_status": status,
                "row_count": sum(
                    1 for row in rows if row.get("daily_vwap_range_status") == status
                ),
            }
            for status in sorted(
                {row.get("daily_vwap_range_status") for row in rows}, key=str
            )
        ],
        ["daily_vwap_range_status", "row_count"],
    )


def write_hash_summary(output_dir: Path) -> None:
    files = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "d3_t11_file_hash_summary.json":
            files.append(
                {
                    "file_name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "byte_count": path.stat().st_size,
                }
            )
    _write_json(output_dir / "d3_t11_file_hash_summary.json", {"files": files})


def blocked_missing_token(
    output_dir: Path, *, run_id: str, security_summary: dict[str, Any]
) -> dict[str, Any]:
    summary = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "d3_t11_generation_decision": "blocked_missing_tnskhdata_token",
        **security_summary,
        "remote_provider_called": False,
        "candidate_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }
    _write_json(output_dir / "d3_t11_generation_summary.json", summary)
    return summary


def blocked_low_security_count(
    output_dir: Path, *, run_id: str, security_summary: dict[str, Any]
) -> dict[str, Any]:
    summary = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "d3_t11_generation_decision": "blocked_low_resolved_security_count",
        **security_summary,
        "remote_provider_called": False,
        "candidate_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }
    _write_json(output_dir / "d3_t11_generation_summary.json", summary)
    _write_json(
        output_dir / "d3_t11_provider_call_summary.json",
        {
            "task_id": TASK_ID,
            **security_summary,
            "remote_provider_called": False,
            "provider_raw_payload_committed": False,
            "credential_committed": False,
            "calls": [],
        },
    )
    return summary


def blocked_missing_d3_t07_source(
    output_dir: Path,
    *,
    run_id: str,
    d3_t07_duckdb: Path,
    security_summary: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "d3_t11_generation_decision": "blocked_missing_d3_t07_source_duckdb",
        "d3_t07_duckdb": str(d3_t07_duckdb),
        **security_summary,
        "remote_provider_called": False,
        "candidate_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }
    _write_json(output_dir / "d3_t11_generation_summary.json", summary)
    _write_json(
        output_dir / "d3_t11_provider_call_summary.json",
        {
            "task_id": TASK_ID,
            **security_summary,
            "remote_provider_called": False,
            "provider_raw_payload_committed": False,
            "credential_committed": False,
            "calls": [],
        },
    )
    return summary


def _redacted_d3_t07_summary(summary: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "task_id",
        "source_task_id",
        "run_id",
        "d3_t07_generation_decision",
        "d3_rows_generated",
        "data_version_published",
        "r0_state_generated",
        "output_duckdb",
    }
    return {key: summary.get(key) for key in allowed_keys if key in summary}


def ensure_d3_t07_source_available(
    *,
    d3_t07_duckdb: Path,
    auto_generate_d3_t07_from_d2_t20: bool,
    d2_t20_duckdb: Path,
    d2_t20_acceptance_report: Path,
    d2_t20_handoff_report: Path,
    start_date: str,
    end_date: str,
    sample_securities: int | None,
) -> dict[str, Any]:
    if d3_t07_duckdb.exists():
        return {
            "d3_t07_source_status": "available",
            "d3_t07_auto_generated": False,
            "d3_t07_source_path": str(d3_t07_duckdb),
            "blocking_reasons": [],
        }
    if not auto_generate_d3_t07_from_d2_t20:
        return {
            "d3_t07_source_status": "blocked_missing_d3_t07_source",
            "d3_t07_auto_generated": False,
            "remote_provider_called": False,
            "blocking_reasons": ["missing_d3_t07_duckdb"],
        }

    required_inputs = {
        "missing_d2_t20_duckdb": d2_t20_duckdb,
        "missing_d2_t20_acceptance_report": d2_t20_acceptance_report,
        "missing_d2_t20_handoff_report": d2_t20_handoff_report,
    }
    missing = ["missing_d3_t07_duckdb"]
    missing.extend(
        reason for reason, path in required_inputs.items() if not path.exists()
    )
    if len(missing) > 1:
        return {
            "d3_t07_source_status": "blocked_missing_d2_t20_inputs",
            "d3_t07_auto_generated": False,
            "remote_provider_called": False,
            "blocking_reasons": missing,
        }

    summary = generate_d3_t07_candidate_daily_observation(
        d2_t20_duckdb=d2_t20_duckdb,
        d2_t20_acceptance_report=d2_t20_acceptance_report,
        d2_t20_handoff_report=d2_t20_handoff_report,
        output_dir=d3_t07_duckdb.parent,
        sample_securities=sample_securities,
        start_date=start_date,
        end_date=end_date,
    )
    redacted_summary = _redacted_d3_t07_summary(summary)
    if summary.get("d3_t07_generation_decision") != "accepted_candidate_observation":
        return {
            "d3_t07_source_status": "blocked_d3_t07_generation_failed",
            "d3_t07_auto_generated": True,
            "d3_t07_generation_summary": redacted_summary,
            "remote_provider_called": False,
            "blocking_reasons": ["d3_t07_generation_failed"],
        }
    if not d3_t07_duckdb.exists():
        return {
            "d3_t07_source_status": "blocked_d3_t07_output_missing",
            "d3_t07_auto_generated": True,
            "d3_t07_generation_summary": redacted_summary,
            "remote_provider_called": False,
            "blocking_reasons": ["d3_t07_output_missing_after_generation"],
        }
    return {
        "d3_t07_source_status": "auto_generated_from_d2_t20",
        "d3_t07_auto_generated": True,
        "d3_t07_source_path": str(d3_t07_duckdb),
        "d2_t20_source_path": str(d2_t20_duckdb),
        "d3_t07_generation_summary": redacted_summary,
        "blocking_reasons": [],
    }


def blocked_source_preflight(
    output_dir: Path,
    *,
    run_id: str,
    security_summary: dict[str, Any],
    source_preflight: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "d3_t11_generation_decision": source_preflight["d3_t07_source_status"],
        **security_summary,
        **source_preflight,
        "remote_provider_called": False,
        "candidate_generated": False,
        "full_candidate_run_executed": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }
    _write_json(output_dir / "d3_t11_generation_summary.json", summary)
    _write_json(
        output_dir / "d3_t11_provider_call_summary.json",
        {
            "task_id": TASK_ID,
            **security_summary,
            **source_preflight,
            "remote_provider_called": False,
            "provider_raw_payload_committed": False,
            "credential_committed": False,
            "calls": [],
        },
    )
    return summary


def generate_d3_t11_volume_amount_share_turnover_candidate(
    *,
    securities_file: Path | None = None,
    security_universe: Path = DEFAULT_SECURITY_UNIVERSE,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    d3_t07_duckdb: Path = DEFAULT_D3_T07_DUCKDB,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    auto_generate_d3_t07_from_d2_t20: bool = True,
    d2_t20_duckdb: Path = DEFAULT_D2_T20_DUCKDB,
    d2_t20_acceptance_report: Path = DEFAULT_D2_T20_ACCEPTANCE_REPORT,
    d2_t20_handoff_report: Path = DEFAULT_D2_T20_HANDOFF_REPORT,
    provider: str = "tnskhdata",
    resume: bool = False,
    max_retries: int = 2,
    sleep_seconds: float = 0.0,
    sample_securities: int | None = None,
    dry_run: bool = False,
    allow_low_security_count: bool = False,
    contract: Path = DEFAULT_CONTRACT,
    provider_client: TnskhdataClient | None = None,
    code_commit: str = "unknown",
) -> dict[str, Any]:
    ensure_allowed_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    remove_previous_outputs(output_dir, resume=resume)
    _load_json(contract)
    run_id = _utc_run_id()
    securities, security_summary = resolve_input_securities(
        securities_file=securities_file, security_universe=security_universe
    )
    selected = securities[:sample_securities] if sample_securities else securities
    if dry_run:
        summary = {
            "task_id": TASK_ID,
            "run_id": run_id,
            "dry_run": True,
            **security_summary,
            "planned_security_count": len(selected),
            "remote_provider_called": False,
            "pcvt_values_generated": False,
            "r0_state_generated": False,
            "formal_data_version_published": False,
        }
        _write_json(output_dir / "d3_t11_generation_summary.json", summary)
        return summary
    if (
        not allow_low_security_count
        and securities_file is None
        and sample_securities is None
        and security_summary["resolved_tnskhdata_security_count"]
        < MIN_RESOLVED_SECURITY_COUNT
    ):
        return blocked_low_security_count(
            output_dir, run_id=run_id, security_summary=security_summary
        )
    source_preflight = ensure_d3_t07_source_available(
        d3_t07_duckdb=d3_t07_duckdb,
        auto_generate_d3_t07_from_d2_t20=auto_generate_d3_t07_from_d2_t20,
        d2_t20_duckdb=d2_t20_duckdb,
        d2_t20_acceptance_report=d2_t20_acceptance_report,
        d2_t20_handoff_report=d2_t20_handoff_report,
        start_date=start_date,
        end_date=end_date,
        sample_securities=sample_securities,
    )
    if source_preflight["d3_t07_source_status"].startswith("blocked"):
        return blocked_source_preflight(
            output_dir,
            run_id=run_id,
            security_summary=security_summary,
            source_preflight=source_preflight,
        )

    client = provider_client
    if client is None:
        token = token_from_env()
        if not token:
            return blocked_missing_token(
                output_dir, run_id=run_id, security_summary=security_summary
            )
        client = real_tnskhdata_client(token)

    d3_rows = source_rows(
        d3_t07_duckdb,
        securities=securities,
        start_date=start_date,
        end_date=end_date,
        sample_securities=sample_securities,
    )
    daily_basic_rows, provider_calls = fetch_daily_basic_rows(
        client,
        selected,
        start_date=start_date,
        end_date=end_date,
        max_retries=max_retries,
        sleep_seconds=sleep_seconds,
    )
    candidate_rows = build_candidate_rows(
        d3_rows=d3_rows,
        daily_basic_rows=daily_basic_rows,
        d3_source_duckdb=d3_t07_duckdb,
        provider_source=provider,
        run_id=run_id,
        code_commit=code_commit,
    )
    output_duckdb = output_dir / OUTPUT_DUCKDB_NAME
    conn = duckdb.connect(str(output_duckdb))
    try:
        create_output_table(conn)
        insert_candidate_rows(conn, candidate_rows)
    finally:
        conn.close()
    summary = build_reports(
        output_dir=output_dir,
        output_duckdb=output_duckdb,
        rows=candidate_rows,
        source_row_count=len(d3_rows),
        daily_basic_rows=daily_basic_rows,
        provider_calls=provider_calls,
        run_id=run_id,
    )
    for report_name in (
        "d3_t11_generation_summary.json",
        "d3_t11_field_coverage_report.json",
        "d3_t11_quality_report.json",
        "d3_t11_provider_call_summary.json",
        "d3_t11_r0_handoff_report.json",
    ):
        path = output_dir / report_name
        payload = _load_json(path)
        payload.update(security_summary)
        payload.update(source_preflight)
        if report_name == "d3_t11_generation_summary.json":
            payload["start_date"] = start_date
            payload["end_date"] = end_date
        _write_json(path, payload)
        if report_name == "d3_t11_generation_summary.json":
            summary = payload
    write_hash_summary(output_dir)
    for forbidden in FORBIDDEN_OUTPUT_FILES | {
        f"{name}.csv" for name in forbidden_output_names()
    }:
        if (output_dir / forbidden).exists():
            raise D3T11GenerationError(f"forbidden output generated: {forbidden}")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--security-universe", type=Path, default=DEFAULT_SECURITY_UNIVERSE
    )
    parser.add_argument("--securities-file", type=Path)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--d3-t07-duckdb", type=Path, default=DEFAULT_D3_T07_DUCKDB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--auto-generate-d3-t07-from-d2-t20",
        dest="auto_generate_d3_t07_from_d2_t20",
        action="store_true",
        default=True,
    )
    parser.add_argument(
        "--no-auto-generate-d3-t07-from-d2-t20",
        dest="auto_generate_d3_t07_from_d2_t20",
        action="store_false",
    )
    parser.add_argument("--d2-t20-duckdb", type=Path, default=DEFAULT_D2_T20_DUCKDB)
    parser.add_argument(
        "--d2-t20-acceptance-report",
        type=Path,
        default=DEFAULT_D2_T20_ACCEPTANCE_REPORT,
    )
    parser.add_argument(
        "--d2-t20-handoff-report",
        type=Path,
        default=DEFAULT_D2_T20_HANDOFF_REPORT,
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--provider", default="tnskhdata")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--sample-securities", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-low-security-count", action="store_true")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    default_env_file = ROOT / ".env.local"
    if args.env_file:
        load_env_file(args.env_file)
    elif default_env_file.exists():
        load_env_file(default_env_file)
    summary = generate_d3_t11_volume_amount_share_turnover_candidate(
        securities_file=args.securities_file,
        security_universe=args.security_universe,
        start_date=args.start_date,
        end_date=args.end_date,
        d3_t07_duckdb=args.d3_t07_duckdb,
        output_dir=args.output_dir,
        auto_generate_d3_t07_from_d2_t20=args.auto_generate_d3_t07_from_d2_t20,
        d2_t20_duckdb=args.d2_t20_duckdb,
        d2_t20_acceptance_report=args.d2_t20_acceptance_report,
        d2_t20_handoff_report=args.d2_t20_handoff_report,
        provider=args.provider,
        resume=args.resume,
        max_retries=args.max_retries,
        sleep_seconds=args.sleep_seconds,
        sample_securities=args.sample_securities,
        dry_run=args.dry_run,
        allow_low_security_count=args.allow_low_security_count,
        contract=args.contract,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
