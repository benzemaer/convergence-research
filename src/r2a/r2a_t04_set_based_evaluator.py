"""T04-local set-based transfer wrapper for the accepted T03 evaluator."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb
import psutil

from src.r2a.r2a_t02_request_identity import validate_canonical_request
from src.r2a.r2a_t03_dynamic_evaluator import (
    EVALUATOR_VERSION,
    OUTPUT_SCHEMA_VERSION,
    DynamicEvaluationError,
    _create_output_tables,
    _drop_temporary_tables,
    _populate_dimensions,
    _populate_intervals,
    _populate_joint_states,
    _resolve_security_scope,
    _scope_predicate,
    _validate_source_content,
    _validate_source_schema,
    _verify_accepted_binding,
)
from src.r2a.r2a_t03_output_contract import (
    DynamicEvaluationSummary,
    validate_dynamic_evaluation_output,
)


class _PeakRSSSampler:
    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        process = psutil.Process()
        while not self._stop.wait(0.05):
            try:
                self.peak = max(self.peak, process.memory_info().rss)
            except psutil.Error:
                return

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


def _copy_selected_source_set_based(
    *,
    output: duckdb.DuckDBPyConnection,
    score_database: Path,
    securities: tuple[str, ...],
    dimensions: tuple[str, ...],
) -> int:
    scope_sql, scope_params = _scope_predicate(securities)
    dimension_sql = "dimension_id IN (" + ",".join("?" for _ in dimensions) + ")"
    escaped = str(score_database.resolve()).replace("'", "''")
    output.execute(f"ATTACH '{escaped}' AS score_source (READ_ONLY)")
    try:
        output.execute(
            "INSERT INTO staging_spine "
            "SELECT score_release_id,security_id,trading_date,observation_sequence,"
            "expected_observation_status,observation_available_time "
            "FROM score_source.security_observation_spine "
            f"WHERE {scope_sql} ORDER BY security_id,observation_sequence",
            scope_params,
        )
        spine_count = int(
            output.execute("SELECT count(*) FROM staging_spine").fetchone()[0]
        )
        output.execute(
            "INSERT INTO staging_dimensions "
            "SELECT score_release_id,security_id,trading_date,observation_sequence,"
            "dimension_id,score_dimension,score_dimension_min,eligible_dimension,"
            "validity_status,reason_codes,available_time "
            "FROM score_source.daily_dimension_scores "
            f"WHERE {scope_sql} AND {dimension_sql} "
            "ORDER BY security_id,observation_sequence,dimension_id",
            [*scope_params, *dimensions],
        )
    finally:
        output.execute("DETACH score_source")
    return spine_count


def _evaluate_set_based_connections(
    *,
    source: duckdb.DuckDBPyConnection,
    output: duckdb.DuckDBPyConnection,
    score_database: Path,
    canonical_request: Mapping[str, Any],
    security_ids: Sequence[str] | None,
) -> DynamicEvaluationSummary:
    _verify_accepted_binding()
    envelope = validate_canonical_request(canonical_request)
    spec = envelope["spec"]
    selected_dimensions = tuple(str(item) for item in spec["selected_dimensions"])
    q_by_dimension = {
        str(key): int(value) for key, value in spec["q_by_dimension"].items()
    }
    confirmation_k = int(spec["confirmation_k"])
    _validate_source_schema(source)
    security_scope, requested_ids, evaluated_ids = _resolve_security_scope(
        source, security_ids
    )
    _validate_source_content(
        source,
        evaluated_ids,
        selected_dimensions,
        str(spec["score_release_id"]),
    )
    _create_output_tables(output)
    spine_count = _copy_selected_source_set_based(
        output=output,
        score_database=score_database,
        securities=evaluated_ids,
        dimensions=selected_dimensions,
    )
    q_json = json.dumps(
        q_by_dimension,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    output.execute(
        "INSERT INTO dynamic_request VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            envelope["request_id"],
            envelope["request_hash"],
            envelope["request_schema_version"],
            spec["dynamic_protocol_version"],
            EVALUATOR_VERSION,
            OUTPUT_SCHEMA_VERSION,
            spec["score_release_id"],
            list(selected_dimensions),
            q_json,
            confirmation_k,
            1000,
            1e-12,
        ],
    )
    date_min, date_max = output.execute(
        "SELECT min(trading_date),max(trading_date) FROM staging_spine"
    ).fetchone()
    output.execute(
        "INSERT INTO evaluation_scope VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            envelope["request_id"],
            security_scope,
            list(requested_ids),
            len(evaluated_ids),
            date_min,
            date_max,
            spine_count,
            len(selected_dimensions),
        ],
    )
    request_id = str(envelope["request_id"])
    _populate_dimensions(output, request_id, selected_dimensions, q_by_dimension)
    _populate_joint_states(output, request_id, confirmation_k)
    _populate_intervals(
        output,
        request_id,
        selected_dimensions,
        q_json,
        confirmation_k,
    )
    _drop_temporary_tables(output)
    return validate_dynamic_evaluation_output(output)


def evaluate_request_set_based_with_threads(
    *,
    score_database: Path,
    canonical_request: Mapping[str, Any],
    output_database: Path,
    duckdb_thread_count: int,
    security_ids: Sequence[str] | None,
) -> tuple[DynamicEvaluationSummary, float, int, int]:
    """Evaluate one request with set-based read-only source transfer."""

    if duckdb_thread_count not in (4, 8, 16):
        raise DynamicEvaluationError("duckdb_thread_count_not_frozen")
    source_path = Path(score_database)
    target = Path(output_database)
    if not source_path.is_file():
        raise DynamicEvaluationError("score_database_missing", str(source_path))
    if source_path.resolve() == target.resolve():
        raise DynamicEvaluationError("source_output_path_same")
    if not target.parent.is_dir():
        raise DynamicEvaluationError("output_parent_missing", str(target.parent))
    if target.exists():
        raise DynamicEvaluationError("output_already_exists", str(target))
    descriptor, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp.duckdb"
    )
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    summary: DynamicEvaluationSummary | None = None
    started = time.perf_counter()
    with _PeakRSSSampler() as rss:
        try:
            with (
                duckdb.connect(str(source_path), read_only=True) as source,
                duckdb.connect(str(temporary)) as output,
            ):
                source.execute(f"SET threads={duckdb_thread_count}")
                output.execute(f"SET threads={duckdb_thread_count}")
                summary = _evaluate_set_based_connections(
                    source=source,
                    output=output,
                    score_database=source_path,
                    canonical_request=canonical_request,
                    security_ids=security_ids,
                )
                output.execute("CHECKPOINT")
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise DynamicEvaluationError(
                    "output_already_exists", str(target)
                ) from error
        finally:
            temporary.unlink(missing_ok=True)
    if summary is None:
        raise DynamicEvaluationError("evaluation_summary_missing")
    return summary, time.perf_counter() - started, rss.peak, target.stat().st_size
