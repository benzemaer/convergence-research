"""Build D2 CSI800 static membership alignment from the D1-T04 reference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_reference.v1.json"
)
DEFAULT_COMPLETION_REPORT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_completion_report.v1.json"
)
DEFAULT_CONTRACT_PATH = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment_contract.v1.json"
)
DEFAULT_D2_T01_CONTRACT_PATH = ROOT / "configs/d2/raw_ohlcv_source_contract.v1.json"
DEFAULT_ALIGNMENT_PATH = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
)
DEFAULT_REPORT_PATH = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment_report.v1.json"
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected object JSON in {path}")
    return payload


def dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def assert_inputs_ready(
    reference: dict[str, Any],
    completion_report: dict[str, Any],
    contract: dict[str, Any],
    d2_t01_contract: dict[str, Any],
) -> None:
    expected_d2_t01 = {
        "contract_id": "D2_RAW_OHLCV_SOURCE_CONTRACT_V1",
        "task_id": "D2-T01",
        "contract_status": "accepted",
        "target_table": "d1.raw_market_prices",
    }
    for key, expected in expected_d2_t01.items():
        if d2_t01_contract.get(key) != expected:
            raise ValueError(f"D2-T01 readiness contract {key} is not accepted")
    if reference["artifact_id"] != contract["membership_source"]:
        raise ValueError("membership reference id does not match contract")
    if not reference["d2_usage_authorized"]:
        raise ValueError("membership reference is not authorized for D2 use")
    if (
        completion_report["d2_readiness_decision"]
        != "ready_for_d2_membership_alignment"
    ):
        raise ValueError("D1-T04 completion report is not ready for D2 alignment")
    if (
        completion_report["membership_reference_artifact_id"]
        != reference["artifact_id"]
    ):
        raise ValueError("completion report reference id mismatch")
    if reference["member_count"] != 800:
        raise ValueError("membership reference member_count is not 800")
    if len(reference["members"]) != 800:
        raise ValueError("membership reference rows are not 800")


def build_alignment_rows(
    reference: dict[str, Any],
    contract: dict[str, Any],
) -> list[dict[str, str]]:
    rows = []
    for member in reference["members"]:
        rows.append(
            {
                "data_version": contract["data_version"],
                "universe_id": contract["universe_id"],
                "time_segment_id": contract["time_segment_id"],
                "security_id": member["security_id"],
                "index_code": contract["index_code"],
                "membership_effective_date": contract["membership_effective_date"],
                "membership_mode": contract["membership_mode"],
                "membership_source": contract["membership_source"],
                "source_registry_id": contract["source_registry_id"],
                "source_snapshot_id": contract["source_snapshot_id"],
                "run_id": contract["run_id"],
            }
        )
    return rows


def primary_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        row["data_version"],
        row["universe_id"],
        row["security_id"],
        row["index_code"],
        row["membership_effective_date"],
    )


def build_alignment(
    reference_path: Path = DEFAULT_REFERENCE_PATH,
    completion_report_path: Path = DEFAULT_COMPLETION_REPORT_PATH,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    d2_t01_contract_path: Path = DEFAULT_D2_T01_CONTRACT_PATH,
) -> dict[str, Any]:
    reference = load_json(reference_path)
    completion_report = load_json(completion_report_path)
    contract = load_json(contract_path)
    d2_t01_contract = load_json(d2_t01_contract_path)
    assert_inputs_ready(reference, completion_report, contract, d2_t01_contract)
    rows = build_alignment_rows(reference, contract)
    return {
        "$schema": "../../schemas/d2_csi800_static_membership_alignment.schema.json",
        "artifact_id": contract["data_version"],
        "artifact_version": "1.0.0",
        "task_id": contract["task_id"],
        "contract_id": contract["contract_id"],
        "data_version": contract["data_version"],
        "universe_id": contract["universe_id"],
        "time_segment_id": contract["time_segment_id"],
        "index_code": contract["index_code"],
        "membership_effective_date": contract["membership_effective_date"],
        "membership_mode": contract["membership_mode"],
        "membership_source": contract["membership_source"],
        "source_registry_id": contract["source_registry_id"],
        "source_snapshot_id": contract["source_snapshot_id"],
        "run_id": contract["run_id"],
        "member_count": len(rows),
        "historical_membership_claim_attempted": False,
        "raw_evidence_read": False,
        "data_external_read": False,
        "duckdb_written": False,
        "market_data_generated": False,
        "run_manifest_created": False,
        "dataset_manifest_created": False,
        "rows": rows,
    }


def build_report(alignment: dict[str, Any]) -> dict[str, Any]:
    rows = alignment["rows"]
    required_fields = set(rows[0]) if rows else set()
    duplicate_primary_key_count = len(rows) - len({primary_key(row) for row in rows})
    missing_required_field_count = sum(1 for row in rows if set(row) != required_fields)
    non_csindex_source_count = sum(
        1 for row in rows if row["source_registry_id"] != "CSINDEX_OFFICIAL"
    )
    return {
        "$schema": (
            "../../schemas/d2_csi800_static_membership_alignment_report.schema.json"
        ),
        "report_id": "D2_CSI800_STATIC_2026_06_MEMBERSHIP_ALIGNMENT_REPORT_V1",
        "report_version": "1.0.0",
        "task_id": "D2-T02",
        "alignment_status": "completed",
        "contract_id": alignment["contract_id"],
        "alignment_artifact_id": alignment["artifact_id"],
        "source_membership_reference_id": alignment["membership_source"],
        "member_count_expected": 800,
        "member_count_observed": len(rows),
        "unique_security_id_count": len({row["security_id"] for row in rows}),
        "duplicate_primary_key_count": duplicate_primary_key_count,
        "missing_required_field_count": missing_required_field_count,
        "non_csindex_source_count": non_csindex_source_count,
        "historical_membership_claim_attempted": False,
        "raw_evidence_read": False,
        "data_external_read": False,
        "duckdb_written": False,
        "market_data_generated": False,
        "run_manifest_created": False,
        "dataset_manifest_created": False,
        "next_task": "D2-T03",
    }


def compare_committed(
    expected: dict[str, Any],
    path: Path,
    label: str,
) -> None:
    actual = load_json(path)
    if actual != expected:
        raise ValueError(f"committed {label} differs from generated output")


def write_if_allowed(path: Path, expected_path: Path, payload: dict[str, Any]) -> None:
    target = path.resolve()
    if target != expected_path.resolve():
        raise ValueError(f"refusing to write outside {expected_path.relative_to(ROOT)}")
    target.write_text(dump_json(payload), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build D2 CSI800 static membership alignment from committed D1-T04 "
            "membership reference only."
        )
    )
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE_PATH)
    parser.add_argument(
        "--completion-report",
        type=Path,
        default=DEFAULT_COMPLETION_REPORT_PATH,
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument(
        "--d2-t01-contract",
        type=Path,
        default=DEFAULT_D2_T01_CONTRACT_PATH,
    )
    parser.add_argument("--write-alignment", type=Path)
    parser.add_argument("--write-report", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    alignment = build_alignment(
        reference_path=args.reference,
        completion_report_path=args.completion_report,
        contract_path=args.contract,
        d2_t01_contract_path=args.d2_t01_contract,
    )
    report = build_report(alignment)
    if args.check:
        compare_committed(alignment, DEFAULT_ALIGNMENT_PATH, "alignment")
        compare_committed(report, DEFAULT_REPORT_PATH, "report")
        print("D2 CSI800 membership alignment is up to date")
        return 0
    if args.write_alignment:
        write_if_allowed(args.write_alignment, DEFAULT_ALIGNMENT_PATH, alignment)
    if args.write_report:
        write_if_allowed(args.write_report, DEFAULT_REPORT_PATH, report)
    if not args.write_alignment and not args.write_report:
        json.dump(
            {"alignment": alignment, "report": report},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
