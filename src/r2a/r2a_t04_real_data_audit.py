"""Execution primitives for the R2A-T04 real-data response audit."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import psutil
import pyarrow as pa
from jsonschema import Draft202012Validator, FormatChecker

from src.r2a.r2a_t03_dynamic_evaluator import (
    evaluate_dynamic_request_connections,
)
from src.r2a.r2a_t03_output_contract import (
    TABLE_CONTRACTS,
    DynamicEvaluationSummary,
    validate_dynamic_evaluation_output,
)
from src.r2a.r2a_t04_charting import (
    deterministic_chart_sample,
    render_diagnostic_chart,
    write_visual_review_worksheet,
)
from src.r2a.r2a_t04_request_panel import (
    stable_smoke_security_ids,
)

ROOT = Path(__file__).resolve().parents[2]
MARKET_SCHEMA = ROOT / "schemas/r2a/r2a_t04_local_source_manifest.schema.json"
STANDARD_MARKET_COLUMNS = (
    "security_id",
    "trading_date",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "volume_shares",
    "amount_yuan",
    "turnover_float",
    "tradable_flag",
    "is_suspended",
    "price_limit_status",
)


class R2AT04AuditError(ValueError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")
        self.reason_code = reason_code


def sha256_file(path: str | Path, *, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file_identity(
    path: str | Path, *, expected_sha256: str, expected_byte_size: int
) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_file():
        raise R2AT04AuditError("bound_file_missing", resolved.name)
    size = resolved.stat().st_size
    if size != expected_byte_size:
        raise R2AT04AuditError("bound_file_size_mismatch", f"{resolved.name}:{size}")
    digest = sha256_file(resolved)
    if digest != expected_sha256:
        raise R2AT04AuditError("bound_file_sha256_mismatch", resolved.name)
    return {"filename": resolved.name, "sha256": digest, "byte_size": size}


def load_market_source_spec(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    schema = json.loads(MARKET_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return dict(value)


class _PeakRSSSampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self.peak = 0
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        process = psutil.Process()
        while not self._stop.wait(0.02):
            try:
                total = process.memory_info().rss
                total += sum(
                    child.memory_info().rss
                    for child in process.children(recursive=True)
                )
                self.peak = max(self.peak, total)
            except (psutil.Error, OSError):
                continue

    def __enter__(self) -> _PeakRSSSampler:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            self.peak = max(self.peak, psutil.Process().memory_info().rss)
        except psutil.Error:
            pass


def evaluate_request_with_threads(
    *,
    score_database: Path,
    canonical_request: Mapping[str, Any],
    output_database: Path,
    duckdb_thread_count: int,
    security_ids: Sequence[str] | None,
) -> tuple[DynamicEvaluationSummary, float, int, int]:
    """Run the accepted evaluator once with fixed internal DuckDB threads."""

    if duckdb_thread_count not in (4, 8, 16):
        raise R2AT04AuditError("duckdb_thread_count_not_frozen")
    source_path = Path(score_database)
    target = Path(output_database)
    if not source_path.is_file() or not target.parent.is_dir() or target.exists():
        raise R2AT04AuditError("evaluation_path_gate_failed")
    descriptor, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp.duckdb"
    )
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    started = time.perf_counter()
    summary: DynamicEvaluationSummary | None = None
    with _PeakRSSSampler() as rss:
        try:
            with (
                duckdb.connect(str(source_path), read_only=True) as source,
                duckdb.connect(str(temporary)) as output,
            ):
                source.execute(f"SET threads={duckdb_thread_count}")
                output.execute(f"SET threads={duckdb_thread_count}")
                summary = evaluate_dynamic_request_connections(
                    source=source,
                    output=output,
                    canonical_request=canonical_request,
                    security_ids=security_ids,
                )
                validate_dynamic_evaluation_output(output)
                output.execute("CHECKPOINT")
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise R2AT04AuditError("output_already_exists") from error
        finally:
            temporary.unlink(missing_ok=True)
    if summary is None:
        raise R2AT04AuditError("evaluation_summary_missing")
    return summary, time.perf_counter() - started, rss.peak, target.stat().st_size


def _canonical_batch_bytes(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


def canonical_table_profiles(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for table_name, contract in TABLE_CONTRACTS.items():
        order = ", ".join(f'"{column}"' for column in contract.primary_key)
        reader = connection.execute(
            f'SELECT * FROM "{table_name}" ORDER BY {order}'
        ).fetch_record_batch(65_536)
        digest = hashlib.sha256()
        row_count = 0
        for batch in reader:
            digest.update(_canonical_batch_bytes(batch))
            row_count += batch.num_rows
        profiles[table_name] = {
            "row_count": row_count,
            "canonical_fingerprint": digest.hexdigest(),
        }
    return profiles


@dataclass(frozen=True)
class ThreadBenchmarkRun:
    duckdb_thread_count: int
    wall_seconds: float
    peak_rss_bytes: int
    temporary_output_bytes: int
    validator_status: str
    output_tables: dict[str, dict[str, Any]]


def choose_duckdb_threads(runs: Sequence[ThreadBenchmarkRun]) -> int:
    if {run.duckdb_thread_count for run in runs} != {4, 8, 16}:
        raise R2AT04AuditError("thread_candidate_set_mismatch")
    if any(run.validator_status != "passed" for run in runs):
        raise R2AT04AuditError("thread_validator_failed")
    fingerprints = {
        json.dumps(run.output_tables, sort_keys=True, separators=(",", ":"))
        for run in runs
    }
    if len(fingerprints) != 1:
        raise R2AT04AuditError("thread_fingerprint_mismatch")
    fastest = min(runs, key=lambda run: (run.wall_seconds, run.duckdb_thread_count))
    eligible_lower = [
        run
        for run in runs
        if run.duckdb_thread_count < fastest.duckdb_thread_count
        and (run.wall_seconds - fastest.wall_seconds) / fastest.wall_seconds < 0.10
    ]
    if eligible_lower:
        return min(run.duckdb_thread_count for run in eligible_lower)
    return fastest.duckdb_thread_count


def run_thread_benchmark(
    *,
    score_database: Path,
    score_release_id: str,
    canonical_request: Mapping[str, Any],
    scratch_directory: Path,
) -> dict[str, Any]:
    """Benchmark 4/8/16 threads on the frozen four-security full-history scope."""

    scratch_directory.mkdir(parents=True, exist_ok=False)
    before_size = score_database.stat().st_size
    before_hash = sha256_file(score_database)
    try:
        with duckdb.connect(str(score_database), read_only=True) as source:
            securities = [
                str(row[0])
                for row in source.execute(
                    "SELECT security_id FROM securities ORDER BY security_id"
                ).fetchall()
            ]
        selected = stable_smoke_security_ids(score_release_id, securities)
        runs: list[ThreadBenchmarkRun] = []
        for threads in (4, 8, 16):
            output = scratch_directory / f"threads-{threads}.duckdb"
            _, elapsed, peak_rss, output_bytes = evaluate_request_with_threads(
                score_database=score_database,
                canonical_request=canonical_request,
                output_database=output,
                duckdb_thread_count=threads,
                security_ids=selected,
            )
            with duckdb.connect(str(output), read_only=True) as connection:
                validate_dynamic_evaluation_output(connection)
                profiles = canonical_table_profiles(connection)
            runs.append(
                ThreadBenchmarkRun(
                    duckdb_thread_count=threads,
                    wall_seconds=elapsed,
                    peak_rss_bytes=peak_rss,
                    temporary_output_bytes=output_bytes,
                    validator_status="passed",
                    output_tables=profiles,
                )
            )
            output.unlink()
        selected_threads = choose_duckdb_threads(runs)
        fingerprint_preimage = {
            "candidate_threads": [4, 8, 16],
            "request_id": canonical_request["request_id"],
            "security_ids": list(selected),
            "output_tables": runs[0].output_tables,
        }
        benchmark_fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_preimage,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if (
            score_database.stat().st_size != before_size
            or sha256_file(score_database) != before_hash
        ):
            raise R2AT04AuditError("score_source_mutated_during_benchmark")
        return {
            "status": "passed",
            "request_id": canonical_request["request_id"],
            "security_ids": list(selected),
            "selected_duckdb_thread_count": selected_threads,
            "thread_benchmark_fingerprint": benchmark_fingerprint,
            "runs": [asdict(run) for run in runs],
            "formal_run_attempt_consumed": False,
        }
    finally:
        if scratch_directory.exists():
            shutil.rmtree(scratch_directory)


def validate_market_source(
    *,
    score_database: Path,
    market_database: Path,
    source_spec: Mapping[str, Any],
    scratch_directory: Path,
) -> dict[str, Any]:
    """Validate identity, standardized schema, values and full present-key coverage."""

    identity = verify_file_identity(
        market_database,
        expected_sha256=str(source_spec["database_sha256"]),
        expected_byte_size=int(source_spec["database_byte_size"]),
    )
    if market_database.name != source_spec["database_basename"]:
        raise R2AT04AuditError("market_database_basename_mismatch")
    query = str(source_spec["source_query"]).strip().rstrip(";")
    scratch_directory.mkdir(parents=True, exist_ok=False)
    key_parquet = scratch_directory / "market-present-keys.parquet"
    try:
        with duckdb.connect(str(market_database), read_only=True) as market:
            columns = [
                row[0] for row in market.execute(f"DESCRIBE ({query})").fetchall()
            ]
            if tuple(columns) != STANDARD_MARKET_COLUMNS:
                raise R2AT04AuditError("market_standard_column_mismatch")
            duplicate_count = market.execute(
                f"SELECT count(*) FROM (SELECT security_id,trading_date,count(*) n "
                f"FROM ({query}) GROUP BY 1,2 HAVING n<>1)"
            ).fetchone()[0]
            if duplicate_count:
                raise R2AT04AuditError("market_duplicate_key")
            invalid_count = market.execute(
                f"SELECT count(*) FROM ({query}) m WHERE "
                "security_id IS NULL OR trading_date IS NULL OR "
                "NOT isfinite(raw_open) OR raw_open<=0 OR NOT isfinite(raw_high) OR raw_high<=0 OR "
                "NOT isfinite(raw_low) OR raw_low<=0 OR NOT isfinite(raw_close) OR raw_close<=0 OR "
                "NOT isfinite(adj_open) OR adj_open<=0 OR NOT isfinite(adj_high) OR adj_high<=0 OR "
                "NOT isfinite(adj_low) OR adj_low<=0 OR NOT isfinite(adj_close) OR adj_close<=0 OR "
                "raw_high<greatest(raw_open,raw_close) OR raw_low>least(raw_open,raw_close) OR "
                "adj_high<greatest(adj_open,adj_close) OR adj_low>least(adj_open,adj_close) OR "
                "volume_shares<0 OR amount_yuan<0 OR "
                "(turnover_float IS NOT NULL AND turnover_float<0)"
            ).fetchone()[0]
            if invalid_count:
                raise R2AT04AuditError(
                    "market_value_integrity_failed", str(invalid_count)
                )
            market.execute(
                f"COPY (SELECT security_id,trading_date FROM ({query}) ORDER BY 1,2) "
                f"TO '{key_parquet.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            market_profile = market.execute(
                f"SELECT count(*),count(DISTINCT security_id),min(trading_date),max(trading_date) FROM ({query})"
            ).fetchone()
        with duckdb.connect(str(score_database), read_only=True) as score:
            missing = score.execute(
                "SELECT count(*) FROM security_observation_spine s ANTI JOIN "
                "read_parquet(?) m USING (security_id,trading_date) "
                "WHERE s.expected_observation_status='present'",
                [str(key_parquet)],
            ).fetchone()[0]
            if missing:
                raise R2AT04AuditError(
                    "market_present_key_coverage_missing", str(missing)
                )
        return {
            **identity,
            "source_id": source_spec["source_id"],
            "row_count": int(market_profile[0]),
            "security_count": int(market_profile[1]),
            "date_min": str(market_profile[2]),
            "date_max": str(market_profile[3]),
            "present_key_missing_count": 0,
            "validator_status": "passed",
        }
    finally:
        if scratch_directory.exists():
            shutil.rmtree(scratch_directory)


def request_metrics(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    joint = connection.execute(
        "SELECT count(*) spine, count(*) FILTER (WHERE expected_observation_status='present') present, "
        "count(*) FILTER (WHERE joint_ready) ready, "
        "count(*) FILTER (WHERE raw_state=true) raw_true, "
        "count(*) FILTER (WHERE raw_state=false) raw_false, "
        "count(*) FILTER (WHERE raw_state IS NULL) raw_null, "
        "coalesce(max(raw_streak),0) max_streak, "
        "count(*) FILTER (WHERE confirmed_state=true) confirmed_true, "
        "count(*) FILTER (WHERE confirmation_event) confirmation_events "
        "FROM daily_joint_states"
    ).fetchone()
    intervals = connection.execute(
        "SELECT count(*),count(DISTINCT security_id),"
        "count(*) FILTER (WHERE right_censored),"
        "min(confirmed_observation_count),quantile_cont(confirmed_observation_count,0.10),"
        "quantile_cont(confirmed_observation_count,0.25),median(confirmed_observation_count),"
        "quantile_cont(confirmed_observation_count,0.75),quantile_cont(confirmed_observation_count,0.90),"
        "quantile_cont(confirmed_observation_count,0.99),max(confirmed_observation_count) "
        "FROM confirmed_intervals"
    ).fetchone()
    security_count = connection.execute(
        "SELECT evaluated_security_count FROM evaluation_scope"
    ).fetchone()[0]
    security_streak = connection.execute(
        "SELECT quantile_cont(max_streak,0.50),quantile_cont(max_streak,0.90),"
        "quantile_cont(max_streak,0.99) FROM (SELECT security_id,coalesce(max(raw_streak),0) max_streak "
        "FROM daily_joint_states GROUP BY security_id)"
    ).fetchone()
    evaluability = connection.execute(
        "SELECT count(*) FILTER(WHERE all_valid),"
        "count(*) FILTER(WHERE all_eligible),count(*) FILTER(WHERE all_finite) "
        "FROM (SELECT security_id,trading_date,"
        "bool_and(validity_status='valid') all_valid,"
        "bool_and(eligible_dimension) all_eligible,"
        "bool_and(coalesce(isfinite(score_dimension),false) AND "
        "coalesce(isfinite(score_dimension_min),false)) "
        "all_finite FROM daily_dimension_states GROUP BY 1,2)"
    ).fetchone()
    reason_codes = (
        "expected_observation_missing",
        "expected_observation_listing_pause",
        "selected_dimension_blocked",
        "selected_dimension_diagnostic_required",
        "selected_dimension_unknown",
        "selected_dimension_not_eligible",
        "selected_dimension_score_non_finite",
    )
    reason_counts = {
        reason: int(
            connection.execute(
                "SELECT count(*) FROM daily_joint_states "
                "WHERE list_contains(joint_reason_codes,?)",
                [reason],
            ).fetchone()[0]
        )
        for reason in reason_codes
    }
    (
        spine,
        present,
        ready,
        raw_true,
        raw_false,
        raw_null,
        max_streak,
        confirmed,
        events,
    ) = map(int, joint)
    interval_count, breadth, right_censored = map(int, intervals[:3])

    def rate(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    quantile_names = ("min", "p10", "p25", "median", "p75", "p90", "p99", "max")
    return {
        "spine_observation_count": spine,
        "present_observation_count": present,
        "joint_ready_count": ready,
        "joint_ready_rate_all": rate(ready, spine),
        "joint_ready_rate_present": rate(ready, present),
        "raw_true_count": raw_true,
        "raw_false_count": raw_false,
        "raw_null_count": raw_null,
        "raw_true_rate_all": rate(raw_true, spine),
        "raw_true_rate_present": rate(raw_true, present),
        "max_raw_streak": max_streak,
        "security_max_streak_p50": security_streak[0],
        "security_max_streak_p90": security_streak[1],
        "security_max_streak_p99": security_streak[2],
        "confirmed_true_count": confirmed,
        "confirmed_true_rate_all": rate(confirmed, spine),
        "confirmation_event_count": events,
        "confirmed_interval_count": interval_count,
        "security_with_interval_count": breadth,
        "security_breadth_rate": rate(breadth, int(security_count)),
        "zero_interval_security_count": int(security_count) - breadth,
        "right_censored_interval_count": right_censored,
        "right_censored_rate": rate(right_censored, interval_count),
        "selected_dimensions_all_valid_count": int(evaluability[0]),
        "selected_dimensions_all_eligible_count": int(evaluability[1]),
        "selected_dimensions_all_finite_count": int(evaluability[2]),
        "joint_non_ready_reason_counts": reason_counts,
        "duration_quantiles": dict(zip(quantile_names, intervals[3:], strict=True)),
    }


def termination_metrics(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    total = int(
        connection.execute("SELECT count(*) FROM confirmed_intervals").fetchone()[0]
    )
    return [
        {
            "termination_reason": row[0],
            "count": int(row[1]),
            "rate": row[1] / total if total else None,
        }
        for row in connection.execute(
            "SELECT termination_reason,count(*) FROM confirmed_intervals GROUP BY 1 ORDER BY 1"
        ).fetchall()
    ]


def year_metrics(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    daily = connection.execute(
        "SELECT year(trading_date) AS metric_year,count(*) FILTER "
        "(WHERE expected_observation_status='present') present,"
        "avg(joint_ready::INT) joint_ready_rate,avg((raw_state=true)::INT) FILTER (WHERE raw_state IS NOT NULL) raw_true_rate,"
        "avg((confirmed_state=true)::INT) FILTER (WHERE confirmed_state IS NOT NULL) confirmed_true_rate,"
        "count(*) FILTER (WHERE confirmation_event) confirmation_events "
        "FROM daily_joint_states GROUP BY 1 ORDER BY 1"
    ).fetchall()
    intervals = {
        int(row[0]): row[1:]
        for row in connection.execute(
            "SELECT year(confirmation_date),count(*),count(DISTINCT security_id),"
            "median(confirmed_observation_count),avg(right_censored::INT) "
            "FROM confirmed_intervals GROUP BY 1 ORDER BY 1"
        ).fetchall()
    }
    termination_by_year: dict[int, dict[str, int]] = defaultdict(dict)
    for metric_year, reason, count in connection.execute(
        "SELECT year(confirmation_date),termination_reason,count(*) "
        "FROM confirmed_intervals GROUP BY 1,2 ORDER BY 1,2"
    ).fetchall():
        termination_by_year[int(metric_year)][str(reason)] = int(count)
    return [
        {
            "year": int(row[0]),
            "coverage_status": "partial_through_2026-06-30"
            if int(row[0]) == 2026
            else "full_year",
            "present_observations": int(row[1]),
            "joint_ready_rate": row[2],
            "raw_true_rate": row[3],
            "confirmed_true_rate": row[4],
            "confirmation_events": int(row[5]),
            "interval_count": int(intervals.get(int(row[0]), (0, 0, None, None))[0]),
            "security_breadth": int(intervals.get(int(row[0]), (0, 0, None, None))[1]),
            "duration_median": intervals.get(int(row[0]), (0, 0, None, None))[2],
            "right_censored_rate": intervals.get(int(row[0]), (0, 0, None, None))[3],
            "termination_distribution": termination_by_year.get(int(row[0]), {}),
        }
        for row in daily
    ]


def free_disk_gate(path: Path, score_database_byte_size: int, multiple: int = 3) -> int:
    free = shutil.disk_usage(path).free
    if free < multiple * score_database_byte_size:
        raise R2AT04AuditError("free_disk_gate_failed", str(free))
    return free


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _load_market_into_audit(
    audit: duckdb.DuckDBPyConnection,
    *,
    market_database: Path,
    source_query: str,
    security_ids: Sequence[str] | None = None,
) -> None:
    query = source_query.strip().rstrip(";")
    parameters: list[object] = []
    if security_ids is not None:
        placeholders = ",".join("?" for _ in security_ids)
        query = f"SELECT * FROM ({query}) WHERE security_id IN ({placeholders})"
        parameters.extend(security_ids)
    with duckdb.connect(str(market_database), read_only=True) as market:
        reader = market.execute(query, parameters).fetch_record_batch(65_536)
        first = True
        for batch in reader:
            audit.register("_market_batch", batch)
            if first:
                audit.execute(
                    "CREATE TABLE market_observations AS SELECT * FROM _market_batch"
                )
                first = False
            else:
                audit.execute(
                    "INSERT INTO market_observations SELECT * FROM _market_batch"
                )
            audit.unregister("_market_batch")
    if first:
        raise R2AT04AuditError("market_source_empty")
    audit.execute(
        "CREATE TEMP TABLE _market_with_prev AS SELECT *,"
        "row_number() OVER (PARTITION BY security_id ORDER BY trading_date)-1 "
        "observation_sequence,lag(adj_close) OVER (PARTITION BY security_id "
        "ORDER BY trading_date) prev_adj_close FROM market_observations"
    )
    audit.execute(
        "CREATE TABLE market_features AS SELECT *,"
        "avg(adj_close) OVER w5 ma5,avg(adj_close) OVER w10 ma10,"
        "avg(adj_close) OVER w20 ma20,avg(adj_close) OVER w30 ma30,"
        "avg(adj_close) OVER w60 ma60,"
        "avg(volume_shares) OVER w20 volume_ma20,"
        "avg(volume_shares) OVER w60 volume_ma60,"
        "avg(amount_yuan) OVER w20 amount_ma20,"
        "avg(amount_yuan) OVER w60 amount_ma60,"
        "avg(turnover_float) OVER w20 turnover_ma20,"
        "avg(turnover_float) OVER w60 turnover_ma60,"
        "avg(greatest(adj_high-adj_low,abs(adj_high-prev_adj_close),"
        "abs(adj_low-prev_adj_close))) OVER w14 atr14,"
        "ln(max(adj_high) OVER w20/min(adj_low) OVER w20) range20 "
        "FROM _market_with_prev "
        "WINDOW w5 AS (PARTITION BY security_id ORDER BY trading_date "
        "ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),"
        "w10 AS (PARTITION BY security_id ORDER BY trading_date "
        "ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),"
        "w14 AS (PARTITION BY security_id ORDER BY trading_date "
        "ROWS BETWEEN 13 PRECEDING AND CURRENT ROW),"
        "w20 AS (PARTITION BY security_id ORDER BY trading_date "
        "ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),"
        "w30 AS (PARTITION BY security_id ORDER BY trading_date "
        "ROWS BETWEEN 29 PRECEDING AND CURRENT ROW),"
        "w60 AS (PARTITION BY security_id ORDER BY trading_date "
        "ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)"
    )
    audit.execute("DROP TABLE market_observations")
    audit.execute("DROP TABLE _market_with_prev")
    audit.execute(
        "CREATE UNIQUE INDEX market_features_key "
        "ON market_features(security_id,trading_date)"
    )


def initialize_audit_database(
    audit: duckdb.DuckDBPyConnection,
    *,
    market_database: Path,
    source_query: str,
    security_ids: Sequence[str] | None = None,
) -> None:
    _load_market_into_audit(
        audit,
        market_database=market_database,
        source_query=source_query,
        security_ids=security_ids,
    )
    audit.execute(
        "CREATE TABLE request_metrics_records("
        "logical_request_name VARCHAR PRIMARY KEY,request_id VARCHAR,"
        "request_hash VARCHAR,validator_status VARCHAR,metrics_json VARCHAR,"
        "output_tables_json VARCHAR,wall_seconds DOUBLE,peak_rss_bytes BIGINT,"
        "temporary_output_bytes BIGINT)"
    )
    audit.execute(
        "CREATE TABLE year_metrics_records(logical_request_name VARCHAR,"
        "year INTEGER,metrics_json VARCHAR,PRIMARY KEY(logical_request_name,year))"
    )
    audit.execute(
        "CREATE TABLE termination_metrics_records(logical_request_name VARCHAR,"
        "termination_reason VARCHAR,count BIGINT,rate DOUBLE,"
        "PRIMARY KEY(logical_request_name,termination_reason))"
    )
    audit.execute(
        "CREATE TABLE response_daily(logical_request_name VARCHAR,"
        "security_id VARCHAR,trading_date DATE,joint_ready BOOLEAN,"
        "raw_state BOOLEAN,confirmed_state BOOLEAN,raw_streak_start_date DATE,"
        "confirmation_event BOOLEAN,PRIMARY KEY(logical_request_name,"
        "security_id,trading_date))"
    )
    audit.execute(
        "CREATE TABLE baseline_dimensions(security_id VARCHAR,trading_date DATE,"
        "dimension_id VARCHAR,q_bp INTEGER,main_threshold DOUBLE,"
        "weak_threshold DOUBLE,dimension_ready BOOLEAN,dimension_active BOOLEAN,"
        "PRIMARY KEY(security_id,trading_date,dimension_id))"
    )
    audit.execute(
        "CREATE TABLE response_checks(check_id VARCHAR,comparison VARCHAR,"
        "violation_count BIGINT,strict_change BOOLEAN,passed BOOLEAN,detail VARCHAR)"
    )
    audit.execute(
        "CREATE TABLE dimension_response_profiles(logical_request_name VARCHAR,"
        "dimension_id VARCHAR,row_count BIGINT,row_fingerprint VARCHAR,"
        "active_count BIGINT,active_fingerprint VARCHAR,"
        "PRIMARY KEY(logical_request_name,dimension_id))"
    )


def _attach_read_only(
    connection: duckdb.DuckDBPyConnection, path: Path, alias: str
) -> None:
    escaped = str(path.resolve()).replace("'", "''")
    connection.execute(f"ATTACH '{escaped}' AS {alias} (READ_ONLY)")


def _detach(connection: duckdb.DuckDBPyConnection, alias: str) -> None:
    connection.execute(f"DETACH {alias}")


def _path_metric_select(logical_name: str) -> str:
    name = logical_name.replace("'", "''")
    return f"""
        WITH base AS (
        SELECT '{name}' logical_request_name,i.request_id,r.request_hash,
          i.security_id,i.interval_ordinal,i.raw_start_date,i.confirmation_date,
          i.last_confirmed_end_date,i.termination_date,i.termination_reason,
          i.confirmed_observation_count,i.right_censored,
          a.adj_close confirmation_adj_close,a.atr14/a.adj_close natr14_confirmation,
          f5.adj_close/a.adj_close-1 close_return_5,
          f10.adj_close/a.adj_close-1 close_return_10,
          f20.adj_close/a.adj_close-1 close_return_20,
          tf5.adj_close/t.adj_close-1 termination_close_return_5,
          tf10.adj_close/t.adj_close-1 termination_close_return_10,
          tf20.adj_close/t.adj_close-1 termination_close_return_20,
          (SELECT max(m.adj_high/a.adj_close-1) FROM market_features m
            WHERE m.security_id=a.security_id AND m.observation_sequence
            BETWEEN a.observation_sequence+1 AND a.observation_sequence+5) mfe5,
          (SELECT min(m.adj_low/a.adj_close-1) FROM market_features m
            WHERE m.security_id=a.security_id AND m.observation_sequence
            BETWEEN a.observation_sequence+1 AND a.observation_sequence+5) mae5,
          (SELECT max(m.adj_high/a.adj_close-1) FROM market_features m
            WHERE m.security_id=a.security_id AND m.observation_sequence
            BETWEEN a.observation_sequence+1 AND a.observation_sequence+10) mfe10,
          (SELECT min(m.adj_low/a.adj_close-1) FROM market_features m
            WHERE m.security_id=a.security_id AND m.observation_sequence
            BETWEEN a.observation_sequence+1 AND a.observation_sequence+10) mae10,
          (SELECT max(m.adj_high/a.adj_close-1) FROM market_features m
            WHERE m.security_id=a.security_id AND m.observation_sequence
            BETWEEN a.observation_sequence+1 AND a.observation_sequence+20) mfe20,
          (SELECT min(m.adj_low/a.adj_close-1) FROM market_features m
            WHERE m.security_id=a.security_id AND m.observation_sequence
            BETWEEN a.observation_sequence+1 AND a.observation_sequence+20) mae20,
          (SELECT max(m.adj_high/t.adj_close-1) FROM market_features m
            WHERE m.security_id=t.security_id AND m.observation_sequence
            BETWEEN t.observation_sequence+1 AND t.observation_sequence+5)
            termination_mfe5,
          (SELECT min(m.adj_low/t.adj_close-1) FROM market_features m
            WHERE m.security_id=t.security_id AND m.observation_sequence
            BETWEEN t.observation_sequence+1 AND t.observation_sequence+5)
            termination_mae5,
          (SELECT max(m.adj_high/t.adj_close-1) FROM market_features m
            WHERE m.security_id=t.security_id AND m.observation_sequence
            BETWEEN t.observation_sequence+1 AND t.observation_sequence+10)
            termination_mfe10,
          (SELECT min(m.adj_low/t.adj_close-1) FROM market_features m
            WHERE m.security_id=t.security_id AND m.observation_sequence
            BETWEEN t.observation_sequence+1 AND t.observation_sequence+10)
            termination_mae10,
          (SELECT max(m.adj_high/t.adj_close-1) FROM market_features m
            WHERE m.security_id=t.security_id AND m.observation_sequence
            BETWEEN t.observation_sequence+1 AND t.observation_sequence+20)
            termination_mfe20,
          (SELECT min(m.adj_low/t.adj_close-1) FROM market_features m
            WHERE m.security_id=t.security_id AND m.observation_sequence
            BETWEEN t.observation_sequence+1 AND t.observation_sequence+20)
            termination_mae20,
          (SELECT m.observation_sequence-a.observation_sequence
            FROM market_features m WHERE m.security_id=a.security_id AND
            m.observation_sequence BETWEEN a.observation_sequence+1 AND
            a.observation_sequence+5 ORDER BY m.adj_high DESC,
            m.observation_sequence LIMIT 1) time_to_peak_5,
          (SELECT m.observation_sequence-a.observation_sequence
            FROM market_features m WHERE m.security_id=a.security_id AND
            m.observation_sequence BETWEEN a.observation_sequence+1 AND
            a.observation_sequence+5 ORDER BY m.adj_low,m.observation_sequence
            LIMIT 1) time_to_trough_5,
          (SELECT m.observation_sequence-a.observation_sequence
            FROM market_features m WHERE m.security_id=a.security_id AND
            m.observation_sequence BETWEEN a.observation_sequence+1 AND
            a.observation_sequence+10 ORDER BY m.adj_high DESC,
            m.observation_sequence LIMIT 1) time_to_peak_10,
          (SELECT m.observation_sequence-a.observation_sequence
            FROM market_features m WHERE m.security_id=a.security_id AND
            m.observation_sequence BETWEEN a.observation_sequence+1 AND
            a.observation_sequence+10 ORDER BY m.adj_low,m.observation_sequence
            LIMIT 1) time_to_trough_10,
          (SELECT m.observation_sequence-a.observation_sequence
            FROM market_features m WHERE m.security_id=a.security_id AND
            m.observation_sequence BETWEEN a.observation_sequence+1 AND
            a.observation_sequence+20 ORDER BY m.adj_high DESC,
            m.observation_sequence LIMIT 1) time_to_peak_20,
          (SELECT m.observation_sequence-a.observation_sequence
            FROM market_features m WHERE m.security_id=a.security_id AND
            m.observation_sequence BETWEEN a.observation_sequence+1 AND
            a.observation_sequence+20 ORDER BY m.adj_low,m.observation_sequence
            LIMIT 1) time_to_trough_20,
          f5.security_id IS NOT NULL horizon5_available,
          f10.security_id IS NOT NULL horizon10_available,
          f20.security_id IS NOT NULL horizon20_available,
          tf5.security_id IS NOT NULL termination_horizon5_available,
          tf10.security_id IS NOT NULL termination_horizon10_available,
          tf20.security_id IS NOT NULL termination_horizon20_available,
          (greatest(a.ma5,a.ma10,a.ma20,a.ma30,a.ma60)-
           least(a.ma5,a.ma10,a.ma20,a.ma30,a.ma60))/a.adj_close
           ma_cloud_width_pct,
          abs(a.adj_close-(a.ma5+a.ma10+a.ma20+a.ma30+a.ma60)/5)/a.adj_close
           price_to_ma_cloud_center_pct,
          a.range20,a.volume_ma20/nullif(a.volume_ma60,0) volume_ratio_20_60,
          a.amount_ma20/nullif(a.amount_ma60,0) amount_ratio_20_60,
          a.turnover_ma20/nullif(a.turnover_ma60,0) turnover_ratio_20_60
        FROM dyn.confirmed_intervals i
        JOIN dyn.dynamic_request r USING(request_id)
        JOIN market_features a ON a.security_id=i.security_id
          AND a.trading_date=i.confirmation_date
        LEFT JOIN market_features f5 ON f5.security_id=a.security_id
          AND f5.observation_sequence=a.observation_sequence+5
        LEFT JOIN market_features f10 ON f10.security_id=a.security_id
          AND f10.observation_sequence=a.observation_sequence+10
        LEFT JOIN market_features f20 ON f20.security_id=a.security_id
          AND f20.observation_sequence=a.observation_sequence+20
        LEFT JOIN market_features t ON t.security_id=i.security_id
          AND t.trading_date=i.termination_date
          AND i.termination_reason='raw_false'
        LEFT JOIN market_features tf5 ON tf5.security_id=t.security_id
          AND tf5.observation_sequence=t.observation_sequence+5
        LEFT JOIN market_features tf10 ON tf10.security_id=t.security_id
          AND tf10.observation_sequence=t.observation_sequence+10
        LEFT JOIN market_features tf20 ON tf20.security_id=t.security_id
          AND tf20.observation_sequence=t.observation_sequence+20
        ), excursions AS (
          SELECT *,greatest(mfe20,abs(mae20)) abs_max_excursion20 FROM base
        )
        SELECT *,abs_max_excursion20/nullif(natr14_confirmation,0)
          release_strength_atr,
          CASE WHEN NOT horizon20_available THEN 'unavailable'
               WHEN mfe20>abs(mae20) THEN 'up'
               WHEN mfe20<abs(mae20) THEN 'down' ELSE 'balanced' END
          release_direction
        FROM excursions
    """


def record_request_result(
    audit: duckdb.DuckDBPyConnection,
    *,
    logical_name: str,
    result_database: Path,
    summary: DynamicEvaluationSummary,
    profiles: Mapping[str, Any],
    wall_seconds: float,
    peak_rss_bytes: int,
    temporary_output_bytes: int,
) -> None:
    _attach_read_only(audit, result_database, "dyn")
    try:
        with duckdb.connect(str(result_database), read_only=True) as result:
            metrics = request_metrics(result)
            years = year_metrics(result)
            terminations = termination_metrics(result)
        audit.execute(
            "INSERT INTO request_metrics_records VALUES (?,?,?,?,?,?,?,?,?)",
            [
                logical_name,
                summary.request_id,
                summary.request_hash,
                "passed",
                json.dumps(metrics, sort_keys=True),
                json.dumps(profiles, sort_keys=True),
                wall_seconds,
                peak_rss_bytes,
                temporary_output_bytes,
            ],
        )
        audit.executemany(
            "INSERT INTO year_metrics_records VALUES (?,?,?)",
            [
                (logical_name, row["year"], json.dumps(row, sort_keys=True))
                for row in years
            ],
        )
        termination_records = [
            (
                logical_name,
                row["termination_reason"],
                row["count"],
                row["rate"],
            )
            for row in terminations
        ]
        if termination_records:
            audit.executemany(
                "INSERT INTO termination_metrics_records VALUES (?,?,?,?)",
                termination_records,
            )
        escaped = logical_name.replace("'", "''")
        audit.execute(
            f"INSERT INTO response_daily SELECT '{escaped}',security_id,"
            "trading_date,joint_ready,raw_state,confirmed_state,"
            "raw_streak_start_date,confirmation_event "
            "FROM dyn.daily_joint_states"
        )
        if logical_name == "D05_PCAVT_q15_k3":
            audit.execute(
                "INSERT INTO baseline_dimensions SELECT security_id,trading_date,"
                "dimension_id,q_bp,main_threshold,weak_threshold,dimension_ready,"
                "dimension_active FROM dyn.daily_dimension_states"
            )
        if logical_name == "D05_PCAVT_q15_k3" or logical_name.startswith("M0"):
            audit.execute(
                "INSERT INTO dimension_response_profiles "
                "SELECT ?,dimension_id,count(*),"
                "CAST(bit_xor(hash(security_id,trading_date,dimension_id,q_bp,"
                "main_threshold,weak_threshold,dimension_ready,dimension_active)) "
                "AS VARCHAR),count(*) FILTER(WHERE dimension_active),"
                "CAST(bit_xor(hash(security_id,trading_date)) "
                "FILTER(WHERE dimension_active) AS VARCHAR) "
                "FROM dyn.daily_dimension_states GROUP BY dimension_id",
                [logical_name],
            )
        if logical_name.startswith("M0"):
            target = {
                "M01": "P",
                "M02": "C",
                "M03": "A",
                "M04": "V",
                "M05": "T",
            }[logical_name[:3]]
            violation = audit.execute(
                "SELECT count(*) FROM baseline_dimensions b "
                "JOIN dyn.daily_dimension_states d "
                "USING(security_id,trading_date,dimension_id) "
                "WHERE b.dimension_id<>? AND (b.q_bp<>d.q_bp OR "
                "b.main_threshold<>d.main_threshold OR "
                "b.weak_threshold<>d.weak_threshold OR "
                "b.dimension_ready IS DISTINCT FROM d.dimension_ready OR "
                "b.dimension_active IS DISTINCT FROM d.dimension_active)",
                [target],
            ).fetchone()[0]
            target_missing = audit.execute(
                "SELECT count(*) FROM baseline_dimensions b ANTI JOIN ("
                "SELECT security_id,trading_date,dimension_id FROM "
                "dyn.daily_dimension_states WHERE dimension_id=? AND "
                "dimension_active=true) d "
                "USING(security_id,trading_date,dimension_id) "
                "WHERE b.dimension_id=? AND b.dimension_active=true",
                [target, target],
            ).fetchone()[0]
            strict = audit.execute(
                "SELECT count(*)>0 FROM dyn.daily_dimension_states d ANTI JOIN ("
                "SELECT security_id,trading_date,dimension_id FROM "
                "baseline_dimensions WHERE dimension_id=? AND "
                "dimension_active=true) b "
                "USING(security_id,trading_date,dimension_id) "
                "WHERE d.dimension_id=? AND d.dimension_active=true",
                [target, target],
            ).fetchone()[0]
            total_violation = int(violation + target_missing)
            audit.execute(
                "INSERT INTO response_checks VALUES (?,?,?,?,?,?)",
                [
                    f"marginal_{target}_non_target_invariance",
                    logical_name,
                    total_violation,
                    bool(strict),
                    total_violation == 0,
                    "online_against_D05",
                ],
            )
        select = _path_metric_select(logical_name)
        table_exists = audit.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name='interval_path_metrics'"
        ).fetchone()[0]
        if not table_exists:
            audit.execute(f"CREATE TABLE interval_path_metrics AS {select}")
        else:
            audit.execute(f"INSERT INTO interval_path_metrics {select}")
        market_structure_select = f"""
            WITH endpoints AS (
              SELECT '{escaped}' logical_request_name,i.request_id,i.security_id,
                i.interval_ordinal,e.anchor_type,e.anchor_date
                  FROM dyn.confirmed_intervals i CROSS JOIN LATERAL (VALUES
                ('raw_start',i.raw_start_date),
                ('confirmation',i.confirmation_date),
                ('last_confirmed_end',i.last_confirmed_end_date)
              ) e(anchor_type,anchor_date)
              UNION ALL
              SELECT '{escaped}',i.request_id,i.security_id,i.interval_ordinal,
                'T-20',m20.trading_date
              FROM dyn.confirmed_intervals i
              JOIN market_features r ON r.security_id=i.security_id
                AND r.trading_date=i.raw_start_date
              JOIN market_features m20 ON m20.security_id=r.security_id
                AND m20.observation_sequence=r.observation_sequence-20
            )
            SELECT e.*,m.ma5,m.ma10,m.ma20,m.ma30,m.ma60,
              (greatest(m.ma5,m.ma10,m.ma20,m.ma30,m.ma60)-
               least(m.ma5,m.ma10,m.ma20,m.ma30,m.ma60))/m.adj_close
               ma_cloud_width_pct,
              abs(m.adj_close-(m.ma5+m.ma10+m.ma20+m.ma30+m.ma60)/5)/
               m.adj_close price_to_ma_cloud_center_pct,
              m.atr14/m.adj_close natr14,m.range20,
              m.volume_ma20/nullif(m.volume_ma60,0) volume_ratio_20_60,
              m.amount_ma20/nullif(m.amount_ma60,0) amount_ratio_20_60,
              m.turnover_ma20/nullif(m.turnover_ma60,0) turnover_ratio_20_60
            FROM endpoints e JOIN market_features m ON m.security_id=e.security_id
              AND m.trading_date=e.anchor_date
        """
        market_structure_exists = audit.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name='market_structure_metrics'"
        ).fetchone()[0]
        if not market_structure_exists:
            audit.execute(
                f"CREATE TABLE market_structure_metrics AS {market_structure_select}"
            )
        else:
            audit.execute(
                f"INSERT INTO market_structure_metrics {market_structure_select}"
            )
    finally:
        _detach(audit, "dyn")


def record_score_structure(
    audit: duckdb.DuckDBPyConnection,
    *,
    logical_name: str,
    result_database: Path,
    score_database: Path,
) -> None:
    """Extract accepted Score fields at four interval endpoints."""

    _attach_read_only(audit, result_database, "dyn")
    _attach_read_only(audit, score_database, "score")
    escaped = logical_name.replace("'", "''")
    try:
        endpoint_sql = f"""
          SELECT '{escaped}' logical_request_name,i.request_id,i.security_id,
            i.interval_ordinal,e.anchor_type,e.anchor_date
          FROM dyn.confirmed_intervals i CROSS JOIN LATERAL (VALUES
            ('raw_start',i.raw_start_date),('confirmation',i.confirmation_date),
            ('last_confirmed_end',i.last_confirmed_end_date),
            ('termination',i.termination_date)
          ) e(anchor_type,anchor_date) WHERE e.anchor_date IS NOT NULL
        """
        dimension_select = f"""
          WITH endpoints AS ({endpoint_sql})
          SELECT e.*,d.dimension_id,d.score_dimension,d.score_dimension_min,
            d.eligible_dimension,d.validity_status,d.reason_codes
          FROM endpoints e JOIN score.daily_dimension_scores d
            ON d.security_id=e.security_id AND d.trading_date=e.anchor_date
        """
        component_select = f"""
          WITH endpoints AS ({endpoint_sql})
          SELECT e.*,c.dimension_id,c.component_id,c.raw_value,c.percentile,
            c.score,c.eligible,c.validity_status,c.reason_codes
          FROM endpoints e JOIN score.daily_component_scores c
            ON c.security_id=e.security_id AND c.trading_date=e.anchor_date
        """
        for table, select in (
            ("score_dimension_structure", dimension_select),
            ("score_component_structure", component_select),
        ):
            exists = audit.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name=?",
                [table],
            ).fetchone()[0]
            audit.execute(
                f"{'INSERT INTO' if exists else 'CREATE TABLE'} {table} "
                f"{'AS' if not exists else ''} {select}"
            )
    finally:
        _detach(audit, "score")
        _detach(audit, "dyn")


def run_response_checks_sql(
    audit: duckdb.DuckDBPyConnection,
) -> list[dict[str, Any]]:
    chains = {
        "q_raw": (
            "Q01_PCAVT_q10_k3",
            "D05_PCAVT_q15_k3",
            "Q02_PCAVT_q20_k3",
            "Q03_PCAVT_q25_k3",
            "raw_state",
        ),
        "q_confirmed": (
            "Q01_PCAVT_q10_k3",
            "D05_PCAVT_q15_k3",
            "Q02_PCAVT_q20_k3",
            "Q03_PCAVT_q25_k3",
            "confirmed_state",
        ),
        "k_confirmed": (
            "K03_PCAVT_q15_k7",
            "K02_PCAVT_q15_k5",
            "D05_PCAVT_q15_k3",
            "K01_PCAVT_q15_k2",
            "confirmed_state",
        ),
        "dimension_raw": (
            "D05_PCAVT_q15_k3",
            "D04_PCAV_q15_k3",
            "D03_PCA_q15_k3",
            "D02_PA_q15_k3",
            "D01_P_q15_k3",
            "raw_state",
        ),
        "dimension_confirmed": (
            "D05_PCAVT_q15_k3",
            "D04_PCAV_q15_k3",
            "D03_PCA_q15_k3",
            "D02_PA_q15_k3",
            "D01_P_q15_k3",
            "confirmed_state",
        ),
    }
    results: list[dict[str, Any]] = []
    for check_id, values in chains.items():
        *names, field = values
        strict_any = False
        total_violation = 0
        for smaller, larger in zip(names, names[1:]):
            violation = audit.execute(
                f"SELECT count(*) FROM response_daily s ANTI JOIN ("
                f"SELECT security_id,trading_date FROM response_daily "
                f"WHERE logical_request_name=? AND {field}=true) l "
                f"USING(security_id,trading_date) WHERE "
                f"s.logical_request_name=? AND s.{field}=true",
                [larger, smaller],
            ).fetchone()[0]
            small_count = audit.execute(
                f"SELECT count(*) FROM response_daily "
                f"WHERE logical_request_name=? AND {field}=true",
                [smaller],
            ).fetchone()[0]
            large_count = audit.execute(
                f"SELECT count(*) FROM response_daily "
                f"WHERE logical_request_name=? AND {field}=true",
                [larger],
            ).fetchone()[0]
            strict_any = strict_any or small_count != large_count
            total_violation += int(violation)
        passed = total_violation == 0 and strict_any
        audit.execute(
            "INSERT INTO response_checks VALUES (?,?,?,?,?,?)",
            [
                check_id,
                "->".join(names),
                total_violation,
                strict_any,
                passed,
                "subset_chain",
            ],
        )
        results.append(
            {
                "check_id": check_id,
                "violation_count": total_violation,
                "strict_change": strict_any,
                "passed": passed,
            }
        )
    for check_id, names, field in (
        (
            "k_raw_equality",
            (
                "K01_PCAVT_q15_k2",
                "D05_PCAVT_q15_k3",
                "K02_PCAVT_q15_k5",
                "K03_PCAVT_q15_k7",
            ),
            "raw_state",
        ),
        (
            "q_joint_ready_equality",
            (
                "Q01_PCAVT_q10_k3",
                "D05_PCAVT_q15_k3",
                "Q02_PCAVT_q20_k3",
                "Q03_PCAVT_q25_k3",
            ),
            "joint_ready",
        ),
    ):
        violation = 0
        for name in names[1:]:
            violation += int(
                audit.execute(
                    f"SELECT count(*) FROM response_daily a JOIN "
                    f"response_daily b USING(security_id,trading_date) "
                    f"WHERE a.logical_request_name=? AND "
                    f"b.logical_request_name=? AND "
                    f"a.{field} IS DISTINCT FROM b.{field}",
                    [names[0], name],
                ).fetchone()[0]
            )
        audit.execute(
            "INSERT INTO response_checks VALUES (?,?,?,?,?,?)",
            [check_id, "=".join(names), violation, None, violation == 0, "exact"],
        )
        results.append(
            {
                "check_id": check_id,
                "violation_count": violation,
                "passed": violation == 0,
            }
        )
    k_confirmation_violation = 0
    k_names = (
        "K01_PCAVT_q15_k2",
        "D05_PCAVT_q15_k3",
        "K02_PCAVT_q15_k5",
        "K03_PCAVT_q15_k7",
    )
    for lower_k, higher_k in zip(k_names, k_names[1:]):
        k_confirmation_violation += int(
            audit.execute(
                "SELECT count(*) FROM response_daily lo JOIN response_daily hi "
                "ON lo.security_id=hi.security_id AND "
                "lo.raw_streak_start_date=hi.raw_streak_start_date "
                "WHERE lo.logical_request_name=? AND hi.logical_request_name=? "
                "AND lo.confirmation_event AND hi.confirmation_event "
                "AND hi.trading_date<lo.trading_date",
                [lower_k, higher_k],
            ).fetchone()[0]
        )
    audit.execute(
        "INSERT INTO response_checks VALUES (?,?,?,?,?,?)",
        [
            "k_confirmation_not_earlier",
            "->".join(k_names),
            k_confirmation_violation,
            None,
            k_confirmation_violation == 0,
            "same_security_and_raw_streak_start",
        ],
    )
    results.append(
        {
            "check_id": "k_confirmation_not_earlier",
            "violation_count": k_confirmation_violation,
            "passed": k_confirmation_violation == 0,
        }
    )
    for marginal, dimension in (
        ("M01_P25", "P"),
        ("M02_C25", "C"),
        ("M03_A25", "A"),
        ("M04_V25", "V"),
        ("M05_T25", "T"),
    ):
        violation = int(
            audit.execute(
                "SELECT count(*) FROM response_daily b ANTI JOIN ("
                "SELECT security_id,trading_date FROM response_daily "
                "WHERE logical_request_name=? AND raw_state=true) m "
                "USING(security_id,trading_date) WHERE "
                "b.logical_request_name='D05_PCAVT_q15_k3' AND b.raw_state=true",
                [marginal],
            ).fetchone()[0]
        )
        baseline_count, marginal_count = audit.execute(
            "SELECT count(*) FILTER(WHERE logical_request_name='D05_PCAVT_q15_k3' "
            "AND raw_state),count(*) FILTER(WHERE logical_request_name=? AND raw_state) "
            "FROM response_daily",
            [marginal],
        ).fetchone()
        strict = int(marginal_count) > int(baseline_count)
        audit.execute(
            "INSERT INTO response_checks VALUES (?,?,?,?,?,?)",
            [
                f"marginal_{dimension}_joint_raw_superset",
                marginal,
                violation,
                strict,
                violation == 0,
                "D05_raw_true_subset",
            ],
        )
        results.append(
            {
                "check_id": f"marginal_{dimension}_joint_raw_superset",
                "violation_count": violation,
                "strict_change": strict,
                "passed": violation == 0,
            }
        )
    marginal_strict = audit.execute(
        "SELECT count(*) FROM response_checks "
        "WHERE check_id LIKE 'marginal_%' AND strict_change"
    ).fetchone()[0]
    if not marginal_strict:
        results.append(
            {
                "check_id": "marginal_overall_non_degenerate",
                "violation_count": 1,
                "passed": False,
            }
        )
    online_marginal_failures = int(
        audit.execute(
            "SELECT count(*) FROM response_checks WHERE check_id LIKE 'marginal_%' "
            "AND passed=false"
        ).fetchone()[0]
    )
    if online_marginal_failures:
        results.append(
            {
                "check_id": "marginal_online_checks",
                "violation_count": online_marginal_failures,
                "passed": False,
            }
        )
    failures = [row for row in results if not row["passed"]]
    if failures:
        raise R2AT04AuditError(
            "response_checks_failed", json.dumps(failures, sort_keys=True)
        )
    return results


def render_chart_samples_for_result(
    audit: duckdb.DuckDBPyConnection,
    *,
    logical_name: str,
    result_database: Path,
    review_directory: Path,
) -> list[dict[str, Any]]:
    """Render the fixed 12 charts after one chart request has finished."""

    path_rows = (
        audit.execute(
            "SELECT * FROM interval_path_metrics WHERE logical_request_name=?",
            [logical_name],
        )
        .fetch_arrow_table()
        .to_pylist()
    )
    if len(path_rows) < 12:
        raise R2AT04AuditError(
            "chart_request_has_fewer_than_12_intervals", logical_name
        )
    request_hash = str(path_rows[0]["request_hash"])
    sampled = deterministic_chart_sample(path_rows, request_hash=request_hash)
    _attach_read_only(audit, result_database, "dyn")
    registry: list[dict[str, Any]] = []
    try:
        request_metadata = audit.execute(
            "SELECT confirmation_k,q_by_dimension FROM dyn.dynamic_request"
        ).fetchone()
        for sample_index, sample in enumerate(sampled, start=1):
            security_id = str(sample["security_id"])
            confirmation_date = str(sample["confirmation_date"])
            context = (
                audit.execute(
                    "SELECT m.trading_date,m.adj_high,m.adj_low,m.adj_close,"
                    "m.ma5,m.ma10,m.ma20,m.ma30,m.ma60,m.volume_shares,"
                    "m.volume_ma20,m.volume_ma60,m.amount_yuan,m.amount_ma20,"
                    "m.amount_ma60,j.raw_state::INT raw_state_numeric,"
                    "j.confirmed_state::INT confirmed_state_numeric,"
                    "max(d.score_dimension) FILTER(WHERE d.dimension_id='P') score_P,"
                    "max(d.score_dimension) FILTER(WHERE d.dimension_id='C') score_C,"
                    "max(d.score_dimension) FILTER(WHERE d.dimension_id='A') score_A,"
                    "max(d.score_dimension) FILTER(WHERE d.dimension_id='V') score_V,"
                    "max(d.score_dimension) FILTER(WHERE d.dimension_id='T') score_T "
                    ",max(d.score_dimension_min) FILTER(WHERE d.dimension_id='P') min_P "
                    ",max(d.score_dimension_min) FILTER(WHERE d.dimension_id='C') min_C "
                    ",max(d.score_dimension_min) FILTER(WHERE d.dimension_id='A') min_A "
                    ",max(d.score_dimension_min) FILTER(WHERE d.dimension_id='V') min_V "
                    ",max(d.score_dimension_min) FILTER(WHERE d.dimension_id='T') min_T "
                    ",max(d.main_threshold) main_threshold "
                    ",max(d.weak_threshold) weak_threshold "
                    "FROM market_features m LEFT JOIN dyn.daily_joint_states j "
                    "USING(security_id,trading_date) LEFT JOIN "
                    "dyn.daily_dimension_states d USING(request_id,security_id,trading_date) "
                    "WHERE m.security_id=? AND m.observation_sequence BETWEEN "
                    "(SELECT observation_sequence-60 FROM market_features "
                    "WHERE security_id=? AND trading_date=?::DATE) AND "
                    "(SELECT observation_sequence+40 FROM market_features "
                    "WHERE security_id=? AND trading_date=?::DATE) "
                    "GROUP BY ALL ORDER BY m.trading_date",
                    [
                        security_id,
                        security_id,
                        confirmation_date,
                        security_id,
                        confirmation_date,
                    ],
                )
                .fetch_arrow_table()
                .to_pylist()
            )
            filename = (
                f"{logical_name}__{sample_index:02d}__{security_id}__"
                f"{confirmation_date}.png"
            ).replace(":", "-")
            relative_chart = Path("charts") / filename
            title = (
                f"{logical_name} | {sample['request_id']} | {security_id} | "
                f"raw={sample['raw_start_date']} confirm={confirmation_date} | "
                f"term={sample['termination_reason']} | "
                f"K={request_metadata[0]} q={request_metadata[1]} | "
                f"T+20={sample['close_return_20']} MFE20={sample['mfe20']} "
                f"MAE20={sample['mae20']}"
            )
            render_diagnostic_chart(
                path=review_directory / relative_chart,
                title=title,
                rows=context,
                markers={
                    "raw_start": str(sample["raw_start_date"]),
                    "confirmation": confirmation_date,
                    "confirmed_end": str(sample["last_confirmed_end_date"]),
                    "termination": (
                        str(sample["termination_date"])
                        if sample["termination_date"] is not None
                        else None
                    ),
                },
            )
            registry.append(
                {
                    "logical_request_name": logical_name,
                    "request_id": sample["request_id"],
                    "request_hash": request_hash,
                    "security_id": security_id,
                    "confirmation_date": confirmation_date,
                    "raw_start_date": sample["raw_start_date"],
                    "last_confirmed_end_date": sample["last_confirmed_end_date"],
                    "termination_date": sample["termination_date"],
                    "termination_reason": sample["termination_reason"],
                    "confirmed_observation_count": sample[
                        "confirmed_observation_count"
                    ],
                    "mfe20": sample["mfe20"],
                    "mae20": sample["mae20"],
                    "release_strength_atr": sample["release_strength_atr"],
                    "sample_stratum": sample["sample_stratum"],
                    "chart_path": relative_chart.as_posix(),
                }
            )
    finally:
        _detach(audit, "dyn")
    return registry


def write_csv_records(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def write_chart_review_files(
    review_directory: Path, registry: Sequence[Mapping[str, Any]]
) -> None:
    write_csv_records(review_directory / "chart_sample_registry.csv", registry)
    write_visual_review_worksheet(
        review_directory / "visual_review_worksheet.csv", registry
    )


def _file_identity(path: Path, root: Path) -> dict[str, Any]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
    }


def finalize_review_bundle(
    *,
    audit_database: Path,
    review_directory: Path,
    formal_run_id: str,
    score_identity: Mapping[str, Any],
    market_identity: Mapping[str, Any],
    source_spec: Mapping[str, Any],
    panel: Sequence[Mapping[str, Any]],
    duckdb_thread_count: int,
    chart_worker_count: int,
    chart_registry: Sequence[Mapping[str, Any]],
    blocking_anomalies: Sequence[str],
) -> dict[str, Any]:
    """Export only compact review files; never copy a full request result."""

    review_directory.mkdir(parents=True, exist_ok=True)
    (review_directory / "charts").mkdir(exist_ok=True)
    with duckdb.connect(str(audit_database), read_only=True) as audit:
        request_rows = [
            {
                "logical_request_name": row[0],
                "request_id": row[1],
                "request_hash": row[2],
                "validator_status": row[3],
                **json.loads(row[4]),
            }
            for row in audit.execute(
                "SELECT logical_request_name,request_id,request_hash,"
                "validator_status,metrics_json FROM request_metrics_records "
                "ORDER BY logical_request_name"
            ).fetchall()
        ]
        year_rows = [
            {"logical_request_name": row[0], **json.loads(row[1])}
            for row in audit.execute(
                "SELECT logical_request_name,metrics_json FROM "
                "year_metrics_records ORDER BY logical_request_name,year"
            ).fetchall()
        ]
        termination_rows = (
            audit.execute(
                "SELECT logical_request_name,termination_reason,count,rate "
                "FROM termination_metrics_records ORDER BY 1,2"
            )
            .fetch_arrow_table()
            .to_pylist()
        )
        response_rows = (
            audit.execute("SELECT * FROM response_checks ORDER BY check_id,comparison")
            .fetch_arrow_table()
            .to_pylist()
        )
        audit.execute(
            f"COPY interval_path_metrics TO "
            f"'{(audit_database.parent / 'interval_path_metrics.parquet').as_posix()}' "
            "(FORMAT PARQUET,COMPRESSION ZSTD)"
        )
    write_csv_records(review_directory / "request_metrics.csv", request_rows)
    write_csv_records(review_directory / "year_metrics.csv", year_rows)
    write_csv_records(review_directory / "termination_metrics.csv", termination_rows)
    write_csv_records(review_directory / "response_checks.csv", response_rows)
    write_chart_review_files(review_directory, chart_registry)
    source_public = {
        "source_id": source_spec["source_id"],
        "database_basename": source_spec["database_basename"],
        "database_sha256": source_spec["database_sha256"],
        "database_byte_size": source_spec["database_byte_size"],
        "source_snapshot_id": source_spec["source_snapshot_id"],
        "date_coverage": source_spec["date_coverage"],
        "security_coverage": source_spec["security_coverage"],
        "unit_mapping": source_spec["unit_mapping"],
    }
    (review_directory / "source_identity.json").write_text(
        json.dumps(source_public, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    public_panel = [dict(item) for item in panel]
    (review_directory / "request_panel.json").write_text(
        json.dumps(public_panel, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    recommendation = (
        "continue_to_owner_visual_review"
        if not blocking_anomalies
        else "blocked_evaluator_or_response_degeneracy"
    )
    validation = {
        "request_validator_failure_count": sum(
            row["validator_status"] != "passed" for row in request_rows
        ),
        "response_violation_count": sum(
            int(row["violation_count"] or 0) for row in response_rows
        ),
        "blocking_anomaly_count": len(blocking_anomalies),
        "status": "passed" if not blocking_anomalies else "failed",
    }
    (review_directory / "validation_receipt.json").write_text(
        json.dumps(
            {"task_id": "R2A-T04", "formal_run_id": formal_run_id, **validation},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    request_line = "\n".join(
        f"- `{row['logical_request_name']}`: raw={row['raw_true_count']}, "
        f"intervals={row['confirmed_interval_count']}, "
        f"breadth={row['security_breadth_rate']:.6f}"
        for row in request_rows
    )
    failed_checks = [row for row in response_rows if not row["passed"]]
    analysis_lines = [
        "# R2A-T04 automated result analysis",
        "",
        "## 1. Input identity and hashes",
        "",
        f"Formal run `{formal_run_id}` used Score `{score_identity['sha256']}` "
        f"({score_identity['byte_size']} bytes) and market source "
        f"`{market_identity['source_id']}` / `{market_identity['sha256']}`.",
        "",
        "## 2. Frozen 16-request panel",
        "",
        f"The panel contains {len(panel)} unique canonical requests. It is diagnostic and does not select a best q/K.",
        "",
        "## 3. Request validator status",
        "",
        f"Independent accepted-output validator failures: `{validation['request_validator_failure_count']}`.",
        "",
        "## 4. Request-level metrics",
        "",
        request_line,
        "",
        "## 5. Yearly metrics",
        "",
        f"`year_metrics.csv` contains {len(year_rows)} daily-year and interval-year records; 2026 is retained through 2026-06-30.",
        "",
        "## 6. Equal-q response",
        "",
        "Exact-key raw and confirmed subset results are recorded in `response_checks.csv`.",
        "",
        "## 7. K response",
        "",
        "Raw-state equality, confirmed contraction, and non-early confirmation checks are recorded in `response_checks.csv`.",
        "",
        "## 8. Dimension contraction",
        "",
        "P→PA→PCA→PCAV→PCAVT exact-key contraction checks are recorded in `response_checks.csv`.",
        "",
        "## 9. Marginal q response",
        "",
        "Target expansion, joint-raw supersets, and non-target invariance were checked for P/C/A/V/T separately.",
        "",
        "## 10. Evaluability reason decomposition",
        "",
        "Request metrics retain present, validity, eligibility, finite, joint-ready and non-ready reason counts.",
        "",
        "## 11. Interval duration",
        "",
        "Each request reports min, p10, p25, median, p75, p90, p99 and max confirmed-observation duration.",
        "",
        "## 12. Security breadth",
        "",
        "Breadth, security-with-interval and zero-interval-security counts are reported per request and year.",
        "",
        "## 13. Termination distribution",
        "",
        f"`termination_metrics.csv` contains {len(termination_rows)} request/reason rows.",
        "",
        "## 14. Score component structure",
        "",
        "The local audit database retains accepted dimension mean/min and all component raw/percentile/score fields at interval endpoints.",
        "",
        "## 15. Market-derived contraction structure",
        "",
        "T-20, raw start, confirmation and confirmed-end MA cloud, NATR/range and participation ratios are retained locally.",
        "",
        "## 16. Future path diagnostics",
        "",
        "T+5/T+10/T+20 returns, MFE, MAE and time-to-peak/trough use security observation offsets. They are not backtest returns.",
        "",
        "## 17. Chart sample inventory",
        "",
        f"The deterministic registry contains `{len(chart_registry)}` PNG charts; manual worksheet fields remain blank.",
        "",
        "## 18. Failure cases",
        "",
        f"Response failures: `{len(failed_checks)}`; blocking anomalies: `{len(blocking_anomalies)}`.",
        "",
        "## 19. Limitations",
        "",
        "This audit does not optimize parameters, select a canonical state version, backtest a strategy, or replace owner visual review.",
        "",
        "## 20. Recommendation",
        "",
        f"Automated recommendation: `{recommendation}`. Owner visual review remains `pending`.",
    ]
    (review_directory / "result_analysis.md").write_text(
        "\n".join(analysis_lines) + "\n", encoding="utf-8", newline="\n"
    )
    files = [
        path
        for path in review_directory.rglob("*")
        if path.is_file() and path.name != "run_summary.json"
    ]
    summary = {
        "task_id": "R2A-T04",
        "bundle_mode": "formal_review",
        "status": (
            "real_data_run_completed_pending_result_review"
            if not blocking_anomalies
            else "formal_run_blocked"
        ),
        "formal_run_id": formal_run_id,
        "formal_authorization_id": "R2A-T04-REAL-AUDIT-AUTH-20260719",
        "panel_id": "r2a_t04_representative_panel.v1",
        "request_count": 16,
        "score_source": {
            "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
            "sha256": score_identity["sha256"],
            "byte_size": score_identity["byte_size"],
        },
        "market_source": {
            "source_id": market_identity["source_id"],
            "sha256": market_identity["sha256"],
            "byte_size": market_identity["byte_size"],
        },
        "execution": {
            "full_universe_request_concurrency": 1,
            "duckdb_thread_count": duckdb_thread_count,
            "chart_worker_count": chart_worker_count,
            "formal_run_consumed": True,
        },
        "validation": validation,
        "review_boundary": {
            "automated_recommendation": recommendation,
            "owner_visual_review": "pending",
            "R2A_T04_DONE": "absent",
            "R2A_T05_allowed_to_start": False,
        },
        "files": sorted(
            (_file_identity(path, review_directory) for path in files),
            key=lambda item: item["relative_path"],
        ),
    }
    (review_directory / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return summary


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _assert_no_consumed_authorization(parent: Path, authorization_id: str) -> None:
    for authorization_path in parent.glob("*/authorization.json"):
        value = json.loads(authorization_path.read_text(encoding="utf-8"))
        if (
            value.get("formal_authorization_id") == authorization_id
            and value.get("formal_run_consumed") is True
        ):
            raise R2AT04AuditError(
                "formal_authorization_already_consumed", authorization_path.parent.name
            )


def run_formal_audit(
    *,
    config: Mapping[str, Any],
    panel: Sequence[Mapping[str, Any]],
    score_database: Path,
    market_database: Path,
    market_source_spec: Mapping[str, Any],
    output_root: Path,
    review_output: Path,
    preflight_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Run all 16 accepted requests strictly serially, once."""

    authorization_id = str(config["formal_authorization_id"])
    if (
        config.get("status") != "authorized_not_started"
        or config.get("formal_run_authorized") is not True
        or config.get("formal_run_consumed") is not False
    ):
        raise R2AT04AuditError("formal_authorization_metadata_invalid")
    threads = config["thread_preflight"].get("duckdb_thread_count")
    if (
        config["thread_preflight"].get("thread_benchmark_status") != "passed"
        or threads not in (4, 8, 16)
        or preflight_receipt.get("status") != "passed"
        or preflight_receipt.get("duckdb_thread_count") != threads
        or preflight_receipt.get("formal_run_attempt_consumed") is not False
    ):
        raise R2AT04AuditError("formal_preflight_gate_failed")
    if config.get("full_universe_request_concurrency") != 1 or len(panel) != 16:
        raise R2AT04AuditError("formal_concurrency_or_panel_gate_failed")
    if output_root.exists() or review_output.exists():
        raise R2AT04AuditError("formal_output_already_exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_consumed_authorization(output_root.parent, authorization_id)
    free_bytes = free_disk_gate(
        output_root.parent,
        int(config["score_release"]["byte_size"]),
        int(config["minimum_free_disk_score_db_multiple"]),
    )
    score_identity = verify_file_identity(
        score_database,
        expected_sha256=str(config["score_release"]["sha256"]),
        expected_byte_size=int(config["score_release"]["byte_size"]),
    )
    market_validation_scratch = output_root.parent / f".{output_root.name}.market-gate"
    market_identity = validate_market_source(
        score_database=score_database,
        market_database=market_database,
        source_spec=market_source_spec,
        scratch_directory=market_validation_scratch,
    )
    output_root.mkdir()
    for child in ("requests", "request-results", "charts", "logs"):
        (output_root / child).mkdir()
    review_output.mkdir(parents=True)
    (review_output / "charts").mkdir()
    authorization_record = {
        "formal_authorization_id": authorization_id,
        "formal_run_consumed": True,
        "full_universe_request_concurrency": 1,
        "duckdb_thread_count": threads,
        "thread_benchmark_fingerprint": config["thread_preflight"][
            "thread_benchmark_fingerprint"
        ],
    }
    _write_json(output_root / "authorization.json", authorization_record)
    _write_json(output_root / "source_manifest.json", dict(market_source_spec))
    _write_json(output_root / "request_panel.json", list(panel))
    for item in panel:
        _write_json(
            output_root / "requests" / f"{item['logical_request_name']}.json",
            {
                key: item[key]
                for key in (
                    "request_schema_version",
                    "request_id",
                    "request_hash",
                    "spec",
                )
            },
        )
    audit_path = output_root / "audit_metrics.duckdb"
    chart_registry: list[dict[str, Any]] = []
    request_summaries: list[dict[str, Any]] = []
    log_path = output_root / "logs" / "formal_run.jsonl"
    started = time.perf_counter()
    with duckdb.connect(str(audit_path)) as audit:
        audit.execute(f"SET threads={threads}")
        initialize_audit_database(
            audit,
            market_database=market_database,
            source_query=str(market_source_spec["source_query"]),
        )
        for ordinal, item in enumerate(panel, start=1):
            logical_name = str(item["logical_request_name"])
            result_path = output_root / "request-results" / f"{logical_name}.duckdb"
            summary, wall, peak, temporary_bytes = evaluate_request_with_threads(
                score_database=score_database,
                canonical_request={
                    key: item[key]
                    for key in (
                        "request_schema_version",
                        "request_id",
                        "request_hash",
                        "spec",
                    )
                },
                output_database=result_path,
                duckdb_thread_count=int(threads),
                security_ids=None,
            )
            with duckdb.connect(str(result_path), read_only=True) as result:
                validate_dynamic_evaluation_output(result)
                profiles = canonical_table_profiles(result)
            record_request_result(
                audit,
                logical_name=logical_name,
                result_database=result_path,
                summary=summary,
                profiles=profiles,
                wall_seconds=wall,
                peak_rss_bytes=peak,
                temporary_output_bytes=temporary_bytes,
            )
            record_score_structure(
                audit,
                logical_name=logical_name,
                result_database=result_path,
                score_database=score_database,
            )
            if logical_name in config["chart_request_names"]:
                chart_registry.extend(
                    render_chart_samples_for_result(
                        audit,
                        logical_name=logical_name,
                        result_database=result_path,
                        review_directory=review_output,
                    )
                )
            request_summary = {
                "ordinal": ordinal,
                "logical_request_name": logical_name,
                "request_id": summary.request_id,
                "validator_status": "passed",
                "wall_seconds": wall,
                "peak_rss_bytes": peak,
                "temporary_output_bytes": temporary_bytes,
                "output_tables": profiles,
            }
            request_summaries.append(request_summary)
            with log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(request_summary, sort_keys=True) + "\n")
            result_path.unlink()
        response_results = run_response_checks_sql(audit)
        total_raw_true, total_intervals = audit.execute(
            "SELECT sum(CAST(json_extract(metrics_json,'$.raw_true_count') AS BIGINT)),"
            "sum(CAST(json_extract(metrics_json,'$.confirmed_interval_count') AS BIGINT)) "
            "FROM request_metrics_records"
        ).fetchone()
        if not total_raw_true or not total_intervals:
            raise R2AT04AuditError("all_requests_zero_state_or_interval")
        audit.execute("CHECKPOINT")
    if len(chart_registry) != 48:
        raise R2AT04AuditError("formal_chart_count_mismatch", str(len(chart_registry)))
    formal_run_id = output_root.name
    blocking_anomalies: list[str] = []
    summary = finalize_review_bundle(
        audit_database=audit_path,
        review_directory=review_output,
        formal_run_id=formal_run_id,
        score_identity=score_identity,
        market_identity=market_identity,
        source_spec=market_source_spec,
        panel=panel,
        duckdb_thread_count=int(threads),
        chart_worker_count=int(config["chart_worker_count"]),
        chart_registry=chart_registry,
        blocking_anomalies=blocking_anomalies,
    )
    run_manifest = {
        "formal_run_id": formal_run_id,
        "formal_authorization_id": authorization_id,
        "formal_run_consumed": True,
        "request_count": 16,
        "request_execution": "strictly_serial",
        "duckdb_thread_count": threads,
        "free_bytes_before_run": free_bytes,
        "elapsed_seconds": time.perf_counter() - started,
        "response_checks": response_results,
        "review_bundle_status": summary["validation"]["status"],
    }
    _write_json(output_root / "run_manifest.json", run_manifest)
    _write_json(output_root / "validation_receipt.json", summary["validation"])
    (output_root / "result_analysis.md").write_text(
        (review_output / "result_analysis.md").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "formal_run_id": formal_run_id,
        "status": summary["status"],
        "score_identity": score_identity,
        "market_identity": market_identity,
        "request_count": 16,
        "chart_count": 48,
        "elapsed_seconds": run_manifest["elapsed_seconds"],
        "automated_recommendation": summary["review_boundary"][
            "automated_recommendation"
        ],
    }


