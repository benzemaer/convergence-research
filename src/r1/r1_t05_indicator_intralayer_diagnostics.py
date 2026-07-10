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
TASK_ID = "R1-T05"
CONFIG_PATH = ROOT / "configs/r1/r1_t05_indicator_intralayer_diagnostics.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t05_indicator_intralayer_diagnostics.schema.json"

RAW_ROWS = 8
SCORE_ROWS = 24
HIT_ROWS = 72
PERCENTILE_BUCKET_ROWS = 240
CORRELATION_ROWS = 12
THRESHOLD_ROWS = 36
DIAGNOSTIC_ROWS = 12
RECONCILIATION_ROWS = 72


class R1T05DiagnosticsError(RuntimeError):
    pass


def run_r1_t05_indicator_intralayer_diagnostics(
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
        root / "schemas/r1/r1_t05_indicator_intralayer_diagnostics.schema.json"
    )
    errors = _validate_config(config, schema)
    gate = _check_r1_t04_gate(config, root)
    errors.extend(gate["errors"])
    input_checks = _check_input_artifacts(
        config, root, verify_hashes=verify_input_hashes
    )
    errors.extend(input_checks["errors"])

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "indicator_raw_distribution_csv": output_dir
        / "r1_t05_indicator_raw_distribution.csv",
        "indicator_score_distribution_csv": output_dir
        / "r1_t05_indicator_score_distribution.csv",
        "indicator_percentile_bucket_distribution_csv": output_dir
        / "r1_t05_indicator_percentile_bucket_distribution.csv",
        "indicator_hit_duration_csv": output_dir / "r1_t05_indicator_hit_duration.csv",
        "intralayer_correlation_csv": output_dir / "r1_t05_intralayer_correlation.csv",
        "intralayer_threshold_structure_csv": output_dir
        / "r1_t05_intralayer_threshold_structure.csv",
        "intralayer_diagnostic_summary_csv": output_dir
        / "r1_t05_intralayer_diagnostic_summary.csv",
        "validity_reason_profile_csv": output_dir
        / "r1_t05_validity_reason_profile.csv",
        "r0_t06_reconciliation_csv": output_dir / "r1_t05_r0_t06_reconciliation.csv",
        "diagnostic_summary": output_dir / "r1_t05_diagnostic_summary.json",
        "anomaly_scan": output_dir / "r1_t05_anomaly_scan.json",
        "summary": output_dir / "r1_t05_experiment_summary.json",
    }
    if errors:
        _write_empty_outputs(paths)
    else:
        con = duckdb.connect()
        try:
            con.execute("PRAGMA threads=1")
            con.execute("PRAGMA memory_limit='2GB'")
            _attach_inputs(con, config, root)
            _create_registry_tables(con, config)
            _write_raw_distribution(con, paths["indicator_raw_distribution_csv"])
            _write_score_distribution(con, paths["indicator_score_distribution_csv"])
            _write_percentile_bucket_distribution(
                con, paths["indicator_percentile_bucket_distribution_csv"]
            )
            _write_hit_duration(con, paths["indicator_hit_duration_csv"])
            _write_intralayer_correlation(con, paths["intralayer_correlation_csv"])
            _write_threshold_structure(con, paths["intralayer_threshold_structure_csv"])
            _write_diagnostic_summary(con, paths["intralayer_diagnostic_summary_csv"])
            _write_reason_profile(con, paths["validity_reason_profile_csv"])
            _write_reconciliation(con, paths["r0_t06_reconciliation_csv"])
        finally:
            con.close()

    invariants = _evaluate_outputs(paths, root)
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
            "r1_t04_gate": gate["lineage"],
            "r0_inputs": input_checks["lineage"],
            "r0_t11_handoff_evidence_path": config["r0_t11_handoff_evidence_path"],
            "r0_t11_handoff_report_path": config["r0_t11_handoff_report_path"],
            "r0_repair_evidence_path": config["r0_repair_evidence_path"],
        },
        "indicator_registry": config["indicators"],
        "layer_pairs": config["layer_pairs"],
        "grid": {"W": config["W"], "q": config["q"], "K": config["K"]},
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
            "R1-T06_allowed_to_start": False,
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
    from src.r1.r1_t05_indicator_intralayer_diagnostics_validator import (
        validate_r1_t05_indicator_intralayer_diagnostics,
    )

    return validate_r1_t05_indicator_intralayer_diagnostics(
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
    engineering = output_dir / "r1_t05_engineering_validation_result.json"
    result_path = output_dir / "r1_t05_result_package.json"
    paths = summary["output_paths"]
    primary_roles = (
        "indicator_raw_distribution_csv",
        "indicator_score_distribution_csv",
        "indicator_percentile_bucket_distribution_csv",
        "indicator_hit_duration_csv",
        "intralayer_correlation_csv",
        "intralayer_threshold_structure_csv",
        "intralayer_diagnostic_summary_csv",
        "validity_reason_profile_csv",
        "r0_t06_reconciliation_csv",
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
            "raw_metric": summary["input_lineage"]["r0_inputs"]["raw_metric"],
            "indicator_score": summary["input_lineage"]["r0_inputs"]["indicator_score"],
            "indicator_state": summary["input_lineage"]["r0_inputs"]["indicator_state"],
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
        "expected_current_task": "R1-T05 单指标诊断与层内互补性分析",
        "expected_next_planned_task": "R1-T06 层间同期留存、关联 Lift 与嵌套增量",
        "expected_downstream_gate_marker": "R1-T06_allowed_to_start: false",
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
        ("rawdb", "raw_metric"),
        ("scoredb", "indicator_score"),
        ("statedb", "indicator_state"),
    ):
        path = root / config["input_artifacts"][key]["path"]
        con.execute(f"ATTACH '{_sql_path(path)}' AS {alias} (READ_ONLY)")


def _create_registry_tables(con: Any, config: dict[str, Any]) -> None:
    indicator_rows = ", ".join(
        "("
        + ", ".join(
            _sql_literal(row[key])
            for key in (
                "layer",
                "role",
                "indicator_id",
                "raw_source_indicator_id",
                "raw_metric_name",
                "domain_rule",
            )
        )
        + ")"
        for row in config["indicators"]
    )
    con.execute(
        f"""
        CREATE TEMP TABLE indicator_registry AS
        SELECT * FROM (VALUES {indicator_rows}) AS t(
          layer, role, indicator_id, raw_source_indicator_id, raw_metric_name, domain_rule
        )
        """
    )
    pair_rows = ", ".join(
        "("
        + ", ".join(
            _sql_literal(row[key]) for key in ("layer", "indicator_a", "indicator_b")
        )
        + ")"
        for row in config["layer_pairs"]
    )
    con.execute(
        f"""
        CREATE TEMP TABLE layer_pairs AS
        SELECT * FROM (VALUES {pair_rows}) AS t(layer, indicator_a, indicator_b)
        """
    )


def _write_raw_distribution(con: Any, path: Path) -> None:
    query = """
    WITH src AS (
      SELECT r.layer, r.role, r.indicator_id, r.raw_source_indicator_id,
             raw.raw_metric_name, raw.validity_status, raw.raw_value,
             raw.security_id, raw.trading_date,
             CASE
               WHEN r.indicator_id = 'T1_ER20'
                 THEN raw.validity_status='valid' AND isfinite(raw.raw_value) AND NOT (raw.raw_value BETWEEN 0 AND 1)
               WHEN r.indicator_id = 'V2_AmountLevel20Pct'
                 THEN raw.validity_status='valid' AND NOT isfinite(raw.raw_value)
               ELSE raw.validity_status='valid' AND isfinite(raw.raw_value) AND raw.raw_value < 0
             END AS domain_violation
      FROM rawdb.r0_t04_raw_metric_results raw
      JOIN indicator_registry r ON raw.indicator_id = r.raw_source_indicator_id
    ), stats AS (
      SELECT layer, role, indicator_id, raw_source_indicator_id,
        any_value(raw_metric_name) AS raw_metric_name,
        count(*) AS total_row_count,
        sum(validity_status='valid') AS valid_count,
        sum(validity_status='unknown') AS unknown_count,
        sum(validity_status='diagnostic_required') AS diagnostic_required_count,
        sum(validity_status='blocked') AS blocked_count,
        sum(raw_value IS NULL) AS raw_value_null_count,
        avg(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END) AS mean,
        stddev_samp(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END) AS standard_deviation,
        min(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END) AS minimum,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.01) AS q01,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.05) AS q05,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.10) AS q10,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.20) AS q20,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.30) AS q30,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.50) AS median,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.90) AS q90,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.95) AS q95,
        quantile_cont(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END, 0.99) AS q99,
        max(CASE WHEN validity_status='valid' AND isfinite(raw_value) THEN raw_value END) AS maximum,
        sum(domain_violation) AS domain_violation_count
      FROM src
      GROUP BY layer, role, indicator_id, raw_source_indicator_id
    )
    SELECT layer, role, indicator_id, raw_source_indicator_id, raw_metric_name,
      total_row_count, valid_count, unknown_count, diagnostic_required_count,
      blocked_count, raw_value_null_count,
      valid_count::DOUBLE / total_row_count AS valid_ratio,
      raw_value_null_count::DOUBLE / total_row_count AS missing_ratio,
      unknown_count::DOUBLE / total_row_count AS unknown_ratio,
      blocked_count::DOUBLE / total_row_count AS blocked_ratio,
      mean, standard_deviation, minimum, q01, q05, q10, q20, q30, median,
      q90, q95, q99, maximum,
      domain_violation_count,
      domain_violation_count::DOUBLE / total_row_count AS domain_violation_ratio
    FROM stats
    ORDER BY layer, role, indicator_id
    """
    # DuckDB cannot reference q01/q99 aliases in the same aggregate list cleanly,
    # so the tail ratio is patched in a second projection.
    query = f"""
    WITH base AS ({query})
    SELECT layer, role, indicator_id, raw_source_indicator_id, raw_metric_name,
      total_row_count, valid_count, unknown_count, diagnostic_required_count,
      blocked_count, raw_value_null_count, valid_ratio, missing_ratio,
      unknown_ratio, blocked_ratio, mean, standard_deviation, minimum, q01,
      q05, q10, q20, q30, median, q90, q95, q99, maximum,
      NULL::DOUBLE AS raw_tail_ratio_outside_q01_q99,
      domain_violation_count, domain_violation_ratio
    FROM base
    ORDER BY layer, role, indicator_id
    """
    _copy_query(con, query, path)
    _patch_raw_tail_ratio(con, path)


def _patch_raw_tail_ratio(con: Any, path: Path) -> None:
    rows = _csv_rows(path)
    counts = con.execute(
        """
        WITH src AS (
          SELECT r.indicator_id, raw.raw_value, raw.validity_status
          FROM rawdb.r0_t04_raw_metric_results raw
          JOIN indicator_registry r ON raw.indicator_id = r.raw_source_indicator_id
        )
        SELECT s.indicator_id,
          sum(s.validity_status='valid' AND isfinite(s.raw_value) AND (s.raw_value < q.q01 OR s.raw_value > q.q99)) AS tail_count
        FROM src s
        JOIN (
          SELECT * FROM read_csv_auto(?, header=true)
        ) q USING(indicator_id)
        GROUP BY s.indicator_id
        """,
        [str(path)],
    ).fetchall()
    tail = {key: int(value or 0) for key, value in counts}
    for row in rows:
        valid = int(row["valid_count"])
        row["raw_tail_ratio_outside_q01_q99"] = (
            "" if valid == 0 else _fmt_float(tail[row["indicator_id"]] / valid)
        )
    _write_csv(path, rows)


def _write_score_distribution(con: Any, path: Path) -> None:
    query = """
    SELECT r.layer, r.role, s.indicator_id, s.percentile_window_W AS W,
      count(*) AS total_row_count,
      sum(s.eligible IS TRUE) AS eligible_count,
      sum(s.eligible IS FALSE) AS ineligible_count,
      sum(s.validity_status='valid') AS valid_count,
      sum(s.validity_status='unknown') AS unknown_count,
      sum(s.validity_status='diagnostic_required') AS diagnostic_required_count,
      sum(s.validity_status='blocked') AS blocked_count,
      sum(s.eligible IS TRUE)::DOUBLE / count(*) AS eligible_ratio,
      avg(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END) AS percentile_mean,
      stddev_samp(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END) AS percentile_std,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.01) AS percentile_q01,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.05) AS percentile_q05,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.10) AS percentile_q10,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.20) AS percentile_q20,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.30) AS percentile_q30,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.50) AS percentile_q50,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.90) AS percentile_q90,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.95) AS percentile_q95,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.percentile END, 0.99) AS percentile_q99,
      avg(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END) AS score_mean,
      stddev_samp(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END) AS score_std,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.01) AS score_q01,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.05) AS score_q05,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.10) AS score_q10,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.20) AS score_q20,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.30) AS score_q30,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.50) AS score_q50,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.90) AS score_q90,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.95) AS score_q95,
      quantile_cont(CASE WHEN s.eligible AND s.validity_status='valid' THEN s.score END, 0.99) AS score_q99,
      sum(s.eligible AND (s.percentile <= 0.01 OR s.percentile >= 0.99))::DOUBLE / NULLIF(sum(s.eligible),0) AS percentile_tail_extreme_ratio,
      min(CASE WHEN s.eligible THEN s.reference_observation_count END) AS reference_observation_count_min,
      max(CASE WHEN s.eligible THEN s.reference_observation_count END) AS reference_observation_count_max,
      sum(s.eligible AND abs(s.score - (1 - s.percentile)) > 1e-12) AS score_formula_mismatch_count,
      sum(s.eligible AND (s.percentile < 0 OR s.percentile > 1 OR s.score < 0 OR s.score > 1)) AS percentile_bounds_violation_count,
      sum(s.eligible AND s.current_value_in_reference_set IS TRUE) AS current_value_in_reference_set_true_count,
      sum(s.eligible AND coalesce(s.tie_method,'') <> 'midrank') AS non_midrank_tie_method_count
    FROM scoredb.r0_t05_indicator_score_results s
    JOIN indicator_registry r USING(indicator_id)
    GROUP BY r.layer, r.role, s.indicator_id, s.percentile_window_W
    ORDER BY r.layer, r.role, s.indicator_id, W
    """
    _copy_query(con, query, path)


def _write_percentile_bucket_distribution(con: Any, path: Path) -> None:
    query = """
    WITH buckets AS (
      SELECT * FROM (VALUES
        ('B00_00_01', 0.00::DOUBLE, 0.01::DOUBLE, true, true),
        ('B01_01_05', 0.01::DOUBLE, 0.05::DOUBLE, false, true),
        ('B02_05_10', 0.05::DOUBLE, 0.10::DOUBLE, false, true),
        ('B03_10_20', 0.10::DOUBLE, 0.20::DOUBLE, false, true),
        ('B04_20_30', 0.20::DOUBLE, 0.30::DOUBLE, false, true),
        ('B05_30_50', 0.30::DOUBLE, 0.50::DOUBLE, false, true),
        ('B06_50_90', 0.50::DOUBLE, 0.90::DOUBLE, false, true),
        ('B07_90_95', 0.90::DOUBLE, 0.95::DOUBLE, false, true),
        ('B08_95_99', 0.95::DOUBLE, 0.99::DOUBLE, false, true),
        ('B09_99_100', 0.99::DOUBLE, 1.00::DOUBLE, false, true)
      ) AS t(bucket_id, lower_bound, upper_bound, lower_inclusive, upper_inclusive)
    ), eligible AS (
      SELECT r.layer, r.role, s.indicator_id, s.percentile_window_W AS W,
        s.percentile
      FROM scoredb.r0_t05_indicator_score_results s
      JOIN indicator_registry r USING(indicator_id)
      WHERE s.eligible AND s.validity_status='valid' AND s.percentile IS NOT NULL
    ), totals AS (
      SELECT layer, role, indicator_id, W, count(*) AS eligible_count
      FROM eligible
      GROUP BY layer, role, indicator_id, W
    ), counted AS (
      SELECT e.layer, e.role, e.indicator_id, e.W,
        b.bucket_id, b.lower_bound, b.upper_bound,
        b.lower_inclusive, b.upper_inclusive,
        count(*) AS bucket_count
      FROM eligible e
      JOIN buckets b
        ON (
          CASE
            WHEN b.lower_inclusive THEN e.percentile >= b.lower_bound
            ELSE e.percentile > b.lower_bound
          END
        )
       AND (
          CASE
            WHEN b.upper_inclusive THEN e.percentile <= b.upper_bound
            ELSE e.percentile < b.upper_bound
          END
        )
      GROUP BY e.layer, e.role, e.indicator_id, e.W,
        b.bucket_id, b.lower_bound, b.upper_bound,
        b.lower_inclusive, b.upper_inclusive
    )
    SELECT t.layer, t.role, t.indicator_id, t.W,
      b.bucket_id, b.lower_bound, b.upper_bound,
      b.lower_inclusive, b.upper_inclusive,
      t.eligible_count,
      coalesce(c.bucket_count,0) AS bucket_count,
      coalesce(c.bucket_count,0)::DOUBLE / NULLIF(t.eligible_count,0) AS bucket_ratio_of_eligible,
      b.upper_bound - b.lower_bound AS nominal_bucket_width,
      coalesce(c.bucket_count,0)::DOUBLE / NULLIF(t.eligible_count,0)
        - (b.upper_bound - b.lower_bound) AS bucket_ratio_minus_nominal_width
    FROM totals t
    CROSS JOIN buckets b
    LEFT JOIN counted c
      ON t.layer=c.layer AND t.role=c.role AND t.indicator_id=c.indicator_id
     AND t.W=c.W AND b.bucket_id=c.bucket_id
    ORDER BY t.layer, t.role, t.indicator_id, t.W, b.bucket_id
    """
    _copy_query(con, query, path)


def _write_hit_duration(con: Any, path: Path) -> None:
    query = """
    WITH ordered AS (
      SELECT r.layer, r.role, st.indicator_id, st.percentile_window_W AS W, st.q,
        st.security_id, st.trading_date, st.eligible, st.validity_status,
        st.indicator_active,
        lag(st.eligible) OVER w AS prior_eligible,
        lag(st.validity_status) OVER w AS prior_validity_status,
        lag(st.indicator_active) OVER w AS prior_active
      FROM statedb.r0_t06_indicator_state_results st
      JOIN indicator_registry r USING(indicator_id)
      WINDOW w AS (
        PARTITION BY st.indicator_id, st.percentile_window_W, st.q, st.security_id
        ORDER BY st.trading_date
      )
    ), flags AS (
      SELECT *,
        eligible AND validity_status='valid' AND indicator_active IS NOT NULL AS active_eligible,
        eligible AND validity_status='valid' AND indicator_active IS TRUE AS active_true,
        eligible AND validity_status='valid' AND indicator_active IS FALSE AS active_false,
        eligible AND validity_status='valid' AND indicator_active IS TRUE
          AND NOT coalesce(
            prior_eligible AND prior_validity_status='valid' AND prior_active IS TRUE
          , false) AS start_flag,
        eligible AND validity_status='valid' AND indicator_active IS TRUE
          AND prior_eligible AND prior_validity_status='valid' AND prior_active IS FALSE AS strict_flag
      FROM ordered
    ), numbered AS (
      SELECT *,
        sum(CASE WHEN start_flag THEN 1 ELSE 0 END) OVER (
          PARTITION BY indicator_id, W, q, security_id ORDER BY trading_date
          ROWS UNBOUNDED PRECEDING
        ) AS segment_id
      FROM flags
    ), segments AS (
      SELECT layer, role, indicator_id, W, q, security_id, segment_id, count(*) AS duration
      FROM numbered
      WHERE active_true
      GROUP BY layer, role, indicator_id, W, q, security_id, segment_id
    ), base AS (
      SELECT layer, role, indicator_id, W, q,
        count(*) AS total_row_count,
        sum(active_eligible) AS eligible_day_count,
        count(*) - sum(active_eligible) AS ineligible_day_count,
        sum(active_true) AS hit_true_day_count,
        sum(active_false) AS hit_false_day_count,
        count(*) - sum(active_true) - sum(active_false) AS hit_null_day_count,
        count(DISTINCT CASE WHEN indicator_active IS TRUE THEN security_id END) AS unique_security_count_hit,
        count(DISTINCT CASE WHEN indicator_active IS TRUE THEN substr(trading_date,1,4) END) AS nonzero_year_count,
        sum(start_flag) AS segment_count,
        sum(strict_flag) AS strict_onset_count,
        sum(start_flag) - sum(strict_flag) AS left_censored_start_count
      FROM flags
      GROUP BY layer, role, indicator_id, W, q
    ), stats AS (
      SELECT layer, role, indicator_id, W, q,
        count(*) AS computed_segment_count,
        sum(duration) AS total_hit_duration,
        avg(duration) AS mean_duration,
        stddev_samp(duration) AS std_duration,
        min(duration) AS min_duration,
        quantile_cont(duration, 0.10) AS q10,
        quantile_cont(duration, 0.25) AS q25,
        quantile_cont(duration, 0.50) AS q50,
        quantile_cont(duration, 0.75) AS q75,
        quantile_cont(duration, 0.90) AS q90,
        quantile_cont(duration, 0.95) AS q95,
        quantile_cont(duration, 0.99) AS q99,
        max(duration) AS max_duration,
        sum(duration=1) AS single_day_segment_count
      FROM segments
      GROUP BY layer, role, indicator_id, W, q
    )
    SELECT b.layer, b.role, b.indicator_id, b.W, b.q,
      b.total_row_count, b.eligible_day_count, b.ineligible_day_count,
      b.hit_true_day_count, b.hit_false_day_count, b.hit_null_day_count,
      b.hit_true_day_count::DOUBLE / NULLIF(b.eligible_day_count,0) AS hit_rate,
      b.hit_true_day_count::DOUBLE / NULLIF(b.total_row_count,0) AS coverage,
      b.unique_security_count_hit, b.nonzero_year_count,
      b.segment_count, b.strict_onset_count, b.left_censored_start_count,
      coalesce(s.total_hit_duration,0) AS total_hit_duration,
      s.mean_duration, s.std_duration, s.min_duration, s.q10, s.q25, s.q50,
      s.q75, s.q90, s.q95, s.q99, s.max_duration,
      coalesce(s.single_day_segment_count,0) AS single_day_segment_count,
      coalesce(s.single_day_segment_count,0)::DOUBLE / NULLIF(b.segment_count,0) AS single_day_fragment_ratio
    FROM base b
    LEFT JOIN stats s USING(layer, role, indicator_id, W, q)
    ORDER BY b.layer, b.role, b.indicator_id, b.W, b.q
    """
    _copy_query(con, query, path)


def _write_intralayer_correlation(con: Any, path: Path) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE pair_scores AS
        SELECT p.layer, p.indicator_a, p.indicator_b, a.percentile_window_W AS W,
          a.security_id, a.trading_date,
          a.score AS a_score, b.score AS b_score,
          a.percentile AS a_percentile, b.percentile AS b_percentile
        FROM layer_pairs p
        JOIN scoredb.r0_t05_indicator_score_results a
          ON a.indicator_id=p.indicator_a
        JOIN scoredb.r0_t05_indicator_score_results b
          ON b.indicator_id=p.indicator_b
         AND a.security_id=b.security_id
         AND a.trading_date=b.trading_date
         AND a.percentile_window_W=b.percentile_window_W
        WHERE a.eligible AND b.eligible
          AND a.validity_status='valid' AND b.validity_status='valid'
          AND a.score IS NOT NULL AND b.score IS NOT NULL
        """
    )
    query = """
    WITH pooled_ranked AS (
      SELECT *,
        rank() OVER (PARTITION BY layer, W ORDER BY a_score) + (count(*) OVER (PARTITION BY layer, W, a_score) - 1) / 2.0 AS a_score_rank,
        rank() OVER (PARTITION BY layer, W ORDER BY b_score) + (count(*) OVER (PARTITION BY layer, W, b_score) - 1) / 2.0 AS b_score_rank,
        rank() OVER (PARTITION BY layer, W ORDER BY a_percentile) + (count(*) OVER (PARTITION BY layer, W, a_percentile) - 1) / 2.0 AS a_percentile_rank,
        rank() OVER (PARTITION BY layer, W ORDER BY b_percentile) + (count(*) OVER (PARTITION BY layer, W, b_percentile) - 1) / 2.0 AS b_percentile_rank
      FROM pair_scores
    ), pooled AS (
      SELECT layer, any_value(indicator_a) AS indicator_a, any_value(indicator_b) AS indicator_b, W,
        count(*) AS eligible_rows,
        count(DISTINCT security_id) AS unique_security_count,
        corr(a_score_rank, b_score_rank) AS pooled_spearman_score,
        corr(a_percentile_rank, b_percentile_rank) AS pooled_spearman_percentile
      FROM pooled_ranked
      GROUP BY layer, W
    ), security_ranked AS (
      SELECT *,
        count(*) OVER (PARTITION BY layer, W, security_id) AS paired_rows,
        count(DISTINCT a_score) OVER (PARTITION BY layer, W, security_id) AS a_distinct,
        count(DISTINCT b_score) OVER (PARTITION BY layer, W, security_id) AS b_distinct,
        rank() OVER (PARTITION BY layer, W, security_id ORDER BY a_score) + (count(*) OVER (PARTITION BY layer, W, security_id, a_score) - 1) / 2.0 AS a_rank,
        rank() OVER (PARTITION BY layer, W, security_id ORDER BY b_score) + (count(*) OVER (PARTITION BY layer, W, security_id, b_score) - 1) / 2.0 AS b_rank
      FROM pair_scores
    ), security_corr AS (
      SELECT layer, W, security_id, corr(a_rank, b_rank) AS rho
      FROM security_ranked
      WHERE paired_rows >= 3 AND a_distinct >= 2 AND b_distinct >= 2
      GROUP BY layer, W, security_id
    ), security_summary AS (
      SELECT layer, W,
        count(*) AS security_spearman_computable_count,
        quantile_cont(rho,0.25) AS security_spearman_q25,
        quantile_cont(rho,0.50) AS security_spearman_median,
        quantile_cont(rho,0.75) AS security_spearman_q75,
        avg(CASE WHEN rho > 0 THEN 1.0 ELSE 0.0 END) AS positive_security_share,
        avg(CASE WHEN rho < 0 THEN 1.0 ELSE 0.0 END) AS negative_security_share,
        avg(CASE WHEN rho = 0 THEN 1.0 ELSE 0.0 END) AS zero_security_share
      FROM security_corr
      GROUP BY layer, W
    )
    SELECT p.layer, p.indicator_a, p.indicator_b, p.W, p.eligible_rows,
      p.unique_security_count, p.pooled_spearman_score,
      p.pooled_spearman_percentile,
      s.security_spearman_computable_count, s.security_spearman_q25,
      s.security_spearman_median, s.security_spearman_q75,
      s.positive_security_share, s.negative_security_share, s.zero_security_share,
      CASE
        WHEN p.pooled_spearman_score IS NULL OR s.security_spearman_median IS NULL THEN NULL
        WHEN (p.pooled_spearman_score >= 0 AND s.security_spearman_median >= 0)
          OR (p.pooled_spearman_score < 0 AND s.security_spearman_median < 0)
        THEN true ELSE false
      END AS pooled_vs_security_median_sign_consistency
    FROM pooled p
    LEFT JOIN security_summary s USING(layer, W)
    ORDER BY p.layer, p.W
    """
    _copy_query(con, query, path)


def _write_threshold_structure(con: Any, path: Path) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE pair_hits AS
        SELECT p.layer, p.indicator_a, p.indicator_b, a.percentile_window_W AS W, a.q,
          a.security_id, a.trading_date,
          a.eligible AND b.eligible
            AND a.validity_status='valid' AND b.validity_status='valid'
            AND a.indicator_active IS NOT NULL AND b.indicator_active IS NOT NULL
            AS pair_eligible,
          a.eligible AND b.eligible
            AND a.validity_status='valid' AND b.validity_status='valid'
            AND a.indicator_active IS TRUE AS a_hit,
          a.eligible AND b.eligible
            AND a.validity_status='valid' AND b.validity_status='valid'
            AND b.indicator_active IS TRUE AS b_hit,
          a.eligible AND b.eligible
            AND a.validity_status='valid' AND b.validity_status='valid'
            AND a.indicator_active IS TRUE AND b.indicator_active IS TRUE AS both_hit
        FROM layer_pairs p
        JOIN statedb.r0_t06_indicator_state_results a
          ON a.indicator_id=p.indicator_a
        JOIN statedb.r0_t06_indicator_state_results b
          ON b.indicator_id=p.indicator_b
         AND a.security_id=b.security_id
         AND a.trading_date=b.trading_date
         AND a.percentile_window_W=b.percentile_window_W
         AND a.q=b.q
        """
    )
    query = """
    WITH ordered AS (
      SELECT *,
        lag(pair_eligible) OVER w AS prior_pair_eligible,
        lag(both_hit) OVER w AS prior_both
      FROM pair_hits
      WINDOW w AS (
        PARTITION BY layer, W, q, security_id ORDER BY trading_date
      )
    ), flags AS (
      SELECT *,
        both_hit AND NOT coalesce(prior_pair_eligible AND prior_both, false) AS joint_start,
        both_hit AND coalesce(prior_pair_eligible, false) AND prior_both IS FALSE AS joint_strict
      FROM ordered
    ), numbered AS (
      SELECT *,
        sum(CASE WHEN joint_start THEN 1 ELSE 0 END) OVER (
          PARTITION BY layer, W, q, security_id ORDER BY trading_date
          ROWS UNBOUNDED PRECEDING
        ) AS joint_segment_id
      FROM flags
    ), joint_segments AS (
      SELECT layer, W, q, security_id, joint_segment_id, count(*) AS duration
      FROM numbered
      WHERE both_hit
      GROUP BY layer, W, q, security_id, joint_segment_id
    ), base AS (
      SELECT layer, any_value(indicator_a) AS indicator_a,
        any_value(indicator_b) AS indicator_b, W, q,
        sum(pair_eligible) AS common_eligible_rows,
        sum(both_hit) AS both_hit,
        sum(pair_eligible AND a_hit AND NOT b_hit) AS indicator_a_only,
        sum(pair_eligible AND b_hit AND NOT a_hit) AS indicator_b_only,
        sum(pair_eligible AND NOT a_hit AND NOT b_hit) AS neither,
        sum(a_hit) AS A_hit_count,
        sum(b_hit) AS B_hit_count,
        sum(joint_start) AS joint_segment_count,
        sum(joint_strict) AS joint_strict_onset_count,
        sum(joint_start) - sum(joint_strict) AS joint_left_censored_start_count
      FROM flags
      GROUP BY layer, W, q
    ), stats AS (
      SELECT layer, W, q,
        sum(duration) AS joint_total_duration,
        avg(duration) AS joint_mean_duration,
        quantile_cont(duration,0.50) AS joint_median_duration,
        quantile_cont(duration,0.90) AS joint_q90_duration,
        quantile_cont(duration,0.95) AS joint_q95_duration,
        max(duration) AS joint_max_duration,
        sum(duration=1) AS joint_single_day_segment_count
      FROM joint_segments
      GROUP BY layer, W, q
    )
    SELECT b.layer, b.indicator_a, b.indicator_b, b.W, b.q,
      b.common_eligible_rows, b.both_hit, b.indicator_a_only,
      b.indicator_b_only, b.neither, b.A_hit_count, b.B_hit_count,
      b.A_hit_count::DOUBLE / NULLIF(b.common_eligible_rows,0) AS A_hit_rate,
      b.B_hit_count::DOUBLE / NULLIF(b.common_eligible_rows,0) AS B_hit_rate,
      b.both_hit::DOUBLE / NULLIF(b.common_eligible_rows,0) AS both_hit_rate,
      b.both_hit::DOUBLE / NULLIF(b.both_hit + b.indicator_b_only,0) AS A_given_B,
      b.both_hit::DOUBLE / NULLIF(b.both_hit + b.indicator_a_only,0) AS B_given_A,
      b.both_hit::DOUBLE / NULLIF(b.both_hit + b.indicator_a_only + b.indicator_b_only,0) AS Jaccard,
      (b.both_hit + b.indicator_b_only = 0) AS A_given_B_denominator_zero,
      (b.both_hit + b.indicator_a_only = 0) AS B_given_A_denominator_zero,
      (b.both_hit + b.indicator_a_only + b.indicator_b_only = 0) AS Jaccard_denominator_zero,
      b.joint_segment_count, b.joint_strict_onset_count,
      b.joint_left_censored_start_count,
      coalesce(s.joint_total_duration,0) AS joint_total_duration,
      s.joint_mean_duration, s.joint_median_duration, s.joint_q90_duration,
      s.joint_q95_duration, s.joint_max_duration,
      coalesce(s.joint_single_day_segment_count,0) AS joint_single_day_segment_count,
      coalesce(s.joint_single_day_segment_count,0)::DOUBLE / NULLIF(b.joint_segment_count,0) AS joint_single_day_fragment_ratio
    FROM base b
    LEFT JOIN stats s USING(layer, W, q)
    ORDER BY b.layer, b.W, b.q
    """
    _copy_query(con, query, path)


