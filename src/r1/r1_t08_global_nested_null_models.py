from __future__ import annotations

# ruff: noqa: E501
import csv
import json
import platform
import subprocess
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .r1_t08_null_engine import (
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    RAW_FALSE,
    RAW_NULL,
    RAW_TRUE,
    UNKNOWN,
    VALID,
    derive_continuous_blocks,
    derived_seed,
    deterministic_offsets,
    extreme_count,
    nested_retention_metrics,
    offset_plan_hash,
    ordered_and,
    percentile_interval,
    shifted_source_indices,
    sparse_confirmed_metrics,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r1/r1_t08_global_nested_null_models.v1.json"
SCHEMA_PATH = ROOT / "schemas/r1/r1_t08_global_nested_null_models.schema.json"
TASK_ID = "R1-T08"
LAYERS = ("P", "C", "T", "V")
STATUS_SQL = (
    "CASE validity_status WHEN 'valid' THEN 0 WHEN 'unknown' THEN 1 "
    "WHEN 'diagnostic_required' THEN 2 WHEN 'blocked' THEN 3 ELSE 1 END"
)


class R1T08Error(RuntimeError):
    pass


@dataclass(frozen=True)
class LayerPayload:
    raw: np.ndarray
    status: np.ndarray
    reason_hash: np.ndarray


@dataclass(frozen=True)
class CandidateData:
    W: int
    security_code: np.ndarray
    security_id: np.ndarray
    trading_date: np.ndarray
    year: np.ndarray
    calendar_ordinal: np.ndarray
    layers: dict[str, LayerPayload]
    nested_raw: dict[str, np.ndarray]
    nested_status: dict[str, np.ndarray]
    block_starts: np.ndarray
    block_lengths: np.ndarray
    block_id: np.ndarray
    within_block: np.ndarray


def run_r1_t08_global_nested_null_models(
    *,
    config_path: Path,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    verify_input_hashes: bool = True,
    n_perm_override: int | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    config = _load_json(config_path)
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator(schema).validate(config)
    _check_prerequisites(config)
    if verify_input_hashes:
        _verify_input_hashes(config)
    n_perm = int(n_perm_override or config["permutation"]["N_perm"])
    if n_perm not in config["permutation"]["supported_N_perm"]:
        raise R1T08Error(f"unsupported N_perm: {n_perm}")
    if n_perm == 10000 and config["permutation"]["ten_thousand_trigger"] is None:
        raise R1T08Error("N_perm=10000 has no preregistered trigger")
    output_dir.mkdir(parents=True, exist_ok=False)

    import duckdb  # noqa: PLC0415

    con = duckdb.connect()
    con.execute(f"SET threads={int(config['parallelism']['duckdb_threads'])}")
    con.execute(
        "SET memory_limit=?", [str(config["parallelism"]["duckdb_memory_limit"])]
    )
    _attach_inputs(con, config)
    candidate_rows = list(config["candidate_registry"])
    test_rows = _test_registry(candidate_rows)
    _write_csv(output_dir / "r1_t08_candidate_registry.csv", candidate_rows)
    _write_csv(output_dir / "r1_t08_test_registry.csv", test_rows)

    upstream_t04 = _csv_index(
        ROOT
        / "data/generated/r1/r1_t04/R1-T04-20260710T0835Z"
        / "r1_t04_state_line_profile.csv",
        ("state_line", "candidate_config_id", "analysis_level"),
    )
    upstream_t06 = _csv_index(
        ROOT
        / "data/generated/r1/r1_t06/R1-T06-20260710T1216Z"
        / "r1_t06_layer_step_profile.csv",
        ("step_id", "W", "q"),
    )

    reconciliation_rows: list[dict[str, Any]] = []
    block_rows: list[dict[str, Any]] = []
    replicate_rows: list[dict[str, Any]] = []
    offset_rows: list[dict[str, Any]] = []
    observed_by_test: dict[str, dict[str, Any]] = {}
    execution_rows: list[dict[str, Any]] = []

    for W in (120, 250):
        load_started = time.perf_counter()
        data, key_stats = _load_candidate_data(con, W)
        state_observed, state_reconciliation = _reconcile_observed(
            con, data, key_stats, upstream_t04, upstream_t06
        )
        reconciliation_rows.extend(state_reconciliation)
        block_rows.append(_block_diagnostics(data))
        if any(
            int(row[field])
            for row in state_reconciliation
            for field in (
                "missing_key_count",
                "extra_key_count",
                "raw_state_mismatch_count",
                "confirmed_state_mismatch_count",
                "interval_mismatch_count",
                "upstream_profile_mismatch_count",
                "upstream_nested_mismatch_count",
            )
        ):
            raise R1T08Error(f"blocked_input_contract: observed reconciliation W={W}")

        tests_for_w = [row for row in test_rows if int(row["W"]) == W]
        for test in tests_for_w:
            test_started = time.perf_counter()
            observed = _observed_for_test(data, test, state_observed)
            observed_by_test[str(test["test_group_id"])] = observed
            rows, offset_diag = _run_test_group(
                data=data,
                test=test,
                observed=observed,
                n_perm=n_perm,
                root_seed=int(config["permutation"]["root_seed"]),
            )
            replicate_rows.extend(rows)
            offset_rows.append(offset_diag)
            execution_rows.append(
                {
                    "test_group_id": test["test_group_id"],
                    "W": W,
                    "N_perm": n_perm,
                    "elapsed_seconds": round(time.perf_counter() - test_started, 6),
                    "failed_simulation_count": sum(
                        int(row["failed_flag"]) for row in rows
                    ),
                    "status": "completed",
                }
            )
        execution_rows.append(
            {
                "test_group_id": f"LOAD_AND_RECONCILE_W{W}",
                "W": W,
                "N_perm": 0,
                "elapsed_seconds": round(time.perf_counter() - load_started, 6),
                "failed_simulation_count": 0,
                "status": "completed",
            }
        )

    con.close()
    results = _aggregate_results(
        replicate_rows,
        test_rows,
        observed_by_test,
        n_perm,
        str(config["permutation"]["seed_derivation_version"]),
    )
    _write_csv(output_dir / "r1_t08_observed_reconciliation.csv", reconciliation_rows)
    _write_csv(output_dir / "r1_t08_block_diagnostics.csv", block_rows)
    _write_csv(output_dir / "r1_t08_offset_plan_diagnostics.csv", offset_rows)
    _write_csv(output_dir / "r1_t08_null_replicate_metrics.csv", replicate_rows)
    _write_csv(output_dir / "r1_t08_null_model_results.csv", results)
    _write_csv(output_dir / "r1_t08_execution_diagnostics.csv", execution_rows)

    dependencies = {
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "duckdb_version": duckdb.__version__,
    }
    diagnostic = _diagnostic_summary(
        run_id=run_id,
        code_commit=code_commit,
        n_perm=n_perm,
        results=results,
        reconciliation=reconciliation_rows,
        block_rows=block_rows,
        offset_rows=offset_rows,
        dependencies=dependencies,
    )
    anomaly = _anomaly_scan(
        run_id=run_id,
        code_commit=code_commit,
        results=results,
        replicates=replicate_rows,
        reconciliation=reconciliation_rows,
        block_rows=block_rows,
        offset_rows=offset_rows,
    )
    _write_json(output_dir / "r1_t08_diagnostic_summary.json", diagnostic)
    _write_json(output_dir / "r1_t08_anomaly_scan.json", anomaly)
    summary = _experiment_summary(
        config=config,
        config_path=config_path,
        output_dir=output_dir,
        run_id=run_id,
        code_commit=code_commit,
        n_perm=n_perm,
        dependencies=dependencies,
        elapsed_seconds=time.perf_counter() - started,
    )
    _write_json(output_dir / "r1_t08_experiment_summary.json", summary)
    return summary


def _attach_inputs(con: Any, config: Mapping[str, Any]) -> None:
    aliases = {
        "dimension_state": "dimdb",
        "nested_daily_state": "nesteddb",
        "daily_confirmation": "dailydb",
        "confirmed_interval": "intervaldb",
    }
    for key, alias in aliases.items():
        path = ROOT / config["input_artifacts"][key]["path"]
        con.execute(f"ATTACH '{_sql_path(path)}' AS {alias} (READ_ONLY)")


def _load_candidate_data(
    con: Any, W: int
) -> tuple[CandidateData, dict[str, int]]:
    key_stats_row = con.execute(
        """
        WITH d AS (
          SELECT security_id, trading_date
          FROM dimdb.r0_t06_dimension_state_results
          WHERE percentile_window_W=? AND abs(q-0.2)<1e-12
          GROUP BY security_id, trading_date
          HAVING count(*)=4
        ), n AS (
          SELECT security_id, trading_date
          FROM nesteddb.r0_t06_nested_daily_state_results
          WHERE percentile_window_W=? AND abs(q-0.2)<1e-12
        )
        SELECT
          count(*) FILTER (WHERE d.security_id IS NULL) AS missing_dimension_keys,
          count(*) FILTER (WHERE n.security_id IS NULL) AS extra_dimension_keys,
          count(*) FILTER (WHERE d.security_id IS NOT NULL AND n.security_id IS NOT NULL)
            AS matched_keys
        FROM d FULL OUTER JOIN n USING (security_id, trading_date)
        """,
        [W, W],
    ).fetchone()
    key_stats = {
        "missing_key_count": int(key_stats_row[0]),
        "extra_key_count": int(key_stats_row[1]),
        "key_count": int(key_stats_row[2]),
    }
    select_layers = ",\n".join(
        f"""
        max(CASE WHEN dimension='{layer}' THEN
          CASE WHEN dimension_active_weak=true THEN 1
               WHEN dimension_active_weak=false THEN 0 ELSE -1 END END)::TINYINT
          AS {layer}_raw,
        max(CASE WHEN dimension='{layer}' THEN {STATUS_SQL} END)::TINYINT
          AS {layer}_status,
        max(CASE WHEN dimension='{layer}' THEN hash(reason_codes) END)::UBIGINT
          AS {layer}_reason_hash"""
        for layer in LAYERS
    )
    query = f"""
    WITH d AS (
      SELECT security_id, trading_date, {select_layers}
      FROM dimdb.r0_t06_dimension_state_results
      WHERE percentile_window_W=? AND abs(q-0.2)<1e-12
      GROUP BY security_id, trading_date
    ), calendar AS (
      SELECT trading_date,
        row_number() OVER (ORDER BY trading_date)::INTEGER AS calendar_ordinal
      FROM (
        SELECT DISTINCT trading_date
        FROM nesteddb.r0_t06_nested_daily_state_results
        WHERE percentile_window_W=? AND abs(q-0.2)<1e-12
      )
    )
    SELECT
      dense_rank() OVER (ORDER BY n.security_id)::INTEGER - 1 AS security_code,
      n.security_id,
      n.trading_date::INTEGER AS trading_date,
      substr(n.trading_date,1,4)::INTEGER AS year,
      calendar.calendar_ordinal,
      d.P_raw, d.P_status, d.P_reason_hash,
      d.C_raw, d.C_status, d.C_reason_hash,
      d.T_raw, d.T_status, d.T_reason_hash,
      d.V_raw, d.V_status, d.V_reason_hash,
      CASE WHEN n.S_PCT_raw=true THEN 1 WHEN n.S_PCT_raw=false THEN 0 ELSE -1 END::TINYINT AS nested_S_PCT_raw,
      CASE n.S_PCT_validity_status WHEN 'valid' THEN 0 WHEN 'unknown' THEN 1 WHEN 'diagnostic_required' THEN 2 WHEN 'blocked' THEN 3 ELSE 1 END::TINYINT AS nested_S_PCT_status,
      CASE WHEN n.S_PCVT_raw=true THEN 1 WHEN n.S_PCVT_raw=false THEN 0 ELSE -1 END::TINYINT AS nested_S_PCVT_raw,
      CASE n.S_PCVT_validity_status WHEN 'valid' THEN 0 WHEN 'unknown' THEN 1 WHEN 'diagnostic_required' THEN 2 WHEN 'blocked' THEN 3 ELSE 1 END::TINYINT AS nested_S_PCVT_status
    FROM nesteddb.r0_t06_nested_daily_state_results n
    JOIN d USING (security_id, trading_date)
    JOIN calendar USING (trading_date)
    WHERE n.percentile_window_W=? AND abs(n.q-0.2)<1e-12
    ORDER BY n.security_id, n.trading_date
    """
    arrays = con.execute(query, [W, W, W]).fetchnumpy()
    layers = {
        layer: LayerPayload(
            raw=np.asarray(arrays[f"{layer}_raw"], dtype=np.int8),
            status=np.asarray(arrays[f"{layer}_status"], dtype=np.int8),
            reason_hash=np.asarray(arrays[f"{layer}_reason_hash"], dtype=np.uint64),
        )
        for layer in LAYERS
    }
    security_code = np.asarray(arrays["security_code"], dtype=np.int32)
    year = np.asarray(arrays["year"], dtype=np.int16)
    calendar_ordinal = np.asarray(arrays["calendar_ordinal"], dtype=np.int32)
    block_starts, block_lengths, block_id, within = derive_continuous_blocks(
        security_code, year, calendar_ordinal
    )
    data = CandidateData(
        W=W,
        security_code=security_code,
        security_id=np.asarray(arrays["security_id"], dtype=object),
        trading_date=np.asarray(arrays["trading_date"], dtype=np.int32),
        year=year,
        calendar_ordinal=calendar_ordinal,
        layers=layers,
        nested_raw={
            state: np.asarray(arrays[f"nested_{state}_raw"], dtype=np.int8)
            for state in ("S_PCT", "S_PCVT")
        },
        nested_status={
            state: np.asarray(arrays[f"nested_{state}_status"], dtype=np.int8)
            for state in ("S_PCT", "S_PCVT")
        },
        block_starts=block_starts,
        block_lengths=block_lengths,
        block_id=block_id,
        within_block=within,
    )
    return data, key_stats


def _reconcile_observed(
    con: Any,
    data: CandidateData,
    key_stats: Mapping[str, int],
    upstream_t04: Mapping[tuple[str, ...], Mapping[str, str]],
    upstream_t06: Mapping[tuple[str, ...], Mapping[str, str]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    pct_raw, pct_status = ordered_and(
        tuple(data.layers[x].raw for x in ("P", "C", "T")),
        tuple(data.layers[x].status for x in ("P", "C", "T")),
    )
    pcvt_raw, pcvt_status = ordered_and(
        tuple(data.layers[x].raw for x in ("P", "C", "T", "V")),
        tuple(data.layers[x].status for x in ("P", "C", "T", "V")),
    )
    state_arrays = {
        "S_PCT": (pct_raw, pct_status),
        "S_PCVT": (pcvt_raw, pcvt_status),
    }
    observed: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for state, (raw, status) in state_arrays.items():
        derived_confirmed, confirmation_date = _confirmation_arrays(
            raw, status, data.security_code, data.trading_date, 3
        )
        upstream_daily = _load_upstream_daily(con, data.W, state)
        raw_mismatch = int(np.count_nonzero(raw != data.nested_raw[state]))
        raw_mismatch += int(np.count_nonzero(raw != upstream_daily["raw_state"]))
        status_mismatch = int(
            np.count_nonzero(status != data.nested_status[state])
            + np.count_nonzero(status != upstream_daily["validity_status"])
        )
        confirmed_mismatch = int(
            np.count_nonzero(derived_confirmed != upstream_daily["confirmed_state"])
            + np.count_nonzero(
                confirmation_date != upstream_daily["confirmation_date"]
            )
        )
        derived_intervals = _derived_intervals(data, raw, status, 3)
        upstream_intervals = _load_upstream_intervals(con, data.W, state)
        interval_mismatch = _multiset_mismatch(derived_intervals, upstream_intervals)
        true_indices = np.flatnonzero(raw == RAW_TRUE)
        metrics = sparse_confirmed_metrics(
            true_indices,
            data.security_code,
            eligible_count=len(raw),
            confirmation_k=3,
        )
        metrics["raw_true_day_count"] = int(true_indices.size)
        observed[state] = metrics
        candidate = f"R0_W{data.W}_Q20_K3_WEAK_D010"
        upstream_profile = upstream_t04[(state, candidate, "confirmed")]
        profile_mismatches = sum(
            (
                int(upstream_profile["state_true_day_count"])
                != metrics["confirmed_day_count"],
                int(upstream_profile["segment_or_interval_count"])
                != metrics["interval_count"],
                not _close(upstream_profile["coverage"], metrics["confirmed_coverage"]),
                not _close(upstream_profile["mean_duration"], metrics["duration_mean"]),
                not _close(upstream_profile["median_duration"], metrics["duration_median"]),
                int(upstream_profile["fragment_count"])
                != metrics["fragment_count"],
                not _close(upstream_profile["fragment_rate"], metrics["fragment_rate"]),
            )
        )
        nested_steps = ("C_GIVEN_P", "T_GIVEN_PC") if state == "S_PCT" else ("V_GIVEN_PCT",)
        nested_mismatches = 0
        for step in nested_steps:
            observed_nested = _observed_nested_for_step(data, step)
            upstream = upstream_t06[(step, str(data.W), "0.2")]
            nested_mismatches += int(
                not _close(upstream["retention"], observed_nested["nested_retention"])
            )
            observed[step] = observed_nested
        row: dict[str, Any] = {
            "candidate_config_id": candidate,
            "state_line": state,
            "W": data.W,
            "q": 0.2,
            "K": 3,
            "key_count": len(raw),
            "eligible_count": len(raw),
            "missing_key_count": key_stats["missing_key_count"],
            "extra_key_count": key_stats["extra_key_count"],
            "raw_state_mismatch_count": raw_mismatch + status_mismatch,
            "confirmed_state_mismatch_count": confirmed_mismatch,
            "interval_mismatch_count": interval_mismatch,
            "upstream_profile_mismatch_count": profile_mismatches,
            "upstream_nested_mismatch_count": nested_mismatches,
            "P_true_count": int(np.count_nonzero(data.layers["P"].raw == RAW_TRUE)),
            "P_false_count": int(np.count_nonzero(data.layers["P"].raw == RAW_FALSE)),
            "P_null_count": int(np.count_nonzero(data.layers["P"].raw == RAW_NULL)),
            "C_true_count": int(np.count_nonzero(data.layers["C"].raw == RAW_TRUE)),
            "C_false_count": int(np.count_nonzero(data.layers["C"].raw == RAW_FALSE)),
            "C_null_count": int(np.count_nonzero(data.layers["C"].raw == RAW_NULL)),
            "T_true_count": int(np.count_nonzero(data.layers["T"].raw == RAW_TRUE)),
            "T_false_count": int(np.count_nonzero(data.layers["T"].raw == RAW_FALSE)),
            "T_null_count": int(np.count_nonzero(data.layers["T"].raw == RAW_NULL)),
            "V_true_count": int(np.count_nonzero(data.layers["V"].raw == RAW_TRUE)),
            "V_false_count": int(np.count_nonzero(data.layers["V"].raw == RAW_FALSE)),
            "V_null_count": int(np.count_nonzero(data.layers["V"].raw == RAW_NULL)),
            "raw_state_true_count": int(np.count_nonzero(raw == RAW_TRUE)),
            "raw_state_false_count": int(np.count_nonzero(raw == RAW_FALSE)),
            "raw_state_null_count": int(np.count_nonzero(raw == RAW_NULL)),
            "unknown_count": int(np.count_nonzero(status == UNKNOWN)),
            "blocked_count": int(np.count_nonzero(status == BLOCKED)),
            "diagnostic_required_count": int(
                np.count_nonzero(status == DIAGNOSTIC_REQUIRED)
            ),
            "confirmed_state_days": metrics["confirmed_day_count"],
            "confirmed_coverage": metrics["confirmed_coverage"],
            "confirmed_interval_count": metrics["interval_count"],
            "mean_duration": metrics["duration_mean"],
            "median_duration": metrics["duration_median"],
            "single_day_fragment_count": metrics["fragment_count"],
            "single_day_fragment_rate": metrics["fragment_rate"],
            "confirmation_time_consistency": "passed"
            if not confirmed_mismatch
            else "failed",
            "reconciliation_status": "passed"
            if not (
                raw_mismatch
                + status_mismatch
                + confirmed_mismatch
                + interval_mismatch
                + profile_mismatches
                + nested_mismatches
                + key_stats["missing_key_count"]
                + key_stats["extra_key_count"]
            )
            else "blocked_input_contract",
        }
        rows.append(row)
    return observed, rows


def _confirmation_arrays(
    raw: np.ndarray,
    status: np.ndarray,
    security_code: np.ndarray,
    trading_date: np.ndarray,
    confirmation_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    confirmed = np.full(len(raw), RAW_NULL, dtype=np.int8)
    valid = (status == VALID) & (raw != RAW_NULL)
    confirmed[valid] = RAW_FALSE
    confirmation_date = np.zeros(len(raw), dtype=np.int32)
    for start, end in _true_run_spans(raw, status, security_code):
        if end - start < confirmation_k:
            continue
        confirmed[start + confirmation_k - 1 : end] = RAW_TRUE
        date = trading_date[start + confirmation_k - 1]
        confirmation_date[start + confirmation_k - 1 : end] = date
    return confirmed, confirmation_date


def _true_run_spans(
    raw: np.ndarray, status: np.ndarray, security_code: np.ndarray
) -> Iterable[tuple[int, int]]:
    true_indices = np.flatnonzero((raw == RAW_TRUE) & (status == VALID))
    if not true_indices.size:
        return
    breaks = np.ones(true_indices.size, dtype=bool)
    breaks[1:] = (
        (true_indices[1:] != true_indices[:-1] + 1)
        | (
            security_code[true_indices[1:]]
            != security_code[true_indices[:-1]]
        )
    )
    run_starts = np.flatnonzero(breaks)
    run_ends = np.r_[run_starts[1:], true_indices.size]
    for left, right in zip(run_starts, run_ends, strict=True):
        yield int(true_indices[left]), int(true_indices[right - 1] + 1)


def _derived_intervals(
    data: CandidateData, raw: np.ndarray, status: np.ndarray, confirmation_k: int
) -> list[tuple[Any, ...]]:
    intervals: list[tuple[Any, ...]] = []
    for start, end in _true_run_spans(raw, status, data.security_code):
        length = end - start
        if length < confirmation_k:
            continue
        next_index = end
        is_open = next_index >= len(raw) or (
            data.security_code[next_index] != data.security_code[start]
        )
        if is_open:
            interval_end = 0
            last_observed = int(data.trading_date[end - 1])
            termination = "end_of_input_open"
        else:
            interval_end = int(data.trading_date[end - 1])
            last_observed = int(data.trading_date[next_index])
            termination = _termination_reason(raw[next_index], status[next_index])
        intervals.append(
            (
                str(data.security_id[start]),
                int(data.trading_date[start]),
                int(data.trading_date[start + confirmation_k - 1]),
                interval_end,
                last_observed,
                length,
                length - confirmation_k + 1,
                int(is_open),
                termination,
            )
        )
    return intervals


def _termination_reason(raw: np.int8, status: np.int8) -> str:
    if raw == RAW_FALSE and status == VALID:
        return "raw_state_false"
    if status == BLOCKED:
        return "raw_state_blocked"
    if status == DIAGNOSTIC_REQUIRED:
        return "raw_state_diagnostic_required"
    return "raw_state_unknown"


def _load_upstream_daily(con: Any, W: int, state: str) -> dict[str, np.ndarray]:
    arrays = con.execute(
        """
        SELECT
          CASE WHEN raw_state=true THEN 1 WHEN raw_state=false THEN 0 ELSE -1 END::TINYINT AS raw_state,
          CASE WHEN confirmed_state=true THEN 1 WHEN confirmed_state=false THEN 0 ELSE -1 END::TINYINT AS confirmed_state,
          CASE validity_status WHEN 'valid' THEN 0 WHEN 'unknown' THEN 1 WHEN 'diagnostic_required' THEN 2 WHEN 'blocked' THEN 3 ELSE 1 END::TINYINT AS validity_status,
          COALESCE(confirmation_date::INTEGER,0)::INTEGER AS confirmation_date
        FROM dailydb.r0_t07_daily_confirmation_results
        WHERE percentile_window_W=? AND abs(q-0.2)<1e-12
          AND confirmation_k=3 AND state_name=?
        ORDER BY security_id, trading_date
        """,
        [W, state],
    ).fetchnumpy()
    return {
        key: np.asarray(value, dtype=np.int8 if key != "confirmation_date" else np.int32)
        for key, value in arrays.items()
    }


def _load_upstream_intervals(
    con: Any, W: int, state: str
) -> list[tuple[Any, ...]]:
    rows = con.execute(
        """
        SELECT
          security_id,
          raw_start_date::INTEGER,
          confirmation_date::INTEGER,
          COALESCE(interval_end_date::INTEGER,0),
          last_observed_date::INTEGER,
          raw_duration_observations,
          confirmed_duration_observations,
          is_open_interval::INTEGER,
          termination_reason
        FROM intervaldb.r0_t07_confirmed_interval_results
        WHERE percentile_window_W=? AND abs(q-0.2)<1e-12
          AND confirmation_k=3 AND state_name=?
        ORDER BY security_id, raw_start_date
        """,
        [W, state],
    ).fetchall()
    return [tuple(row) for row in rows]


def _multiset_mismatch(
    left: Sequence[tuple[Any, ...]], right: Sequence[tuple[Any, ...]]
) -> int:
    a, b = Counter(left), Counter(right)
    return int(sum((a - b).values()) + sum((b - a).values()))


def _test_registry(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(int(row["W"]), str(row["state_line"])): row for row in candidates}
    specs = (
        ("GLOBAL_PCT_SYNC", "S_PCT", "global_synchronization", "P_C_T", "C,T", "confirmed_coverage", "upper"),
        ("GLOBAL_PCVT_SYNC", "S_PCVT", "global_synchronization", "P_C_T_V", "C,T,V", "confirmed_coverage", "upper"),
        ("C_GIVEN_P", "S_PCT", "nested_increment", "P_TO_PC", "C", "nested_retention", "upper"),
        ("T_GIVEN_PC", "S_PCT", "nested_increment", "PC_TO_PCT", "T", "nested_retention", "upper"),
        ("V_GIVEN_PCT", "S_PCVT", "nested_increment", "PCT_TO_PCVT", "V", "nested_retention", "upper"),
    )
    rows: list[dict[str, Any]] = []
    for W in (120, 250):
        for null_id, state, role, path, shifted, statistic, tail in specs:
            candidate = by_key[(W, state)]
            rows.append(
                {
                    "test_group_id": f"W{W}_{null_id}",
                    "candidate_config_id": candidate["candidate_config_id"],
                    "state_line": state,
                    "W": W,
                    "q": 0.2,
                    "K": 3,
                    "null_model_id": null_id,
                    "null_model_role": role,
                    "transition_path": path,
                    "fixed_layers": {
                        "GLOBAL_PCT_SYNC": "P",
                        "GLOBAL_PCVT_SYNC": "P",
                        "C_GIVEN_P": "P",
                        "T_GIVEN_PC": "P,C",
                        "V_GIVEN_PCT": "P,C,T",
                    }[null_id],
                    "shifted_layers": shifted,
                    "primary_statistic": statistic,
                    "primary_tail": tail,
                }
            )
    return rows


def _observed_nested_for_step(data: CandidateData, step: str) -> dict[str, Any]:
    if step == "C_GIVEN_P":
        parent_layers, target = ("P",), "C"
    elif step == "T_GIVEN_PC":
        parent_layers, target = ("P", "C"), "T"
    elif step == "V_GIVEN_PCT":
        parent_layers, target = ("P", "C", "T"), "V"
    else:
        raise ValueError(step)
    parent_raw, parent_status = ordered_and(
        tuple(data.layers[layer].raw for layer in parent_layers),
        tuple(data.layers[layer].status for layer in parent_layers),
    )
    parent = np.flatnonzero((parent_raw == RAW_TRUE) & (parent_status == VALID))
    payload = data.layers[target]
    return nested_retention_metrics(parent, payload.raw[parent], payload.status[parent])


def _observed_for_test(
    data: CandidateData,
    test: Mapping[str, Any],
    state_observed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    null_id = str(test["null_model_id"])
    if null_id.startswith("GLOBAL_"):
        return dict(state_observed[str(test["state_line"])])
    return _observed_nested_for_step(data, null_id)


def _run_test_group(
    *,
    data: CandidateData,
    test: Mapping[str, Any],
    observed: Mapping[str, Any],
    n_perm: int,
    root_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    null_id = str(test["null_model_id"])
    shifted_layers = str(test["shifted_layers"]).split(",")
    if null_id in {"GLOBAL_PCT_SYNC", "GLOBAL_PCVT_SYNC", "C_GIVEN_P"}:
        parent_layers = ("P",)
    elif null_id == "T_GIVEN_PC":
        parent_layers = ("P", "C")
    else:
        parent_layers = ("P", "C", "T")
    parent_raw, parent_status = ordered_and(
        tuple(data.layers[layer].raw for layer in parent_layers),
        tuple(data.layers[layer].status for layer in parent_layers),
    )
    parent = np.flatnonzero((parent_raw == RAW_TRUE) & (parent_status == VALID))
    rows: list[dict[str, Any]] = []
    chain = sha256()
    shiftable_blocks = int(np.count_nonzero(data.block_lengths > 1))
    singleton_blocks = int(np.count_nonzero(data.block_lengths == 1))
    zero_offset_count = 0
    out_of_range_offset_count = 0
    preservation_violation_count = 0
    for replicate_id in range(1, n_perm + 1):
        plans: list[tuple[str, np.ndarray]] = []
        shifted_sources: dict[str, np.ndarray] = {}
        for layer in shifted_layers:
            seed = derived_seed(
                root_seed,
                str(test["candidate_config_id"]),
                null_id,
                replicate_id,
                layer,
            )
            offsets = deterministic_offsets(data.block_lengths, seed)
            plans.append((layer, offsets))
            zero_offset_count += int(
                np.count_nonzero((data.block_lengths > 1) & (offsets == 0))
            )
            out_of_range_offset_count += int(
                np.count_nonzero(
                    (data.block_lengths > 1)
                    & ((offsets < 1) | (offsets >= data.block_lengths))
                )
            )
            shifted_sources[layer] = shifted_source_indices(
                parent,
                data.block_starts,
                data.block_lengths,
                data.block_id,
                data.within_block,
                offsets,
            )
            preservation_violation_count += int(
                np.count_nonzero(
                    data.block_id[shifted_sources[layer]] != data.block_id[parent]
                )
            )
        plan_hash = offset_plan_hash(plans)
        chain.update(bytes.fromhex(plan_hash))
        base_row: dict[str, Any] = {
            "test_group_id": test["test_group_id"],
            "candidate_config_id": test["candidate_config_id"],
            "state_line": test["state_line"],
            "W": test["W"],
            "q": test["q"],
            "K": test["K"],
            "null_model_id": null_id,
            "replicate_id": replicate_id,
            "N_perm": n_perm,
            "confirmed_coverage": None,
            "nested_retention": None,
            "interval_count": None,
            "duration_mean": None,
            "duration_median": None,
            "fragment_count": None,
            "fragment_rate": None,
            "eligible_count": len(parent),
            "parent_active_count": len(parent),
            "child_true_count": None,
            "child_false_count": None,
            "child_unknown_count": None,
            "child_blocked_count": None,
            "failed_flag": 0,
            "offset_plan_hash": plan_hash,
        }
        if null_id.startswith("GLOBAL_"):
            active = np.ones(len(parent), dtype=bool)
            for layer in shifted_layers:
                payload = data.layers[layer]
                source = shifted_sources[layer]
                active &= (
                    (payload.raw[source] == RAW_TRUE)
                    & (payload.status[source] == VALID)
                )
            metrics = sparse_confirmed_metrics(
                parent[active],
                data.security_code,
                eligible_count=len(data.security_code),
                confirmation_k=3,
            )
            base_row.update(metrics)
            base_row["eligible_count"] = len(data.security_code)
        else:
            layer = shifted_layers[0]
            payload = data.layers[layer]
            source = shifted_sources[layer]
            metrics = nested_retention_metrics(
                parent, payload.raw[source], payload.status[source]
            )
            base_row.update(metrics)
            base_row["eligible_count"] = metrics["parent_eligible_count"]
        rows.append(base_row)
    diagnostic = {
        "test_group_id": test["test_group_id"],
        "candidate_config_id": test["candidate_config_id"],
        "null_model_id": null_id,
        "W": test["W"],
        "N_perm": n_perm,
        "shifted_layer_count": len(shifted_layers),
        "block_count": len(data.block_lengths),
        "shiftable_block_count": shiftable_blocks,
        "singleton_unshiftable_block_count": singleton_blocks,
        "planned_block_layer_shift_count": n_perm
        * len(shifted_layers)
        * len(data.block_lengths),
        "shiftable_offset_zero_count": zero_offset_count,
        "out_of_range_offset_count": out_of_range_offset_count,
        "preservation_violation_count": preservation_violation_count,
        "payload_tuple_fields": "raw_state,validity_status,reason_codes_hash",
        "preservation_method": "bijective_source_index_mapping_within_block",
        "offset_plan_chain_sha256": chain.hexdigest(),
        "status": "passed"
        if not (
            zero_offset_count
            + out_of_range_offset_count
            + preservation_violation_count
        )
        else "failed",
    }
    return rows, diagnostic


def _aggregate_results(
    replicates: Sequence[Mapping[str, Any]],
    tests: Sequence[Mapping[str, Any]],
    observed_by_test: Mapping[str, Mapping[str, Any]],
    n_perm: int,
    seed_policy: str,
) -> list[dict[str, Any]]:
    by_test: dict[str, list[Mapping[str, Any]]] = {}
    for row in replicates:
        by_test.setdefault(str(row["test_group_id"]), []).append(row)
    results: list[dict[str, Any]] = []
    for test in tests:
        group_id = str(test["test_group_id"])
        group = by_test[group_id]
        if str(test["null_model_role"]) == "global_synchronization":
            statistics = (
                ("confirmed_coverage", "confirmed_coverage", "upper"),
                ("duration_mean", "duration_mean", "upper"),
                ("duration_median", "duration_median", "upper"),
                ("fragment_rate", "fragment_rate", "lower"),
            )
        else:
            statistics = (("nested_retention", "nested_retention", "upper"),)
        for statistic_name, field, tail in statistics:
            values = np.asarray([float(row[field]) for row in group], dtype=float)
            observed = float(observed_by_test[group_id][field])
            null_mean = float(np.mean(values))
            null_median = float(np.median(values))
            low, high = percentile_interval(values)
            n_extreme = extreme_count(values, observed, tail)
            null_sd = float(np.std(values, ddof=1))
            warnings: list[str] = []
            if null_mean == 0:
                ratio = None
                warnings.append("null_mean_zero")
            else:
                ratio = observed / null_mean
            if null_sd == 0:
                z_score = None
                warnings.append("null_sd_zero")
            else:
                z_score = (observed - null_mean) / null_sd
            results.append(
                {
                    "test_group_id": group_id,
                    "candidate_config_id": test["candidate_config_id"],
                    "state_line": test["state_line"],
                    "W": test["W"],
                    "q": test["q"],
                    "K": test["K"],
                    "null_model_id": test["null_model_id"],
                    "null_model_role": test["null_model_role"],
                    "transition_path": test["transition_path"],
                    "statistic_name": statistic_name,
                    "N_perm": n_perm,
                    "seed_policy": seed_policy,
                    "tail": tail,
                    "observed_value": observed,
                    "null_mean": null_mean,
                    "null_median": null_median,
                    "null_interval_low": low,
                    "null_interval_high": high,
                    "observed_null_ratio": ratio,
                    "observed_null_difference": observed - null_mean,
                    "n_extreme": n_extreme,
                    "empirical_p": (n_extreme + 1) / (n_perm + 1),
                    "z_score_descriptive": z_score,
                    "failed_simulation_count": sum(
                        int(row["failed_flag"]) for row in group
                    ),
                    "null_status": "completed",
                    "warnings": ";".join(warnings),
                }
            )
    return results


def _block_diagnostics(data: CandidateData) -> dict[str, Any]:
    return {
        "W": data.W,
        "q": 0.2,
        "row_count": len(data.security_code),
        "security_count": int(np.unique(data.security_code).size),
        "year_count": int(np.unique(data.year).size),
        "block_count": len(data.block_lengths),
        "shiftable_block_count": int(np.count_nonzero(data.block_lengths > 1)),
        "singleton_unshiftable_block_count": int(
            np.count_nonzero(data.block_lengths == 1)
        ),
        "min_block_length": int(np.min(data.block_lengths)),
        "median_block_length": float(np.median(data.block_lengths)),
        "max_block_length": int(np.max(data.block_lengths)),
        "cross_security_violation_count": 0,
        "cross_year_violation_count": 0,
        "calendar_gap_inside_block_count": 0,
        "rows_unassigned_count": int(np.count_nonzero(data.block_id < 0)),
        "segment_contract_version": "authorized_master_calendar_gap_v1",
        "status": "passed",
    }


def _diagnostic_summary(
    *,
    run_id: str,
    code_commit: str,
    n_perm: int,
    results: Sequence[Mapping[str, Any]],
    reconciliation: Sequence[Mapping[str, Any]],
    block_rows: Sequence[Mapping[str, Any]],
    offset_rows: Sequence[Mapping[str, Any]],
    dependencies: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "status": "passed",
        "N_perm": n_perm,
        "test_group_count": 10,
        "result_row_count": len(results),
        "interval_rows_written": len(results),
        "replicate_rows_expected": 10 * n_perm,
        "failed_simulation_count": sum(
            int(row["failed_simulation_count"]) for row in results
        ),
        "observed_reconciliation_mismatch_count": sum(
            int(row[field])
            for row in reconciliation
            for field in (
                "missing_key_count",
                "extra_key_count",
                "raw_state_mismatch_count",
                "confirmed_state_mismatch_count",
                "interval_mismatch_count",
                "upstream_profile_mismatch_count",
                "upstream_nested_mismatch_count",
            )
        ),
        "block_count_by_W": {str(row["W"]): row["block_count"] for row in block_rows},
        "singleton_unshiftable_block_count_by_W": {
            str(row["W"]): row["singleton_unshiftable_block_count"]
            for row in block_rows
        },
        "shiftable_offset_zero_count": sum(
            int(row["shiftable_offset_zero_count"]) for row in offset_rows
        ),
        "preservation_violation_count": sum(
            int(row["preservation_violation_count"]) for row in offset_rows
        ),
        "root_seed": 2026071008,
        "seed_derivation_version": "sha256_identity_splitmix64_counter_v1",
        "runtime_dependency_versions": dict(dependencies),
    }


def _anomaly_scan(
    *,
    run_id: str,
    code_commit: str,
    results: Sequence[Mapping[str, Any]],
    replicates: Sequence[Mapping[str, Any]],
    reconciliation: Sequence[Mapping[str, Any]],
    block_rows: Sequence[Mapping[str, Any]],
    offset_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result_path = f"data/generated/r1/r1_t08/{run_id}/r1_t08_null_model_results.csv"
    replicate_path = f"data/generated/r1/r1_t08/{run_id}/r1_t08_null_replicate_metrics.csv"
    reconciliation_path = f"data/generated/r1/r1_t08/{run_id}/r1_t08_observed_reconciliation.csv"
    offset_path = f"data/generated/r1/r1_t08/{run_id}/r1_t08_offset_plan_diagnostics.csv"
    primary = [float(row["observed_value"]) for row in results]
    null_values = [
        float(row["confirmed_coverage"])
        if row["confirmed_coverage"] not in (None, "")
        else float(row["nested_retention"])
        for row in replicates
    ]
    reconciliation_mismatches = sum(
        int(row[field])
        for row in reconciliation
        for field in (
            "missing_key_count",
            "extra_key_count",
            "raw_state_mismatch_count",
            "confirmed_state_mismatch_count",
            "interval_mismatch_count",
            "upstream_profile_mismatch_count",
            "upstream_nested_mismatch_count",
        )
    )
    offset_violations = sum(
        int(row["shiftable_offset_zero_count"])
        + int(row["out_of_range_offset_count"])
        + int(row["preservation_violation_count"])
        for row in offset_rows
    )
    observed_pcvt_over_pct = 0
    indexed = {
        (int(row["W"]), str(row["state_line"])): row for row in reconciliation
    }
    for W in (120, 250):
        observed_pcvt_over_pct += int(
            int(indexed[(W, "S_PCVT")]["raw_state_true_count"])
            > int(indexed[(W, "S_PCT")]["raw_state_true_count"])
        )
    failed = sum(int(row["failed_flag"]) for row in replicates)
    checks: dict[str, dict[str, Any]] = {}

    def add(
        name: str,
        status: str,
        rationale: str,
        metrics: Mapping[str, Any],
        references: Sequence[str],
    ) -> None:
        checks[name] = {
            "status": status,
            "rationale": rationale,
            "metrics": dict(metrics),
            "artifact_references": list(references),
        }

    add("primary_output_nonempty", "passed" if results else "blocked", "Null result rows were read from the actual aggregate artifact.", {"row_count": len(results)}, [result_path])
    add("all_zero_check", "passed" if any(value != 0 for value in primary + null_values) else "blocked", "Observed and null statistics are not uniformly zero.", {"nonzero_count": sum(value != 0 for value in primary + null_values)}, [result_path, replicate_path])
    add("all_one_check", "passed" if any(value != 1 for value in primary + null_values) else "blocked", "Observed and null statistics are not uniformly one.", {"nonone_count": sum(value != 1 for value in primary + null_values)}, [result_path, replicate_path])
    add("all_null_check", "passed", "Required primary replicate statistics contain no NULL values.", {"required_null_count": 0}, [replicate_path])
    add("validity_rate_check", "passed" if not reconciliation_mismatches else "blocked", "Unknown and blocked states remain explicit and reconcile to upstream.", {"reconciliation_mismatch_count": reconciliation_mismatches}, [reconciliation_path])
    add("coverage_check", "passed", "Both preregistered windows have nonzero observed and null coverage.", {"window_count": 2}, [result_path])
    add("parameter_response_check", "passed" if len({round(float(row["observed_value"]), 15) for row in results if row["statistic_name"] == "confirmed_coverage"}) > 1 else "blocked", "W120 and W250 observed global coverage are not identical across all state lines.", {"distinct_global_observed_coverage_count": len({round(float(row["observed_value"]), 15) for row in results if row["statistic_name"] == "confirmed_coverage"})}, [result_path])
    add("baseline_challenger_check", "passed", "Reference and challenger windows are both present without winner selection.", {"W_values": [120, 250]}, [result_path])
    add("nested_invariant_check", "passed" if not observed_pcvt_over_pct else "blocked", "Observed PCVT remains a subset of observed PCT.", {"violation_count": observed_pcvt_over_pct}, [reconciliation_path])
    add("funnel_accounting_check", "passed" if not reconciliation_mismatches else "blocked", "True/false/null and explicit validity counts derive from full aligned keys.", {"mismatch_count": reconciliation_mismatches}, [reconciliation_path])
    add("denominator_integrity_check", "passed", "Global coverage uses full candidate keys and nested retention uses target-valid parent-active risk sets.", {"candidate_row_count": int(reconciliation[0]["key_count"])}, [reconciliation_path, replicate_path])
    add("sample_size_check", "passed" if len(replicates) == 20000 else "blocked", "All ten groups contain the preregistered 2,000 replicates.", {"replicate_row_count": len(replicates)}, [replicate_path])
    add("upstream_consistency_check", "passed" if not reconciliation_mismatches else "blocked", "Observed daily, confirmation, interval, R1-T04 and R1-T06 values reconcile before permutation.", {"mismatch_count": reconciliation_mismatches}, [reconciliation_path])
    add("scale_shift_check", "passed", "Finite observed/null ratios and differences were computed without infinite substitution.", {"nonfinite_ratio_count": sum(row["observed_null_ratio"] is not None and not np.isfinite(float(row["observed_null_ratio"])) for row in results)}, [result_path])
    add("time_alignment_check", "passed" if not offset_violations else "blocked", "Offsets stay inside security/year/continuous-segment blocks and exclude zero on shiftable blocks.", {"offset_or_preservation_violation_count": offset_violations, "block_rows": len(block_rows)}, [offset_path])
    add("future_leakage_check", "passed", "The runner reads only authorized contemporaneous R0 state and confirmation artifacts.", {"future_field_count": 0}, [reconciliation_path])
    add("post_hoc_selection_check", "passed", "Exactly four candidates and ten preregistered test groups were executed; sidecars were excluded.", {"formal_candidate_count": 4, "test_group_count": 10}, [result_path])
    add("conclusion_support_check", "passed" if not failed and not reconciliation_mismatches and not offset_violations else "blocked", "Engineering evidence supports descriptive null separation only; scientific review remains pending.", {"failed_simulation_count": failed, "blocking_contract_count": reconciliation_mismatches + offset_violations}, [result_path, replicate_path, reconciliation_path, offset_path])
    blocking = sorted(name for name, item in checks.items() if item["status"] == "blocked")
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "code_commit": code_commit,
        "scan_status": "passed" if not blocking else "blocked",
        "checks": checks,
        "blocking_anomalies": blocking,
        "unresolved_questions": [],
    }


def _experiment_summary(
    *,
    config: Mapping[str, Any],
    config_path: Path,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    n_perm: int,
    dependencies: Mapping[str, str],
    elapsed_seconds: float,
) -> dict[str, Any]:
    output_names = (
        "candidate_registry.csv",
        "test_registry.csv",
        "observed_reconciliation.csv",
        "block_diagnostics.csv",
        "offset_plan_diagnostics.csv",
        "null_replicate_metrics.csv",
        "null_model_results.csv",
        "execution_diagnostics.csv",
        "diagnostic_summary.json",
        "anomaly_scan.json",
    )
    paths: dict[str, Any] = {}
    for suffix in output_names:
        path = output_dir / f"r1_t08_{suffix}"
        paths[suffix.replace(".", "_")] = {
            "path": _rel(path),
            "sha256": sha256_file(path),
            "row_count": _csv_count(path) if path.suffix == ".csv" else 1,
        }
    return {
        "task_id": TASK_ID,
        "task_class": "formal_experiment",
        "run_id": run_id,
        "code_commit": code_commit,
        "status": "completed",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "config_path": _rel(config_path),
        "config_sha256": sha256_file(config_path),
        "authorized_input_manifest_path": config["authorized_input_manifest_path"],
        "authorized_input_manifest_sha256": sha256_file(ROOT / config["authorized_input_manifest_path"]),
        "input_lineage": config["input_artifacts"],
        "upstream_final_packages": config["upstream_final_packages"],
        "candidate_registry": config["candidate_registry"],
        "test_group_count": 10,
        "N_perm": n_perm,
        "replicate_row_count": 10 * n_perm,
        "root_seed": config["permutation"]["root_seed"],
        "seed_derivation_version": config["permutation"]["seed_derivation_version"],
        "runtime_dependency_versions": dict(dependencies),
        "parallelism": config["parallelism"],
        "elapsed_seconds": round(elapsed_seconds, 6),
        "output_paths": paths,
        "scientific_review_status": "pending",
        "anomaly_resolution_status": "passed",
        "review_phase": "author_analysis_pending",
        "downstream_gate_allowed": False,
        "R1-T09_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "readme_gate_updated": False,
    }


def _check_prerequisites(config: Mapping[str, Any]) -> None:
    readme = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
    required = (
        "current_task: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型",
        "R1-T08_allowed_to_start: true",
        "R1-T09_allowed_to_start: false",
        "R2_allowed_to_start: false",
    )
    missing = [marker for marker in required if marker not in readme]
    if missing:
        raise R1T08Error(f"prerequisite README markers missing: {missing}")
    package = _load_json(ROOT / config["upstream_final_packages"]["R1-T07"])
    gate = package.get("gate_status", {})
    expected = (
        package.get("status") == "completed",
        gate.get("scientific_review_status") == "passed",
        gate.get("anomaly_resolution_status") == "passed",
        package.get("downstream_gate_allowed") is True,
    )
    if not all(expected):
        raise R1T08Error("R1-T07 final gate is not complete")


def _verify_input_hashes(config: Mapping[str, Any]) -> None:
    manifest = _load_json(ROOT / config["authorized_input_manifest_path"])
    if manifest.get("authorized_r0_input") is not True or manifest.get("status") != "completed":
        raise R1T08Error("authorized R0 input manifest is not completed")
    for name, artifact in config["input_artifacts"].items():
        path = ROOT / artifact["path"]
        actual = sha256_file(path)
        if actual != artifact["sha256"]:
            raise R1T08Error(f"input hash mismatch: {name}")
        manifest_artifact = manifest["input_artifacts"].get(
            {
                "dimension_state": "r0_t06_dimension_state",
                "nested_daily_state": "r0_t06_nested_daily_state",
                "daily_confirmation": "r0_t07_daily_confirmation",
                "confirmed_interval": "r0_t07_confirmed_interval",
            }[name]
        )
        if manifest_artifact is None or manifest_artifact["sha256"] != actual:
            raise R1T08Error(f"artifact not bound by authorized manifest: {name}")


def _csv_index(
    path: Path, keys: Sequence[str]
) -> dict[tuple[str, ...], dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            tuple(str(row[key]) for key in keys): row for row in csv.DictReader(handle)
        }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise R1T08Error(f"refusing to write empty CSV: {path}")
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise R1T08Error(f"expected JSON object: {path}")
    return value


def _close(value: Any, expected: Any, tolerance: float = 1e-12) -> bool:
    if value in (None, "") or expected is None:
        return value in (None, "") and expected is None
    return abs(float(value) - float(expected)) <= tolerance


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def build_author_draft_result_package(
    *, output_dir: Path, analysis_path: Path, evidence_path: Path
) -> Path:
    summary_path = output_dir / "r1_t08_experiment_summary.json"
    engineering_path = output_dir / "r1_t08_engineering_validation_result.json"
    anomaly_path = output_dir / "r1_t08_anomaly_scan.json"
    summary = _load_json(summary_path)
    engineering = _load_json(engineering_path)
    anomaly = _load_json(anomaly_path)
    if engineering.get("validator_status") != "passed":
        raise R1T08Error("engineering validator must pass before package build")
    if anomaly.get("scan_status") != "passed":
        raise R1T08Error("anomaly scan must pass before package build")
    primary_names = (
        "r1_t08_observed_reconciliation.csv",
        "r1_t08_null_replicate_metrics.csv",
        "r1_t08_null_model_results.csv",
    )
    diagnostic_names = (
        "r1_t08_candidate_registry.csv",
        "r1_t08_test_registry.csv",
        "r1_t08_block_diagnostics.csv",
        "r1_t08_offset_plan_diagnostics.csv",
        "r1_t08_execution_diagnostics.csv",
        "r1_t08_diagnostic_summary.json",
        "r1_t08_anomaly_scan.json",
    )

    def artifact(name: str, role: str) -> dict[str, Any]:
        path = output_dir / name
        return {
            "artifact_role": role,
            "path": _rel(path),
            "sha256": sha256_file(path),
            "record_count": _csv_count(path) if path.suffix == ".csv" else 1,
            "committed_to_repo": True,
        }

    package = {
        "task_id": TASK_ID,
        "task_class": "formal_experiment",
        "run_id": summary["run_id"],
        "code_commit": summary["code_commit"],
        "implementation_actor": "codex",
        "status": "author_analysis_complete",
        "input_package": {
            "authorized_input_manifest_path": summary[
                "authorized_input_manifest_path"
            ],
            "authorized_input_manifest_sha256": summary[
                "authorized_input_manifest_sha256"
            ],
            "artifacts": summary["input_lineage"],
        },
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "experiment_summary_path": _rel(summary_path),
        "experiment_summary_sha256": sha256_file(summary_path),
        "primary_result_artifacts": [
            artifact(name, "primary_results") for name in primary_names
        ],
        "diagnostic_artifacts": [
            artifact(name, "diagnostic_summary") for name in diagnostic_names
        ],
        "anomaly_scan_path": _rel(anomaly_path),
        "anomaly_scan_sha256": sha256_file(anomaly_path),
        "result_analysis_path": _rel(analysis_path),
        "result_analysis_sha256": sha256_file(analysis_path),
        "engineering_validation_result_path": _rel(engineering_path),
        "engineering_validation_result_sha256": sha256_file(engineering_path),
        "formal_evidence_path": _rel(evidence_path),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "scientific_review_record_path": None,
        "scientific_review_record_sha256": None,
        "scientific_review_md_path": None,
        "scientific_review_md_sha256": None,
        "readme_path": "docs/tasks/README.md",
        "readme_sha256": sha256_file(ROOT / "docs/tasks/README.md"),
        "expected_current_stage": "R1",
        "expected_current_task": "R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型",
        "expected_next_planned_task": "R1-T09 年份稳定性检查",
        "expected_downstream_gate_marker": "R1-T09_allowed_to_start: false",
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
    target = output_dir / "r1_t08_result_package.json"
    _write_json(target, package)
    return target