def run_real_input_smoke(
    *,
    config: Mapping[str, Any],
    score_database: Path,
    market_database: Path,
    market_source_spec: Mapping[str, Any],
    canonical_request: Mapping[str, Any],
    benchmark_receipt: Mapping[str, Any],
    scratch_directory: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Run the authorized four-security real-input chain without consuming formal."""

    threads = config["thread_preflight"].get("duckdb_thread_count")
    securities = tuple(str(item) for item in benchmark_receipt.get("security_ids", []))
    if (
        config.get("formal_run_authorized") is not True
        or config.get("formal_run_consumed") is not False
        or benchmark_receipt.get("status") != "passed"
        or benchmark_receipt.get("selected_duckdb_thread_count") != threads
        or len(securities) != 4
    ):
        raise R2AT04AuditError("real_smoke_authorization_gate_failed")
    scratch_directory.mkdir(parents=True, exist_ok=False)
    score_before = verify_file_identity(
        score_database,
        expected_sha256=str(config["score_release"]["sha256"]),
        expected_byte_size=int(config["score_release"]["byte_size"]),
    )
    market_before = verify_file_identity(
        market_database,
        expected_sha256=str(market_source_spec["database_sha256"]),
        expected_byte_size=int(market_source_spec["database_byte_size"]),
    )
    started = time.perf_counter()
    try:
        audit_path = scratch_directory / "smoke_audit.duckdb"
        result_path = scratch_directory / "smoke_result.duckdb"
        bundle = scratch_directory / "review-bundle"
        bundle.mkdir()
        chart_count = 0
        with duckdb.connect(str(audit_path)) as audit:
            audit.execute(f"SET threads={threads}")
            initialize_audit_database(
                audit,
                market_database=market_database,
                source_query=str(market_source_spec["source_query"]),
                security_ids=securities,
            )
            summary, wall, peak, temporary_bytes = evaluate_request_with_threads(
                score_database=score_database,
                canonical_request=canonical_request,
                output_database=result_path,
                duckdb_thread_count=int(threads),
                security_ids=securities,
            )
            with duckdb.connect(str(result_path), read_only=True) as result:
                validate_dynamic_evaluation_output(result)
                profiles = canonical_table_profiles(result)
            record_request_result(
                audit,
                logical_name="D05_PCAVT_q15_k3",
                result_database=result_path,
                summary=summary,
                profiles=profiles,
                wall_seconds=wall,
                peak_rss_bytes=peak,
                temporary_output_bytes=temporary_bytes,
            )
            interval_count = int(
                audit.execute("SELECT count(*) FROM interval_path_metrics").fetchone()[
                    0
                ]
            )
            if interval_count:
                sample = audit.execute(
                    "SELECT security_id,confirmation_date,raw_start_date,"
                    "last_confirmed_end_date,termination_date,termination_reason "
                    "FROM interval_path_metrics ORDER BY request_hash,security_id,"
                    "confirmation_date LIMIT 1"
                ).fetchone()
                _attach_read_only(audit, result_path, "dyn")
                try:
                    context = (
                        audit.execute(
                            "SELECT m.trading_date,m.adj_high,m.adj_low,m.adj_close,"
                            "m.ma5,m.ma10,m.ma20,m.ma30,m.ma60,m.volume_shares,"
                            "m.volume_ma20,m.volume_ma60,m.amount_yuan,m.amount_ma20,"
                            "m.amount_ma60,j.raw_state::INT raw_state_numeric,"
                            "j.confirmed_state::INT confirmed_state_numeric "
                            "FROM market_features m LEFT JOIN dyn.daily_joint_states j "
                            "USING(security_id,trading_date) WHERE m.security_id=? AND "
                            "m.observation_sequence BETWEEN (SELECT observation_sequence-60 "
                            "FROM market_features WHERE security_id=? AND trading_date=?) AND "
                            "(SELECT observation_sequence+40 FROM market_features "
                            "WHERE security_id=? AND trading_date=?) ORDER BY m.trading_date",
                            [sample[0], sample[0], sample[1], sample[0], sample[1]],
                        )
                        .fetch_arrow_table()
                        .to_pylist()
                    )
                finally:
                    _detach(audit, "dyn")
                chart_path = bundle / "charts" / "real_input_smoke.png"
                render_diagnostic_chart(
                    path=chart_path,
                    title=(
                        f"REAL SMOKE | {canonical_request['request_id']} | "
                        f"{sample[0]} | confirm={sample[1]} | term={sample[5]}"
                    ),
                    rows=context,
                    markers={
                        "raw_start": str(sample[2]),
                        "confirmation": str(sample[1]),
                        "confirmed_end": str(sample[3]),
                        "termination": str(sample[4]) if sample[4] else None,
                    },
                )
                chart_count = 1
        payload = {
            "status": "passed",
            "score_db_sha256": score_before["sha256"],
            "market_source_sha256": market_before["sha256"],
            "request_id": canonical_request["request_id"],
            "security_ids": list(securities),
            "duckdb_thread_count": threads,
            "output_table_counts": {
                name: value["row_count"] for name, value in profiles.items()
            },
            "output_fingerprints": {
                name: value["canonical_fingerprint"] for name, value in profiles.items()
            },
            "validator_status": "passed",
            "elapsed_seconds": time.perf_counter() - started,
            "temporary_bytes": temporary_bytes,
            "interval_count": interval_count,
            "chart_count": chart_count,
            "zero_interval_smoke": interval_count == 0,
            "formal_run_attempt_consumed": False,
        }
        _write_json(bundle / "smoke_receipt.json", payload)
        files = [_file_identity(bundle / "smoke_receipt.json", bundle)]
        files.extend(
            _file_identity(path, bundle) for path in (bundle / "charts").glob("*.png")
        )
        smoke_summary = {
            "task_id": "R2A-T04",
            "bundle_mode": "real_input_smoke",
            "status": "real_data_run_completed_pending_result_review",
            "formal_run_id": "R2A-T04-20260719T000000000Z",
            "formal_authorization_id": config["formal_authorization_id"],
            "panel_id": config["panel_id"],
            "request_count": 1,
            "score_source": {
                "score_release_id": config["score_release"]["score_release_id"],
                "sha256": score_before["sha256"],
                "byte_size": score_before["byte_size"],
            },
            "market_source": {
                "source_id": market_source_spec["source_id"],
                "sha256": market_before["sha256"],
                "byte_size": market_before["byte_size"],
            },
            "execution": {
                "full_universe_request_concurrency": 1,
                "duckdb_thread_count": threads,
                "chart_worker_count": 0,
                "formal_run_consumed": False,
            },
            "validation": {
                "request_validator_failure_count": 0,
                "response_violation_count": 0,
                "blocking_anomaly_count": 0,
                "status": "passed",
            },
            "review_boundary": {
                "automated_recommendation": "smoke_passed",
                "owner_visual_review": "not_applicable_smoke",
                "R2A_T04_DONE": "absent",
                "R2A_T05_allowed_to_start": False,
            },
            "files": files,
        }
        _write_json(bundle / "run_summary.json", smoke_summary)
        from src.r2a.r2a_t04_audit_validator import validate_review_bundle

        validate_review_bundle(bundle)
        if (
            verify_file_identity(
                score_database,
                expected_sha256=score_before["sha256"],
                expected_byte_size=score_before["byte_size"],
            )
            != score_before
        ):
            raise R2AT04AuditError("score_source_mutated_during_real_smoke")
        if (
            verify_file_identity(
                market_database,
                expected_sha256=market_before["sha256"],
                expected_byte_size=market_before["byte_size"],
            )
            != market_before
        ):
            raise R2AT04AuditError("market_source_mutated_during_real_smoke")
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(receipt_path, payload)
        return payload
    finally:
        if scratch_directory.exists():
            shutil.rmtree(scratch_directory)