def _write_diagnostic_summary(con: Any, path: Path) -> None:
    threshold_path = _sql_path(
        path.parent / "r1_t05_intralayer_threshold_structure.csv"
    )
    correlation_path = _sql_path(path.parent / "r1_t05_intralayer_correlation.csv")
    query = """
    WITH corr AS (
      SELECT * FROM read_csv_auto('__CORRELATION__', header=true)
    ), th AS (
      SELECT * FROM read_csv_auto('__THRESHOLD__', header=true) WHERE abs(q - 0.2) < 1e-12
    )
    SELECT c.layer, c.indicator_a, c.indicator_b, c.W,
      c.eligible_rows AS common_eligible_rows,
      c.unique_security_count,
      c.pooled_spearman_score,
      c.security_spearman_median,
      th.both_hit AS q20_both_hit,
      th.indicator_a_only AS q20_indicator_a_only,
      th.indicator_b_only AS q20_indicator_b_only,
      th.neither AS q20_neither,
      th.A_hit_count AS q20_A_hit_count,
      th.B_hit_count AS q20_B_hit_count,
      th.Jaccard AS q20_Jaccard,
      CASE
        WHEN c.eligible_rows = 0 OR c.pooled_spearman_score IS NULL
          OR (th.both_hit + th.indicator_a_only + th.indicator_b_only) = 0
          THEN 'insufficient_eligible_sample'
        WHEN c.pooled_spearman_score < 0
          OR c.security_spearman_median < 0
          OR (th.A_hit_count > 0 AND th.B_hit_count > 0 AND th.both_hit = 0)
          THEN 'construct_conflict_warning'
        WHEN th.indicator_a_only = 0 OR th.indicator_b_only = 0
          OR (c.pooled_spearman_score >= 0.95 AND th.Jaccard >= 0.90
              AND least(th.A_given_B, th.B_given_A) >= 0.95)
          THEN 'redundancy_warning'
        WHEN c.pooled_spearman_score >= 0 AND th.both_hit > 0
          AND th.indicator_a_only > 0 AND th.indicator_b_only > 0
          THEN 'complementary_structure'
        ELSE 'insufficient_eligible_sample'
      END AS diagnostic_status
    FROM corr c
    JOIN th USING(layer, W)
    ORDER BY c.layer, c.W
    """
    query = query.replace("__CORRELATION__", correlation_path).replace(
        "__THRESHOLD__", threshold_path
    )
    _copy_query(con, query, path)


