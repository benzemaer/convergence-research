"""Aggregate-only CSI800 security mapping output validator."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

membership = importlib.import_module(
    "scripts.validate_csi800_static_membership_materialization"
)
DEFAULT_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)
DEFAULT_FIELD_ALIASES_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json"
)
DEFAULT_SECURITY_MAPPING_REFERENCE_CONTRACT_PATH = (
    ROOT
    / "configs/d1"
    / "csi800_static_2026_06_security_mapping_reference_contract.v1.json"
)
DEFAULT_SECURITY_MAPPING_OUTPUT_CONTRACT_PATH = (
    ROOT
    / "configs/d1"
    / "csi800_static_2026_06_security_mapping_output_contract.v1.json"
)
DEFAULT_SECURITY_MASTER_CONTRACT_PATH = (
    ROOT / "configs/d1/security_master_contract.v1.json"
)

MAPPING_METHOD = "ticker_exchange_effective_date_to_d1_security_master"
MAPPING_STATUS = "mapped"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON in {path}")
    return data


def security_id_regex(security_master_contract: dict[str, Any]) -> re.Pattern[str]:
    return re.compile(
        security_master_contract["identifier_policy"]["security_id_regex"]
    )


def security_id_format(security_master_contract: dict[str, Any]) -> str:
    value = security_master_contract["identifier_policy"]["security_id_format"]
    if value != "CN.{exchange}.{ticker}":
        raise ValueError(
            "unsupported security_id format in D1 security master contract"
        )
    return value


def mapped_rows_from_members(
    members: list[dict[str, str]],
    membership_contract: dict[str, Any],
    security_master_contract: dict[str, Any],
) -> list[dict[str, str]]:
    security_id_template = security_id_format(security_master_contract)
    effective_date = membership_contract["universe"]["membership_effective_date"]
    source_snapshot_id = membership_contract["source_evidence"]["source_snapshot_id"]
    universe_id = membership_contract["universe"]["universe_id"]
    mapped_rows: list[dict[str, str]] = []
    for member in members:
        ticker = member.get("ticker", "")
        exchange = member.get("exchange", "")
        security_id = security_id_template.format(exchange=exchange, ticker=ticker)
        mapped_rows.append(
            {
                "universe_id": universe_id,
                "source_snapshot_id": source_snapshot_id,
                "membership_effective_date": effective_date,
                "source_symbol": member.get("source_symbol", ""),
                "ticker": ticker,
                "exchange": exchange,
                "security_id": security_id,
                "security_id_mapping_reference": (
                    "D1_SECURITY_MASTER_CONTRACT_V1:ticker_exchange_effective_date"
                ),
                "mapping_method": MAPPING_METHOD,
                "mapping_status": MAPPING_STATUS,
            }
        )
    return mapped_rows


def duplicate_count(values: list[tuple[str, ...]]) -> int:
    return sum(count - 1 for count in Counter(values).values() if count > 1)


def aggregate_mapped_rows(
    rows: list[dict[str, str]],
    output_contract: dict[str, Any],
    security_master_contract: dict[str, Any],
) -> dict[str, object]:
    expected_row_count = int(output_contract["expected_row_count"])
    valid_security_id = security_id_regex(security_master_contract)
    required_method = output_contract["required_mapping_method"]
    allowed_statuses = set(output_contract["allowed_mapping_status"])
    membership_keys = [
        (
            row.get("ticker", ""),
            row.get("exchange", ""),
            row.get("membership_effective_date", ""),
        )
        for row in rows
    ]
    security_ids = [row.get("security_id", "") for row in rows]
    aggregate = {
        "expected_row_count": expected_row_count,
        "observed_row_count": len(rows),
        "mapped_row_count": sum(
            1 for row in rows if row.get("mapping_status") == MAPPING_STATUS
        ),
        "unmapped_row_count": sum(
            1 for row in rows if row.get("mapping_status") != MAPPING_STATUS
        ),
        "duplicate_membership_key_count": duplicate_count(membership_keys),
        "duplicate_security_id_count": duplicate_count(
            [(value,) for value in security_ids]
        ),
        "invalid_security_id_format_count": sum(
            1 for value in security_ids if not valid_security_id.fullmatch(value)
        ),
        "invalid_mapping_method_count": sum(
            1 for row in rows if row.get("mapping_method") != required_method
        ),
        "invalid_mapping_status_count": sum(
            1 for row in rows if row.get("mapping_status") not in allowed_statuses
        ),
    }
    aggregate["report_status"] = report_status(aggregate)
    return aggregate


def report_status(aggregate: dict[str, object]) -> str:
    if aggregate["observed_row_count"] != aggregate["expected_row_count"]:
        return "failed_row_count"
    if aggregate["unmapped_row_count"]:
        return "failed_unmapped_rows"
    if aggregate["duplicate_membership_key_count"]:
        return "failed_duplicate_membership_key"
    if aggregate["duplicate_security_id_count"]:
        return "failed_duplicate_security_id"
    if aggregate["invalid_security_id_format_count"]:
        return "failed_security_id_format"
    if aggregate["invalid_mapping_method_count"]:
        return "failed_mapping_method"
    if aggregate["invalid_mapping_status_count"]:
        return "failed_mapping_status"
    return "passed"


def blocked_report(reason: str, output_contract: dict[str, Any]) -> dict[str, object]:
    return {
        "report_status": "blocked_missing_security_mapping_output",
        "expected_row_count": output_contract["expected_row_count"],
        "observed_row_count": 0,
        "mapped_row_count": 0,
        "unmapped_row_count": 0,
        "duplicate_membership_key_count": 0,
        "duplicate_security_id_count": 0,
        "invalid_security_id_format_count": 0,
        "invalid_mapping_method_count": 0,
        "invalid_mapping_status_count": 0,
        "downstream_decision": "materialization_remains_blocked",
        "validation_reason": reason,
    }


def finalize_report(
    aggregate: dict[str, object],
    output_contract: dict[str, Any],
) -> dict[str, object]:
    passed = aggregate["report_status"] == "passed"
    aggregate.update(
        {
            "downstream_decision": (
                "security_mapping_output_validated_but_membership_rows_not_materialized"
                if passed
                else "materialization_remains_blocked"
            ),
            "validation_reason": (
                "Approved raw evidence was parsed and mapped through the approved "
                "field alias and D1 security master mapping contracts; all 800 rows "
                "mapped successfully in aggregate, but no row-level security mapping "
                "output or membership rows are committed."
                if passed
                else "Controlled security mapping aggregate validation did not pass; "
                "materialization remains blocked and no row-level output is committed."
            ),
            "security_mapping_output_contract_id": output_contract["contract_id"],
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
        }
    )
    return aggregate


def build_aggregate_report(
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    field_aliases_path: Path = DEFAULT_FIELD_ALIASES_PATH,
    security_mapping_reference_contract_path: Path = (
        DEFAULT_SECURITY_MAPPING_REFERENCE_CONTRACT_PATH
    ),
    security_mapping_output_contract_path: Path = (
        DEFAULT_SECURITY_MAPPING_OUTPUT_CONTRACT_PATH
    ),
    security_master_contract_path: Path = DEFAULT_SECURITY_MASTER_CONTRACT_PATH,
) -> dict[str, object]:
    membership_contract = membership.load_contract(contract_path)
    field_aliases = membership.load_field_aliases(field_aliases_path)
    membership.load_security_mapping_reference_contract(
        security_mapping_reference_contract_path
    )
    output_contract = membership.load_security_mapping_output_contract(
        security_mapping_output_contract_path
    )
    security_master_contract = load_json(security_master_contract_path)
    inputs = membership.contract_inputs(membership_contract)
    evidence_path = inputs["raw_evidence_path"]
    if not evidence_path.exists():
        return blocked_report(
            "approved raw evidence is unavailable in the current runtime; "
            "no security_id was generated or inferred; materialization remains blocked",
            output_contract,
        )
    actual_sha256 = membership.sha256_file(evidence_path)
    if actual_sha256 != inputs["raw_evidence_sha256"]:
        raise ValueError("raw_evidence_sha256_mismatch")
    raw_members = membership.parse_members(evidence_path)
    normalized_members = membership.normalize_members_with_field_aliases(
        raw_members,
        field_aliases,
    )
    rows = mapped_rows_from_members(
        normalized_members,
        membership_contract,
        security_master_contract,
    )
    aggregate = aggregate_mapped_rows(rows, output_contract, security_master_contract)
    return finalize_report(aggregate, output_contract)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an aggregate-only CSI800 security mapping report. "
            "This script never writes row-level output, DuckDB, or manifests."
        )
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument(
        "--field-aliases",
        type=Path,
        default=DEFAULT_FIELD_ALIASES_PATH,
    )
    parser.add_argument(
        "--security-mapping-reference-contract",
        type=Path,
        default=DEFAULT_SECURITY_MAPPING_REFERENCE_CONTRACT_PATH,
    )
    parser.add_argument(
        "--security-mapping-output-contract",
        type=Path,
        default=DEFAULT_SECURITY_MAPPING_OUTPUT_CONTRACT_PATH,
    )
    parser.add_argument(
        "--security-master-contract",
        type=Path,
        default=DEFAULT_SECURITY_MASTER_CONTRACT_PATH,
    )
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Documented safety flag; output is aggregate-only regardless.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_aggregate_report(
        contract_path=args.contract,
        field_aliases_path=args.field_aliases,
        security_mapping_reference_contract_path=(
            args.security_mapping_reference_contract
        ),
        security_mapping_output_contract_path=args.security_mapping_output_contract,
        security_master_contract_path=args.security_master_contract,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    success_statuses = {"passed", "blocked_missing_security_mapping_output"}
    return 0 if report["report_status"] in success_statuses else 1


if __name__ == "__main__":
    raise SystemExit(main())
