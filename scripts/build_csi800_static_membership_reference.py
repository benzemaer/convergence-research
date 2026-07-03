"""Build the standardized CSI800 static membership reference artifact."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

mapper = importlib.import_module("scripts.build_csi800_security_mapping_output")
membership = importlib.import_module(
    "scripts.validate_csi800_static_membership_materialization"
)

DEFAULT_REFERENCE_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_reference.v1.json"
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
DEFAULT_SECURITY_MAPPING_OUTPUT_REPORT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_report.v1.json"
)
DEFAULT_SECURITY_MASTER_CONTRACT_PATH = (
    ROOT / "configs/d1/security_master_contract.v1.json"
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON in {path}")
    return data


def contract_inputs_are_aligned(
    membership_contract: dict[str, Any],
    field_aliases: dict[str, Any],
    security_mapping_reference_contract: dict[str, Any],
    security_mapping_output_contract: dict[str, Any],
    security_mapping_output_report: dict[str, Any],
) -> None:
    universe = membership_contract["universe"]
    evidence = membership_contract["source_evidence"]
    expected = {
        "universe_id": universe["universe_id"],
        "index_code": universe["index_code"],
        "source_snapshot_id": evidence["source_snapshot_id"],
        "raw_evidence_sha256_expected": evidence["raw_evidence_sha256"],
    }
    contracts = (
        field_aliases,
        security_mapping_reference_contract,
        security_mapping_output_contract,
        security_mapping_output_report,
    )
    for contract in contracts:
        for key, value in expected.items():
            if contract[key] != value:
                raise ValueError(f"contract chain mismatch for {key}")
    if (
        security_mapping_reference_contract["field_alias_contract_id"]
        != field_aliases["contract_id"]
    ):
        raise ValueError("field alias contract id mismatch")
    if (
        security_mapping_output_contract["field_alias_contract_id"]
        != field_aliases["contract_id"]
    ):
        raise ValueError("output contract field alias id mismatch")
    if (
        security_mapping_output_contract["security_mapping_reference_contract_id"]
        != security_mapping_reference_contract["contract_id"]
    ):
        raise ValueError("security mapping reference contract id mismatch")
    if (
        security_mapping_output_report["field_alias_contract_id"]
        != field_aliases["contract_id"]
    ):
        raise ValueError("output report field alias id mismatch")
    if (
        security_mapping_output_report["security_mapping_reference_contract_id"]
        != security_mapping_reference_contract["contract_id"]
    ):
        raise ValueError("output report security mapping reference id mismatch")
    if (
        security_mapping_output_report["security_mapping_output_contract_id"]
        != security_mapping_output_contract["contract_id"]
    ):
        raise ValueError("output report contract id mismatch")
    if security_mapping_output_report["report_status"] != "passed":
        raise ValueError("security mapping output report is not passed")


def load_and_map_members(
    membership_contract: dict[str, Any],
    field_aliases: dict[str, Any],
    security_master_contract: dict[str, Any],
    security_mapping_output_contract: dict[str, Any],
) -> list[dict[str, str]]:
    inputs = membership.contract_inputs(membership_contract)
    evidence_path = inputs["raw_evidence_path"]
    if not evidence_path.exists():
        raise FileNotFoundError(f"approved raw evidence not found: {evidence_path}")
    actual_sha256 = membership.sha256_file(evidence_path)
    if actual_sha256 != inputs["raw_evidence_sha256"]:
        raise ValueError("raw_evidence_sha256_mismatch")
    raw_members = membership.parse_members(evidence_path)
    normalized_members = membership.normalize_members_with_field_aliases(
        raw_members,
        field_aliases,
    )
    expected_count = membership_contract["universe"]["expected_member_count"]
    if len(normalized_members) != expected_count:
        raise ValueError(
            "member_count_mismatch "
            f"expected={expected_count} actual={len(normalized_members)}"
        )
    for index, member in enumerate(normalized_members, start=1):
        if not member.get("source_symbol"):
            raise ValueError(f"member {index} missing source_symbol")
        if not member.get("ticker"):
            raise ValueError(f"member {index} missing ticker")
        if not member.get("exchange"):
            raise ValueError(f"member {index} missing exchange")
    rows = mapper.mapped_rows_from_members(
        normalized_members,
        membership_contract,
        security_master_contract,
    )
    aggregate = mapper.aggregate_mapped_rows(
        rows,
        security_mapping_output_contract,
        security_master_contract,
    )
    if aggregate["report_status"] != "passed":
        raise ValueError(f"mapped row aggregate did not pass: {aggregate}")
    return rows


def build_membership_reference(
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    field_aliases_path: Path = DEFAULT_FIELD_ALIASES_PATH,
    security_mapping_reference_contract_path: Path = (
        DEFAULT_SECURITY_MAPPING_REFERENCE_CONTRACT_PATH
    ),
    security_mapping_output_contract_path: Path = (
        DEFAULT_SECURITY_MAPPING_OUTPUT_CONTRACT_PATH
    ),
    security_mapping_output_report_path: Path = (
        DEFAULT_SECURITY_MAPPING_OUTPUT_REPORT_PATH
    ),
    security_master_contract_path: Path = DEFAULT_SECURITY_MASTER_CONTRACT_PATH,
) -> dict[str, Any]:
    membership_contract = membership.load_contract(contract_path)
    field_aliases = membership.load_field_aliases(field_aliases_path)
    security_mapping_reference_contract = (
        membership.load_security_mapping_reference_contract(
            security_mapping_reference_contract_path
        )
    )
    security_mapping_output_contract = membership.load_security_mapping_output_contract(
        security_mapping_output_contract_path
    )
    security_mapping_output_report = load_json(security_mapping_output_report_path)
    security_master_contract = load_json(security_master_contract_path)
    contract_inputs_are_aligned(
        membership_contract,
        field_aliases,
        security_mapping_reference_contract,
        security_mapping_output_contract,
        security_mapping_output_report,
    )
    rows = load_and_map_members(
        membership_contract,
        field_aliases,
        security_master_contract,
        security_mapping_output_contract,
    )
    universe = membership_contract["universe"]
    evidence = membership_contract["source_evidence"]
    members = []
    for ordinal, row in enumerate(rows, start=1):
        members.append(
            {
                "member_ordinal": ordinal,
                "universe_id": universe["universe_id"],
                "membership_effective_date": universe["membership_effective_date"],
                "source_registry_id": evidence["source_registry_id"],
                "source_snapshot_id": evidence["source_snapshot_id"],
                "source_symbol": row["source_symbol"],
                "ticker": row["ticker"],
                "exchange": row["exchange"],
                "security_id": row["security_id"],
                "security_id_mapping_reference": row["security_id_mapping_reference"],
                "mapping_method": row["mapping_method"],
                "mapping_status": row["mapping_status"],
                "membership_status": "active_static_member",
            }
        )
    return {
        "$schema": "../../schemas/d1_csi800_static_membership_reference.schema.json",
        "artifact_id": "D1_T04_CSI800_STATIC_2026_06_MEMBERSHIP_REFERENCE_V1",
        "artifact_version": "1.0.0",
        "task_id": "D1-T04",
        "universe_id": universe["universe_id"],
        "index_code": universe["index_code"],
        "index_alias": universe["index_alias"],
        "membership_mode": universe["membership_mode"],
        "membership_effective_date": universe["membership_effective_date"],
        "source_registry_id": evidence["source_registry_id"],
        "source_snapshot_id": evidence["source_snapshot_id"],
        "raw_evidence_sha256": evidence["raw_evidence_sha256"],
        "field_alias_contract_id": field_aliases["contract_id"],
        "security_mapping_reference_contract_id": (
            security_mapping_reference_contract["contract_id"]
        ),
        "security_mapping_output_contract_id": (
            security_mapping_output_contract["contract_id"]
        ),
        "security_mapping_output_report_id": (
            security_mapping_output_report["report_id"]
        ),
        "member_count": len(members),
        "row_level_membership_reference_committed": True,
        "raw_bytes_committed": False,
        "duckdb_written": False,
        "run_manifest_created": False,
        "dataset_manifest_created": False,
        "d2_usage_authorized": True,
        "d2_usage_boundary": (
            "D2 may read this membership reference only through the declared "
            "D1/D2 standard input path; D2 must not read raw G0 evidence or "
            "data/external directly."
        ),
        "members": members,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the standardized CSI800 static membership reference. "
            "This script reads approved local evidence, writes no DuckDB, "
            "and creates no run or dataset manifest."
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
        "--security-mapping-output-report",
        type=Path,
        default=DEFAULT_SECURITY_MAPPING_OUTPUT_REPORT_PATH,
    )
    parser.add_argument(
        "--security-master-contract",
        type=Path,
        default=DEFAULT_SECURITY_MASTER_CONTRACT_PATH,
    )
    parser.add_argument(
        "--write-reference",
        type=Path,
        help=(
            "Optional output path. The only allowed committed path is "
            "configs/d1/csi800_static_2026_06_membership_reference.v1.json."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reference = build_membership_reference(
        contract_path=args.contract,
        field_aliases_path=args.field_aliases,
        security_mapping_reference_contract_path=(
            args.security_mapping_reference_contract
        ),
        security_mapping_output_contract_path=args.security_mapping_output_contract,
        security_mapping_output_report_path=args.security_mapping_output_report,
        security_master_contract_path=args.security_master_contract,
    )
    payload = json.dumps(reference, ensure_ascii=False, indent=2)
    if args.write_reference:
        target = args.write_reference.resolve()
        if target != DEFAULT_REFERENCE_PATH.resolve():
            raise ValueError(
                "membership reference may only be written to "
                f"{DEFAULT_REFERENCE_PATH.relative_to(ROOT)}"
            )
        target.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
