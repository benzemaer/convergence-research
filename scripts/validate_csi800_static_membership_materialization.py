"""Dry-run validator for CSI800 static membership materialization inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)

STATUS_PASSED = "passed"
STATUS_BLOCKED = "blocked_missing_evidence"
STATUS_FAILED = "failed"

SYMBOL_FIELDS = (
    "source_symbol",
    "symbol",
    "证券代码",
    "成分券代码",
    "成份券代码",
    "指数成分券代码",
    "constituent_code",
    "security_code",
)
TICKER_FIELDS = ("ticker", "证券代码", "成分券代码", "成份券代码", "security_code")
EXCHANGE_FIELDS = ("exchange", "交易所", "证券交易所", "market", "交易市场")
MAPPING_REFERENCE_FIELDS = (
    "security_id_mapping_reference",
    "mapping_reference",
    "security_master_mapping_reference",
)


@dataclass(frozen=True)
class ValidationResult:
    status: str
    reason: str
    member_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "member_count": self.member_count,
        }


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() == "tr":
            self._current_row = []
        elif tag.lower() in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None:
            assert self._current_row is not None
            self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON in {path}")
    return data


def load_contract(path: Path) -> dict[str, Any]:
    contract = load_json(path)
    if contract.get("materialization_authorized") is not False:
        raise ValueError("contract must keep materialization_authorized=false")
    if contract.get("member_rows_materialized") is not False:
        raise ValueError("contract must keep member_rows_materialized=false")
    return contract


def contract_inputs(contract: dict[str, Any]) -> dict[str, Any]:
    source = contract["source_evidence"]
    universe = contract["universe"]
    return {
        "raw_evidence_path": ROOT / source["raw_evidence_path"],
        "raw_evidence_sha256": source["raw_evidence_sha256"],
        "expected_member_count": universe["expected_member_count"],
        "universe_id": universe["universe_id"],
        "index_code": universe["index_code"],
        "membership_effective_date": universe["membership_effective_date"],
        "source_snapshot_id": source["source_snapshot_id"],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("raw evidence is not decodable text or HTML-table .xls")


def parse_json_members(text: str) -> list[dict[str, str]]:
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("members", "constituents", "data", "rows"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError("JSON evidence must be a list or contain a member list")
    members: list[dict[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("JSON member rows must be objects")
        members.append(
            {str(key).strip(): str(value).strip() for key, value in row.items()}
        )
    return members


def rows_to_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    header_index = 0
    for index, row in enumerate(rows[:5]):
        lowered = {cell.strip().lower() for cell in row}
        if lowered & {"source_symbol", "ticker", "exchange", "证券代码"}:
            header_index = index
            break
    headers = [cell.strip() for cell in rows[header_index]]
    members: list[dict[str, str]] = []
    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * max(0, len(headers) - len(row))
        members.append(
            {
                headers[index]: padded[index].strip()
                for index in range(len(headers))
                if headers[index]
            }
        )
    return members


def parse_delimited_members(text: str) -> list[dict[str, str]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    return [
        {str(key).strip(): str(value).strip() for key, value in row.items()}
        for row in rows
    ]


def parse_html_table_members(text: str) -> list[dict[str, str]]:
    parser = TableParser()
    parser.feed(text)
    return rows_to_dicts(parser.rows)


def parse_members(path: Path) -> list[dict[str, str]]:
    text = read_text(path)
    suffix = path.suffix.lower()
    stripped = text.lstrip()
    if suffix == ".json" or stripped.startswith(("{", "[")):
        return parse_json_members(text)
    if "<table" in stripped[:4096].lower():
        return parse_html_table_members(text)
    return parse_delimited_members(text)


def first_present(row: dict[str, str], names: tuple[str, ...]) -> str:
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        value = row.get(name)
        if value:
            return value.strip()
        value = lowered.get(name.lower())
        if value:
            return value.strip()
    return ""


def normalize_ticker(value: str) -> str:
    match = re.search(r"(\d{6})", value)
    return match.group(1) if match else value.strip()


def derive_exchange(source_symbol: str, explicit_exchange: str) -> str:
    exchange = explicit_exchange.strip().upper()
    if exchange in {"SH", "SSE", "XSHG", "上海证券交易所"}:
        return "SSE"
    if exchange in {"SZ", "SZSE", "XSHE", "深圳证券交易所"}:
        return "SZSE"
    symbol = source_symbol.strip().upper()
    if symbol.endswith((".SH", ".SSE", ".XSHG")):
        return "SSE"
    if symbol.endswith((".SZ", ".SZSE", ".XSHE")):
        return "SZSE"
    return ""


def validate_members(
    members: list[dict[str, str]],
    expected_member_count: int,
) -> ValidationResult:
    if len(members) != expected_member_count:
        return ValidationResult(
            STATUS_FAILED,
            "member_count_mismatch "
            f"expected={expected_member_count} actual={len(members)}",
            len(members),
        )
    for index, member in enumerate(members, start=1):
        source_symbol = first_present(member, SYMBOL_FIELDS)
        raw_ticker = first_present(member, TICKER_FIELDS)
        ticker = normalize_ticker(raw_ticker)
        exchange = derive_exchange(
            source_symbol, first_present(member, EXCHANGE_FIELDS)
        )
        mapping_reference = first_present(member, MAPPING_REFERENCE_FIELDS)
        if not source_symbol:
            return ValidationResult(
                STATUS_FAILED, f"member {index} missing source_symbol"
            )
        if not ticker:
            return ValidationResult(STATUS_FAILED, f"member {index} missing ticker")
        if not exchange:
            return ValidationResult(STATUS_FAILED, f"member {index} missing exchange")
        if not mapping_reference:
            return ValidationResult(
                STATUS_FAILED,
                f"member {index} missing security_id_mapping_reference",
            )
    return ValidationResult(
        STATUS_PASSED,
        "dry-run validation passed; security_id mapping remains required",
        len(members),
    )


def validate_materialization_inputs(
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    allow_missing_evidence: bool = False,
) -> ValidationResult:
    contract = load_contract(contract_path)
    inputs = contract_inputs(contract)
    evidence_path = inputs["raw_evidence_path"]
    if not evidence_path.exists():
        result = ValidationResult(
            STATUS_BLOCKED,
            f"missing approved raw evidence at {evidence_path}",
        )
        if allow_missing_evidence:
            return result
        return ValidationResult(STATUS_FAILED, result.reason)
    actual_sha256 = sha256_file(evidence_path)
    if actual_sha256 != inputs["raw_evidence_sha256"]:
        return ValidationResult(
            STATUS_FAILED,
            "raw_evidence_sha256_mismatch "
            f"expected={inputs['raw_evidence_sha256']} actual={actual_sha256}",
        )
    try:
        members = parse_members(evidence_path)
    except Exception as exc:
        return ValidationResult(STATUS_FAILED, f"parse_failed: {exc}")
    return validate_members(members, int(inputs["expected_member_count"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate local CSI800 static membership evidence in dry-run mode. "
            "This script never writes DuckDB, manifests, or member rows."
        )
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT_PATH,
        help="Path to the D1-T04 CSI800 membership contract.",
    )
    parser.add_argument(
        "--allow-missing-evidence",
        action="store_true",
        help="Return 0 with blocked status when local ignored raw evidence is absent.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_materialization_inputs(
        contract_path=args.contract,
        allow_missing_evidence=args.allow_missing_evidence,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    if result.status == STATUS_PASSED:
        return 0
    if result.status == STATUS_BLOCKED and args.allow_missing_evidence:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
