"""Resolve internal security ids to provider-specific A-share codes."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderCodeMapping:
    security_id: str
    exchange: str | None
    local_symbol: str | None
    hithink_thscode: str | None
    baostock_code: str | None
    tushare_ts_code: str | None
    tnskhdata_ts_code: str | None
    mapping_status: str
    mapping_blocking_reasons: list[str]


_TS_CODE = re.compile(r"^(?P<symbol>\d{6})\.(?P<suffix>SZ|SH)$", re.IGNORECASE)
_BAOSTOCK = re.compile(r"^(?P<prefix>sz|sh)\.(?P<symbol>\d{6})$", re.IGNORECASE)
_PREFIXED = re.compile(
    r"^(?:(?:CN)\.)?(?P<exchange>XSHE|XSHG|SZSE|SHSE|SSE)\.(?P<symbol>\d{6})$",
    re.IGNORECASE,
)


def _exchange_from_suffix(suffix: str) -> str | None:
    normalized = suffix.upper()
    if normalized == "SZ":
        return "SZSE"
    if normalized == "SH":
        return "SSE"
    return None


def _exchange_from_prefix(prefix: str) -> str | None:
    normalized = prefix.upper()
    if normalized in {"XSHE", "SZSE"}:
        return "SZSE"
    if normalized in {"XSHG", "SHSE", "SSE"}:
        return "SSE"
    return None


def _provider_codes(symbol: str, exchange: str) -> tuple[str, str]:
    if exchange == "SZSE":
        return f"{symbol}.SZ", f"sz.{symbol}"
    if exchange == "SSE":
        return f"{symbol}.SH", f"sh.{symbol}"
    raise ValueError(f"unsupported exchange: {exchange}")


def resolve_security_provider_codes(security_id: str) -> ProviderCodeMapping:
    """Map common A-share code formats to HiThink/Tushare/tnskhdata/BAOSTOCK."""

    raw = str(security_id).strip()
    symbol: str | None = None
    exchange: str | None = None
    match = _TS_CODE.match(raw)
    if match:
        symbol = match.group("symbol")
        exchange = _exchange_from_suffix(match.group("suffix"))
    if symbol is None:
        match = _BAOSTOCK.match(raw)
        if match:
            symbol = match.group("symbol")
            exchange = _exchange_from_suffix(match.group("prefix"))
    if symbol is None:
        match = _PREFIXED.match(raw)
        if match:
            symbol = match.group("symbol")
            exchange = _exchange_from_prefix(match.group("exchange"))

    if symbol is None or exchange is None:
        return ProviderCodeMapping(
            security_id=raw,
            exchange=None,
            local_symbol=None,
            hithink_thscode=None,
            baostock_code=None,
            tushare_ts_code=None,
            tnskhdata_ts_code=None,
            mapping_status="unresolved",
            mapping_blocking_reasons=["unsupported_security_id_format"],
        )

    ts_code, baostock_code = _provider_codes(symbol, exchange)
    return ProviderCodeMapping(
        security_id=raw,
        exchange=exchange,
        local_symbol=symbol,
        hithink_thscode=ts_code,
        baostock_code=baostock_code,
        tushare_ts_code=ts_code,
        tnskhdata_ts_code=ts_code,
        mapping_status="resolved",
        mapping_blocking_reasons=[],
    )


def mapping_to_dict(mapping: ProviderCodeMapping) -> dict[str, Any]:
    return asdict(mapping)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("security_id")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    print(
        json.dumps(
            mapping_to_dict(resolve_security_provider_codes(args.security_id)),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
