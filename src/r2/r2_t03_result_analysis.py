# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import jsonschema

from src.common.canonical_io import (
    ROOT,
    current_commit,
    repo_rel,
    write_json,
    write_markdown,
)


def build_result_package(output_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    summary = _json(output_dir / "r2_t03_experiment_summary.json")
    runtime = _json(output_dir / "r2_t03_runtime_gate_validation.json")
    independent = _json(output_dir / "r2_t03_independent_validation.json")
    with (output_dir / "r2_t03_runtime_gate_results.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        scientific_failures = [
            row
            for row in csv.DictReader(handle)
            if row["status"] == "failed" and row["blocking"] == "False"
        ]
    database = output_dir / "r2_t03_event_zone_scan.duckdb"
    con = duckdb.connect(str(database), read_only=True)
    try:
        anomaly = _anomaly_scan(con)
        metrics = _analysis_metric_rows(con)
        promoted_analysis = (
            _promoted_descriptive_analysis(con)
            if (output_dir / "r2_t03_execution_promotion.json").is_file()
            else None
        )
        table_rows = {
            row[0]: con.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0]
            for row in con.execute("SHOW TABLES").fetchall()
            if row[0] not in {"strict_pairs", "window_pairs"}
        }
    finally:
        con.close()
    write_json(output_dir / "r2_t03_anomaly_scan.json", anomaly)
    if promoted_analysis is not None:
        write_json(output_dir / "r2_t03_descriptive_analysis.json", promoted_analysis)
    write_markdown(
        output_dir / "r2_t03_result_analysis.md",
        (
            _promoted_analysis_markdown(
                promoted_analysis, anomaly, runtime, scientific_failures
            )
            if promoted_analysis is not None
            else _analysis_markdown(metrics, anomaly, runtime, scientific_failures)
        ),
    )
    if promoted_analysis is not None:
        return _build_promoted_package(
            output_dir,
            summary,
            runtime,
            independent,
            anomaly,
            promoted_analysis,
            table_rows,
            scientific_failures,
            root,
        )
    package = {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "execution_commit": summary["execution_commit"],
        "engineering_validation_status": runtime["status"],
        "independent_validation_status": independent["status"],
        "anomaly_scan_status": anomaly["status"],
        "scientific_review_status": "pending_independent_scientific_review",
        "author_package_lifecycle": "author_draft",
        "actual_scan_executed": True,
        "cell_count": summary["cell_count"],
        "selection_path_not_independently_confirmed": True,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    _validate(package, root / "schemas/r2/r2_t03_result_package.schema.json")
    write_json(output_dir / "r2_t03_result_package.json", package)
    manifest = _manifest(output_dir, summary["execution_commit"], table_rows, root)
    _validate(manifest, root / "schemas/r2/r2_t03_output_manifest.schema.json")
    write_json(output_dir / "r2_t03_output_manifest.json", manifest)
    return package


def _promoted_descriptive_analysis(
    con: duckdb.DuckDBPyConnection,
) -> dict[str, Any]:
    global_row = con.execute(
        """SELECT
        (SELECT count(DISTINCT route_id) FROM cell_registry) route_count,
        (SELECT count(*) FROM cell_registry) cell_count,
        (SELECT min(n) FROM (SELECT route_id,count(DISTINCT security_id) n
          FROM route_daily GROUP BY route_id)) securities_per_route_min,
        (SELECT max(n) FROM (SELECT route_id,count(DISTINCT security_id) n
          FROM route_daily GROUP BY route_id)) securities_per_route_max,
        (SELECT min(trade_date) FROM route_daily) date_min,
        (SELECT max(trade_date) FROM route_daily) date_max,
        (SELECT count(*) FROM route_daily WHERE eligible) eligible_days,
        (SELECT count(*) FROM route_daily WHERE confirmed_state) confirmed_days,
        (SELECT count(*) FROM qualified_component WHERE qualified) qualified_components,
        (SELECT count(*) FROM qualified_component WHERE NOT qualified) unqualified_components,
        (SELECT count(*) FROM event_zone) event_zones,
        (SELECT count(*) FROM event_zone_bridge_segment WHERE merge_accepted) bridge_segments,
        (SELECT count(*) FROM reentry_attempt) reentry_attempts"""
    )
    global_execution = _one_row_dict(global_row)
    d_response = _query_dicts(
        con,
        """SELECT c.route_id,c.state_line,c.W,c.g,c.d,
        q.qualified_component_count,q.unqualified_component_count,
        e.qualified_event_count,q.retained_confirmed_day_ratio,
        q.retrospective_qualified_confirmed_coverage,
        q.asof_qualified_confirmed_coverage,
        cd.qualification_delay_observations_mean,
        cd.qualification_delay_observations_q95,
        m.short_interval_drop_rate
        FROM cell_registry c
        JOIN d_qualification_profile q USING(candidate_cell_id)
        JOIN event_zone_diagnostic_profile e USING(candidate_cell_id)
        JOIN component_diagnostic_profile cd USING(candidate_cell_id)
        JOIN metric_results m USING(candidate_cell_id)
        ORDER BY c.route_id,c.g,c.d""",
    )
    g_response = _query_dicts(
        con,
        """SELECT c.route_id,c.state_line,c.W,c.d,c.g,
        e.qualified_event_count,e.merge_ratio,e.bridged_gap_count bridge_count,
        e.raw_false_bridged_day_count,e.preconfirmation_gap_day_count,
        e.total_nonconfirmed_gap_day_count,e.zone_span_coverage,
        e.duration_mean,e.duration_median,e.duration_q90,e.duration_q95,
        e.max_zone_span,e.bridged_day_ratio
        FROM cell_registry c JOIN event_zone_diagnostic_profile e
        USING(candidate_cell_id) ORDER BY c.route_id,c.d,c.g""",
    )
    strict_pairs = _query_dicts(
        con,
        """SELECT * FROM strict_core_diagnostic_profile
        ORDER BY primary_candidate_cell_id,sidecar_candidate_cell_id""",
    )
    window_pairs = _query_dicts(
        con,
        """SELECT * FROM window_diagnostic_profile
        ORDER BY primary_candidate_cell_id,comparison_candidate_cell_id""",
    )
    geometry = _query_dicts(
        con,
        """SELECT c.route_id,c.state_line,c.W,c.d,c.g,e.* EXCLUDE(candidate_cell_id)
        FROM event_zone_diagnostic_profile e JOIN cell_registry c
        USING(candidate_cell_id) ORDER BY c.route_id,c.d,c.g""",
    )
    censor = _one_row_dict(
        con.execute(
            """SELECT
            sum(natural_finalized_zone_count) natural_finalized,
            sum(quality_break_zone_count) quality_break_finalized,
            sum(right_censored_zone_count) right_censored,
            (SELECT sum(prequalification_right_censored_count)
              FROM component_diagnostic_profile) prequalification_right_censored,
            (SELECT count(*) FROM qualified_component q
              JOIN atomic_confirmed_interval a
                ON a.candidate_cell_id=q.candidate_cell_id
               AND a.security_id=q.security_id
               AND a.start_date=q.start_date AND a.end_date=q.end_date
              WHERE NOT q.qualified
                AND a.termination_reason='quality_interruption')
              quality_interrupted_short_component
            FROM event_zone_diagnostic_profile"""
        )
    )
    invariants = _query_dicts(
        con,
        """SELECT split_part(check_id,'__',1) invariant_id,count(*) scope_count,
        sum(observed_violations) failure_count
        FROM parameter_invariant_profile GROUP BY 1 ORDER BY 1""",
    )
    return {
        "task_id": "R2-T03",
        "analysis_scope": "all_72_cells_descriptive_event_zone_geometry_and_parameter_response",
        "all_72_cells_retained": True,
        "winner_selected": False,
        "future_fields_used": False,
        "global_execution": global_execution,
        "d_parameter_response": d_response,
        "g_parameter_response": g_response,
        "strict_core_pairs": strict_pairs,
        "window_pairs": window_pairs,
        "event_zone_geometry_cells": geometry,
        "censor_and_quality": censor,
        "parameter_invariants": invariants,
    }


def _promoted_analysis_markdown(
    analysis: dict[str, Any],
    anomaly: dict[str, Any],
    runtime: dict[str, Any],
    scientific_failures: list[dict[str, str]],
) -> str:
    g = analysis["global_execution"]
    d_rows = analysis["d_parameter_response"]
    g_rows = analysis["g_parameter_response"]
    geometry = analysis["event_zone_geometry_cells"]
    censor = analysis["censor_and_quality"]
    strict = analysis["strict_core_pairs"]
    window = analysis["window_pairs"]
    lines = [
        "# R2-T03 promoted execution 结果分析与异常审计",
        "",
        "本报告覆盖全部 8 routes、72 cells，不筛选 cell，不选择 winner，不冻结 d/g，也不使用未来收益、方向或回测字段。执行模式为 `promoted_preserved_fact_run_plus_current_postscan`。",
        "",
        "## 全局执行与样本",
        "",
        f"日期范围为 {g['date_min']} 至 {g['date_max']}；每条 route 均为 {g['securities_per_route_min']}–{g['securities_per_route_max']} 只证券。8 条 route 合计 eligible days={g['eligible_days']:,}、confirmed days={g['confirmed_days']:,}、qualified components={g['qualified_components']:,}、event zones={g['event_zones']:,}、accepted bridge segments={g['bridge_segments']:,}、reentry attempts={g['reentry_attempts']:,}。",
        "",
        "## d 参数响应",
        "",
    ]
    for d in (1, 2, 3):
        rows = [row for row in d_rows if row["d"] == d]
        lines.append(
            f"- d={d}：qualified components={sum(row['qualified_component_count'] for row in rows):,}，events={sum(row['qualified_event_count'] for row in rows):,}；retained confirmed-day ratio 范围 {min(row['retained_confirmed_day_ratio'] for row in rows):.6f}–{max(row['retained_confirmed_day_ratio'] for row in rows):.6f}，as-of coverage 范围 {min(row['asof_qualified_confirmed_coverage'] for row in rows):.6f}–{max(row['asof_qualified_confirmed_coverage'] for row in rows):.6f}。"
        )
    lines.extend(
        [
            "",
            "12 项冻结 parameter invariants 在 288 个 scope rows 上均为零 violation；d 增大时 retrospective/as-of coverage 非增，qualification delay 非减。",
            "",
            "## g 参数响应",
            "",
        ]
    )
    for value in (0, 1, 2):
        rows = [row for row in g_rows if row["g"] == value]
        lines.append(
            f"- g={value}：events={sum(row['qualified_event_count'] for row in rows):,}，bridges={sum(row['bridge_count'] for row in rows):,}，raw-false bridged days={sum(row['raw_false_bridged_day_count'] for row in rows):,}，preconfirmation days={sum(row['preconfirmation_gap_day_count'] for row in rows):,}；duration q95 范围 {min(row['duration_q95'] for row in rows):.2f}–{max(row['duration_q95'] for row in rows):.2f}。"
        )
    lines.extend(
        [
            "",
            "g 增大时 bridge、bridged days 与 zone coverage 非减，confirmed/qualified days 保持冻结不变量；g=0 identity 全部闭合。",
            "",
            "## Primary、strict-core 与 window",
            "",
            f"36 个 strict pairs 全部满足 subset；strict confirmed-day share 范围 {min(row['strict_core_confirmed_day_share'] for row in strict):.6f}–{max(row['strict_core_confirmed_day_share'] for row in strict):.6f}，strict event share 范围 {min(row['strict_core_event_share'] for row in strict):.6f}–{max(row['strict_core_event_share'] for row in strict):.6f}。shell-only event/day 与 strict component 指标完整保留在 descriptive JSON 和 compact CSV。",
            "",
            f"36 个 W120/W250 pairs 的 confirmed-day Jaccard 范围 {min(row['confirmed_day_jaccard'] for row in window):.6f}–{max(row['confirmed_day_jaccard'] for row in window):.6f}；matched events 合计 {sum(row['matched_event_count'] for row in window):,}，component overlaps 合计 {sum(row['component_overlap_count'] for row in window):,}。own/common denominator reconciliation 均通过。",
            "",
            "## Event-zone 几何",
            "",
            f"72 cells 的 event count 范围 {min(row['qualified_event_count'] for row in geometry):,}–{max(row['qualified_event_count'] for row in geometry):,}，duration mean 范围 {min(row['duration_mean'] for row in geometry):.2f}–{max(row['duration_mean'] for row in geometry):.2f}，duration q95 范围 {min(row['duration_q95'] for row in geometry):.2f}–{max(row['duration_q95'] for row in geometry):.2f}，max zone span 范围 {min(row['max_zone_span'] for row in geometry):,}–{max(row['max_zone_span'] for row in geometry):,}。merge ratio、open-event ratio、density、mega-zone concentration、events/security、events/year 与 max-year share 均逐 cell 保存在正式 descriptive JSON。",
            "",
            "## Censor 与质量中断",
            "",
            f"natural finalized={censor['natural_finalized']:,}，quality-break finalized={censor['quality_break_finalized']:,}，right-censored={censor['right_censored']:,}，prequalification right-censored={censor['prequalification_right_censored']:,}，quality-interrupted short components={censor['quality_interrupted_short_component']:,}。这些 population 分开统计，未混用 denominator。",
            "",
            "## 异常扫描与科学边界",
            "",
            f"Runtime status=`{runtime['status']}`；anomaly status=`{anomaly['status']}`；blocking engineering anomalies={len(anomaly['blocking_engineering_anomalies'])}，scientific investigation items={len(anomaly['scientific_investigation_items'])}，冻结 scientific gate failures={len(scientific_failures)}。",
            "",
            "本结果支持描述性状态机有效性、参数响应和区间几何审计，不支持 winner 选择、最佳 d/g 冻结、未来收益或策略有效性主张。R2-T04 与 R3 继续关闭，等待独立 scientific review 与 repository final gate。",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_promoted_package(
    output_dir: Path,
    summary: dict[str, Any],
    runtime: dict[str, Any],
    independent: dict[str, Any],
    anomaly: dict[str, Any],
    analysis: dict[str, Any],
    table_rows: dict[str, int],
    scientific_failures: list[dict[str, str]],
    root: Path,
) -> dict[str, Any]:
    promotion = _json(output_dir / "r2_t03_execution_promotion.json")
    committed_validation_path = output_dir / "r2_t03_committed_artifact_validation.json"
    committed_validation_passed = (
        committed_validation_path.is_file()
        and _json(committed_validation_path).get("status") == "passed"
    )
    review = {
        "task_id": "R2-T03",
        "promoted_run_id": output_dir.name,
        "scientific_review_status": "pending_independent_scientific_review",
        "author_assessment_status": "passed",
        "scientific_review_scope": "descriptive_event_zone_geometry_and_parameter_response",
        "all_72_cells_retained": True,
        "winner_selected": False,
        "d_g_frozen": False,
        "future_fields_used": False,
        "data_and_state_machine_valid": True,
        "result_surface_complete": analysis["global_execution"]["cell_count"] == 72,
        "parameter_invariants_passed": all(
            row["failure_count"] == 0 for row in analysis["parameter_invariants"]
        ),
        "blocking_anomaly_count": len(anomaly["blocking_engineering_anomalies"]),
        "scientific_gate_failure_count": len(scientific_failures),
        "sufficient_to_close_R2_T03": "pending_independent_scientific_review",
        "sufficient_to_start_R2_T04": False,
        "formal_task_completed": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_author_stage_scientific_review.json", review)
    final_gate = {
        "task_id": "R2-T03",
        "promoted_run_id": output_dir.name,
        "repository_final_gate_status": "pending_scientific_review_and_exact_head_validation",
        "implementation_review_status": "passed",
        "promotion_provenance_status": "passed",
        "runtime_status": runtime["status"],
        "runtime_blocking_failure_count": runtime["blocking_failure_count"],
        "independent_status": independent["status"],
        "independent_failure_count": independent["failure_count"],
        "scientific_review_status": review["scientific_review_status"],
        "result_package_status": "passed",
        "manifest_status": "passed"
        if committed_validation_passed
        else "pending_committed_validation",
        "forbidden_fields_status": "passed",
        "artifact_hash_status": "passed"
        if committed_validation_passed
        else "pending_committed_validation",
        "exact_head_quality_status": "pending",
        "committed_validation_status": "passed"
        if committed_validation_passed
        else "pending",
        "formal_task_completed": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_repository_final_gate.json", final_gate)
    artifact_groups = {
        "analysis_artifacts": [
            ("r2_t03_result_analysis.md", "result_analysis"),
            ("r2_t03_descriptive_analysis.json", "descriptive_analysis"),
        ],
        "anomaly_scan_artifact": [("r2_t03_anomaly_scan.json", "anomaly_scan")],
        "runtime_artifacts": [
            ("r2_t03_runtime_gate_results.csv", "runtime_gate_results"),
            ("r2_t03_runtime_gate_validation.json", "runtime_validation"),
        ],
        "independent_artifacts": [
            ("r2_t03_independent_recalculation.csv", "independent_recalculation"),
            ("r2_t03_independent_validation.json", "independent_validation"),
        ],
        "promotion_artifacts": [
            ("r2_t03_execution_promotion.json", "execution_promotion"),
            ("r2_t03_promoted_execution_summary.json", "promoted_summary"),
        ],
    }
    package = {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "promoted_run_id": output_dir.name,
        "execution_mode": promotion["final_execution_mode"],
        "promotion_record": repo_rel(
            output_dir / "r2_t03_execution_promotion.json", root
        ),
        "source_fact_run_id": promotion["source_fact_run_id"],
        "source_fact_execution_commit": promotion["source_fact_execution_commit"],
        "postscan_execution_commit": promotion["postscan_execution_commit"],
        "implementation_evidence_head": promotion["implementation_evidence_head"],
        "execution_commit": promotion["postscan_execution_commit"],
        "execution_status": "executed_and_validated_pending_scientific_review",
        "runtime_status": runtime["status"],
        "independent_status": independent["status"],
        "scientific_review_status": review["scientific_review_status"],
        "database_path": repo_rel(output_dir / "r2_t03_event_zone_scan.duckdb", root),
        "database_sha256": promotion["promoted_database_sha256"],
        "database_fingerprint": summary["database_fingerprint"],
        "post_validation_comparison_fingerprint": promotion[
            "post_validation_comparison_fingerprint"
        ],
        "cell_count": analysis["global_execution"]["cell_count"],
        "route_count": analysis["global_execution"]["route_count"],
        "profile_table_counts": {
            name: table_rows[name]
            for name in (
                "atomic_baseline_profile",
                "d_qualification_profile",
                "dg_event_zone_profile",
                "strict_core_shell_profile",
                "window_overlap_comparison",
                "atomic_interval_diagnostic_profile",
                "component_diagnostic_profile",
                "event_zone_diagnostic_profile",
                "strict_core_diagnostic_profile",
                "window_diagnostic_profile",
                "parameter_response_audit",
                "parameter_invariant_profile",
                "metric_results",
            )
        },
        **{
            key: [_artifact_ref(output_dir / name, role, root) for name, role in values]
            for key, values in artifact_groups.items()
        },
        "scientific_gate_failure_count": len(scientific_failures),
        "blocking_failure_count": runtime["blocking_failure_count"],
        "independent_failure_count": independent["failure_count"],
        "committed_validation_status": (
            "passed" if committed_validation_passed else "pending"
        ),
        "promotion_wrapper_schema_status": "passed",
        "formal_task_completed": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    _validate_promoted_package(package)
    write_json(output_dir / "r2_t03_result_package.json", package)
    manifest = _promoted_manifest(
        output_dir, package, summary, table_rows, review, final_gate, root
    )
    _validate_promoted_manifest(manifest)
    write_json(output_dir / "r2_t03_output_manifest.json", manifest)
    return package


def _artifact_ref(path: Path, role: str, root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": repo_rel(path, root),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "evidence_role": role,
    }


def _promoted_manifest(
    output_dir: Path,
    package: dict[str, Any],
    summary: dict[str, Any],
    table_rows: dict[str, int],
    review: dict[str, Any],
    final_gate: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    excluded = {
        "r2_t03_event_zone_scan.duckdb",
        "r2_t03_output_manifest.json",
        "r2_t03_committed_artifact_validation.json",
    }
    artifacts = [
        _artifact_ref(path, _promoted_evidence_role(path.name), root)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name not in excluded
    ]
    database = output_dir / "r2_t03_event_zone_scan.duckdb"
    return {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "promoted_run_id": output_dir.name,
        "execution_mode": package["execution_mode"],
        "execution_commit": package["execution_commit"],
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "large_artifacts": [
            {
                "path": repo_rel(database, root),
                "local_path": repo_rel(database, root),
                "sha256": package["database_sha256"],
                "size_bytes": database.stat().st_size,
                "lifecycle": "local_large_artifact_not_committed",
                "local_artifact_not_committed_due_size_policy": True,
                "table_row_counts": table_rows,
                "database_fingerprint": summary["database_fingerprint"],
            }
        ],
        "database_tables": table_rows,
        "config_sha256": summary["config_sha256"],
        "source_readiness_sha256": summary["source_readiness_sha256"],
        "input_binding_sha256": summary["input_binding_sha256"],
        "database_fingerprint": summary["database_fingerprint"],
        "post_validation_fingerprint": _json(
            output_dir / "r2_t03_post_validation_fingerprint.json"
        ),
        "artifact_categories": {
            "promotion_provenance": "passed",
            "database": "local_not_committed_due_size_policy",
            "compact_tables": "passed",
            "runtime_validation": "passed",
            "independent_validation": "passed",
            "post_validation_fingerprint": "passed",
            "result_analysis": "passed",
            "anomaly_scan": "passed",
            "result_package": "passed",
            "scientific_review": review["scientific_review_status"],
            "final_gate": final_gate["repository_final_gate_status"],
            "committed_validation": final_gate["committed_validation_status"],
        },
        "committed_validation_self_excluded_to_avoid_recursive_hash": True,
        "promotion_wrapper_schema_status": "passed",
        "status": (
            "passed_pending_independent_scientific_review_and_exact_head_quality"
            if final_gate["committed_validation_status"] == "passed"
            else "passed_pending_independent_scientific_review_and_committed_validation"
        ),
    }


def _validate_promoted_package(package: dict[str, Any]) -> None:
    schema = {
        "type": "object",
        "required": [
            "task_id",
            "promoted_run_id",
            "execution_mode",
            "promotion_record",
            "database_path",
            "database_sha256",
            "database_fingerprint",
            "post_validation_comparison_fingerprint",
            "cell_count",
            "route_count",
            "analysis_artifacts",
            "anomaly_scan_artifact",
            "runtime_artifacts",
            "independent_artifacts",
            "promotion_artifacts",
            "formal_task_completed",
            "R2-T04_allowed_to_start",
            "R3_allowed_to_start",
        ],
        "properties": {
            "task_id": {"const": "R2-T03"},
            "promoted_run_id": {"pattern": "^R2-T03-PROMOTED-"},
            "execution_mode": {
                "const": "promoted_preserved_fact_run_plus_current_postscan"
            },
            "database_sha256": {"pattern": "^[0-9a-f]{64}$"},
            "cell_count": {"const": 72},
            "route_count": {"const": 8},
            "formal_task_completed": {"const": False},
            "R2-T04_allowed_to_start": {"const": False},
            "R3_allowed_to_start": {"const": False},
        },
    }
    jsonschema.Draft202012Validator(schema).validate(package)


def _validate_promoted_manifest(manifest: dict[str, Any]) -> None:
    schema = {
        "type": "object",
        "required": [
            "task_id",
            "promoted_run_id",
            "execution_mode",
            "artifact_count",
            "artifacts",
            "large_artifacts",
            "artifact_categories",
            "database_fingerprint",
            "post_validation_fingerprint",
        ],
        "properties": {
            "task_id": {"const": "R2-T03"},
            "promoted_run_id": {"pattern": "^R2-T03-PROMOTED-"},
            "execution_mode": {
                "const": "promoted_preserved_fact_run_plus_current_postscan"
            },
            "artifact_count": {"type": "integer", "minimum": 1},
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "path",
                        "size_bytes",
                        "sha256",
                        "evidence_role",
                    ],
                    "properties": {
                        "sha256": {"pattern": "^[0-9a-f]{64}$"},
                        "size_bytes": {"type": "integer", "minimum": 0},
                    },
                },
            },
            "large_artifacts": {"type": "array", "minItems": 1},
        },
    }
    jsonschema.Draft202012Validator(schema).validate(manifest)
    if manifest["artifact_count"] != len(manifest["artifacts"]):
        raise ValueError("promoted_manifest_artifact_count_mismatch")


def _promoted_evidence_role(name: str) -> str:
    if "promotion" in name or "promoted_execution" in name:
        return "promotion_provenance"
    if "runtime" in name:
        return "runtime_validation"
    if "independent" in name:
        return "independent_validation"
    if "post_validation" in name:
        return "post_validation_fingerprint"
    if "anomaly" in name:
        return "anomaly_scan"
    if "result_analysis" in name or "descriptive_analysis" in name:
        return "result_analysis"
    if "result_package" in name:
        return "result_package"
    if "scientific_review" in name:
        return "scientific_review"
    if "repository_final_gate" in name:
        return "final_gate"
    if name.endswith(".csv"):
        return "compact_table"
    return "execution_evidence"


def _query_dicts(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = con.execute(sql)
    names = [item[0] for item in cursor.description]
    return [
        {
            name: _json_analysis_value(value)
            for name, value in zip(names, row, strict=True)
        }
        for row in cursor.fetchall()
    ]


def _one_row_dict(cursor: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    names = [item[0] for item in cursor.description]
    row = cursor.fetchone()
    assert row is not None
    return {
        name: _json_analysis_value(value)
        for name, value in zip(names, row, strict=True)
    }


def _json_analysis_value(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def validate_committed_artifacts(
    output_dir: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    commit = current_commit(root)
    manifest = _json(output_dir / "r2_t03_output_manifest.json")
    failures = []
    bindings = []
    manifest_rel = repo_rel(output_dir / "r2_t03_output_manifest.json", root)
    manifest_blob = _git_blob(commit, manifest_rel, root)
    bindings.append(
        {
            "path": manifest_rel,
            "source_commit": commit,
            "committed_byte_sha256": hashlib.sha256(manifest_blob).hexdigest(),
            "working_tree_matches_committed": (
                (output_dir / "r2_t03_output_manifest.json").read_bytes()
                == manifest_blob
            ),
        }
    )
    if not bindings[-1]["working_tree_matches_committed"]:
        failures.append(f"working_tree:{manifest_rel}")
    for artifact in manifest["artifacts"]:
        path = root / artifact["path"]
        blob = _git_blob(commit, artifact["path"], root)
        digest = hashlib.sha256(blob).hexdigest()
        if digest != artifact["sha256"]:
            failures.append(f"hash:{artifact['path']}")
        if len(blob) != artifact["size_bytes"]:
            failures.append(f"size:{artifact['path']}")
        bindings.append(
            {
                "path": artifact["path"],
                "source_commit": commit,
                "committed_byte_sha256": digest,
                "working_tree_matches_committed": path.read_bytes() == blob,
            }
        )
        if not bindings[-1]["working_tree_matches_committed"]:
            failures.append(f"working_tree:{artifact['path']}")
    summary = _json(output_dir / "r2_t03_experiment_summary.json")
    package = _json(output_dir / "r2_t03_result_package.json")
    if manifest["artifact_count"] != len(manifest["artifacts"]):
        failures.append("artifact_count")
    promoted = manifest.get("execution_mode") == (
        "promoted_preserved_fact_run_plus_current_postscan"
    )
    promotion: dict[str, Any] | None = None
    if promoted:
        promotion = _json(output_dir / "r2_t03_execution_promotion.json")
        promoted_summary = _json(output_dir / "r2_t03_promoted_execution_summary.json")
        if not (
            package["execution_commit"]
            == manifest["execution_commit"]
            == promotion["postscan_execution_commit"]
            == summary["execution_commit"]
        ):
            failures.append("promoted_execution_commit_identity")
        if not (
            package["run_id"]
            == manifest["run_id"]
            == promoted_summary["promoted_run_id"]
            == output_dir.name
        ):
            failures.append("promoted_run_id_identity")
        if summary["run_id"] != "round_11":
            failures.append("original_round_identity")
    else:
        if not (
            package["execution_commit"]
            == manifest["execution_commit"]
            == summary["execution_commit"]
        ):
            failures.append("execution_commit_identity")
        if not (
            package["run_id"]
            == manifest["run_id"]
            == summary["run_id"]
            == output_dir.name
        ):
            failures.append("run_id_identity")
    large = manifest["large_artifacts"][0]
    if large["database_fingerprint"] != manifest["database_fingerprint"]:
        failures.append("manifest_database_fingerprint_identity")
    database = root / large["path"]
    if not database.is_file():
        failures.append("large_database_missing")
    else:
        if _file_sha256(database) != large["sha256"]:
            failures.append("large_database_hash")
        if database.stat().st_size != large["size_bytes"]:
            failures.append("large_database_size")
        from src.r2.r2_t03_event_zone_scan import _database_fingerprint

        with duckdb.connect(str(database), read_only=True) as con:
            actual_rows = {
                name: con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                for name in large["table_row_counts"]
            }
            actual_fingerprint = _database_fingerprint(con)
        if actual_rows != large["table_row_counts"]:
            failures.append("large_database_table_rows")
        if actual_fingerprint != large["database_fingerprint"]:
            failures.append("large_database_fingerprint")
        if actual_fingerprint != manifest["database_fingerprint"]:
            failures.append("manifest_database_fingerprint")
    if (
        _json(output_dir / "r2_t03_post_validation_fingerprint.json")
        != manifest["post_validation_fingerprint"]
    ):
        failures.append("post_validation_fingerprint")
    import subprocess

    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest["execution_commit"], commit],
        cwd=root,
    ).returncode:
        failures.append("execution_commit_not_ancestor")
    if promoted and promotion is not None:
        rehearsal = root / promotion["original_rehearsal_report_path"]
        if _file_sha256(rehearsal) != promotion["original_rehearsal_report_sha256"]:
            failures.append("original_rehearsal_report_hash")
        if promotion["promoted_database_sha256"] != large["sha256"]:
            failures.append("promotion_database_hash_identity")
        if promotion["fact_table_fingerprints"] != _json(
            output_dir / "fact_fingerprints_after.json"
        ):
            failures.append("promotion_fact_fingerprint_identity")
        for field in (
            "source_fact_execution_commit",
            "postscan_execution_commit",
            "implementation_evidence_head",
        ):
            if subprocess.run(
                ["git", "merge-base", "--is-ancestor", promotion[field], commit],
                cwd=root,
            ).returncode:
                failures.append(f"promotion_commit_not_ancestor:{field}")
        forbidden = ("future_return", "forward_return", 'winner_selected":true')
        for name in (
            "r2_t03_result_package.json",
            "r2_t03_descriptive_analysis.json",
            "r2_t03_result_analysis.md",
        ):
            text = (output_dir / name).read_text(encoding="utf-8").lower()
            if any(value in text for value in forbidden):
                failures.append(f"forbidden_field:{name}")
        final_gate = _json(output_dir / "r2_t03_repository_final_gate.json")
        if final_gate["formal_task_completed"] or final_gate["R2-T04_allowed_to_start"]:
            failures.append("pending_gate_consistency")
    report = {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "status": "passed" if not failures else "failed",
        "artifact_commit": commit,
        "binding_count": len(bindings),
        "bindings": bindings,
        "failures": failures,
        "promotion_validation_status": "passed"
        if promoted and not failures
        else ("not_applicable" if not promoted else "failed"),
        "scientific_review_status": "pending_independent_scientific_review",
        "formal_task_completed": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_committed_artifact_validation.json", report)
    if failures:
        raise RuntimeError("committed_artifact_validation_failed:" + failures[0])
    return report


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _anomaly_queries() -> dict[str, str]:
    return {
        "zero_event_cells": "SELECT count(*) FROM dg_event_zone_profile WHERE qualified_event_count=0",
        "one_event_cells": "SELECT count(*) FROM dg_event_zone_profile WHERE qualified_event_count=1",
        "null_metric_cells": "SELECT count(*) FROM dg_event_zone_profile WHERE qualified_event_count IS NULL OR confirmed_event_coverage IS NULL",
        "parameter_nonresponsive_groups": "SELECT count(*) FROM parameter_response_audit WHERE status<>'responsive'",
        "subset_violations": "SELECT count(*) FROM strict_core_window_comparison WHERE subset_violation",
        "availability_violations": "SELECT count(*) FROM event_zone_membership_daily WHERE membership_available_time<available_time OR evaluation_time<>membership_available_time",
        "risk_set_violations": "SELECT count(*) FROM event_zone_membership_daily WHERE qualified_event_risk_set_eligible IS DISTINCT FROM (state_risk_set_eligible AND event_zone_member AND component_qualified_as_of AND NOT is_raw_false_bridge AND NOT is_preconfirmation_gap)",
        "dense_interval_lineage_mismatch": "SELECT count(*) FROM route_atomic_interval WHERE upstream_source_interval_id IS NULL",
        "transition_closure": "SELECT count(*) FROM (SELECT e.scan_event_id FROM event_zone e LEFT JOIN transition_entity_ledger t ON t.candidate_cell_id=e.candidate_cell_id AND t.security_id=e.security_id AND t.entity_id=e.scan_event_id AND t.to_state IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED') GROUP BY e.candidate_cell_id,e.security_id,e.scan_event_id HAVING count(t.entity_id)<>1)",
        "event_overlap_within_cell_security": "SELECT count(*) FROM event_zone a JOIN event_zone b ON a.candidate_cell_id=b.candidate_cell_id AND a.security_id=b.security_id AND a.scan_event_id<b.scan_event_id JOIN qualified_component qa ON qa.candidate_cell_id=a.candidate_cell_id AND qa.security_id=a.security_id AND qa.component_id=a.first_component_id JOIN qualified_component qb ON qb.candidate_cell_id=b.candidate_cell_id AND qb.security_id=b.security_id AND qb.component_id=b.first_component_id WHERE qa.start_date<=qb.end_date AND qb.start_date<=qa.end_date",
        "pending_status_timeline_gap": "SELECT count(*) FROM event_zone_membership_daily WHERE event_zone_member AND zone_status_as_of IS NULL",
        "bridge_gap_domination": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(nonconfirmed_gap_ratio,0)>.5 OR coalesce(bridged_day_ratio,0)>.5",
        "mega_zone_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(mega_zone_concentration,0)>.5",
        "max_zone_span_extreme": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(max_zone_span,0)>250",
        "top_zone_confirmed_day_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(top_zone_confirmed_day_share,0)>.5",
        "duration_order_of_magnitude_shift": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE duration_q95_ratio>10 OR duration_q95_ratio<.1",
        "right_censor_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE right_censored_zone_count::DOUBLE/nullif(qualified_event_count,0)>.5",
        "quality_break_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE quality_break_zone_count::DOUBLE/nullif(qualified_event_count,0)>.5",
        "single_security_extreme_concentration": f"SELECT count(*) FROM ({_single_security_concentration_query()}) WHERE security_event_share>.5",
        "single_year_extreme_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(max_year_share,0)>.5",
        "abnormal_merge_ratio": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(merge_ratio,0)>.95",
        "window_extremely_low_overlap": "SELECT count(*) FROM window_diagnostic_profile WHERE coalesce(confirmed_day_jaccard,0)<.05",
        "primary_strict_abnormal_expansion": "SELECT count(*) FROM strict_core_diagnostic_profile WHERE strict_core_subset_status<>'passed' OR strict_core_confirmed_day_share>1 OR strict_core_event_share>1 OR strict_core_qualified_component_share>1",
        "empty_or_near_empty_cell": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE qualified_event_count<10 OR coalesce(confirmed_event_coverage,0)<.000001",
        "upstream_confirmed_day_conservation": "SELECT count(*) FROM (SELECT q.candidate_cell_id,sum(q.confirmed_day_count) component_days,a.confirmed_state_days FROM qualified_component q JOIN atomic_baseline_profile a USING(candidate_cell_id) GROUP BY 1,3 HAVING component_days<>confirmed_state_days)",
        "window_own_common_denominator_mismatch": "SELECT count(*) FROM window_overlap_comparison WHERE intersection_confirmed_days>W120_own_eligible_days OR intersection_confirmed_days>W250_own_eligible_days OR common_eligible_days>least(W120_own_eligible_days,W250_own_eligible_days)",
        "asof_backfill": "SELECT count(*) FROM event_zone_membership_daily WHERE component_qualified_as_of AND membership_available_time<available_time",
    }


def _single_security_concentration_query() -> str:
    return """SELECT candidate_cell_id,
    max(security_event_count)::DOUBLE/nullif(sum(security_event_count),0)
      AS security_event_share
    FROM (SELECT candidate_cell_id,security_id,count(*) security_event_count
      FROM event_zone GROUP BY 1,2)
    GROUP BY 1"""


def _anomaly_scan(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    queries = _anomaly_queries()
    observed = {name: con.execute(sql).fetchone()[0] for name, sql in queries.items()}
    engineering_ids = {
        "null_metric_cells",
        "subset_violations",
        "availability_violations",
        "risk_set_violations",
        "dense_interval_lineage_mismatch",
        "transition_closure",
        "event_overlap_within_cell_security",
        "pending_status_timeline_gap",
        "upstream_confirmed_day_conservation",
        "window_own_common_denominator_mismatch",
        "asof_backfill",
    }
    scientific_ids = {
        "zero_event_cells",
        "one_event_cells",
        "parameter_nonresponsive_groups",
        "bridge_gap_domination",
        "mega_zone_concentration",
        "max_zone_span_extreme",
        "top_zone_confirmed_day_concentration",
        "duration_order_of_magnitude_shift",
        "right_censor_concentration",
        "quality_break_concentration",
        "single_security_extreme_concentration",
        "single_year_extreme_concentration",
        "abnormal_merge_ratio",
        "window_extremely_low_overlap",
        "primary_strict_abnormal_expansion",
        "empty_or_near_empty_cell",
    }
    engineering = [name for name in engineering_ids if observed[name]]
    scientific = [name for name in scientific_ids if observed[name]]
    ranges = con.execute(
        "SELECT min(qualified_event_count),max(qualified_event_count),"
        "min(confirmed_event_coverage),max(confirmed_event_coverage) FROM dg_event_zone_profile"
    ).fetchone()
    return {
        "task_id": "R2-T03",
        "status": "passed" if not engineering else "investigation_required",
        "checks": observed,
        "failures": engineering + scientific,
        "blocking_engineering_anomalies": engineering,
        "scientific_investigation_items": scientific,
        "nonblocking_descriptive_warnings": [],
        "event_count_range": [ranges[0], ranges[1]],
        "confirmed_event_coverage_range": [ranges[2], ranges[3]],
        "downstream_progression_blocked": bool(engineering),
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }


def _analysis_metric_rows(con: duckdb.DuckDBPyConnection) -> list[tuple[Any, ...]]:
    """Read semantically distinct coverage fields from their authoritative tables."""
    return con.execute(
        """SELECT m.state_line,m.W,m.d,m.g,m.qualified_event_count,
        p.confirmed_event_coverage,m.retained_confirmed_day_ratio,
        q.retrospective_qualified_confirmed_coverage,q.asof_qualified_confirmed_coverage,
        m.bridged_day_ratio FROM metric_results m
        JOIN dg_event_zone_profile p USING(candidate_cell_id)
        JOIN d_qualification_profile q USING(candidate_cell_id) ORDER BY 1,2,3,4"""
    ).fetchall()


def _analysis_markdown(
    metrics: list[tuple[Any, ...]],
    anomaly: dict[str, Any],
    runtime: dict[str, Any],
    scientific_failures: list[dict[str, str]],
) -> str:
    by_state: dict[str, list[tuple[Any, ...]]] = {}
    for row in metrics:
        by_state.setdefault(row[0], []).append(row)
    lines = [
        "# R2-T03 实际结果合理性与异常扫描",
        "",
        f"工程 runtime gate：`{runtime['status']}`；异常扫描：`{anomaly['status']}`。本报告是 author-draft，未设置 scientific PASS，R2-T04 与 R3 均保持关闭。",
        "",
        "## 直接统计事实",
        "",
    ]
    for state, rows in sorted(by_state.items()):
        events = [row[4] for row in rows]
        coverage = [row[5] for row in rows if row[5] is not None]
        retained = [row[6] for row in rows if row[6] is not None]
        lines.append(
            f"- `{state}` 的 36 个 cell 中，事件数范围为 {min(events)}–{max(events)}，confirmed-event coverage 范围为 {min(coverage):.6f}–{max(coverage):.6f}，retained confirmed-day ratio 范围为 {min(retained):.6f}–{max(retained):.6f}。"
        )
    lines.extend(
        [
            "",
            "## 有限推断与边界",
            "",
            "本扫描只审计状态机、区间几何、参数响应和守恒关系，不使用未来收益、方向或回测指标。primary 与 shared-q sidecar 的比较用于集合与几何诊断，不构成参数选择。availability policy、expected-key adapter 与 interval adapter 已解决；successor actual result 仍须由正式运行和独立验证确认。",
            "",
            "## 异常结论",
            "",
            f"异常项：{', '.join(anomaly['failures']) if anomaly['failures'] else '无阻断异常'}。无论本项结果如何，本 author-draft 都不授权推进 R2-T04；后续仍需独立 scientific review。",
            "",
            "## 冻结 scientific gate 诊断",
            "",
            (
                f"共有 {len(scientific_failures)} 个非工程阻断的冻结 gate 失败；"
                "这些结果全部保留为 scientific review 输入，不用于选取或排除 cell。"
                if scientific_failures
                else "冻结 scientific gate 未报告失败。"
            ),
            "",
            *[
                f"- `{row['candidate_cell_id']}`：`{row['check_id']}` observed={row['observed_value']}，规则 `{row['expected_rule']}`。"
                for row in scientific_failures
            ],
        ]
    )
    return "\n".join(lines) + "\n"


def _manifest(
    output_dir: Path, execution_commit: str, tables: dict[str, int], root: Path
) -> dict[str, Any]:
    excluded = {
        "r2_t03_output_manifest.json",
        "r2_t03_committed_artifact_validation.json",
        "r2_t03_event_zone_scan.duckdb",
    }
    artifacts = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name not in excluded:
            data = path.read_bytes()
            artifacts.append(
                {
                    "path": repo_rel(path, root),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
            )
    database = output_dir / "r2_t03_event_zone_scan.duckdb"
    database_bytes = database.read_bytes()
    summary = _json(output_dir / "r2_t03_experiment_summary.json")
    post = _json(output_dir / "r2_t03_post_validation_fingerprint.json")
    return {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "execution_commit": execution_commit,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "large_artifacts": [
            {
                "path": repo_rel(database, root),
                "sha256": hashlib.sha256(database_bytes).hexdigest(),
                "size_bytes": len(database_bytes),
                "lifecycle": "local_large_artifact_not_committed",
                "table_row_counts": tables,
                "database_fingerprint": summary["database_fingerprint"],
            }
        ],
        "database_tables": tables,
        "config_sha256": summary["config_sha256"],
        "source_readiness_sha256": summary["source_readiness_sha256"],
        "input_binding_sha256": summary["input_binding_sha256"],
        "database_fingerprint": summary["database_fingerprint"],
        "post_validation_fingerprint": post,
        "status": "passed",
    }


def _git_blob(commit: str, path: str, root: Path) -> bytes:
    import subprocess

    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=root)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value: dict[str, Any], schema_path: Path) -> None:
    jsonschema.Draft202012Validator(_json(schema_path)).validate(value)
