# ruff: noqa: E501
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import ROOT, repo_rel, write_csv, write_json


class R2T03IndependentValidationError(RuntimeError):
    pass


def validate_independently(
    database: Path, output_dir: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    """Recompute cell counts directly, without importing the production scanner/metrics."""
    con = duckdb.connect(str(database), read_only=True)
    try:
        direct = _direct_recalculation(con)
        event_recalc = _independent_event_recalculation(con)
        profile = {
            row[0]: row[1:]
            for row in con.execute(
                "SELECT candidate_cell_id,qualified_event_count,confirmed_event_coverage,"
                "raw_false_bridged_day_count FROM dg_event_zone_profile"
            ).fetchall()
        }
        rows = []
        failures = []
        for cell_id, values in sorted(direct.items()):
            production = profile[cell_id]
            independent_events = event_recalc.get(cell_id, 0)
            checks = {
                "confirmed_days": (values[0], values[1]),
                "qualified_components": (values[2], values[3]),
                "event_count": (independent_events, production[0]),
                "confirmed_event_coverage": (values[4], production[1]),
                "raw_false_bridged_days": (values[5], production[2]),
            }
            for metric, (independent, observed) in checks.items():
                equal = _equal(independent, observed)
                rows.append(
                    {
                        "candidate_cell_id": cell_id,
                        "metric_id": metric,
                        "independent_value": independent,
                        "production_value": observed,
                        "status": "passed" if equal else "failed",
                    }
                )
                if not equal:
                    failures.append(f"{cell_id}:{metric}")
        structural = _structural_failures(con)
        failures.extend(structural)
    finally:
        con.close()
    write_csv(
        output_dir / "r2_t03_independent_recalculation.csv",
        rows,
        [
            "candidate_cell_id",
            "metric_id",
            "independent_value",
            "production_value",
            "status",
        ],
    )
    report = {
        "task_id": "R2-T03",
        "status": "passed" if not failures else "failed",
        "database_path": repo_rel(database, root),
        "cell_count": len(direct),
        "comparison_count": len(rows),
        "failure_count": len(failures),
        "failures": failures[:100],
        "production_scanner_imported": False,
        "production_metrics_imported": False,
        "event_reconstruction_method": "independent SQL adjacent-component bridge reconstruction",
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_independent_validation.json", report)
    if failures:
        raise R2T03IndependentValidationError(
            "independent_validation_failed:" + failures[0]
        )
    return report


def _direct_recalculation(con: duckdb.DuckDBPyConnection) -> dict[str, tuple[Any, ...]]:
    rows = con.execute(
        """
        WITH atomic AS (
          SELECT candidate_cell_id,
                 count(*) FILTER (WHERE confirmed_state) direct_confirmed,
                 max(a.confirmed_state_days) profile_confirmed
          FROM atomic_confirmed_daily d JOIN atomic_baseline_profile a USING(candidate_cell_id)
          GROUP BY 1
        ), component AS (
          SELECT q.candidate_cell_id,
                 count(*) FILTER (WHERE q.qualified) direct_qualified,
                 max(d.qualified_component_count) profile_qualified
          FROM qualified_component q JOIN d_qualification_profile d USING(candidate_cell_id)
          GROUP BY 1
        ), member AS (
          SELECT m.candidate_cell_id,
                 count(*) FILTER (WHERE qualified_event_risk_set_eligible)::DOUBLE /
                   nullif(max(a.confirmed_state_days),0) direct_coverage,
                 count(*) FILTER (WHERE is_raw_false_bridge AND event_zone_member) direct_raw_false
          FROM event_zone_membership_daily m
          JOIN atomic_baseline_profile a USING(candidate_cell_id) GROUP BY 1
        )
        SELECT a.candidate_cell_id,a.direct_confirmed,a.profile_confirmed,
               c.direct_qualified,c.profile_qualified,m.direct_coverage,m.direct_raw_false
        FROM atomic a JOIN component c USING(candidate_cell_id)
        JOIN member m USING(candidate_cell_id)
        """
    ).fetchall()
    return {row[0]: tuple(row[1:]) for row in rows}


def _independent_event_recalculation(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = con.execute(
        """
        WITH ordered AS (
          SELECT q.*, c.route_id, c.g,
                 lag(q.qualified) OVER w previous_qualified,
                 lag(q.end_date) OVER w previous_end
          FROM qualified_component q JOIN cell_registry c USING(candidate_cell_id)
          WINDOW w AS (PARTITION BY q.candidate_cell_id,q.security_id ORDER BY q.start_date,q.component_id)
        ), bridge AS (
          SELECT o.candidate_cell_id,o.security_id,o.component_id,
                 count(*) FILTER (WHERE r.raw_state=false) raw_false_days,
                 count(*) FILTER (WHERE NOT r.eligible OR r.quality_state<>'valid') quality_breaks
          FROM ordered o LEFT JOIN route_daily r ON r.route_id=o.route_id
            AND r.security_id=o.security_id AND r.trade_date>o.previous_end
            AND r.trade_date<o.start_date
          WHERE o.qualified AND o.previous_qualified
          GROUP BY 1,2,3
        ), counts AS (
          SELECT c.candidate_cell_id,
                 count(*) FILTER (WHERE q.qualified) qualified_count,
                 count(*) FILTER (WHERE b.raw_false_days<=c.g AND b.quality_breaks=0) accepted_bridges
          FROM cell_registry c LEFT JOIN qualified_component q USING(candidate_cell_id)
          LEFT JOIN bridge b USING(candidate_cell_id,security_id,component_id)
          GROUP BY 1
        )
        SELECT candidate_cell_id,qualified_count-accepted_bridges FROM counts
        """
    ).fetchall()
    return {row[0]: int(row[1]) for row in rows}


def _structural_failures(con: duckdb.DuckDBPyConnection) -> list[str]:
    checks = {
        "cell_count": "SELECT count(*)=72 FROM cell_registry",
        "subset": "SELECT count(*)=0 FROM strict_core_window_comparison WHERE subset_violation",
        "event_pk": "SELECT count(*)=count(DISTINCT candidate_cell_id||'|'||security_id||'|'||scan_event_id) FROM event_zone",
        "membership_time": "SELECT count(*)=0 FROM event_zone_membership_daily WHERE membership_available_time<available_time",
        "risk_formula": "SELECT count(*)=0 FROM event_zone_membership_daily WHERE qualified_event_risk_set_eligible IS DISTINCT FROM (state_risk_set_eligible AND event_zone_member AND component_qualified_as_of AND NOT is_raw_false_bridge AND NOT is_preconfirmation_gap)",
    }
    return [name for name, sql in checks.items() if not con.execute(sql).fetchone()[0]]


def _equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, float) or isinstance(right, float):
        return abs(float(left) - float(right)) <= 1e-12
    return left == right
