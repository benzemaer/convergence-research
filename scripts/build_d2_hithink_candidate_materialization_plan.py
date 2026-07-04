"""Build a D2-T09 stage-2 candidate materialization and fallback repair plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATERIALIZATION_CONTRACT_PATH = (
    ROOT
    / "configs/d2/hithink_raw_market_prices_candidate_materialization_contract.v1.json"
)
DEFAULT_SOURCE_REGISTRY_PATH = (
    ROOT / "configs/d2/formal_source_registry_contract.v1.json"
)
DEFAULT_PROBE_CONTRACT_PATH = (
    ROOT / "configs/d2/hithink_raw_ohlcv_probe_contract.v1.json"
)
PROHIBITED_PROBE_REPORT_PATH_TOKENS = (
    "data/raw",
    "data/external",
    "marketdb",
    ".parquet",
    ".duckdb",
    ".day",
)
PROHIBITED_REPORT_FIELDS = {
    "raw_rows",
    "row_level_prices",
    "vendor_payload",
    "raw_vendor_payload",
    "qfq_rows",
    "hfq_rows",
    "future_return",
    "label",
    "pcvt_value",
    "backtest_signal",
    "portfolio_return",
}


class CandidateMaterializationPlanError(ValueError):
    """Raised when D2-T09 stage-2 gates do not allow plan construction."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _validate_probe_report_path(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    for token in PROHIBITED_PROBE_REPORT_PATH_TOKENS:
        if token in normalized:
            raise CandidateMaterializationPlanError(
                f"probe report path is forbidden for stage 2: {path}"
            )


