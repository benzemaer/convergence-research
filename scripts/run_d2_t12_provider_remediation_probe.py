"""Run D2-T12 provider remediation probes with redacted aggregate outputs."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib import parse, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.resolve_security_provider_codes import resolve_security_provider_codes  # noqa: E402,I001

DEFAULT_CONTRACT = (
    ROOT / "configs/d2/tnskhdata_tushare_hithink_provider_remediation_contract.v1.json"
)
UNIVERSE_COLUMNS = ["security_id", "trading_date", "universe_id", "time_segment_id"]
STATUS_FIELDS = [
    "trading_status",
    "price_limit_status",
    "suspension_status",
    "st_status",
    "limit_up_price",
    "limit_down_price",
    "is_trading_day",
    "trading_calendar_status",
]
FACTOR_FIELDS = [
    "adjustment_factor",
    "factor_as_of_time",
    "adjustment_revision",
    "adjustment_factor_direction",
    "point_in_time_eligible",
]
TUSHARE_COMPATIBLE_APIS = [
    "stock_basic",
    "trade_cal",
    "daily",
    "stk_limit",
    "adj_factor",
    "stock_st",
    "suspend_d",
    "pro_bar",
    "namechange",
]
TNSKHDATA_FACTOR_AS_OF_POLICY = (
    "tnskhdata_adj_factor_source_level_daily_ingestion_window"
)
TNSKHDATA_FACTOR_AS_OF_CLOCK = "09:20:00 Asia/Shanghai"
SNAPSHOT_REVISION_CLASS = "snapshot_level_revision"
PIT_ELIGIBILITY_CLASS = "source_level_asof_snapshot_revision"
FORBIDDEN_OUTPUT_TOKENS = ("data/raw", "data/external", "marketdb", ".duckdb", ".day")


class D2T12ProbeError(ValueError):
    """Raised when D2-T12 provider remediation gates fail."""


class HttpClient(Protocol):
    def get_json(
        self, url: str, headers: dict[str, str], params: dict[str, Any]
    ) -> dict[str, Any]:
        """Return decoded JSON without exposing request headers."""


class UrllibHttpClient:
    def get_json(
        self, url: str, headers: dict[str, str], params: dict[str, Any]
    ) -> dict[str, Any]:
        query = parse.urlencode({key: value for key, value in params.items() if value})
        target = f"{url}?{query}" if query else url
        req = request.Request(target, headers=headers, method="GET")
        with request.urlopen(req, timeout=20) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text[:10]


def _date_yyyymmdd(value: Any) -> str:
    return _date_text(value).replace("-", "")


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def load_provider_credentials(
    env_file: Path | None, allow_tnskhdata_tushare_fallback: bool
) -> dict[str, str]:
    values = _read_env_file(env_file)
    credentials = {
        "HITHINK_API_KEY": os.environ.get("HITHINK_API_KEY")
        or values.get("HITHINK_API_KEY", ""),
        "TUSHARE_TOKEN": os.environ.get("TUSHARE_TOKEN")
        or values.get("TUSHARE_TOKEN", ""),
        "TNSKHDATA_TOKEN": os.environ.get("TNSKHDATA_TOKEN")
        or values.get("TNSKHDATA_TOKEN", ""),
    }
    if allow_tnskhdata_tushare_fallback and not credentials["TNSKHDATA_TOKEN"]:
        credentials["TNSKHDATA_TOKEN"] = credentials["TUSHARE_TOKEN"]
    return credentials


def _guard_output_dir(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if any(token in normalized for token in FORBIDDEN_OUTPUT_TOKENS):
        raise D2T12ProbeError(f"output-dir is forbidden: {path}")


def _load_candidate_universe(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise D2T12ProbeError(f"candidate universe does not exist: {path}")
    if path.suffix.lower() == ".parquet":
        import pandas as pd
        import pyarrow.parquet as pq

        available = set(pq.ParquetFile(path).schema.names)
        missing = sorted(set(UNIVERSE_COLUMNS) - available)
        if missing:
            raise D2T12ProbeError(f"candidate universe missing fields: {missing}")
        frame = pd.read_parquet(path, columns=UNIVERSE_COLUMNS)
        frame["trading_date"] = frame["trading_date"].map(_date_text)
        frame = frame.drop_duplicates(UNIVERSE_COLUMNS)
        return [
            {field: row[field] for field in UNIVERSE_COLUMNS}
            for row in frame.to_dict(orient="records")
        ]
    payload = _load_json(path)
    rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise D2T12ProbeError("candidate universe must be parquet or row JSON")
    output = []
    for row in rows:
        if any(field not in row for field in UNIVERSE_COLUMNS):
            raise D2T12ProbeError("candidate universe row missing required fields")
        output.append(
            {
                "security_id": str(row["security_id"]),
                "trading_date": _date_text(row["trading_date"]),
                "universe_id": str(row["universe_id"]),
                "time_segment_id": str(row["time_segment_id"]),
            }
        )
    return output


def sample_candidate_universe(
    rows: list[dict[str, Any]],
    max_securities: int = 20,
    max_dates_per_security: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_security: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_security.setdefault(str(row["security_id"]), []).append(row)
    selected_securities: list[str] = []
    for predicate in (
        lambda value: value.startswith(("XSHE.", "SZSE.", "CN.SZSE.")),
        lambda value: value.startswith(("XSHG.", "SHSE.", "CN.SSE.")),
        lambda value: value.endswith(".SZ"),
        lambda value: value.endswith(".SH"),
    ):
        match = next((sec for sec in by_security if predicate(sec)), None)
        if match and match not in selected_securities:
            selected_securities.append(match)
    for security_id in sorted(by_security):
        if len(selected_securities) >= max_securities:
            break
        if security_id not in selected_securities:
            selected_securities.append(security_id)
    sample: list[dict[str, Any]] = []
    for security_id in selected_securities:
        dates = sorted(by_security[security_id], key=lambda row: row["trading_date"])
        sample.extend(dates[-max_dates_per_security:])
    exchanges = {
        resolve_security_provider_codes(security_id).exchange
        for security_id in selected_securities
    }
    limitation = []
    if "SZSE" not in exchanges or "SSE" not in exchanges:
        limitation.append("sample_does_not_cover_both_szse_and_sse")
    return sample, {
        "sample_mode": "latest_and_eventful",
        "candidate_universe_total_count": len(rows),
        "sample_row_count": len(sample),
        "sample_security_count": len(selected_securities),
        "sample_exchange_coverage": sorted(
            exchange for exchange in exchanges if exchange
        ),
        "sample_coverage_limitation": limitation,
    }


def _empty_capability(
    provider_id: str,
    api_name: str,
    status: str,
    rows_requested: int,
    error_category: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "api_name": api_name,
        "probe_status": status,
        "rows_requested": rows_requested,
        "rows_returned": 0,
        "fields_returned": [],
        "required_fields_covered": [],
        "required_fields_missing": [],
        "error_code_category": error_category,
        "error_message_redacted": message,
    }


def _frame_records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "empty") and frame.empty:
        return []
    if hasattr(frame, "to_dict"):
        return [dict(row) for row in frame.to_dict("records")]
    if isinstance(frame, list):
        return [dict(row) for row in frame if isinstance(row, dict)]
    return []


def _capability_from_records(
    provider_id: str,
    api_name: str,
    rows_requested: int,
    records: list[dict[str, Any]],
    required_fields: list[str],
) -> dict[str, Any]:
    fields = sorted({field for row in records for field in row})
    covered = sorted(set(fields) & set(required_fields))
    missing = sorted(set(required_fields) - set(fields))
    return {
        "provider_id": provider_id,
        "api_name": api_name,
        "probe_status": "ok"
        if records and not missing
        else "field_missing"
        if records
        else "empty",
        "rows_requested": rows_requested,
        "rows_returned": len(records),
        "fields_returned": fields,
        "required_fields_covered": covered,
        "required_fields_missing": missing,
        "error_code_category": None,
        "error_message_redacted": None,
    }


class TushareCompatibleProviderAdapter:
    provider_id = "tushare"
    token_key = "TUSHARE_TOKEN"

    def __init__(self, pro_client: Any | None = None) -> None:
        self.pro_client = pro_client

    def _client(self, token: str) -> Any:
        if self.pro_client is not None:
            return self.pro_client
        if not token:
            raise D2T12ProbeError(f"{self.provider_id} token missing")
        module = __import__("tushare")
        return module.pro_api(token)

    def probe(
        self, sample_rows: list[dict[str, Any]], credentials: dict[str, str]
    ) -> dict[str, Any]:
        token = credentials.get(self.token_key, "")
        try:
            client = self._client(token)
        except Exception as exc:
            return self._failed(sample_rows, f"client_init_failed:{type(exc).__name__}")
        matrix = []
        status_rows: list[dict[str, Any]] = []
        factor_rows: list[dict[str, Any]] = []
        for api_name in TUSHARE_COMPATIBLE_APIS:
            try:
                records = self._probe_api(client, api_name, sample_rows)
                matrix.append(
                    _capability_from_records(
                        self.provider_id,
                        api_name,
                        len(sample_rows),
                        records,
                        self._required_fields(api_name),
                    )
                )
                status_rows.extend(self._status_rows(api_name, records, sample_rows))
                factor_rows.extend(self._factor_rows(api_name, records, sample_rows))
            except Exception as exc:
                matrix.append(
                    _empty_capability(
                        self.provider_id,
                        api_name,
                        "provider_probe_failed",
                        len(sample_rows),
                        type(exc).__name__,
                        "provider API call failed",
                    )
                )
        return {
            "provider_id": self.provider_id,
            "capability_matrix": matrix,
            "status_rows": status_rows,
            "factor_rows": factor_rows,
        }

    def _failed(self, sample_rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capability_matrix": [
                _empty_capability(
                    self.provider_id,
                    api_name,
                    "provider_probe_failed",
                    len(sample_rows),
                    reason,
                    "provider client unavailable",
                )
                for api_name in TUSHARE_COMPATIBLE_APIS
            ],
            "status_rows": [],
            "factor_rows": [],
        }

    def _required_fields(self, api_name: str) -> list[str]:
        return {
            "stock_basic": ["ts_code", "name"],
            "trade_cal": ["cal_date", "is_open"],
            "daily": ["ts_code", "trade_date", "open", "high", "low", "close"],
            "stk_limit": ["ts_code", "trade_date", "up_limit", "down_limit"],
            "adj_factor": ["ts_code", "trade_date", "adj_factor"],
            "stock_st": ["ts_code"],
            "suspend_d": ["ts_code", "suspend_date"],
            "pro_bar": ["ts_code", "trade_date", "close"],
            "namechange": ["ts_code", "name", "start_date"],
        }.get(api_name, [])

    def _probe_api(
        self, client: Any, api_name: str, sample_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        first = sample_rows[0] if sample_rows else {}
        mapping = resolve_security_provider_codes(str(first.get("security_id", "")))
        ts_code = mapping.tushare_ts_code
        trade_date = _date_yyyymmdd(first.get("trading_date"))
        if api_name == "stock_basic":
            return _frame_records(client.stock_basic(exchange="", list_status="L"))
        if api_name == "trade_cal":
            return _frame_records(client.trade_cal(exchange="", cal_date=trade_date))
        if api_name == "daily":
            return _frame_records(client.daily(ts_code=ts_code, trade_date=trade_date))
        if api_name == "stk_limit":
            return _frame_records(
                client.stk_limit(ts_code=ts_code, trade_date=trade_date)
            )
        if api_name == "adj_factor":
            records = _frame_records(client.adj_factor(trade_date=trade_date))
            if records:
                return records
            return _frame_records(client.adj_factor(ts_code=ts_code, trade_date=""))
        if api_name == "stock_st":
            fn = getattr(client, "stock_st", None)
            if fn is None:
                raise AttributeError("stock_st")
            return _frame_records(fn(ts_code=ts_code, trade_date=trade_date))
        if api_name == "suspend_d":
            fn = getattr(client, "suspend_d", None) or getattr(client, "suspend", None)
            if fn is None:
                raise AttributeError("suspend_d")
            return _frame_records(fn(ts_code=ts_code, suspend_date=trade_date))
        if api_name == "pro_bar":
            fn = getattr(client, "pro_bar", None)
            if fn is None:
                raise AttributeError("pro_bar")
            return _frame_records(
                fn(ts_code=ts_code, start_date=trade_date, end_date=trade_date)
            )
        if api_name == "namechange":
            return _frame_records(client.namechange(ts_code=ts_code))
        return []

    def _status_rows(
        self,
        api_name: str,
        records: list[dict[str, Any]],
        sample_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not records:
            return []
        by_key = {(row["security_id"], row["trading_date"]): row for row in sample_rows}
        output: list[dict[str, Any]] = []
        for sample in by_key.values():
            base = {
                **sample,
                "provider_id": self.provider_id,
                "trading_status": "unknown",
                "price_limit_status": "unknown",
                "suspension_status": "unknown",
                "st_status": "unknown",
                "limit_up_price": None,
                "limit_down_price": None,
                "is_trading_day": None,
                "trading_calendar_status": "unknown",
            }
            if api_name == "trade_cal":
                match = next(
                    (
                        row
                        for row in records
                        if str(row.get("cal_date"))
                        == _date_yyyymmdd(sample["trading_date"])
                    ),
                    None,
                )
                if match:
                    is_open = str(match.get("is_open")) == "1"
                    base["is_trading_day"] = is_open
                    base["trading_calendar_status"] = "open" if is_open else "closed"
            if api_name == "daily":
                base["trading_status"] = "normal_trading"
            if api_name == "stk_limit":
                match = records[0]
                base["limit_up_price"] = _to_float(match.get("up_limit"))
                base["limit_down_price"] = _to_float(match.get("down_limit"))
            if api_name == "suspend_d":
                base["suspension_status"] = "suspended"
            if api_name == "stock_st":
                base["st_status"] = "st"
                base["st_status_evidence_method"] = "stock_st"
            if api_name == "namechange":
                base["st_status"] = "st_candidate"
                base["st_status_evidence_method"] = "namechange_derived_candidate"
            output.append(base)
        return output

    def _factor_rows(
        self,
        api_name: str,
        records: list[dict[str, Any]],
        sample_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if api_name != "adj_factor" or not records:
            return []
        output = []
        for sample in sample_rows:
            record = next(
                (
                    row
                    for row in records
                    if str(row.get("trade_date"))
                    == _date_yyyymmdd(sample["trading_date"])
                ),
                records[0],
            )
            factor = _to_float(record.get("adj_factor"))
            snapshot_id = sample.get("source_snapshot_id") or sample.get(
                "run_id", "candidate_snapshot_revision"
            )
            artifact_hash = sample.get("artifact_sha256") or sample.get(
                "source_snapshot_sha256", "candidate_artifact_sha256_pending"
            )
            output.append(
                {
                    **sample,
                    "provider_id": self.provider_id,
                    "adjustment_factor": factor,
                    "adjustment_factor_status": "resolved"
                    if factor is not None
                    else "unresolved",
                    "factor_as_of_time": source_level_factor_as_of_time(
                        sample["trading_date"]
                    )
                    if factor is not None
                    else None,
                    "factor_as_of_time_policy": TNSKHDATA_FACTOR_AS_OF_POLICY,
                    "row_level_factor_as_of_time_available": False,
                    "adjustment_revision": snapshot_id if factor is not None else None,
                    "adjustment_revision_class": SNAPSHOT_REVISION_CLASS,
                    "adjustment_revision_hash": artifact_hash
                    if factor is not None
                    else None,
                    "provider_row_level_revision_available": False,
                    "adjustment_factor_direction": "provider_adj_factor",
                    "point_in_time_eligible": factor is not None,
                    "point_in_time_eligibility_class": PIT_ELIGIBILITY_CLASS,
                    "point_in_time_eligible_for_eod_research": factor is not None,
                    "strict_provider_row_level_revision_eligible": False,
                }
            )
        return output


class TnskhdataProviderAdapter(TushareCompatibleProviderAdapter):
    provider_id = "tnskhdata"
    token_key = "TNSKHDATA_TOKEN"

    def _client(self, token: str) -> Any:
        if self.pro_client is not None:
            return self.pro_client
        if not token:
            raise D2T12ProbeError("tnskhdata token missing")
        module = __import__("tnskhdata")
        return module.pro_api(token)


class BaoStockProviderAdapter:
    provider_id = "baostock"

    def __init__(self, module: Any | None = None) -> None:
        self.module = module

    def probe(
        self, sample_rows: list[dict[str, Any]], credentials: dict[str, str]
    ) -> dict[str, Any]:
        del credentials
        try:
            bs = self.module or __import__("baostock")
        except Exception as exc:
            return self._failed(sample_rows, f"import_failed:{type(exc).__name__}")
        status_rows = []
        matrix_rows = []
        try:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                login = bs.login()
            if getattr(login, "error_code", "0") != "0":
                return self._failed(sample_rows, "login_failed")
            for sample in sample_rows:
                mapping = resolve_security_provider_codes(sample["security_id"])
                if mapping.mapping_status != "resolved":
                    continue
                result = bs.query_history_k_data_plus(
                    mapping.baostock_code,
                    "date,code,open,high,low,close,preclose,volume,amount,tradestatus,isST,adjustflag",
                    start_date=sample["trading_date"],
                    end_date=sample["trading_date"],
                    frequency="d",
                    adjustflag="3",
                )
                rows = []
                while result.next():
                    rows.append(
                        dict(zip(result.fields, result.get_row_data(), strict=False))
                    )
                matrix_rows.extend(rows)
                for row in rows:
                    status_rows.append(self._status_row(sample, row))
        except Exception as exc:
            return self._failed(sample_rows, f"probe_failed:{type(exc).__name__}")
        finally:
            try:
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    bs.logout()
            except Exception:
                pass
        return {
            "provider_id": self.provider_id,
            "capability_matrix": [
                _capability_from_records(
                    self.provider_id,
                    "query_history_k_data_plus",
                    len(sample_rows),
                    matrix_rows,
                    ["date", "code", "tradestatus", "isST", "close"],
                )
            ],
            "status_rows": status_rows,
            "factor_rows": [],
        }

    def _failed(self, sample_rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capability_matrix": [
                _empty_capability(
                    self.provider_id,
                    "query_history_k_data_plus",
                    "provider_probe_failed",
                    len(sample_rows),
                    reason,
                    "baostock probe failed",
                )
            ],
            "status_rows": [],
            "factor_rows": [],
        }

    def _status_row(
        self, sample: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any]:
        trade_status = str(row.get("tradestatus", ""))
        is_st = str(row.get("isST", ""))
        close_value = _to_float(row.get("close"))
        return {
            **sample,
            "provider_id": self.provider_id,
            "trading_status": "normal_trading"
            if trade_status == "1"
            else "suspended"
            if trade_status == "0"
            else "unknown",
            "price_limit_status": "unknown",
            "suspension_status": "not_suspended"
            if trade_status == "1"
            else "suspended"
            if trade_status == "0"
            else "unknown",
            "st_status": "st"
            if is_st == "1"
            else "not_st"
            if is_st == "0"
            else "unknown",
            "limit_up_price": None
            if close_value is None
            else round(close_value * 1.1, 4),
            "limit_down_price": None
            if close_value is None
            else round(close_value * 0.9, 4),
            "limit_price_evidence_method": "candidate_derived_unverified",
            "is_trading_day": trade_status == "1",
            "trading_calendar_status": "open"
            if trade_status == "1"
            else "closed_or_suspended",
        }


class HiThinkRestProviderAdapter:
    provider_id = "hithink_financial_api"

    def __init__(
        self,
        base_url: str = "https://api.hithink.com",
        http_client: HttpClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or UrllibHttpClient()

    def probe(
        self, sample_rows: list[dict[str, Any]], credentials: dict[str, str]
    ) -> dict[str, Any]:
        token = credentials.get("HITHINK_API_KEY", "")
        if not token:
            return self._failed(sample_rows, "hithink_api_key_missing")
        endpoints = {
            "/api/meta/tickers/search": ["ticker", "thscode"],
            "/api/meta/tickers/list": ["ticker", "thscode"],
            "/api/a-share/prices/historical": ["date", "open", "close"],
            "/api/a-share/corporate-actions/adjustment-factors": [
                "date",
                "adjustment_factor",
            ],
            "/api/a-share/calendar/trading-days": ["date", "is_trading_day"],
            "/api/a-share/special-data/limit-up-pool": ["date", "limit_up_price"],
        }
        matrix = []
        for endpoint, required in endpoints.items():
            try:
                first = sample_rows[0] if sample_rows else {}
                mapping = resolve_security_provider_codes(
                    str(first.get("security_id", ""))
                )
                payload = self.http_client.get_json(
                    self.base_url + endpoint,
                    headers={"X-api-key": token},
                    params={
                        "thscode": mapping.hithink_thscode,
                        "date": first.get("trading_date"),
                    },
                )
                code = payload.get("code", 0)
                if code not in (0, "0", None):
                    matrix.append(
                        _empty_capability(
                            self.provider_id,
                            endpoint,
                            "provider_probe_failed",
                            len(sample_rows),
                            f"business_code_{code}",
                            "business code not successful",
                        )
                    )
                    continue
                records = payload.get("data", [])
                if isinstance(records, dict):
                    records = [records]
                matrix.append(
                    _capability_from_records(
                        self.provider_id,
                        endpoint,
                        len(sample_rows),
                        [dict(row) for row in records if isinstance(row, dict)],
                        required,
                    )
                )
            except Exception as exc:
                matrix.append(
                    _empty_capability(
                        self.provider_id,
                        endpoint,
                        "provider_probe_failed",
                        len(sample_rows),
                        type(exc).__name__,
                        "HiThink REST call failed",
                    )
                )
        return {
            "provider_id": self.provider_id,
            "capability_matrix": matrix,
            "status_rows": [],
            "factor_rows": [],
        }

    def _failed(self, sample_rows: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capability_matrix": [
                _empty_capability(
                    self.provider_id,
                    "hithink_rest",
                    "provider_probe_failed",
                    len(sample_rows),
                    reason,
                    "HiThink REST client unavailable",
                )
            ],
            "status_rows": [],
            "factor_rows": [],
        }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def source_level_factor_as_of_time(trading_date: Any) -> str:
    return f"{_date_yyyymmdd(trading_date)} {TNSKHDATA_FACTOR_AS_OF_CLOCK}"


def classify_trading_status(
    *,
    trading_date: Any,
    stock_basic: dict[str, Any] | None,
    trade_cal: dict[str, Any] | None,
    daily_row: dict[str, Any] | None,
    suspend_row: dict[str, Any] | None,
) -> str:
    trade_date = _date_yyyymmdd(trading_date)
    stock_basic = stock_basic or {}
    list_date = _date_yyyymmdd(stock_basic.get("list_date"))
    delist_date = _date_yyyymmdd(stock_basic.get("delist_date"))
    if list_date and trade_date < list_date:
        return "not_listed_yet"
    if delist_date and trade_date > delist_date:
        return "after_delist"
    if str((trade_cal or {}).get("is_open")) == "0":
        return "market_closed"
    if str((suspend_row or {}).get("suspend_type")) == "S":
        return "suspended"
    if daily_row:
        return "normal_trading"
    return "provider_empty_or_unclassified"


def classify_suspension_status(
    *,
    trading_status: str,
    daily_row: dict[str, Any] | None,
    suspend_row: dict[str, Any] | None,
) -> str:
    suspend_type = str((suspend_row or {}).get("suspend_type", ""))
    if suspend_type == "S":
        return "suspended"
    if suspend_type == "R":
        return "resumed"
    if daily_row and suspend_type != "S":
        return "not_suspended"
    if trading_status in {"not_listed_yet", "market_closed", "after_delist"}:
        return "not_applicable"
    return "unresolved"


def classify_st_status(
    *,
    trading_status: str,
    stock_st_row: dict[str, Any] | None,
    namechange_row: dict[str, Any] | None = None,
) -> dict[str, str]:
    if trading_status in {"not_listed_yet", "after_delist", "market_closed"}:
        return {"st_status": "not_applicable", "st_status_evidence_method": "calendar"}
    if stock_st_row:
        return {"st_status": "st", "st_status_evidence_method": "stock_st"}
    if namechange_row:
        return {
            "st_status": "st_candidate",
            "st_status_evidence_method": "namechange_derived_candidate",
        }
    return {"st_status": "not_st", "st_status_evidence_method": "stock_st_absence"}


def derive_price_limit_status(
    *,
    trading_status: str,
    daily_row: dict[str, Any] | None,
    stk_limit_row: dict[str, Any] | None,
    epsilon: float = 0.001,
) -> dict[str, Any]:
    if trading_status in {
        "not_listed_yet",
        "after_delist",
        "market_closed",
        "suspended",
    }:
        return {
            "price_limit_status": "not_applicable",
            "limit_up_price": None,
            "limit_down_price": None,
            "price_limit_status_evidence_method": "provider_stk_limit_plus_daily_ohlc",
        }
    up_limit = _to_float((stk_limit_row or {}).get("up_limit"))
    down_limit = _to_float((stk_limit_row or {}).get("down_limit"))
    if not daily_row or up_limit is None or down_limit is None:
        return {
            "price_limit_status": "unresolved",
            "limit_up_price": up_limit,
            "limit_down_price": down_limit,
            "price_limit_status_evidence_method": "provider_stk_limit_plus_daily_ohlc",
        }
    high = _to_float(daily_row.get("high"))
    low = _to_float(daily_row.get("low"))
    close = _to_float(daily_row.get("close"))
    if any(
        value is not None and value >= up_limit - epsilon for value in (high, close)
    ):
        status = "limit_up_touched_or_closed"
    elif any(
        value is not None and value <= down_limit + epsilon for value in (low, close)
    ):
        status = "limit_down_touched_or_closed"
    else:
        status = "not_limited"
    return {
        "price_limit_status": status,
        "limit_up_price": up_limit,
        "limit_down_price": down_limit,
        "price_limit_status_evidence_method": "provider_stk_limit_plus_daily_ohlc",
    }


def build_adj_factor_snapshot_revision(
    *,
    trading_date: Any,
    adj_factor_row: dict[str, Any],
    source_snapshot_id: str,
    artifact_sha256: str,
) -> dict[str, Any]:
    factor = _to_float(adj_factor_row.get("adj_factor"))
    return {
        "adjustment_factor": factor,
        "adjustment_factor_status": "resolved" if factor is not None else "unresolved",
        "factor_as_of_time": source_level_factor_as_of_time(trading_date)
        if factor is not None
        else None,
        "factor_as_of_time_policy": TNSKHDATA_FACTOR_AS_OF_POLICY,
        "row_level_factor_as_of_time_available": False,
        "adjustment_revision": source_snapshot_id if factor is not None else None,
        "adjustment_revision_class": SNAPSHOT_REVISION_CLASS,
        "adjustment_revision_hash": artifact_sha256 if factor is not None else None,
        "provider_row_level_revision_available": False,
        "point_in_time_eligibility_class": PIT_ELIGIBILITY_CLASS,
        "point_in_time_eligible_for_eod_research": factor is not None,
        "strict_provider_row_level_revision_eligible": False,
        "point_in_time_eligible": factor is not None,
    }


def _is_known(value: Any) -> bool:
    return value not in (None, "", "unknown", "unresolved")


def _first_known(rows: list[dict[str, Any]], field: str) -> tuple[Any, str | None]:
    for row in rows:
        value = row.get(field)
        if _is_known(value):
            return value, str(row.get("provider_id"))
    return None, None


def _field_coverage(
    rows: list[dict[str, Any]], sample_rows: list[dict[str, Any]], fields: list[str]
) -> dict[str, Any]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault((row["security_id"], row["trading_date"]), []).append(row)
    resolved_counts = {}
    unresolved_counts = {}
    fallback_counts = {"tnskhdata": 0, "baostock": 0, "tushare": 0}
    conflicts = []
    for field in fields:
        resolved = 0
        for sample in sample_rows:
            key_rows = by_key.get((sample["security_id"], sample["trading_date"]), [])
            value, provider = _first_known(key_rows, field)
            if _is_known(value):
                resolved += 1
                if provider in fallback_counts:
                    fallback_counts[provider] += 1
            known_values = {
                str(row.get(field)) for row in key_rows if _is_known(row.get(field))
            }
            if len(known_values) > 1:
                conflicts.append({"field": field, "provider_count": len(known_values)})
        resolved_counts[field] = resolved
        unresolved_counts[field] = len(sample_rows) - resolved
    return {
        "resolved_counts_by_field": resolved_counts,
        "unresolved_counts_by_field": unresolved_counts,
        "fallback_used_counts_by_source": fallback_counts,
        "conflict_count": len(conflicts),
        "conflict_fields": sorted({item["field"] for item in conflicts}),
    }


def _mapping_report(sample_rows: list[dict[str, Any]]) -> dict[str, Any]:
    mappings = [
        resolve_security_provider_codes(row["security_id"]) for row in sample_rows
    ]
    unresolved = [item for item in mappings if item.mapping_status != "resolved"]
    return {
        "mapping_success_count": len(mappings) - len(unresolved),
        "mapping_failure_count": len(unresolved),
        "mapping_blocking_reasons": sorted(
            {reason for item in unresolved for reason in item.mapping_blocking_reasons}
        ),
        "query_skipped_for_unmapped_count": len(unresolved),
    }


def _provider_failure_categories(matrix: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in matrix:
        category = row.get("error_code_category") or row.get("probe_status")
        counts[str(category)] = counts.get(str(category), 0) + 1
    return counts


def run_provider_remediation_probe(
    *,
    contract: dict[str, Any],
    candidate_universe_path: Path,
    output_dir: Path,
    credentials: dict[str, str],
    max_securities: int = 20,
    max_dates_per_security: int = 5,
    adapters: list[Any] | None = None,
) -> dict[str, Any]:
    if (
        contract.get("contract_id")
        != "D2_TNSKHDATA_TUSHARE_HITHINK_PROVIDER_REMEDIATION_CONTRACT_V1"
    ):
        raise D2T12ProbeError("wrong D2-T12 contract")
    for key in [
        "formal_source_acceptance_authorized",
        "formal_ingestion_authorized",
        "duckdb_write_authorized",
        "manifest_creation_authorized",
        "data_version_release_authorized",
        "d3_generation_authorized",
        "r0_state_generation_authorized",
    ]:
        if contract.get(key) is not False:
            raise D2T12ProbeError(f"{key} must remain false")
    _guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    universe = _load_candidate_universe(candidate_universe_path)
    sample, sample_report = sample_candidate_universe(
        universe,
        max_securities=max_securities,
        max_dates_per_security=max_dates_per_security,
    )
    mapped_sample = [
        row
        for row in sample
        if resolve_security_provider_codes(row["security_id"]).mapping_status
        == "resolved"
    ]
    adapters = adapters or [
        HiThinkRestProviderAdapter(),
        TnskhdataProviderAdapter(),
        BaoStockProviderAdapter(),
        TushareCompatibleProviderAdapter(),
    ]
    capability_matrix: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    if mapped_sample:
        for adapter in adapters:
            result = adapter.probe(mapped_sample, credentials)
            capability_matrix.extend(result["capability_matrix"])
            status_rows.extend(result["status_rows"])
            factor_rows.extend(result["factor_rows"])
    mapping = _mapping_report(sample)
    status_coverage = _field_coverage(status_rows, mapped_sample, STATUS_FIELDS)
    factor_coverage = _field_coverage(factor_rows, mapped_sample, FACTOR_FIELDS)
    discrepancy = {
        "source_status_conflict_count": status_coverage["conflict_count"],
        "factor_evidence_conflict_count": factor_coverage["conflict_count"],
        "conflict_count": status_coverage["conflict_count"]
        + factor_coverage["conflict_count"],
        "conflict_fields": sorted(
            set(status_coverage["conflict_fields"])
            | set(factor_coverage["conflict_fields"])
        ),
        "silent_override_count": 0,
    }
    remaining_blockers = []
    if any(status_coverage["unresolved_counts_by_field"].values()):
        remaining_blockers.append("source_status_unresolved")
    if any(factor_coverage["unresolved_counts_by_field"].values()):
        remaining_blockers.append("factor_evidence_unresolved")
    if factor_coverage["unresolved_counts_by_field"].get("factor_as_of_time", 0):
        remaining_blockers.append("factor_as_of_time_unresolved")
    if factor_coverage["unresolved_counts_by_field"].get("adjustment_revision", 0):
        remaining_blockers.append("adjustment_revision_unresolved")
    if factor_coverage["unresolved_counts_by_field"].get("point_in_time_eligible", 0):
        remaining_blockers.append("point_in_time_evidence_unresolved")
    if discrepancy["conflict_count"]:
        remaining_blockers.append("provider_discrepancy_unresolved")
    gate = {
        **sample_report,
        "mapped_probe_row_count": len(mapped_sample),
        "provider_count": len(adapters),
        "provider_failure_categories": _provider_failure_categories(capability_matrix),
        "d2_acceptance_decision": "accepted_for_d3_candidate_generation"
        if not remaining_blockers
        else "blocked_pending_source_status_resolution",
        "d3_handoff_decision": "d3_candidate_generation_allowed"
        if not remaining_blockers
        else "d3_candidate_generation_blocked",
        "r0_handoff_decision": "r0_blocked",
        "remaining_blockers": sorted(set(remaining_blockers)),
        "duckdb_written": False,
        "data_version_published": False,
        "d3_rows_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }
    outputs = {
        "provider_capability_matrix": capability_matrix,
        "security_code_mapping_probe_report": mapping,
        "source_status_field_coverage_report": status_coverage,
        "factor_evidence_field_coverage_report": factor_coverage,
        "provider_discrepancy_report": discrepancy,
        "d2_t12_gate_decision_summary": gate,
    }
    paths = {}
    for name, payload in outputs.items():
        path = output_dir / f"{name}.json"
        _write_json(path, payload)
        paths[name] = path
    hash_summary = {
        name: {"sha256": _sha256_file(path), "size_bytes": path.stat().st_size}
        for name, path in paths.items()
    }
    hash_path = output_dir / "candidate_file_hash_summary.json"
    _write_json(hash_path, hash_summary)
    return {
        "reports": {name: str(path) for name, path in paths.items()},
        "report_hashes": hash_summary,
        "candidate_file_hash_summary": str(hash_path),
        "redacted_summary": {
            "sample": sample_report,
            "mapping": mapping,
            "source_status": status_coverage,
            "factor_evidence": factor_coverage,
            "discrepancy": discrepancy,
            "gate": gate,
        },
        "no_row_level_payload_returned": True,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument("--candidate-universe", required=True, type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--allow-tnskhdata-tushare-token-fallback", action="store_true")
    parser.add_argument("--remote-max-securities", default=20, type=int)
    parser.add_argument("--remote-max-dates-per-security", default=5, type=int)
    parser.add_argument("--remote-sample-mode", default="latest_and_eventful")
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.remote_sample_mode != "latest_and_eventful":
        raise D2T12ProbeError("only latest_and_eventful sample mode is supported")
    report = run_provider_remediation_probe(
        contract=_load_json(args.contract),
        candidate_universe_path=args.candidate_universe,
        output_dir=args.output_dir,
        credentials=load_provider_credentials(
            args.env_file, args.allow_tnskhdata_tushare_token_fallback
        ),
        max_securities=args.remote_max_securities,
        max_dates_per_security=args.remote_max_dates_per_security,
    )
    print(json.dumps(report["redacted_summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