def _write_reason_profile(con: Any, path: Path) -> None:
    rows: list[dict[str, Any]] = []
    registry = con.execute(
        "SELECT layer, role, indicator_id, raw_source_indicator_id FROM indicator_registry ORDER BY layer, role"
    ).fetchall()
    for layer, _role, indicator_id, raw_source in registry:
        raw_total = int(
            con.execute(
                """
                SELECT count(*)
                FROM rawdb.r0_t04_raw_metric_results raw
                WHERE raw.indicator_id = ?
                """,
                [raw_source],
            ).fetchone()[0]
        )
        raw_rows = con.execute(
            """
            SELECT validity_status, reason.reason_code, count(*) AS row_count
            FROM rawdb.r0_t04_raw_metric_results raw
            CROSS JOIN UNNEST(coalesce(raw.reason_codes, []::VARCHAR[])) AS reason(reason_code)
            WHERE raw.indicator_id = ?
            GROUP BY validity_status, reason.reason_code
            ORDER BY validity_status, reason.reason_code
            """,
            [raw_source],
        ).fetchall()
        raw_occurrence_total = sum(
            int(row_count) for _status, _reason, row_count in raw_rows
        )
        for validity_status, reason_code, row_count in raw_rows:
            rows.append(
                {
                    "source_level": "raw_metric",
                    "layer": layer,
                    "indicator_id": indicator_id,
                    "raw_source_indicator_id": raw_source,
                    "W": None,
                    "validity_status": validity_status,
                    "reason_code": reason_code,
                    "total_row_count": raw_total,
                    "reason_occurrence_count": raw_occurrence_total,
                    "row_count": int(row_count),
                    "row_prevalence": _safe_div(row_count, raw_total),
                    "reason_occurrence_share": _safe_div(
                        row_count, raw_occurrence_total
                    ),
                }
            )
        for w in (120, 250, 500):
            score_total = int(
                con.execute(
                    """
                    SELECT count(*)
                    FROM scoredb.r0_t05_indicator_score_results s
                    WHERE s.indicator_id = ? AND s.percentile_window_W = ?
                    """,
                    [indicator_id, w],
                ).fetchone()[0]
            )
            score_rows = con.execute(
                """
                SELECT validity_status, reason.reason_code, count(*) AS row_count
                FROM scoredb.r0_t05_indicator_score_results s
                CROSS JOIN UNNEST(coalesce(s.reason_codes, []::VARCHAR[])) AS reason(reason_code)
                WHERE s.indicator_id = ? AND s.percentile_window_W = ?
                GROUP BY validity_status, reason.reason_code
                ORDER BY validity_status, reason.reason_code
                """,
                [indicator_id, w],
            ).fetchall()
            score_occurrence_total = sum(
                int(row_count) for _status, _reason, row_count in score_rows
            )
            for validity_status, reason_code, row_count in score_rows:
                rows.append(
                    {
                        "source_level": "indicator_score",
                        "layer": layer,
                        "indicator_id": indicator_id,
                        "raw_source_indicator_id": raw_source,
                        "W": w,
                        "validity_status": validity_status,
                        "reason_code": reason_code,
                        "total_row_count": score_total,
                        "reason_occurrence_count": score_occurrence_total,
                        "row_count": int(row_count),
                        "row_prevalence": _safe_div(row_count, score_total),
                        "reason_occurrence_share": _safe_div(
                            row_count, score_occurrence_total
                        ),
                    }
                )
    rows.sort(
        key=lambda row: (
            row["source_level"],
            row["layer"],
            row["indicator_id"],
            -1 if row["W"] is None else int(row["W"]),
            row["validity_status"],
            row["reason_code"],
        )
    )
    _write_csv(path, rows)


