from __future__ import annotations

# ruff: noqa: E501
import csv
import json
import math
import platform
import subprocess
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r1/r1_t09_year_stability_concentration.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t09_year_stability_concentration.schema.json"
TASK_ID = "R1-T09"
YEARS = tuple(range(2016, 2027))
STEPS = (
    ("C_GIVEN_P", "P", "C", "S_PC", "P,C"),
    ("T_GIVEN_PC", "S_PC", "T", "S_PCT", "P,C,T"),
    ("V_GIVEN_PCT", "S_PCT", "V", "S_PCVT", "P,C,T,V"),
)
ARTIFACT_NAMES = (
    "r1_t09_candidate_registry.csv",
    "r1_t09_year_state_profile.csv",
    "r1_t09_year_interval_profile.csv",
    "r1_t09_calendar_year_clipped_geometry.csv",
    "r1_t09_year_interlayer_profile.csv",
    "r1_t09_year_concentration_summary.csv",
    "r1_t09_leave_one_year_out.csv",
    "r1_t09_reference_challenger_year_comparison.csv",
    "r1_t09_upstream_reconciliation.csv",
    "r1_t09_anomaly_scan.json",
    "r1_t09_diagnostic_summary.json",
    "r1_t09_experiment_summary.json",
)


class R1T09Error(RuntimeError):
    pass


