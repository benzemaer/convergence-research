# ruff: noqa: E501, UP038
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import subprocess
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r1/r1_t14_01_layer_q_response_diagnostic.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t14_01_layer_q_response_diagnostic.schema.json"
TASK_ID = "R1-T14-01"
NAMESPACE = "r1_t14_01_diagnostic_only"
EPSILON = 1e-12

CSV_ARTIFACTS = (
    "r1_t14_01_grid_registry.csv",
    "r1_t14_01_layer_response_profile.csv",
    "r1_t14_01_common_valid_funnel.csv",
    "r1_t14_01_attrition_profile.csv",
    "r1_t14_01_state_profile.csv",
    "r1_t14_01_interlayer_profile.csv",
    "r1_t14_01_identity_overlap.csv",
    "r1_t14_01_interval_profile.csv",
    "r1_t14_01_year_profile.csv",
    "r1_t14_01_leave_one_year_out.csv",
    "r1_t14_01_baseline_stability_envelope.csv",
    "r1_t14_01_archetype_registry.csv",
    "r1_t14_01_candidate_selection_audit.csv",
    "r1_t14_01_upstream_reconciliation.csv",
)


class R1T1401Error(RuntimeError):
    pass


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_grid_registry(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    q_values = [float(value) for value in config["grid"]["Q"]]
    rows: list[dict[str, Any]] = []
    for window in config["grid"]["W"]:
        baseline = {
            "candidate_q_vector_id": vector_id(int(window), 0.2, 0.2, 0.2, 0.2),
            "W": int(window),
            "K": 3,
            "qP": 0.2,
            "qC": 0.2,
            "qT": 0.2,
            "qV": 0.2,
            "changed_layer": "BASELINE",
            "changed_q": 0.2,
            "role": "baseline",
            "diagnostic_namespace": NAMESPACE,
            "authoritative": False,
            "formal_candidate_state": False,
        }
        rows.append(baseline)
        for layer in ("P", "C", "T", "V"):
            for q in q_values:
                if abs(q - 0.2) <= EPSILON:
                    continue
                values = {"P": 0.2, "C": 0.2, "T": 0.2, "V": 0.2}
                values[layer] = q
                rows.append(
                    {
                        "candidate_q_vector_id": vector_id(
                            int(window),
                            values["P"],
                            values["C"],
                            values["T"],
                            values["V"],
                        ),
                        "W": int(window),
                        "K": 3,
                        "qP": values["P"],
                        "qC": values["C"],
                        "qT": values["T"],
                        "qV": values["V"],
                        "changed_layer": layer,
                        "changed_q": q,
                        "role": "diagnostic_nonbaseline",
                        "diagnostic_namespace": NAMESPACE,
                        "authoritative": False,
                        "formal_candidate_state": False,
                    }
                )
    expected = int(config["grid"]["expected_vector_W_count"])
    if (
        len(rows) != expected
        or len({row["candidate_q_vector_id"] for row in rows}) != expected
    ):
        raise R1T1401Error("grid_registry_cardinality_mismatch")
    return rows


def vector_id(window: int, q_p: float, q_c: float, q_t: float, q_v: float) -> str:
    return (
        f"W{window}_K3_P{int(round(q_p * 100)):02d}_C{int(round(q_c * 100)):02d}_"
        f"T{int(round(q_t * 100)):02d}_V{int(round(q_v * 100)):02d}"
    )


def run_r1_t14_01_layer_q_response_diagnostic(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    verify_input_hashes: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = _load_json(config_path)
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator(schema).validate(config)
    inputs = _resolve_and_verify_inputs(config, verify_input_hashes)
    registry = build_grid_registry(config)
    _write_csv(output_dir / CSV_ARTIFACTS[0], registry)

    import duckdb  # noqa: PLC0415

    con = duckdb.connect()
    try:
        con.execute(f"SET threads={int(config['parallelism']['duckdb_threads'])}")
        con.execute(
            "SET memory_limit=?", [config["parallelism"]["duckdb_memory_limit"]]
        )
        con.execute("SET preserve_insertion_order=false")
        _attach_inputs(con, inputs)
        _create_base_scores(con)
        _verify_base_shape(con, config)
        results = _run_vectors(con, registry, config)
    finally:
        con.close()

    response_rows = build_layer_response_profile(results, config)
    envelope_rows = build_stability_envelopes(results, config)
    archetype_rows, audit_rows, decision = select_materialization_request(
        registry=registry,
        results=results,
        envelope_rows=envelope_rows,
        config=config,
        run_id=run_id,
    )
    results["layer_response"] = response_rows
    results["stability_envelope"] = envelope_rows
    results["archetype"] = archetype_rows
    results["selection_audit"] = audit_rows

    for name, key in zip(
        CSV_ARTIFACTS[1:],
        (
            "layer_response",
            "common_funnel",
            "attrition",
            "state",
            "interlayer",
            "identity",
            "interval",
            "year",
            "loyo",
            "stability_envelope",
            "archetype",
            "selection_audit",
            "reconciliation",
        ),
        strict=True,
    ):
        _write_csv(output_dir / name, results[key])

    decision_name = (
        "r1_t14_01_materialization_request.json"
        if decision["decision"] == "q_vector_materialization_request"
        else "r1_t14_01_no_candidate_decision.json"
    )
    write_json_atomic(output_dir / decision_name, decision)
    anomaly_scan = build_anomaly_scan(registry, results, decision, config)
    write_json_atomic(output_dir / "r1_t14_01_anomaly_scan.json", anomaly_scan)
    diagnostic_summary = build_diagnostic_summary(
        run_id=run_id,
        code_commit=code_commit,
        config=config,
        inputs=inputs,
        results=results,
        decision=decision,
        anomaly_scan=anomaly_scan,
        runtime_seconds=time.monotonic() - started,
    )
    write_json_atomic(
        output_dir / "r1_t14_01_diagnostic_summary.json", diagnostic_summary
    )
    return diagnostic_summary


def _resolve_and_verify_inputs(
    config: Mapping[str, Any], verify: bool
) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for name, item in config["input_artifacts"].items():
        path = ROOT / str(item["path"])
        if not path.is_file():
            raise R1T1401Error(f"input_missing:{name}:{path}")
        actual = sha256_file(path) if verify else str(item["sha256"])
        if verify and actual != item["sha256"]:
            raise R1T1401Error(f"input_hash_mismatch:{name}")
        resolved[name] = {
            **dict(item),
            "absolute_path": str(path),
            "actual_sha256": actual,
        }
    return resolved


def _attach_inputs(con: Any, inputs: Mapping[str, Mapping[str, Any]]) -> None:
    for alias, name in (
        ("scoredb", "dimension_score"),
        ("dailydb", "baseline_daily_confirmation"),
        ("intervaldb", "baseline_confirmed_interval"),
    ):
        con.execute(f"ATTACH ? AS {alias} (READ_ONLY)", [inputs[name]["absolute_path"]])


def _create_base_scores(con: Any) -> None:
    con.execute(
        """
        CREATE TEMP TABLE base_scores AS
        WITH p AS (
          SELECT security_id,trading_date,CAST(percentile_window_W AS INTEGER) AS W,
            max(score_dimension) FILTER (WHERE dimension='P') AS score_P,
            max(score_dimension_min) FILTER (WHERE dimension='P') AS min_P,
            max(score_dimension) FILTER (WHERE dimension='C') AS score_C,
            max(score_dimension_min) FILTER (WHERE dimension='C') AS min_C,
            max(score_dimension) FILTER (WHERE dimension='T') AS score_T,
            max(score_dimension_min) FILTER (WHERE dimension='T') AS min_T,
            max(score_dimension) FILTER (WHERE dimension='V') AS score_V,
            max(score_dimension_min) FILTER (WHERE dimension='V') AS min_V,
            bool_and(eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL)
              FILTER (WHERE dimension='P') AS valid_P,
            bool_and(eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL)
              FILTER (WHERE dimension='C') AS valid_C,
            bool_and(eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL)
              FILTER (WHERE dimension='T') AS valid_T,
            bool_and(eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL)
              FILTER (WHERE dimension='V') AS valid_V,
            max(validity_status) FILTER (WHERE dimension='P') AS status_P,
            max(validity_status) FILTER (WHERE dimension='C') AS status_C,
            max(validity_status) FILTER (WHERE dimension='T') AS status_T,
            max(validity_status) FILTER (WHERE dimension='V') AS status_V,
            count(*) AS dimension_rows
          FROM scoredb.r0_t05_dimension_score_results
          WHERE percentile_window_W IN (120,250)
          GROUP BY security_id,trading_date,percentile_window_W
        )
        SELECT *, lead(trading_date) OVER (PARTITION BY W,security_id ORDER BY trading_date) AS next_date
        FROM p
        """
    )


def _verify_base_shape(con: Any, config: Mapping[str, Any]) -> None:
    bad, windows, securities, date_min, date_max = con.execute(
        """
        SELECT count(*) FILTER (WHERE dimension_rows<>4),count(DISTINCT W),
          count(DISTINCT security_id),min(trading_date),max(trading_date)
        FROM base_scores
        """
    ).fetchone()
    expected = config["input_artifacts"]["dimension_score"]
    if bad or windows != 2 or securities != expected["security_count"]:
        raise R1T1401Error("base_score_shape_mismatch")
    if date_min != expected["date_min"] or date_max != expected["date_max"]:
        raise R1T1401Error("base_score_date_domain_mismatch")


def _run_vectors(
    con: Any, registry: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    results: dict[str, list[dict[str, Any]]] = {
        key: []
        for key in (
            "common_funnel",
            "attrition",
            "state",
            "interlayer",
            "identity",
            "interval",
            "year",
            "loyo",
            "reconciliation",
        )
    }
    for window in config["grid"]["W"]:
        ordered = [row for row in registry if row["W"] == window]
        for row in ordered:
            _create_vector_daily(con, row)
            _create_vector_intervals(con)
            state_rows = _state_profile(con, row)
            interval_rows = _interval_profile(con, row)
            year_rows = _year_profile(con, row)
            interlayer_rows, interlayer_year, security_summary = _interlayer_profiles(
                con, row
            )
            loyo_rows = _build_interlayer_loyo(row, interlayer_year)
            funnel, attrition = _common_funnel(con, row)
            if row["role"] == "baseline":
                _store_baseline(con, int(window))
                identity_rows = _baseline_identity(row, state_rows, interval_rows)
                reconciliation = _baseline_reconciliation(
                    con, row, state_rows, interval_rows
                )
                results["reconciliation"].extend(reconciliation)
            else:
                identity_rows = _identity_profile(
                    con, row, state_rows, interval_rows, int(window)
                )
            results["state"].extend(
                _merge_state_geometry(state_rows, interval_rows, year_rows)
            )
            results["interval"].extend(interval_rows)
            results["year"].extend(year_rows + interlayer_year)
            results["interlayer"].extend(interlayer_rows + security_summary)
            results["loyo"].extend(loyo_rows)
            results["common_funnel"].extend(funnel)
            results["attrition"].extend(attrition)
            results["identity"].extend(identity_rows)
            con.execute("DROP TABLE vector_intervals")
            con.execute("DROP TABLE vector_daily")
    return results


def _create_vector_daily(con: Any, row: Mapping[str, Any]) -> None:
    con.execute(
        """
        CREATE TEMP TABLE vector_daily AS
        WITH active AS (
          SELECT *,
            CASE WHEN valid_P THEN score_P+? >= 1.0-? AND min_P+? >= 1.0-?-0.1 ELSE NULL END AS P,
            CASE WHEN valid_C THEN score_C+? >= 1.0-? AND min_C+? >= 1.0-?-0.1 ELSE NULL END AS C,
            CASE WHEN valid_T THEN score_T+? >= 1.0-? AND min_T+? >= 1.0-?-0.1 ELSE NULL END AS T,
            CASE WHEN valid_V THEN score_V+? >= 1.0-? AND min_V+? >= 1.0-?-0.1 ELSE NULL END AS V
          FROM base_scores WHERE W=?
        ), nested AS (
          SELECT *,P AS S_P,
            CASE WHEN P=false THEN false WHEN P IS NULL THEN NULL ELSE C END AS S_PC,
            CASE WHEN P=false THEN false WHEN P IS NULL THEN NULL WHEN C=false THEN false WHEN C IS NULL THEN NULL ELSE T END AS S_PCT,
            CASE WHEN P=false THEN false WHEN P IS NULL THEN NULL WHEN C=false THEN false WHEN C IS NULL THEN NULL WHEN T=false THEN false WHEN T IS NULL THEN NULL ELSE V END AS S_PCVT,
            CASE WHEN P IS NULL THEN status_P ELSE 'valid' END AS status_S_P,
            CASE WHEN P IS NULL THEN status_P WHEN P=false THEN 'valid' WHEN C IS NULL THEN status_C ELSE 'valid' END AS status_S_PC,
            CASE WHEN P IS NULL THEN status_P WHEN P=false THEN 'valid' WHEN C IS NULL THEN status_C WHEN C=false THEN 'valid' WHEN T IS NULL THEN status_T ELSE 'valid' END AS status_S_PCT,
            CASE WHEN P IS NULL THEN status_P WHEN P=false THEN 'valid' WHEN C IS NULL THEN status_C WHEN C=false THEN 'valid' WHEN T IS NULL THEN status_T WHEN T=false THEN 'valid' WHEN V IS NULL THEN status_V ELSE 'valid' END AS status_S_PCVT
          FROM active
        ), segments AS (
          SELECT *,
            sum(CASE WHEN S_P IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_P,
            sum(CASE WHEN S_PC IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_PC,
            sum(CASE WHEN S_PCT IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_PCT,
            sum(CASE WHEN S_PCVT IS TRUE THEN 0 ELSE 1 END) OVER (PARTITION BY security_id ORDER BY trading_date) AS grp_PCVT
          FROM nested
        ), streaks AS (
          SELECT *,
            sum(CASE WHEN S_P IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_P ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_P,
            sum(CASE WHEN S_PC IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_PC ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_PC,
            sum(CASE WHEN S_PCT IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_PCT ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_PCT,
            sum(CASE WHEN S_PCVT IS TRUE THEN 1 ELSE 0 END) OVER (PARTITION BY security_id,grp_PCVT ORDER BY trading_date ROWS UNBOUNDED PRECEDING) AS streak_PCVT
          FROM segments
        )
        SELECT *,
          CASE WHEN S_P IS NULL THEN NULL WHEN S_P=false THEN false ELSE streak_P>=3 END AS confirmed_P,
          CASE WHEN S_PC IS NULL THEN NULL WHEN S_PC=false THEN false ELSE streak_PC>=3 END AS confirmed_PC,
          CASE WHEN S_PCT IS NULL THEN NULL WHEN S_PCT=false THEN false ELSE streak_PCT>=3 END AS confirmed_PCT,
          CASE WHEN S_PCVT IS NULL THEN NULL WHEN S_PCVT=false THEN false ELSE streak_PCVT>=3 END AS confirmed_PCVT
        FROM streaks
        """,
        [
            EPSILON,
            row["qP"],
            EPSILON,
            row["qP"],
            EPSILON,
            row["qC"],
            EPSILON,
            row["qC"],
            EPSILON,
            row["qT"],
            EPSILON,
            row["qT"],
            EPSILON,
            row["qV"],
            EPSILON,
            row["qV"],
            row["W"],
        ],
    )


def _long_state_sql(source: str = "vector_daily") -> str:
    parts = []
    for short, name in (
        ("P", "S_P"),
        ("PC", "S_PC"),
        ("PCT", "S_PCT"),
        ("PCVT", "S_PCVT"),
    ):
        parts.append(
            f"SELECT security_id,trading_date,next_date,'{name}' AS state_name,"
            f"S_{short} AS raw_state,status_S_{short} AS validity_status,"
            f"confirmed_{short} AS confirmed_state,grp_{short} AS state_group,streak_{short} AS raw_streak FROM {source}"
        )
    return " UNION ALL ".join(parts)


def _create_vector_intervals(con: Any) -> None:
    con.execute(
        f"""
        CREATE TEMP TABLE vector_intervals AS
        WITH long AS ({_long_state_sql()}), grouped AS (
          SELECT state_name,security_id,state_group,
            min(trading_date) AS raw_start_date,
            min(trading_date) FILTER (WHERE raw_streak=3) AS confirmation_date,
            max(trading_date) AS last_true_date,
            arg_max(next_date,trading_date) AS next_observed_date,
            count(*)::BIGINT AS raw_duration,
            count(*) FILTER (WHERE raw_streak>=3)::BIGINT AS confirmed_duration
          FROM long WHERE raw_state IS TRUE
          GROUP BY state_name,security_id,state_group
        )
        SELECT *,next_observed_date IS NULL AS is_open_interval,
          CASE WHEN next_observed_date IS NULL THEN NULL ELSE last_true_date END AS interval_end_date
        FROM grouped WHERE confirmed_duration>0
        """
    )


def _state_profile(con: Any, row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _query_dicts(
        con,
        f"""
        WITH long AS ({_long_state_sql()})
        SELECT state_name,count(*)::BIGINT AS total_rows,
          count(*) FILTER (WHERE validity_status='valid')::BIGINT AS valid_rows,
          count(*) FILTER (WHERE validity_status='unknown')::BIGINT AS unknown_rows,
          count(*) FILTER (WHERE validity_status='blocked')::BIGINT AS blocked_rows,
          count(*) FILTER (WHERE validity_status='diagnostic_required')::BIGINT AS diagnostic_required_rows,
          count(*) FILTER (WHERE raw_state IS TRUE)::BIGINT AS raw_state_days,
          count(*) FILTER (WHERE confirmed_state IS TRUE)::BIGINT AS confirmed_state_days,
          count(DISTINCT security_id) FILTER (WHERE confirmed_state IS TRUE)::BIGINT AS unique_securities,
          count(*) FILTER (WHERE raw_state IS TRUE)::DOUBLE/nullif(count(*) FILTER (WHERE validity_status='valid'),0) AS raw_coverage,
          count(*) FILTER (WHERE confirmed_state IS TRUE)::DOUBLE/nullif(count(*) FILTER (WHERE validity_status='valid'),0) AS confirmed_coverage
        FROM long GROUP BY state_name ORDER BY state_name
        """,
        prefix=row,
    )


def _interval_profile(con: Any, row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _query_dicts(
        con,
        """
        SELECT state_name,count(*)::BIGINT AS confirmed_intervals,
          sum(confirmed_duration)::BIGINT AS confirmed_interval_total_duration,
          avg(confirmed_duration) AS mean_duration,median(confirmed_duration) AS median_duration,
          quantile_cont(confirmed_duration,0.25) AS q25_duration,
          quantile_cont(confirmed_duration,0.75) AS q75_duration,
          quantile_cont(confirmed_duration,0.90) AS q90_duration,
          count(*) FILTER (WHERE confirmed_duration=1)::DOUBLE/nullif(count(*),0) AS fragment_rate,
          count(*) FILTER (WHERE is_open_interval)::BIGINT AS open_intervals,
          count(*) FILTER (WHERE substr(confirmation_date,1,4)<>substr(last_true_date,1,4))::BIGINT AS cross_year_intervals
        FROM vector_intervals GROUP BY state_name ORDER BY state_name
        """,
        prefix=row,
    )


def _year_profile(con: Any, row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _query_dicts(
        con,
        f"""
        WITH long AS ({_long_state_sql()}), years AS (
          SELECT DISTINCT substr(trading_date,1,4)::INTEGER AS year FROM vector_daily
        ), states(state_name) AS (VALUES ('S_P'),('S_PC'),('S_PCT'),('S_PCVT')),
        a AS (
          SELECT state_name,substr(trading_date,1,4)::INTEGER AS year,
            count(*) FILTER (WHERE validity_status='valid')::BIGINT AS valid_rows,
            count(*) FILTER (WHERE raw_state IS TRUE)::BIGINT AS raw_state_days,
            count(*) FILTER (WHERE confirmed_state IS TRUE)::BIGINT AS confirmed_state_days,
            count(DISTINCT security_id) FILTER (WHERE confirmed_state IS TRUE)::BIGINT AS unique_securities
          FROM long GROUP BY state_name,year
        ), i AS (
          SELECT state_name,substr(confirmation_date,1,4)::INTEGER AS year,
            count(*)::BIGINT AS confirmed_intervals,sum(confirmed_duration)::BIGINT AS confirmed_interval_total_duration
          FROM vector_intervals GROUP BY state_name,year
        )
        SELECT 'state_year' AS profile_type,s.state_name,y.year,
          coalesce(a.valid_rows,0)::BIGINT AS valid_rows,coalesce(a.raw_state_days,0)::BIGINT AS raw_state_days,
          coalesce(a.confirmed_state_days,0)::BIGINT AS confirmed_state_days,coalesce(a.unique_securities,0)::BIGINT AS unique_securities,
          coalesce(i.confirmed_intervals,0)::BIGINT AS confirmed_intervals,coalesce(i.confirmed_interval_total_duration,0)::BIGINT AS confirmed_interval_total_duration
        FROM states s CROSS JOIN years y LEFT JOIN a USING(state_name,year) LEFT JOIN i USING(state_name,year)
        ORDER BY state_name,year
        """,
        prefix=row,
    )


def _interlayer_profiles(
    con: Any, row: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    common = """
      WITH steps AS (
        SELECT security_id,trading_date,
          'C_GIVEN_P' AS step_id,(valid_P AND valid_C) AS denominator,P AS anchor,C AS target FROM vector_daily
        UNION ALL SELECT security_id,trading_date,'T_GIVEN_PC',(valid_P AND valid_C AND valid_T),(P AND C),T FROM vector_daily
        UNION ALL SELECT security_id,trading_date,'V_GIVEN_PCT',(valid_P AND valid_C AND valid_T AND valid_V),(P AND C AND T),V FROM vector_daily
      )
    """
    pooled = _query_dicts(
        con,
        common
        + """
        SELECT 'pooled' AS profile_type,step_id,NULL::INTEGER AS year,
          count(*) FILTER (WHERE denominator)::BIGINT AS N,
          count(*) FILTER (WHERE denominator AND anchor AND target)::BIGINT AS n11,
          count(*) FILTER (WHERE denominator AND anchor AND NOT target)::BIGINT AS n10,
          count(*) FILTER (WHERE denominator AND NOT anchor AND target)::BIGINT AS n01,
          count(*) FILTER (WHERE denominator AND NOT anchor AND NOT target)::BIGINT AS n00
        FROM steps GROUP BY step_id ORDER BY step_id
        """,
        prefix=row,
    )
    years = _query_dicts(
        con,
        common
        + """
        SELECT 'interlayer_year' AS profile_type,step_id,substr(trading_date,1,4)::INTEGER AS year,
          count(*) FILTER (WHERE denominator)::BIGINT AS N,
          count(*) FILTER (WHERE denominator AND anchor AND target)::BIGINT AS n11,
          count(*) FILTER (WHERE denominator AND anchor AND NOT target)::BIGINT AS n10,
          count(*) FILTER (WHERE denominator AND NOT anchor AND target)::BIGINT AS n01,
          count(*) FILTER (WHERE denominator AND NOT anchor AND NOT target)::BIGINT AS n00
        FROM steps GROUP BY step_id,year ORDER BY step_id,year
        """,
        prefix=row,
    )
    security = _query_dicts(
        con,
        common
        + """
        , counts AS (
          SELECT step_id,security_id,
            count(*) FILTER (WHERE denominator)::BIGINT AS N,
            count(*) FILTER (WHERE denominator AND anchor AND target)::BIGINT AS n11,
            count(*) FILTER (WHERE denominator AND anchor AND NOT target)::BIGINT AS n10,
            count(*) FILTER (WHERE denominator AND NOT anchor AND target)::BIGINT AS n01,
            count(*) FILTER (WHERE denominator AND NOT anchor AND NOT target)::BIGINT AS n00
          FROM steps GROUP BY step_id,security_id
        ), metrics AS (
          SELECT *,CASE WHEN n11+n10=0 THEN NULL ELSE n11::DOUBLE/(n11+n10)-(n11+n01)::DOUBLE/nullif(N,0) END AS delta,
            CASE WHEN n11+n10=0 OR n11+n01=0 THEN NULL ELSE (n11::DOUBLE/(n11+n10))/((n11+n01)::DOUBLE/N) END AS lift
          FROM counts
        )
        SELECT 'security_summary' AS profile_type,step_id,NULL::INTEGER AS year,
          sum(N)::BIGINT AS N,sum(n11)::BIGINT AS n11,sum(n10)::BIGINT AS n10,sum(n01)::BIGINT AS n01,sum(n00)::BIGINT AS n00,
          count(*) FILTER (WHERE delta IS NOT NULL)::BIGINT AS evaluable_securities,
          median(delta) AS security_median_delta,quantile_cont(delta,0.25) AS security_q25_delta,quantile_cont(delta,0.75) AS security_q75_delta,
          median(lift) AS security_median_lift
        FROM metrics GROUP BY step_id ORDER BY step_id
        """,
        prefix=row,
    )
    return (
        [_add_2x2_metrics(item) for item in pooled],
        [_add_2x2_metrics(item) for item in years],
        security,
    )


def _add_2x2_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(row)
    n = int(item["N"] or 0)
    n11, n10, n01 = (int(item[key] or 0) for key in ("n11", "n10", "n01"))
    anchor = n11 + n10
    target = n11 + n01
    retention = n11 / anchor if anchor else None
    marginal = target / n if n else None
    nonanchor = n01 / (n - anchor) if n > anchor else None
    item.update(
        {
            "anchor_true_count": anchor,
            "target_true_count": target,
            "child_true_count": n11,
            "retention": retention,
            "target_marginal_rate": marginal,
            "nonanchor_target_rate": nonanchor,
            "lift": retention / marginal
            if retention is not None and marginal
            else None,
            "delta": retention - marginal
            if retention is not None and marginal is not None
            else None,
            "delta_nonanchor": retention - nonanchor
            if retention is not None and nonanchor is not None
            else None,
        }
    )
    return item


def _build_interlayer_loyo(
    registry_row: Mapping[str, Any], year_rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    groups = _group(year_rows, "step_id")
    for step, rows in groups.items():
        totals = {
            key: sum(int(row[key] or 0) for row in rows)
            for key in ("N", "n11", "n10", "n01", "n00")
        }
        for removed in rows:
            item = {
                **_registry_prefix(registry_row),
                "profile_type": "leave_one_year_out",
                "step_id": step,
                "removed_year": removed["year"],
                **{key: totals[key] - int(removed[key] or 0) for key in totals},
            }
            output.append(_add_2x2_metrics(item))
    return output


def _common_funnel(
    con: Any, row: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    counts = _query_dicts(
        con,
        """
        SELECT count(*)::BIGINT AS N,
          count(*) FILTER (WHERE P)::BIGINT AS P_count,
          count(*) FILTER (WHERE P AND C)::BIGINT AS PC_count,
          count(*) FILTER (WHERE P AND C AND T)::BIGINT AS PCT_count,
          count(*) FILTER (WHERE P AND C AND T AND V)::BIGINT AS PCVT_count
        FROM vector_daily WHERE valid_P AND valid_C AND valid_T AND valid_V
        """,
        prefix=row,
    )[0]
    n, p, pc, pct, pcvt = (
        int(counts[key])
        for key in ("N", "P_count", "PC_count", "PCT_count", "PCVT_count")
    )
    rates = {
        "P": p / n if n else None,
        "C": pc / p if p else None,
        "T": pct / pc if pc else None,
        "V": pcvt / pct if pct else None,
    }
    funnel = []
    attritions = {
        layer: -math.log(value) if value and value > 0 else None
        for layer, value in rates.items()
    }
    total_attrition = sum(value for value in attritions.values() if value is not None)
    for layer in ("P", "C", "T", "V"):
        funnel.append(
            {
                **_registry_prefix(row),
                "layer": layer,
                "common_valid_N": n,
                "conditional_rate": rates[layer],
                **{
                    key: counts[key]
                    for key in ("P_count", "PC_count", "PCT_count", "PCVT_count")
                },
            }
        )
    attrition = [
        {
            **_registry_prefix(row),
            "layer": layer,
            "attrition": attritions[layer],
            "attrition_share": attritions[layer] / total_attrition
            if attritions[layer] is not None and total_attrition
            else None,
        }
        for layer in ("P", "C", "T", "V")
    ]
    return funnel, attrition


def _store_baseline(con: Any, window: int) -> None:
    con.execute(
        f"""
        CREATE TEMP TABLE baseline_daily_{window} AS
        SELECT security_id,trading_date,confirmed_PCT,confirmed_PCVT FROM vector_daily
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE baseline_intervals_{window} AS
        SELECT state_name,security_id,raw_start_date,confirmation_date,last_true_date
        FROM vector_intervals WHERE state_name IN ('S_PCT','S_PCVT')
        """
    )


def _baseline_identity(
    row: Mapping[str, Any],
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    state_index = {item["state_name"]: item for item in state_rows}
    interval_index = {item["state_name"]: item for item in interval_rows}
    return [
        {
            **_registry_prefix(row),
            "state_name": state,
            "exact_day_intersection": state_index[state]["confirmed_state_days"],
            "exact_day_union": state_index[state]["confirmed_state_days"],
            "jaccard": 1.0,
            "baseline_retention": 1.0,
            "candidate_novelty": 0.0,
            "added_state_days": 0,
            "lost_state_days": 0,
            "same_security_overlap": state_index[state]["unique_securities"],
            "confirmed_interval_overlap": interval_index[state]["confirmed_intervals"],
        }
        for state in ("S_PCT", "S_PCVT")
    ]


def _identity_profile(
    con: Any,
    row: Mapping[str, Any],
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    window: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    state_index = {item["state_name"]: item for item in state_rows}
    interval_index = {item["state_name"]: item for item in interval_rows}
    for state, col in (("S_PCT", "confirmed_PCT"), ("S_PCVT", "confirmed_PCVT")):
        overlap, baseline_days, candidate_days, union_days, security_overlap = (
            con.execute(
                f"""
            SELECT count(*) FILTER (WHERE b.{col} IS TRUE AND d.{col} IS TRUE),
              count(*) FILTER (WHERE b.{col} IS TRUE),count(*) FILTER (WHERE d.{col} IS TRUE),
              count(*) FILTER (WHERE b.{col} IS TRUE OR d.{col} IS TRUE),
              (SELECT count(*) FROM (SELECT DISTINCT d2.security_id FROM vector_daily d2 JOIN baseline_daily_{window} b2 USING(security_id,trading_date) WHERE d2.{col} IS TRUE INTERSECT SELECT DISTINCT b3.security_id FROM baseline_daily_{window} b3 WHERE b3.{col} IS TRUE))
            FROM vector_daily d JOIN baseline_daily_{window} b USING(security_id,trading_date)
            """
            ).fetchone()
        )
        interval_overlap = con.execute(
            f"""
            SELECT count(*) FROM vector_intervals d JOIN baseline_intervals_{window} b
              USING(state_name,security_id,raw_start_date,confirmation_date,last_true_date)
            WHERE d.state_name=?
            """,
            [state],
        ).fetchone()[0]
        output.append(
            {
                **_registry_prefix(row),
                "state_name": state,
                "exact_day_intersection": overlap,
                "exact_day_union": union_days,
                "jaccard": overlap / union_days if union_days else None,
                "baseline_retention": overlap / baseline_days
                if baseline_days
                else None,
                "candidate_novelty": 1.0 - overlap / candidate_days
                if candidate_days
                else None,
                "added_state_days": candidate_days - overlap,
                "lost_state_days": baseline_days - overlap,
                "same_security_overlap": security_overlap,
                "confirmed_interval_overlap": interval_overlap,
                "candidate_confirmed_intervals": interval_index[state][
                    "confirmed_intervals"
                ],
                "candidate_confirmed_state_days": state_index[state][
                    "confirmed_state_days"
                ],
            }
        )
    return output


def _baseline_reconciliation(
    con: Any,
    row: Mapping[str, Any],
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    state_index = {item["state_name"]: item for item in state_rows}
    interval_index = {item["state_name"]: item for item in interval_rows}
    for state in ("S_PCT", "S_PCVT"):
        upstream = con.execute(
            """
            SELECT count(*) FILTER (WHERE raw_state IS TRUE),count(*) FILTER (WHERE confirmed_state IS TRUE),
              count(*) FILTER (WHERE validity_status='valid'),count(*) FILTER (WHERE validity_status='unknown'),
              count(*) FILTER (WHERE validity_status='blocked')
            FROM dailydb.r0_t07_daily_confirmation_results
            WHERE percentile_window_W=? AND abs(q-0.2)<1e-12 AND confirmation_k=3 AND state_name=?
            """,
            [row["W"], state],
        ).fetchone()
        up_interval = con.execute(
            """
            SELECT count(*),coalesce(sum(confirmed_duration_observations),0),count(*) FILTER (WHERE is_open_interval)
            FROM intervaldb.r0_t07_confirmed_interval_results
            WHERE percentile_window_W=? AND abs(q-0.2)<1e-12 AND confirmation_k=3 AND state_name=?
            """,
            [row["W"], state],
        ).fetchone()
        pairs = (
            ("raw_state_days", state_index[state]["raw_state_days"], upstream[0]),
            (
                "confirmed_state_days",
                state_index[state]["confirmed_state_days"],
                upstream[1],
            ),
            ("valid_rows", state_index[state]["valid_rows"], upstream[2]),
            ("unknown_rows", state_index[state]["unknown_rows"], upstream[3]),
            ("blocked_rows", state_index[state]["blocked_rows"], upstream[4]),
            (
                "confirmed_intervals",
                interval_index[state]["confirmed_intervals"],
                up_interval[0],
            ),
            (
                "confirmed_interval_total_duration",
                interval_index[state]["confirmed_interval_total_duration"],
                up_interval[1],
            ),
            ("open_intervals", interval_index[state]["open_intervals"], up_interval[2]),
        )
        output.extend(
            {
                **_registry_prefix(row),
                "state_name": state,
                "metric": metric,
                "diagnostic_value": actual,
                "upstream_value": expected,
                "mismatch_count": abs(int(actual) - int(expected)),
                "status": "passed" if int(actual) == int(expected) else "failed",
            }
            for metric, actual, expected in pairs
        )
    return output


def _merge_state_geometry(
    state_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    year_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    interval_index = {row["state_name"]: row for row in interval_rows}
    by_state = _group(year_rows, "state_name")
    output = []
    for state in state_rows:
        years = by_state[state["state_name"]]
        confirmed_total = int(state["confirmed_state_days"])
        shares = (
            [int(item["confirmed_state_days"]) / confirmed_total for item in years]
            if confirmed_total
            else []
        )
        output.append(
            {
                **dict(state),
                **{
                    key: value
                    for key, value in interval_index[state["state_name"]].items()
                    if key not in state
                },
                "nonzero_years": sum(
                    int(item["confirmed_state_days"]) > 0 for item in years
                ),
                "max_year_share": max(shares, default=0.0),
                "year_HHI": sum(value * value for value in shares),
                "effective_years": 1.0 / sum(value * value for value in shares)
                if shares
                else None,
            }
        )
    return output


def build_layer_response_profile(
    results: Mapping[str, Sequence[Mapping[str, Any]]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    state_index = {
        (row["candidate_q_vector_id"], row["state_name"]): row
        for row in results["state"]
    }
    inter_index = {
        (row["candidate_q_vector_id"], row["step_id"]): row
        for row in results["interlayer"]
        if row["profile_type"] == "pooled"
    }
    identity_index = {
        (row["candidate_q_vector_id"], row["state_name"]): row
        for row in results["identity"]
    }
    registry = _unique_registry(results["state"])
    output: list[dict[str, Any]] = []
    q_values = [float(value) for value in config["grid"]["Q"]]
    for window in config["grid"]["W"]:
        for layer in ("P", "C", "T", "V"):
            vectors = {
                float(row["changed_q"]): row
                for row in registry
                if row["W"] == window
                and (row["changed_layer"] == layer or row["role"] == "baseline")
            }
            affected_state = config["candidate_rules"]["affected_state_by_layer"][layer]
            affected_step = config["candidate_rules"]["affected_step_by_layer"][layer]
            metrics: dict[str, list[float | None]] = defaultdict(list)
            for q in q_values:
                vector = vectors[q]
                vid = vector["candidate_q_vector_id"]
                metrics["confirmed_coverage"].append(
                    _float(state_index[(vid, affected_state)]["confirmed_coverage"])
                )
                metrics["confirmed_intervals"].append(
                    _float(state_index[(vid, affected_state)]["confirmed_intervals"])
                )
                metrics["unique_securities"].append(
                    _float(state_index[(vid, affected_state)]["unique_securities"])
                )
                metrics["baseline_retention"].append(
                    _float(identity_index[(vid, affected_state)]["baseline_retention"])
                )
                metrics["affected_delta"].append(
                    _float(inter_index[(vid, affected_step)]["delta"])
                )
                metrics["affected_lift"].append(
                    _float(inter_index[(vid, affected_step)]["lift"])
                )
                metrics["fragment_rate"].append(
                    _float(state_index[(vid, affected_state)]["fragment_rate"])
                )
            for metric, values in metrics.items():
                diffs = [
                    None
                    if values[i] is None or values[i + 1] is None
                    else values[i + 1] - values[i]
                    for i in range(4)
                ]
                nonnull = [value for value in values if value is not None]
                monotonic_inc = len(nonnull) == 5 and all(
                    values[i + 1] >= values[i] for i in range(4)
                )
                monotonic_dec = len(nonnull) == 5 and all(
                    values[i + 1] <= values[i] for i in range(4)
                )
                tolerance = _response_tolerance(metric, config)
                left = (
                    None
                    if values[1] is None or values[2] is None
                    else (values[2] - values[1]) / 0.05
                )
                right = (
                    None
                    if values[2] is None or values[3] is None
                    else (values[3] - values[2]) / 0.05
                )
                output.append(
                    {
                        "W": window,
                        "changed_layer": layer,
                        "metric": metric,
                        **{
                            f"q{int(q * 100):02d}": value
                            for q, value in zip(q_values, values, strict=True)
                        },
                        "delta_10_15": diffs[0],
                        "delta_15_20": diffs[1],
                        "delta_20_25": diffs[2],
                        "delta_25_30": diffs[3],
                        "left_slope": left,
                        "right_slope": right,
                        "monotonic_increasing": monotonic_inc,
                        "monotonic_decreasing": monotonic_dec,
                        "locally_flat": left is not None
                        and right is not None
                        and abs(left * 0.05) <= tolerance
                        and abs(right * 0.05) <= tolerance,
                        "direction_reversal": any(
                            diffs[i] is not None
                            and diffs[i + 1] is not None
                            and diffs[i] * diffs[i + 1] < 0
                            for i in range(3)
                        ),
                        "boundary_response": diffs[0] is not None
                        and diffs[-1] is not None
                        and (abs(diffs[0]) > tolerance or abs(diffs[-1]) > tolerance),
                        "isolated_spike_warning": _isolated_spike(values, tolerance),
                    }
                )
    return output


def _response_tolerance(metric: str, config: Mapping[str, Any]) -> float:
    mapping = {
        "confirmed_coverage": "confirmed_coverage",
        "confirmed_intervals": "confirmed_intervals",
        "unique_securities": "unique_securities",
        "baseline_retention": "baseline_overlap",
        "affected_delta": "delta",
        "affected_lift": "lift_excess",
        "fragment_rate": "fragment_rate",
    }
    return float(config["fallback_tolerances"][mapping[metric]])


def _isolated_spike(values: Sequence[float | None], tolerance: float) -> bool:
    for index in range(1, len(values) - 1):
        if (
            values[index] is None
            or values[index - 1] is None
            or values[index + 1] is None
        ):
            continue
        if (
            abs(values[index] - values[index - 1]) > tolerance
            and abs(values[index] - values[index + 1]) > tolerance
            and (values[index] - values[index - 1])
            * (values[index] - values[index + 1])
            > 0
        ):
            return True
    return False


def build_stability_envelopes(
    results: Mapping[str, Sequence[Mapping[str, Any]]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    baselines = [
        row for row in _unique_registry(results["state"]) if row["role"] == "baseline"
    ]
    for baseline in baselines:
        vid = baseline["candidate_q_vector_id"]
        state_years = [
            row
            for row in results["year"]
            if row["candidate_q_vector_id"] == vid
            and row["profile_type"] == "state_year"
        ]
        for state_name, rows in _group(state_years, "state_name").items():
            total_valid = sum(int(row["valid_rows"]) for row in rows)
            total_true = sum(int(row["confirmed_state_days"]) for row in rows)
            pooled = total_true / total_valid if total_valid else None
            yearly = [
                int(row["confirmed_state_days"]) / int(row["valid_rows"])
                for row in rows
                if int(row["valid_rows"]) > 0
            ]
            loyo = [
                (total_true - int(row["confirmed_state_days"]))
                / (total_valid - int(row["valid_rows"]))
                for row in rows
                if total_valid > int(row["valid_rows"])
            ]
            output.append(
                _envelope_row(
                    baseline,
                    state_name,
                    "confirmed_coverage",
                    pooled,
                    yearly,
                    loyo,
                    config,
                )
            )
        for step_name, rows in _group(
            [
                row
                for row in results["year"]
                if row["candidate_q_vector_id"] == vid
                and row["profile_type"] == "interlayer_year"
            ],
            "step_id",
        ).items():
            pooled = next(
                row
                for row in results["interlayer"]
                if row["candidate_q_vector_id"] == vid
                and row["profile_type"] == "pooled"
                and row["step_id"] == step_name
            )
            loyo_rows = [
                row
                for row in results["loyo"]
                if row["candidate_q_vector_id"] == vid and row["step_id"] == step_name
            ]
            for metric, fallback in (("delta", "delta"), ("lift", "lift_excess")):
                output.append(
                    _envelope_row(
                        baseline,
                        step_name,
                        metric,
                        _float(pooled[metric]),
                        [_float(row[metric]) for row in rows],
                        [_float(row[metric]) for row in loyo_rows],
                        config,
                        fallback_key=fallback,
                    )
                )
    return output


def _envelope_row(
    baseline: Mapping[str, Any],
    scope: str,
    metric: str,
    pooled: float | None,
    yearly: Sequence[float | None],
    loyo: Sequence[float | None],
    config: Mapping[str, Any],
    fallback_key: str | None = None,
) -> dict[str, Any]:
    valid_year = [value for value in yearly if value is not None]
    valid_loyo = [value for value in loyo if value is not None]
    envelope = (
        max((abs(value - pooled) for value in valid_loyo), default=0.0)
        if pooled is not None
        else 0.0
    )
    mad = (
        statistics.median(
            [abs(value - statistics.median(valid_year)) for value in valid_year]
        )
        if valid_year
        else 0.0
    )
    fallback = float(config["fallback_tolerances"][fallback_key or metric])
    robust = max(envelope, 1.4826 * mad, fallback)
    return {
        **_registry_prefix(baseline),
        "scope": scope,
        "metric": metric,
        "pooled_baseline": pooled,
        "loyo_envelope": envelope,
        "annual_mad_scaled": 1.4826 * mad,
        "fallback_tolerance": fallback,
        "robust_envelope": robust,
    }


def select_materialization_request(
    *,
    registry: Sequence[Mapping[str, Any]],
    results: Mapping[str, Sequence[Mapping[str, Any]]],
    envelope_rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    state = {
        (row["candidate_q_vector_id"], row["state_name"]): row
        for row in results["state"]
    }
    pooled = {
        (row["candidate_q_vector_id"], row["step_id"]): row
        for row in results["interlayer"]
        if row["profile_type"] == "pooled"
    }
    security = {
        (row["candidate_q_vector_id"], row["step_id"]): row
        for row in results["interlayer"]
        if row["profile_type"] == "security_summary"
    }
    identity = {
        (row["candidate_q_vector_id"], row["state_name"]): row
        for row in results["identity"]
    }
    funnel = {
        (row["candidate_q_vector_id"], row["layer"]): row
        for row in results["common_funnel"]
    }
    baseline_by_w = {row["W"]: row for row in registry if row["role"] == "baseline"}
    envelope = {
        (row["W"], row["scope"], row["metric"]): float(row["robust_envelope"])
        for row in envelope_rows
    }
    q_lookup = {
        (row["W"], row["changed_layer"], float(row["changed_q"])): row
        for row in registry
        if row["role"] != "baseline"
    }
    audit: list[dict[str, Any]] = []
    passed_by_arch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in (row for row in registry if row["role"] != "baseline"):
        layer, window, q = (
            candidate["changed_layer"],
            candidate["W"],
            float(candidate["changed_q"]),
        )
        state_name = config["candidate_rules"]["affected_state_by_layer"][layer]
        step = config["candidate_rules"]["affected_step_by_layer"][layer]
        archetype = config["candidate_rules"]["archetype_by_layer_W"][
            f"{layer}_{window}"
        ]
        base = baseline_by_w[window]
        c_state, b_state = (
            state[(candidate["candidate_q_vector_id"], state_name)],
            state[(base["candidate_q_vector_id"], state_name)],
        )
        c_step, b_step = (
            pooled[(candidate["candidate_q_vector_id"], step)],
            pooled[(base["candidate_q_vector_id"], step)],
        )
        c_identity = identity[(candidate["candidate_q_vector_id"], state_name)]
        c_security = security[(candidate["candidate_q_vector_id"], step)]
        years = [
            row
            for row in results["year"]
            if row["candidate_q_vector_id"] == candidate["candidate_q_vector_id"]
            and row.get("profile_type") == "interlayer_year"
            and row.get("step_id") == step
            and row.get("delta") is not None
        ]
        loyos = [
            row
            for row in results["loyo"]
            if row["candidate_q_vector_id"] == candidate["candidate_q_vector_id"]
            and row["step_id"] == step
        ]
        neighbors = _immediate_q_neighbors(q)
        neighbor_rows = [
            q_lookup.get((window, layer, value))
            or (base if abs(value - 0.2) <= EPSILON else None)
            for value in neighbors
        ]
        neighbor_nondegenerate = all(
            item is not None
            and int(
                state[(item["candidate_q_vector_id"], state_name)][
                    "confirmed_state_days"
                ]
            )
            >= int(config["existence_floors"]["confirmed_state_days"])
            for item in neighbor_rows
        )
        floor = config["existence_floors"]
        existence = (
            int(c_state["confirmed_state_days"]) >= floor["confirmed_state_days"]
            and int(c_state["unique_securities"]) >= floor["unique_securities"]
            and int(c_state["confirmed_intervals"]) >= floor["confirmed_intervals"]
            and int(c_state["nonzero_years"]) >= floor["nonzero_years"]
            and float(c_state["max_year_share"]) <= floor["max_year_share"]
            and int(c_state["confirmed_state_days"]) < int(c_state["valid_rows"])
        )
        year_ok = bool(years) and all(float(item["delta"]) >= 0 for item in years)
        loyo_ok = bool(loyos) and all(
            item["delta"] is not None
            and float(item["delta"]) >= 0
            and item["lift"] is not None
            and float(item["lift"]) >= 1
            for item in loyos
        )
        sign_ok = (
            c_security.get("security_median_delta") is not None
            and float(c_security["security_median_delta"]) >= 0
        )
        child_strict = int(
            funnel[(candidate["candidate_q_vector_id"], "V")]["PCVT_count"]
        ) < int(funnel[(candidate["candidate_q_vector_id"], "V")]["PCT_count"])
        coverage_gain = float(c_state["confirmed_coverage"]) - float(
            b_state["confirmed_coverage"]
        )
        delta_gain = float(c_step["delta"]) - float(b_step["delta"])
        lift_gain = (float(c_step["lift"]) - 1.0) - (float(b_step["lift"]) - 1.0)
        material = (
            coverage_gain > envelope[(window, state_name, "confirmed_coverage")]
            or delta_gain > envelope[(window, step, "delta")]
            or lift_gain > envelope[(window, step, "lift")]
        )
        baseline_dominates = _dominates(
            _candidate_metrics(b_state, b_step, {"baseline_retention": 1.0}),
            _candidate_metrics(c_state, c_step, c_identity),
        )
        v_guard = True
        selectivity_retained = None
        if layer == "V":
            base_ratio = int(
                funnel[(base["candidate_q_vector_id"], "V")]["PCVT_count"]
            ) / int(funnel[(base["candidate_q_vector_id"], "V")]["PCT_count"])
            cand_ratio = int(
                funnel[(candidate["candidate_q_vector_id"], "V")]["PCVT_count"]
            ) / int(funnel[(candidate["candidate_q_vector_id"], "V")]["PCT_count"])
            selectivity_retained = (
                (1.0 - cand_ratio) / (1.0 - base_ratio) if base_ratio < 1 else None
            )
            v_guard = (
                selectivity_retained is not None
                and selectivity_retained
                >= config["candidate_rules"]["v_selectivity_retained_min"]
                and cand_ratio < 1
            )
        hard_gate = (
            existence
            and float(c_step["delta"]) > 0
            and float(c_step["lift"]) > 1
            and year_ok
            and loyo_ok
            and sign_ok
            and child_strict
            and neighbor_nondegenerate
            and material
            and not baseline_dominates
            and v_guard
        )
        reasons = [
            name
            for name, passed in (
                ("existence", existence),
                ("pooled_delta_positive", float(c_step["delta"]) > 0),
                ("pooled_lift_above_one", float(c_step["lift"]) > 1),
                ("year_direction", year_ok),
                ("loyo_direction", loyo_ok),
                ("pooled_security_direction", sign_ok),
                ("strict_parent_child", child_strict),
                ("neighbor_nondegenerate", neighbor_nondegenerate),
                ("material_advantage", material),
                ("not_baseline_dominated", not baseline_dominates),
                ("v_construct_guard", v_guard),
            )
            if not passed
        ]
        item = {
            **_registry_prefix(candidate),
            "archetype": archetype,
            "affected_state": state_name,
            "affected_step": step,
            "confirmed_coverage": c_state["confirmed_coverage"],
            "confirmed_state_days": c_state["confirmed_state_days"],
            "unique_securities": c_state["unique_securities"],
            "confirmed_intervals": c_state["confirmed_intervals"],
            "max_year_share": c_state["max_year_share"],
            "fragment_rate": c_state["fragment_rate"],
            "baseline_retention": c_identity["baseline_retention"],
            "affected_delta": c_step["delta"],
            "affected_lift": c_step["lift"],
            "affected_lift_excess": float(c_step["lift"]) - 1.0,
            "selectivity_retained": selectivity_retained,
            "hard_gate_pass": hard_gate,
            "rejection_reasons": "|".join(reasons),
            "pareto_frontier": False,
            "selected_center": False,
        }
        audit.append(item)
        if hard_gate:
            passed_by_arch[archetype].append(item)
    selected: list[dict[str, Any]] = []
    archetype_rows: list[dict[str, Any]] = []
    for priority, archetype in enumerate(
        config["candidate_rules"]["archetype_priority"], start=1
    ):
        candidates = passed_by_arch.get(archetype, [])
        frontier = [
            item
            for item in candidates
            if not any(
                other is not item
                and _dominates(_audit_metrics(other), _audit_metrics(item))
                for other in candidates
            )
        ]
        for item in frontier:
            item["pareto_frontier"] = True
        winner = min(frontier, key=_selection_sort_key) if frontier else None
        if winner:
            winner["selected_center"] = True
            selected.append(winner)
        archetype_rows.append(
            {
                "archetype": archetype,
                "priority": priority,
                "hard_gate_candidate_count": len(candidates),
                "pareto_count": len(frontier),
                "selected_center_id": winner["candidate_q_vector_id"]
                if winner
                else None,
                "status": "selected" if winner else "no_eligible_center",
            }
        )
    request_registry = _expand_request_registry(selected, registry, config)
    if selected:
        decision = {
            "task_id": TASK_ID,
            "run_id": run_id,
            "decision": "q_vector_materialization_request",
            "request_id": f"R1-T14-01-{run_id}-R0-T15",
            "R0_q_vector_materialization_task_id": "R0-T15",
            "center_count": len(selected),
            "nonbaseline_formal_vector_count": sum(
                row["request_role"] != "baseline_reference" for row in request_registry
            ),
            "frozen_registry": request_registry,
            "scientific_review_status": "pending",
            "reviewer_identity": "unassigned",
            "independence_attestation": False,
            "goal_internal_continuation_gate_status": "pending_author_analysis",
            "goal_internal_continuation_allowed": False,
            "repository_r0_materialization_gate_passed": False,
        }
    else:
        decision = {
            "task_id": TASK_ID,
            "run_id": run_id,
            "decision": "no_q_decoupling_candidate",
            "reason": "no_nonbaseline_point_passed_all_preregistered_hard_gates_and_pareto_rules",
            "scientific_review_status": "pending",
            "reviewer_identity": "unassigned",
            "independence_attestation": False,
            "goal_internal_continuation_gate_status": "pending_author_analysis",
            "goal_internal_continuation_allowed": False,
        }
    return archetype_rows, audit, decision


def _candidate_metrics(
    state: Mapping[str, Any], step: Mapping[str, Any], identity: Mapping[str, Any]
) -> dict[str, float]:
    return {
        "confirmed_coverage": float(state["confirmed_coverage"]),
        "affected_delta": float(step["delta"]),
        "affected_lift_excess": float(step["lift"]) - 1.0,
        "baseline_retention": float(identity["baseline_retention"]),
        "max_year_share": float(state["max_year_share"]),
        "fragment_rate": float(state["fragment_rate"]),
    }


def _audit_metrics(item: Mapping[str, Any]) -> dict[str, float]:
    return {
        key: float(item[key])
        for key in (
            "confirmed_coverage",
            "affected_delta",
            "affected_lift_excess",
            "baseline_retention",
            "max_year_share",
            "fragment_rate",
        )
    }


def _dominates(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    maximize = (
        "confirmed_coverage",
        "affected_delta",
        "affected_lift_excess",
        "baseline_retention",
    )
    minimize = ("max_year_share", "fragment_rate")
    no_worse = all(left[key] >= right[key] - EPSILON for key in maximize) and all(
        left[key] <= right[key] + EPSILON for key in minimize
    )
    better = any(left[key] > right[key] + EPSILON for key in maximize) or any(
        left[key] < right[key] - EPSILON for key in minimize
    )
    return no_worse and better


def _selection_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    q_values = [float(item[key]) for key in ("qP", "qC", "qT", "qV")]
    return (
        sum(abs(value - 0.2) > EPSILON for value in q_values),
        sum(abs(value - 0.2) for value in q_values),
        -float(item["baseline_retention"]),
        float(item["max_year_share"]),
        float(item["fragment_rate"]),
        -float(item["affected_delta"]),
        str(item["candidate_q_vector_id"]),
    )


def _expand_request_registry(
    selected: Sequence[Mapping[str, Any]],
    registry: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    lookup = {
        (row["W"], row["changed_layer"], float(row["changed_q"])): row
        for row in registry
        if row["role"] != "baseline"
    }
    baseline = {row["W"]: row for row in registry if row["role"] == "baseline"}
    expanded: dict[str, dict[str, Any]] = {}
    for center in selected:
        source = next(
            row
            for row in registry
            if row["candidate_q_vector_id"] == center["candidate_q_vector_id"]
        )
        expanded[source["candidate_q_vector_id"]] = {
            **_registry_prefix(source),
            "request_role": "center",
            "archetype": center["archetype"],
            "center_id": source["candidate_q_vector_id"],
            "same_parameter_parent_id": vector_id(
                source["W"], source["qP"], source["qC"], source["qT"], 0.2
            )
            if source["changed_layer"] == "V"
            else source["candidate_q_vector_id"],
            "selection_reason": "passed_hard_gates_pareto_and_deterministic_tie_break",
            "interaction_unobserved_in_t14_01": False,
        }
        for q in _immediate_q_neighbors(float(source["changed_q"])):
            neighbor = (
                baseline[source["W"]]
                if abs(q - 0.2) <= EPSILON
                else lookup[(source["W"], source["changed_layer"], q)]
            )
            role = (
                "baseline_reference"
                if neighbor["role"] == "baseline"
                else "immediate_neighbor"
            )
            expanded.setdefault(
                neighbor["candidate_q_vector_id"],
                {
                    **_registry_prefix(neighbor),
                    "request_role": role,
                    "archetype": center["archetype"],
                    "center_id": source["candidate_q_vector_id"],
                    "same_parameter_parent_id": vector_id(
                        neighbor["W"],
                        neighbor["qP"],
                        neighbor["qC"],
                        neighbor["qT"],
                        0.2,
                    )
                    if source["changed_layer"] == "V"
                    else neighbor["candidate_q_vector_id"],
                    "selection_reason": "mandatory_coordinate_neighbor",
                    "interaction_unobserved_in_t14_01": False,
                },
            )
        expanded.setdefault(
            baseline[source["W"]]["candidate_q_vector_id"],
            {
                **_registry_prefix(baseline[source["W"]]),
                "request_role": "baseline_reference",
                "archetype": center["archetype"],
                "center_id": source["candidate_q_vector_id"],
                "same_parameter_parent_id": baseline[source["W"]][
                    "candidate_q_vector_id"
                ],
                "selection_reason": "shared_baseline_lineage_reference",
                "interaction_unobserved_in_t14_01": False,
            },
        )
    rows = sorted(
        expanded.values(),
        key=lambda row: (
            row["W"],
            {"baseline_reference": 0, "center": 1, "immediate_neighbor": 2}[
                row["request_role"]
            ],
            row["candidate_q_vector_id"],
        ),
    )
    nonbaseline = sum(row["request_role"] != "baseline_reference" for row in rows)
    if nonbaseline > config["candidate_rules"]["nonbaseline_vector_count_max"]:
        raise R1T1401Error("request_registry_nonbaseline_limit_exceeded")
    return rows


def _immediate_q_neighbors(q: float) -> tuple[float, ...]:
    mapping = {0.1: (0.15,), 0.15: (0.1, 0.2), 0.25: (0.2, 0.3), 0.3: (0.25,)}
    return mapping[round(q, 2)]


def build_anomaly_scan(
    registry: Sequence[Mapping[str, Any]],
    results: Mapping[str, Sequence[Mapping[str, Any]]],
    decision: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    state = results["state"]
    mismatch = sum(int(row["mismatch_count"]) for row in results["reconciliation"])
    checks = {
        "grid_cardinality": len(registry) == 34,
        "baseline_reconciliation_mismatch_zero": mismatch == 0,
        "no_all_null": all(int(row["valid_rows"]) > 0 for row in state),
        "no_all_zero": all(int(row["raw_state_days"]) > 0 for row in state),
        "no_all_one": all(
            int(row["raw_state_days"]) < int(row["valid_rows"]) for row in state
        ),
        "parent_child_daily_invariant": all(
            int(row["PCVT_count"]) <= int(row["PCT_count"])
            for row in results["common_funnel"]
        ),
        "interval_duration_conservation": all(
            int(row["confirmed_interval_total_duration"])
            == int(
                next(
                    item
                    for item in state
                    if item["candidate_q_vector_id"] == row["candidate_q_vector_id"]
                    and item["state_name"] == row["state_name"]
                )["confirmed_state_days"]
            )
            for row in results["interval"]
        ),
        "availability_constant_within_W": _availability_constant(
            results["common_funnel"]
        ),
        "decision_enum": decision["decision"]
        in {"q_vector_materialization_request", "no_q_decoupling_candidate"},
    }
    findings = [name for name, passed in checks.items() if not passed]
    return {
        "task_id": TASK_ID,
        "diagnostic_namespace": NAMESPACE,
        "checks": checks,
        "blocking_findings": findings,
        "unresolved_questions": [],
        "anomaly_resolution_status": "passed" if not findings else "failed",
        "status": "passed" if not findings else "failed",
    }


def _availability_constant(rows: Sequence[Mapping[str, Any]]) -> bool:
    values: dict[int, set[int]] = defaultdict(set)
    for row in rows:
        values[int(row["W"])].add(int(row["common_valid_N"]))
    return all(len(items) == 1 for items in values.values())


def build_diagnostic_summary(
    *,
    run_id: str,
    code_commit: str,
    config: Mapping[str, Any],
    inputs: Mapping[str, Mapping[str, Any]],
    results: Mapping[str, Sequence[Mapping[str, Any]]],
    decision: Mapping[str, Any],
    anomaly_scan: Mapping[str, Any],
    runtime_seconds: float,
) -> dict[str, Any]:
    artifacts = {}
    output_dir = ROOT / "data/generated/r1/r1_t14_01" / run_id
    for name in (*CSV_ARTIFACTS, "r1_t14_01_anomaly_scan.json"):
        path = output_dir / name
        if path.is_file():
            artifacts[name] = {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256_file(path),
                "row_count": _artifact_row_count(path),
            }
    return {
        "task_id": TASK_ID,
        "stage": "R1",
        "task_class": "exploratory_structural_diagnostic",
        "run_id": run_id,
        "code_commit": code_commit,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "runtime_seconds": runtime_seconds,
        "config_path": str(CONFIG_PATH.relative_to(ROOT)).replace("\\", "/"),
        "config_sha256": sha256_file(CONFIG_PATH),
        "diagnostic_namespace": NAMESPACE,
        "authoritative": False,
        "formal_candidate_state": False,
        "input_lineage": {
            name: {key: value for key, value in item.items() if key != "absolute_path"}
            for name, item in inputs.items()
        },
        "grid_vector_W_count": len(_unique_registry(results["state"])),
        "decision": decision["decision"],
        "center_count": decision.get("center_count", 0),
        "anomaly_scan_status": anomaly_scan["status"],
        "anomaly_resolution_status": anomaly_scan["anomaly_resolution_status"],
        "engineering_validator_status": "pending",
        "author_result_analysis_status": "pending",
        "scientific_review_status": "pending",
        "review_phase": "author_analysis_pending",
        "independent_review_status": "not_started",
        "downstream_gate_allowed": False,
        "formal_task_completed": False,
        "goal_internal_continuation_gate_status": "pending_author_analysis",
        "goal_internal_continuation_allowed": False,
        "artifacts": artifacts,
    }


def build_author_draft_result_package(
    *,
    run_dir: str | Path,
    analysis_path: str | Path,
    evidence_path: str | Path,
    engineering_validation_path: str | Path,
    readme_path: str | Path,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    analysis_path = Path(analysis_path)
    evidence_path = Path(evidence_path)
    engineering_validation_path = Path(engineering_validation_path)
    readme_path = Path(readme_path)
    summary_path = run_dir / "r1_t14_01_diagnostic_summary.json"
    anomaly_path = run_dir / "r1_t14_01_anomaly_scan.json"
    summary = _load_json(summary_path)
    anomaly = _load_json(anomaly_path)
    engineering = _load_json(engineering_validation_path)
    if anomaly.get("status") != "passed" or anomaly.get("blocking_findings"):
        raise R1T1401Error("anomaly_gate_not_passed")
    if engineering.get("status") != "passed":
        raise R1T1401Error("engineering_validation_not_passed")
    if not analysis_path.is_file() or not evidence_path.is_file():
        raise R1T1401Error("analysis_or_evidence_missing")
    decision_paths = [
        run_dir / "r1_t14_01_materialization_request.json",
        run_dir / "r1_t14_01_no_candidate_decision.json",
    ]
    existing = [path for path in decision_paths if path.is_file()]
    if len(existing) != 1:
        raise R1T1401Error("exactly_one_decision_artifact_required")
    decision_path = existing[0]
    decision = _load_json(decision_path)
    internal_allowed = decision["decision"] == "q_vector_materialization_request"
    decision.update(
        {
            "scientific_review_status": "pending",
            "reviewer_identity": "unassigned",
            "independence_attestation": False,
            "goal_internal_continuation_gate_status": "passed",
            "goal_internal_continuation_allowed": internal_allowed,
            "goal_internal_r0_materialization_authorized": internal_allowed,
            "repository_r0_materialization_gate_passed": False,
        }
    )
    write_json_atomic(decision_path, decision)
    primary_names = [
        name
        for name in CSV_ARTIFACTS
        if name not in {"r1_t14_01_upstream_reconciliation.csv"}
    ] + [decision_path.name]
    diagnostic_names = [
        "r1_t14_01_upstream_reconciliation.csv",
        "r1_t14_01_anomaly_scan.json",
        "r1_t14_01_diagnostic_summary.json",
    ]
    package = {
        "task_id": TASK_ID,
        "stage": "R1",
        "task_class": "exploratory_structural_diagnostic",
        "run_id": summary["run_id"],
        "code_commit": summary["code_commit"],
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "input_lineage": summary["input_lineage"],
        "decision": decision["decision"],
        "decision_path": _rel(decision_path),
        "decision_sha256": sha256_file(decision_path),
        "result_analysis_path": _rel(analysis_path),
        "result_analysis_sha256": sha256_file(analysis_path),
        "formal_evidence_path": _rel(evidence_path),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "engineering_validation_result_path": _rel(engineering_validation_path),
        "engineering_validation_result_sha256": sha256_file(
            engineering_validation_path
        ),
        "anomaly_scan_path": _rel(anomaly_path),
        "anomaly_scan_sha256": sha256_file(anomaly_path),
        "readme_path": _rel(readme_path),
        "readme_sha256": sha256_file(readme_path),
        "primary_result_artifacts": [
            _artifact_record(run_dir / name, "primary_results")
            for name in primary_names
        ],
        "diagnostic_artifacts": [
            _artifact_record(run_dir / name, "diagnostic_summary")
            for name in diagnostic_names
        ],
        "gate_status": {
            "engineering_validator_status": "passed",
            "author_result_analysis_status": "passed",
            "anomaly_resolution_status": "passed",
            "scientific_review_status": "pending",
            "review_phase": "author_analysis_complete",
            "independent_review_status": "not_started",
            "goal_internal_continuation_gate_status": "passed",
            "goal_internal_continuation_allowed": internal_allowed,
            "repository_final_gate_status": "pending",
        },
        "downstream_gate_allowed": False,
        "R0_q_vector_materialization_allowed_to_start": False,
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "formal_task_completed": False,
        "scientific_review_status": "pending",
        "reviewer_identity": "unassigned",
        "independence_attestation": False,
        "status": "author_draft_complete",
        "superseded": False,
    }
    target = run_dir / "r1_t14_01_result_package.json"
    write_json_atomic(target, package)
    return package


def _artifact_record(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise R1T1401Error(f"required_artifact_missing:{path}")
    return {
        "artifact_role": role,
        "path": _rel(path),
        "sha256": sha256_file(path),
        "record_count": _artifact_row_count(path),
        "committed_to_repo": True,
    }


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _query_dicts(
    con: Any,
    sql: str,
    params: Sequence[Any] | None = None,
    prefix: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cursor = con.execute(sql, params or [])
    columns = [item[0] for item in cursor.description]
    base = _registry_prefix(prefix) if prefix else {}
    return [
        {**base, **dict(zip(columns, values, strict=True))}
        for values in cursor.fetchall()
    ]


def _registry_prefix(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        key: row[key]
        for key in (
            "candidate_q_vector_id",
            "W",
            "K",
            "qP",
            "qC",
            "qT",
            "qV",
            "changed_layer",
            "changed_q",
            "role",
        )
        if key in row
    }


def _unique_registry(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        seen.setdefault(str(row["candidate_q_vector_id"]), _registry_prefix(row))
    return list(seen.values())


def _group(
    rows: Iterable[Mapping[str, Any]], key: str
) -> dict[Any, list[Mapping[str, Any]]]:
    grouped: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise R1T1401Error(f"json_object_required:{path}")
    return value


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    if isinstance(value, bool):
        return str(value).lower()
    return value


def _artifact_row_count(path: Path) -> int:
    if path.suffix == ".csv":
        with path.open(encoding="utf-8") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    return 1


def _selection_sort_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        list(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