def _write_reconciliation(con: Any, path: Path) -> None:
    query = """
    SELECT r.layer, r.role, st.indicator_id, st.percentile_window_W AS W, st.q,
      count(*) AS r0_t06_row_count,
      sum(st.eligible IS TRUE) AS state_eligible_count,
      sum(st.indicator_active IS TRUE) AS state_active_true_count,
      sum(st.indicator_active IS FALSE) AS state_active_false_count,
      sum(st.indicator_active IS NULL) AS state_active_null_count,
      sum(sc.eligible IS TRUE) AS score_eligible_count,
      sum(sc.eligible IS TRUE AND sc.score >= 1 - st.q - 1e-12) AS recomputed_active_true_count,
      sum(sc.eligible IS TRUE AND NOT (sc.score >= 1 - st.q - 1e-12)) AS recomputed_active_false_count,
      sum(sc.eligible IS NOT TRUE) AS recomputed_active_null_count,
      sum(
        CASE
          WHEN sc.eligible IS TRUE THEN
            st.indicator_active IS DISTINCT FROM (sc.score >= 1 - st.q - 1e-12)
          ELSE st.indicator_active IS NOT NULL
        END
      ) AS active_mismatch_count
    FROM statedb.r0_t06_indicator_state_results st
    JOIN scoredb.r0_t05_indicator_score_results sc
      ON st.security_id=sc.security_id
     AND st.trading_date=sc.trading_date
     AND st.indicator_id=sc.indicator_id
     AND st.percentile_window_W=sc.percentile_window_W
    JOIN indicator_registry r ON r.indicator_id = st.indicator_id
    GROUP BY r.layer, r.role, st.indicator_id, W, st.q
    ORDER BY r.layer, r.role, st.indicator_id, W, st.q
    """
    _copy_query(con, query, path)


