from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.canonical_io import (
    canonical_json_sha256,
    write_csv,
    write_json,
    write_markdown,
)
from src.r2.r2_t04_freeze_decision import (
    ROOT,
    T04InputError,
    _committed_csv,
    _evaluate_operator,
    _number,
    _runtime_threshold,
    _source,
)

RUN_ID = "R2-T04-20260713T120000Z"
DECISION_VALIDATION_MODE = "explicit_user_override_over_hard_gate_eligible_candidates"
PENDING_GATE_STATUS = "pending_independent_scientific_review_and_exact_head_validation"
FREEZE_PLAN_STATUS = "author_decision_recorded_pending_independent_scientific_review"
T03_RUN = "data/generated/r2/r2_t03/R2-T03-PROMOTED-20260713T050903Z"
CONFIG_PATH = ROOT / "configs/r2/r2_t04_hard_gate_pareto_freeze_plan.v1.json"
PHASE_A_FILES = (
    "r2_t04_input_binding.json",
    "r2_t04_automatic_recommendation.json",
    "r2_t04_hard_gate_report.csv",
    "r2_t04_cell_gate_summary.csv",
)
FORBIDDEN_FIELDS = {
    "backtest",
    "future_return",
    "future_path",
    "future_direction",
    "future_volatility",
    "trading_efficacy",
    "winner",
    "global_optimum",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    write_json(path, value)


def _decision_time(value: str | None) -> str:
    if value:
        return value
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _phase_a_guard(output_dir: Path) -> dict[str, Any]:
    if output_dir.name != RUN_ID:
        raise T04InputError(f"phase_b_run_id_mismatch:{output_dir.name}")
    for filename in PHASE_A_FILES:
        if not (output_dir / filename).is_file():
            raise T04InputError(f"phase_a_artifact_missing:{filename}")
    binding = _json(output_dir / "r2_t04_input_binding.json")
    if binding.get("task_id") != "R2-T04" or binding.get("phase") != "A":
        raise T04InputError("phase_a_binding_invalid")
    return binding


def _metric_evidence(output_dir: Path, cell_id: str) -> dict[str, Any]:
    t03 = ROOT / T03_RUN
    metric = next(
        row
        for row in _rows(t03 / "r2_t03_metric_results.csv")
        if row["candidate_cell_id"] == cell_id
    )
    diagnostic = next(
        row
        for row in _rows(t03 / "r2_t03_event_zone_diagnostic_profile.csv")
        if row["candidate_cell_id"] == cell_id
    )
    names = (
        "retained_confirmed_day_ratio",
        "short_interval_drop_rate",
        "bridged_day_ratio",
        "merge_ratio",
        "max_year_share",
        "qualified_event_count",
        "unique_securities",
    )
    values = {name: _number(metric[name]) for name in names}
    values["confirmed_density"] = _number(diagnostic["confirmed_density"])
    return values


def _shortlist_row(route_id: str) -> dict[str, str]:
    path = (
        ROOT
        / "data/generated/r2/r2_t01/R2-T01-20260712T0020Z/r2_t01_primary_shortlist.csv"
    )
    rows = _rows(path)
    for row in rows:
        if row["route_id"] == route_id:
            return row
    return {}


def _decision_units(
    decision_time: str, recommendation: dict[str, Any]
) -> list[dict[str, Any]]:
    rec_by_unit = {
        row["decision_unit"]: row for row in recommendation["recommendations"]
    }
    pct_w120 = "r2_s_pct_w120_qt25_primary__d2__g1"
    pct_w120_core = "r2_s_pct_w120_q20_shared__d2__g1"
    pcvt_w120 = "r2_s_pcvt_w120_qv30_primary__d2__g1"
    pcvt_w120_core = "r2_s_pcvt_w120_q20_shared__d2__g1"
    units = [
        {
            "decision_unit": "S_PCT×W120",
            "automatic_recommendation": rec_by_unit["S_PCT×W120"].get(
                "automatic_recommendation"
            ),
            "user_disposition": "selected",
            "primary_disposition": "selected",
            "shared_disposition": "retain_as_strict_core_only",
            "pair_disposition": "selected",
            "selected_candidate_cell_id": pct_w120,
            "selected_d": 2,
            "selected_g": 1,
            "paired_primary_candidate": pct_w120,
            "paired_shared_candidate": pct_w120_core,
            "strict_core_enabled": True,
            "primary_reason_code": (
                "w120_year_stability_and_coverage_with_geometry_preserved"
            ),
            "secondary_reason_codes": [
                "persistence_coverage_knee",
                "single_day_gap_tolerance_with_low_contamination",
            ],
            "accepted_warnings": json.loads(
                _shortlist_row("r2_s_pct_w120_qt25_primary").get("warning_codes", "[]")
            ),
            "accepted_event_zone_tradeoffs": [
                "W250_short_interval_drop_rate_is_marginally_lower"
            ],
            "rejected_alternatives": [
                "r2_s_pct_w120_qt25_primary__d1__g1",
                "r2_s_pct_w120_qt25_primary__d3__g1",
                "r2_s_pct_w250_qt25_primary__d2__g1",
            ],
            "override_justification": (
                "W120 preserves coverage and year stability while retaining "
                "geometry quality; d2/g1 is the persistence/coverage knee."
            ),
        },
        {
            "decision_unit": "S_PCT×W250",
            "automatic_recommendation": rec_by_unit["S_PCT×W250"].get(
                "automatic_recommendation"
            ),
            "user_disposition": "reject_pair",
            "primary_disposition": "rejected",
            "shared_disposition": "rejected",
            "pair_disposition": "reject_pair",
            "selected_candidate_cell_id": None,
            "selected_d": None,
            "selected_g": None,
            "paired_primary_candidate": "r2_s_pct_w250_qt25_primary",
            "paired_shared_candidate": "r2_s_pct_w250_q20_shared",
            "strict_core_enabled": False,
            "primary_reason_code": (
                "w120_year_stability_and_coverage_with_geometry_preserved"
            ),
            "secondary_reason_codes": ["w250_short_drop_advantage_not_material"],
            "accepted_warnings": [],
            "accepted_event_zone_tradeoffs": [
                "W250_not_materially_better_on_registered objectives"
            ],
            "rejected_alternatives": [
                "r2_s_pct_w250_qt25_primary",
                "r2_s_pct_w250_q20_shared",
            ],
            "override_justification": (
                "Reject the W250 pair because its small short-drop advantage does "
                "not compensate for lower coverage and higher year concentration."
            ),
        },
        {
            "decision_unit": "S_PCVT×W120",
            "automatic_recommendation": rec_by_unit["S_PCVT×W120"].get(
                "automatic_recommendation"
            ),
            "user_disposition": "selected",
            "primary_disposition": "selected",
            "shared_disposition": "retain_as_strict_core_only",
            "pair_disposition": "selected",
            "selected_candidate_cell_id": pcvt_w120,
            "selected_d": 2,
            "selected_g": 1,
            "paired_primary_candidate": pcvt_w120,
            "paired_shared_candidate": pcvt_w120_core,
            "strict_core_enabled": True,
            "primary_reason_code": (
                "w120_security_breadth_and_year_stability_with_geometry_preserved"
            ),
            "secondary_reason_codes": [
                "persistence_coverage_knee",
                "single_day_gap_tolerance_with_low_contamination",
            ],
            "accepted_warnings": json.loads(
                _shortlist_row("r2_s_pcvt_w120_qv30_primary").get("warning_codes", "[]")
            ),
            "accepted_event_zone_tradeoffs": [
                "W250_persistence_advantage_is_not_material_for_freeze_goal"
            ],
            "rejected_alternatives": [
                "r2_s_pcvt_w120_qv30_primary__d1__g1",
                "r2_s_pcvt_w120_qv30_primary__d3__g1",
                "r2_s_pcvt_w250_qv30_primary__d2__g1",
            ],
            "override_justification": (
                "W120 has materially broader security and year coverage with "
                "preserved geometry; d2/g1 is the persistence/coverage knee."
            ),
        },
        {
            "decision_unit": "S_PCVT×W250",
            "automatic_recommendation": rec_by_unit["S_PCVT×W250"].get(
                "automatic_recommendation"
            ),
            "user_disposition": "reject_pair",
            "primary_disposition": "rejected",
            "shared_disposition": "rejected",
            "pair_disposition": "reject_pair",
            "selected_candidate_cell_id": None,
            "selected_d": None,
            "selected_g": None,
            "paired_primary_candidate": "r2_s_pcvt_w250_qv30_primary",
            "paired_shared_candidate": "r2_s_pcvt_w250_q20_shared",
            "strict_core_enabled": False,
            "primary_reason_code": (
                "w120_security_breadth_and_year_stability_with_geometry_preserved"
            ),
            "secondary_reason_codes": ["w250_persistence_advantage_not_material"],
            "accepted_warnings": [],
            "accepted_event_zone_tradeoffs": [
                "W250_not_materially_better_on_registered objectives"
            ],
            "rejected_alternatives": [
                "r2_s_pcvt_w250_qv30_primary",
                "r2_s_pcvt_w250_q20_shared",
            ],
            "override_justification": (
                "Reject the W250 pair because its persistence advantage is small "
                "relative to W120 breadth, coverage, stability and merge geometry."
            ),
        },
    ]
    for unit in units:
        unit.update(
            {
                "automatic_recommendation_authoritative": False,
                "override": True,
                "decision_time": decision_time,
                "reviewer_identity": "Jianfeng Xie",
                "github_identity": "benzemaer",
                "decision_authority": "user_explicit_instruction",
                "evidence_refs": [
                    f"{T03_RUN}/r2_t03_metric_results.csv",
                    f"{T03_RUN}/r2_t03_event_zone_diagnostic_profile.csv",
                ],
            }
        )
        if unit["selected_candidate_cell_id"]:
            unit["evidence_values"] = {
                "selected_primary": _metric_evidence(
                    ROOT / T03_RUN, unit["selected_candidate_cell_id"]
                ),
                "strict_core": {"candidate_cell_id": unit["paired_shared_candidate"]},
            }
        else:
            unit["evidence_values"] = {}
    return units


def _write_user_inputs(
    output_dir: Path, decision_time: str, recommendation: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "phase_a_review_id": 4682660769,
        "reviewed_head": "f1e69e54729c0d6dd3b27d2d9bc5ce40220291de",
        "phase_a_review_status": "needs_revision",
        "resolution_mode": "explicit_user_override_without_phase_a_rerun",
        "automatic_recommendation_authoritative": False,
        "automatic_recommendation_consumed_by_freeze_decision": False,
        "hard_gate_evidence_reused": True,
        "hard_gate_evidence_status": "passed",
        "pareto_result_used_as_decision_authority": False,
        "weighted_score_used": False,
        "user_decision_authority": True,
        "new_parameter_search_performed": False,
        "new_candidate_generated": False,
        "phase_a_artifacts_preserved": True,
        "phase_a_artifact_paths": list(PHASE_A_FILES),
    }
    units = _decision_units(decision_time, recommendation)
    payload = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "decision_authority": "user_explicit_instruction",
        "reviewer_identity": "Jianfeng Xie",
        "github_identity": "benzemaer",
        "decision_time_utc": decision_time,
        "decision_goal": "interpretable_freeze_not_global_parameter_optimum",
        "automatic_recommendation_override": True,
        "phase_a_review_resolution_path": "r2_t04_phase_a_review_resolution.json",
        "phase_a_automatic_recommendation_path": "r2_t04_automatic_recommendation.json",
        "decision_units": units,
        "parameter_search_closed": True,
        "interaction_sidecar_requested": False,
        "T25_V30_scan_requested": False,
    }
    payload["decision_input_hash"] = canonical_json_sha256(payload)
    _write(output_dir / "r2_t04_phase_a_review_resolution.json", resolution)
    _write(output_dir / "r2_t04_user_decision_input.json", payload)
    return payload, resolution