def run_r1_t09_year_stability_concentration(
    *,
    config_path: Path,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    verify_input_hashes: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    config = _load_json(config_path)
    Draft202012Validator(_load_json(SCHEMA_PATH)).validate(config)
    _validate_frozen_registry(config)
    _check_prerequisites(config, verify_input_hashes=verify_input_hashes)
    output_dir.mkdir(parents=True, exist_ok=False)

    import duckdb  # noqa: PLC0415

    con = duckdb.connect()
    con.execute(f"SET threads={int(config['parallelism']['duckdb_threads'])}")
    con.execute("SET memory_limit=?", [config["parallelism"]["duckdb_memory_limit"]])
    _attach_inputs(con, config)
    _create_candidate_registry(con, config)
    _create_dimension_wide(con)

    registry = _registry_rows(config)
    _write_csv(output_dir / "r1_t09_candidate_registry.csv", registry)
    state_rows = _year_state_rows(con, run_id, code_commit)
    interval_rows = _year_interval_rows(con, run_id, code_commit)
    clipped_rows = _calendar_clipped_rows(con, run_id, code_commit)
    interlayer_rows = _year_interlayer_rows(con, config, run_id, code_commit)
    concentration_rows = build_concentration_summary(
        state_rows, interval_rows, interlayer_rows, config
    )
    loyo_rows = build_leave_one_year_out(
        state_rows, interval_rows, interlayer_rows, config
    )
    comparison_rows = build_reference_challenger_comparison(state_rows, interval_rows)
    reconciliation_rows = _upstream_reconciliation(
        con,
        config,
        registry,
        state_rows,
        interval_rows,
        interlayer_rows,
        concentration_rows,
    )
    con.close()

    _write_csv(output_dir / "r1_t09_year_state_profile.csv", state_rows)
    _write_csv(output_dir / "r1_t09_year_interval_profile.csv", interval_rows)
    _write_csv(output_dir / "r1_t09_calendar_year_clipped_geometry.csv", clipped_rows)
    _write_csv(output_dir / "r1_t09_year_interlayer_profile.csv", interlayer_rows)
    _write_csv(output_dir / "r1_t09_year_concentration_summary.csv", concentration_rows)
    _write_csv(output_dir / "r1_t09_leave_one_year_out.csv", loyo_rows)
    _write_csv(
        output_dir / "r1_t09_reference_challenger_year_comparison.csv",
        comparison_rows,
    )
    _write_csv(output_dir / "r1_t09_upstream_reconciliation.csv", reconciliation_rows)

    anomaly = _build_anomaly_scan(
        run_id,
        code_commit,
        state_rows,
        interval_rows,
        interlayer_rows,
        concentration_rows,
        loyo_rows,
        reconciliation_rows,
    )
    dependencies = {
        "python_version": platform.python_version(),
        "duckdb_version": duckdb.__version__,
        "jsonschema_version": _dependency_version("jsonschema"),
    }
    diagnostic = _build_diagnostic_summary(
        run_id,
        code_commit,
        config,
        state_rows,
        interval_rows,
        clipped_rows,
        interlayer_rows,
        concentration_rows,
        loyo_rows,
        comparison_rows,
        reconciliation_rows,
        anomaly,
        dependencies,
        time.perf_counter() - started,
    )
    _write_json(output_dir / "r1_t09_anomaly_scan.json", anomaly)
    _write_json(output_dir / "r1_t09_diagnostic_summary.json", diagnostic)
    summary = _build_experiment_summary(
        config,
        config_path,
        output_dir,
        run_id,
        code_commit,
        dependencies,
        time.perf_counter() - started,
        anomaly,
    )
    _write_json(output_dir / "r1_t09_experiment_summary.json", summary)
    return summary


def _attach_inputs(con: Any, config: Mapping[str, Any]) -> None:
    for key, alias in (
        ("dimension_state", "dimdb"),
        ("nested_daily_state", "nesteddb"),
        ("daily_confirmation", "dailydb"),
        ("confirmed_interval", "intervaldb"),
    ):
        path = ROOT / config["input_artifacts"][key]["path"]
        con.execute(f"ATTACH '{_sql_path(path)}' AS {alias} (READ_ONLY)")


def _create_candidate_registry(con: Any, config: Mapping[str, Any]) -> None:
    values = []
    for row in config["candidate_registry"]:
        values.append(
            "("
            + ",".join(
                (
                    _sql_string(row["candidate_config_id"]),
                    _sql_string(row["state_line"]),
                    str(int(row["W"])),
                    str(float(row["q"])),
                    str(int(row["K"])),
                    _sql_string(row["primary_role"]),
                )
            )
            + ")"
        )
    con.execute(
        "CREATE TEMP TABLE candidate_registry AS SELECT * FROM (VALUES "
        + ",".join(values)
        + ") AS t(candidate_config_id,state_line,W,q,K,primary_role)"
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
          bool_or(dimension='V' AND dimension_active_weak IS TRUE) AS V_active
        FROM dimdb.r0_t06_dimension_state_results
        WHERE percentile_window_W IN (120,250) AND abs(q-0.2)<1e-12
        GROUP BY security_id, trading_date, percentile_window_W, q
        """
    )


def _year_state_rows(con: Any, run_id: str, code_commit: str) -> list[dict[str, Any]]:
    query = f"""
    WITH filtered AS (
      SELECT c.candidate_config_id, c.state_line, c.W, c.q, c.K, c.primary_role,
        d.security_id, d.trading_date, substr(d.trading_date,1,4)::INTEGER AS year,
        d.raw_state, d.confirmed_state, d.validity_status,
        lag(d.raw_state) OVER (
          PARTITION BY c.candidate_config_id,c.state_line,d.security_id
          ORDER BY d.trading_date
        ) AS previous_raw_state
      FROM candidate_registry c
      JOIN dailydb.r0_t07_daily_confirmation_results d
        ON d.percentile_window_W=c.W AND abs(d.q-c.q)<1e-12
       AND d.confirmation_k=c.K AND d.state_name=c.state_line
    ), a AS (
      SELECT candidate_config_id,state_line,W,q,K,primary_role,year,
        count(*)::BIGINT AS eligible_trading_days,
        count(*) FILTER (WHERE validity_status='valid')::BIGINT AS valid_day_count,
        count(*) FILTER (WHERE validity_status='unknown')::BIGINT AS unknown_day_count,
        count(*) FILTER (WHERE validity_status='blocked')::BIGINT AS blocked_day_count,
        count(*) FILTER (WHERE validity_status='diagnostic_required')::BIGINT AS diagnostic_required_day_count,
        count(*) FILTER (WHERE raw_state IS TRUE)::BIGINT AS raw_state_true_count,
        count(*) FILTER (WHERE raw_state IS FALSE)::BIGINT AS raw_state_false_count,
        count(*) FILTER (WHERE raw_state IS NULL)::BIGINT AS raw_state_null_count,
        count(DISTINCT security_id) FILTER (WHERE raw_state IS TRUE)::BIGINT AS raw_unique_security_count,
        count(*) FILTER (WHERE raw_state IS TRUE AND previous_raw_state IS DISTINCT FROM TRUE)::BIGINT AS raw_onset_count,
        count(*) FILTER (WHERE confirmed_state IS TRUE)::BIGINT AS confirmed_state_true_count,
        count(*) FILTER (WHERE confirmed_state IS FALSE)::BIGINT AS confirmed_state_false_count,
        count(*) FILTER (WHERE confirmed_state IS NULL)::BIGINT AS confirmed_state_null_count,
        count(DISTINCT security_id) FILTER (WHERE confirmed_state IS TRUE)::BIGINT AS confirmed_unique_security_count
      FROM filtered
      GROUP BY candidate_config_id,state_line,W,q,K,primary_role,year
    )
    SELECT '{TASK_ID}' AS task_id, '{run_id}' AS run_id, '{code_commit}' AS code_commit,
      *,
      raw_state_true_count::DOUBLE/eligible_trading_days AS raw_coverage,
      CASE WHEN valid_day_count=0 THEN NULL ELSE raw_state_true_count::DOUBLE/valid_day_count END AS raw_valid_hit_rate,
      confirmed_state_true_count::DOUBLE/eligible_trading_days AS confirmed_coverage,
      CASE WHEN valid_day_count=0 THEN NULL ELSE confirmed_state_true_count::DOUBLE/valid_day_count END AS confirmed_valid_hit_rate,
      eligible_trading_days::DOUBLE/sum(eligible_trading_days) OVER (PARTITION BY candidate_config_id,state_line) AS denominator_share,
      valid_day_count::DOUBLE/nullif(sum(valid_day_count) OVER (PARTITION BY candidate_config_id,state_line),0) AS valid_denominator_share,
      raw_state_true_count::DOUBLE/nullif(sum(raw_state_true_count) OVER (PARTITION BY candidate_config_id,state_line),0) AS raw_state_year_share,
      confirmed_state_true_count::DOUBLE/nullif(sum(confirmed_state_true_count) OVER (PARTITION BY candidate_config_id,state_line),0) AS confirmed_state_year_share,
      year=2026 AS partial_year_observation
    FROM a ORDER BY state_line,W,year
    """
    return _query_dicts(con, query)


def _year_interval_rows(
    con: Any, run_id: str, code_commit: str
) -> list[dict[str, Any]]:
    query = f"""
    WITH grid AS (
      SELECT c.*, y.year
      FROM candidate_registry c
      CROSS JOIN (SELECT * FROM range(2016,2027) t(year)) y
    ), a AS (
      SELECT c.candidate_config_id,c.state_line,c.W,c.q,c.K,c.primary_role,
        substr(i.confirmation_date,1,4)::INTEGER AS year,
        count(*)::BIGINT AS confirmed_interval_count,
        sum(i.confirmed_duration_observations)::BIGINT AS confirmed_interval_total_duration,
        avg(i.confirmed_duration_observations) AS confirmed_interval_mean_duration,
        median(i.confirmed_duration_observations) AS confirmed_interval_median_duration,
        quantile_cont(i.confirmed_duration_observations,0.10) AS confirmed_interval_q10,
        quantile_cont(i.confirmed_duration_observations,0.25) AS confirmed_interval_q25,
        quantile_cont(i.confirmed_duration_observations,0.75) AS confirmed_interval_q75,
        quantile_cont(i.confirmed_duration_observations,0.90) AS confirmed_interval_q90,
        max(i.confirmed_duration_observations)::BIGINT AS confirmed_interval_max,
        count(*) FILTER (WHERE i.confirmed_duration_observations=1)::BIGINT AS single_day_fragment_count,
        count(*) FILTER (WHERE i.is_open_interval IS TRUE)::BIGINT AS open_interval_count,
        count(*) FILTER (WHERE substr(i.confirmation_date,1,4) != substr(coalesce(i.interval_end_date,i.last_observed_date),1,4))::BIGINT AS cross_year_interval_count
      FROM candidate_registry c
      JOIN intervaldb.r0_t07_confirmed_interval_results i
        ON i.percentile_window_W=c.W AND abs(i.q-c.q)<1e-12
       AND i.confirmation_k=c.K AND i.state_name=c.state_line
      GROUP BY c.candidate_config_id,c.state_line,c.W,c.q,c.K,c.primary_role,substr(i.confirmation_date,1,4)
    )
    SELECT '{TASK_ID}' AS task_id,'{run_id}' AS run_id,'{code_commit}' AS code_commit,
      g.candidate_config_id,g.state_line,g.W,g.q,g.K,g.primary_role,g.year,
      coalesce(a.confirmed_interval_count,0)::BIGINT AS confirmed_interval_count,
      coalesce(a.confirmed_interval_total_duration,0)::BIGINT AS confirmed_interval_total_duration,
      a.confirmed_interval_mean_duration,a.confirmed_interval_median_duration,
      a.confirmed_interval_q10,a.confirmed_interval_q25,a.confirmed_interval_q75,a.confirmed_interval_q90,a.confirmed_interval_max,
      coalesce(a.single_day_fragment_count,0)::BIGINT AS single_day_fragment_count,
      CASE WHEN coalesce(a.confirmed_interval_count,0)=0 THEN NULL ELSE a.single_day_fragment_count::DOUBLE/a.confirmed_interval_count END AS fragment_rate,
      coalesce(a.open_interval_count,0)::BIGINT AS open_interval_count,
      CASE WHEN coalesce(a.confirmed_interval_count,0)=0 THEN NULL ELSE a.open_interval_count::DOUBLE/a.confirmed_interval_count END AS open_interval_ratio,
      coalesce(a.cross_year_interval_count,0)::BIGINT AS cross_year_interval_count,
      CASE WHEN coalesce(a.confirmed_interval_count,0)=0 THEN NULL ELSE a.cross_year_interval_count::DOUBLE/a.confirmed_interval_count END AS cross_year_interval_ratio,
      coalesce(a.confirmed_interval_count,0)::DOUBLE/nullif(sum(coalesce(a.confirmed_interval_count,0)) OVER (PARTITION BY g.candidate_config_id,g.state_line),0) AS interval_year_share,
      g.year=2026 AS partial_year_observation,
      'confirmation_year_full_interval' AS interval_year_semantics
    FROM grid g LEFT JOIN a USING(candidate_config_id,state_line,W,q,K,primary_role,year)
    ORDER BY g.state_line,g.W,g.year
    """
    return _query_dicts(con, query)


def _calendar_clipped_rows(
    con: Any, run_id: str, code_commit: str
) -> list[dict[str, Any]]:
    query = f"""
    WITH grid AS (
      SELECT c.*, y.year FROM candidate_registry c
      CROSS JOIN (SELECT * FROM range(2016,2027) t(year)) y
    ), marked AS (
      SELECT c.candidate_config_id,c.state_line,c.W,c.q,c.K,c.primary_role,
        d.security_id,d.trading_date,substr(d.trading_date,1,4)::INTEGER AS year,d.confirmed_state,
        CASE WHEN d.confirmed_state IS TRUE AND lag(d.confirmed_state) OVER (
          PARTITION BY c.candidate_config_id,c.state_line,d.security_id,substr(d.trading_date,1,4)
          ORDER BY d.trading_date
        ) IS DISTINCT FROM TRUE THEN 1 ELSE 0 END AS new_segment
      FROM candidate_registry c
      JOIN dailydb.r0_t07_daily_confirmation_results d
        ON d.percentile_window_W=c.W AND abs(d.q-c.q)<1e-12
       AND d.confirmation_k=c.K AND d.state_name=c.state_line
    ), islands AS (
      SELECT *,sum(new_segment) OVER (
        PARTITION BY candidate_config_id,state_line,security_id,year ORDER BY trading_date
      ) AS segment_id
      FROM marked
    ), segments AS (
      SELECT candidate_config_id,state_line,W,q,K,primary_role,security_id,year,segment_id,
        count(*)::BIGINT AS duration
      FROM islands WHERE confirmed_state IS TRUE
      GROUP BY candidate_config_id,state_line,W,q,K,primary_role,security_id,year,segment_id
    ), a AS (
      SELECT candidate_config_id,state_line,W,q,K,primary_role,year,
        count(*)::BIGINT AS segment_count,sum(duration)::BIGINT AS duration_total,
        avg(duration) AS mean_duration,median(duration) AS median_duration,
        quantile_cont(duration,0.10) AS q10,quantile_cont(duration,0.25) AS q25,
        quantile_cont(duration,0.75) AS q75,quantile_cont(duration,0.90) AS q90,
        max(duration)::BIGINT AS max_duration,
        count(*) FILTER (WHERE duration=1)::BIGINT AS fragment_count
      FROM segments GROUP BY candidate_config_id,state_line,W,q,K,primary_role,year
    )
    SELECT '{TASK_ID}' AS task_id,'{run_id}' AS run_id,'{code_commit}' AS code_commit,
      g.candidate_config_id,g.state_line,g.W,g.q,g.K,g.primary_role,g.year,
      coalesce(a.segment_count,0)::BIGINT AS calendar_year_clipped_segment_count,
      coalesce(a.duration_total,0)::BIGINT AS calendar_year_clipped_duration_total,
      a.mean_duration AS calendar_year_clipped_mean_duration,
      a.median_duration AS calendar_year_clipped_median_duration,
      a.q10 AS calendar_year_clipped_q10,a.q25 AS calendar_year_clipped_q25,
      a.q75 AS calendar_year_clipped_q75,a.q90 AS calendar_year_clipped_q90,
      a.max_duration AS calendar_year_clipped_max_duration,
      coalesce(a.fragment_count,0)::BIGINT AS calendar_year_clipped_fragment_count,
      CASE WHEN coalesce(a.segment_count,0)=0 THEN NULL ELSE a.fragment_count::DOUBLE/a.segment_count END AS calendar_year_clipped_fragment_rate,
      g.year=2026 AS partial_year_observation,
      'trading_year_clipped_confirmed_runs' AS geometry_semantics
    FROM grid g LEFT JOIN a USING(candidate_config_id,state_line,W,q,K,primary_role,year)
    ORDER BY g.state_line,g.W,g.year
    """
    return _query_dicts(con, query)


def _year_interlayer_rows(
    con: Any, config: Mapping[str, Any], run_id: str, code_commit: str
) -> list[dict[str, Any]]:
    small_n = int(config["status_rules"]["small_denominator_N"])
    small_anchor = int(config["status_rules"]["small_anchor_count"])
    query = f"""
    WITH step_registry AS (
      SELECT * FROM (VALUES
        ('C_GIVEN_P','P','C','S_PC','P,C'),
        ('T_GIVEN_PC','S_PC','T','S_PCT','P,C,T'),
        ('V_GIVEN_PCT','S_PCT','V','S_PCVT','P,C,T,V')
      ) t(step_id,anchor_state,target_dimension,child_state,required_dimensions)
    ), grid AS (
      SELECT s.*,w.W,0.2::DOUBLE AS q,y.year
      FROM step_registry s CROSS JOIN (VALUES (120),(250)) w(W)
      CROSS JOIN (SELECT * FROM range(2016,2027) t(year)) y
    ), projected AS (
      SELECT s.*,d.security_id,d.trading_date,d.W,d.q,substr(d.trading_date,1,4)::INTEGER AS year,
        CASE s.step_id
          WHEN 'C_GIVEN_P' THEN d.P_valid AND d.C_valid
          WHEN 'T_GIVEN_PC' THEN d.P_valid AND d.C_valid AND d.T_valid
          WHEN 'V_GIVEN_PCT' THEN d.P_valid AND d.C_valid AND d.T_valid AND d.V_valid END AS denominator,
        CASE s.step_id
          WHEN 'C_GIVEN_P' THEN d.P_active
          WHEN 'T_GIVEN_PC' THEN d.P_active AND d.C_active
          WHEN 'V_GIVEN_PCT' THEN d.P_active AND d.C_active AND d.T_active END AS anchor_active,
        CASE s.step_id WHEN 'C_GIVEN_P' THEN d.C_active WHEN 'T_GIVEN_PC' THEN d.T_active WHEN 'V_GIVEN_PCT' THEN d.V_active END AS target_active
      FROM dimension_wide d CROSS JOIN step_registry s
    ), a AS (
      SELECT step_id,anchor_state,target_dimension,child_state,required_dimensions,W,q,year,
        count(*)::BIGINT AS N,
        count(*) FILTER (WHERE anchor_active IS TRUE AND target_active IS TRUE)::BIGINT AS n11,
        count(*) FILTER (WHERE anchor_active IS TRUE AND target_active IS FALSE)::BIGINT AS n10,
        count(*) FILTER (WHERE anchor_active IS FALSE AND target_active IS TRUE)::BIGINT AS n01,
        count(*) FILTER (WHERE anchor_active IS FALSE AND target_active IS FALSE)::BIGINT AS n00
      FROM projected WHERE denominator IS TRUE
      GROUP BY step_id,anchor_state,target_dimension,child_state,required_dimensions,W,q,year
    ), counts AS (
      SELECT g.step_id,g.anchor_state,g.target_dimension,g.child_state,g.required_dimensions,g.W,g.q,g.year,
        coalesce(a.N,0)::BIGINT AS N,coalesce(a.n11,0)::BIGINT AS n11,
        coalesce(a.n10,0)::BIGINT AS n10,coalesce(a.n01,0)::BIGINT AS n01,coalesce(a.n00,0)::BIGINT AS n00
      FROM grid g LEFT JOIN a USING(step_id,anchor_state,target_dimension,child_state,required_dimensions,W,q,year)
    ), metrics AS (
      SELECT *,n11+n10 AS anchor_true_count,n01+n00 AS anchor_false_count,
        n11+n01 AS target_true_count,n10+n00 AS target_false_count,n11 AS child_true_count
      FROM counts
    ), rates AS (
      SELECT *,CASE WHEN anchor_true_count=0 THEN NULL ELSE n11::DOUBLE/anchor_true_count END AS retention,
        CASE WHEN N=0 THEN NULL ELSE target_true_count::DOUBLE/N END AS target_marginal_rate,
        CASE WHEN anchor_false_count=0 THEN NULL ELSE n01::DOUBLE/anchor_false_count END AS nonanchor_target_rate
      FROM metrics
    )
    SELECT '{TASK_ID}' AS task_id,'{run_id}' AS run_id,'{code_commit}' AS code_commit,
      *,
      CASE WHEN retention IS NULL OR target_marginal_rate=0 THEN NULL ELSE retention/target_marginal_rate END AS association_lift,
      CASE WHEN retention IS NULL OR target_marginal_rate IS NULL THEN NULL ELSE retention-target_marginal_rate END AS absolute_increment,
      CASE WHEN retention IS NULL OR nonanchor_target_rate IS NULL THEN NULL ELSE retention-nonanchor_target_rate END AS delta_nonanchor,
      N::DOUBLE/nullif(sum(N) OVER (PARTITION BY step_id,W,q),0) AS step_denominator_year_share,
      anchor_true_count::DOUBLE/nullif(sum(anchor_true_count) OVER (PARTITION BY step_id,W,q),0) AS anchor_year_share,
      child_true_count::DOUBLE/nullif(sum(child_true_count) OVER (PARTITION BY step_id,W,q),0) AS child_year_share,
      CASE WHEN N=0 OR anchor_true_count=0 THEN 'undefined_denominator'
           WHEN N<{small_n} OR anchor_true_count<{small_anchor} THEN 'small_denominator_warning'
           ELSE 'computed' END AS step_status,
      concat_ws(';',CASE WHEN N>0 AND (N<{small_n} OR anchor_true_count<{small_anchor}) THEN 'small_denominator_warning' END,
        CASE WHEN year=2026 THEN 'partial_year_observation' END) AS warnings,
      year=2026 AS partial_year_observation
    FROM rates ORDER BY step_id,W,year
    """
    return _query_dicts(con, query)


def concentration_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    count_key: str,
    eligible_key: str,
    valid_key: str,
    coverage_key: str,
) -> dict[str, Any]:
    counts = [int(row[count_key]) for row in rows]
    eligible = [int(row[eligible_key]) for row in rows]
    valid = [int(row[valid_key]) for row in rows]
    total = sum(counts)
    total_eligible = sum(eligible)
    total_valid = sum(valid)
    shares = [value / total if total else 0.0 for value in counts]
    eligible_shares = [
        value / total_eligible if total_eligible else 0.0 for value in eligible
    ]
    valid_shares = [value / total_valid if total_valid else 0.0 for value in valid]
    hhi = sum(value * value for value in shares) if total else None
    coverages = sorted(
        float(row[coverage_key]) for row in rows if row.get(coverage_key) is not None
    )
    peak_index = max(range(len(rows)), key=lambda index: (counts[index], -index))
    coverage_peak_index = max(
        range(len(rows)),
        key=lambda index: (
            -math.inf
            if rows[index].get(coverage_key) is None
            else float(rows[index][coverage_key]),
            -index,
        ),
    )
    return {
        "nonzero_year_count": sum(value > 0 for value in counts),
        "evaluable_year_count": sum(value > 0 for value in eligible),
        "zero_state_year_count": sum(value == 0 for value in counts),
        "max_year_state_share": max(shares, default=0.0),
        "top2_year_state_share": sum(sorted(shares, reverse=True)[:2]),
        "year_hhi": hhi,
        "effective_year_count": None if not hhi else 1.0 / hhi,
        "max_year_eligible_share": max(eligible_shares, default=0.0),
        "max_year_valid_share": max(valid_shares, default=0.0),
        "state_share_minus_eligible_share_at_peak": shares[peak_index]
        - eligible_shares[peak_index],
        "coverage_min": min(coverages) if coverages else None,
        "coverage_q25": _quantile(coverages, 0.25),
        "coverage_median": _quantile(coverages, 0.5),
        "coverage_q75": _quantile(coverages, 0.75),
        "coverage_max": max(coverages) if coverages else None,
        "coverage_iqr": None
        if not coverages
        else _quantile(coverages, 0.75) - _quantile(coverages, 0.25),
        "peak_state_year": int(rows[peak_index]["year"]),
        "peak_coverage_year": int(rows[coverage_peak_index]["year"]),
    }


def build_concentration_summary(
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    interlayer_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    majority = float(config["status_rules"]["single_year_majority_threshold"])
    min_years = int(config["status_rules"]["minimum_evaluable_years"])
    min_nonzero = int(config["status_rules"]["minimum_nonzero_years"])
    grouped_state = _group(state_rows, ("candidate_config_id", "state_line"))
    grouped_interval = _group(interval_rows, ("candidate_config_id", "state_line"))
    for key, rows in grouped_state.items():
        for level in ("raw", "confirmed"):
            metrics = concentration_metrics(
                rows,
                count_key=f"{level}_state_true_count",
                eligible_key="eligible_trading_days",
                valid_key="valid_day_count",
                coverage_key=f"{level}_coverage",
            )
            interval_shares = [
                float(row["interval_year_share"] or 0.0)
                for row in grouped_interval[key]
            ]
            warnings = []
            if metrics["max_year_state_share"] > majority:
                warnings.append("single_year_majority_warning")
            if level == "confirmed" and max(interval_shares, default=0.0) > majority:
                warnings.append("single_year_interval_majority_warning")
            if (
                metrics["evaluable_year_count"] < min_years
                or metrics["nonzero_year_count"] < min_nonzero
            ):
                status = "insufficient_year_coverage"
            elif warnings:
                status = "year_stability_supported_with_warning"
            else:
                status = "year_stability_supported"
            first = rows[0]
            result.append(
                {
                    "summary_scope": "candidate_state",
                    "candidate_config_id": key[0],
                    "state_line": key[1],
                    "W": first["W"],
                    "q": first["q"],
                    "K": first["K"],
                    "analysis_level": level,
                    **metrics,
                    "max_year_interval_share": max(interval_shares, default=0.0),
                    "candidate_stability_status": status,
                    "warnings": ";".join(warnings),
                }
            )
    for key, rows in _group(interlayer_rows, ("step_id", "W", "q")).items():
        deltas = [row.get("absolute_increment") for row in rows]
        lifts = [row.get("association_lift") for row in rows]
        valid_deltas = [float(value) for value in deltas if value is not None]
        positive = sum(value > 0 for value in valid_deltas)
        negative = sum(value < 0 for value in valid_deltas)
        positive_lift = sum(float(value) > 1 for value in lifts if value is not None)
        negative_lift = sum(float(value) < 1 for value in lifts if value is not None)
        warnings = []
        if positive and negative or positive_lift and negative_lift:
            warnings.append("year_direction_conflict_warning")
        if max(float(row["child_year_share"] or 0) for row in rows) > majority:
            warnings.append("single_year_majority_warning")
        weights = [
            int(row["N"]) for row in rows if row.get("absolute_increment") is not None
        ]
        weighted = (
            sum(
                float(row["absolute_increment"]) * int(row["N"])
                for row in rows
                if row.get("absolute_increment") is not None
            )
            / sum(weights)
            if sum(weights)
            else None
        )
        result.append(
            {
                "summary_scope": "interlayer_step",
                "step_id": key[0],
                "W": key[1],
                "q": key[2],
                "positive_delta_year_count": positive,
                "negative_delta_year_count": negative,
                "zero_delta_year_count": sum(value == 0 for value in valid_deltas),
                "undefined_delta_year_count": sum(value is None for value in deltas),
                "positive_lift_excess_year_count": positive_lift,
                "negative_lift_excess_year_count": negative_lift,
                "max_year_denominator_share": max(
                    float(row["step_denominator_year_share"] or 0) for row in rows
                ),
                "max_year_child_share": max(
                    float(row["child_year_share"] or 0) for row in rows
                ),
                "delta_weighted_mean": weighted,
                "delta_unweighted_median": _quantile(sorted(valid_deltas), 0.5),
                "min_year_delta": min(valid_deltas) if valid_deltas else None,
                "max_year_delta": max(valid_deltas) if valid_deltas else None,
                "candidate_stability_status": "year_stability_supported_with_warning"
                if warnings
                else "year_stability_supported",
                "warnings": ";".join(warnings),
            }
        )
    return result


def _step_metrics(n11: int, n10: int, n01: int, n00: int) -> dict[str, Any]:
    n = n11 + n10 + n01 + n00
    anchor = n11 + n10
    target = n11 + n01
    retention = n11 / anchor if anchor else None
    marginal = target / n if n else None
    lift = retention / marginal if retention is not None and marginal else None
    delta = (
        retention - marginal if retention is not None and marginal is not None else None
    )
    return {
        "N": n,
        "retention": retention,
        "target_marginal": marginal,
        "lift": lift,
        "delta": delta,
    }


def metric_sign(value: Any, tolerance: float = 1e-12, *, center: float = 0.0) -> str:
    if value is None:
        return "undefined"
    difference = float(value) - center
    if difference > tolerance:
        return "positive"
    if difference < -tolerance:
        return "negative"
    return "zero"


def build_leave_one_year_out(
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    interlayer_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    tolerance = float(config["status_rules"]["sign_zero_tolerance"])
    result: list[dict[str, Any]] = []
    interval_groups = _group(interval_rows, ("candidate_config_id", "state_line"))
    for key, rows in _group(state_rows, ("candidate_config_id", "state_line")).items():
        total_state = sum(int(row["confirmed_state_true_count"]) for row in rows)
        total_eligible = sum(int(row["eligible_trading_days"]) for row in rows)
        total_intervals = sum(
            int(row["confirmed_interval_count"]) for row in interval_groups[key]
        )
        pooled_coverage = total_state / total_eligible if total_eligible else None
        for removed in rows:
            remaining = [row for row in rows if row["year"] != removed["year"]]
            state_without = total_state - int(removed["confirmed_state_true_count"])
            eligible_without = total_eligible - int(removed["eligible_trading_days"])
            interval_removed = next(
                row for row in interval_groups[key] if row["year"] == removed["year"]
            )
            intervals_without = total_intervals - int(
                interval_removed["confirmed_interval_count"]
            )
            shares = [
                int(row["confirmed_state_true_count"]) / state_without
                if state_without
                else 0.0
                for row in remaining
            ]
            coverage_without = (
                state_without / eligible_without if eligible_without else None
            )
            pooled_sign = metric_sign(total_state, tolerance)
            leave_sign = metric_sign(state_without, tolerance)
            result.append(
                {
                    "scope_type": "candidate_state",
                    "candidate_config_id": key[0],
                    "state_line": key[1],
                    "W": removed["W"],
                    "q": removed["q"],
                    "K": removed["K"],
                    "removed_year": removed["year"],
                    "confirmed_state_days_without_year": state_without,
                    "confirmed_coverage_without_year": coverage_without,
                    "confirmed_interval_count_without_confirmation_year": intervals_without,
                    "max_remaining_year_share": max(shares, default=0.0),
                    "remaining_year_hhi": sum(value * value for value in shares)
                    if state_without
                    else None,
                    "pooled_sign": pooled_sign,
                    "leave_one_out_sign": leave_sign,
                    "sign_flip": pooled_sign != leave_sign,
                    "relative_count_change": _relative_change(
                        state_without, total_state
                    ),
                    "relative_metric_change": _relative_change(
                        coverage_without, pooled_coverage
                    ),
                    "removed_year_denominator_share": int(
                        removed["eligible_trading_days"]
                    )
                    / total_eligible
                    if total_eligible
                    else None,
                    "removed_year_state_or_child_share": int(
                        removed["confirmed_state_true_count"]
                    )
                    / total_state
                    if total_state
                    else None,
                    "partial_year_removed": int(removed["year"]) == 2026,
                }
            )
    for key, rows in _group(interlayer_rows, ("step_id", "W", "q")).items():
        totals = {
            name: sum(int(row[name]) for row in rows)
            for name in ("n11", "n10", "n01", "n00")
        }
        pooled = _step_metrics(**totals)
        total_child = totals["n11"]
        for removed in rows:
            counts = {
                name: totals[name] - int(removed[name])
                for name in ("n11", "n10", "n01", "n00")
            }
            metrics = _step_metrics(**counts)
            pooled_delta_sign = metric_sign(pooled["delta"], tolerance)
            loyo_delta_sign = metric_sign(metrics["delta"], tolerance)
            pooled_lift_sign = metric_sign(pooled["lift"], tolerance, center=1.0)
            loyo_lift_sign = metric_sign(metrics["lift"], tolerance, center=1.0)
            result.append(
                {
                    "scope_type": "interlayer_step",
                    "step_id": key[0],
                    "W": key[1],
                    "q": key[2],
                    "removed_year": removed["year"],
                    "N_without_year": metrics["N"],
                    "n11_without_year": counts["n11"],
                    "n10_without_year": counts["n10"],
                    "n01_without_year": counts["n01"],
                    "n00_without_year": counts["n00"],
                    "retention_without_year": metrics["retention"],
                    "target_marginal_without_year": metrics["target_marginal"],
                    "lift_without_year": metrics["lift"],
                    "delta_without_year": metrics["delta"],
                    "pooled_sign": f"delta:{pooled_delta_sign}|lift_excess:{pooled_lift_sign}",
                    "leave_one_out_sign": f"delta:{loyo_delta_sign}|lift_excess:{loyo_lift_sign}",
                    "pooled_delta_sign": pooled_delta_sign,
                    "leave_one_out_delta_sign": loyo_delta_sign,
                    "pooled_lift_excess_sign": pooled_lift_sign,
                    "leave_one_out_lift_excess_sign": loyo_lift_sign,
                    "sign_flip": pooled_delta_sign != loyo_delta_sign
                    or pooled_lift_sign != loyo_lift_sign,
                    "relative_count_change": _relative_change(
                        metrics["N"], pooled["N"]
                    ),
                    "relative_metric_change": _relative_change(
                        metrics["delta"], pooled["delta"]
                    ),
                    "removed_year_denominator_share": int(removed["N"]) / pooled["N"]
                    if pooled["N"]
                    else None,
                    "removed_year_state_or_child_share": int(
                        removed["child_true_count"]
                    )
                    / total_child
                    if total_child
                    else None,
                    "partial_year_removed": int(removed["year"]) == 2026,
                }
            )
    return result


def build_reference_challenger_comparison(
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    state_index = {
        (row["state_line"], int(row["W"]), int(row["year"])): row for row in state_rows
    }
    interval_index = {
        (row["state_line"], int(row["W"]), int(row["year"])): row
        for row in interval_rows
    }
    result = []
    for state_line in ("S_PCT", "S_PCVT"):
        for year in YEARS:
            challenger = state_index[(state_line, 120, year)]
            reference = state_index[(state_line, 250, year)]
            challenger_i = interval_index[(state_line, 120, year)]
            reference_i = interval_index[(state_line, 250, year)]
            availability_difference = int(challenger["valid_day_count"]) - int(
                reference["valid_day_count"]
            )
            warnings = ["partial_year_observation"] if year == 2026 else []
            if availability_difference != 0:
                warnings.append("availability_difference_requires_caution")
            result.append(
                {
                    "state_line": state_line,
                    "year": year,
                    "W120_eligible_days": challenger["eligible_trading_days"],
                    "W250_eligible_days": reference["eligible_trading_days"],
                    "W120_valid_days": challenger["valid_day_count"],
                    "W250_valid_days": reference["valid_day_count"],
                    "W120_confirmed_coverage": challenger["confirmed_coverage"],
                    "W250_confirmed_coverage": reference["confirmed_coverage"],
                    "coverage_difference": float(challenger["confirmed_coverage"])
                    - float(reference["confirmed_coverage"]),
                    "coverage_ratio": _safe_ratio(
                        challenger["confirmed_coverage"],
                        reference["confirmed_coverage"],
                    ),
                    "W120_confirmed_intervals": challenger_i[
                        "confirmed_interval_count"
                    ],
                    "W250_confirmed_intervals": reference_i["confirmed_interval_count"],
                    "interval_difference": int(challenger_i["confirmed_interval_count"])
                    - int(reference_i["confirmed_interval_count"]),
                    "W120_fragment_rate": challenger_i["fragment_rate"],
                    "W250_fragment_rate": reference_i["fragment_rate"],
                    "fragment_difference": _difference(
                        challenger_i["fragment_rate"], reference_i["fragment_rate"]
                    ),
                    "W120_unique_securities": challenger[
                        "confirmed_unique_security_count"
                    ],
                    "W250_unique_securities": reference[
                        "confirmed_unique_security_count"
                    ],
                    "availability_difference": availability_difference,
                    "paired_comparison_status": "descriptive_availability_qualified",
                    "warnings": ";".join(warnings),
                }
            )
    return result


def _upstream_reconciliation(
    con: Any,
    config: Mapping[str, Any],
    registry: Sequence[Mapping[str, Any]],
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    interlayer_rows: Sequence[Mapping[str, Any]],
    concentration_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def add(
        source: str,
        scope: str,
        metric: str,
        actual: Any,
        expected: Any,
        year: Any = "pooled",
        tolerance: float = 1e-12,
    ) -> None:
        mismatch = not _close(actual, expected, tolerance)
        result.append(
            {
                "upstream_task": source,
                "scope_id": scope,
                "year": year,
                "metric": metric,
                "actual_value": actual,
                "expected_value": expected,
                "absolute_difference": _absolute_difference(actual, expected),
                "mismatch_count": int(mismatch),
                "status": "mismatch" if mismatch else "matched",
            }
        )

    t04_profile = _csv_index(
        ROOT / config["upstream_artifacts"]["t04_state_line_profile"]["path"],
        ("candidate_config_id", "state_line", "analysis_level"),
    )
    t04_year = _csv_index(
        ROOT / config["upstream_artifacts"]["t04_year_concentration_profile"]["path"],
        ("candidate_config_id", "state_line", "analysis_level", "year"),
    )
    for key, rows in _group(state_rows, ("candidate_config_id", "state_line")).items():
        interval_group = [
            row
            for row in interval_rows
            if (row["candidate_config_id"], row["state_line"]) == key
        ]
        for level in ("raw", "confirmed"):
            expected = t04_profile[(key[0], key[1], level)]
            scope = f"{key[0]}|{key[1]}|{level}"
            sums = {
                "eligible_day_count": sum(
                    int(row["eligible_trading_days"]) for row in rows
                ),
                "valid_day_count": sum(int(row["valid_day_count"]) for row in rows),
                "unknown_day_count": sum(int(row["unknown_day_count"]) for row in rows),
                "blocked_day_count": sum(int(row["blocked_day_count"]) for row in rows),
                "state_true_day_count": sum(
                    int(row[f"{level}_state_true_count"]) for row in rows
                ),
                "state_false_day_count": sum(
                    int(row[f"{level}_state_false_count"]) for row in rows
                ),
                "state_null_day_count": sum(
                    int(row[f"{level}_state_null_count"]) for row in rows
                ),
            }
            for metric, actual in sums.items():
                add("R1-T04", scope, metric, actual, expected[metric])
            add(
                "R1-T04",
                scope,
                "coverage",
                sums["state_true_day_count"] / sums["eligible_day_count"],
                expected["coverage"],
            )
            summary = next(
                row
                for row in concentration_rows
                if row.get("summary_scope") == "candidate_state"
                and row["candidate_config_id"] == key[0]
                and row["state_line"] == key[1]
                and row["analysis_level"] == level
            )
            add(
                "R1-T04",
                scope,
                "max_year_share",
                summary["max_year_state_share"],
                expected["max_year_share"],
            )
            add("R1-T04", scope, "year_hhi", summary["year_hhi"], expected["year_hhi"])
            for row in rows:
                year_key = (key[0], key[1], level, str(row["year"]))
                upstream = t04_year.get(year_key)
                expected_count = (
                    0 if upstream is None else upstream["state_true_day_count"]
                )
                expected_share = (
                    0.0 if upstream is None else upstream["year_share_of_state_days"]
                )
                add(
                    "R1-T04",
                    scope,
                    "year_state_true_count",
                    row[f"{level}_state_true_count"],
                    expected_count,
                    row["year"],
                )
                add(
                    "R1-T04",
                    scope,
                    "year_state_share",
                    row[f"{level}_state_year_share"] or 0.0,
                    expected_share,
                    row["year"],
                )
            if level == "confirmed":
                add(
                    "R1-T04",
                    scope,
                    "confirmed_interval_count",
                    sum(int(row["confirmed_interval_count"]) for row in interval_group),
                    expected["segment_or_interval_count"],
                )
                add(
                    "R1-T04",
                    scope,
                    "confirmed_total_duration",
                    sum(
                        int(row["confirmed_interval_total_duration"])
                        for row in interval_group
                    ),
                    expected["total_duration_days"],
                )

    t06_year = _csv_index(
        ROOT / config["upstream_artifacts"]["t06_year_step_profile"]["path"],
        ("step_id", "W", "q", "year"),
    )
    t06_pooled = _csv_index(
        ROOT / config["upstream_artifacts"]["t06_layer_step_profile"]["path"],
        ("step_id", "W", "q"),
    )
    for key, rows in _group(interlayer_rows, ("step_id", "W", "q")).items():
        scope = f"{key[0]}|W{key[1]}|q{key[2]}"
        for row in rows:
            upstream = t06_year.get(
                (str(key[0]), str(key[1]), str(key[2]), str(row["year"]))
            )
            for metric in ("N", "n11", "n10", "n01", "n00"):
                add(
                    "R1-T06",
                    scope,
                    metric,
                    row[metric],
                    0 if upstream is None else upstream[metric],
                    row["year"],
                )
            if upstream is not None:
                add(
                    "R1-T06",
                    scope,
                    "retention",
                    row["retention"],
                    upstream["retention"],
                    row["year"],
                )
                add(
                    "R1-T06",
                    scope,
                    "target_marginal_rate",
                    row["target_marginal_rate"],
                    upstream["target_marginal_rate"],
                    row["year"],
                )
                add(
                    "R1-T06",
                    scope,
                    "association_lift",
                    row["association_lift"],
                    upstream["lift"],
                    row["year"],
                )
                add(
                    "R1-T06",
                    scope,
                    "absolute_increment",
                    row["absolute_increment"],
                    upstream["delta"],
                    row["year"],
                )
        pooled = t06_pooled[(str(key[0]), str(key[1]), str(key[2]))]
        for metric in ("N", "n11", "n10", "n01", "n00"):
            add(
                "R1-T06",
                scope,
                f"pooled_{metric}",
                sum(int(row[metric]) for row in rows),
                pooled[metric],
            )

    t08_registry = _csv_rows(
        ROOT / config["upstream_artifacts"]["t08_candidate_registry"]["path"]
    )
    normalized = {
        (
            row["candidate_config_id"],
            row["state_line"],
            int(row["W"]),
            float(row["q"]),
            int(row["K"]),
        )
        for row in registry
    }
    upstream_normalized = {
        (
            row["candidate_config_id"],
            row["state_line"],
            int(row["W"]),
            float(row["q"]),
            int(row["K"]),
        )
        for row in t08_registry
    }
    add(
        "R1-T08",
        "candidate_registry",
        "symmetric_difference_count",
        len(normalized ^ upstream_normalized),
        0,
    )
    t08_null = _csv_index(
        ROOT / config["upstream_artifacts"]["t08_null_model_results"]["path"],
        ("test_group_id", "statistic_name"),
    )
    for key, rows in _group(state_rows, ("candidate_config_id", "state_line")).items():
        W = int(rows[0]["W"])
        state_line = str(rows[0]["state_line"])
        test_id = f"W{W}_GLOBAL_{'PCT' if state_line == 'S_PCT' else 'PCVT'}_SYNC"
        upstream = t08_null[(test_id, "confirmed_coverage")]
        actual = sum(int(row["confirmed_state_true_count"]) for row in rows) / sum(
            int(row["eligible_trading_days"]) for row in rows
        )
        add(
            "R1-T08",
            f"{key[0]}|{key[1]}",
            "pooled_observed_confirmed_coverage",
            actual,
            upstream["observed_value"],
        )
    for key, rows in _group(interlayer_rows, ("step_id", "W", "q")).items():
        test_id = f"W{key[1]}_{key[0]}"
        upstream = t08_null[(test_id, "nested_retention")]
        totals = {
            name: sum(int(row[name]) for row in rows)
            for name in ("n11", "n10", "n01", "n00")
        }
        actual = _step_metrics(**totals)["retention"]
        add(
            "R1-T08",
            f"{key[0]}|W{key[1]}",
            "pooled_nested_observed_retention",
            actual,
            upstream["observed_value"],
        )

    subset = con.execute(
        """
        WITH s AS (
          SELECT security_id,trading_date,percentile_window_W AS W,state_name,raw_state,confirmed_state
          FROM dailydb.r0_t07_daily_confirmation_results
          WHERE percentile_window_W IN (120,250) AND abs(q-0.2)<1e-12 AND confirmation_k=3 AND state_name IN ('S_PCT','S_PCVT')
        ), w AS (
          SELECT security_id,trading_date,W,
            max(raw_state) FILTER (WHERE state_name='S_PCT') AS pct_raw,
            max(raw_state) FILTER (WHERE state_name='S_PCVT') AS pcvt_raw,
            max(confirmed_state) FILTER (WHERE state_name='S_PCT') AS pct_confirmed,
            max(confirmed_state) FILTER (WHERE state_name='S_PCVT') AS pcvt_confirmed
          FROM s GROUP BY security_id,trading_date,W
        )
        SELECT W,count(*) FILTER (WHERE pcvt_raw IS TRUE AND pct_raw IS DISTINCT FROM TRUE),
          count(*) FILTER (WHERE pcvt_confirmed IS TRUE AND pct_confirmed IS DISTINCT FROM TRUE)
        FROM w GROUP BY W ORDER BY W
        """
    ).fetchall()
    for W, raw_mismatch, confirmed_mismatch in subset:
        add("R0", f"PCVT_SUBSET_PCT|W{W}", "raw_subset_mismatch_count", raw_mismatch, 0)
        add(
            "R0",
            f"PCVT_SUBSET_PCT|W{W}",
            "confirmed_subset_mismatch_count",
            confirmed_mismatch,
            0,
        )
    return result


def _build_anomaly_scan(
    run_id: str,
    code_commit: str,
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    interlayer_rows: Sequence[Mapping[str, Any]],
    concentration_rows: Sequence[Mapping[str, Any]],
    loyo_rows: Sequence[Mapping[str, Any]],
    reconciliation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def block(check_id: str, message: str, count: int) -> None:
        if count:
            blocking.append({"check_id": check_id, "message": message, "count": count})

    block(
        "upstream_reconciliation",
        "At least one upstream or parent-child reconciliation check failed.",
        sum(int(row["mismatch_count"]) for row in reconciliation_rows),
    )
    block(
        "daily_state_conservation",
        "Annual raw/confirmed or validity counts do not conserve eligible rows.",
        sum(
            int(row["raw_state_true_count"])
            + int(row["raw_state_false_count"])
            + int(row["raw_state_null_count"])
            != int(row["eligible_trading_days"])
            or int(row["confirmed_state_true_count"])
            + int(row["confirmed_state_false_count"])
            + int(row["confirmed_state_null_count"])
            != int(row["eligible_trading_days"])
            or int(row["valid_day_count"])
            + int(row["unknown_day_count"])
            + int(row["blocked_day_count"])
            + int(row["diagnostic_required_day_count"])
            != int(row["eligible_trading_days"])
            for row in state_rows
        ),
    )
    block(
        "interlayer_2x2_conservation",
        "Annual interlayer 2x2 cells do not sum to N.",
        sum(
            int(row["n11"]) + int(row["n10"]) + int(row["n01"]) + int(row["n00"])
            != int(row["N"])
            for row in interlayer_rows
        ),
    )
    block(
        "partial_year_contract",
        "The 2026 partial-year marker is incorrect.",
        sum(
            bool(row["partial_year_observation"]) != (int(row["year"]) == 2026)
            for row in state_rows
        ),
    )
    for row in concentration_rows:
        warning_text = str(row.get("warnings") or "")
        for warning in filter(None, warning_text.split(";")):
            warnings.append(
                {
                    "check_id": warning,
                    "scope_id": row.get("candidate_config_id")
                    or f"{row.get('step_id')}|W{row.get('W')}",
                    "message": "Preregistered yearly concentration or direction warning triggered.",
                }
            )
    sign_flips = [row for row in loyo_rows if _as_bool(row.get("sign_flip"))]
    if sign_flips:
        warnings.append(
            {
                "check_id": "year_direction_conflict_warning",
                "scope_id": "leave_one_year_out",
                "message": f"{len(sign_flips)} leave-one-year-out rows changed a pooled sign.",
            }
        )
    zero_years = sum(int(row["confirmed_state_true_count"]) == 0 for row in state_rows)
    if zero_years:
        warnings.append(
            {
                "check_id": "zero_state_year_retained",
                "scope_id": "candidate_year",
                "message": f"{zero_years} candidate-years have zero confirmed state days and were retained.",
            }
        )
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "scan_status": "passed" if not blocking else "blocked",
        "anomaly_resolution_status": "passed" if not blocking else "unresolved",
        "blocking_findings": blocking,
        "material_warnings": warnings,
        "checks": {
            "candidate_year_rows": len(state_rows),
            "interval_year_rows": len(interval_rows),
            "interlayer_year_rows": len(interlayer_rows),
            "reconciliation_mismatch_count": sum(
                int(row["mismatch_count"]) for row in reconciliation_rows
            ),
            "leave_one_year_out_sign_flip_count": len(sign_flips),
            "zero_confirmed_state_year_count": zero_years,
        },
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }


def _build_diagnostic_summary(
    run_id: str,
    code_commit: str,
    config: Mapping[str, Any],
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    clipped_rows: Sequence[Mapping[str, Any]],
    interlayer_rows: Sequence[Mapping[str, Any]],
    concentration_rows: Sequence[Mapping[str, Any]],
    loyo_rows: Sequence[Mapping[str, Any]],
    comparison_rows: Sequence[Mapping[str, Any]],
    reconciliation_rows: Sequence[Mapping[str, Any]],
    anomaly: Mapping[str, Any],
    dependencies: Mapping[str, Any],
    runtime_seconds: float,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "candidate_count": 4,
        "year_count_by_candidate": {
            f"{key[0]}|{key[1]}": len(rows)
            for key, rows in _group(
                state_rows, ("candidate_config_id", "state_line")
            ).items()
        },
        "output_row_counts": {
            "candidate_registry": 4,
            "year_state_profile": len(state_rows),
            "year_interval_profile": len(interval_rows),
            "calendar_year_clipped_geometry": len(clipped_rows),
            "year_interlayer_profile": len(interlayer_rows),
            "year_concentration_summary": len(concentration_rows),
            "leave_one_year_out": len(loyo_rows),
            "reference_challenger_year_comparison": len(comparison_rows),
            "upstream_reconciliation": len(reconciliation_rows),
        },
        "input_row_counts": {
            name: artifact["row_count"]
            for name, artifact in config["input_artifacts"].items()
        },
        "reconciliation_mismatch_count": sum(
            int(row["mismatch_count"]) for row in reconciliation_rows
        ),
        "runtime_seconds": runtime_seconds,
        "duckdb_threads": config["parallelism"]["duckdb_threads"],
        "duckdb_memory_limit": config["parallelism"]["duckdb_memory_limit"],
        "dependency_versions": dependencies,
        "partial_year": 2026,
        "anomaly_scan_status": anomaly["scan_status"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }


def _build_experiment_summary(
    config: Mapping[str, Any],
    config_path: Path,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    dependencies: Mapping[str, Any],
    elapsed_seconds: float,
    anomaly: Mapping[str, Any],
) -> dict[str, Any]:
    artifacts = {}
    for name in ARTIFACT_NAMES:
        path = output_dir / name
        if path.exists():
            artifacts[name] = {
                "path": _rel(path),
                "sha256": sha256_file(path),
                "row_count": _csv_count(path) if path.suffix == ".csv" else 1,
            }
    return {
        "task_id": TASK_ID,
        "stage": "R1",
        "task_class": "formal_experiment",
        "run_id": run_id,
        "status": "author_analysis_pending",
        "code_commit": code_commit,
        "implementation_actor": "codex",
        "config_path": _rel(config_path),
        "config_sha256": sha256_file(config_path),
        "date_min": config["years"]["date_min"],
        "date_max": config["years"]["date_max"],
        "partial_years": config["years"]["partial_years"],
        "candidate_count": len(config["candidate_registry"]),
        "input_lineage": config["input_artifacts"],
        "upstream_final_packages": config["upstream_final_packages"],
        "upstream_artifacts": config["upstream_artifacts"],
        "parallelism": config["parallelism"],
        "dependency_versions": dependencies,
        "runtime_seconds": elapsed_seconds,
        "artifacts": artifacts,
        "anomaly_scan_status": anomaly["scan_status"],
        "anomaly_resolution_status": anomaly["anomaly_resolution_status"],
        "scientific_review_status": "pending",
        "review_phase": "author_analysis_pending",
        "downstream_gate_allowed": False,
        "readme_gate_updated": False,
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }


def build_author_draft_result_package(
    *,
    run_dir: Path,
    analysis_path: Path,
    evidence_path: Path,
    engineering_validation_path: Path,
    readme_path: Path,
) -> Path:
    summary_path = run_dir / "r1_t09_experiment_summary.json"
    anomaly_path = run_dir / "r1_t09_anomaly_scan.json"
    summary = _load_json(summary_path)
    anomaly = _load_json(anomaly_path)
    engineering = _load_json(engineering_validation_path)
    if engineering.get("validator_status") != "passed":
        raise R1T09Error("engineering validator has not passed")
    if not analysis_path.exists() or not evidence_path.exists():
        raise R1T09Error("analysis and evidence must exist before author package")
    anomaly_status = anomaly.get("anomaly_resolution_status", "unresolved")

    primary_names = (
        "r1_t09_candidate_registry.csv",
        "r1_t09_year_state_profile.csv",
        "r1_t09_year_interval_profile.csv",
        "r1_t09_calendar_year_clipped_geometry.csv",
        "r1_t09_year_interlayer_profile.csv",
        "r1_t09_year_concentration_summary.csv",
        "r1_t09_leave_one_year_out.csv",
        "r1_t09_reference_challenger_year_comparison.csv",
    )
    diagnostic_names = (
        "r1_t09_upstream_reconciliation.csv",
        "r1_t09_anomaly_scan.json",
        "r1_t09_diagnostic_summary.json",
    )

    def artifact(name: str, role: str) -> dict[str, Any]:
        path = run_dir / name
        return {
            "path": _rel(path),
            "sha256": sha256_file(path),
            "record_count": _csv_count(path) if path.suffix == ".csv" else 1,
            "artifact_role": role,
            "committed_to_repo": True,
        }

    package = {
        "task_id": TASK_ID,
        "task_class": "formal_experiment",
        "run_id": summary["run_id"],
        "status": "author_analysis_complete",
        "code_commit": summary["code_commit"],
        "implementation_actor": "codex",
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "input_package": {
            "authorized_input_manifest_path": _load_json(CONFIG_PATH)[
                "authorized_input_manifest_path"
            ],
            "artifacts": summary["input_lineage"],
            "upstream_final_packages": summary["upstream_final_packages"],
        },
        "experiment_summary_path": _rel(summary_path),
        "experiment_summary_sha256": sha256_file(summary_path),
        "anomaly_scan_path": _rel(anomaly_path),
        "anomaly_scan_sha256": sha256_file(anomaly_path),
        "engineering_validation_result_path": _rel(engineering_validation_path),
        "engineering_validation_result_sha256": sha256_file(
            engineering_validation_path
        ),
        "primary_result_artifacts": [
            artifact(name, "primary_results") for name in primary_names
        ],
        "diagnostic_artifacts": [
            artifact(name, "diagnostic_summary") for name in diagnostic_names
        ],
        "result_analysis_path": _rel(analysis_path),
        "result_analysis_sha256": sha256_file(analysis_path),
        "formal_evidence_path": _rel(evidence_path),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "scientific_review_record_path": None,
        "scientific_review_record_sha256": None,
        "scientific_review_md_path": None,
        "scientific_review_md_sha256": None,
        "readme_path": _rel(readme_path),
        "readme_sha256": sha256_file(readme_path),
        "expected_current_stage": "R1",
        "expected_current_task": "R1-T09 年份稳定性与状态集中度检查",
        "expected_next_planned_task": "R1-T10 R1 验收门禁与 R2 交接矩阵",
        "expected_downstream_gate_marker": "R1-T10_allowed_to_start: false",
        "superseded": False,
        "superseded_by": None,
        "gate_status": {
            "engineering_validator_status": "passed",
            "result_artifact_status": "passed",
            "author_result_analysis_status": "passed",
            "scientific_review_status": "pending",
            "anomaly_resolution_status": anomaly_status,
            "review_phase": "author_analysis_complete",
            "readme_gate_updated": False,
        },
        "downstream_gate_allowed": False,
    }
    path = run_dir / "r1_t09_result_package.json"
    _write_json(path, package)
    return path


def _check_prerequisites(
    config: Mapping[str, Any], *, verify_input_hashes: bool
) -> None:
    readme = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
    for marker in (
        "current_task: R1-T09 年份稳定性与状态集中度检查",
        "R1-T09_allowed_to_start: true",
        "R1-T10_allowed_to_start: false",
        "R2_allowed_to_start: false",
    ):
        if marker not in readme:
            raise R1T09Error(f"blocked_input_contract: README marker missing: {marker}")
    for task_id, package in config["upstream_final_packages"].items():
        for path_key, hash_key in (
            ("result_package_path", "result_package_sha256"),
            ("scientific_review_path", "scientific_review_sha256"),
            ("final_gate_path", "final_gate_sha256"),
        ):
            path = ROOT / package[path_key]
            if not path.exists():
                raise R1T09Error(
                    f"blocked_input_contract: missing {task_id} {path_key}"
                )
            if verify_input_hashes and sha256_file(path) != package[hash_key]:
                raise R1T09Error(
                    f"blocked_input_contract: hash mismatch {task_id} {path_key}"
                )
        result = _load_json(ROOT / package["result_package_path"])
        review = _load_json(ROOT / package["scientific_review_path"])
        gate = _load_json(ROOT / package["final_gate_path"])
        if (
            result.get("status") != "completed"
            or result.get("gate_status", {}).get("scientific_review_status") != "passed"
            or result.get("gate_status", {}).get("review_phase")
            != "independent_review_complete"
            or not result.get("downstream_gate_allowed")
            or review.get("scientific_review_status") != "passed"
            or gate.get("author_package_validator_status") != "passed"
            or gate.get("mode") != "final-gate"
            or not gate.get("formal_task_completed")
        ):
            raise R1T09Error(
                f"blocked_input_contract: upstream final gate invalid: {task_id}"
            )
    if verify_input_hashes:
        for group in ("input_artifacts", "upstream_artifacts"):
            for name, artifact in config[group].items():
                path = ROOT / artifact["path"]
                if not path.exists() or sha256_file(path) != artifact["sha256"]:
                    raise R1T09Error(
                        f"blocked_input_contract: {group} hash mismatch: {name}"
                    )


def _validate_frozen_registry(config: Mapping[str, Any]) -> None:
    actual = {
        (row["state_line"], int(row["W"]), float(row["q"]), int(row["K"]))
        for row in config["candidate_registry"]
    }
    expected = {
        ("S_PCT", 120, 0.2, 3),
        ("S_PCT", 250, 0.2, 3),
        ("S_PCVT", 120, 0.2, 3),
        ("S_PCVT", 250, 0.2, 3),
    }
    if actual != expected or len(config["candidate_registry"]) != 4:
        raise R1T09Error(
            "candidate registry must contain exactly the four formal candidates"
        )


def _registry_rows(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **{
                key: value
                for key, value in row.items()
                if key != "upstream_t08_test_group_ids"
            },
            "upstream_t08_test_group_ids": "|".join(row["upstream_t08_test_group_ids"]),
        }
        for row in config["candidate_registry"]
    ]


def _query_dicts(con: Any, query: str) -> list[dict[str, Any]]:
    cursor = con.execute(query)
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _group(
    rows: Sequence[Mapping[str, Any]], keys: Sequence[str]
) -> dict[tuple[Any, ...], list[Mapping[str, Any]]]:
    result: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        result.setdefault(tuple(row[key] for key in keys), []).append(row)
    return result


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    fraction = position - lower
    return float(values[lower]) * (1 - fraction) + float(values[upper]) * fraction


def _safe_ratio(left: Any, right: Any) -> float | None:
    if left is None or right is None or float(right) == 0:
        return None
    return float(left) / float(right)


def _difference(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _relative_change(actual: Any, baseline: Any) -> float | None:
    if actual is None or baseline is None or float(baseline) == 0:
        return None
    return (float(actual) - float(baseline)) / abs(float(baseline))


def _close(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    if left in (None, "") and right in (None, ""):
        return True
    try:
        return math.isclose(
            float(left), float(right), rel_tol=tolerance, abs_tol=tolerance
        )
    except (TypeError, ValueError):
        return str(left).lower() == str(right).lower()


def _absolute_difference(left: Any, right: Any) -> float | None:
    try:
        return abs(float(left) - float(right))
    except (TypeError, ValueError):
        return 0.0 if str(left) == str(right) else None


def _as_bool(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _sql_string(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _dependency_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # pragma: no cover
        return "unknown"


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise R1T09Error(f"refusing to write empty artifact: {path.name}")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_index(
    path: Path, keys: Sequence[str]
) -> dict[tuple[str, ...], dict[str, str]]:
    return {tuple(row[key] for key in keys): row for row in _csv_rows(path)}


def _csv_count(path: Path) -> int:
    return len(_csv_rows(path))


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