def _evaluate_outputs(paths: dict[str, Path], root: Path) -> dict[str, Any]:
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

    raw = _csv_rows(paths["indicator_raw_distribution_csv"])
    score = _csv_rows(paths["indicator_score_distribution_csv"])
    bucket = _csv_rows(paths["indicator_percentile_bucket_distribution_csv"])
    hit = _csv_rows(paths["indicator_hit_duration_csv"])
    corr = _csv_rows(paths["intralayer_correlation_csv"])
    threshold = _csv_rows(paths["intralayer_threshold_structure_csv"])
    diag = _csv_rows(paths["intralayer_diagnostic_summary_csv"])
    reason = _csv_rows(paths["validity_reason_profile_csv"])
    recon = _csv_rows(paths["r0_t06_reconciliation_csv"])
    check(
        "primary_output_nonempty",
        len(raw) == RAW_ROWS
        and len(score) == SCORE_ROWS
        and len(bucket) == PERCENTILE_BUCKET_ROWS
        and len(hit) == HIT_ROWS
        and len(corr) == CORRELATION_ROWS
        and len(threshold) == THRESHOLD_ROWS
        and len(diag) == DIAGNOSTIC_ROWS
        and len(recon) == RECONCILIATION_ROWS
        and len(reason) > 0,
        "primary_output_row_count_mismatch",
    )
    check(
        "c2_repaired_validity",
        any(
            row["indicator_id"] == "C2_AdjVWAPSpread_5_60"
            and _int(row, "valid_count") == 1659385
            and _int(row, "unknown_count") == 38879
            and _int(row, "blocked_count") == 32505
            for row in raw
        ),
        "c2_repaired_counts_mismatch",
    )
    check(
        "raw_domain",
        all(_int(row, "domain_violation_count") == 0 for row in raw),
        "raw_domain_violation",
    )
    check(
        "score_formula",
        all(
            _int(row, "score_formula_mismatch_count") == 0
            and _int(row, "percentile_bounds_violation_count") == 0
            and _int(row, "current_value_in_reference_set_true_count") == 0
            and _int(row, "non_midrank_tie_method_count") == 0
            for row in score
        ),
        "score_invariant_violation",
    )
    check(
        "w_availability_response",
        _w_monotone(score),
        "w_availability_not_monotone",
    )
    check(
        "indicator_hit_accounting",
        all(
            _int(row, "segment_count")
            == _int(row, "strict_onset_count") + _int(row, "left_censored_start_count")
            and _int(row, "total_hit_duration") == _int(row, "hit_true_day_count")
            and _hit_denominator_integrity(row)
            for row in hit
        ),
        "indicator_duration_accounting",
    )
    check(
        "percentile_bucket_distribution",
        _percentile_bucket_integrity(bucket, score),
        "percentile_bucket_distribution_mismatch",
    )
    check(
        "q_hit_nesting",
        _q_nested(hit, threshold),
        "q_hit_nesting_failed",
    )
    check(
        "spearman_reconciliation",
        all(
            abs(
                _float(row, "pooled_spearman_score")
                - _float(row, "pooled_spearman_percentile")
            )
            <= 1e-12
            for row in corr
            if row.get("pooled_spearman_score") not in ("", None)
        ),
        "spearman_score_percentile_mismatch",
    )
    check(
        "threshold_accounting",
        all(
            _int(row, "both_hit")
            + _int(row, "indicator_a_only")
            + _int(row, "indicator_b_only")
            + _int(row, "neither")
            == _int(row, "common_eligible_rows")
            and _int(row, "joint_segment_count")
            == _int(row, "joint_strict_onset_count")
            + _int(row, "joint_left_censored_start_count")
            and _int(row, "joint_total_duration") == _int(row, "both_hit")
            for row in threshold
        ),
        "threshold_or_joint_accounting",
    )
    check(
        "r0_t06_reconciliation",
        all(_int(row, "active_mismatch_count") == 0 for row in recon),
        "r0_t06_reconciliation_mismatch",
    )
    check(
        "validity_reason_denominator",
        _reason_profile_integrity(reason),
        "validity_reason_denominator_mismatch",
    )
    check(
        "diagnostic_status_complete",
        len(diag) == DIAGNOSTIC_ROWS
        and all(
            row["diagnostic_status"]
            in {
                "complementary_structure",
                "redundancy_warning",
                "construct_conflict_warning",
                "insufficient_eligible_sample",
            }
            for row in diag
        ),
        "diagnostic_status_incomplete",
    )
    check(
        "forbidden_output_tokens",
        not _contains_forbidden_tokens(paths, root),
        "forbidden_output_token_present",
    )
    material_warnings = _material_warnings(raw, corr, hit, threshold, bucket)
    return {
        "checks": checks,
        "errors": errors,
        "row_counts": row_counts,
        "material_warnings": material_warnings,
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
    mapping = {
        "primary_output_nonempty": ("primary_output_nonempty",),
        "all_zero_check": ("primary_output_nonempty", "q_hit_nesting"),
        "all_one_check": ("primary_output_nonempty",),
        "all_null_check": ("primary_output_nonempty", "diagnostic_status_complete"),
        "validity_rate_check": ("c2_repaired_validity", "w_availability_response"),
        "coverage_check": ("primary_output_nonempty",),
        "parameter_response_check": ("w_availability_response", "q_hit_nesting"),
        "baseline_challenger_check": ("diagnostic_status_complete",),
        "nested_invariant_check": ("q_hit_nesting",),
        "funnel_accounting_check": (
            "indicator_hit_accounting",
            "threshold_accounting",
        ),
        "denominator_integrity_check": (
            "indicator_hit_accounting",
            "threshold_accounting",
            "percentile_bucket_distribution",
            "validity_reason_denominator",
        ),
        "sample_size_check": ("primary_output_nonempty",),
        "upstream_consistency_check": ("r0_t06_reconciliation",),
        "scale_shift_check": ("score_formula", "raw_domain"),
        "time_alignment_check": ("r0_t06_reconciliation",),
        "future_leakage_check": ("forbidden_output_tokens",),
        "post_hoc_selection_check": ("diagnostic_status_complete",),
        "conclusion_support_check": ("forbidden_output_tokens",),
    }
    source = diagnostic["checks"]
    checks = {}
    for name in names:
        required = mapping[name]
        passed = status == "completed" and all(
            source.get(check) == "passed" for check in required
        )
        checks[name] = {
            "status": "passed" if passed else "blocked",
            "rationale": "R1-T05 task-specific machine-readable check: "
            + ", ".join(required),
            "metrics": {check: source.get(check) for check in required},
            "artifact_references": [_rel(paths["diagnostic_summary"], ROOT)],
        }
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "scan_status": "passed" if status == "completed" else "blocked",
        "checks": checks,
        "blocking_anomalies": diagnostic["errors"],
        "nonblocking_anomalies": [
            warning["name"] for warning in diagnostic["material_warnings"]
        ],
        "investigations": diagnostic["material_warnings"],
        "unresolved_questions": [],
    }


