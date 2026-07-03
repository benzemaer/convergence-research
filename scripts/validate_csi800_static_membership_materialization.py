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
DEFAULT_SECURITY_MAPPING_OUTPUT_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_contract.v1.json"
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
REQUIRED_FIELDS = (
    "source_symbol",
    "ticker",
    "exchange",
    "security_id_mapping_reference",
)
OLE_COMPOUND_FILE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


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


def load_field_aliases(path: Path) -> dict[str, Any]:
    aliases = load_json(path)
    for field in (
        "row_level_detail_included",
        "raw_bytes_committed",
        "member_rows_committed",
        "duckdb_written",
        "run_manifest_created",
        "dataset_manifest_created",
        "materialization_authorized",
        "member_rows_materialized",
    ):
        if aliases.get(field) is not False:
            raise ValueError(f"field alias contract must keep {field}=false")
    mapping_alias = aliases["canonical_field_aliases"]["security_id_mapping_reference"]
    if mapping_alias.get("source_columns"):
        raise ValueError(
            "security_id_mapping_reference cannot be sourced from CSINDEX evidence"
        )
    return aliases


def load_security_mapping_reference_contract(path: Path) -> dict[str, Any]:
    contract = load_json(path)
    for field in (
        "row_level_detail_included",
        "raw_bytes_committed",
        "member_rows_committed",
        "duckdb_written",
        "run_manifest_created",
        "dataset_manifest_created",
        "materialization_authorized",
        "member_rows_materialized",
    ):
        if contract.get(field) is not False:
            raise ValueError(
                f"security mapping reference contract must keep {field}=false"
            )
    source = contract["security_mapping_source"]
    if source.get("source_domain") != "D1_SECURITY_MASTER":
        raise ValueError("security_id mapping reference must come from D1")
    if source.get("mapping_key_fields") != ["ticker", "exchange"]:
        raise ValueError("security_id mapping reference requires ticker+exchange")
    shortcuts = contract["prohibited_mapping_shortcuts"]
    if any(shortcuts.values()):
        raise ValueError("security_id mapping shortcuts must remain disabled")
    return contract


def load_security_mapping_output_contract(path: Path) -> dict[str, Any]:
    contract = load_json(path)
    for field in (
        "output_artifact_allowed_in_this_pr",
        "output_rows_committed",
        "security_id_mapping_output_committed",
        "row_level_detail_included",
        "raw_bytes_committed",
        "member_rows_committed",
        "duckdb_written",
        "run_manifest_created",
        "dataset_manifest_created",
        "materialization_authorized",
        "member_rows_materialized",
    ):
        if contract.get(field) is not False:
            raise ValueError(
                f"security mapping output contract must keep {field}=false"
            )
    if contract.get("expected_row_count") != 800:
        raise ValueError("security mapping output contract must expect 800 rows")
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


def read_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("raw evidence is not decodable text")


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


def format_excel_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


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


def is_binary_xls(data: bytes) -> bool:
    return data.startswith(OLE_COMPOUND_FILE_MAGIC)


def parse_binary_xls_members(data: bytes) -> list[dict[str, str]]:
    try:
        import xlrd
    except ImportError as exc:
        raise ValueError(
            "binary Excel/OLE .xls parsing requires xlrd from requirements-dev.txt"
        ) from exc
    workbook = xlrd.open_workbook(file_contents=data)
    if workbook.nsheets < 1:
        raise ValueError("binary Excel/OLE .xls has no worksheets")
    sheet = workbook.sheet_by_index(0)
    rows: list[list[str]] = []
    for row_index in range(sheet.nrows):
        rows.append(
            [
                format_excel_cell(sheet.cell_value(row_index, column_index))
                for column_index in range(sheet.ncols)
            ]
        )
    return rows_to_dicts(rows)


