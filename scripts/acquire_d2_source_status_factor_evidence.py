"""Acquire local D2-T11 source status and factor evidence candidates."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "configs/d2/source_status_factor_evidence_acceptance_handoff_contract.v1.json"
)
DEFAULT_SOURCE_REGISTRY = ROOT / "configs/d2/formal_source_registry_contract.v1.json"
SOURCE_PRIORITY = {"hithink_financial_api": 0, "baostock": 1, "tushare": 2}
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
UNIVERSE_FIELDS = ["security_id", "trading_date", "universe_id", "time_segment_id"]
FORBIDDEN_TOKENS = ("marketdb", ".duckdb", ".day")
FORBIDDEN_OUTPUT_TOKENS = ("data/raw", "data/external")


class D2T11AcquisitionError(ValueError):
    """Raised when D2-T11 acquisition gates fail."""


class ProviderAdapter(Protocol):
    provider_id: str

    def probe(
        self, universe_rows: list[dict[str, Any]], credentials: dict[str, str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Return status rows, factor rows, and aggregate provider diagnostics."""


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = _load_json(path)
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return [dict(row) for row in payload["rows"]]
    raise D2T11AcquisitionError(f"expected row evidence payload: {path}")


def _load_json_or_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise D2T11AcquisitionError(f"candidate input does not exist: {path}")
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = _load_json(path)
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return [dict(row) for row in payload["rows"]]
    raise D2T11AcquisitionError(f"expected candidate row payload: {path}")


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _guard_read_path(path: Path | None, label: str) -> None:
    if path is None:
        return
    normalized = _norm(path)
    if any(token in normalized for token in FORBIDDEN_TOKENS):
        raise D2T11AcquisitionError(f"{label} path is forbidden: {path}")


def _guard_output_dir(path: Path) -> None:
    normalized = _norm(path)
    if any(
        token in normalized for token in (*FORBIDDEN_TOKENS, *FORBIDDEN_OUTPUT_TOKENS)
    ):
        raise D2T11AcquisitionError(f"output-dir is forbidden: {path}")


def _parse_observed_at(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise D2T11AcquisitionError("source_observed_at must include timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def _remote_credentials(env_file: Path | None) -> dict[str, str]:
    values = _load_env_file(env_file)
    credentials = {
        key: os.environ.get(key) or values.get(key, "")
        for key in ["HITHINK_API_KEY", "TUSHARE_TOKEN"]
    }
    return credentials


def _require_remote_env(env_file: Path | None) -> dict[str, str]:
    credentials = _remote_credentials(env_file)
    missing = [key for key, value in credentials.items() if not value]
    if missing:
        raise D2T11AcquisitionError(
            "Missing required environment keys for --enable-remote-fetch: "
            + ", ".join(missing)
            + ". Use environment variables or --env-file .env.local."
        )
    return credentials


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


def _read_candidate_universe(
    raw_candidate_path: Path | None, adjusted_candidate_path: Path | None
) -> list[dict[str, Any]]:
    path = raw_candidate_path or adjusted_candidate_path
    if path is None:
        return []
    _guard_read_path(path, "candidate universe")
    if path.suffix.lower() == ".parquet":
        import pandas as pd
        import pyarrow.parquet as pq

        available = set(pq.ParquetFile(path).schema.names)
        missing = sorted(set(UNIVERSE_FIELDS) - available)
        if missing:
            raise D2T11AcquisitionError(
                f"candidate universe missing fields: {', '.join(missing)}"
            )
        frame = pd.read_parquet(path, columns=UNIVERSE_FIELDS)
        frame = frame.drop_duplicates(UNIVERSE_FIELDS)
        frame["trading_date"] = frame["trading_date"].map(_date_text)
        return [
            {field: row[field] for field in UNIVERSE_FIELDS}
            for row in frame.to_dict(orient="records")
        ]
    rows = _load_json_or_jsonl_rows(path)
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        missing = [field for field in UNIVERSE_FIELDS if field not in row]
        if missing:
            raise D2T11AcquisitionError(
                f"candidate universe missing fields: {', '.join(missing)}"
            )
        key = (
            str(row["security_id"]),
            _date_text(row["trading_date"]),
            str(row["universe_id"]),
            str(row["time_segment_id"]),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "security_id": key[0],
                "trading_date": key[1],
                "universe_id": key[2],
                "time_segment_id": key[3],
            }
        )
    return output


def _validate_contracts(
    contract: dict[str, Any], source_registry: dict[str, Any]
) -> None:
    if (
        contract.get("contract_id")
        != "D2_SOURCE_STATUS_FACTOR_EVIDENCE_ACCEPTANCE_HANDOFF_CONTRACT_V1"
    ):
        raise D2T11AcquisitionError("wrong D2-T11 contract")
    if source_registry.get("contract_id") != contract.get("source_registry_contract"):
        raise D2T11AcquisitionError("source registry contract mismatch")
    for key in [
        "formal_source_acceptance_authorized",
        "formal_ingestion_authorized",
        "duckdb_write_authorized",
        "real_data_materialization_authorized",
        "manifest_creation_authorized",
        "data_version_release_authorized",
        "d3_generation_authorized",
        "r0_state_generation_authorized",
    ]:
        if contract.get(key) is not False:
            raise D2T11AcquisitionError(f"{key} must remain false")
    if contract["active_source_policy"]["a_stock_data_active_allowed"] is not False:
        raise D2T11AcquisitionError("a-stock-data must not be active")


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["security_id"]), str(row["trading_date"])