def _scan_prohibited_report_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in PROHIBITED_REPORT_FIELDS:
                raise CandidateMaterializationPlanError(
                    f"probe report contains prohibited field {key!r} at {path}"
                )
            _scan_prohibited_report_fields(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _scan_prohibited_report_fields(nested, f"{path}[{index}]")


def _require_false(config: dict[str, Any], keys: list[str], label: str) -> None:
    for key in keys:
        if config.get(key) is not False:
            raise CandidateMaterializationPlanError(
                f"{label}.{key} must remain false in D2-T09 stage 2"
            )


def _validate_contracts(
    materialization_contract: dict[str, Any],
    source_registry: dict[str, Any],
    probe_contract: dict[str, Any],
) -> None:
    if (
        materialization_contract.get("contract_id")
        != "D2_HITHINK_RAW_MARKET_PRICES_CANDIDATE_MATERIALIZATION_CONTRACT_V1"
    ):
        raise CandidateMaterializationPlanError(
            "unexpected materialization contract_id"
        )
    if materialization_contract.get("task_id") != "D2-T09":
        raise CandidateMaterializationPlanError(
            "materialization contract task_id mismatch"
        )
    if materialization_contract.get("contract_status") != "accepted":
        raise CandidateMaterializationPlanError(
            "materialization contract is not accepted"
        )
    if materialization_contract.get("target_table") != "d1.raw_market_prices":
        raise CandidateMaterializationPlanError("materialization target_table mismatch")
    if materialization_contract.get("primary_source") != "hithink_financial_api":
        raise CandidateMaterializationPlanError("primary source must be HiThink")
    if source_registry.get("contract_id") != materialization_contract.get(
        "formal_source_registry_contract"
    ):
        raise CandidateMaterializationPlanError("source registry contract mismatch")
    if probe_contract.get("contract_id") != materialization_contract.get(
        "raw_ohlcv_probe_contract"
    ):
        raise CandidateMaterializationPlanError("probe contract mismatch")
    auth_keys = [
        "formal_source_acceptance_authorized",
        "formal_ingestion_authorized",
        "duckdb_write_authorized",
        "real_data_materialization_authorized",
        "manifest_creation_authorized",
        "data_version_release_authorized",
        "d3_generation_authorized",
        "r0_state_generation_authorized",
    ]
    _require_false(materialization_contract, auth_keys, "materialization_contract")
    _require_false(source_registry, auth_keys, "source_registry")
    _require_false(probe_contract, auth_keys, "probe_contract")

    hierarchy = source_registry["source_hierarchy"]
    active_sources = [hierarchy["primary_source"]["source_id"]]
    active_sources.extend(
        source["source_id"] for source in hierarchy["fallback_sources"]
    )
    if hierarchy["primary_source"]["source_id"] != "hithink_financial_api":
        raise CandidateMaterializationPlanError("HiThink must be primary source")
    if "a-stock-data" in active_sources:
        raise CandidateMaterializationPlanError("a-stock-data must not be active")


def _validate_probe_report(
    probe_report: dict[str, Any],
    materialization_contract: dict[str, Any],
) -> None:
    missing_sections = [
        section
        for section in materialization_contract["raw_probe_required_sections"]
        if section not in probe_report
    ]
    if missing_sections:
        joined = ", ".join(missing_sections)
        raise CandidateMaterializationPlanError(
            f"probe report missing required sections: {joined}"
        )
    diagnostics = probe_report["probe_diagnostics"]
    required_false_diagnostics = {
        "default_scan_data_raw": "probe report must not scan data/raw by default",
        "data_version_published": "probe report must not publish data_version",
        "raw_rows_emitted": "probe report must not emit raw rows",
        "duckdb_written": "probe report must not write DuckDB",
        "manifest_created": "probe report must not create manifests",
    }
    for key, message in required_false_diagnostics.items():
        if diagnostics.get(key) is not False:
            raise CandidateMaterializationPlanError(message)
    _scan_prohibited_report_fields(probe_report)


def _price_field_mapping(probe_report: dict[str, Any]) -> dict[str, str]:
    resolved = probe_report["raw_k_schema_report"]["resolved_fields"]
    return {
        field: resolved[field]
        for field in [
            "trading_date",
            "raw_open",
            "raw_high",
            "raw_low",
            "raw_close",
            "volume",
            "amount",
        ]
        if field in resolved
    }


def _target_field_status(
    materialization_contract: dict[str, Any],
    price_mapping: dict[str, str],
) -> list[dict[str, Any]]:
    unresolved_reasons = {
        "data_version": "requires_reviewed_dataset_manifest",
        "universe_id": "requires_d1_membership_alignment_scope",
        "time_segment_id": "requires_declared_time_segment",
        "security_id": "requires_d1_security_mapping",
        "trading_status": "requires_status_mapping_review",
        "price_limit_status": "requires_price_limit_status_review",
        "source_registry_id": "requires_formal_source_acceptance",
        "source_snapshot_id": "requires_reviewed_source_snapshot_manifest",
        "observed_at": "requires_source_or_snapshot_observation_time_review",
        "run_id": "requires_reviewed_run_manifest",
    }
    rows: list[dict[str, Any]] = []
    for field in materialization_contract["required_target_fields"]:
        if field in price_mapping:
            rows.append(
                {
                    "target_field": field,
                    "status": "mapped_from_primary_candidate",
                    "source_column": price_mapping[field],
                }
            )
        elif field == "source_registry_id":
            rows.append(
                {
                    "target_field": field,
                    "status": "blocked",
                    "source_column": None,
                    "blocking_reason": unresolved_reasons[field],
                    "candidate_value": "hithink_financial_api",
                }
            )
        else:
            rows.append(
                {
                    "target_field": field,
                    "status": "blocked",
                    "source_column": None,
                    "blocking_reason": unresolved_reasons.get(
                        field, "requires_stage_2_review"
                    ),
                }
            )
    return rows


def _missing_semantic_fields_by_section(
    probe_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    missing_fields = list(
        probe_report["missing_field_report"].get("missing_fields", [])
    )
    raw_missing = [item for item in missing_fields if item.get("section") == "raw_k"]
    adjustment_missing = [
        item for item in missing_fields if item.get("section") == "adjustment_events"
    ]
    return raw_missing, adjustment_missing


def build_candidate_materialization_plan(
    probe_report: dict[str, Any],
    materialization_contract: dict[str, Any],
    source_registry: dict[str, Any],
    probe_contract: dict[str, Any],
) -> dict[str, Any]:
    _validate_contracts(materialization_contract, source_registry, probe_contract)
    _validate_probe_report(probe_report, materialization_contract)

    price_mapping = _price_field_mapping(probe_report)
    raw_missing_fields, adjustment_missing_fields = _missing_semantic_fields_by_section(
        probe_report
    )
    fallback_sources = materialization_contract["fallback_repair_policy"][
        "fallback_sources"
    ]
    active_blockers = list(materialization_contract["blocking_conditions"])
    if raw_missing_fields:
        active_blockers.append("primary_candidate_missing_required_semantic_fields")
    if adjustment_missing_fields:
        active_blockers.append("adjustment_event_readiness_deferred_to_d2_t10")

    raw_schema_status = probe_report["raw_k_schema_report"]["status"]
    coverage = probe_report["coverage_report"]
    field_status = _target_field_status(materialization_contract, price_mapping)
    blocked_target_fields = [
        item for item in field_status if item["status"] == "blocked"
    ]
    return {
        "contract_readiness_report": {
            "status": "blocked",
            "contract_id": materialization_contract["contract_id"],
            "contract_status": materialization_contract["contract_status"],
            "target_table": materialization_contract["target_table"],
            "primary_candidate_source": materialization_contract["primary_source"],
            "raw_schema_status": raw_schema_status,
            "coverage_row_count": coverage["row_count"],
            "formal_authorization_granted": False,
            "real_data_materialization_authorized": False,
        },
        "source_boundary_report": {
            "status": "passed",
            "primary_source": source_registry["source_hierarchy"]["primary_source"],
            "fallback_sources": fallback_sources,
            "a_stock_data_active": False,
        },
        "raw_field_mapping_report": {
            "status": "passed" if raw_schema_status == "passed" else "warning",
            "primary_source": materialization_contract["primary_source"],
            "resolved_price_fields": price_mapping,
            "missing_semantic_fields": raw_missing_fields,
            "raw_rows_emitted": False,
        },
        "adjustment_event_readiness_report": {
            "status": "deferred_to_d2_t10"
            if adjustment_missing_fields
            else "not_applicable_for_raw_price_materialization",
            "missing_semantic_fields": adjustment_missing_fields,
            "deferred_to_d2_t10": True,
        },
        "target_field_readiness_report": {
            "status": "blocked" if blocked_target_fields else "passed",
            "required_target_fields": materialization_contract[
                "required_target_fields"
            ],
            "field_status": field_status,
        },
        "fallback_repair_probe_plan": {
            "status": "blocked_pending_review",
            "fallback_mode": materialization_contract["fallback_repair_policy"][
                "fallback_mode"
            ],
            "fallback_sources": fallback_sources,
            "missing_only_repair_only": True,
            "missing_semantic_fields_to_probe": raw_missing_fields,
            "conflict_policy": "discrepancy_report_required_no_silent_override",
            "fallback_rows_generated": False,
        },
        "blocking_report": {
            "status": "blocked",
            "active_blocking_conditions": active_blockers,
        },
        "candidate_plan_diagnostics": {
            "default_scan_data_raw": False,
            "external_api_called": False,
            "duckdb_written": False,
            "manifest_created": False,
            "data_version_published": False,
            "row_level_prices_emitted": False,
            "d3_artifact_generated": False,
            "r0_state_generated": False,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-report", required=True, type=Path)
    parser.add_argument(
        "--materialization-contract",
        default=DEFAULT_MATERIALIZATION_CONTRACT_PATH,
        type=Path,
    )
    parser.add_argument(
        "--source-registry",
        default=DEFAULT_SOURCE_REGISTRY_PATH,
        type=Path,
    )
    parser.add_argument(
        "--probe-contract",
        default=DEFAULT_PROBE_CONTRACT_PATH,
        type=Path,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _validate_probe_report_path(args.probe_report)
    report = build_candidate_materialization_plan(
        probe_report=_load_json(args.probe_report),
        materialization_contract=_load_json(args.materialization_contract),
        source_registry=_load_json(args.source_registry),
        probe_contract=_load_json(args.probe_contract),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