def parse_members(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    if is_binary_xls(data):
        return parse_binary_xls_members(data)
    text = read_text(data)
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


def first_present_list(row: dict[str, str], names: list[str]) -> str:
    return first_present(row, tuple(names))


def normalize_column_name(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def observed_columns_hash(columns: list[str]) -> str:
    payload = json.dumps(columns, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def candidate_aliases_by_required_field(
    columns: list[str],
) -> dict[str, list[str]]:
    normalized = {column: normalize_column_name(column) for column in columns}
    candidates: dict[str, list[str]] = {field: [] for field in REQUIRED_FIELDS}
    for column, normalized_column in normalized.items():
        if normalized_column in {"sourcesymbol", "symbol"}:
            candidates["source_symbol"].append(column)
        if "成份券代码" in normalized_column or "成分券代码" in normalized_column:
            candidates["source_symbol"].append(column)
            candidates["ticker"].append(column)
        if "证券代码" in normalized_column or "constituentcode" in normalized_column:
            candidates["source_symbol"].append(column)
            candidates["ticker"].append(column)
        if normalized_column in {"ticker", "securitycode"}:
            candidates["ticker"].append(column)
        if normalized_column in {"exchange", "market"} or "交易所" in normalized_column:
            candidates["exchange"].append(column)
        if (
            "mappingreference" in normalized_column
            or "securityidmappingreference" in normalized_column
        ):
            candidates["security_id_mapping_reference"].append(column)
    return {
        field: sorted(set(field_candidates))
        for field, field_candidates in candidates.items()
    }


def field_diagnostics(members: list[dict[str, str]]) -> dict[str, object]:
    columns = list(members[0]) if members else []
    candidates = candidate_aliases_by_required_field(columns)
    matched = {
        "source_symbol": bool(candidates["source_symbol"]),
        "ticker": bool(candidates["ticker"]),
        "exchange": bool(candidates["exchange"]),
        "security_id_mapping_reference": bool(
            candidates["security_id_mapping_reference"]
        ),
    }
    return {
        "observed_column_count": len(columns),
        "observed_columns_hash": observed_columns_hash(columns),
        "normalized_observed_columns": columns,
        "member_count_observed": len(members),
        "required_field_match_summary": matched,
        "missing_required_fields": [
            field for field, is_matched in matched.items() if not is_matched
        ],
        "candidate_aliases_by_required_field": candidates,
        "row_level_detail_included": False,
        "raw_bytes_committed": False,
        "member_rows_committed": False,
    }


def normalize_ticker(value: str) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", value)
    return match.group(1) if match else ""


def normalize_member_ticker(raw_ticker: str, source_symbol: str) -> str:
    ticker = normalize_ticker(raw_ticker)
    if ticker:
        return ticker
    return normalize_ticker(source_symbol)


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


def normalize_members_with_field_aliases(
    members: list[dict[str, str]],
    field_aliases: dict[str, Any],
) -> list[dict[str, str]]:
    aliases = field_aliases["canonical_field_aliases"]
    source_columns = aliases["source_symbol"]["source_columns"]
    ticker_columns = aliases["ticker"]["source_columns"]
    exchange_alias = aliases["exchange"]
    exchange_columns = [
        exchange_alias["primary_source_column"],
        *exchange_alias.get("fallback_source_columns", []),
    ]
    normalized: list[dict[str, str]] = []
    for member in members:
        source_symbol = first_present_list(member, source_columns)
        ticker = normalize_member_ticker(
            first_present_list(member, ticker_columns),
            source_symbol,
        )
        exchange = derive_exchange(
            source_symbol,
            first_present_list(member, exchange_columns),
        )
        normalized.append(
            {
                "source_symbol": source_symbol,
                "ticker": ticker,
                "exchange": exchange,
            }
        )
    return normalized


def is_deferred_security_mapping_alias(field_aliases: dict[str, Any]) -> bool:
    mapping_alias = field_aliases["canonical_field_aliases"][
        "security_id_mapping_reference"
    ]
    return (
        mapping_alias.get("source_columns") == []
        and mapping_alias.get("cannot_be_sourced_from_csindex") is True
        and mapping_alias.get("deferred_to_d1_security_master_mapping") is True
        and mapping_alias.get("required_before_materialization") is True
    )


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
        ticker = normalize_member_ticker(raw_ticker, source_symbol)
        exchange = derive_exchange(
            source_symbol, first_present(member, EXCHANGE_FIELDS)
        )
        mapping_reference = first_present(member, MAPPING_REFERENCE_FIELDS)
        if not source_symbol:
            return ValidationResult(
                STATUS_FAILED, f"member {index} missing source_symbol"
            )
        if not ticker:
            return ValidationResult(STATUS_FAILED, f"member {index} invalid ticker")
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
    field_aliases_path: Path | None = None,
    security_mapping_reference_contract_path: Path | None = None,
) -> ValidationResult:
    contract = load_contract(contract_path)
    field_aliases = (
        load_field_aliases(field_aliases_path) if field_aliases_path else None
    )
    security_mapping_reference_contract = (
        load_security_mapping_reference_contract(
            security_mapping_reference_contract_path
        )
        if security_mapping_reference_contract_path
        else None
    )
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
    if field_aliases is not None:
        members = normalize_members_with_field_aliases(members, field_aliases)
        result = validate_members(members, int(inputs["expected_member_count"]))
        if (
            security_mapping_reference_contract is not None
            and result.status == STATUS_FAILED
            and "missing security_id_mapping_reference" in result.reason
            and is_deferred_security_mapping_alias(field_aliases)
        ):
            return ValidationResult(
                STATUS_FAILED,
                "source/ticker/exchange_aliases_resolved; "
                "security_mapping_reference_contract_present; "
                "security_id_mapping_output_pending; "
                "materialization_remains_blocked",
                len(members),
            )
        if (
            result.status == STATUS_FAILED
            and "missing security_id_mapping_reference" in result.reason
            and is_deferred_security_mapping_alias(field_aliases)
        ):
            return ValidationResult(
                STATUS_FAILED,
                "source/ticker/exchange_aliases_resolved; "
                "security_id_mapping_reference_pending; "
                "materialization_remains_blocked",
                len(members),
            )
        return result
    return validate_members(members, int(inputs["expected_member_count"]))


def diagnose_fields(contract_path: Path = DEFAULT_CONTRACT_PATH) -> dict[str, object]:
    contract = load_contract(contract_path)
    inputs = contract_inputs(contract)
    evidence_path = inputs["raw_evidence_path"]
    if not evidence_path.exists():
        raise ValueError(f"missing approved raw evidence at {evidence_path}")
    actual_sha256 = sha256_file(evidence_path)
    if actual_sha256 != inputs["raw_evidence_sha256"]:
        raise ValueError(
            "raw_evidence_sha256_mismatch "
            f"expected={inputs['raw_evidence_sha256']} actual={actual_sha256}"
        )
    members = parse_members(evidence_path)
    diagnostics = field_diagnostics(members)
    diagnostics.update(
        {
            "universe_id": inputs["universe_id"],
            "index_code": inputs["index_code"],
            "source_snapshot_id": inputs["source_snapshot_id"],
            "raw_evidence_path": contract["source_evidence"]["raw_evidence_path"],
            "raw_evidence_sha256_expected": inputs["raw_evidence_sha256"],
            "raw_evidence_sha256_actual": actual_sha256,
            "expected_member_count": inputs["expected_member_count"],
        }
    )
    return diagnostics


def check_security_mapping_output(
    output_contract_path: Path = DEFAULT_SECURITY_MAPPING_OUTPUT_CONTRACT_PATH,
) -> dict[str, object]:
    output_contract = load_security_mapping_output_contract(output_contract_path)
    return {
        "report_status": "blocked_missing_security_mapping_output",
        "reason": (
            "security mapping output contract exists, but no approved row-level "
            "security mapping output is available; no security_id was generated "
            "or inferred"
        ),
        "security_mapping_output_contract_id": output_contract["contract_id"],
        "expected_row_count": output_contract["expected_row_count"],
        "observed_row_count": 0,
        "mapped_row_count": 0,
        "unmapped_row_count": 0,
        "duplicate_membership_key_count": 0,
        "duplicate_security_id_count": 0,
        "invalid_security_id_format_count": 0,
        "invalid_mapping_method_count": 0,
        "invalid_mapping_status_count": 0,
        "row_level_detail_included": False,
        "output_rows_committed": False,
        "security_id_mapping_output_committed": False,
        "raw_bytes_committed": False,
        "member_rows_committed": False,
        "duckdb_written": False,
        "run_manifest_created": False,
        "dataset_manifest_created": False,
        "materialization_authorized": False,
        "member_rows_materialized": False,
        "downstream_decision": "materialization_remains_blocked",
    }


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
    parser.add_argument(
        "--diagnose-fields",
        action="store_true",
        help="Emit aggregate field diagnostics as JSON and do not validate rows.",
    )
    parser.add_argument(
        "--field-aliases",
        type=Path,
        default=None,
        help=(
            "Optional D1-T04 field alias contract used to normalize raw columns. "
            "This never fabricates security_id mapping references."
        ),
    )
    parser.add_argument(
        "--security-mapping-reference-contract",
        type=Path,
        default=None,
        help=(
            "Optional D1-T04 security mapping reference contract. "
            "This gates validation and never produces security_id mapping output."
        ),
    )
    parser.add_argument(
        "--check-security-mapping-output",
        action="store_true",
        help=(
            "Emit aggregate security mapping output readiness JSON. "
            "This never reads or writes row-level mapping output."
        ),
    )
    parser.add_argument(
        "--security-mapping-output-contract",
        type=Path,
        default=DEFAULT_SECURITY_MAPPING_OUTPUT_CONTRACT_PATH,
        help="Path to the D1-T04 security mapping output contract.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.diagnose_fields:
        try:
            diagnostics = diagnose_fields(contract_path=args.contract)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "diagnostics_status": "diagnostics_failed",
                        "reason": str(exc),
                        "row_level_detail_included": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(diagnostics, ensure_ascii=False, sort_keys=True))
        return 0
    if args.check_security_mapping_output:
        try:
            report = check_security_mapping_output(
                output_contract_path=args.security_mapping_output_contract
            )
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "report_status": "failed_contract_mismatch",
                        "reason": str(exc),
                        "row_level_detail_included": False,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    result = validate_materialization_inputs(
        contract_path=args.contract,
        allow_missing_evidence=args.allow_missing_evidence,
        field_aliases_path=args.field_aliases,
        security_mapping_reference_contract_path=(
            args.security_mapping_reference_contract
        ),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    if result.status == STATUS_PASSED:
        return 0
    if result.status == STATUS_BLOCKED and args.allow_missing_evidence:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
