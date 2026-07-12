# ruff: noqa: E501
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import ROOT, repo_rel, write_csv, write_json


class R2T03GateError(RuntimeError):
    pass


def validate_runtime_gates(
    database: Path,
    output_dir: Path,
    hard_gate_registry: Path,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    con = duckdb.connect(str(database), read_only=True)
    try:
        checks = _structural_checks(con)
        checks.append(
            _transition_registry_check(
                con, hard_gate_registry.parent / "r2_t02_transition_registry.csv"
            )
        )
        parameter = _parameter_checks(con)
        gates = _evaluate_frozen_gates(con, hard_gate_registry)
    finally:
        con.close()
    gate_path = output_dir / "r2_t03_runtime_gate_results.csv"
    write_csv(
        gate_path,
        checks + parameter + gates,
        [
            "check_id",
            "scope",
            "candidate_cell_id",
            "observed_value",
            "expected_rule",
            "status",
            "blocking",
            "detail",
        ],
    )
    blocking = [
        row
        for row in checks + parameter
        if row["blocking"] and row["status"] != "passed"
    ]
    report = {
        "task_id": "R2-T03",
        "status": "passed" if not blocking else "failed",
        "database_path": repo_rel(database, root),
        "check_count": len(checks) + len(parameter) + len(gates),
        "blocking_failure_count": len(blocking),
        "blocking_failures": [row["check_id"] + ":" + row["scope"] for row in blocking],
        "frozen_scientific_gate_failure_count": sum(
            row["status"] != "passed" for row in gates
        ),
        "scientific_gate_failures_are_reported_not_cell_selection": True,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_runtime_gate_validation.json", report)
    if blocking:
        raise R2T03GateError(
            "runtime_gate_blocking_failure:" + report["blocking_failures"][0]
        )
    return report


def _structural_checks(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    specs = [
        ("cell_count", "global", "SELECT count(*) FROM cell_registry", 72, "=72"),
        (
            "route_count",
            "global",
            "SELECT count(DISTINCT route_id) FROM cell_registry",
            8,
            "=8",
        ),
        (
            "cell_execution_nonzero",
            "global",
            "SELECT count(*) FROM event_zone",
            0,
            ">0",
        ),
        (
            "event_pk_duplicates",
            "global",
            "SELECT count(*)-count(DISTINCT candidate_cell_id||'|'||security_id||'|'||scan_event_id) FROM event_zone",
            0,
            "=0",
        ),
        (
            "membership_pk_duplicates",
            "global",
            "SELECT count(*)-count(DISTINCT candidate_cell_id||'|'||security_id||'|'||scan_event_id||'|'||trade_date) FROM event_zone_membership_daily",
            0,
            "=0",
        ),
        (
            "subset_violation",
            "global",
            "SELECT count(*) FROM strict_core_window_comparison WHERE subset_violation",
            0,
            "=0",
        ),
        (
            "strict_core_subset_status",
            "global",
            "SELECT count(*) FROM strict_core_shell_profile WHERE strict_core_subset_status<>'passed'",
            0,
            "=0",
        ),
        (
            "risk_set_formula",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE state_risk_set_eligible IS DISTINCT FROM (eligible AND quality_state='valid' AND confirmed_state)",
            0,
            "=0",
        ),
        (
            "qualified_risk_formula",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE qualified_event_risk_set_eligible IS DISTINCT FROM (state_risk_set_eligible AND event_zone_member AND component_qualified_as_of AND NOT is_raw_false_bridge AND NOT is_preconfirmation_gap)",
            0,
            "=0",
        ),
        (
            "membership_time_order",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE membership_available_time < available_time OR evaluation_time <> membership_available_time",
            0,
            "=0",
        ),
        (
            "g_zero_bridge",
            "g=0",
            "SELECT count(*) FROM event_zone e JOIN cell_registry c USING(candidate_cell_id) WHERE c.g=0 AND e.raw_false_bridged_day_count<>0",
            0,
            "=0",
        ),
        (
            "all_null_metrics",
            "global",
            "SELECT count(*) FROM dg_event_zone_profile WHERE qualified_event_count IS NULL OR confirmed_event_coverage IS NULL",
            0,
            "=0",
        ),
        (
            "all_one_or_zero_primary",
            "primary",
            "SELECT CASE WHEN min(qualified_event_count)=max(qualified_event_count) AND min(qualified_event_count) IN (0,1) THEN 1 ELSE 0 END FROM dg_event_zone_profile p JOIN cell_registry c USING(candidate_cell_id) WHERE c.candidate_role='primary'",
            0,
            "=0",
        ),
        (
            "confirmed_conservation",
            "global",
            "SELECT count(*) FROM (SELECT m.candidate_cell_id, sum(m.confirmed_day_count) component_days, a.confirmed_state_days FROM qualified_component m JOIN atomic_baseline_profile a USING(candidate_cell_id) GROUP BY 1,3 HAVING component_days<>confirmed_state_days)",
            0,
            "=0",
        ),
    ]
    output = []
    for check_id, scope, sql, threshold, rule in specs:
        value = con.execute(sql).fetchone()[0]
        passed = value > threshold if rule == ">0" else value == threshold
        output.append(
            _row(check_id, scope, "", value, rule, passed, True, "direct_sql")
        )
    output.extend(_transition_closure_checks(con))
    return output


def _transition_closure_checks(
    con: duckdb.DuckDBPyConnection,
) -> list[dict[str, Any]]:
    """Entity-level closure checks bound to the frozen T02 transition registry."""
    specs = [
        (
            "qualified_component_transition_closure",
            """SELECT count(*) FROM (
            SELECT q.candidate_cell_id,q.security_id,q.component_id
            FROM qualified_component q LEFT JOIN transition_entity_ledger t
              ON t.candidate_cell_id=q.candidate_cell_id AND t.security_id=q.security_id
             AND t.entity_kind='component' AND t.entity_id=q.component_id
             AND t.from_state='COMPONENT_FORMING' AND t.to_state='QUALIFIED_ACTIVE'
             AND t.reason_code='d_qualification'
            WHERE q.qualified GROUP BY 1,2,3 HAVING count(t.entity_id)<>1)""",
        ),
        (
            "unqualified_normal_close_transition_closure",
            """SELECT count(*) FROM (
            SELECT q.candidate_cell_id,q.security_id,q.component_id
            FROM qualified_component q JOIN component_source_lineage l
              USING(candidate_cell_id,security_id,component_id)
            LEFT JOIN transition_entity_ledger t
              ON t.candidate_cell_id=q.candidate_cell_id AND t.security_id=q.security_id
             AND t.entity_kind='component' AND t.entity_id=q.component_id
             AND t.to_state='UNQUALIFIED_CLOSED'
            WHERE NOT q.qualified AND l.normally_ended
            GROUP BY 1,2,3 HAVING count(t.entity_id)<>1)""",
        ),
        (
            "event_creation_transition_closure",
            """SELECT count(*) FROM (
            SELECT e.candidate_cell_id,e.security_id,e.scan_event_id
            FROM event_zone e LEFT JOIN transition_entity_ledger t
              ON t.candidate_cell_id=e.candidate_cell_id AND t.security_id=e.security_id
             AND t.entity_kind='event_zone' AND t.entity_id=e.scan_event_id
             AND t.to_state='QUALIFIED_ACTIVE'
            GROUP BY 1,2,3 HAVING count(t.entity_id)<>1)""",
        ),
        (
            "event_terminal_transition_closure",
            """SELECT count(*) FROM (
            SELECT e.candidate_cell_id,e.security_id,e.scan_event_id
            FROM event_zone e LEFT JOIN transition_entity_ledger t
              ON t.candidate_cell_id=e.candidate_cell_id AND t.security_id=e.security_id
             AND t.entity_kind='event_zone' AND t.entity_id=e.scan_event_id
             AND t.to_state IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED')
            GROUP BY 1,2,3 HAVING count(t.entity_id)<>1)""",
        ),
        (
            "accepted_bridge_transition_closure",
            """SELECT count(*) FROM (
            SELECT b.candidate_cell_id,b.security_id,b.bridge_segment_id
            FROM event_zone_bridge_segment b LEFT JOIN transition_entity_ledger t
              ON t.candidate_cell_id=b.candidate_cell_id AND t.security_id=b.security_id
             AND t.entity_kind='bridge' AND t.entity_id=b.bridge_segment_id
            WHERE b.merge_accepted GROUP BY 1,2,3 HAVING count(t.entity_id)<>3)""",
        ),
        (
            "rejected_reentry_transition_closure",
            """SELECT count(*) FROM (
            SELECT r.candidate_cell_id,r.security_id,r.reentry_attempt_id
            FROM reentry_attempt r LEFT JOIN transition_entity_ledger t
              ON t.candidate_cell_id=r.candidate_cell_id AND t.security_id=r.security_id
             AND t.entity_kind='reentry' AND t.entity_id=r.reentry_attempt_id
            GROUP BY 1,2,3 HAVING count(t.entity_id)<>3)""",
        ),
        (
            "quality_break_not_bridged",
            """SELECT count(*) FROM event_zone_bridge_segment
            WHERE merge_accepted AND decision_reason='quality_break'""",
        ),
        (
            "event_entity_transition_continuity",
            """SELECT count(*) FROM (
            SELECT candidate_cell_id,security_id,entity_id,transition_ordinal,from_state,
              lag(to_state) OVER (PARTITION BY candidate_cell_id,security_id,entity_id ORDER BY transition_ordinal) prior_to
            FROM transition_entity_ledger WHERE entity_kind='event_zone')
            WHERE transition_ordinal>1 AND from_state<>prior_to""",
        ),
        (
            "event_entity_transition_ordinal_continuity",
            """SELECT count(*) FROM (
            SELECT candidate_cell_id,security_id,entity_id,count(*) n,min(transition_ordinal) lo,max(transition_ordinal) hi
            FROM transition_entity_ledger WHERE entity_kind='event_zone' GROUP BY 1,2,3)
            WHERE lo<>1 OR hi<>n""",
        ),
        (
            "event_entity_no_transition_after_terminal",
            """SELECT count(*) FROM (
            SELECT candidate_cell_id,security_id,entity_id,transition_ordinal,to_state,
              max(transition_ordinal) OVER (PARTITION BY candidate_cell_id,security_id,entity_id) last_ordinal
            FROM transition_entity_ledger WHERE entity_kind='event_zone')
            WHERE to_state IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED') AND transition_ordinal<>last_ordinal""",
        ),
    ]
    return [
        _row(check_id, "global", "", value, "=0", value == 0, True, "entity_ledger")
        for check_id, sql in specs
        for value in [con.execute(sql).fetchone()[0]]
    ]


def _transition_registry_check(
    con: duckdb.DuckDBPyConnection, path: Path
) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    allowed = {(row["from_state"], row["to_state"], row["reason_code"]) for row in rows}
    observed = set(
        con.execute(
            "SELECT DISTINCT from_state,to_state,reason_code FROM transition_entity_ledger"
        ).fetchall()
    )
    invalid = sorted(observed - allowed)
    return _row(
        "transition_tuple_registry",
        "global",
        "",
        len(invalid),
        "=0",
        not invalid,
        True,
        json.dumps(invalid[:3]),
    )


def _parameter_checks(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    output = []
    rows = con.execute(
        "SELECT route_id,d,event_count_variants,bridge_count_variants,status FROM parameter_response_audit ORDER BY 1,2"
    ).fetchall()
    for route, d, event_variants, bridge_variants, status in rows:
        output.append(
            _row(
                "g_parameter_response",
                f"{route}:d={d}",
                "",
                f"events={event_variants};bridges={bridge_variants}",
                "at least one metric varies across g",
                status == "responsive",
                True,
                status,
            )
        )
    monotonic = con.execute(
        """
        SELECT a.candidate_cell_id,b.candidate_cell_id,a.qualified_event_count,b.qualified_event_count
        FROM dg_event_zone_profile a JOIN cell_registry ca USING(candidate_cell_id)
        JOIN cell_registry cb ON cb.route_id=ca.route_id AND cb.d=ca.d AND cb.g=ca.g+1
        JOIN dg_event_zone_profile b ON b.candidate_cell_id=cb.candidate_cell_id
        WHERE b.qualified_event_count>a.qualified_event_count
        """
    ).fetchall()
    output.append(
        _row(
            "g_event_count_monotonic",
            "global",
            "",
            len(monotonic),
            "=0 increases",
            not monotonic,
            True,
            json.dumps(monotonic[:3]),
        )
    )
    d_bad = con.execute(
        """
        SELECT count(*) FROM d_qualification_profile a JOIN cell_registry ca USING(candidate_cell_id)
        JOIN cell_registry cb ON cb.route_id=ca.route_id AND cb.g=ca.g AND cb.d=ca.d+1
        JOIN d_qualification_profile b ON b.candidate_cell_id=cb.candidate_cell_id
        WHERE b.qualified_component_count>a.qualified_component_count
        """
    ).fetchone()[0]
    output.append(
        _row(
            "d_component_monotonic",
            "global",
            "",
            d_bad,
            "=0 increases",
            d_bad == 0,
            True,
            "direct_sql",
        )
    )
    return output


def _evaluate_frozen_gates(
    con: duckdb.DuckDBPyConnection, registry: Path
) -> list[dict[str, Any]]:
    with registry.open(encoding="utf-8", newline="") as handle:
        rules = list(csv.DictReader(handle))
    metrics = {
        row[0]: dict(zip([column[0] for column in con.description], row))
        for row in con.execute("SELECT * FROM metric_results").fetchall()
    }
    baseline = {
        row[0]: (row[1], row[2])
        for row in con.execute(
            "SELECT candidate_cell_id,atomic_confirmed_interval_count,confirmed_state_days FROM atomic_baseline_profile"
        ).fetchall()
    }
    upstream_securities = {
        row[0]: row[1]
        for row in con.execute(
            "SELECT route_id,count(DISTINCT security_id) FROM route_daily "
            "WHERE confirmed_state GROUP BY route_id"
        ).fetchall()
    }
    output = []
    for rule in rules:
        if rule["implementation_stage"] != "r2_t02_reference_executable":
            continue
        for cell_id, metric in metrics.items():
            if metric["state_line"] != rule["state_line"]:
                continue
            observed = metric[rule["metric_id"]]
            threshold = _threshold(
                rule["gate_id"],
                rule["metric_id"],
                baseline[cell_id],
                upstream_securities.get(metric["route_id"], 0),
            )
            passed = _compare(observed, rule["operator"], threshold)
            output.append(
                _row(
                    rule["gate_id"],
                    metric["route_id"],
                    cell_id,
                    observed,
                    f"{rule['operator']}{threshold}",
                    passed,
                    False,
                    "frozen_reference_gate",
                )
            )
    return output


def _threshold(
    gate_id: str,
    metric_id: str,
    baseline: tuple[int, int],
    upstream_unique_securities: int,
) -> float:
    state = "S_PCT" if gate_id.startswith("s_pct_") else "S_PCVT"
    if metric_id == "qualified_event_count":
        return max(
            250 if state == "S_PCT" else 100, int((0.05 * baseline[0]) + 0.999999)
        )
    if metric_id == "unique_securities":
        # The frozen rule references upstream unique securities; derive it from the route.
        floor, share = (150, 0.20) if state == "S_PCT" else (100, 0.15)
        return max(floor, int((share * upstream_unique_securities) + 0.999999))
    constants = {
        "retained_confirmed_day_ratio": 0.35 if state == "S_PCT" else 0.25,
        "short_interval_drop_rate": 0.80 if state == "S_PCT" else 0.85,
        "bridged_day_ratio": 0.30 if state == "S_PCT" else 0.35,
        "merge_ratio": 0.70 if state == "S_PCT" else 0.75,
        "open_event_ratio": 0.10,
        "nonzero_years": 8,
        "max_year_share": 0.35,
        "duration_q95_ratio": 3.0,
    }
    return constants[metric_id]


def _compare(value: Any, operator: str, threshold: float) -> bool:
    if value is None:
        return False
    return {
        ">=": value >= threshold,
        "<=": value <= threshold,
        "==": value == threshold,
    }[operator]


def _row(
    check_id: str,
    scope: str,
    cell: str,
    observed: Any,
    rule: str,
    passed: bool,
    blocking: bool,
    detail: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "scope": scope,
        "candidate_cell_id": cell,
        "observed_value": observed,
        "expected_rule": rule,
        "status": "passed" if passed else "failed",
        "blocking": blocking,
        "detail": detail,
    }
