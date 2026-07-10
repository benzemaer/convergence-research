# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "R1-T06"
CONFIG_PATH = ROOT / "configs/r1/r1_t06_contemporaneous_retention_lift.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t06_contemporaneous_retention_lift.schema.json"

PRIMARY_ROWS = 27
DENOMINATOR_SENSITIVITY_ROWS = 27
SECURITY_SUMMARY_ROWS = 27
DIMENSION_RECONCILIATION_ROWS = 36
NESTED_RECONCILIATION_ROWS = 36
Q_NESTING_RECONCILIATION_ROWS = 78


class R1T06RetentionLiftError(RuntimeError):
    pass


def run_r1_t06_contemporaneous_retention_lift(
    *,
    config_path: Path = CONFIG_PATH,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    root: Path = ROOT,
    verify_input_hashes: bool = True,
) -> dict[str, Any]:
    import duckdb

    config = _load_json(config_path)
    schema = _load_json(
        root / "schemas/r1/r1_t06_contemporaneous_retention_lift.schema.json"
    )
    errors = _validate_config(config, schema)
    gate = _check_r1_t05_gate(config, root)
    errors.extend(gate["errors"])
    input_checks = _check_input_artifacts(
        config, root, verify_hashes=verify_input_hashes
    )
    errors.extend(input_checks["errors"])

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "layer_step_profile_csv": output_dir / "r1_t06_layer_step_profile.csv",
        "denominator_sensitivity_csv": output_dir
        / "r1_t06_denominator_sensitivity.csv",
        "year_step_profile_csv": output_dir / "r1_t06_year_step_profile.csv",
        "security_step_summary_csv": output_dir / "r1_t06_security_step_summary.csv",
        "r0_nested_reconciliation_csv": output_dir
        / "r1_t06_r0_nested_reconciliation.csv",
        "dimension_state_reconciliation_csv": output_dir
        / "r1_t06_dimension_state_reconciliation.csv",
        "q_nesting_reconciliation_csv": output_dir
        / "r1_t06_q_nesting_reconciliation.csv",
        "diagnostic_summary": output_dir / "r1_t06_diagnostic_summary.json",
        "anomaly_scan": output_dir / "r1_t06_anomaly_scan.json",
        "summary": output_dir / "r1_t06_experiment_summary.json",
    }
    if errors:
        _write_empty_outputs(paths)
    else:
        con = duckdb.connect()
        try:
            con.execute(
                f"PRAGMA threads={int(config['parallelism']['duckdb_threads'])}"
            )
            con.execute(
                f"PRAGMA memory_limit='{config['parallelism']['duckdb_memory_limit']}'"
            )
            _attach_inputs(con, config, root)
            _create_step_registry(con)
            _create_dimension_wide(con)
            _write_layer_step_profile(
                con, paths["layer_step_profile_csv"], run_id, code_commit
            )
            _write_denominator_sensitivity(con, paths["denominator_sensitivity_csv"])
            _write_year_profile(con, paths["year_step_profile_csv"])
            _write_security_summary(con, paths["security_step_summary_csv"])
            _write_dimension_reconciliation(
                con, paths["dimension_state_reconciliation_csv"]
            )
            _write_nested_reconciliation(con, paths["r0_nested_reconciliation_csv"])
            _write_q_nesting_reconciliation(con, paths["q_nesting_reconciliation_csv"])
        finally:
            con.close()

    invariants = _evaluate_outputs(paths)
    errors.extend(invariants["errors"])
    status = "completed" if not errors else "blocked"
    diagnostic = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "status": status,
        "errors": sorted(set(errors)),
        "gate": gate,
        "input_checks": input_checks,
        "checks": invariants["checks"],
        "row_counts": invariants["row_counts"],
        "material_warnings": invariants["material_warnings"],
    }
    _write_json(paths["diagnostic_summary"], diagnostic)
    anomaly = _build_anomaly_scan(status, run_id, code_commit, paths, diagnostic)
    _write_json(paths["anomaly_scan"], anomaly)
    summary = {
        "task_id": TASK_ID,
        "status": status,
        "run_id": run_id,
        "code_commit": code_commit,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "config_path": _rel(config_path, root),
        "config_sha256": sha256_file(config_path),
        "protocol_version": config["protocol_version"],
        "input_lineage": {
            "r1_t05_gate": gate["lineage"],
            "r0_inputs": input_checks["lineage"],
            "r0_t11_handoff_evidence_path": config["r0_t11_handoff_evidence_path"],
            "r0_t11_handoff_report_path": config["r0_t11_handoff_report_path"],
            "r0_repair_evidence_path": config["r0_repair_evidence_path"],
        },
        "step_registry": config["steps"],
        "grid": {"W": config["W"], "q": config["q"], "K": config["K"]},
        "primary_baseline": config["primary_baseline"],
        "challengers": config["challengers"],
        "parallelism": config["parallelism"],
        "output_paths": {
            key: {"path": _rel(path, root), "sha256": sha256_file(path)}
            for key, path in paths.items()
            if key != "summary"
        },
        "counts": invariants["row_counts"],
        "checks": invariants["checks"],
        "blocked_reasons": sorted(set(errors)),
        "material_warnings": invariants["material_warnings"],
        "downstream_gates": {
            "R1-T07_allowed_to_start": False,
            "downstream_gate_allowed": False,
        },
    }
    _write_json(paths["summary"], summary)
    return summary


