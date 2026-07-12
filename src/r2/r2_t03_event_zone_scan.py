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
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
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
    if value.get("config_version") != "r2_t03_four_route_event_zone_scan.v2":
        raise R2T03Error("successor_formal_run_requires_v2_config")
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
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise R2T03Error("formal_run_output_dir_not_empty")
    config = load_config(config_path)
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
        raise R2T03Error("formal_run_output_dir_not_empty")
    connection = duckdb.connect(str(database))
    try:
        connection.execute(f"SET threads={int(config['runtime']['duckdb_threads'])}")
        connection.execute(
            f"SET memory_limit='{config['runtime']['duckdb_memory_limit']}'"
        )
        connection.execute(f"SET TimeZone='{config['runtime']['timezone']}'")
        _create_output_schema(connection)
        _insert_cell_registry(connection, cells)
        _materialize_route_source_daily(connection, routes, root)
        _materialize_authoritative_expected_keys(connection, config, root)
        _materialize_canonical_daily_and_intervals(connection)
        _materialize_authorized_upstream_intervals(connection, config, root)
        _bind_dense_interval_lineage(connection)
        _assert_canonical_daily(connection)
        _assert_upstream_interval_reconciliation(connection)
        _create_atomic_daily_view(connection)
        _create_atomic_interval_view(connection)
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
        fingerprint = _database_fingerprint(connection)
        config_sha = _actual_sha256(config_path)
        readiness_sha = _actual_sha256(output_dir / "r2_t03_source_readiness.json")
        input_binding_sha = _actual_sha256(output_dir / "r2_t03_input_binding.json")
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
                    "execution_commit": execution_commit,
                    "config_sha256": config_sha,
                    "source_readiness_sha256": readiness_sha,
                    "input_binding_sha256": input_binding_sha,
                    "route_source_daily_row_count": connection.execute(
                        "SELECT count(*) FROM route_source_daily"
                    ).fetchone()[0],
                    "canonical_route_daily_row_count": connection.execute(
                        "SELECT count(*) FROM route_daily"
                    ).fetchone()[0],
                    "expected_empty_row_count": connection.execute(
                        "SELECT count(*) FROM route_daily WHERE NOT source_row_present"
                    ).fetchone()[0],
                    "dense_interval_count": connection.execute(
                        "SELECT count(*) FROM route_atomic_interval"
                    ).fetchone()[0],
                    "source_interval_count": connection.execute(
                        "SELECT count(*) FROM authorized_upstream_interval"
                    ).fetchone()[0],
                    "post_validation_fingerprint": None,
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
            "config_sha256": config_sha,
            "source_readiness_sha256": readiness_sha,
            "input_binding_sha256": input_binding_sha,
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
    adapter = adapter_contract_status(config, root=root)
    if adapter["availability_adapter_status"] != "resolved_research_policy":
        raise R2T03Error("availability_adapter_status:unresolved_upstream_contract")
    if adapter["expected_key_adapter_status"] != "resolved_upstream_adapter":
        raise R2T03Error("expected_key_adapter_status:unresolved_upstream_contract")
    if adapter["interval_reconciliation_adapter_status"] != "resolved_upstream_adapter":
        raise R2T03Error(
            "interval_reconciliation_adapter_status:unresolved_upstream_contract"
        )
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
    binding_input_keys = [
        "t02_handoff_path",
        "t02_handoff_validation_path",
        "cell_registry_path",
        "output_contract_path",
        "metric_dictionary_path",
        "hard_gate_registry_path",
        "transition_registry_path",
        "event_zone_contract_path",
        "risk_set_contract_path",
        "r0_t15_manifest_path",
        "r0_t15_registry_path",
        "r0_t10_manifest_path",
    ]
    for key in binding_input_keys:
        path = root / inputs[key]
        _record_actual_file(path, file_checks, root)
    expected_contract = _load_json(root / config["expected_key_adapter_contract_path"])
    _check_file(
        root / expected_contract["source_manifest_path"],
        expected_contract["source_manifest_sha256"],
        file_checks,
        root,
    )
    expected_db = root / expected_contract["source_duckdb_path"]
    _check_file(
        expected_db, expected_contract["source_duckdb_sha256"], file_checks, root
    )
    expected_source = expected_contract["expected_skeleton_source"]
    with duckdb.connect(str(expected_db), read_only=True) as con:
        expected_count, expected_security_count, expected_min, expected_max = (
            con.execute(
                f"SELECT count(*),count(DISTINCT {expected_source['security_id_field']}),"
                f"min({expected_source['trade_date_field']}),max({expected_source['trade_date_field']}) "
                f"FROM {expected_source['table']} WHERE {expected_source['trade_date_field']} "
                f"BETWEEN ? AND ?",
                [expected_contract["date_min"], expected_contract["date_max"]],
            ).fetchone()
        )
    file_checks[repo_rel(expected_db, root)]["tables"] = {
        expected_source["table"]: {
            "row_count": expected_count,
            "security_count": expected_security_count,
            "date_min": expected_min,
            "date_max": expected_max,
        }
    }
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
    _validate_interval_contract_sources(config, routes, file_checks, root)
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
        **adapter,
        "superseded_input_detected": _superseded_input_detected(
            inputs, handoff, handoff_validation, routes
        ),
    }
    if report["superseded_input_detected"]:
        raise R2T03Error("superseded_input_detected")
    return report, routes