def _is_missing(value: Any) -> bool:
    return value in (None, "", "unknown", "unresolved")


def _merge_evidence(
    rows: list[dict[str, Any]], fields: list[str], source_key: str
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    fallback_used = {"baostock": 0, "tushare": 0}
    for row in sorted(
        rows, key=lambda r: SOURCE_PRIORITY.get(str(r.get(source_key)), 99)
    ):
        source = str(row.get(source_key, ""))
        if source == "a-stock-data":
            raise D2T11AcquisitionError("a-stock-data is not an active source")
        key = _row_key(row)
        target = merged.setdefault(key, {field: None for field in fields})
        target.setdefault("security_id", key[0])
        target.setdefault("trading_date", key[1])
        for field in fields:
            incoming = row.get(field)
            if _is_missing(incoming):
                continue
            current = target.get(field)
            if _is_missing(current):
                target[field] = incoming
                target[f"{field}_source"] = source
                if source in fallback_used:
                    fallback_used[source] += 1
            elif current != incoming and target.get(f"{field}_source") != source:
                conflicts.append(
                    {
                        "security_id": key[0],
                        "trading_date": key[1],
                        "field": field,
                        "sources": [target.get(f"{field}_source"), source],
                    }
                )
    return merged, {"conflicts": conflicts, "fallback_used": fallback_used}


def _security_to_baostock_code(security_id: str) -> str | None:
    if security_id.startswith("XSHE."):
        return "sz." + security_id.split(".", 1)[1]
    if security_id.startswith("XSHG."):
        return "sh." + security_id.split(".", 1)[1]
    return None


def _security_to_tushare_code(security_id: str) -> str | None:
    if security_id.startswith("XSHE."):
        return security_id.split(".", 1)[1] + ".SZ"
    if security_id.startswith("XSHG."):
        return security_id.split(".", 1)[1] + ".SH"
    return None


class HiThinkProviderAdapter:
    provider_id = "hithink_financial_api"

    def probe(
        self, universe_rows: list[dict[str, Any]], credentials: dict[str, str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        del universe_rows, credentials
        return (
            [],
            [],
            {
                "provider_id": self.provider_id,
                "probe_status": "provider_probe_failed",
                "probe_failure_reason": "hithink_python_adapter_unavailable",
                "rows_requested": 0,
                "status_rows_returned": 0,
                "factor_rows_returned": 0,
            },
        )


class BaoStockProviderAdapter:
    provider_id = "baostock"

    def probe(
        self, universe_rows: list[dict[str, Any]], credentials: dict[str, str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        del credentials
        try:
            import baostock as bs
        except Exception as exc:
            return (
                [],
                [],
                self._failed(
                    universe_rows, f"baostock_import_failed:{type(exc).__name__}"
                ),
            )
        status_rows: list[dict[str, Any]] = []
        factor_rows: list[dict[str, Any]] = []
        login = None
        try:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                login = bs.login()
            if getattr(login, "error_code", "0") != "0":
                return [], [], self._failed(universe_rows, "baostock_login_failed")
            for item in universe_rows:
                code = _security_to_baostock_code(str(item["security_id"]))
                if not code:
                    continue
                date = str(item["trading_date"])
                fields = (
                    "date,code,open,high,low,close,preclose,volume,amount,"
                    "tradestatus,isST,adjustflag"
                )
                with (
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    result = bs.query_history_k_data_plus(
                        code,
                        fields,
                        start_date=date,
                        end_date=date,
                        frequency="d",
                        adjustflag="3",
                    )
                if getattr(result, "error_code", "0") != "0":
                    continue
                while result.next():
                    row = dict(zip(result.fields, result.get_row_data(), strict=False))
                    status_rows.append(self._status_row(item, row))
                    factor_rows.append(self._factor_row(item, row))
        except Exception as exc:
            return (
                status_rows,
                factor_rows,
                self._failed(
                    universe_rows, f"baostock_probe_failed:{type(exc).__name__}"
                ),
            )
        finally:
            if login is not None:
                try:
                    with (
                        contextlib.redirect_stdout(io.StringIO()),
                        contextlib.redirect_stderr(io.StringIO()),
                    ):
                        bs.logout()
                except Exception:
                    pass
        return (
            status_rows,
            factor_rows,
            {
                "provider_id": self.provider_id,
                "probe_status": "provider_probe_completed",
                "rows_requested": len(universe_rows),
                "status_rows_returned": len(status_rows),
                "factor_rows_returned": len(factor_rows),
            },
        )

    def _failed(
        self, universe_rows: list[dict[str, Any]], reason: str
    ) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "probe_status": "provider_probe_failed",
            "probe_failure_reason": reason,
            "rows_requested": len(universe_rows),
            "status_rows_returned": 0,
            "factor_rows_returned": 0,
        }

    def _status_row(self, item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        trade_status = str(row.get("tradestatus", ""))
        is_st = str(row.get("isST", ""))
        close_value = _to_float(row.get("close"))
        return {
            "security_id": item["security_id"],
            "trading_date": item["trading_date"],
            "universe_id": item["universe_id"],
            "time_segment_id": item["time_segment_id"],
            "status_source": self.provider_id,
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
            "is_trading_day": trade_status == "1",
            "trading_calendar_status": "open"
            if trade_status == "1"
            else "closed_or_suspended",
        }

    def _factor_row(self, item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        return {
            "security_id": item["security_id"],
            "trading_date": item["trading_date"],
            "universe_id": item["universe_id"],
            "time_segment_id": item["time_segment_id"],
            "factor_source": self.provider_id,
            "adjustment_factor": None,
            "factor_as_of_time": None,
            "adjustment_revision": None,
            "adjustment_factor_direction": "provider_schema_unresolved",
            "point_in_time_eligible": False,
        }


class TushareProviderAdapter:
    provider_id = "tushare"

    def probe(
        self, universe_rows: list[dict[str, Any]], credentials: dict[str, str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        token = credentials.get("TUSHARE_TOKEN", "")
        try:
            import tushare as ts
        except Exception as exc:
            return (
                [],
                [],
                self._failed(
                    universe_rows, f"tushare_import_failed:{type(exc).__name__}"
                ),
            )
        status_rows: list[dict[str, Any]] = []
        factor_rows: list[dict[str, Any]] = []
        try:
            pro = ts.pro_api(token)
            for item in universe_rows:
                ts_code = _security_to_tushare_code(str(item["security_id"]))
                if not ts_code:
                    continue
                date = str(item["trading_date"]).replace("-", "")
                limit_frame = pro.stk_limit(ts_code=ts_code, trade_date=date)
                if not limit_frame.empty:
                    limit = limit_frame.iloc[0].to_dict()
                    status_rows.append(self._status_row(item, limit))
                factor_frame = pro.adj_factor(ts_code=ts_code, trade_date=date)
                if not factor_frame.empty:
                    factor_rows.append(
                        self._factor_row(item, factor_frame.iloc[0].to_dict())
                    )
        except Exception as exc:
            return (
                status_rows,
                factor_rows,
                self._failed(
                    universe_rows, f"tushare_probe_failed:{type(exc).__name__}"
                ),
            )
        return (
            status_rows,
            factor_rows,
            {
                "provider_id": self.provider_id,
                "probe_status": "provider_probe_completed",
                "rows_requested": len(universe_rows),
                "status_rows_returned": len(status_rows),
                "factor_rows_returned": len(factor_rows),
            },
        )

    def _failed(
        self, universe_rows: list[dict[str, Any]], reason: str
    ) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "probe_status": "provider_probe_failed",
            "probe_failure_reason": reason,
            "rows_requested": len(universe_rows),
            "status_rows_returned": 0,
            "factor_rows_returned": 0,
        }

    def _status_row(self, item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        return {
            "security_id": item["security_id"],
            "trading_date": item["trading_date"],
            "universe_id": item["universe_id"],
            "time_segment_id": item["time_segment_id"],
            "status_source": self.provider_id,
            "trading_status": "unknown",
            "price_limit_status": "unknown",
            "suspension_status": "unknown",
            "st_status": "unknown",
            "limit_up_price": _to_float(row.get("up_limit")),
            "limit_down_price": _to_float(row.get("down_limit")),
            "is_trading_day": None,
            "trading_calendar_status": "unknown",
        }

    def _factor_row(self, item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        return {
            "security_id": item["security_id"],
            "trading_date": item["trading_date"],
            "universe_id": item["universe_id"],
            "time_segment_id": item["time_segment_id"],
            "factor_source": self.provider_id,
            "adjustment_factor": _to_float(row.get("adj_factor")),
            "factor_as_of_time": None,
            "adjustment_revision": None,
            "adjustment_factor_direction": "provider_schema_unresolved",
            "point_in_time_eligible": False,
        }


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _provider_adapters() -> list[ProviderAdapter]:
    return [
        HiThinkProviderAdapter(),
        BaoStockProviderAdapter(),
        TushareProviderAdapter(),
    ]


def _remote_probe_rows(
    universe_rows: list[dict[str, Any]],
    credentials: dict[str, str],
    adapters: list[ProviderAdapter] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    status_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for adapter in adapters or _provider_adapters():
        provider_status, provider_factor, diagnostic = adapter.probe(
            universe_rows, credentials
        )
        status_rows.extend(provider_status)
        factor_rows.extend(provider_factor)
        diagnostics.append(diagnostic)
    return status_rows, factor_rows, diagnostics


def acquire_source_status_factor_evidence(
    *,
    contract: dict[str, Any],
    source_registry: dict[str, Any],
    status_evidence_rows: list[dict[str, Any]],
    factor_evidence_rows: list[dict[str, Any]],
    candidate_universe_rows: list[dict[str, Any]] | None = None,
    observed_at: str,
    output_dir: Path,
    enable_remote_fetch: bool = False,
    env_file: Path | None = None,
    provider_adapters: list[ProviderAdapter] | None = None,
    remote_max_rows: int | None = None,
) -> dict[str, Any]:
    _validate_contracts(contract, source_registry)
    provider_diagnostics: list[dict[str, Any]] = []
    candidate_universe_total_count = len(candidate_universe_rows or [])
    if enable_remote_fetch:
        credentials = _require_remote_env(env_file)
        if not candidate_universe_rows:
            raise D2T11AcquisitionError(
                "--enable-remote-fetch requires --d2-t09-raw-candidate or "
                "--d2-t10-adjusted-candidate candidate universe"
            )
        probe_universe_rows = candidate_universe_rows
        if remote_max_rows is not None:
            if remote_max_rows <= 0:
                raise D2T11AcquisitionError("--remote-max-rows must be positive")
            probe_universe_rows = candidate_universe_rows[-remote_max_rows:]
        remote_status, remote_factor, provider_diagnostics = _remote_probe_rows(
            probe_universe_rows, credentials, provider_adapters
        )
        candidate_universe_rows = probe_universe_rows
        status_evidence_rows = [*status_evidence_rows, *remote_status]
        factor_evidence_rows = [*factor_evidence_rows, *remote_factor]
    observed_at = _parse_observed_at(observed_at)
    _guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = "d2_t11_candidate_" + hashlib.sha256(observed_at.encode()).hexdigest()[:16]
    data_version = "D2_T11_SOURCE_FACTOR_CANDIDATE_" + run_id
    source_snapshot_id = (
        "d2_t11_local_snapshot_"
        + hashlib.sha256(
            json.dumps(
                [status_evidence_rows, factor_evidence_rows], sort_keys=True
            ).encode()
        ).hexdigest()[:16]
    )

    status_merged, status_meta = _merge_evidence(
        status_evidence_rows, STATUS_FIELDS, "status_source"
    )
    factor_merged, factor_meta = _merge_evidence(
        factor_evidence_rows, FACTOR_FIELDS, "factor_source"
    )
    universe_keys = {
        (str(row["security_id"]), str(row["trading_date"]))
        for row in candidate_universe_rows or []
    }
    universe_meta = {
        (str(row["security_id"]), str(row["trading_date"])): row
        for row in candidate_universe_rows or []
    }
    keys = sorted(set(status_merged) | set(factor_merged) | universe_keys)
    status_rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    for security_id, trading_date in keys:
        meta = universe_meta.get((security_id, trading_date), {})
        status = status_merged.get((security_id, trading_date), {})
        status_known = all(
            not _is_missing(status.get(field)) for field in STATUS_FIELDS
        )
        status_rows.append(
            {
                "data_version": data_version,
                "universe_id": meta.get("universe_id", "CSI800_STATIC_2026_07"),
                "time_segment_id": meta.get("time_segment_id", "RAW_10Y_TO_20260704"),
                "security_id": security_id,
                "trading_date": trading_date,
                **{field: status.get(field, "unknown") for field in STATUS_FIELDS},
                "status_source": status.get("trading_status_source", "unresolved"),
                "status_source_priority": SOURCE_PRIORITY.get(
                    str(status.get("trading_status_source")), 99
                ),
                "status_observed_at": observed_at if status_known else None,
                "status_revision": "candidate" if status_known else None,
                "status_resolution_status": "resolved"
                if status_known
                else "unresolved",
                "source_registry_id": "hithink_financial_api",
                "source_snapshot_id": source_snapshot_id,
                "observed_at": observed_at,
                "run_id": run_id,
            }
        )
        factor = factor_merged.get((security_id, trading_date), {})
        factor_asof = factor.get("factor_as_of_time")
        revision = factor.get("adjustment_revision")
        factor_known = not _is_missing(factor.get("adjustment_factor"))
        factor_resolved = (
            factor_known
            and not _is_missing(factor_asof)
            and not _is_missing(revision)
            and factor.get("point_in_time_eligible") is True
        )
        factor_rows.append(
            {
                "data_version": data_version,
                "universe_id": meta.get("universe_id", "CSI800_STATIC_2026_07"),
                "time_segment_id": meta.get("time_segment_id", "RAW_10Y_TO_20260704"),
                "security_id": security_id,
                "trading_date": trading_date,
                "adjustment_factor": factor.get("adjustment_factor"),
                "factor_as_of_time": factor_asof,
                "adjustment_revision": revision,
                "factor_source": factor.get("adjustment_factor_source", "unresolved"),
                "factor_source_priority": SOURCE_PRIORITY.get(
                    str(factor.get("adjustment_factor_source")), 99
                ),
                "factor_observed_at": observed_at if factor_known else None,
                "factor_revision_status": "candidate"
                if not _is_missing(revision)
                else "missing",
                "adjustment_factor_direction": factor.get(
                    "adjustment_factor_direction", "candidate_requires_review"
                ),
                "point_in_time_eligible": bool(
                    factor.get("point_in_time_eligible") is True and factor_resolved
                ),
                "factor_resolution_status": "resolved"
                if factor_resolved
                else "unresolved",
                "source_registry_id": "hithink_financial_api",
                "source_snapshot_id": source_snapshot_id,
                "observed_at": observed_at,
                "run_id": run_id,
            }
        )
    status_path = output_dir / "source_status_evidence_candidate.jsonl"
    factor_path = output_dir / "factor_evidence_candidate.jsonl"
    discrepancy_path = output_dir / "source_discrepancy_report.json"
    _write_jsonl(status_path, status_rows)
    _write_jsonl(factor_path, factor_rows)
    conflicts = [*status_meta["conflicts"], *factor_meta["conflicts"]]
    discrepancy = {
        "conflict_count": len(conflicts),
        "conflict_fields": sorted({item["field"] for item in conflicts}),
        "conflict_sources": sorted(
            {src for item in conflicts for src in item["sources"] if src}
        ),
        "conflict_resolution_policy": "record_conflict_no_silent_override",
        "silent_override_count": 0,
        "fallback_used_count": sum(status_meta["fallback_used"].values())
        + sum(factor_meta["fallback_used"].values()),
        "fallback_by_source": {
            key: status_meta["fallback_used"].get(key, 0)
            + factor_meta["fallback_used"].get(key, 0)
            for key in ["baostock", "tushare"]
        },
        "unresolved_conflict_count": len(conflicts),
        "provider_probe_diagnostics": provider_diagnostics,
        "provider_probe_failed_count": sum(
            item.get("probe_status") == "provider_probe_failed"
            for item in provider_diagnostics
        ),
        "blocking_flag": bool(conflicts)
        or any(
            item.get("probe_status") == "provider_probe_failed"
            for item in provider_diagnostics
        ),
        "blocking_reasons": (["source_conflict_requires_review"] if conflicts else [])
        + (
            ["provider_probe_failed"]
            if any(
                item.get("probe_status") == "provider_probe_failed"
                for item in provider_diagnostics
            )
            else []
        ),
    }
    _write_json(discrepancy_path, discrepancy)
    return {
        "source_status_evidence_candidate": str(status_path),
        "factor_evidence_candidate": str(factor_path),
        "source_discrepancy_report": str(discrepancy_path),
        "discrepancy_report": discrepancy,
        "candidate_universe_total_count": candidate_universe_total_count,
        "candidate_universe_row_count": len(candidate_universe_rows or []),
        "candidate_universe_security_count": len(
            {row["security_id"] for row in candidate_universe_rows or []}
        ),
        "provider_probe_diagnostics": provider_diagnostics,
        "duckdb_written": False,
        "data_version_published": False,
        "d3_artifact_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument("--source-registry", default=DEFAULT_SOURCE_REGISTRY, type=Path)
    parser.add_argument("--d2-t09-raw-candidate", type=Path)
    parser.add_argument("--d2-t10-adjusted-candidate", type=Path)
    parser.add_argument("--d2-t10-readiness-report", type=Path)
    parser.add_argument("--d2-t10-reconciliation-report", type=Path)
    parser.add_argument("--source-status-evidence", type=Path)
    parser.add_argument("--factor-evidence", type=Path)
    parser.add_argument("--source-observed-at", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--enable-remote-fetch", action="store_true")
    parser.add_argument("--remote-max-rows", type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    for label, path in [
        ("raw candidate", args.d2_t09_raw_candidate),
        ("adjusted candidate", args.d2_t10_adjusted_candidate),
        ("readiness report", args.d2_t10_readiness_report),
        ("reconciliation report", args.d2_t10_reconciliation_report),
        ("source status evidence", args.source_status_evidence),
        ("factor evidence", args.factor_evidence),
    ]:
        _guard_read_path(path, label)
    try:
        report = acquire_source_status_factor_evidence(
            contract=_load_json(args.contract),
            source_registry=_load_json(args.source_registry),
            status_evidence_rows=_load_rows(args.source_status_evidence),
            factor_evidence_rows=_load_rows(args.factor_evidence),
            candidate_universe_rows=_read_candidate_universe(
                args.d2_t09_raw_candidate, args.d2_t10_adjusted_candidate
            ),
            observed_at=args.source_observed_at,
            output_dir=args.output_dir,
            enable_remote_fetch=args.enable_remote_fetch,
            env_file=args.env_file,
            remote_max_rows=args.remote_max_rows,
        )
    except D2T11AcquisitionError as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
