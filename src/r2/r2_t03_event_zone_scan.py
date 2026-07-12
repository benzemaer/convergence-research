# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import (
    ROOT,
    current_commit,
    formal_source_binding,
    repo_rel,
    sha256_bytes,
    write_csv,
    write_json,
)
from src.r2.r2_t02_protocol_freeze import (
    DailyInput,
    _earliest_gap_decision,
    _gap_segment,
    _rows_between,
    atomic_intervals,
    group_event_zones,
    replay_confirmation,
)

TASK_ID = "R2-T03"
TABLE_CONTRACT_NAMES = {
    "atomic_baseline_profile",
    "atomic_confirmed_daily",
    "d_qualification_profile",
    "dg_event_zone_profile",
    "event_zone",
    "event_zone_bridge_segment",
    "event_zone_membership_daily",
    "qualified_component",
    "strict_core_shell_profile",
    "strict_core_window_comparison",
    "transition_aggregate_profile",
    "transition_profile",
    "window_overlap_comparison",
}


class R2T03Error(RuntimeError):
    pass


@dataclass(frozen=True)
class RouteSpec:
    route_id: str
    candidate_role: str
    state_line: str
    W: int
    K: int
    qP: float
    qC: float
    qT: float
    qV: float
    source_kind: str
    source_id: str
    daily_path: str
    interval_path: str


def load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("task_id") != TASK_ID:
        raise R2T03Error("config_task_id_mismatch")
    return value


