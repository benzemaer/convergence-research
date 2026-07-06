"""Probe minimal tnskhdata daily/daily_basic fields with redacted summaries."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.d3_t10_field_standardization import combine_standardized_fields  # noqa: E402

TASK_ID = "D3-T10"
DEFAULT_SAMPLE_SECURITIES = ("000001.SZ", "600000.SH", "688981.SH")
DEFAULT_START_DATE = "20260601"
DEFAULT_END_DATE = "20260605"
TOKEN_ENV_NAMES = ("TNSKHDATA_TOKEN", "TUSHARE_TOKEN", "TNS_TOKEN")


class TnskhdataClient(Protocol):
    def daily(self, *, ts_code: str, start_date: str, end_date: str) -> Any: ...

    def daily_basic(self, *, ts_code: str, start_date: str, end_date: str) -> Any: ...


def token_from_env() -> str | None:
    for name in TOKEN_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            return value
    return None


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


def _non_null_rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(field) not in (None, "")) / len(rows)


def summarize_probe(
    *,
    daily_rows: list[dict[str, Any]],
    daily_basic_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    daily_fields = ("vol", "amount")
    daily_basic_fields = (
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
        "limit_status",
    )
    joined_checks = []
    by_key = {
        (row.get("ts_code"), row.get("trade_date")): row for row in daily_basic_rows
    }
    for row in daily_rows:
        key = (row.get("ts_code"), row.get("trade_date"))
        if key in by_key:
            standardized = combine_standardized_fields(row, by_key[key])
            joined_checks.append(
                {
                    "ts_code": row.get("ts_code"),
                    "trade_date": row.get("trade_date"),
                    "amount_volume_unit_status": standardized[
                        "amount_volume_unit_status"
                    ],
                    "daily_vwap_range_status": standardized["daily_vwap_range_status"],
                    "share_field_status": standardized["share_field_status"],
                    "turnover_field_status": standardized["turnover_field_status"],
                    "provider_turnover_crosscheck_status": standardized[
                        "provider_turnover_crosscheck_status"
                    ],
                }
            )
    return {
        "task_id": TASK_ID,
        "raw_payload_redacted": True,
        "remote_provider_called": True,
        "daily_row_count": len(daily_rows),
        "daily_basic_row_count": len(daily_basic_rows),
        "daily_field_non_null_rates": {
            field: _non_null_rate(daily_rows, field) for field in daily_fields
        },
        "daily_basic_field_non_null_rates": {
            field: _non_null_rate(daily_basic_rows, field)
            for field in daily_basic_fields
        },
        "joined_quality_checks": joined_checks,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }


def run_probe_with_client(
    client: TnskhdataClient,
    *,
    securities: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    daily_rows: list[dict[str, Any]] = []
    daily_basic_rows: list[dict[str, Any]] = []
    for ts_code in securities:
        daily_rows.extend(
            _records(
                client.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            )
        )
        daily_basic_rows.extend(
            _records(
                client.daily_basic(
                    ts_code=ts_code, start_date=start_date, end_date=end_date
                )
            )
        )
    return summarize_probe(daily_rows=daily_rows, daily_basic_rows=daily_basic_rows)


def blocked_missing_token_summary() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "probe_decision": "blocked_missing_tnskhdata_token",
        "remote_provider_called": False,
        "raw_payload_redacted": True,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "formal_data_version_published": False,
    }


def _real_client(token: str) -> TnskhdataClient:
    try:
        import tnskhdata as ts  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("tnskhdata package is not available") from exc
    if hasattr(ts, "pro_api"):
        return ts.pro_api(token)
    if hasattr(ts, "set_token"):
        ts.set_token(token)
    return ts.pro_api()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--securities", nargs="*", default=list(DEFAULT_SAMPLE_SECURITIES)
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    token = token_from_env()
    if not token:
        summary = blocked_missing_token_summary()
    else:
        try:
            summary = run_probe_with_client(
                _real_client(token),
                securities=args.securities[:5],
                start_date=args.start_date,
                end_date=args.end_date,
            )
        except Exception as exc:  # pragma: no cover - exercised only with provider.
            summary = {
                "task_id": TASK_ID,
                "probe_decision": "blocked_provider_probe_error",
                "error_type": type(exc).__name__,
                "remote_provider_called": True,
                "raw_payload_redacted": True,
                "pcvt_values_generated": False,
                "r0_state_generated": False,
                "formal_data_version_published": False,
            }
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