def adapter_contract_status(
    config: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    """Bind adapters to upstream contracts; configuration assertions are not evidence."""
    semantics = config.get("semantics", {})
    availability_contract = config.get("availability_policy_contract_path", "")
    expected_key_contract = config.get("expected_key_adapter_contract_path", "")
    expected_validation = config.get("expected_key_adapter_validation_path", "")
    interval_contract = config.get("interval_adapter_contract_path", "")
    interval_validation = config.get("interval_adapter_validation_path", "")

    def passed(path: str) -> bool:
        if not path or not (root / path).is_file():
            return False
        return _load_json(root / path).get("status") == "passed"

    availability_resolved = bool(
        semantics.get("availability_adapter_status") == "resolved_research_policy"
        and availability_contract
        and (root / availability_contract).is_file()
        and _load_json(root / availability_contract).get("policy_id")
        == "r2_t03_eod_close_1500_asia_shanghai.v1"
    )
    expected_resolved = bool(
        semantics.get("expected_key_adapter_status") == "resolved_upstream_adapter"
        and expected_key_contract
        and (root / expected_key_contract).is_file()
        and passed(str(expected_validation))
    )
    if expected_resolved:
        contract = _load_json(root / str(expected_key_contract))
        validation = _load_json(root / str(expected_validation))
        expected_resolved = all(
            _actual_sha256(root / contract[key.replace("_sha256", "_path")])
            == contract[key]
            == validation.get(key)
            for key in ("source_manifest_sha256", "source_duckdb_sha256")
        )
    interval_resolved = bool(
        semantics.get("interval_reconciliation_adapter_status")
        == "resolved_upstream_adapter"
        and interval_contract
        and (root / interval_contract).is_file()
        and passed(str(interval_validation))
    )
    if interval_resolved:
        contract = _load_json(root / str(interval_contract))
        validation = _load_json(root / str(interval_validation))
        interval_resolved = bool(
            validation.get("adapter_id") == contract.get("adapter_id")
            and all(
                _actual_sha256(root / row["interval_path"])
                == row["source_artifact_sha256"]
                for row in contract.get("route_mappings", [])
            )
        )
    return {
        "availability_adapter_status": (
            "resolved_research_policy"
            if availability_resolved
            else "unresolved_upstream_contract"
        ),
        "availability_upstream_contract_path": str(availability_contract),
        "expected_key_adapter_status": (
            "resolved_upstream_adapter"
            if expected_resolved
            else "unresolved_upstream_contract"
        ),
        "expected_key_upstream_contract_path": str(expected_key_contract),
        "interval_reconciliation_adapter_status": (
            "resolved_upstream_adapter"
            if interval_resolved
            else "unresolved_upstream_contract"
        ),
        "interval_reconciliation_upstream_contract_path": str(interval_contract),
    }


def build_expected_security_dates(
    security_ids: Iterable[str],
    trading_dates: Iterable[str],
    applicable_keys: Iterable[tuple[str, str]],
) -> dict[str, list[str]]:
    """Build security x expected-date keys from an authoritative applicability set.

    Neither the security universe nor the date set may be inferred from observed route rows.
    The explicit applicability keys bind listing/delisting and route-universe policy.
    """
    securities = set(security_ids)
    dates = set(trading_dates)
    keys = set(applicable_keys)
    if any(security not in securities or date not in dates for security, date in keys):
        raise R2T03Error("expected_key_outside_authoritative_domain")
    return {
        security: sorted(
            date for key_security, date in keys if key_security == security
        )
        for security in sorted(securities)
    }


def reconcile_atomic_interval_rows(
    rebuilt: Iterable[Mapping[str, Any]], upstream: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Exact row-level reconciliation required before a successor formal run."""
    fields = (
        "route_id",
        "security_id",
        "start_date",
        "end_date",
        "confirmed_day_count",
        "termination_reason",
    )

    def canonical(rows: Iterable[Mapping[str, Any]]) -> list[tuple[Any, ...]]:
        output = []
        for row in rows:
            missing = [field for field in fields if field not in row]
            if missing:
                raise R2T03Error(f"interval_reconciliation_missing_field:{missing[0]}")
            output.append(tuple(row[field] for field in fields))
        return sorted(output)

    left, right = Counter(canonical(rebuilt)), Counter(canonical(upstream))
    missing, unexpected = right - left, left - right
    return {
        "status": "passed" if not missing and not unexpected else "failed",
        "rebuilt_row_count": sum(left.values()),
        "upstream_row_count": sum(right.values()),
        "missing_multiset_row_count": sum(missing.values()),
        "unexpected_multiset_row_count": sum(unexpected.values()),
        "missing_from_rebuilt": sorted(missing.elements()),
        "unexpected_rebuilt": sorted(unexpected.elements()),
    }


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


def _materialize_route_source_daily(
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
    con.execute("CREATE TABLE route_source_daily AS " + " UNION ALL ".join(selects))
    con.execute(
        "ALTER TABLE route_source_daily ADD COLUMN expected_empty_reason VARCHAR;"
        "ALTER TABLE route_source_daily ADD COLUMN source_row_present BOOLEAN DEFAULT true"
    )
    con.execute(
        "CREATE UNIQUE INDEX route_source_daily_pk ON route_source_daily(route_id,security_id,trade_date)"
    )
    if con.execute("SELECT count(*) FROM route_source_daily").fetchone()[0] == 0:
        raise R2T03Error("route_source_daily_all_zero")


def _materialize_authoritative_expected_keys(
    con: duckdb.DuckDBPyConnection, config: Mapping[str, Any], root: Path
) -> None:
    """Load route/security/date keys from an upstream-authorized source, never observations."""
    contract_path = str(config.get("expected_key_adapter_contract_path", ""))
    if not contract_path:
        raise R2T03Error("expected_key_adapter_status:unresolved_upstream_contract")
    contract = _load_json(root / contract_path)
    source = contract["expected_skeleton_source"]
    path = root / str(source["source_duckdb_path"])
    if not path.is_file():
        raise R2T03Error("expected_key_source_missing")
    con.execute(f"ATTACH '{_sql_path(path)}' AS expected_key_source (READ_ONLY)")
    con.execute(
        f"""CREATE TABLE base_expected_security_date AS
        SELECT {source["security_id_field"]}::VARCHAR security_id,
               CAST(strptime({source["trade_date_field"]}::VARCHAR,'%Y%m%d') AS DATE) trade_date,
               'applicable'::VARCHAR applicability_status,
               'd2_expected_security_dates'::VARCHAR source_status
        FROM expected_key_source.{source["table"]}
        WHERE {source["trade_date_field"]} BETWEEN '{contract["date_min"]}' AND '{contract["date_max"]}';
        CREATE TABLE expected_route_key AS
        SELECT r.route_id,b.security_id,b.trade_date
        FROM (SELECT DISTINCT route_id FROM cell_registry) r
        CROSS JOIN base_expected_security_date b"""
    )
    duplicates = con.execute(
        "SELECT count(*)-count(DISTINCT (route_id,security_id,trade_date)) FROM expected_route_key"
    ).fetchone()[0]
    if duplicates:
        raise R2T03Error("expected_key_source_duplicate_key")
    unexpected = con.execute(
        """SELECT r.route_id,r.security_id,r.trade_date FROM route_source_daily r
        LEFT JOIN expected_route_key e USING(route_id,security_id,trade_date)
        WHERE e.trade_date IS NULL ORDER BY 1,2,3 LIMIT 1"""
    ).fetchone()
    if unexpected:
        raise R2T03Error(
            "observed_row_outside_expected_key_contract:"
            + ":".join(str(value) for value in unexpected)
        )
    con.execute(
        """INSERT INTO route_source_daily
        SELECT e.route_id,e.security_id,e.trade_date,
               strftime(e.trade_date,'%Y-%m-%d') || 'T15:00:00+08:00',
               false,'expected_empty',NULL,false,NULL,NULL,false,
               CASE s.trading_status WHEN 'suspended' THEN 'suspended'
                    WHEN 'listing_pause' THEN 'listing_pause'
                    ELSE error('unclassified_expected_empty:' || coalesce(s.trading_status,'NULL')) END,
               false
        FROM expected_route_key e LEFT JOIN route_source_daily r USING(route_id,security_id,trade_date)
        LEFT JOIN expected_key_source.d2_source_status s
          ON s.ts_code=e.security_id AND CAST(strptime(s.trade_date,'%Y%m%d') AS DATE)=e.trade_date
        WHERE r.trade_date IS NULL"""
    )
    remaining = con.execute(
        """SELECT count(*) FROM expected_route_key e LEFT JOIN route_source_daily r
        USING(route_id,security_id,trade_date) WHERE r.trade_date IS NULL"""
    ).fetchone()[0]
    if remaining:
        raise R2T03Error("dense_expected_surface_materialization_incomplete")
    observed = con.execute(
        """SELECT count(*),count(*) FILTER (WHERE NOT source_row_present),
        count(*) FILTER (WHERE expected_empty_reason='suspended'),
        count(*) FILTER (WHERE expected_empty_reason='listing_pause')
        FROM route_source_daily"""
    ).fetchone()
    if contract.get("adapter_id") == "r2_t03_expected_key_adapter.v1" and observed != (
        14008528,
        162376,
        154264,
        8112,
    ):
        raise R2T03Error(f"expected_empty_fixed_aggregate_mismatch:{observed!r}")


def _materialize_canonical_daily_and_intervals(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Replay K=3 exactly once per route/security over the complete expected surface."""
    daily_rows: list[tuple[Any, ...]] = []
    interval_rows: list[tuple[Any, ...]] = []
    for route_id, security_id in con.execute(
        "SELECT DISTINCT route_id,security_id FROM route_source_daily ORDER BY 1,2"
    ).fetchall():
        source = con.execute(
            """SELECT trade_date,CAST(available_time AS VARCHAR),eligible,quality_state,raw_state,
            expected_empty_reason,source_row_present FROM route_source_daily
            WHERE route_id=? AND security_id=? ORDER BY trade_date""",
            [route_id, security_id],
        ).fetchall()
        dates = [row[0].isoformat() for row in source]
        inputs = [
            DailyInput(
                security_id=security_id,
                trade_date=row[0].isoformat(),
                available_time=_iso_time(row[1]),
                eligible=bool(row[2]),
                quality_state=str(row[3]),
                raw_state=row[4],
            )
            for row in source
        ]
        timeline, _ = replay_confirmation(inputs, dates, security_id=security_id)
        for item, raw in zip(timeline, source, strict=True):
            daily_rows.append(
                (
                    route_id,
                    security_id,
                    item["trade_date"],
                    item["available_time"],
                    item["eligible"],
                    item["quality_state"],
                    item["raw_state"],
                    item["confirmed_state"],
                    item["confirmed_start_date"] or None,
                    (
                        item["confirmation_time"]
                        if item["reason_code"] == "k3_confirmation"
                        else None
                    ),
                    item["confirmed_end_date"] or None,
                    item["exit_observation_time"] or None,
                    bool(
                        item["eligible"]
                        and item["quality_state"] == "valid"
                        and item["confirmed_state"]
                    ),
                    item["reason_code"],
                    item["hard_break"],
                    raw[5],
                    raw[6],
                )
            )
        dense_intervals = atomic_intervals(timeline)
        for ordinal, interval in enumerate(dense_intervals, start=1):
            dense_id = hashlib.sha256(
                f"dense-v1|{route_id}|{security_id}|{ordinal}|{interval['start_date']}|{interval['end_date']}".encode()
            ).hexdigest()[:32]
            exit_time = (
                timeline[interval["end_index"] + 1]["available_time"]
                if interval["termination_reason"] != "sample_end_censoring"
                and interval["end_index"] + 1 < len(timeline)
                else timeline[interval["end_index"]]["available_time"]
            )
            interval_rows.append(
                (
                    route_id,
                    security_id,
                    dense_id,
                    None,
                    interval["start_date"],
                    interval["end_date"],
                    interval["confirmed_day_count"],
                    interval["termination_reason"],
                    exit_time,
                    False,
                    False,
                    1,
                )
            )
        if len(daily_rows) >= 100000:
            _copy_rows(con, "route_daily", daily_rows)
        if len(interval_rows) >= 10000:
            _copy_rows(con, "route_atomic_interval", interval_rows)
    _copy_rows(con, "route_daily", daily_rows)
    _copy_rows(con, "route_atomic_interval", interval_rows)


def _copy_rows(
    con: duckdb.DuckDBPyConnection, table: str, rows: list[tuple[Any, ...]]
) -> None:
    if not rows:
        return
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            csv.writer(handle, lineterminator="\n").writerows(rows)
        con.execute(
            f"COPY {table} FROM '{_sql_path(temp_path)}' (FORMAT CSV, HEADER false, NULL '')"
        )
        rows.clear()
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _materialize_authorized_upstream_intervals(
    con: duckdb.DuckDBPyConnection, config: Mapping[str, Any], root: Path
) -> None:
    """Normalize the eight exact R0 interval surfaces without persisting row payloads."""
    contract_path = str(config.get("interval_adapter_contract_path", ""))
    if not contract_path:
        raise R2T03Error(
            "interval_reconciliation_adapter_status:unresolved_upstream_contract"
        )
    contract = _load_json(root / contract_path)
    mappings = contract.get("route_mappings", [])
    if len(mappings) != 8 or len({row["route_id"] for row in mappings}) != 8:
        raise R2T03Error("interval_route_mapping_not_exactly_8")
    selects = []
    for index, mapping in enumerate(mappings):
        path = root / mapping["interval_path"]
        if not path.is_file():
            raise R2T03Error(
                f"authorized_interval_source_missing:{mapping['route_id']}"
            )
        alias = f"interval_adapter_{index}"
        con.execute(f"ATTACH '{_sql_path(path)}' AS {alias} (READ_ONLY)")
        route_id = mapping["route_id"]
        state_line = mapping["state_line"]
        if mapping["source_kind"] == "r0_t10_shared_q":
            selects.append(
                f"""SELECT '{route_id}' route_id,i.security_id,
                i.confirmed_interval_id upstream_source_interval_id,
                CAST(strptime(i.raw_start_date,'%Y%m%d') AS DATE) raw_start_date,
                CAST(strptime(i.confirmed_start_date,'%Y%m%d') AS DATE) confirmed_start_date,
                CAST(strptime(i.interval_end_date,'%Y%m%d') AS DATE) interval_end_date,
                CAST(strptime(i.last_observed_date,'%Y%m%d') AS DATE) last_observed_date,
                i.confirmed_length::INTEGER confirmed_day_count,
                CASE i.termination_type
                  WHEN 'raw_state_false' THEN 'natural_state_exit'
                  WHEN 'end_of_input_open' THEN 'sample_end_censoring'
                  WHEN 'raw_state_blocked' THEN 'quality_interruption'
                  WHEN 'raw_state_diagnostic_required' THEN 'quality_interruption'
                  WHEN 'raw_state_unknown' THEN 'quality_interruption'
                  ELSE error('unregistered_source_termination_reason:' || coalesce(i.termination_type,'NULL'))
                END normalized_termination_reason,
                i.termination_type source_termination_reason,i.is_open_interval,
                '{mapping["source_kind"]}' source_kind,'{mapping["source_artifact_sha256"]}' source_artifact_sha256
                FROM {alias}.candidate_confirmed_interval i
                WHERE i.candidate_config_id='{mapping["source_id"]}' AND i.state_level='{state_line}'"""
            )
        else:
            selects.append(
                f"""SELECT * FROM (WITH source AS (
                  SELECT i.*,(SELECT struct_pack(quality_state:=d.quality_state,raw_state:=d.raw_state)
                    FROM route_source_daily d WHERE d.route_id='{route_id}' AND d.security_id=i.security_id
                    AND d.trade_date=CAST(strptime(i.last_observed_date,'%Y%m%d') AS DATE)
                    LIMIT 1) decision
                  FROM {alias}.r0_t15_confirmed_interval_results i
                  WHERE i.formal_vector_id='{mapping["source_id"]}' AND i.state_name='{state_line}'
                ) SELECT '{route_id}' route_id,security_id,interval_id upstream_source_interval_id,
                CAST(strptime(raw_start_date,'%Y%m%d') AS DATE) raw_start_date,
                CAST(strptime(confirmed_start_date,'%Y%m%d') AS DATE) confirmed_start_date,
                CAST(strptime(interval_end_date,'%Y%m%d') AS DATE) interval_end_date,
                CAST(strptime(last_observed_date,'%Y%m%d') AS DATE) last_observed_date,
                confirmed_duration_observations::INTEGER confirmed_day_count,
                CASE WHEN is_open_interval THEN 'sample_end_censoring'
                     WHEN decision IS NULL THEN error('closed_interval_terminal_decision_missing')
                     WHEN decision.quality_state IN ('blocked','diagnostic_required','unknown') OR decision.raw_state IS NULL THEN 'quality_interruption'
                     WHEN decision.raw_state=false THEN 'natural_state_exit'
                     ELSE error('interval_terminal_decision_not_an_exit') END normalized_termination_reason,
                CASE WHEN is_open_interval THEN 'end_of_input_open'
                     WHEN decision IS NULL THEN error('closed_interval_terminal_decision_missing')
                     WHEN decision.quality_state='blocked' THEN 'raw_state_blocked'
                     WHEN decision.quality_state='diagnostic_required' THEN 'raw_state_diagnostic_required'
                     WHEN decision.quality_state!='valid' OR decision.raw_state IS NULL THEN 'raw_state_unknown'
                     ELSE 'raw_state_false' END source_termination_reason,
                is_open_interval,'{mapping["source_kind"]}' source_kind,
                '{mapping["source_artifact_sha256"]}' source_artifact_sha256 FROM source)"""
            )
    con.execute(
        "CREATE TABLE authorized_upstream_interval AS " + " UNION ALL ".join(selects)
    )


def _assert_upstream_interval_reconciliation(con: duckdb.DuckDBPyConnection) -> None:
    ambiguous = con.execute(
        """SELECT r.route_id,r.security_id,r.interval_id,count(*) n
        FROM route_atomic_interval r JOIN authorized_upstream_interval u
          ON r.route_id=u.route_id AND r.security_id=u.security_id
         AND r.start_date>=u.raw_start_date AND r.end_date<=u.interval_end_date
        GROUP BY 1,2,3 HAVING count(*)<>1 LIMIT 1"""
    ).fetchone()
    unmapped = con.execute(
        """SELECT r.route_id,r.security_id,r.interval_id FROM route_atomic_interval r
        WHERE NOT EXISTS (SELECT 1 FROM authorized_upstream_interval u
          WHERE r.route_id=u.route_id AND r.security_id=u.security_id
            AND r.start_date>=u.raw_start_date AND r.end_date<=u.interval_end_date) LIMIT 1"""
    ).fetchone()
    unaffected_mismatch = con.execute(
        """SELECT u.route_id,u.security_id,u.upstream_source_interval_id
        FROM authorized_upstream_interval u
        WHERE NOT EXISTS (SELECT 1 FROM route_daily d WHERE d.route_id=u.route_id
          AND d.security_id=u.security_id AND d.quality_state='expected_empty'
          AND d.trade_date BETWEEN u.raw_start_date AND u.interval_end_date)
        AND NOT EXISTS (SELECT 1 FROM route_daily d WHERE d.route_id=u.route_id
          AND d.security_id=u.security_id AND d.quality_state='expected_empty'
          AND d.trade_date>u.interval_end_date AND d.trade_date<=u.last_observed_date)
        AND NOT EXISTS (SELECT 1 FROM route_atomic_interval r WHERE r.route_id=u.route_id
          AND r.security_id=u.security_id AND r.start_date=u.confirmed_start_date
          AND r.end_date=u.interval_end_date AND r.confirmed_day_count=u.confirmed_day_count
          AND r.termination_reason=u.normalized_termination_reason) LIMIT 1"""
    ).fetchone()
    if ambiguous or unmapped or unaffected_mismatch:
        raise R2T03Error(
            "dense_interval_source_reconciliation_failed:"
            f"ambiguous={ambiguous!r}:unmapped={unmapped!r}:"
            f"unaffected_mismatch={unaffected_mismatch!r}"
        )


def _bind_dense_interval_lineage(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TEMP TABLE dense_lineage AS
        WITH candidates AS (
          SELECT r.route_id,r.security_id,r.interval_id,u.upstream_source_interval_id,
            EXISTS(SELECT 1 FROM route_source_daily d WHERE d.route_id=u.route_id
              AND d.security_id=u.security_id AND NOT d.source_row_present
              AND d.trade_date BETWEEN u.raw_start_date AND u.interval_end_date) geometry_affected,
            EXISTS(SELECT 1 FROM route_source_daily d WHERE d.route_id=u.route_id
              AND d.security_id=u.security_id AND NOT d.source_row_present
              AND d.trade_date>u.interval_end_date AND d.trade_date<=u.last_observed_date) termination_affected
          FROM route_atomic_interval r JOIN authorized_upstream_interval u
            ON r.route_id=u.route_id AND r.security_id=u.security_id
           AND r.start_date>=u.raw_start_date AND r.end_date<=u.interval_end_date
        ), unique_map AS (
          SELECT *,count(*) OVER (PARTITION BY route_id,security_id,interval_id) mapping_count
          FROM candidates
        ) SELECT route_id,security_id,interval_id,upstream_source_interval_id,
          geometry_affected,termination_affected,
          row_number() OVER (PARTITION BY route_id,security_id,upstream_source_interval_id
                             ORDER BY interval_id) dense_fragment_ordinal,
          mapping_count FROM unique_map"""
    )
    bad = con.execute(
        "SELECT count(*) FROM dense_lineage WHERE mapping_count<>1"
    ).fetchone()[0]
    unmapped = con.execute(
        """SELECT count(*) FROM route_atomic_interval r LEFT JOIN dense_lineage d
        USING(route_id,security_id,interval_id) WHERE d.interval_id IS NULL"""
    ).fetchone()[0]
    if bad or unmapped:
        raise R2T03Error(f"dense_interval_lineage_mapping_failed:{bad}:{unmapped}")
    con.execute(
        """UPDATE route_atomic_interval r SET
          upstream_source_interval_id=d.upstream_source_interval_id,
          source_geometry_affected=d.geometry_affected,
          source_termination_affected=d.termination_affected,
          dense_fragment_ordinal=d.dense_fragment_ordinal
        FROM dense_lineage d WHERE r.route_id=d.route_id AND r.security_id=d.security_id
          AND r.interval_id=d.interval_id"""
    )


def _assert_canonical_daily(con: duckdb.DuckDBPyConnection) -> None:
    checks = {
        "row_count": "SELECT (SELECT count(*) FROM route_daily)-(SELECT count(*) FROM expected_route_key)",
        "duplicate_pk": "SELECT count(*)-count(DISTINCT (route_id,security_id,trade_date)) FROM route_daily",
        "route_count": "SELECT count(DISTINCT route_id)-8 FROM route_daily",
        "route_surface": "SELECT count(*) FROM (SELECT route_id,count(*) n FROM route_daily GROUP BY 1 HAVING n<>1751066)",
        "expected_empty_count": "SELECT count(*)-162376 FROM route_daily WHERE NOT source_row_present",
        "confirmed_ineligible": "SELECT count(*) FROM route_daily WHERE confirmed_state AND (NOT eligible OR quality_state<>'valid' OR raw_state IS DISTINCT FROM true)",
        "risk_formula": "SELECT count(*) FROM route_daily WHERE state_risk_set_eligible IS DISTINCT FROM (eligible AND quality_state='valid' AND confirmed_state)",
        "expected_empty_state": "SELECT count(*) FROM route_daily WHERE NOT source_row_present AND (confirmed_state OR state_risk_set_eligible)",
        "confirmation_time": "SELECT count(*) FROM route_daily WHERE coalesce(reason_code='k3_confirmation',false) IS DISTINCT FROM (confirmation_time IS NOT NULL)",
    }
    for check_id, sql in checks.items():
        value = con.execute(sql).fetchone()[0]
        if value:
            raise R2T03Error(f"canonical_daily_assertion_failed:{check_id}:{value}")


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
                [
                    {
                        "interval_id": value[0],
                        "upstream_source_interval_id": value[1],
                        "start_date": value[2].isoformat(),
                        "end_date": value[3].isoformat(),
                        "confirmed_day_count": value[4],
                        "termination_reason": value[5],
                        "exit_observation_time": _iso_time(value[6]),
                        "source_geometry_affected": value[7],
                        "source_termination_affected": value[8],
                        "dense_fragment_ordinal": value[9],
                    }
                    for value in con.execute(
                        """SELECT interval_id,upstream_source_interval_id,start_date,end_date,
                        confirmed_day_count,termination_reason,exit_observation_time,
                        source_geometry_affected,source_termination_affected,dense_fragment_ordinal
                        FROM route_atomic_interval WHERE route_id=? AND security_id=?
                        ORDER BY start_date,end_date,interval_id""",
                        [route.route_id, security_id],
                    ).fetchall()
                ],
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
               raw_state, confirmed_state, confirmed_start_date, confirmation_time,
               confirmed_end_date,exit_observation_time,state_risk_set_eligible,
               reason_code,hard_break,expected_empty_reason,source_row_present
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
    intervals: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    execution: dict[str, dict[str, Any]],
    buffers: dict[str, list[tuple[Any, ...]]],
) -> None:
    timeline = [
        {
            "security_id": security_id,
            "trade_date": row[1].isoformat(),
            "row_index": index,
            "available_time": _iso_time(row[2]),
            "eligible": bool(row[3]),
            "quality_state": str(row[4]),
            "raw_state": row[5],
            "confirmed_state": bool(row[6]),
            "confirmed_start_date": row[7].isoformat() if row[7] else "",
            "confirmation_time": _iso_time(row[8]) if row[8] else "",
            "confirmed_end_date": row[9].isoformat() if row[9] else "",
            "exit_observation_time": _iso_time(row[10]) if row[10] else "",
            "state_risk_set_eligible": bool(row[11]),
            "reason_code": str(row[12]),
            "hard_break": bool(row[13]),
            "expected_empty_reason": row[14] or "",
            "source_row_present": bool(row[15]),
        }
        for index, row in enumerate(source_rows)
    ]
    by_date = {row["trade_date"]: row["row_index"] for row in timeline}
    for interval in intervals:
        interval["start_index"] = by_date[interval["start_date"]]
        interval["end_index"] = by_date[interval["end_date"]]
    confirmation_ledger = [
        {
            "trade_date": row["trade_date"],
            "from_state": "RAW_NOT_CONFIRMED"
            if row["reason_code"] == "k3_confirmation"
            else "CONFIRMED_ACTIVE",
            "to_state": "CONFIRMED_ACTIVE"
            if row["reason_code"] == "k3_confirmation"
            else "CONFIRMED_EXITED",
            "reason_code": row["reason_code"],
        }
        for row in timeline
        if row["reason_code"]
        in {"k3_confirmation", "natural_state_exit", "quality_interruption"}
    ]
    for cell in sorted(cells, key=lambda row: row["candidate_cell_id"]):
        cell_id = cell["candidate_cell_id"]
        d, g = int(cell["d"]), int(cell["g"])
        components, zones, zone_ledger = group_event_zones(
            timeline, intervals, d, g, candidate_cell_id=cell_id
        )
        _bind_zone_terminal_reasons(zones, zone_ledger)
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
        buffers["component_source_lineage"].extend(
            _component_lineage_rows(route, cell_id, security_id, components, intervals)
        )
        membership_rows, event_rows = _zone_rows(
            route, cell_id, security_id, timeline, zones
        )
        buffers["event_zone"].extend(event_rows)
        buffers["event_zone_membership_daily"].extend(membership_rows)
        bridge_rows = _bridge_rows(
            route, cell_id, security_id, timeline, components, zones, d, g
        )
        buffers["event_zone_bridge_segment"].extend(bridge_rows)
        reentry_rows = _reentry_attempt_rows(
            cell_id, route.route_id, security_id, components, zones
        )
        buffers["reentry_attempt"].extend(reentry_rows)
        entity_ledger = _entity_transition_rows(
            cell_id,
            security_id,
            confirmation_ledger,
            components,
            zones,
            bridge_rows,
            reentry_rows,
        )
        buffers["transition_entity_ledger"].extend(entity_ledger)
        transitions = [
            {"from_state": row[5], "to_state": row[6], "reason_code": row[7]}
            for row in entity_ledger
        ]
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
            "qualified_component",
            "component_source_lineage",
            "event_zone",
            "event_zone_membership_daily",
            "event_zone_bridge_segment",
            "reentry_attempt",
            "transition_entity_ledger",
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


def _component_lineage_rows(
    route: RouteSpec,
    cell_id: str,
    security_id: str,
    components: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
) -> list[tuple[Any, ...]]:
    interval_ids: dict[tuple[Any, ...], list[str]] = {}
    for interval in intervals:
        key = (
            interval["start_date"],
            interval["end_date"],
            interval["confirmed_day_count"],
            interval["termination_reason"],
        )
        source_id = interval.get("upstream_source_interval_id")
        if not source_id:
            raise R2T03Error("component_lineage_missing_upstream_source_interval_id")
        interval_ids.setdefault(key, []).append(source_id)
    output = []
    for component in components:
        termination = component["termination_reason"]
        censor_status = {
            "natural_state_exit": "not_censored",
            "sample_end_censoring": "right_censored",
            "quality_interruption": "quality_break",
            "missing_expected_trading_row": "missing_row_fail_closed",
        }.get(termination, "unknown_fail_closed")
        key = (
            component["start_date"],
            component["end_date"],
            component["confirmed_day_count"],
            termination,
        )
        matches = interval_ids.get(key, [])
        if len(matches) != 1:
            raise R2T03Error(
                f"component_source_interval_mapping_not_unique:{route.route_id}:{security_id}:{component['component_id']}"
            )
        output.append(
            (
                cell_id,
                security_id,
                component["component_id"],
                matches[0],
                termination,
                censor_status,
                termination == "natural_state_exit",
            )
        )
    return output


def _bind_zone_terminal_reasons(
    zones: list[dict[str, Any]], zone_ledger: list[dict[str, Any]]
) -> None:
    """Bind terminal rows by explicit scan_event_id; ordering is never identity."""
    terminal_states = {"FINALIZED", "FINALIZED_WITH_QUALITY_BREAK", "RIGHT_CENSORED"}
    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in zone_ledger:
        if row.get("to_state") in terminal_states and row.get("from_state") in {
            "GAP_PENDING",
            "REENTRY_PENDING_QUALIFICATION",
        }:
            by_event.setdefault(str(row.get("scan_event_id") or ""), []).append(row)
    for zone in zones:
        matches = by_event.get(str(zone.get("scan_event_id") or ""), [])
        if len(matches) != 1:
            raise R2T03Error(
                f"zone_terminal_ledger_not_closed:{zone.get('scan_event_id', 'missing_id')}"
            )
        terminal = matches[0]
        if zone["status"] != terminal["to_state"]:
            raise R2T03Error("zone_terminal_state_mismatch")
        zone["terminal_reason_code"] = terminal["reason_code"]


def _reentry_attempt_rows(
    cell_id: str,
    route_id: str,
    security_id: str,
    components: list[dict[str, Any]],
    zones: list[dict[str, Any]],
) -> list[tuple[Any, ...]]:
    output = []
    for component in components:
        if component["qualified"]:
            continue
        zone_id = ""
        for zone in zones:
            if any(
                row["unqualified_reentry_member"]
                and component["start_index"]
                <= row["row_index"]
                <= component["end_index"]
                for row in zone["membership_rows"]
            ):
                zone_id = zone["scan_event_id"]
                break
        if not zone_id:
            continue
        termination = component["termination_reason"]
        outcome = {
            "natural_state_exit": "unqualified_reentry",
            "quality_interruption": "quality_break",
            "sample_end_censoring": "right_censored_reentry",
        }.get(termination, "unknown_fail_closed")
        attempt_id = f"{cell_id}|{security_id}|reentry|{component['component_id']}"
        output.append(
            (
                cell_id,
                route_id,
                security_id,
                zone_id,
                attempt_id,
                component["component_id"],
                component["start_date"],
                component["end_date"],
                termination,
                outcome,
            )
        )
    return output


def _entity_transition_rows(
    cell_id: str,
    security_id: str,
    confirmation_ledger: list[dict[str, Any]],
    components: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    bridge_rows: list[tuple[Any, ...]],
    reentry_rows: list[tuple[Any, ...]],
) -> list[tuple[Any, ...]]:
    """Create entity-addressable ledger rows; aggregate equality is never fabricated."""
    rows: list[tuple[Any, ...]] = []

    entity_ordinals: Counter[tuple[str, str]] = Counter()

    def add(
        entity_kind: str,
        entity_id: str,
        from_state: str,
        to_state: str,
        reason: str,
    ) -> None:
        entity_ordinals[(entity_kind, entity_id)] += 1
        rows.append(
            (
                cell_id,
                security_id,
                entity_ordinals[(entity_kind, entity_id)],
                entity_kind,
                entity_id,
                from_state,
                to_state,
                reason,
            )
        )

    for index, item in enumerate(confirmation_ledger, start=1):
        if item["from_state"] != "ANY" and item["to_state"] != "FAIL_CLOSED":
            add(
                "confirmation",
                f"confirmation|{index:05d}",
                item["from_state"],
                item["to_state"],
                item["reason_code"],
            )
    for component in components:
        if component["qualified"]:
            to_state, reason = "QUALIFIED_ACTIVE", "d_qualification"
        elif component["termination_reason"] == "sample_end_censoring":
            to_state, reason = "RIGHT_CENSORED", "prequalification_right_censored"
        elif component["termination_reason"] == "natural_state_exit":
            to_state, reason = "UNQUALIFIED_CLOSED", "normal_short_interval_drop"
        else:
            to_state, reason = "UNQUALIFIED_CLOSED", "normal_short_interval_drop"
        add(
            "component",
            component["component_id"],
            "COMPONENT_FORMING",
            to_state,
            reason,
        )
    bridges_by_zone: dict[str, list[tuple[Any, ...]]] = {}
    for bridge in bridge_rows:
        if bridge[16]:
            bridges_by_zone.setdefault(bridge[3], []).append(bridge)
    reentries_by_zone: dict[str, list[tuple[Any, ...]]] = {}
    for reentry in reentry_rows:
        reentries_by_zone.setdefault(reentry[3], []).append(reentry)
    for zone in zones:
        event_id = zone["scan_event_id"]
        add(
            "event_zone",
            event_id,
            "COMPONENT_FORMING",
            "QUALIFIED_ACTIVE",
            "d_qualification",
        )
        accepted = sorted(bridges_by_zone.get(event_id, []), key=lambda row: row[5])
        rejected = sorted(reentries_by_zone.get(event_id, []), key=lambda row: row[4])
        for bridge in accepted:
            add(
                "event_zone", event_id, "QUALIFIED_ACTIVE", "GAP_PENDING", "gap_pending"
            )
            add(
                "event_zone",
                event_id,
                "GAP_PENDING",
                "REENTRY_PENDING_QUALIFICATION",
                "reentry_pending",
            )
            add(
                "event_zone",
                event_id,
                "REENTRY_PENDING_QUALIFICATION",
                "QUALIFIED_ACTIVE",
                "reentry_reaches_d_merge",
            )
        add("event_zone", event_id, "QUALIFIED_ACTIVE", "GAP_PENDING", "gap_pending")
        if rejected:
            add(
                "event_zone",
                event_id,
                "GAP_PENDING",
                "REENTRY_PENDING_QUALIFICATION",
                "unqualified_reentry_observed",
            )
            terminal_from = "REENTRY_PENDING_QUALIFICATION"
        else:
            terminal_from = "GAP_PENDING"
        reason = _zone_reason(zone)
        if rejected and reason == "sample_end_open_zone":
            reason = "sample_end_before_requalification"
        add("event_zone", event_id, terminal_from, zone["status"], reason)
    for bridge in bridge_rows:
        if not bridge[16]:
            continue
        attempt_id = bridge[4]
        add("bridge", attempt_id, "QUALIFIED_ACTIVE", "GAP_PENDING", "gap_pending")
        add(
            "bridge",
            attempt_id,
            "GAP_PENDING",
            "REENTRY_PENDING_QUALIFICATION",
            "reentry_pending",
        )
        add(
            "bridge",
            attempt_id,
            "REENTRY_PENDING_QUALIFICATION",
            "QUALIFIED_ACTIVE",
            "reentry_reaches_d_merge",
        )
    for reentry in reentry_rows:
        attempt_id, outcome = reentry[4], reentry[9]
        add("reentry", attempt_id, "QUALIFIED_ACTIVE", "GAP_PENDING", "gap_pending")
        add(
            "reentry",
            attempt_id,
            "GAP_PENDING",
            "REENTRY_PENDING_QUALIFICATION",
            "unqualified_reentry_observed",
        )
        terminal = {
            "unqualified_reentry": ("FINALIZED", "unqualified_reentry_blocks_merge"),
            "quality_break": ("FINALIZED_WITH_QUALITY_BREAK", "quality_break"),
            "right_censored_reentry": (
                "RIGHT_CENSORED",
                "sample_end_before_requalification",
            ),
        }.get(outcome, ("FINALIZED_WITH_QUALITY_BREAK", "unknown_fail_closed"))
        add(
            "reentry",
            attempt_id,
            "REENTRY_PENDING_QUALIFICATION",
            terminal[0],
            terminal[1],
        )
    return rows


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
        CREATE TABLE route_daily(route_id VARCHAR,security_id VARCHAR,trade_date DATE,
          available_time TIMESTAMPTZ,eligible BOOLEAN,quality_state VARCHAR,raw_state BOOLEAN,
          confirmed_state BOOLEAN,confirmed_start_date DATE,confirmation_time TIMESTAMPTZ,
          confirmed_end_date DATE,exit_observation_time TIMESTAMPTZ,
          state_risk_set_eligible BOOLEAN,reason_code VARCHAR,hard_break BOOLEAN,
          expected_empty_reason VARCHAR,source_row_present BOOLEAN,
          PRIMARY KEY(route_id,security_id,trade_date));
        CREATE TABLE route_atomic_interval(route_id VARCHAR, security_id VARCHAR,
          interval_id VARCHAR, upstream_source_interval_id VARCHAR,
          start_date DATE, end_date DATE, confirmed_day_count INTEGER,
          termination_reason VARCHAR, exit_observation_time TIMESTAMPTZ,
          source_geometry_affected BOOLEAN,source_termination_affected BOOLEAN,
          dense_fragment_ordinal INTEGER,
          PRIMARY KEY(route_id,security_id,interval_id));
        CREATE TABLE qualified_component(candidate_cell_id VARCHAR, security_id VARCHAR,
          component_id VARCHAR, start_date DATE, end_date DATE,
          confirmed_day_count INTEGER, qualified BOOLEAN,
          event_qualification_time TIMESTAMPTZ);
        CREATE TABLE component_source_lineage(candidate_cell_id VARCHAR,
          security_id VARCHAR, component_id VARCHAR, source_atomic_interval_id VARCHAR,
          termination_reason VARCHAR, censor_status VARCHAR, normally_ended BOOLEAN);
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
        CREATE TABLE reentry_attempt(candidate_cell_id VARCHAR, route_id VARCHAR,
          security_id VARCHAR, scan_event_id VARCHAR, reentry_attempt_id VARCHAR,
          source_component_id VARCHAR, start_date DATE, end_date DATE,
          termination_reason VARCHAR, outcome VARCHAR);
        CREATE TABLE transition_entity_ledger(candidate_cell_id VARCHAR, security_id VARCHAR,
          transition_ordinal INTEGER, entity_kind VARCHAR, entity_id VARCHAR,
          from_state VARCHAR, to_state VARCHAR, reason_code VARCHAR);
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
               r.available_time, r.eligible, r.quality_state,
               r.raw_state, r.confirmed_state,
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
        "atomic_interval_diagnostic_profile": "r2_t03_atomic_interval_diagnostic_profile.csv",
        "component_diagnostic_profile": "r2_t03_component_diagnostic_profile.csv",
        "event_zone_diagnostic_profile": "r2_t03_event_zone_diagnostic_profile.csv",
        "strict_core_diagnostic_profile": "r2_t03_strict_core_diagnostic_profile.csv",
        "window_diagnostic_profile": "r2_t03_window_diagnostic_profile.csv",
        "parameter_invariant_profile": "r2_t03_parameter_invariant_profile.csv",
    }
    for table, name in exports.items():
        con.execute(
            f"COPY (SELECT * FROM {table} ORDER BY ALL) "
            f"TO '{_sql_path(output_dir / name)}' (HEADER, DELIMITER ',')"
        )


def _database_fingerprint(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    tables = [
        "cell_registry",
        "route_source_daily",
        "base_expected_security_date",
        "expected_route_key",
        "route_daily",
        "authorized_upstream_interval",
        "route_atomic_interval",
        "qualified_component",
        "component_source_lineage",
        "event_zone",
        "event_zone_membership_daily",
        "event_zone_bridge_segment",
        "reentry_attempt",
        "transition_entity_ledger",
        "transition_profile",
        "atomic_baseline_profile",
        "atomic_interval_diagnostic_profile",
        "d_qualification_profile",
        "component_diagnostic_profile",
        "dg_event_zone_profile",
        "event_zone_diagnostic_profile",
        "strict_core_shell_profile",
        "strict_core_diagnostic_profile",
        "window_overlap_comparison",
        "window_diagnostic_profile",
        "parameter_response_audit",
        "parameter_invariant_profile",
        "metric_results",
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
        partition_columns = [
            column
            for column in ("route_id", "candidate_cell_id", "security_id")
            if column in columns
        ]
        group = ",".join(f'"{column}"' for column in partition_columns)
        if group:
            partition_rows = con.execute(
                f"SELECT {group},sha256(to_json(list_sort(list(hash({quoted}))))) "
                f"FROM {table} GROUP BY {group} ORDER BY {group}"
            ).fetchall()
        else:
            partition_rows = [
                con.execute(
                    f"SELECT sha256(to_json(list_sort(list(hash({quoted}))))) FROM {table}"
                ).fetchone()
            ]
        multiset_hash = hashlib.sha256(
            json.dumps(partition_rows, default=str, separators=(",", ":")).encode()
        ).hexdigest()
        result[table] = {
            "row_count": row_count,
            "hash_xor_uint64": int(xor_hash or 0),
            "stable_multiset_sha256": multiset_hash,
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
        "actual_source_bindings": readiness.get("files", {}),
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


def _actual_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _record_actual_file(path: Path, report: dict[str, Any], root: Path) -> None:
    if not path.is_file():
        raise R2T03Error(f"source_file_missing:{path}")
    actual = _actual_sha256(path)
    report.setdefault(
        repo_rel(path, root),
        {
            "sha256": actual,
            "registered_sha256": actual,
            "size_bytes": path.stat().st_size,
            "status": "passed",
        },
    )


def _superseded_input_detected(
    inputs: Mapping[str, str],
    handoff: Mapping[str, Any],
    validation: Mapping[str, Any],
    routes: list[RouteSpec],
) -> bool:
    run_id = "R2-T02-20260712T1700Z"
    if handoff.get("run_id") != run_id or validation.get("run_id") != run_id:
        return True
    if any(
        run_id not in inputs[key]
        for key in (
            "t02_handoff_path",
            "t02_handoff_validation_path",
            "cell_registry_path",
            "output_contract_path",
            "metric_dictionary_path",
            "hard_gate_registry_path",
            "transition_registry_path",
            "event_zone_contract_path",
            "risk_set_contract_path",
        )
    ):
        return True
    return len(routes) != 8 or len({route.route_id for route in routes}) != 8


def _validate_interval_contract_sources(
    config: Mapping[str, Any],
    routes: list[RouteSpec],
    file_checks: Mapping[str, Any],
    root: Path,
) -> None:
    contract = _load_json(root / config["interval_adapter_contract_path"])
    mappings = {row["route_id"]: row for row in contract["route_mappings"]}
    if set(mappings) != {route.route_id for route in routes}:
        raise R2T03Error("interval_contract_route_set_mismatch")
    for route in routes:
        mapping = mappings[route.route_id]
        expected = {
            "source_kind": route.source_kind,
            "source_id": route.source_id,
            "state_line": route.state_line,
            "interval_path": route.interval_path,
        }
        for key, value in expected.items():
            if mapping.get(key) != value:
                raise R2T03Error(
                    f"interval_contract_route_mismatch:{route.route_id}:{key}"
                )
        checked = file_checks.get(repo_rel(root / route.interval_path, root), {})
        if checked.get("sha256") != mapping["source_artifact_sha256"]:
            raise R2T03Error(f"interval_contract_actual_sha_mismatch:{route.route_id}")


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
    if zone.get("terminal_reason_code"):
        return str(zone["terminal_reason_code"])
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