def run_scan(
    config_path: Path,
    output_dir: Path,
    *,
    worker_count: int | None = None,
    baseline_only: bool = False,
    root: Path = ROOT,
) -> dict[str, Any]:
    started = time.time()
    config_path = config_path.resolve()
    config = load_config(config_path)
    output_dir = output_dir.resolve()
    run_id = output_dir.name
    if not run_id.startswith("R2-T03-"):
        raise R2T03Error("run_id_must_start_R2_T03")
    execution_commit = current_commit(root)
    _assert_formal_sources_clean(config, execution_commit, root)
    workers = worker_count or int(config["runtime"]["formal_worker_count"])
    if workers != 1:
        raise R2T03Error("v1_runner_supports_exact_single_worker_only")
    output_dir.mkdir(parents=True, exist_ok=True)
    cells = _read_cells(root / config["inputs"]["cell_registry_path"])
    readiness, routes = validate_source_readiness(config, cells, root=root)
    write_json(output_dir / "r2_t03_source_readiness.json", readiness)
    bindings = _input_binding(config, config_path, execution_commit, readiness, root)
    write_json(output_dir / "r2_t03_input_binding.json", bindings)
    database = output_dir / config["runtime"]["output_database_name"]
    if database.exists():
        database.unlink()
    connection = duckdb.connect(str(database))
    try:
        connection.execute(f"SET threads={int(config['runtime']['duckdb_threads'])}")
        connection.execute(
            f"SET memory_limit='{config['runtime']['duckdb_memory_limit']}'"
        )
        connection.execute(f"SET TimeZone='{config['runtime']['timezone']}'")
        _create_output_schema(connection)
        _insert_cell_registry(connection, cells)
        _materialize_route_daily(connection, routes, root)
        _create_atomic_daily_view(connection)
        connection.execute("BEGIN TRANSACTION")
        try:
            execution_rows = _execute_routes(
                connection,
                routes,
                cells,
                heartbeat_interval=int(
                    config["runtime"]["heartbeat_security_interval"]
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        _create_profiles_and_comparisons(connection)
        _create_atomic_interval_view(connection)
        fingerprint = _database_fingerprint(connection)
        if baseline_only:
            write_json(
                output_dir / "r2_t03_single_worker_baseline.json",
                {
                    "task_id": TASK_ID,
                    "run_id": run_id,
                    "worker_count": workers,
                    "status": "passed",
                    "database_fingerprint": fingerprint,
                    "cell_count": 72,
                },
            )
        _export_compact_tables(connection, output_dir)
        write_csv(
            output_dir / "r2_t03_cell_execution_registry.csv",
            execution_rows,
            [
                "candidate_cell_id",
                "route_id",
                "d",
                "g",
                "status",
                "security_count",
                "component_count",
                "event_count",
                "error",
            ],
        )
        summary = {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "executed_pending_validation",
            "execution_commit": execution_commit,
            "worker_count": workers,
            "baseline_only": baseline_only,
            "cell_count": len(cells),
            "route_count": len(routes),
            "database_path": repo_rel(database, root),
            "database_fingerprint": fingerprint,
            "elapsed_seconds": round(time.time() - started, 6),
            "selection_path_not_independently_confirmed": True,
            "R2-T04_allowed_to_start": False,
            "R3_allowed_to_start": False,
        }
        write_json(output_dir / "r2_t03_experiment_summary.json", summary)
        return summary
    finally:
        connection.close()


def validate_source_readiness(
    config: dict[str, Any], cells: list[dict[str, Any]], *, root: Path = ROOT
) -> tuple[dict[str, Any], list[RouteSpec]]:
    inputs = config["inputs"]
    handoff = _load_json(root / inputs["t02_handoff_path"])
    handoff_validation = _load_json(root / inputs["t02_handoff_validation_path"])
    required_handoff = {
        "scientific_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2-T03_allowed_to_start": True,
        "selection_path_not_independently_confirmed": True,
    }
    for key, expected in required_handoff.items():
        if handoff.get(key) != expected or handoff_validation.get(key) != expected:
            raise R2T03Error(f"t02_handoff_not_authorized:{key}")
    if handoff_validation.get("status") != "passed":
        raise R2T03Error("t02_handoff_validation_not_passed")
    if len(cells) != 72 or len({row["candidate_cell_id"] for row in cells}) != 72:
        raise R2T03Error("candidate_cell_registry_not_exactly_72")
    contract = _load_json(root / inputs["output_contract_path"])
    if set(contract["table_contracts"]) != TABLE_CONTRACT_NAMES:
        raise R2T03Error("t02_output_contract_table_set_mismatch")
    t15_manifest = _load_json(root / inputs["r0_t15_manifest_path"])
    t10_manifest = _load_json(root / inputs["r0_t10_manifest_path"])
    t15_registry = _read_csv(root / inputs["r0_t15_registry_path"])
    file_checks: dict[str, Any] = {}
    for key in ["daily_confirmation", "confirmed_interval"]:
        registered = t15_manifest["outputs"][key]
        path = root / registered["path"]
        _check_file(path, registered["sha256"], file_checks, root)
        table = registered["table"]
        with duckdb.connect(str(path), read_only=True) as con:
            observed = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if observed != registered["row_count"]:
            raise R2T03Error(f"source_row_count_mismatch:{key}")
        file_checks[repo_rel(path, root)]["row_count"] = observed
    routes = _route_specs(cells, t15_registry, inputs, t10_manifest, root)
    for route in routes:
        for path_value in [route.daily_path, route.interval_path]:
            path = root / path_value
            if repo_rel(path, root) not in file_checks:
                expected = _registered_t10_hash(t10_manifest, path_value)
                _check_file(path, expected, file_checks, root)
    report = {
        "task_id": TASK_ID,
        "status": "passed",
        "t02_handoff_status": "passed",
        "candidate_cell_count": len(cells),
        "route_count": len(routes),
        "files": file_checks,
        "available_time_source_field_present": False,
        "available_time_policy": config["semantics"]["available_time_policy"],
        "eligibility_source_field_present": False,
        "eligibility_policy": config["semantics"]["eligibility_policy"],
        "quality_raw_confirmed_fields_present": True,
        "superseded_input_detected": False,
    }
    return report, routes


def _route_specs(
    cells: list[dict[str, Any]],
    t15_registry: list[dict[str, str]],
    inputs: dict[str, str],
    t10_manifest: dict[str, Any],
    root: Path,
) -> list[RouteSpec]:
    unique: dict[str, dict[str, Any]] = {}
    for row in cells:
        unique.setdefault(row["route_id"], row)
    if len(unique) != 8:
        raise R2T03Error("route_registry_not_exactly_8")
    routes = []
    for route_id, row in sorted(unique.items()):
        W = int(row["W"])
        qP, qC, qT, qV = (float(row[k]) for k in ["qP", "qC", "qT", "qV"])
        shared = row["candidate_role"] == "strict_core_reference"
        if shared:
            config_id = f"R0_W{W}_Q20_K3_WEAK_D010"
            entry = t10_manifest["artifacts_by_config"][config_id]
            daily_path = _normalize_path(entry["daily_duckdb_path"])
            interval_path = _normalize_path(entry["interval_duckdb_path"])
            source_id = config_id
            source_kind = "r0_t10_shared_q"
        else:
            matches = [
                candidate
                for candidate in t15_registry
                if int(candidate["W"]) == W
                and int(candidate["K"]) == 3
                and all(
                    abs(float(candidate[key]) - value) < 1e-12
                    for key, value in {
                        "qP": qP,
                        "qC": qC,
                        "qT": qT,
                        "qV": qV,
                    }.items()
                )
                and row["state_line"] in candidate["state_line_role"].split("|")
            ]
            if len(matches) != 1:
                raise R2T03Error(f"primary_route_mapping_not_unique:{route_id}")
            source_id = matches[0]["formal_vector_id"]
            source_kind = "r0_t15_primary_q_vector"
            daily_path = inputs["r0_t15_daily_path"]
            interval_path = inputs["r0_t15_interval_path"]
        for path in [daily_path, interval_path]:
            if not (root / path).is_file():
                raise R2T03Error(f"route_source_missing:{route_id}:{path}")
        routes.append(
            RouteSpec(
                route_id=route_id,
                candidate_role=row["candidate_role"],
                state_line=row["state_line"],
                W=W,
                K=3,
                qP=qP,
                qC=qC,
                qT=qT,
                qV=qV,
                source_kind=source_kind,
                source_id=source_id,
                daily_path=daily_path,
                interval_path=interval_path,
            )
        )
    return routes


def _materialize_route_daily(
    con: duckdb.DuckDBPyConnection, routes: list[RouteSpec], root: Path
) -> None:
    selects = []
    aliases: dict[str, str] = {}
    for index, route in enumerate(routes):
        alias = f"src_{index}"
        aliases.setdefault(route.daily_path, alias)
    for path, alias in aliases.items():
        con.execute(f"ATTACH '{_sql_path(root / path)}' AS {alias} (READ_ONLY)")
    for route in routes:
        alias = aliases[route.daily_path]
        if route.source_kind == "r0_t15_primary_q_vector":
            table = f"{alias}.r0_t15_daily_confirmation_results"
            source_filter = f"formal_vector_id='{route.source_id}'"
            date_col = "trading_date"
        else:
            table = f"{alias}.candidate_daily_state"
            source_filter = f"candidate_config_id='{route.source_id}'"
            date_col = "trading_date"
        available = (
            f"strftime(strptime({date_col}, '%Y%m%d'), '%Y-%m-%d') || 'T15:00:00+08:00'"
        )
        selects.append(
            f"""
            SELECT '{route.route_id}'::VARCHAR AS route_id,
                   security_id,
                   CAST(strptime({date_col}, '%Y%m%d') AS DATE) AS trade_date,
                   {available} AS available_time,
                   validity_status='valid' AS eligible,
                   CASE
                     WHEN validity_status='valid' THEN 'valid'
                     WHEN validity_status='blocked' THEN 'blocked'
                     WHEN validity_status='diagnostic_required' THEN 'diagnostic_required'
                     ELSE 'unknown'
                   END::VARCHAR AS quality_state,
                   raw_state,
                   coalesce(confirmed_state, false)::BOOLEAN AS confirmed_state,
                   CASE WHEN confirmation_start_date IS NULL THEN NULL
                        ELSE CAST(strptime(confirmation_start_date, '%Y%m%d') AS DATE)
                   END AS confirmed_start_date,
                   CASE WHEN confirmation_date={date_col} THEN {available} ELSE NULL END
                     AS confirmation_time,
                   (validity_status='valid' AND coalesce(confirmed_state,false))::BOOLEAN
                     AS state_risk_set_eligible
            FROM {table}
            WHERE {source_filter} AND state_name='{route.state_line}'
            """
        )
    con.execute("CREATE TABLE route_daily AS " + " UNION ALL ".join(selects))
    con.execute(
        "CREATE UNIQUE INDEX route_daily_pk ON route_daily(route_id,security_id,trade_date)"
    )
    if con.execute("SELECT count(*) FROM route_daily").fetchone()[0] == 0:
        raise R2T03Error("route_daily_all_zero")


def _execute_routes(
    con: duckdb.DuckDBPyConnection,
    routes: list[RouteSpec],
    cells: list[dict[str, Any]],
    *,
    heartbeat_interval: int,
) -> list[dict[str, Any]]:
    cell_by_route: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        cell_by_route.setdefault(cell["route_id"], []).append(cell)
    execution: dict[str, dict[str, Any]] = {
        row["candidate_cell_id"]: {
            "candidate_cell_id": row["candidate_cell_id"],
            "route_id": row["route_id"],
            "d": row["d"],
            "g": row["g"],
            "status": "running",
            "security_count": 0,
            "component_count": 0,
            "event_count": 0,
            "error": "",
        }
        for row in cells
    }
    for route in routes:
        processed = 0
        buffers = _new_write_buffers()
        for security_id, rows in _iter_security_timelines(con, route.route_id):
            _process_security(
                route,
                security_id,
                rows,
                cell_by_route[route.route_id],
                execution,
                buffers,
            )
            processed += 1
            if processed % heartbeat_interval == 0:
                _flush_write_buffers(con, buffers)
                print(
                    f"heartbeat route={route.route_id} securities={processed}",
                    flush=True,
                )
        _flush_write_buffers(con, buffers)
        for cell in cell_by_route[route.route_id]:
            execution[cell["candidate_cell_id"]]["status"] = "completed"
    return [execution[key] for key in sorted(execution)]


def _iter_security_timelines(
    con: duckdb.DuckDBPyConnection, route_id: str
) -> Iterator[tuple[str, list[tuple[Any, ...]]]]:
    cursor = con.cursor().execute(
        """
        SELECT security_id, trade_date, available_time, eligible, quality_state,
               raw_state, confirmed_state, confirmed_start_date, confirmation_time
        FROM route_daily WHERE route_id=? ORDER BY security_id, trade_date
        """,
        [route_id],
    )
    current_security = None
    rows: list[tuple[Any, ...]] = []
    try:
        while True:
            batch = cursor.fetchmany(20000)
            if not batch:
                break
            for row in batch:
                if current_security is None:
                    current_security = row[0]
                if row[0] != current_security:
                    yield current_security, rows
                    current_security = row[0]
                    rows = []
                rows.append(row)
        if current_security is not None:
            yield current_security, rows
    finally:
        cursor.close()


def _process_security(
    route: RouteSpec,
    security_id: str,
    source_rows: list[tuple[Any, ...]],
    cells: list[dict[str, Any]],
    execution: dict[str, dict[str, Any]],
    buffers: dict[str, list[tuple[Any, ...]]],
) -> None:
    daily = [
        DailyInput(
            security_id=security_id,
            trade_date=row[1].isoformat(),
            available_time=_iso_time(row[2]),
            eligible=bool(row[3]),
            quality_state=str(row[4]),
            raw_state=row[5],
        )
        for row in source_rows
    ]
    expected_dates = [row.trade_date for row in daily]
    timeline, confirmation_ledger = replay_confirmation(
        daily, expected_dates, security_id=security_id
    )
    upstream_confirmed = [bool(row[6]) for row in source_rows]
    replayed = [bool(row["confirmed_state"]) for row in timeline]
    if upstream_confirmed != replayed:
        mismatch = next(
            index
            for index, (left, right) in enumerate(zip(upstream_confirmed, replayed))
            if left != right
        )
        raise R2T03Error(
            f"upstream_confirmation_replay_mismatch:{route.route_id}:"
            f"{security_id}:{expected_dates[mismatch]}"
        )
    intervals = atomic_intervals(timeline)
    interval_rows = []
    for ordinal, interval in enumerate(intervals, start=1):
        interval_rows.append(
            (
                route.route_id,
                security_id,
                f"{route.route_id}|{security_id}|{ordinal:05d}",
                interval["start_date"],
                interval["end_date"],
                interval["confirmed_day_count"],
                interval["termination_reason"],
            )
        )
    buffers["route_atomic_interval"].extend(interval_rows)
    for cell in sorted(cells, key=lambda row: row["candidate_cell_id"]):
        cell_id = cell["candidate_cell_id"]
        d, g = int(cell["d"]), int(cell["g"])
        components, zones, zone_ledger = group_event_zones(
            timeline, intervals, d, g, candidate_cell_id=cell_id
        )
        component_rows = [
            (
                cell_id,
                security_id,
                component["component_id"],
                component["start_date"],
                component["end_date"],
                component["confirmed_day_count"],
                component["qualified"],
                component["event_qualification_time"] or None,
            )
            for component in components
        ]
        buffers["qualified_component"].extend(component_rows)
        membership_rows, event_rows = _zone_rows(
            route, cell_id, security_id, timeline, zones
        )
        buffers["event_zone"].extend(event_rows)
        buffers["event_zone_membership_daily"].extend(membership_rows)
        bridge_rows = _bridge_rows(
            route, cell_id, security_id, timeline, components, zones, d, g
        )
        buffers["event_zone_bridge_segment"].extend(bridge_rows)
        transitions = confirmation_ledger + zone_ledger
        transition_rows = [
            (
                cell_id,
                security_id,
                ordinal,
                item["from_state"],
                item["to_state"],
                item["reason_code"],
            )
            for ordinal, item in enumerate(transitions, start=1)
            if item["from_state"] != "ANY" and item["to_state"] != "FAIL_CLOSED"
        ]
        buffers["transition_profile"].extend(transition_rows)
        item = execution[cell_id]
        item["security_count"] += 1
        item["component_count"] += len(components)
        item["event_count"] += len(zones)


def _new_write_buffers() -> dict[str, list[tuple[Any, ...]]]:
    return {
        table: []
        for table in [
            "route_atomic_interval",
            "qualified_component",
            "event_zone",
            "event_zone_membership_daily",
            "event_zone_bridge_segment",
            "transition_profile",
        ]
    }


def _flush_write_buffers(
    con: duckdb.DuckDBPyConnection, buffers: dict[str, list[tuple[Any, ...]]]
) -> None:
    for table, rows in buffers.items():
        if rows:
            temp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    prefix=f"r2_t03_{table}_",
                    suffix=".csv",
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    writer = csv.writer(handle, lineterminator="\n")
                    writer.writerows(rows)
                con.execute(
                    f"COPY {table} FROM '{_sql_path(temp_path)}' "
                    "(FORMAT CSV, HEADER false, NULL '')"
                )
                rows.clear()
            finally:
                if temp_path and temp_path.exists():
                    temp_path.unlink()


def _zone_rows(
    route: RouteSpec,
    cell_id: str,
    security_id: str,
    timeline: list[dict[str, Any]],
    zones: list[dict[str, Any]],
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    membership_output = []
    event_output = []
    by_index = {row["row_index"]: row for row in timeline}
    for zone in zones:
        member_rows = [
            row for row in zone["membership_rows"] if row["event_zone_member"]
        ]
        confirmed_count = sum(
            bool(by_index[row["row_index"]]["confirmed_state"]) for row in member_rows
        )
        span = len(member_rows)
        density = confirmed_count / span if span else 0.0
        reason = _zone_reason(zone)
        event_output.append(
            (
                cell_id,
                security_id,
                zone["scan_event_id"],
                zone["first_component_id"],
                zone["component_count"],
                zone["bridge_count"],
                zone["bridged_day_count"],
                zone["raw_false_bridge_segment_count"],
                zone["raw_false_bridged_day_count"],
                zone["preconfirmation_gap_day_count"],
                zone["total_nonconfirmed_gap_day_count"],
                zone["max_raw_false_gap_days"],
                zone["max_total_gap_span_days"],
                confirmed_count,
                span,
                density,
                zone["zone_revision"],
                zone["membership_available_time"],
                zone["zone_finalization_time"] or None,
                zone["status"],
                reason,
            )
        )
        for member in zone["membership_rows"]:
            source = by_index[member["row_index"]]
            state_risk = (
                source["eligible"]
                and source["quality_state"] == "valid"
                and source["confirmed_state"]
            )
            qualified_risk = (
                state_risk
                and member["event_zone_member"]
                and member["component_qualified_as_of"]
                and not member["is_raw_false_bridge"]
                and not member["is_preconfirmation_gap"]
            )
            membership_output.append(
                (
                    cell_id,
                    route.route_id,
                    security_id,
                    source["trade_date"],
                    source["available_time"],
                    member["membership_available_time"],
                    source["eligible"],
                    source["quality_state"],
                    source["raw_state"],
                    source["confirmed_state"],
                    zone["scan_event_id"],
                    member["event_zone_member"],
                    state_risk,
                    member["retrospective_component_member"],
                    member["component_qualified_as_of"],
                    member["is_bridged_gap"],
                    member["is_raw_false_bridge"],
                    member["is_preconfirmation_gap"],
                    member["raw_false_gap_ordinal_as_of"],
                    member["raw_false_gap_count_as_of"],
                    member["membership_available_time"],
                    member["zone_revision_as_of"],
                    member["zone_status_as_of"],
                    member["prequalification_member"],
                    member["unqualified_reentry_member"],
                    qualified_risk,
                )
            )
    return membership_output, event_output


def _bridge_rows(
    route: RouteSpec,
    cell_id: str,
    security_id: str,
    timeline: list[dict[str, Any]],
    components: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    d: int,
    g: int,
) -> list[tuple[Any, ...]]:
    qualified = [component for component in components if component["qualified"]]
    component_zone: dict[str, str] = {}
    for zone in zones:
        membership_dates = {
            row["trade_date"]
            for row in zone["membership_rows"]
            if row["retrospective_component_member"]
        }
        for component in qualified:
            if component["start_date"] in membership_dates:
                component_zone[component["component_id"]] = zone["scan_event_id"]
    output = []
    for ordinal, (left, right) in enumerate(zip(qualified, qualified[1:]), start=1):
        gap_rows = _rows_between(timeline, left["end_index"], right["start_index"])
        if not gap_rows:
            continue
        gap = _gap_segment(gap_rows, g)
        decisive = _earliest_gap_decision(gap_rows, gap)
        same_zone = component_zone.get(left["component_id"]) == component_zone.get(
            right["component_id"]
        )
        intervening = [
            component
            for component in components
            if left["end_index"] < component["start_index"] < right["start_index"]
            and not component["qualified"]
        ]
        if same_zone:
            reason = "bridge_accepted"
            decision_time = right["event_qualification_time"]
        elif intervening:
            reason = "intervening_unqualified_component"
            decision_time = right["event_qualification_time"]
        elif decisive and decisive["status"] == "FINALIZED_WITH_QUALITY_BREAK":
            reason = "quality_break"
            decision_time = decisive["available_time"]
        elif gap["exceeds_g"]:
            reason = "raw_false_gap_exceeds_g"
            decision_time = gap["g_plus_one_raw_false_time"]
        else:
            reason = "sample_end_censoring"
            decision_time = gap_rows[-1]["available_time"]
        event_id = component_zone.get(left["component_id"])
        if not event_id:
            continue
        output.append(
            (
                cell_id,
                route.route_id,
                security_id,
                event_id,
                f"{event_id}|bridge|{ordinal:03d}",
                ordinal,
                left["component_id"],
                right["component_id"],
                gap_rows[0]["trade_date"],
                gap_rows[-1]["trade_date"],
                3,
                d,
                g,
                gap["raw_false_gap_count"],
                gap["preconfirmation_raw_true_count"],
                gap["total_nonconfirmed_gap_count"],
                same_zone,
                reason,
                decision_time,
                right["event_qualification_time"],
            )
        )
    return output


def _create_output_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE cell_registry(candidate_cell_id VARCHAR PRIMARY KEY, route_id VARCHAR,
          candidate_role VARCHAR, state_line VARCHAR, W INTEGER, K INTEGER,
          qP DOUBLE, qC DOUBLE, qT DOUBLE, qV DOUBLE, d INTEGER, g INTEGER);
        CREATE TABLE route_atomic_interval(route_id VARCHAR, security_id VARCHAR,
          interval_id VARCHAR, start_date DATE, end_date DATE,
          confirmed_day_count INTEGER, termination_reason VARCHAR);
        CREATE TABLE qualified_component(candidate_cell_id VARCHAR, security_id VARCHAR,
          component_id VARCHAR, start_date DATE, end_date DATE,
          confirmed_day_count INTEGER, qualified BOOLEAN,
          event_qualification_time TIMESTAMPTZ);
        CREATE TABLE event_zone(candidate_cell_id VARCHAR, security_id VARCHAR,
          scan_event_id VARCHAR, first_component_id VARCHAR, component_count INTEGER,
          bridge_count INTEGER, bridged_day_count INTEGER,
          raw_false_bridge_segment_count INTEGER, raw_false_bridged_day_count INTEGER,
          preconfirmation_gap_day_count INTEGER, total_nonconfirmed_gap_day_count INTEGER,
          max_raw_false_gap_days INTEGER, max_total_gap_span_days INTEGER,
          confirmed_day_count INTEGER, zone_span_days INTEGER, confirmed_density DOUBLE,
          zone_revision INTEGER, membership_available_time TIMESTAMPTZ,
          zone_finalization_time TIMESTAMPTZ, status VARCHAR,
          exit_or_censor_reason VARCHAR);
        CREATE TABLE event_zone_membership_daily(candidate_cell_id VARCHAR, route_id VARCHAR,
          security_id VARCHAR, trade_date DATE, available_time TIMESTAMPTZ,
          evaluation_time TIMESTAMPTZ, eligible BOOLEAN, quality_state VARCHAR,
          raw_state BOOLEAN, confirmed_state BOOLEAN, scan_event_id VARCHAR,
          event_zone_member BOOLEAN, state_risk_set_eligible BOOLEAN,
          retrospective_component_member BOOLEAN, component_qualified_as_of BOOLEAN,
          is_bridged_gap BOOLEAN, is_raw_false_bridge BOOLEAN,
          is_preconfirmation_gap BOOLEAN, raw_false_gap_ordinal_as_of INTEGER,
          raw_false_gap_count_as_of INTEGER, membership_available_time TIMESTAMPTZ,
          zone_revision_as_of INTEGER, zone_status_as_of VARCHAR,
          prequalification_member BOOLEAN, unqualified_reentry_member BOOLEAN,
          qualified_event_risk_set_eligible BOOLEAN);
        CREATE TABLE event_zone_bridge_segment(candidate_cell_id VARCHAR, route_id VARCHAR,
          security_id VARCHAR, scan_event_id VARCHAR, bridge_segment_id VARCHAR,
          segment_ordinal INTEGER, left_component_id VARCHAR, right_component_id VARCHAR,
          segment_start_date DATE, segment_end_date DATE, K INTEGER, d INTEGER, g INTEGER,
          raw_false_gap_day_count INTEGER, preconfirmation_gap_day_count INTEGER,
          total_nonconfirmed_gap_day_count INTEGER, merge_accepted BOOLEAN,
          decision_reason VARCHAR, decision_available_time TIMESTAMPTZ,
          membership_available_time TIMESTAMPTZ);
        CREATE TABLE transition_profile(candidate_cell_id VARCHAR, security_id VARCHAR,
          transition_ordinal INTEGER, from_state VARCHAR, to_state VARCHAR,
          reason_code VARCHAR);
        """
    )


def _insert_cell_registry(
    con: duckdb.DuckDBPyConnection, cells: list[dict[str, Any]]
) -> None:
    con.executemany(
        "INSERT INTO cell_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            tuple(
                row[key]
                for key in [
                    "candidate_cell_id",
                    "route_id",
                    "candidate_role",
                    "state_line",
                    "W",
                    "K",
                    "qP",
                    "qC",
                    "qT",
                    "qV",
                    "d",
                    "g",
                ]
            )
            for row in cells
        ],
    )


def _create_atomic_daily_view(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE VIEW atomic_confirmed_daily AS
        SELECT c.candidate_cell_id, r.route_id, r.security_id, r.trade_date,
               r.available_time, r.raw_state, r.confirmed_state,
               r.confirmed_start_date, r.confirmation_time,
               r.state_risk_set_eligible
        FROM route_daily r JOIN cell_registry c USING(route_id)
        """
    )


def _create_atomic_interval_view(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE VIEW atomic_confirmed_interval AS
        SELECT c.candidate_cell_id, i.* FROM route_atomic_interval i
        JOIN cell_registry c USING(route_id)
        """
    )


def _create_profiles_and_comparisons(con: duckdb.DuckDBPyConnection) -> None:
    from src.r2.r2_t03_metrics import create_metric_tables

    create_metric_tables(con)


def _export_compact_tables(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    exports = {
        "atomic_baseline_profile": "r2_t03_atomic_baseline_profile.csv",
        "d_qualification_profile": "r2_t03_d_qualification_profile.csv",
        "dg_event_zone_profile": "r2_t03_dg_event_zone_profile.csv",
        "transition_aggregate_profile": "r2_t03_transition_profile.csv",
        "strict_core_shell_profile": "r2_t03_strict_core_shell_profile.csv",
        "window_overlap_comparison": "r2_t03_window_overlap_profile.csv",
        "parameter_response_audit": "r2_t03_parameter_response_audit.csv",
        "metric_results": "r2_t03_metric_results.csv",
    }
    for table, name in exports.items():
        con.execute(
            f"COPY (SELECT * FROM {table} ORDER BY ALL) "
            f"TO '{_sql_path(output_dir / name)}' (HEADER, DELIMITER ',')"
        )


def _database_fingerprint(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    tables = [
        "route_daily",
        "route_atomic_interval",
        "qualified_component",
        "event_zone",
        "event_zone_membership_daily",
        "event_zone_bridge_segment",
        "transition_profile",
    ]
    result = {}
    for table in tables:
        columns = [
            row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
        ]
        quoted = ",".join(f'"{column}"' for column in columns)
        row_count, xor_hash = con.execute(
            f"SELECT count(*), bit_xor(hash({quoted})) FROM {table}"
        ).fetchone()
        result[table] = {
            "row_count": row_count,
            "hash_xor_uint64": int(xor_hash or 0),
        }
    return result


def _input_binding(
    config: dict[str, Any],
    config_path: Path,
    execution_commit: str,
    readiness: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "execution_commit": execution_commit,
        "config_binding": formal_source_binding(
            config_path, execution_commit, root=root
        ),
        "formal_source_bindings": [
            formal_source_binding(root / path, execution_commit, root=root)
            for path in config["formal_source_paths"]
        ],
        "source_readiness_sha256": sha256_bytes(
            json.dumps(readiness, sort_keys=True, separators=(",", ":")).encode()
        ),
        "python": sys.version,
        "platform": platform.platform(),
        "duckdb": duckdb.__version__,
    }


def _assert_formal_sources_clean(
    config: dict[str, Any], execution_commit: str, root: Path
) -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True
    ).splitlines()
    if status:
        raise R2T03Error(f"formal_run_requires_clean_worktree:{status[0]}")
    for path in config["formal_source_paths"]:
        formal_source_binding(root / path, execution_commit, root=root)


def _read_cells(path: Path) -> list[dict[str, Any]]:
    rows = _read_csv(path)
    for row in rows:
        for key in ["W", "K", "d", "g"]:
            row[key] = int(row[key])
        for key in ["qP", "qC", "qT", "qV"]:
            row[key] = float(row[key])
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R2T03Error(f"expected_json_object:{path}")
    return value


def _check_file(
    path: Path, expected_sha: str, report: dict[str, Any], root: Path
) -> None:
    if not path.is_file():
        raise R2T03Error(f"source_file_missing:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(16 * 1024 * 1024):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha:
        raise R2T03Error(f"source_sha256_mismatch:{path}")
    report[repo_rel(path, root)] = {
        "sha256": actual,
        "size_bytes": path.stat().st_size,
        "status": "passed",
    }


def _registered_t10_hash(manifest: dict[str, Any], path: str) -> str:
    normalized = _normalize_path(path)
    for entry in manifest["artifacts_by_config"].values():
        for prefix in ["daily_duckdb", "interval_duckdb"]:
            if _normalize_path(entry[f"{prefix}_path"]) == normalized:
                return entry[f"{prefix}_sha256"]
    raise R2T03Error(f"r0_t10_path_not_registered:{path}")


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/")


def _zone_reason(zone: dict[str, Any]) -> str:
    if zone["status"] == "FINALIZED_WITH_QUALITY_BREAK":
        return "quality_break"
    if zone["status"] == "RIGHT_CENSORED":
        return "sample_end_censoring"
    if zone["status"] == "FINALIZED":
        return "natural_finalization"
    return "open_zone"


def _iso_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")