def _check_r1_t04_gate(config: dict[str, Any], root: Path) -> dict[str, Any]:
    errors: list[str] = []
    package = _load_json(root / config["r1_t04_result_package_path"])
    review = _load_json(root / config["r1_t04_scientific_review_path"])
    readme = (root / "docs/tasks/README.md").read_text(encoding="utf-8")
    if package.get("status") != "completed":
        errors.append("r1_t04_status_not_completed")
    gate = package.get("gate_status", {})
    if gate.get("scientific_review_status") != "passed":
        errors.append("r1_t04_scientific_review_not_passed")
    if package.get("downstream_gate_allowed") is not True:
        errors.append("r1_t04_downstream_gate_not_allowed")
    if review.get("scientific_review_status") != "passed":
        errors.append("r1_t04_review_record_not_passed")
    if "current_task: R1-T05 单指标诊断与层内互补性分析" not in readme:
        errors.append("readme_current_task_not_r1_t05")
    if "R1-T05_allowed_to_start: true" not in readme:
        errors.append("readme_r1_t05_gate_not_true")
    return {
        "errors": errors,
        "lineage": {
            "r1_t04_result_package_path": config["r1_t04_result_package_path"],
            "r1_t04_result_package_sha256": sha256_file(
                root / config["r1_t04_result_package_path"]
            ),
            "r1_t04_scientific_review_path": config["r1_t04_scientific_review_path"],
            "r1_t04_scientific_review_sha256": sha256_file(
                root / config["r1_t04_scientific_review_path"]
            ),
            "r1_t04_scientific_review_md_path": config[
                "r1_t04_scientific_review_md_path"
            ],
            "r1_t04_evidence_path": config["r1_t04_evidence_path"],
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
    indicators = config.get("indicators", [])
    if len({row.get("indicator_id") for row in indicators}) != 8:
        errors.append("indicator_registry_not_exactly_eight")
    if len({row.get("layer") for row in config.get("layer_pairs", [])}) != 4:
        errors.append("layer_pair_registry_not_exactly_four")
    if config.get("W") != [120, 250, 500] or config.get("q") != [0.1, 0.2, 0.3]:
        errors.append("grid_not_exact")
    return errors


def _copy_query(
    con: Any, query: str, path: Path, parameters: list[Any] | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    copy_sql = f"COPY ({query}) TO '{_sql_path(path)}' (HEADER, DELIMITER ',')"
    if parameters:
        con.execute(copy_sql, parameters)
    else:
        con.execute(copy_sql)


def _write_empty_outputs(paths: dict[str, Path]) -> None:
    for name, path in paths.items():
        if name == "summary":
            continue
        if path.suffix == ".csv":
            _write_csv(path, [])
        else:
            _write_json(path, {})


def _material_warnings(
    raw_rows: list[dict[str, str]],
    correlation_rows: list[dict[str, str]],
    hit_rows: list[dict[str, str]],
    threshold_rows: list[dict[str, str]],
    bucket_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = [
        {
            "name": "inherits_r1_t04_window_dependent_state_identity",
            "status": "material_warning",
            "rationale": "R1-T04 final gate recorded window-dependent state identity; R1-T05 describes indicator-level availability and overlap without selecting W.",
        },
        {
            "name": "inherits_r1_t04_confirmation_population_k_sensitivity",
            "status": "material_warning",
            "rationale": "R1-T05 is K-not-applicable and does not remove the R1-T04 confirmation population warning.",
        },
        {
            "name": "inherits_r1_t04_pcvt_confirmed_high_fragmentation",
            "status": "material_warning",
            "rationale": "R1-T05 reports indicator and joint-hit duration fragments but does not alter PCVT confirmation semantics.",
        },
    ]
    c_rows = [row for row in correlation_rows if row["layer"] == "C"]
    if c_rows and max(_float(row, "pooled_spearman_score") for row in c_rows) >= 0.90:
        warnings.append(
            {
                "name": "C_layer_near_redundancy",
                "status": "material_warning",
                "metrics": {
                    "max_pooled_spearman_score": _fmt_float(
                        max(_float(row, "pooled_spearman_score") for row in c_rows)
                    ),
                    "max_security_spearman_median": _fmt_float(
                        max(_float(row, "security_spearman_median") for row in c_rows)
                    ),
                },
                "rationale": "C layer remains below the frozen redundancy threshold, but its two indicators are materially closer than P/T/V.",
            }
        )
    v_rows = sorted(
        [row for row in correlation_rows if row["layer"] == "V"],
        key=lambda row: int(row["W"]),
    )
    if len(v_rows) == 3:
        drop = _float(v_rows[0], "pooled_spearman_score") - _float(
            v_rows[-1], "pooled_spearman_score"
        )
        if drop >= 0.10:
            warnings.append(
                {
                    "name": "V_layer_W_dependent_identity",
                    "status": "material_warning",
                    "metrics": {
                        "W120_pooled_spearman_score": v_rows[0][
                            "pooled_spearman_score"
                        ],
                        "W500_pooled_spearman_score": v_rows[-1][
                            "pooled_spearman_score"
                        ],
                        "drop": _fmt_float(drop),
                    },
                    "rationale": "V layer intralayer relationship weakens materially as W increases; this is a diagnostic input for the inherited R1-T04 window-dependent warning.",
                }
            )
    for row in hit_rows:
        frag = _float_or_none(row, "single_day_fragment_ratio")
        if frag is not None and frag >= 0.5 and _int(row, "segment_count") > 0:
            warnings.append(
                {
                    "name": f"{row['indicator_id']}_W{row['W']}_Q{_q_label(row['q'])}_high_fragment_rate",
                    "status": "material_warning",
                    "metrics": {
                        "single_day_fragment_ratio": row["single_day_fragment_ratio"],
                        "segment_count": row["segment_count"],
                    },
                    "rationale": "High single-day hit fragmentation is reported for scientific review.",
                }
            )
    for row in threshold_rows:
        if (
            row["layer"] == "T"
            and abs(_float(row, "q") - 0.10) <= 1e-12
            and _float_or_none(row, "joint_single_day_fragment_ratio") is not None
            and _float(row, "joint_single_day_fragment_ratio") >= 0.5
        ):
            warnings.append(
                {
                    "name": f"T_layer_W{row['W']}_Q10_joint_high_fragmentation",
                    "status": "material_warning",
                    "metrics": {
                        "joint_single_day_fragment_ratio": row[
                            "joint_single_day_fragment_ratio"
                        ],
                        "joint_segment_count": row["joint_segment_count"],
                    },
                    "rationale": "T layer q10 joint both-hit events are directionally consistent but concentrated in short fragments.",
                }
            )
        if _int(row, "both_hit") == 0 and (
            _int(row, "A_hit_count") > 0 or _int(row, "B_hit_count") > 0
        ):
            warnings.append(
                {
                    "name": f"{row['layer']}_W{row['W']}_Q{_q_label(row['q'])}_zero_joint_both_hit",
                    "status": "material_warning",
                    "metrics": {
                        "A_hit_count": row["A_hit_count"],
                        "B_hit_count": row["B_hit_count"],
                    },
                    "rationale": "Zero joint both-hit is a scientific finding unless the frozen diagnostic rules classify it as a blocker.",
                }
            )
    t2 = next(
        (row for row in raw_rows if row["indicator_id"] == "T2_AbsTrendT20"), None
    )
    if t2 is not None and _float(row=t2, key="q99") > 0:
        max_to_q99 = _float(t2, "maximum") / _float(t2, "q99")
        if max_to_q99 >= 100:
            warnings.append(
                {
                    "name": "T2_AbsTrendT20_extreme_right_tail",
                    "status": "material_warning",
                    "metrics": {
                        "q99": t2["q99"],
                        "maximum": t2["maximum"],
                        "max_to_q99_ratio": _fmt_float(max_to_q99),
                    },
                    "rationale": "Extreme right tail is a raw-scale numerical warning; it does not by itself invalidate the low-tail trend-neutrality definition.",
                }
            )
    grouped_buckets: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in bucket_rows:
        grouped_buckets.setdefault((row["indicator_id"], row["W"]), []).append(row)
    for (indicator_id, w), rows in grouped_buckets.items():
        max_abs_delta = max(
            abs(_float(row, "bucket_ratio_minus_nominal_width")) for row in rows
        )
        if max_abs_delta >= 0.05:
            warnings.append(
                {
                    "name": f"{indicator_id}_W{w}_nonuniform_strict_past_percentile_distribution",
                    "status": "material_warning",
                    "metrics": {
                        "max_abs_bucket_ratio_minus_nominal_width": _fmt_float(
                            max_abs_delta
                        )
                    },
                    "rationale": "Strict-past percentile buckets are materially nonuniform; nominal q is a threshold, not a guaranteed target coverage.",
                }
            )
    for row in hit_rows:
        q = _float(row, "q")
        hit_rate = _float_or_none(row, "hit_rate")
        if hit_rate is not None and abs(hit_rate - q) >= 0.025:
            warnings.append(
                {
                    "name": f"{row['indicator_id']}_W{row['W']}_Q{_q_label(row['q'])}_boundary_mass_and_nominal_q_coverage_divergence",
                    "status": "material_warning",
                    "metrics": {
                        "q": row["q"],
                        "eligible_hit_rate": row["hit_rate"],
                        "coverage": row["coverage"],
                    },
                    "rationale": "Observed eligible hit rate diverges from nominal q under strict-past percentiles, ties, and time-varying distributions.",
                }
            )
    return warnings


def _hit_denominator_integrity(row: dict[str, str]) -> bool:
    total = _int(row, "total_row_count")
    eligible = _int(row, "eligible_day_count")
    ineligible = _int(row, "ineligible_day_count")
    true_count = _int(row, "hit_true_day_count")
    false_count = _int(row, "hit_false_day_count")
    null_count = _int(row, "hit_null_day_count")
    if total != eligible + ineligible:
        return False
    if eligible != true_count + false_count:
        return False
    if total != true_count + false_count + null_count:
        return False
    hit_rate = _float_or_none(row, "hit_rate")
    coverage = _float_or_none(row, "coverage")
    expected_hit_rate = _safe_div(true_count, eligible)
    expected_coverage = _safe_div(true_count, total)
    if not _float_matches(hit_rate, expected_hit_rate):
        return False
    return _float_matches(coverage, expected_coverage)


def _percentile_bucket_integrity(
    bucket_rows: list[dict[str, str]], score_rows: list[dict[str, str]]
) -> bool:
    if len(bucket_rows) != PERCENTILE_BUCKET_ROWS:
        return False
    score_eligible = {
        (row["indicator_id"], row["W"]): _int(row, "eligible_count")
        for row in score_rows
    }
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in bucket_rows:
        grouped.setdefault((row["indicator_id"], row["W"]), []).append(row)
    if set(grouped) != set(score_eligible):
        return False
    expected_buckets = {
        "B00_00_01",
        "B01_01_05",
        "B02_05_10",
        "B03_10_20",
        "B04_20_30",
        "B05_30_50",
        "B06_50_90",
        "B07_90_95",
        "B08_95_99",
        "B09_99_100",
    }
    for key, rows in grouped.items():
        if {row["bucket_id"] for row in rows} != expected_buckets:
            return False
        eligible = score_eligible[key]
        if any(_int(row, "eligible_count") != eligible for row in rows):
            return False
        if sum(_int(row, "bucket_count") for row in rows) != eligible:
            return False
        ratio_sum = sum(_float(row, "bucket_ratio_of_eligible") for row in rows)
        if eligible > 0 and abs(ratio_sum - 1.0) > 1e-9:
            return False
    return True


def _reason_profile_integrity(rows: list[dict[str, str]]) -> bool:
    if not rows:
        return False
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        required = {
            "total_row_count",
            "reason_occurrence_count",
            "row_prevalence",
            "reason_occurrence_share",
        }
        if not required.issubset(row):
            return False
        total = _int(row, "total_row_count")
        occurrences = _int(row, "reason_occurrence_count")
        row_count = _int(row, "row_count")
        if total <= 0 or occurrences <= 0:
            return False
        if not _float_matches(_float_or_none(row, "row_prevalence"), row_count / total):
            return False
        if not _float_matches(
            _float_or_none(row, "reason_occurrence_share"),
            row_count / occurrences,
        ):
            return False
        grouped.setdefault(
            (
                row["source_level"],
                row["indicator_id"],
                row.get("raw_source_indicator_id", ""),
                row.get("W", ""),
            ),
            [],
        ).append(row)
    for group_rows in grouped.values():
        occurrence_total = _int(group_rows[0], "reason_occurrence_count")
        if sum(_int(row, "row_count") for row in group_rows) != occurrence_total:
            return False
        share_sum = sum(_float(row, "reason_occurrence_share") for row in group_rows)
        if abs(share_sum - 1.0) > 1e-9:
            return False
    return True


def _float_matches(actual: float | None, expected: float | None) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return abs(actual - expected) <= 1e-12


def _w_monotone(score_rows: list[dict[str, str]]) -> bool:
    by_indicator: dict[str, list[dict[str, str]]] = {}
    for row in score_rows:
        by_indicator.setdefault(row["indicator_id"], []).append(row)
    for rows in by_indicator.values():
        rows = sorted(rows, key=lambda row: int(row["W"]))
        eligible = [_int(row, "eligible_count") for row in rows]
        unknown = [
            _float(row, "unknown_count") / _float(row, "total_row_count")
            for row in rows
        ]
        if not (eligible[0] >= eligible[1] >= eligible[2]):
            return False
        if not (unknown[0] <= unknown[1] <= unknown[2]):
            return False
    return True


def _q_nested(
    hit_rows: list[dict[str, str]], threshold_rows: list[dict[str, str]]
) -> bool:
    by_indicator: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in hit_rows:
        by_indicator.setdefault((row["indicator_id"], row["W"]), []).append(row)
    for rows in by_indicator.values():
        rows = sorted(rows, key=lambda row: float(row["q"]))
        hits = [_int(row, "hit_true_day_count") for row in rows]
        if not (hits[0] <= hits[1] <= hits[2]):
            return False
    by_layer: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in threshold_rows:
        by_layer.setdefault((row["layer"], row["W"]), []).append(row)
    for rows in by_layer.values():
        rows = sorted(rows, key=lambda row: float(row["q"]))
        both = [_int(row, "both_hit") for row in rows]
        neither = [_int(row, "neither") for row in rows]
        if not (both[0] <= both[1] <= both[2]):
            return False
        if not (neither[0] >= neither[1] >= neither[2]):
            return False
    return True


def _contains_forbidden_tokens(paths: dict[str, Path], root: Path) -> bool:
    forbidden = (
        "future_return",
        "backtest",
        "portfolio",
        "trade_signal",
        "best_indicator",
        "best_layer",
        "best_config",
        "winner",
        "optimized_q",
        "freeze_candidate",
    )
    for path in paths.values():
        if path.suffix not in (".csv", ".json") or not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        if any(token in text for token in forbidden):
            return True
    return False


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
    keys = list(rows[0])
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=keys, extrasaction="raise", lineterminator="\n"
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


def _float_or_none(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    return None if value in (None, "") else float(value)


def _fmt_float(value: float) -> str:
    return format(value, ".17g")


def _safe_div(
    numerator: int | float | None, denominator: int | float | None
) -> float | None:
    return (
        None
        if numerator is None or denominator in (None, 0)
        else float(numerator) / float(denominator)
    )


def _q_label(value: str) -> str:
    return str(int(round(float(value) * 100)))


def _sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int | float):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