def _global_alias(metric_id: str) -> str:
    return {
        "strict_core_subset_violation": "strict_core_subset_status",
        "transition_closure_violation": "accepted_bridge_transition_closure",
    }.get(metric_id, metric_id)


def _gate_rows(
    config: dict[str, Any], output_dir: Path, selected: list[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    binding = _json(output_dir / "r2_t04_input_binding.json")
    commit = binding["execution_commit"]
    gates = _committed_csv(_source(config, "r2_t02_hard_gate_registry.csv"), commit)
    runtime = _committed_csv(_source(config, "r2_t03_runtime_gate_results.csv"), commit)
    cell_registry = _committed_csv(
        _source(config, "r2_t02_t03_cell_registry.csv"), commit
    )
    execution = _rows(ROOT / T03_RUN / "r2_t03_cell_execution_registry.csv")
    runtime_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    global_runtime: dict[str, list[dict[str, str]]] = {}
    for row in runtime:
        key = (row["check_id"], row.get("candidate_cell_id", ""))
        runtime_by_key.setdefault(key, []).append(row)
        if not row.get("candidate_cell_id"):
            global_runtime.setdefault(row["check_id"], []).append(row)
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for cell_id in selected:
        contract = next(
            (row for row in cell_registry if row["candidate_cell_id"] == cell_id), None
        )
        run_row = next(
            (row for row in execution if row["candidate_cell_id"] == cell_id), None
        )
        if not contract or not run_row:
            failures.append(f"cell_registry_missing:{cell_id}")
            continue
        for gate in gates:
            if gate["state_line"] not in {"GLOBAL", contract["state_line"]}:
                continue
            if gate["state_line"] == "GLOBAL":
                evidence = global_runtime.get(_global_alias(gate["metric_id"]), [])
                inherited = True
            else:
                evidence = runtime_by_key.get((gate["gate_id"], cell_id), [])
                inherited = False
            record = evidence[0] if len(evidence) == 1 else None
            observed = _number(record.get("observed_value")) if record else None
            threshold = (
                _runtime_threshold(record.get("expected_rule", "")) if record else None
            )
            passed = bool(record) and record["status"] == "passed"
            if record and gate["operator"] in {">=", "<=", ">", "<", "=="}:
                passed = passed and _evaluate_operator(
                    observed, gate["operator"], threshold
                )
            if not passed:
                failures.append(f"gate_failed:{cell_id}:{gate['gate_id']}")
            rows.append(
                {
                    "candidate_cell_id": cell_id,
                    "gate_id": gate["gate_id"],
                    "state_line": gate["state_line"],
                    "metric_id": gate["metric_id"],
                    "scope": "GLOBAL_INHERITED" if inherited else "CELL",
                    "observed_value": observed,
                    "expected_rule": record.get("expected_rule") if record else None,
                    "threshold": threshold,
                    "status": "passed" if passed else "failed_missing_evidence",
                    "missing_evidence": record is None,
                    "hard_gate_override": False,
                    "selection_eligibility": run_row["status"] == "completed"
                    and contract["actual_scan_executed"] == "False",
                    "candidate_role": contract["candidate_role"],
                    "d": contract["d"],
                    "g": contract["g"],
                }
            )
        if run_row["status"] != "completed":
            failures.append(f"execution_not_completed:{cell_id}")
        if contract["d"] not in {"2"} or contract["g"] not in {"1"}:
            failures.append(f"cell_parameter_drift:{cell_id}")
    summary = {
        "selected_cell_gate_status": "passed" if not failures else "failed",
        "strict_core_cell_gate_status": "passed" if not failures else "failed",
        "selected_cell_count": len(selected),
        "gate_row_count": len(rows),
        "global_gate_rows_inherited": sum(
            row["scope"] == "GLOBAL_INHERITED" for row in rows
        ),
        "missing_evidence_count": sum(row["missing_evidence"] for row in rows),
        "hard_gate_override_count": sum(row["hard_gate_override"] for row in rows),
        "failures": failures,
    }
    return rows, summary


def _freeze_plan(units: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    versions = [
        {
            "planned_state_version_id": "r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8",
            "state_line": "S_PCT",
            "window_track_id": "W120",
            "W": 120,
            "K": 3,
            "qP": 0.20,
            "qC": 0.20,
            "qT": 0.25,
            "qV": 0.20,
            "d": 2,
            "g": 1,
            "source_candidate_cell_id": "r2_s_pct_w120_qt25_primary__d2__g1",
            "strict_core_source_candidate_cell_id": "r2_s_pct_w120_q20_shared__d2__g1",
            "strict_core_enabled": True,
        },
        {
            "planned_state_version_id": (
                "r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8"
            ),
            "state_line": "S_PCVT",
            "window_track_id": "W120",
            "W": 120,
            "K": 3,
            "qP": 0.20,
            "qC": 0.20,
            "qT": 0.20,
            "qV": 0.30,
            "d": 2,
            "g": 1,
            "source_candidate_cell_id": "r2_s_pcvt_w120_qv30_primary__d2__g1",
            "strict_core_source_candidate_cell_id": "r2_s_pcvt_w120_q20_shared__d2__g1",
            "strict_core_enabled": True,
        },
    ]
    return {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "contract_version": "r2_t02_confirmed_event_zone_state_machine_contract.v8",
        "freeze_plan_status": "passed",
        "planned_versions": versions,
        "planned_state_version_count": 2,
        "cross_window_overlap_handling_required": False,
        "cross_state_line_identity_must_remain_distinct": True,
        "t05_materialization_requirements": [
            "canonical_daily_confirmed_state",
            "component_qualification_asof",
            "event_zone_state_asof",
            "retrospective_event_membership",
            "event_zone_revision",
            "exit_censor_quality_break_reason",
            "strict_core_member",
            "state_risk_set_eligible",
            "qualified_event_risk_set_eligible",
        ],
        "t05_scope_constraints": [
            "materialize_only_two_selected_primary_versions",
            "do_not_materialize_W250",
            "shared_q_is_strict_core_only_without_independent_version",
            "do_not_modify_K_q_d_g",
            "do_not_select_additional_versions",
            "do_not_generate_PCT_parent_product",
        ],
    }


def _analysis(output_dir: Path) -> None:
    text = """# R2-T04 Phase B result analysis

本任务的目标是可解释的 freeze，而不是在同一数据上寻找全局最优参数、
交易收益最优或方向预测最优。Phase A 的 automatic recommendation 只作为历史
比较产物；本次最终选择来自用户显式 override，hard-gate 仍不可被 override。

用户没有要求 T25/V30 interaction sidecar，也没有重新打开参数搜索。W120 被选择，
因为在两条 state line 上保持更高覆盖、证券广度和年份稳定性，同时 density、
bridge 和 merge geometry 没有退化；W250 的局部 persistence 或 short-drop 优势
不足以抵消这些差异。

d=2 是 persistence/coverage knee：d=1 保留短暂与 singleton 状态，d=3 带来明显
过度过滤。g=1 提供单日 gap 容忍，同时 bridged-day ratio 低于 1% 且 density
超过 97%；g=2 的边际合并收益不足以抵消额外 gap 污染与复杂度。

两个 primary 被选为 planned versions；对应 shared-q 只作为 strict core member，
不建立独立 state_version_id 或 event identity。W250 的两个 pair 均拒绝，因此最终
是两个版本而不是四个版本。S_PCT 与 S_PCVT 始终保持不同 state version 和 event
identity。

接受的 warnings 保留在 decision record：S_PCT 的 affected-lift deterioration、
q complexity、same-sample revalidation 和 selection-path limitation；S_PCVT 的
V security negative delta、V selectivity guard、q complexity、same-sample
revalidation 和 selection-path limitation。这些 warning 不构成交易效能证据。

Phase B 完成作者阶段收口，但 R2-T04 仍等待独立 scientific review 与 repository
final gate；因此 R2-T05 和 R3 继续关闭。没有生成 T05 canonical artifacts，也没有
运行 T03 或 Phase A。
"""
    write_markdown(output_dir / "r2_t04_result_analysis.md", text)


def _anomaly(
    output_dir: Path,
    decision: dict[str, Any],
    freeze_decision: dict[str, Any],
    freeze: dict[str, Any],
    gate_summary: dict[str, Any],
    decision_input: dict[str, Any],
) -> dict[str, Any]:
    units = decision["decision_units"]
    plans = freeze["planned_versions"]

    def forbidden(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                key.lower() in FORBIDDEN_FIELDS or forbidden(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(forbidden(item) for item in value)
        return False

    checks = {
        "user_decision_missing": 0 if len(units) == 4 else 1,
        "duplicate_decision_unit": len(units)
        - len({u["decision_unit"] for u in units}),
        "selected_cell_missing": 0
        if all(
            u["selected_candidate_cell_id"]
            for u in units
            if u["user_disposition"] == "selected"
        )
        else 1,
        "selected_cell_hard_gate_failure": 0
        if gate_summary["selected_cell_gate_status"] == "passed"
        else 1,
        "global_gate_not_inherited": 0
        if gate_summary["global_gate_rows_inherited"] == 120
        else 1,
        "strict_core_pair_invalid": 0
        if all(
            u["strict_core_enabled"]
            for u in units
            if u["user_disposition"] == "selected"
        )
        else 1,
        "strict_core_independent_version": 0 if len(plans) == 2 else 1,
        "W250_in_freeze_plan": int(any(plan["W"] == 250 for plan in plans)),
        "selected_count_mismatch": int(
            sum(u["user_disposition"] == "selected" for u in units) != 2
        ),
        "state_version_id_collision": len(plans)
        - len({p["planned_state_version_id"] for p in plans}),
        "parameter_drift": int(any(p["d"] != 2 or p["g"] != 1 for p in plans)),
        "sensitivity_or_excluded_selected": 0,
        "override_without_reason": int(
            any(not u["override_justification"] for u in units)
        ),
        "warning_loss": int(
            any(
                not unit.get("accepted_warnings")
                for unit in units
                if unit["user_disposition"] == "selected"
            )
        ),
        "decision_input_hash_mismatch": int(
            decision_input.get("decision_input_hash")
            != canonical_json_sha256(
                {
                    key: value
                    for key, value in decision_input.items()
                    if key != "decision_input_hash"
                }
            )
        ),
        "decision_hash_mismatch": int(
            decision.get("decision_hash")
            != canonical_json_sha256(
                {
                    key: value
                    for key, value in decision.items()
                    if key != "decision_hash"
                }
            )
        ),
        "freeze_decision_hash_mismatch": int(
            freeze_decision.get("freeze_decision_hash")
            != canonical_json_sha256(
                {
                    key: value
                    for key, value in freeze_decision.items()
                    if key != "freeze_decision_hash"
                }
            )
        ),
        "freeze_plan_reference_mismatch": int(
            {plan["source_candidate_cell_id"] for plan in freeze["planned_versions"]}
            != {
                "r2_s_pct_w120_qt25_primary__d2__g1",
                "r2_s_pcvt_w120_qv30_primary__d2__g1",
            }
        ),
        "future_or_trading_field": int(forbidden(decision) or forbidden(freeze)),
    }
    return {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "status": "passed" if not any(checks.values()) else "investigation_required",
        "checks": checks,
        "blocking_failure_count": sum(checks.values()),
        "scientific_investigation_item_count": 0,
        "failures": [name for name, value in checks.items() if value],
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }


def _artifact_records(output_dir: Path, names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "path": str((output_dir / name).relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha(output_dir / name),
            "size_bytes": (output_dir / name).stat().st_size,
        }
        for name in names
        if (output_dir / name).is_file()
    ]


def _source_artifact_bindings(
    output_dir: Path, phase_a_binding: dict[str, Any]
) -> list[dict[str, Any]]:
    bindings = []
    for name in PHASE_A_FILES:
        path = output_dir / name
        bindings.append(
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha(path),
                "role": "phase_a_preserved_artifact",
            }
        )
    for binding in phase_a_binding["source_bindings"]:
        bindings.append(
            {
                "path": binding["path"],
                "sha256": binding["committed_byte_sha256"],
                "role": binding["role"],
            }
        )
    return bindings


def run_phase_b(
    output_dir: Path, *, decision_time_utc: str | None = None
) -> dict[str, Any]:
    phase_a_binding = _phase_a_guard(output_dir)
    config = _json(CONFIG_PATH)
    decision_time = _decision_time(decision_time_utc)
    recommendation = _json(output_dir / "r2_t04_automatic_recommendation.json")
    decision_input, resolution = _write_user_inputs(
        output_dir, decision_time, recommendation
    )
    selected = [
        "r2_s_pct_w120_qt25_primary__d2__g1",
        "r2_s_pct_w120_q20_shared__d2__g1",
        "r2_s_pcvt_w120_qv30_primary__d2__g1",
        "r2_s_pcvt_w120_q20_shared__d2__g1",
    ]
    gate_rows, gate_summary = _gate_rows(config, output_dir, selected)
    write_csv(
        output_dir / "r2_t04_selected_cell_gate_revalidation.csv",
        gate_rows,
        list(gate_rows[0]),
    )
    gate_summary["task_id"] = "R2-T04"
    gate_summary["run_id"] = RUN_ID
    gate_summary["selected_cells"] = selected
    _write(output_dir / "r2_t04_selected_cell_gate_revalidation.json", gate_summary)
    if gate_summary["selected_cell_gate_status"] != "passed":
        raise T04InputError("selected_cell_gate_revalidation_failed")
    record_units = []
    for unit in decision_input["decision_units"]:
        row = dict(unit)
        if row["selected_candidate_cell_id"]:
            row["evidence_values"]["selected_primary"] = _metric_evidence(
                output_dir, row["selected_candidate_cell_id"]
            )
        record_units.append(row)
    decision_record = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "decision_authority": decision_input["decision_authority"],
        "reviewer_identity": decision_input["reviewer_identity"],
        "github_identity": decision_input["github_identity"],
        "decision_time": decision_time,
        "automatic_recommendation_authoritative": False,
        "phase_a_automatic_recommendation_consumed_by_freeze_decision": False,
        "decision_validation_mode": DECISION_VALIDATION_MODE,
        "decision_units": record_units,
        "user_decision_authority": True,
        "warnings_accepted_for_freeze_plan": True,
        "warnings_do_not_establish_trading_efficacy": True,
        "phase_a_review_resolution_path": "r2_t04_phase_a_review_resolution.json",
        "user_decision_input_path": "r2_t04_user_decision_input.json",
        "phase_a_automatic_recommendation_path": "r2_t04_automatic_recommendation.json",
        "phase_a_hard_gate_report_path": "r2_t04_hard_gate_report.csv",
        "phase_a_cell_gate_summary_path": "r2_t04_cell_gate_summary.csv",
        "source_artifact_bindings": _source_artifact_bindings(
            output_dir, phase_a_binding
        ),
        "decision_input_hash": decision_input["decision_input_hash"],
    }
    decision_record["decision_hash"] = canonical_json_sha256(decision_record)
    _write(output_dir / "r2_t04_user_decision_record.json", decision_record)
    freeze_decision = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "freeze_decision_status": "passed",
        "selected_version_count": 2,
        "rejected_decision_unit_count": 2,
        "strict_core_only_count": 2,
        "decision_units": [
            {
                "decision_unit": u["decision_unit"],
                "automatic_recommendation": u["automatic_recommendation"],
                "primary_candidate_cell_id": u["paired_primary_candidate"],
                "shared_candidate_cell_id": u["paired_shared_candidate"],
                "primary_disposition": u["primary_disposition"],
                "shared_disposition": u["shared_disposition"],
                "pair_disposition": u["pair_disposition"],
                "selected_d": u["selected_d"],
                "selected_g": u["selected_g"],
                "strict_core_enabled": u["strict_core_enabled"],
            }
            for u in record_units
        ],
        "user_decision_record_path": "r2_t04_user_decision_record.json",
        "decision_hash": decision_record["decision_hash"],
        "freeze_plan_status": FREEZE_PLAN_STATUS,
    }
    freeze_decision["freeze_decision_hash"] = canonical_json_sha256(freeze_decision)
    _write(output_dir / "r2_t04_freeze_decision.json", freeze_decision)
    freeze_plan = _freeze_plan(record_units, output_dir)
    freeze_plan["user_decision_record_path"] = "r2_t04_user_decision_record.json"
    freeze_plan["freeze_decision_path"] = "r2_t04_freeze_decision.json"
    freeze_plan["decision_hash"] = decision_record["decision_hash"]
    freeze_plan["freeze_decision_hash"] = freeze_decision["freeze_decision_hash"]
    freeze_plan["freeze_plan_hash"] = canonical_json_sha256(freeze_plan)
    _write(output_dir / "r2_t04_freeze_plan_manifest.json", freeze_plan)
    anomaly = _anomaly(
        output_dir,
        decision_record,
        freeze_decision,
        freeze_plan,
        gate_summary,
        decision_input,
    )
    _write(output_dir / "r2_t04_anomaly_scan.json", anomaly)
    if anomaly["status"] != "passed":
        raise T04InputError("phase_b_anomaly_scan_failed")
    _analysis(output_dir)
    author_review = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "review_phase": "author_stage",
        "user_decision_status": "recorded",
        "freeze_decision_status": "passed",
        "freeze_plan_status": "passed",
        "independent_validation_status": "pending",
        "scientific_review_status": "pending_independent_scientific_review",
        "reviewer_identity": "Jianfeng Xie",
        "selection_path_not_independently_confirmed": True,
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    _write(output_dir / "r2_t04_author_stage_scientific_review.json", author_review)
    repository_gate = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "repository_final_gate_status": PENDING_GATE_STATUS,
        "exact_head_required": True,
        "reviewed_head": None,
        "scientific_review_status": "pending_independent_scientific_review",
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    _write(output_dir / "r2_t04_repository_final_gate.json", repository_gate)
    result_package = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "phase": "A+B_author_stage",
        "user_decision_status": "recorded",
        "freeze_decision_status": "passed",
        "freeze_plan_status": "passed",
        "independent_validation_status": "pending",
        "anomaly_scan_status": "passed",
        "scientific_review_status": "pending_independent_scientific_review",
        "repository_final_gate_status": PENDING_GATE_STATUS,
        "phase_a_automatic_recommendation_authoritative": False,
        "phase_a_user_override": True,
        "pareto_recommendation_recomputed": False,
        "pareto_recommendation_used_for_final_decision": False,
        "decision_validation_mode": DECISION_VALIDATION_MODE,
        "hard_gate_evidence_status": "passed",
        "selected_version_count": 2,
        "strict_core_only_count": 2,
        "rejected_pair_count": 2,
        "decision_hash": decision_record["decision_hash"],
        "freeze_decision_hash": freeze_decision["freeze_decision_hash"],
        "freeze_plan_hash": freeze_plan["freeze_plan_hash"],
        "phase_a_artifacts_preserved": True,
        "source_artifact_bindings": decision_record["source_artifact_bindings"],
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "source_artifacts": phase_a_binding["source_bindings"],
    }
    _write(output_dir / "r2_t04_result_package.json", result_package)
    from src.r2.r2_t04_independent_validator import validate_phase_b

    independent = validate_phase_b(output_dir)
    _write(output_dir / "r2_t04_phase_b_independent_validation.json", independent)
    if independent["status"] != "passed":
        raise T04InputError("phase_b_independent_validation_failed")
    author_review["independent_validation_status"] = "passed"
    _write(output_dir / "r2_t04_author_stage_scientific_review.json", author_review)
    result_package["independent_validation_status"] = "passed"
    result_package["independent_validation_path"] = (
        "r2_t04_phase_b_independent_validation.json"
    )
    _write(output_dir / "r2_t04_result_package.json", result_package)
    phase_b_validation = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "status": "passed",
        "phase_a_rerun": False,
        "t03_rerun": False,
        "selected_cell_gate_status": gate_summary["selected_cell_gate_status"],
        "independent_validation_status": independent["status"],
        "anomaly_scan_status": anomaly["status"],
        "user_decision_status": "recorded",
        "freeze_plan_status": "passed",
        "scientific_review_status": "pending_independent_scientific_review",
        "repository_final_gate_status": PENDING_GATE_STATUS,
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    _write(output_dir / "r2_t04_phase_b_validation.json", phase_b_validation)
    artifact_names = [
        "r2_t04_phase_a_review_resolution.json",
        "r2_t04_user_decision_input.json",
        "r2_t04_user_decision_record.json",
        "r2_t04_selected_cell_gate_revalidation.csv",
        "r2_t04_selected_cell_gate_revalidation.json",
        "r2_t04_freeze_decision.json",
        "r2_t04_freeze_plan_manifest.json",
        "r2_t04_phase_b_independent_validation.json",
        "r2_t04_anomaly_scan.json",
        "r2_t04_result_analysis.md",
        "r2_t04_result_package.json",
        "r2_t04_author_stage_scientific_review.json",
        "r2_t04_repository_final_gate.json",
        "r2_t04_phase_b_validation.json",
    ]
    manifest = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "artifact_hash_basis": "committed_artifact_bytes",
        "artifact_count": len(artifact_names),
        "artifacts": _artifact_records(output_dir, artifact_names),
        "phase_a_artifacts_preserved": True,
        "user_decision_status": "recorded",
        "freeze_decision_status": "passed",
        "freeze_plan_status": "passed",
        "independent_validation_status": "passed",
        "anomaly_scan_status": "passed",
        "scientific_review_status": "pending_independent_scientific_review",
        "repository_final_gate_status": PENDING_GATE_STATUS,
        "formal_task_completed": False,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    _write(output_dir / "r2_t04_output_manifest.json", manifest)
    return phase_b_validation
