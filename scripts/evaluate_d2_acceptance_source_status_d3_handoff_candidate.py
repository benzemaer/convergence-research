"""Evaluate D2-T11 acceptance and D3 handoff candidate reports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "configs/d2/source_status_factor_evidence_acceptance_handoff_contract.v1.json"
)
FORBIDDEN_TOKENS = ("marketdb", ".duckdb", ".day", "data/raw", "data/external")


class D2T11EvaluationError(ValueError):
    """Raised when D2-T11 evaluator gates fail."""


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
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
    raise D2T11EvaluationError(f"expected row evidence payload: {path}")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _guard_path(path: Path, label: str, allow_docs: bool = False) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if allow_docs and normalized.startswith("docs/research/"):
        return
    if any(token in normalized for token in FORBIDDEN_TOKENS):
        raise D2T11EvaluationError(f"{label} path is forbidden: {path}")


def _guard_output_dir(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if any(token in normalized for token in FORBIDDEN_TOKENS):
        raise D2T11EvaluationError(f"output-dir is forbidden: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _known(rows: list[dict[str, Any]], field: str) -> int:
    return sum(row.get(field) not in (None, "", "unknown") for row in rows)


def _unknown(rows: list[dict[str, Any]], field: str) -> int:
    return len(rows) - _known(rows, field)


def _count_true(rows: list[dict[str, Any]], field: str) -> int:
    return sum(bool(row.get(field)) for row in rows)


def _base_stats(rows: list[dict[str, Any]]) -> tuple[int, str | None, str | None]:
    securities = {row.get("security_id") for row in rows}
    dates = sorted(
        str(row.get("trading_date")) for row in rows if row.get("trading_date")
    )
    return len(securities), dates[0] if dates else None, dates[-1] if dates else None


def evaluate_d2_acceptance_source_status_d3_handoff_candidate(
    *,
    contract: dict[str, Any],
    source_status_rows: list[dict[str, Any]],
    factor_rows: list[dict[str, Any]],
    discrepancy_report: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    expected = "D2_SOURCE_STATUS_FACTOR_EVIDENCE_ACCEPTANCE_HANDOFF_CONTRACT_V1"
    if contract.get("contract_id") != expected:
        raise D2T11EvaluationError("wrong D2-T11 contract")
    _guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_resolved = bool(source_status_rows) and all(
        row.get("status_resolution_status") == "resolved" for row in source_status_rows
    )
    factor_resolved = bool(factor_rows) and all(
        row.get("factor_resolution_status") == "resolved" for row in factor_rows
    )
    point_ready = bool(factor_rows) and all(
        row.get("point_in_time_eligible") is True for row in factor_rows
    )
    conflict_count = int(discrepancy_report.get("conflict_count", 0))
    blocking: list[str] = []
    if not source_resolved:
        blocking.append("source_status_unresolved")
    if not factor_resolved:
        blocking.append("factor_evidence_unresolved")
    if not point_ready:
        blocking.append("point_in_time_evidence_unresolved")
    if conflict_count:
        blocking.append("source_discrepancy_unresolved")
    allowed = not blocking
    decision = (
        "accepted_for_d3_candidate_generation"
        if allowed
        else "blocked_pending_source_status_resolution"
        if not source_resolved
        else "blocked_pending_adjustment_factor_resolution"
    )
    d3_decision = (
        "d3_candidate_generation_allowed"
        if allowed
        else "d3_candidate_generation_blocked"
    )
    all_rows = [*source_status_rows, *factor_rows]
    security_count, date_min, date_max = _base_stats(all_rows)

    source_report = {
        "trading_status_known_count": _known(source_status_rows, "trading_status"),
        "trading_status_unknown_count": _unknown(source_status_rows, "trading_status"),
        "price_limit_status_known_count": _known(
            source_status_rows, "price_limit_status"
        ),
        "price_limit_status_unknown_count": _unknown(
            source_status_rows, "price_limit_status"
        ),
        "suspension_status_known_count": _known(
            source_status_rows, "suspension_status"
        ),
        "suspension_status_unknown_count": _unknown(
            source_status_rows, "suspension_status"
        ),
        "st_status_known_count": _known(source_status_rows, "st_status"),
        "st_status_unknown_count": _unknown(source_status_rows, "st_status"),
        "limit_price_known_count": sum(
            row.get("limit_up_price") is not None
            and row.get("limit_down_price") is not None
            for row in source_status_rows
        ),
        "limit_price_unknown_count": sum(
            row.get("limit_up_price") is None or row.get("limit_down_price") is None
            for row in source_status_rows
        ),
        "resolved_by_source": {},
        "unresolved_by_field": {},
        "conflict_count": conflict_count,
        "fallback_sources_used": [],
        "fallback_sources_considered": ["baostock", "tushare"],
        "a_stock_data_active": False,
        "resolution_blocking_flag": not source_resolved,
        "resolution_blocking_reasons": []
        if source_resolved
        else ["source_status_unresolved"],
        "recommended_next_action": "D3-T07"
        if allowed
        else "D2-T12 source status remediation",
    }
    factor_report = {
        "adjustment_factor_known_count": _known(factor_rows, "adjustment_factor"),
        "adjustment_factor_missing_count": _unknown(factor_rows, "adjustment_factor"),
        "factor_as_of_time_known_count": _known(factor_rows, "factor_as_of_time"),
        "factor_as_of_time_missing_count": _unknown(factor_rows, "factor_as_of_time"),
        "adjustment_revision_known_count": _known(factor_rows, "adjustment_revision"),
        "adjustment_revision_missing_count": _unknown(
            factor_rows, "adjustment_revision"
        ),
        "point_in_time_eligible_count": _count_true(
            factor_rows, "point_in_time_eligible"
        ),
        "point_in_time_ineligible_count": len(factor_rows)
        - _count_true(factor_rows, "point_in_time_eligible"),
        "history_revision_class": "point_in_time_candidate"
        if factor_resolved
        else "final_revised_or_missing_evidence",
        "factor_direction_status": "candidate_requires_review",
        "factor_resolution_blocking_flag": not factor_resolved,
        "factor_resolution_blocking_reasons": []
        if factor_resolved
        else ["factor_evidence_unresolved"],
        "recommended_next_action": "D3-T07"
        if allowed
        else "D2-T12 factor evidence remediation",
    }
    acceptance = {
        "contract_id": contract["contract_id"],
        "task_id": contract["task_id"],
        "decision": decision,
        "decision_status": "allowed" if allowed else "blocked",
        "raw_candidate_row_count": len(source_status_rows),
        "adjusted_candidate_row_count": len(factor_rows),
        "security_count": security_count,
        "trading_date_min": date_min,
        "trading_date_max": date_max,
        "source_status_resolution_status": "resolved"
        if source_resolved
        else "unresolved",
        "factor_status_resolution_status": "resolved"
        if factor_resolved
        else "unresolved",
        "point_in_time_eligibility_status": "eligible" if point_ready else "ineligible",
        "quality_blocking_flag": bool(blocking),
        "quality_blocking_reasons": blocking,
        "acceptance_blocking_reasons": blocking,
        "d3_candidate_generation_allowed": allowed,
        "d3_generation_authorized": False,
        "r0_state_generation_authorized": False,
    }
    handoff = {
        "handoff_status": "candidate",
        "handoff_decision": d3_decision,
        "d3_candidate_generation_allowed": allowed,
        "d3_blocked_gate_report_only_allowed": not allowed,
        "upstream_d2_artifacts": ["D2-T09", "D2-T10", "D2-T11"],
        "artifact_hashes": {},
        "row_count_contract": len(source_status_rows),
        "security_count_contract": security_count,
        "date_range_contract": {"min": date_min, "max": date_max},
        "source_lineage_summary": "candidate source status and factor evidence only",
        "history_revision_class": factor_report["history_revision_class"],
        "point_in_time_eligibility_status": acceptance[
            "point_in_time_eligibility_status"
        ],
        "quality_readiness_status": "ready" if allowed else "blocked",
        "source_status_readiness_status": "ready" if source_resolved else "blocked",
        "factor_status_readiness_status": "ready" if factor_resolved else "blocked",
        "d3_required_inputs_present": ["source_status_evidence", "factor_evidence"]
        if allowed
        else [],
        "d3_required_inputs_missing": [] if allowed else blocking,
        "d3_blocking_reasons": [] if allowed else blocking,
        "next_allowed_task": "D3-T07"
        if allowed
        else "D2-T12 remediation or D3-T07 blocked gate report only",
    }
    gate = {
        "d2_acceptance_decision": decision,
        "source_status_decision": "resolved" if source_resolved else "unresolved",
        "factor_status_decision": "resolved" if factor_resolved else "unresolved",
        "quality_decision": "ready" if allowed else "blocked",
        "d3_handoff_decision": d3_decision,
        "r0_handoff_decision": "r0_blocked",
        "all_blocking_reasons": blocking,
        "allowed_next_actions": ["D3-T07 formal candidate generation gate execution"]
        if allowed
        else ["D2-T12 source status / factor evidence remediation"],
        "forbidden_next_actions": ["R0 generation", "backtest", "portfolio generation"],
    }
    payloads = {
        "source_status_resolution_candidate_report": source_report,
        "factor_status_resolution_candidate_report": factor_report,
        "d2_acceptance_candidate_report": acceptance,
        "d3_handoff_candidate_report": handoff,
        "d2_t11_gate_decision_summary": gate,
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = output_dir / f"{name}.json"
        _write_json(path, payload)
        paths[name] = path
    return {
        "d2_acceptance_decision": decision,
        "d3_handoff_decision": d3_decision,
        "r0_handoff_decision": "r0_blocked",
        "d3_candidate_generation_allowed": allowed,
        "d3_generation_authorized": False,
        "r0_state_generation_authorized": False,
        "reports": {key: str(path) for key, path in paths.items()},
        "report_hashes": {key: _sha256_file(path) for key, path in paths.items()},
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument("--d2-t09-redacted-summary", type=Path)
    parser.add_argument("--d2-t10-redacted-summary", type=Path)
    parser.add_argument("--source-status-evidence", required=True, type=Path)
    parser.add_argument("--factor-evidence", required=True, type=Path)
    parser.add_argument("--discrepancy-report", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    for label, path, allow_docs in [
        ("d2-t09-redacted-summary", args.d2_t09_redacted_summary, True),
        ("d2-t10-redacted-summary", args.d2_t10_redacted_summary, True),
        ("source-status-evidence", args.source_status_evidence, False),
        ("factor-evidence", args.factor_evidence, False),
        ("discrepancy-report", args.discrepancy_report, False),
    ]:
        if path:
            _guard_path(path, label, allow_docs=allow_docs)
    try:
        report = evaluate_d2_acceptance_source_status_d3_handoff_candidate(
            contract=_load_json(args.contract),
            source_status_rows=_load_rows(args.source_status_evidence),
            factor_rows=_load_rows(args.factor_evidence),
            discrepancy_report=_load_json(args.discrepancy_report),
            output_dir=args.output_dir,
        )
    except D2T11EvaluationError as exc:
        print(str(exc))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