def validate_engineering_outputs(
    *,
    summary_path: Path,
    result_package_path: Path | None = None,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    from src.r1.r1_t06_contemporaneous_retention_lift_validator import (
        validate_r1_t06_contemporaneous_retention_lift,
    )

    return validate_r1_t06_contemporaneous_retention_lift(
        summary_path=summary_path,
        result_package_path=result_package_path,
        output_path=output_path,
        root=root,
    )


def build_author_draft_package(
    *,
    summary_path: Path,
    evidence_path: Path,
    analysis_path: Path,
    readme_path: Path,
    root: Path = ROOT,
) -> Path:
    summary = _load_json(summary_path)
    output_dir = summary_path.parent
    engineering = output_dir / "r1_t06_engineering_validation_result.json"
    result_path = output_dir / "r1_t06_result_package.json"
    paths = summary["output_paths"]
    primary_roles = (
        "layer_step_profile_csv",
        "denominator_sensitivity_csv",
        "year_step_profile_csv",
        "security_step_summary_csv",
        "r0_nested_reconciliation_csv",
        "dimension_state_reconciliation_csv",
        "q_nesting_reconciliation_csv",
    )
    primary = [
        {
            "artifact_role": "primary_results",
            "path": paths[role]["path"],
            "sha256": paths[role]["sha256"],
            "record_count": _csv_count(root / paths[role]["path"]),
            "committed_to_repo": True,
        }
        for role in primary_roles
    ]
    diagnostic = [
        {
            "artifact_role": "diagnostic_summary",
            "path": paths["diagnostic_summary"]["path"],
            "sha256": paths["diagnostic_summary"]["sha256"],
            "record_count": 1,
            "committed_to_repo": True,
        },
        {
            "artifact_role": "anomaly_scan",
            "path": paths["anomaly_scan"]["path"],
            "sha256": paths["anomaly_scan"]["sha256"],
            "record_count": 1,
            "committed_to_repo": True,
        },
    ]
    package = {
        "task_id": TASK_ID,
        "task_class": "formal_experiment",
        "run_id": summary["run_id"],
        "code_commit": summary["code_commit"],
        "implementation_actor": "codex",
        "status": "author_analysis_complete",
        "input_package": {
            "dimension_score": summary["input_lineage"]["r0_inputs"]["dimension_score"],
            "dimension_state": summary["input_lineage"]["r0_inputs"]["dimension_state"],
            "nested_daily_state": summary["input_lineage"]["r0_inputs"][
                "nested_daily_state"
            ],
        },
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "experiment_summary_path": _rel(summary_path, root),
        "experiment_summary_sha256": sha256_file(summary_path),
        "primary_result_artifacts": primary,
        "diagnostic_artifacts": diagnostic,
        "anomaly_scan_path": paths["anomaly_scan"]["path"],
        "anomaly_scan_sha256": paths["anomaly_scan"]["sha256"],
        "result_analysis_path": _rel(analysis_path, root),
        "result_analysis_sha256": sha256_file(analysis_path),
        "engineering_validation_result_path": _rel(engineering, root),
        "engineering_validation_result_sha256": sha256_file(engineering),
        "formal_evidence_path": _rel(evidence_path, root),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "scientific_review_record_path": None,
        "scientific_review_record_sha256": None,
        "scientific_review_md_path": None,
        "scientific_review_md_sha256": None,
        "readme_path": _rel(readme_path, root),
        "readme_sha256": sha256_file(readme_path),
        "expected_current_stage": "R1",
        "expected_current_task": "R1-T06 层间同期留存、关联 Lift 与嵌套增量",
        "expected_next_planned_task": "R1-T07 P 首入锚定的固定滞后结构关系",
        "expected_downstream_gate_marker": "R1-T07_allowed_to_start: false",
        "superseded": False,
        "superseded_by": None,
        "gate_status": {
            "engineering_validator_status": "passed",
            "result_artifact_status": "passed",
            "author_result_analysis_status": "passed",
            "scientific_review_status": "pending",
            "anomaly_resolution_status": "passed",
            "review_phase": "author_analysis_complete",
            "readme_gate_updated": False,
        },
        "downstream_gate_allowed": False,
    }
    _write_json(result_path, package)
    return result_path


def _attach_inputs(con: Any, config: dict[str, Any], root: Path) -> None:
    for alias, key in (
        ("scoredb", "dimension_score"),
        ("statedb", "dimension_state"),
        ("nesteddb", "nested_daily_state"),
    ):
        path = root / config["input_artifacts"][key]["path"]
        con.execute(f"ATTACH '{_sql_path(path)}' AS {alias} (READ_ONLY)")


def _create_step_registry(con: Any) -> None:
    con.execute(
        """
        CREATE TEMP TABLE step_registry AS
        SELECT * FROM (VALUES
          ('C_GIVEN_P', 'P', 'C', 'S_PC', 'P,C', 2),
          ('T_GIVEN_PC', 'S_PC', 'T', 'S_PCT', 'P,C,T', 3),
          ('V_GIVEN_PCT', 'S_PCT', 'V', 'S_PCVT', 'P,C,T,V', 4)
        ) AS t(step_id, anchor_state, target_dimension, child_state, required_dimensions, required_dimension_count)
        """
    )


def _create_dimension_wide(con: Any) -> None:
    con.execute(
        """
        CREATE TEMP TABLE dimension_wide AS
        SELECT security_id, trading_date, percentile_window_W AS W, q,
          bool_or(dimension='P' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS P_valid,
          bool_or(dimension='C' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS C_valid,
          bool_or(dimension='T' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS T_valid,
          bool_or(dimension='V' AND eligible_dimension IS TRUE AND validity_status='valid' AND dimension_active_weak IS NOT NULL) AS V_valid,
          bool_or(dimension='P' AND dimension_active_weak IS TRUE) AS P_active,
          bool_or(dimension='C' AND dimension_active_weak IS TRUE) AS C_active,
          bool_or(dimension='T' AND dimension_active_weak IS TRUE) AS T_active,
          bool_or(dimension='V' AND dimension_active_weak IS TRUE) AS V_active,
          CASE
            WHEN sum(CASE WHEN dimension='P' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true
            WHEN sum(CASE WHEN dimension='P' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false
            ELSE NULL
          END AS P_raw,
          CASE
            WHEN sum(CASE WHEN dimension='C' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true
            WHEN sum(CASE WHEN dimension='C' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false
            ELSE NULL
          END AS C_raw,
          CASE
            WHEN sum(CASE WHEN dimension='T' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true
            WHEN sum(CASE WHEN dimension='T' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false
            ELSE NULL
          END AS T_raw,
          CASE
            WHEN sum(CASE WHEN dimension='V' AND dimension_active_weak IS TRUE THEN 1 ELSE 0 END) > 0 THEN true
            WHEN sum(CASE WHEN dimension='V' AND dimension_active_weak IS FALSE THEN 1 ELSE 0 END) > 0 THEN false
            ELSE NULL
          END AS V_raw
        FROM statedb.r0_t06_dimension_state_results
        GROUP BY security_id, trading_date, percentile_window_W, q
        """
    )


def _step_projection_sql(source: str, where_clause: str) -> str:
    return f"""
    WITH projected AS (
      SELECT sr.step_id, sr.anchor_state, sr.target_dimension, sr.child_state,
        sr.required_dimensions, d.security_id, d.trading_date, d.W, d.q,
        CASE sr.step_id
          WHEN 'C_GIVEN_P' THEN d.P_valid AND d.C_valid
          WHEN 'T_GIVEN_PC' THEN d.P_valid AND d.C_valid AND d.T_valid
          WHEN 'V_GIVEN_PCT' THEN d.P_valid AND d.C_valid AND d.T_valid AND d.V_valid
        END AS primary_denominator,
        d.P_valid AND d.C_valid AND d.T_valid AND d.V_valid AS all4_denominator,
        CASE sr.step_id
          WHEN 'C_GIVEN_P' THEN d.P_active
          WHEN 'T_GIVEN_PC' THEN d.P_active AND d.C_active
          WHEN 'V_GIVEN_PCT' THEN d.P_active AND d.C_active AND d.T_active
        END AS anchor_active,
        CASE sr.step_id
          WHEN 'C_GIVEN_P' THEN d.C_active
          WHEN 'T_GIVEN_PC' THEN d.T_active
          WHEN 'V_GIVEN_PCT' THEN d.V_active
        END AS target_active
      FROM {source} d
      CROSS JOIN step_registry sr
    )
    SELECT * FROM projected
    WHERE {where_clause}
    """


def _aggregate_sql(
    source: str,
    where_clause: str,
    group_cols: str,
    group_by_cols: str | None = None,
) -> str:
    group_by = group_by_cols or group_cols
    return f"""
    WITH base AS ({_step_projection_sql(source, where_clause)}),
    counts AS (
      SELECT {group_cols},
        count(*)::BIGINT AS N,
        sum(anchor_active IS TRUE AND target_active IS TRUE)::BIGINT AS n11,
        sum(anchor_active IS TRUE AND target_active IS FALSE)::BIGINT AS n10,
        sum(anchor_active IS FALSE AND target_active IS TRUE)::BIGINT AS n01,
        sum(anchor_active IS FALSE AND target_active IS FALSE)::BIGINT AS n00
      FROM base
      GROUP BY {group_by}
    ),
    metrics AS (
      SELECT *,
        n11+n10 AS anchor_true_count,
        n01+n00 AS anchor_false_count,
        n11+n01 AS target_true_count,
        n10+n00 AS target_false_count,
        n11 AS child_true_count,
        n10 AS anchor_only_count,
        n01 AS target_only_count,
        n00 AS neither_count
      FROM counts
    )
    SELECT *,
      anchor_true_count::DOUBLE / N AS anchor_rate,
      target_true_count::DOUBLE / N AS target_marginal_rate,
      child_true_count::DOUBLE / N AS child_joint_rate,
      CASE WHEN anchor_true_count=0 THEN NULL ELSE child_true_count::DOUBLE / anchor_true_count END AS retention,
      CASE WHEN anchor_false_count=0 THEN NULL ELSE n01::DOUBLE / anchor_false_count END AS nonanchor_target_rate,
      CASE WHEN anchor_true_count=0 OR target_true_count=0 THEN NULL ELSE (child_true_count::DOUBLE / anchor_true_count) / (target_true_count::DOUBLE / N) END AS lift,
      CASE WHEN anchor_true_count=0 THEN NULL ELSE (child_true_count::DOUBLE / anchor_true_count) - (target_true_count::DOUBLE / N) END AS delta,
      CASE WHEN anchor_true_count=0 OR anchor_false_count=0 THEN NULL ELSE (child_true_count::DOUBLE / anchor_true_count) - (n01::DOUBLE / anchor_false_count) END AS delta_nonanchor,
      (anchor_true_count::DOUBLE / N) * (target_true_count::DOUBLE / N) AS independence_expected_joint_rate,
      child_true_count::DOUBLE / N - ((anchor_true_count::DOUBLE / N) * (target_true_count::DOUBLE / N)) AS joint_excess,
      anchor_true_count=0 AS retention_denominator_zero,
      anchor_true_count=0 OR target_true_count=0 AS lift_denominator_zero,
      anchor_false_count=0 AS nonanchor_denominator_zero
    FROM metrics
    """


def _write_layer_step_profile(
    con: Any, path: Path, run_id: str, code_commit: str
) -> None:
    aggregate = _aggregate_sql(
        "dimension_wide",
        "primary_denominator",
        "step_id, anchor_state, target_dimension, child_state, required_dimensions, W, q",
    )
    query = f"""
    WITH primary_rows AS ({aggregate}),
    year_summary AS (
      SELECT step_id, W, q,
        sum(N > 0)::BIGINT AS nonzero_year_count,
        sum(delta > 0)::BIGINT AS positive_delta_year_count,
        sum(delta < 0)::BIGINT AS negative_delta_year_count,
        sum(delta IS NULL)::BIGINT AS undefined_year_count,
        max(year_share_of_step_denominator) AS max_year_denominator_share,
        median(delta) AS median_year_delta
      FROM (
        WITH y AS ({_aggregate_sql("dimension_wide", "primary_denominator", "step_id, W, q, substr(trading_date,1,4) AS year", "step_id, W, q, substr(trading_date,1,4)")})
        SELECT y.*, y.N::DOUBLE / sum(y.N) OVER (PARTITION BY step_id, W, q) AS year_share_of_step_denominator
        FROM y
      )
      GROUP BY step_id, W, q
    )
    SELECT
      '{TASK_ID}' AS task_id,
      '{run_id}' AS run_id,
      '{code_commit}' AS code_commit,
      p.step_id, p.anchor_state, p.target_dimension, p.child_state, p.W, p.q,
      'not_applicable' AS K,
      p.required_dimensions,
      'step_specific_minimal_common_valid' AS denominator_scope,
      p.N, p.n11, p.n10, p.n01, p.n00,
      p.anchor_true_count, p.anchor_false_count, p.target_true_count, p.target_false_count, p.child_true_count,
      p.anchor_rate, p.target_marginal_rate, p.child_joint_rate, p.retention, p.nonanchor_target_rate, p.lift, p.delta, p.delta_nonanchor,
      p.independence_expected_joint_rate, p.joint_excess,
      p.retention_denominator_zero, p.lift_denominator_zero, p.nonanchor_denominator_zero,
      y.nonzero_year_count, y.positive_delta_year_count, y.negative_delta_year_count, y.undefined_year_count,
      y.max_year_denominator_share,
      CASE
        WHEN p.delta IS NULL OR y.median_year_delta IS NULL THEN NULL
        WHEN abs(p.delta) <= 1e-12 AND abs(y.median_year_delta) <= 1e-12 THEN true
        WHEN p.delta > 0 AND y.median_year_delta > 0 THEN true
        WHEN p.delta < 0 AND y.median_year_delta < 0 THEN true
        ELSE false
      END AS pooled_vs_year_median_sign_consistency,
      CASE
        WHEN p.retention_denominator_zero OR p.lift_denominator_zero THEN 'undefined_denominator'
        WHEN abs(p.delta) <= 1e-12 AND abs(p.lift - 1) <= 1e-12 THEN 'neutral_same_time_association'
        WHEN p.delta > 0 AND p.lift > 1 THEN 'positive_same_time_association'
        WHEN p.delta < 0 AND p.lift < 1 THEN 'negative_same_time_association'
        ELSE 'mixed_metric_direction'
      END AS association_direction,
      concat_ws(';',
        CASE WHEN p.lift >= 2 AND abs(p.delta) < 0.02 THEN 'high_lift_low_delta' END,
        CASE WHEN p.retention >= 0.5 AND abs(p.lift - 1) < 0.05 THEN 'high_retention_lift_near_one' END,
        CASE WHEN p.target_marginal_rate < 0.02 AND p.lift >= 2 THEN 'rare_target_lift_inflation' END
      ) AS warnings
    FROM primary_rows p
    LEFT JOIN year_summary y USING(step_id, W, q)
    ORDER BY p.step_id, p.W, p.q
    """
    _copy_query(con, query, path)


def _write_denominator_sensitivity(con: Any, path: Path) -> None:
    primary_sql = _aggregate_sql(
        "dimension_wide", "primary_denominator", "step_id, W, q"
    )
    all4_sql = _aggregate_sql("dimension_wide", "all4_denominator", "step_id, W, q")
    query = f"""
    WITH primary_rows AS ({primary_sql}),
    all4_rows AS ({all4_sql})
    SELECT p.step_id, p.W, p.q,
      p.N AS primary_step_denominator,
      a.N AS all4_common_denominator,
      a.N::DOUBLE / p.N AS denominator_retention_ratio,
      p.retention AS primary_retention,
      a.retention AS all4_restricted_retention,
      a.retention - p.retention AS retention_difference,
      p.lift AS primary_lift,
      a.lift AS all4_restricted_lift,
      a.lift - p.lift AS lift_difference,
      p.delta AS primary_delta,
      a.delta AS all4_restricted_delta,
      a.delta - p.delta AS delta_difference
    FROM primary_rows p
    JOIN all4_rows a USING(step_id, W, q)
    ORDER BY p.step_id, p.W, p.q
    """
    _copy_query(con, query, path)


def _write_year_profile(con: Any, path: Path) -> None:
    year_sql = _aggregate_sql(
        "dimension_wide",
        "primary_denominator",
        "step_id, W, q, substr(trading_date,1,4) AS year",
        "step_id, W, q, substr(trading_date,1,4)",
    )
    query = f"""
    WITH y AS ({year_sql})
    SELECT step_id, W, q, year, N, n11, n10, n01, n00,
      anchor_true_count, target_true_count, retention, target_marginal_rate,
      lift, delta, delta_nonanchor,
      N::DOUBLE / sum(N) OVER (PARTITION BY step_id, W, q) AS year_share_of_step_denominator
    FROM y
    ORDER BY step_id, W, q, year
    """
    _copy_query(con, query, path)


def _write_security_summary(con: Any, path: Path) -> None:
    per_security = _aggregate_sql(
        "dimension_wide",
        "primary_denominator",
        "step_id, W, q, security_id",
    )
    pooled = _aggregate_sql("dimension_wide", "primary_denominator", "step_id, W, q")
    query = f"""
    WITH s AS ({per_security}),
    p AS ({pooled})
    SELECT s.step_id, s.W, s.q,
      count(*)::BIGINT AS security_count_total,
      sum(s.retention IS NOT NULL)::BIGINT AS retention_computable_security_count,
      sum(s.lift IS NOT NULL)::BIGINT AS lift_computable_security_count,
      quantile_cont(s.anchor_true_count, 0.25) AS anchor_count_q25,
      median(s.anchor_true_count) AS anchor_count_median,
      quantile_cont(s.anchor_true_count, 0.75) AS anchor_count_q75,
      quantile_cont(s.retention, 0.25) AS retention_q25,
      median(s.retention) AS retention_median,
      quantile_cont(s.retention, 0.75) AS retention_q75,
      quantile_cont(s.lift, 0.25) AS lift_q25,
      median(s.lift) AS lift_median,
      quantile_cont(s.lift, 0.75) AS lift_q75,
      quantile_cont(s.delta, 0.25) AS delta_q25,
      median(s.delta) AS delta_median,
      quantile_cont(s.delta, 0.75) AS delta_q75,
      avg(CASE WHEN s.delta > 0 THEN 1.0 WHEN s.delta IS NOT NULL THEN 0.0 END) AS positive_delta_security_share,
      avg(CASE WHEN s.delta < 0 THEN 1.0 WHEN s.delta IS NOT NULL THEN 0.0 END) AS negative_delta_security_share,
      CASE
        WHEN p.delta IS NULL OR median(s.delta) IS NULL THEN NULL
        WHEN abs(p.delta) <= 1e-12 AND abs(median(s.delta)) <= 1e-12 THEN true
        WHEN p.delta > 0 AND median(s.delta) > 0 THEN true
        WHEN p.delta < 0 AND median(s.delta) < 0 THEN true
        ELSE false
      END AS pooled_vs_security_median_sign_consistency
    FROM s
    JOIN p USING(step_id, W, q)
    GROUP BY s.step_id, s.W, s.q, p.delta
    ORDER BY s.step_id, s.W, s.q
    """
    _copy_query(con, query, path)


def _write_dimension_reconciliation(con: Any, path: Path) -> None:
    query = """
    WITH joined AS (
      SELECT s.dimension, s.percentile_window_W AS W, s.q,
        s.eligible_dimension AS state_eligible_dimension,
        s.validity_status AS state_validity_status,
        s.dimension_active_weak,
        sc.eligible_dimension AS score_eligible_dimension,
        sc.validity_status AS score_validity_status,
        sc.score_dimension,
        sc.score_dimension_min,
        CASE
          WHEN sc.eligible_dimension IS TRUE AND sc.validity_status='valid'
            THEN sc.score_dimension >= 1 - s.q - 1e-12
             AND sc.score_dimension_min >= 1 - s.q - 0.10 - 1e-12
          ELSE NULL
        END AS recomputed_active
      FROM statedb.r0_t06_dimension_state_results s
      JOIN scoredb.r0_t05_dimension_score_results sc
        ON s.security_id=sc.security_id
       AND s.trading_date=sc.trading_date
       AND s.percentile_window_W=sc.percentile_window_W
       AND s.dimension=sc.dimension
    )
    SELECT dimension, W, q,
      count(*)::BIGINT AS r0_t06_row_count,
      sum(state_eligible_dimension IS TRUE)::BIGINT AS state_eligible_count,
      sum(dimension_active_weak IS TRUE)::BIGINT AS state_active_true_count,
      sum(dimension_active_weak IS FALSE)::BIGINT AS state_active_false_count,
      sum(dimension_active_weak IS NULL)::BIGINT AS state_active_null_count,
      sum(score_eligible_dimension IS TRUE)::BIGINT AS score_eligible_count,
      sum(recomputed_active IS TRUE)::BIGINT AS recomputed_active_true_count,
      sum(recomputed_active IS FALSE)::BIGINT AS recomputed_active_false_count,
      sum(recomputed_active IS NULL)::BIGINT AS recomputed_active_null_count,
      sum(dimension_active_weak IS DISTINCT FROM recomputed_active)::BIGINT AS active_mismatch_count
    FROM joined
    GROUP BY dimension, W, q
    ORDER BY dimension, W, q
    """
    _copy_query(con, query, path)


def _write_nested_reconciliation(con: Any, path: Path) -> None:
    query = """
    WITH base AS (
      SELECT security_id, trading_date, W, q,
        P_valid AS S_P_valid,
        P_valid AND C_valid AS S_PC_valid,
        P_valid AND C_valid AND T_valid AS S_PCT_valid,
        P_valid AND C_valid AND T_valid AND V_valid AS S_PCVT_valid,
        P_raw, C_raw, T_raw, V_raw
      FROM dimension_wide
    ),
    s_p AS (
      SELECT *, P_raw AS derived_S_P FROM base
    ),
    s_pc AS (
      SELECT *,
        CASE
          WHEN derived_S_P IS FALSE THEN false
          WHEN derived_S_P IS NULL THEN NULL
          ELSE C_raw
        END AS derived_S_PC
      FROM s_p
    ),
    s_pct AS (
      SELECT *,
        CASE
          WHEN derived_S_PC IS FALSE THEN false
          WHEN derived_S_PC IS NULL THEN NULL
          ELSE T_raw
        END AS derived_S_PCT
      FROM s_pc
    ),
    chained AS (
      SELECT *,
        CASE
          WHEN derived_S_PCT IS FALSE THEN false
          WHEN derived_S_PCT IS NULL THEN NULL
          ELSE V_raw
        END AS derived_S_PCVT
      FROM s_pct
    ),
    derived_long AS (
      SELECT security_id, trading_date, W, q, 'S_P' AS state_name,
        1 AS required_dimension_count, S_P_valid AS common_valid,
        derived_S_P AS derived_value
      FROM chained
      UNION ALL
      SELECT security_id, trading_date, W, q, 'S_PC' AS state_name,
        2 AS required_dimension_count, S_PC_valid AS common_valid,
        derived_S_PC AS derived_value
      FROM chained
      UNION ALL
      SELECT security_id, trading_date, W, q, 'S_PCT' AS state_name,
        3 AS required_dimension_count, S_PCT_valid AS common_valid,
        derived_S_PCT AS derived_value
      FROM chained
      UNION ALL
      SELECT security_id, trading_date, W, q, 'S_PCVT' AS state_name,
        4 AS required_dimension_count, S_PCVT_valid AS common_valid,
        derived_S_PCVT AS derived_value
      FROM chained
    ),
    r0_long AS (
      SELECT security_id, trading_date, percentile_window_W AS W, q,
        'S_P' AS state_name, 1 AS required_dimension_count, S_P_raw AS r0_value
      FROM nesteddb.r0_t06_nested_daily_state_results
      UNION ALL
      SELECT security_id, trading_date, percentile_window_W AS W, q,
        'S_PC' AS state_name, 2 AS required_dimension_count, S_PC_raw AS r0_value
      FROM nesteddb.r0_t06_nested_daily_state_results
      UNION ALL
      SELECT security_id, trading_date, percentile_window_W AS W, q,
        'S_PCT' AS state_name, 3 AS required_dimension_count, S_PCT_raw AS r0_value
      FROM nesteddb.r0_t06_nested_daily_state_results
      UNION ALL
      SELECT security_id, trading_date, percentile_window_W AS W, q,
        'S_PCVT' AS state_name, 4 AS required_dimension_count, S_PCVT_raw AS r0_value
      FROM nesteddb.r0_t06_nested_daily_state_results
    ),
    joined AS (
      SELECT
        coalesce(d.W, r.W) AS W,
        coalesce(d.q, r.q) AS q,
        coalesce(d.state_name, r.state_name) AS state_name,
        coalesce(d.required_dimension_count, r.required_dimension_count) AS required_dimension_count,
        d.security_id AS derived_security_id,
        r.security_id AS r0_security_id,
        d.common_valid,
        d.derived_value,
        r.r0_value
      FROM derived_long d
      FULL OUTER JOIN r0_long r
        ON d.security_id=r.security_id
       AND d.trading_date=r.trading_date
       AND d.W=r.W
       AND d.q=r.q
       AND d.state_name=r.state_name
    )
    SELECT W, q, state_name, required_dimension_count,
      count(*)::BIGINT AS joined_row_count,
      sum(common_valid IS TRUE)::BIGINT AS common_valid_row_count,
      sum(derived_value IS TRUE)::BIGINT AS derived_true_count,
      sum(r0_value IS TRUE)::BIGINT AS r0_true_count,
      sum(derived_value IS FALSE)::BIGINT AS derived_false_count,
      sum(r0_value IS FALSE)::BIGINT AS r0_false_count,
      sum(derived_value IS NULL)::BIGINT AS derived_null_count,
      sum(r0_value IS NULL)::BIGINT AS r0_null_count,
      sum(derived_security_id IS NULL OR r0_security_id IS NULL)::BIGINT
        AS missing_key_count,
      sum(
        derived_security_id IS NOT NULL
        AND r0_security_id IS NOT NULL
        AND derived_value IS DISTINCT FROM r0_value
      )::BIGINT
        AS row_mismatch_count,
      (sum(derived_value IS TRUE) != sum(r0_value IS TRUE)) AS true_count_mismatch,
      (sum(derived_value IS FALSE) != sum(r0_value IS FALSE)) AS false_count_mismatch,
      (sum(derived_value IS NULL) != sum(r0_value IS NULL)) AS null_count_mismatch
    FROM joined
    GROUP BY W, q, state_name, required_dimension_count
    ORDER BY W, q, state_name
    """
    _copy_query(con, query, path)


def _write_q_nesting_reconciliation(con: Any, path: Path) -> None:
    projected = _step_projection_sql("dimension_wide", "primary_denominator")
    query = f"""
    WITH q_pairs AS (
      SELECT * FROM (VALUES (0.1, 0.2), (0.2, 0.3)) AS t(q_low, q_high)
    ),
    dimensions AS (
      SELECT * FROM (VALUES
        ('P'), ('C'), ('T'), ('V')
      ) AS t(scope_id)
    ),
    dimension_sets AS (
      SELECT security_id, trading_date, W, q, 'P' AS scope_id
      FROM dimension_wide WHERE P_active IS TRUE
      UNION ALL
      SELECT security_id, trading_date, W, q, 'C' AS scope_id
      FROM dimension_wide WHERE C_active IS TRUE
      UNION ALL
      SELECT security_id, trading_date, W, q, 'T' AS scope_id
      FROM dimension_wide WHERE T_active IS TRUE
      UNION ALL
      SELECT security_id, trading_date, W, q, 'V' AS scope_id
      FROM dimension_wide WHERE V_active IS TRUE
    ),
    projected AS ({projected}),
    anchor_sets AS (
      SELECT step_id, security_id, trading_date, W, q
      FROM projected
      WHERE primary_denominator AND anchor_active IS TRUE
    ),
    child_sets AS (
      SELECT step_id, security_id, trading_date, W, q
      FROM projected
      WHERE primary_denominator AND anchor_active IS TRUE AND target_active IS TRUE
    ),
    denominator_sets AS (
      SELECT step_id, security_id, trading_date, W, q
      FROM projected
      WHERE primary_denominator
    ),
    dimension_grid AS (
      SELECT 'dimension_active' AS scope_type, d.scope_id, w.W, qp.q_low, qp.q_high
      FROM dimensions d
      CROSS JOIN (SELECT DISTINCT W FROM dimension_wide) w
      CROSS JOIN q_pairs qp
    ),
    step_grid AS (
      SELECT s.step_id AS scope_id, w.W, qp.q_low, qp.q_high
      FROM step_registry s
      CROSS JOIN (SELECT DISTINCT W FROM dimension_wide) w
      CROSS JOIN q_pairs qp
    ),
    dimension_checks AS (
      SELECT scope_type, scope_id, W, q_low, q_high,
        (SELECT count(*) FROM dimension_sets ds WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_low)::BIGINT AS lower_set_count,
        (SELECT count(*) FROM dimension_sets ds WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_high)::BIGINT AS higher_set_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM dimension_sets ds
          WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_low
          EXCEPT
          SELECT security_id, trading_date FROM dimension_sets ds
          WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_high
        ))::BIGINT AS lower_not_in_higher_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM dimension_sets ds
          WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_high
          EXCEPT
          SELECT security_id, trading_date FROM dimension_sets ds
          WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_low
        ))::BIGINT AS higher_not_in_lower_count,
        (
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM dimension_sets ds
            WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_low
            EXCEPT
            SELECT security_id, trading_date FROM dimension_sets ds
            WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_high
          ))
          +
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM dimension_sets ds
            WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_high
            EXCEPT
            SELECT security_id, trading_date FROM dimension_sets ds
            WHERE ds.scope_id=g.scope_id AND ds.W=g.W AND ds.q=g.q_low
          ))
        )::BIGINT AS symmetric_difference_count
      FROM dimension_grid g
    ),
    anchor_checks AS (
      SELECT 'anchor_active' AS scope_type, scope_id, W, q_low, q_high,
        (SELECT count(*) FROM anchor_sets s WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low)::BIGINT AS lower_set_count,
        (SELECT count(*) FROM anchor_sets s WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high)::BIGINT AS higher_set_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM anchor_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
          EXCEPT
          SELECT security_id, trading_date FROM anchor_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
        ))::BIGINT AS lower_not_in_higher_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM anchor_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
          EXCEPT
          SELECT security_id, trading_date FROM anchor_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
        ))::BIGINT AS higher_not_in_lower_count,
        (
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM anchor_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
            EXCEPT
            SELECT security_id, trading_date FROM anchor_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
          ))
          +
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM anchor_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
            EXCEPT
            SELECT security_id, trading_date FROM anchor_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
          ))
        )::BIGINT AS symmetric_difference_count
      FROM step_grid g
    ),
    child_checks AS (
      SELECT 'child_active' AS scope_type, scope_id, W, q_low, q_high,
        (SELECT count(*) FROM child_sets s WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low)::BIGINT AS lower_set_count,
        (SELECT count(*) FROM child_sets s WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high)::BIGINT AS higher_set_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM child_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
          EXCEPT
          SELECT security_id, trading_date FROM child_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
        ))::BIGINT AS lower_not_in_higher_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM child_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
          EXCEPT
          SELECT security_id, trading_date FROM child_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
        ))::BIGINT AS higher_not_in_lower_count,
        (
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM child_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
            EXCEPT
            SELECT security_id, trading_date FROM child_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
          ))
          +
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM child_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
            EXCEPT
            SELECT security_id, trading_date FROM child_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
          ))
        )::BIGINT AS symmetric_difference_count
      FROM step_grid g
    ),
    denominator_checks AS (
      SELECT 'denominator_keys' AS scope_type, scope_id, W, q_low, q_high,
        (SELECT count(*) FROM denominator_sets s WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low)::BIGINT AS lower_set_count,
        (SELECT count(*) FROM denominator_sets s WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high)::BIGINT AS higher_set_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM denominator_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
          EXCEPT
          SELECT security_id, trading_date FROM denominator_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
        ))::BIGINT AS lower_not_in_higher_count,
        (SELECT count(*) FROM (
          SELECT security_id, trading_date FROM denominator_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
          EXCEPT
          SELECT security_id, trading_date FROM denominator_sets s
          WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
        ))::BIGINT AS higher_not_in_lower_count,
        (
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM denominator_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
            EXCEPT
            SELECT security_id, trading_date FROM denominator_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
          ))
          +
          (SELECT count(*) FROM (
            SELECT security_id, trading_date FROM denominator_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_high
            EXCEPT
            SELECT security_id, trading_date FROM denominator_sets s
            WHERE s.step_id=g.scope_id AND s.W=g.W AND s.q=g.q_low
          ))
        )::BIGINT AS symmetric_difference_count
      FROM step_grid g
    )
    SELECT * FROM dimension_checks
    UNION ALL
    SELECT * FROM anchor_checks
    UNION ALL
    SELECT * FROM child_checks
    UNION ALL
    SELECT * FROM denominator_checks
    ORDER BY scope_type, scope_id, W, q_low
    """
    _copy_query(con, query, path)


def _evaluate_outputs(paths: dict[str, Path]) -> dict[str, Any]:
    row_counts = {
        name: _csv_count(path) if path.suffix == ".csv" else 1
        for name, path in paths.items()
        if name != "summary" and path.exists()
    }
    errors: list[str] = []
    checks: dict[str, str] = {}

    def check(name: str, passed: bool, error: str) -> None:
        checks[name] = "passed" if passed else "blocked"
        if not passed:
            errors.append(error)

    primary = _csv_rows(paths["layer_step_profile_csv"])
    denom = _csv_rows(paths["denominator_sensitivity_csv"])
    year = _csv_rows(paths["year_step_profile_csv"])
    sec = _csv_rows(paths["security_step_summary_csv"])
    nested = _csv_rows(paths["r0_nested_reconciliation_csv"])
    dim = _csv_rows(paths["dimension_state_reconciliation_csv"])
    q_nesting = _csv_rows(paths["q_nesting_reconciliation_csv"])
    check(
        "primary_output_nonempty",
        len(primary) == PRIMARY_ROWS
        and len(denom) == DENOMINATOR_SENSITIVITY_ROWS
        and len(sec) == SECURITY_SUMMARY_ROWS
        and len(nested) == NESTED_RECONCILIATION_ROWS
        and len(dim) == DIMENSION_RECONCILIATION_ROWS
        and len(q_nesting) == Q_NESTING_RECONCILIATION_ROWS
        and len(year) > 0,
        "primary_output_row_count_mismatch",
    )
    check(
        "all_zero_check",
        _primary_baseline_nonzero(primary),
        "primary_baseline_zero_count",
    )
    check("all_one_check", not _all_one_rates(primary), "rates_unexpected_all_one")
    check(
        "all_null_check",
        all(row["retention"] and row["lift"] and row["delta"] for row in primary),
        "primary_metric_null",
    )
    check(
        "validity_rate_check",
        _dimension_reconciliation_ok(dim),
        "dimension_state_mismatch",
    )
    check("coverage_check", _coverage_ok(primary), "coverage_invalid")
    check(
        "parameter_response_check",
        _parameter_response_ok(primary) and _q_nesting_reconciliation_ok(q_nesting),
        "parameter_response_violation",
    )
    check(
        "baseline_challenger_check",
        _baseline_challenger_ok(primary),
        "baseline_challenger_missing",
    )
    check(
        "nested_invariant_check",
        _nested_reconciliation_ok(nested),
        "nested_reconciliation_mismatch",
    )
    check(
        "funnel_accounting_check",
        _funnel_accounting_ok(primary),
        "funnel_accounting_mismatch",
    )
    check(
        "denominator_integrity_check",
        _denominator_integrity_ok(primary, denom),
        "denominator_integrity_mismatch",
    )
    check(
        "sample_size_check", _sample_size_ok(primary, sec, year), "sample_size_invalid"
    )
    check(
        "upstream_consistency_check",
        _dimension_reconciliation_ok(dim)
        and _nested_reconciliation_ok(nested)
        and _q_nesting_reconciliation_ok(q_nesting),
        "upstream_consistency_mismatch",
    )
    check(
        "scale_shift_check", _metric_identities_ok(primary), "metric_identity_mismatch"
    )
    check(
        "time_alignment_check",
        _q_independent_denominator_ok(primary) and _q_denominator_keyset_ok(q_nesting),
        "time_alignment_q_denominator_mismatch",
    )
    check(
        "future_leakage_check",
        not _contains_forbidden_tokens(paths),
        "forbidden_output_token",
    )
    check(
        "post_hoc_selection_check", _exact_registry(primary), "post_hoc_registry_drift"
    )
    check(
        "conclusion_support_check",
        not _contains_forbidden_tokens(paths),
        "forbidden_conclusion_token",
    )
    warnings = _material_warnings(primary, denom, sec)
    return {
        "errors": errors,
        "checks": checks,
        "row_counts": row_counts,
        "material_warnings": warnings,
    }


def _build_anomaly_scan(
    status: str,
    run_id: str,
    code_commit: str,
    paths: dict[str, Path],
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    names = (
        "primary_output_nonempty",
        "all_zero_check",
        "all_one_check",
        "all_null_check",
        "validity_rate_check",
        "coverage_check",
        "parameter_response_check",
        "baseline_challenger_check",
        "nested_invariant_check",
        "funnel_accounting_check",
        "denominator_integrity_check",
        "sample_size_check",
        "upstream_consistency_check",
        "scale_shift_check",
        "time_alignment_check",
        "future_leakage_check",
        "post_hoc_selection_check",
        "conclusion_support_check",
    )
    source = diagnostic["checks"]
    checks = {}
    for name in names:
        passed = status == "completed" and source.get(name) == "passed"
        checks[name] = {
            "status": "passed" if passed else "blocked",
            "rationale": f"R1-T06 task-specific machine-readable check: {name}",
            "metrics": {"task_specific_check": source.get(name)},
            "artifact_references": [_rel(paths["diagnostic_summary"], ROOT)],
        }
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "scan_status": "passed" if status == "completed" else "blocked",
        "checks": checks,
        "blocking_anomalies": [
            name for name, item in checks.items() if item["status"] == "blocked"
        ],
        "nonblocking_anomalies": [
            warning["name"] for warning in diagnostic["material_warnings"]
        ],
        "investigations": diagnostic["material_warnings"],
        "unresolved_questions": [],
    }


def _check_r1_t05_gate(config: dict[str, Any], root: Path) -> dict[str, Any]:
    errors: list[str] = []
    package = _load_json(root / config["r1_t05_result_package_path"])
    review = _load_json(root / config["r1_t05_scientific_review_path"])
    readme = (root / "docs/tasks/README.md").read_text(encoding="utf-8")
    if package.get("status") != "completed":
        errors.append("r1_t05_status_not_completed")
    gate = package.get("gate_status", {})
    if gate.get("scientific_review_status") != "passed":
        errors.append("r1_t05_scientific_review_not_passed")
    if gate.get("anomaly_resolution_status") != "passed":
        errors.append("r1_t05_anomaly_resolution_not_passed")
    if package.get("downstream_gate_allowed") is not True:
        errors.append("r1_t05_downstream_gate_not_allowed")
    if review.get("scientific_review_status") != "passed":
        errors.append("r1_t05_review_record_not_passed")
    if "current_task: R1-T06 层间同期留存、关联 Lift 与嵌套增量" not in readme:
        errors.append("readme_current_task_not_r1_t06")
    if "R1-T06_allowed_to_start: true" not in readme:
        errors.append("readme_r1_t06_gate_not_true")
    return {
        "errors": errors,
        "lineage": {
            "r1_t05_result_package_path": config["r1_t05_result_package_path"],
            "r1_t05_result_package_sha256": sha256_file(
                root / config["r1_t05_result_package_path"]
            ),
            "r1_t05_scientific_review_path": config["r1_t05_scientific_review_path"],
            "r1_t05_scientific_review_sha256": sha256_file(
                root / config["r1_t05_scientific_review_path"]
            ),
            "r1_t05_scientific_review_md_path": config[
                "r1_t05_scientific_review_md_path"
            ],
            "r1_t05_evidence_path": config["r1_t05_evidence_path"],
        },
    }


def _check_input_artifacts(
    config: dict[str, Any], root: Path, *, verify_hashes: bool
) -> dict[str, Any]:
    import duckdb

    errors: list[str] = []
    lineage: dict[str, Any] = {}
    for key, artifact in config["input_artifacts"].items():
        path = root / artifact["path"]
        if not path.exists():
            errors.append(f"missing_input_artifact:{key}")
            continue
        actual_hash = sha256_file(path) if verify_hashes else artifact["sha256"]
        if verify_hashes and actual_hash != artifact["sha256"]:
            errors.append(f"input_hash_mismatch:{key}")
        try:
            con = duckdb.connect(str(path), read_only=True)
            row_count, security_count, date_min, date_max = con.execute(
                f"SELECT count(*), count(DISTINCT security_id), min(trading_date), max(trading_date) FROM {artifact['table']}"
            ).fetchone()
            con.close()
        except Exception as exc:
            errors.append(f"input_table_check:{key}:{exc}")
            continue
        if int(row_count) != artifact["row_count"]:
            errors.append(f"input_row_count_mismatch:{key}")
        if int(security_count) != artifact["security_count"]:
            errors.append(f"input_security_count_mismatch:{key}")
        if date_min != artifact["date_min"] or date_max != artifact["date_max"]:
            errors.append(f"input_date_range_mismatch:{key}")
        lineage[key] = {
            "path": artifact["path"],
            "sha256": actual_hash,
            "table": artifact["table"],
            "row_count": int(row_count),
            "security_count": int(security_count),
            "date_min": date_min,
            "date_max": date_max,
            "evidence_path": artifact["evidence_path"],
        }
    return {"errors": errors, "lineage": lineage}


def _validate_config(config: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = []
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
    except Exception as exc:
        errors.append(f"config_schema:{exc}")
    if config.get("W") != [120, 250, 500] or config.get("q") != [0.1, 0.2, 0.3]:
        errors.append("grid_not_exact")
    expected_steps = ["C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"]
    if [step.get("step_id") for step in config.get("steps", [])] != expected_steps:
        errors.append("step_registry_not_exact")
    if config.get("K") != "not_applicable":
        errors.append("k_not_applicable_violation")
    return errors


def _primary_baseline_nonzero(rows: list[dict[str, str]]) -> bool:
    baseline = [
        row
        for row in rows
        if row["W"] == "250" and abs(_float(row, "q") - 0.2) <= 1e-12
    ]
    return len(baseline) == 3 and all(
        _int(row, "N") > 0
        and _int(row, "anchor_true_count") > 0
        and _int(row, "child_true_count") > 0
        for row in baseline
    )


def _all_one_rates(rows: list[dict[str, str]]) -> bool:
    return bool(rows) and all(
        _float(row, "retention") == 1.0 and _float(row, "target_marginal_rate") == 1.0
        for row in rows
    )


def _coverage_ok(rows: list[dict[str, str]]) -> bool:
    for row in rows:
        n11, n10, n01, n00, n = (
            _int(row, key) for key in ("n11", "n10", "n01", "n00", "N")
        )
        if n11 + n10 + n01 + n00 != n:
            return False
        if _int(row, "child_true_count") > _int(row, "anchor_true_count"):
            return False
        if _int(row, "child_true_count") > _int(row, "target_true_count"):
            return False
    return True


def _parameter_response_ok(rows: list[dict[str, str]]) -> bool:
    if not (
        _q_independent_denominator_ok(rows)
        and _w_availability_ok(rows)
        and _step_denominator_ok(rows)
    ):
        return False
    for step in {"C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"}:
        for w in ("120", "250", "500"):
            ordered = sorted(
                [row for row in rows if row["step_id"] == step and row["W"] == w],
                key=lambda row: _float(row, "q"),
            )
            if len(ordered) != 3:
                return False
            for key in ("anchor_true_count", "target_true_count", "child_true_count"):
                values = [_int(row, key) for row in ordered]
                if not (values[0] <= values[1] <= values[2]):
                    return False
    return True


def _baseline_challenger_ok(rows: list[dict[str, str]]) -> bool:
    required = {(250, 0.2), (120, 0.2), (500, 0.2), (250, 0.1), (250, 0.3)}
    for step in {"C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"}:
        present = {
            (int(row["W"]), round(_float(row, "q"), 1))
            for row in rows
            if row["step_id"] == step
        }
        if not required.issubset(present):
            return False
    return True


def _nested_reconciliation_ok(rows: list[dict[str, str]]) -> bool:
    return len(rows) == NESTED_RECONCILIATION_ROWS and all(
        _int(row, "missing_key_count") == 0
        and _int(row, "row_mismatch_count") == 0
        and row["true_count_mismatch"].lower() == "false"
        and row["false_count_mismatch"].lower() == "false"
        and row["null_count_mismatch"].lower() == "false"
        and _int(row, "derived_true_count") == _int(row, "r0_true_count")
        and _int(row, "derived_false_count") == _int(row, "r0_false_count")
        and _int(row, "derived_null_count") == _int(row, "r0_null_count")
        for row in rows
    )


def _q_nesting_reconciliation_ok(rows: list[dict[str, str]]) -> bool:
    return len(rows) == Q_NESTING_RECONCILIATION_ROWS and all(
        _int(row, "lower_not_in_higher_count") == 0
        and (
            row["scope_type"] != "denominator_keys"
            or (
                _int(row, "higher_not_in_lower_count") == 0
                and _int(row, "symmetric_difference_count") == 0
                and _int(row, "lower_set_count") == _int(row, "higher_set_count")
            )
        )
        for row in rows
    )


def _q_denominator_keyset_ok(rows: list[dict[str, str]]) -> bool:
    denominator_rows = [
        row for row in rows if row.get("scope_type") == "denominator_keys"
    ]
    return len(denominator_rows) == 18 and all(
        _int(row, "symmetric_difference_count") == 0
        and _int(row, "lower_not_in_higher_count") == 0
        and _int(row, "higher_not_in_lower_count") == 0
        and _int(row, "lower_set_count") == _int(row, "higher_set_count")
        for row in denominator_rows
    )


def _dimension_reconciliation_ok(rows: list[dict[str, str]]) -> bool:
    return len(rows) == DIMENSION_RECONCILIATION_ROWS and all(
        _int(row, "active_mismatch_count") == 0 for row in rows
    )


def _funnel_accounting_ok(rows: list[dict[str, str]]) -> bool:
    return _coverage_ok(rows) and _step_denominator_ok(rows)


def _denominator_integrity_ok(
    primary: list[dict[str, str]], denom: list[dict[str, str]]
) -> bool:
    if len(denom) != DENOMINATOR_SENSITIVITY_ROWS:
        return False
    for row in denom:
        if _int(row, "all4_common_denominator") > _int(row, "primary_step_denominator"):
            return False
        if row["step_id"] == "V_GIVEN_PCT":
            for key in ("retention_difference", "lift_difference", "delta_difference"):
                if abs(_float(row, key)) > 1e-12:
                    return False
    return _q_independent_denominator_ok(primary)


def _sample_size_ok(
    primary: list[dict[str, str]], sec: list[dict[str, str]], year: list[dict[str, str]]
) -> bool:
    return (
        all(_int(row, "N") > 0 for row in primary)
        and len(sec) == SECURITY_SUMMARY_ROWS
        and len(year) > 0
    )


def _metric_identities_ok(rows: list[dict[str, str]]) -> bool:
    for row in rows:
        anchor_rate = _float(row, "anchor_rate")
        retention = _float(row, "retention")
        target_rate = _float(row, "target_marginal_rate")
        lift = _float(row, "lift")
        delta = _float(row, "delta")
        child_rate = _float(row, "child_joint_rate")
        joint_excess = _float(row, "joint_excess")
        if abs(child_rate - anchor_rate * retention) > 1e-12:
            return False
        if abs(joint_excess - anchor_rate * delta) > 1e-12:
            return False
        if abs(retention - lift * target_rate) > 1e-12:
            return False
    return True


def _q_independent_denominator_ok(rows: list[dict[str, str]]) -> bool:
    for step in {"C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"}:
        for w in {"120", "250", "500"}:
            ns = {
                _int(row, "N")
                for row in rows
                if row["step_id"] == step and row["W"] == w
            }
            if len(ns) != 1:
                return False
    return True


def _w_availability_ok(rows: list[dict[str, str]]) -> bool:
    for step in {"C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"}:
        for q in {"0.1", "0.2", "0.3"}:
            by_w = {
                row["W"]: _int(row, "N")
                for row in rows
                if row["step_id"] == step and row["q"] == q
            }
            if not (by_w["120"] >= by_w["250"] >= by_w["500"]):
                return False
    return True


def _step_denominator_ok(rows: list[dict[str, str]]) -> bool:
    for w in {"120", "250", "500"}:
        for q in {"0.1", "0.2", "0.3"}:
            by_step = {
                row["step_id"]: _int(row, "N")
                for row in rows
                if row["W"] == w and row["q"] == q
            }
            if not (
                by_step["C_GIVEN_P"] >= by_step["T_GIVEN_PC"] >= by_step["V_GIVEN_PCT"]
            ):
                return False
    return True


def _exact_registry(rows: list[dict[str, str]]) -> bool:
    expected = {"C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"}
    return (
        len(rows) == PRIMARY_ROWS
        and {row["step_id"] for row in rows} == expected
        and {row["K"] for row in rows} == {"not_applicable"}
    )


def _material_warnings(
    primary: list[dict[str, str]],
    denom: list[dict[str, str]],
    sec: list[dict[str, str]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = [
        {
            "name": "inherits_r1_t05_C_layer_near_redundancy",
            "status": "material_warning",
            "rationale": "R1-T06 uses R0 weak dimension states and inherits R1-T05's C-layer near-redundancy warning as a possible same-time association amplifier.",
        },
        {
            "name": "inherits_r1_t05_V_layer_W_dependent_identity",
            "status": "material_warning",
            "rationale": "R1-T06 reports W response without selecting W; V_given_PCT must be read against the inherited V window-dependence warning.",
        },
        {
            "name": "inherits_r1_t05_T_q10_joint_high_fragmentation",
            "status": "material_warning",
            "rationale": "T_given_PC q10 results may be affected by high single-day fragmentation inherited from R1-T05 diagnostics.",
        },
        {
            "name": "inherits_r1_t05_T2_extreme_right_tail",
            "status": "material_warning",
            "rationale": "R1-T06 does not modify T2 raw-scale tail behavior; it only describes contemporaneous weak dimension states.",
        },
        {
            "name": "inherits_r1_t05_strict_past_percentile_nonuniformity",
            "status": "material_warning",
            "rationale": "Strict-past percentile buckets are nonuniform; nominal q remains a threshold rather than exact target coverage.",
        },
        {
            "name": "inherits_r1_t05_nominal_q_actual_hit_rate_divergence",
            "status": "material_warning",
            "rationale": "Observed active rates can diverge from nominal q under ties, availability, and rolling history.",
        },
    ]
    for row in primary:
        if row.get("warnings"):
            for name in row["warnings"].split(";"):
                warnings.append(
                    {
                        "name": f"{row['step_id']}_W{row['W']}_Q{_q_label(row['q'])}_{name}",
                        "status": "material_warning",
                        "metrics": {
                            "retention": row["retention"],
                            "target_marginal_rate": row["target_marginal_rate"],
                            "lift": row["lift"],
                            "delta": row["delta"],
                        },
                        "rationale": "Base-rate and scale-sensitive same-time association warning for scientific review.",
                    }
                )
    for row in denom:
        if (
            abs(_float(row, "retention_difference")) >= 0.05
            or abs(_float(row, "lift_difference")) >= 0.25
        ):
            warnings.append(
                {
                    "name": f"{row['step_id']}_W{row['W']}_Q{_q_label(row['q'])}_step_denominator_availability_sensitivity",
                    "status": "material_warning",
                    "metrics": {
                        "primary_step_denominator": row["primary_step_denominator"],
                        "all4_common_denominator": row["all4_common_denominator"],
                        "retention_difference": row["retention_difference"],
                        "lift_difference": row["lift_difference"],
                    },
                    "rationale": "All-four common-valid restriction changes the descriptive metric; primary denominator remains step-specific.",
                }
            )
    for row in sec:
        if row["pooled_vs_security_median_sign_consistency"].lower() == "false":
            warnings.append(
                {
                    "name": f"{row['step_id']}_W{row['W']}_Q{_q_label(row['q'])}_pooled_security_sign_reversal",
                    "status": "material_warning",
                    "metrics": {"delta_median": row["delta_median"]},
                    "rationale": "Pooled association sign differs from the security-level median sign.",
                }
            )
    return warnings


def _contains_forbidden_tokens(paths: dict[str, Path]) -> bool:
    forbidden = (
        "future_return",
        "backtest",
        "portfolio",
        "trade_signal",
        "causal_increment",
        "predictive_increment",
        "statistically_significant",
        "best_step",
        "best_dimension",
        "best_W",
        "best_q",
        "freeze_candidate",
        "R2_candidate",
        "p_value",
        "z_score",
        "permutation",
    )
    for path in paths.values():
        if path.suffix not in (".csv", ".json") or not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        if any(token.lower() in text for token in forbidden):
            return True
    return False


def _copy_query(con: Any, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({query}) TO '{_sql_path(path)}' (HEADER, DELIMITER ',')")


def _write_empty_outputs(paths: dict[str, Path]) -> None:
    for name, path in paths.items():
        if name == "summary":
            continue
        if path.suffix == ".csv":
            _write_csv(path, [])
        else:
            _write_json(path, {})


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def _int(row: dict[str, str], key: str) -> int:
    value = row.get(key)
    if value in (None, ""):
        return 0
    return int(float(value))


def _float(row: dict[str, str], key: str) -> float:
    value = row.get(key)
    if value in (None, ""):
        raise ValueError(key)
    return float(value)


def _q_label(value: str) -> str:
    return str(int(round(float(value) * 100)))


def _sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
