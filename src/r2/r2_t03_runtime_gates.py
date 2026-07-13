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
        checks.extend(_binding_checks(output_dir))
        checks.append(
            _transition_registry_check(
                con, hard_gate_registry.parent / "r2_t02_transition_registry.csv"
            )
        )
        checks.append(
            _output_contract_check(
                con, hard_gate_registry.parent / "r2_t02_t03_output_contract.json"
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
    specs = _structural_check_specs()
    output = []
    for check_id, scope, sql, threshold, rule in specs:
        value = con.execute(sql).fetchone()[0]
        passed = value > threshold if rule == ">0" else value == threshold
        output.append(
            _row(check_id, scope, "", value, rule, passed, True, "direct_sql")
        )
    output.extend(_transition_closure_checks(con))
    return output


def _structural_check_specs() -> list[tuple[str, str, str, int, str]]:
    return [
        (
            "duplicate_primary_key",
            "route_daily",
            "SELECT count(*)-count(DISTINCT (route_id,security_id,trade_date)) FROM route_daily",
            0,
            "=0",
        ),
        (
            "missing_expected_trading_row",
            "global",
            "SELECT (SELECT count(*) FROM expected_route_key)-(SELECT count(*) FROM route_daily)",
            0,
            "=0",
        ),
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
            "risk_set_violation",
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
            "confirmed_day_conservation_mismatch",
            "global",
            "SELECT count(*) FROM (SELECT m.candidate_cell_id, sum(m.confirmed_day_count) component_days, a.confirmed_state_days FROM qualified_component m JOIN atomic_baseline_profile a USING(candidate_cell_id) GROUP BY 1,3 HAVING component_days<>confirmed_state_days)",
            0,
            "=0",
        ),
        (
            "lineage_mismatch",
            "global",
            "SELECT count(*) FROM route_atomic_interval WHERE upstream_source_interval_id IS NULL",
            0,
            "=0",
        ),
        (
            "event_id_instability",
            "global",
            "SELECT count(*) FROM event_zone WHERE scan_event_id IS NULL OR scan_event_id=''",
            0,
            "=0",
        ),
        (
            "post_merge_short_zone",
            "global",
            "SELECT count(*) FROM event_zone e JOIN cell_registry c USING(candidate_cell_id) WHERE e.confirmed_day_count<c.d",
            0,
            "=0",
        ),
        (
            "unknown_bridge",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE is_bridged_gap AND quality_state='unknown'",
            0,
            "=0",
        ),
        (
            "blocked_bridge",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE is_bridged_gap AND quality_state='blocked'",
            0,
            "=0",
        ),
        (
            "diagnostic_required_bridge",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE is_bridged_gap AND quality_state='diagnostic_required'",
            0,
            "=0",
        ),
        (
            "ineligible_bridge",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE is_bridged_gap AND NOT eligible",
            0,
            "=0",
        ),
        (
            "right_censor_misclassified_as_natural_exit",
            "global",
            "SELECT count(*) FROM event_zone WHERE status='RIGHT_CENSORED' AND exit_or_censor_reason NOT IN ('sample_end_open_zone','sample_end_before_requalification')",
            0,
            "=0",
        ),
        (
            "prequalification_censor_included_in_drop_denominator",
            "global",
            "SELECT count(*) FROM component_source_lineage WHERE censor_status='right_censored' AND normally_ended",
            0,
            "=0",
        ),
        (
            "asof_membership_leakage",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE component_qualified_as_of AND membership_available_time<available_time",
            0,
            "=0",
        ),
        (
            "availability_backfill",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE membership_available_time<available_time OR evaluation_time<>membership_available_time",
            0,
            "=0",
        ),
        (
            "unqualified_reentry_unfinalized",
            "global",
            """SELECT count(*) FROM reentry_attempt r LEFT JOIN (
              SELECT candidate_cell_id,security_id,entity_id,
               arg_max(to_state,transition_ordinal) terminal_state
              FROM transition_entity_ledger WHERE entity_kind='reentry' GROUP BY 1,2,3) t
              ON t.candidate_cell_id=r.candidate_cell_id AND t.security_id=r.security_id
             AND t.entity_id=r.reentry_attempt_id
              WHERE r.outcome NOT IN ('unqualified_reentry','quality_break','right_censored_reentry')
                 OR t.terminal_state NOT IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED')""",
            0,
            "=0",
        ),
        (
            "censor_contamination",
            "global",
            "SELECT count(*) FROM component_source_lineage WHERE censor_status<>'not_censored' AND normally_ended",
            0,
            "=0",
        ),
        (
            "raw_false_gap_days_exceed_g",
            "global",
            "SELECT count(*) FROM event_zone e JOIN cell_registry c USING(candidate_cell_id) WHERE e.max_raw_false_gap_days>c.g",
            0,
            "=0",
        ),
        (
            "preconfirmation_days_exceed_k_minus_one_bound",
            "global",
            """SELECT count(*) FROM event_zone_bridge_segment
            WHERE merge_accepted AND preconfirmation_gap_day_count>
              (K-1)*raw_false_gap_day_count""",
            0,
            "=0",
        ),
        (
            "total_nonconfirmed_gap_days_exceed_k_bound",
            "global",
            """SELECT count(*) FROM event_zone_bridge_segment
            WHERE merge_accepted AND (
              total_nonconfirmed_gap_day_count<>
                raw_false_gap_day_count+preconfirmation_gap_day_count
              OR total_nonconfirmed_gap_day_count>K*raw_false_gap_day_count
              OR total_nonconfirmed_gap_day_count>K*g)""",
            0,
            "=0",
        ),
        (
            "event_overlap_within_same_route_cell_security",
            "global",
            "SELECT count(*) FROM event_zone a JOIN event_zone b ON a.candidate_cell_id=b.candidate_cell_id AND a.security_id=b.security_id AND a.scan_event_id<b.scan_event_id JOIN qualified_component qa ON qa.candidate_cell_id=a.candidate_cell_id AND qa.security_id=a.security_id AND qa.component_id=a.first_component_id JOIN qualified_component qb ON qb.candidate_cell_id=b.candidate_cell_id AND qb.security_id=b.security_id AND qb.component_id=b.first_component_id WHERE qa.start_date<=qb.end_date AND qb.start_date<=qa.end_date",
            0,
            "=0",
        ),
        (
            "event_zone_revision_regression",
            "global",
            """SELECT count(*) FROM (
              SELECT zone_revision_as_of,
               lag(zone_revision_as_of) OVER(PARTITION BY candidate_cell_id,security_id,scan_event_id ORDER BY trade_date) prior_revision
              FROM event_zone_membership_daily WHERE event_zone_member)
              WHERE zone_revision_as_of<0 OR zone_revision_as_of<prior_revision""",
            0,
            "=0",
        ),
        (
            "status_asof_timeline_gap",
            "global",
            "SELECT count(*) FROM event_zone_membership_daily WHERE event_zone_member AND zone_status_as_of IS NULL",
            0,
            "=0",
        ),
        (
            "strict_core_shell_reconciliation_mismatch",
            "global",
            "SELECT count(*) FROM strict_core_shell_profile WHERE strict_core_subset_status<>'passed'",
            0,
            "=0",
        ),
        (
            "forbidden_output_field",
            "global",
            """SELECT count(*) FROM information_schema.columns
            WHERE table_schema='main' AND (
              column_name ILIKE '%future%' OR column_name ILIKE '%return%'
              OR column_name ILIKE '%precision%' OR column_name ILIKE '%recall%'
              OR column_name ILIKE '%winner%' OR column_name ILIKE '%selected_d%'
              OR column_name ILIKE '%selected_g%')""",
            0,
            "=0",
        ),
    ]


def _binding_checks(output_dir: Path) -> list[dict[str, Any]]:
    readiness = json.loads(
        (output_dir / "r2_t03_source_readiness.json").read_text(encoding="utf-8")
    )
    bindings = json.loads(
        (output_dir / "r2_t03_input_binding.json").read_text(encoding="utf-8")
    )
    file_failures = sum(
        value.get("status") != "passed" for value in readiness.get("files", {}).values()
    )
    superseded = bool(readiness.get("superseded_input_detected", True))
    binding_failed = bindings.get("status") != "passed"
    return [
        _row(
            "source_hash_mismatch",
            "global",
            "",
            file_failures,
            "=0",
            file_failures == 0,
            True,
            "source_readiness",
        ),
        _row(
            "superseded_input",
            "global",
            "",
            int(superseded),
            "=0",
            not superseded,
            True,
            "derived_identity_check",
        ),
        _row(
            "input_binding_mismatch",
            "global",
            "",
            int(binding_failed),
            "=0",
            not binding_failed,
            True,
            "input_binding",
        ),
    ]


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
             AND t.from_state='COMPONENT_FORMING' AND t.to_state='QUALIFIED_ACTIVE'
             AND t.reason_code='d_qualification'
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


def _output_contract_check(
    con: duckdb.DuckDBPyConnection, path: Path
) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    missing = []
    for table, spec in contract.get("table_contracts", {}).items():
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if table not in tables:
            missing.append(f"table:{table}")
            continue
        info = con.execute(f"PRAGMA table_info('{table}')").fetchall()
        actual = {row[1] for row in info}
        actual_types = {row[1]: str(row[2]).upper() for row in info}
        fields = spec.get("fields", [])
        required = {field["name"] for field in fields}
        missing.extend(f"field:{table}:{field}" for field in required - actual)
        primary_key = spec.get("primary_key", [])
        if primary_key:
            key = ",".join(primary_key)
            duplicates = con.execute(
                f"SELECT count(*)-count(DISTINCT ({key})) FROM {table}"
            ).fetchone()[0]
            if duplicates:
                missing.append(f"duplicate_pk:{table}:{duplicates}")
        for field in fields:
            expected_type = field.get("type")
            compatible = {
                "string": ("VARCHAR",),
                "enum": ("VARCHAR",),
                "integer": ("INTEGER", "BIGINT", "HUGEINT", "SMALLINT"),
                "number": ("DOUBLE", "FLOAT", "DECIMAL", "REAL"),
                "boolean": ("BOOLEAN",),
                "boolean_or_unknown": ("BOOLEAN", "VARCHAR"),
                "date": ("DATE",),
                "datetime_tz": ("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"),
            }.get(expected_type, ())
            if (
                field["name"] in actual
                and compatible
                and not any(
                    actual_types[field["name"]].startswith(value)
                    for value in compatible
                )
            ):
                missing.append(
                    f"type:{table}:{field['name']}:{actual_types[field['name']]}"
                )
            if not field.get("nullable", True) and field["name"] in actual:
                nulls = con.execute(
                    f'SELECT count(*) FROM {table} WHERE "{field["name"]}" IS NULL'
                ).fetchone()[0]
                if nulls:
                    missing.append(f"null:{table}:{field['name']}:{nulls}")
            enums = field.get("enum_values", [])
            if enums and field["name"] in actual:
                placeholders = ",".join("?" for _ in enums)
                invalid = con.execute(
                    f'SELECT count(*) FROM {table} WHERE "{field["name"]}" NOT IN ({placeholders})',
                    enums,
                ).fetchone()[0]
                if invalid:
                    missing.append(f"enum:{table}:{field['name']}:{invalid}")
    return _row(
        "schema_mismatch",
        "global",
        "",
        len(missing),
        "=0",
        not missing,
        True,
        json.dumps(missing[:5]),
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
    for check_id, scope, violations, rule in con.execute(
        "SELECT check_id,scope,observed_violations,expected_rule FROM parameter_invariant_profile"
    ).fetchall():
        output.append(
            _row(
                check_id,
                scope,
                "",
                violations,
                rule,
                violations == 0,
                True,
                "parameter_invariant_profile",
            )
        )
    g0 = con.execute(
        """SELECT count(*) FROM dg_event_zone_profile p JOIN d_qualification_profile d USING(candidate_cell_id)
        JOIN cell_registry c USING(candidate_cell_id) WHERE c.g=0 AND
        (p.qualified_event_count<>d.qualified_component_count OR p.raw_false_bridged_day_count<>0)"""
    ).fetchone()[0]
    output.append(
        _row(
            "g_zero_identity",
            "global",
            "",
            g0,
            "=0",
            g0 == 0,
            True,
            "event=component;bridge=0",
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
        if (
            rule["implementation_stage"] != "r2_t02_reference_executable"
            or rule["state_line"] == "GLOBAL"
        ):
            continue
        for cell_id, metric in metrics.items():
            if (
                rule["state_line"] != "GLOBAL"
                and metric["state_line"] != rule["state_line"]
            ):
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
