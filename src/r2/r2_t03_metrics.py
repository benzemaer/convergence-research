# ruff: noqa: E501
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import duckdb

ExactKey = tuple[str, str]

# Frozen source: R2-T02 metric dictionary, run R2-T02-20260712T1700Z.
# Each entry binds metric_id -> evaluator_id, numerator, denominator, population.
METRIC_BINDINGS: dict[str, dict[str, str]] = {
    "qualified_event_count": {
        "evaluator_id": "r2_t02_metric_eval__qualified_event_count",
        "numerator": "count distinct finalized or right-censored qualified scan_event_id",
        "denominator": "security-year-route-cell reporting scope",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "unique_securities": {
        "evaluator_id": "r2_t02_metric_eval__unique_securities",
        "numerator": "distinct securities with at least one qualified event zone",
        "denominator": "upstream unique securities for the same state line",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "confirmed_event_coverage": {
        "evaluator_id": "r2_t02_metric_eval__confirmed_event_coverage",
        "numerator": "distinct eligible valid confirmed days in qualified components",
        "denominator": "eligible valid daily security-date rows in the candidate cell",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "retained_confirmed_day_ratio": {
        "evaluator_id": "r2_t02_metric_eval__retained_confirmed_day_ratio",
        "numerator": "qualified component confirmed days",
        "denominator": "confirmed_state_days",
        "population": "atomic intervals partitioned by d and censor status",
    },
    "bridged_day_ratio": {
        "evaluator_id": "r2_t02_metric_eval__bridged_day_ratio",
        "numerator": "sum raw_false_bridged_day_count",
        "denominator": "sum event zone_span_days",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "retrospective_qualified_confirmed_coverage": {
        "evaluator_id": "r2_t02_metric_eval__retrospective_qualified_confirmed_coverage",
        "numerator": "retrospective qualified confirmed days",
        "denominator": "eligible valid daily security-date rows",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "asof_qualified_confirmed_coverage": {
        "evaluator_id": "r2_t02_metric_eval__asof_qualified_confirmed_coverage",
        "numerator": "confirmed days qualified as of evaluation time",
        "denominator": "eligible valid daily security-date rows",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "duration_q95_ratio": {
        "evaluator_id": "r2_t02_metric_eval__duration_q95_ratio",
        "numerator": "nearest-order q95 event zone_span_days",
        "denominator": "nearest-order q95 upstream atomic confirmed_day_count for route and state line",
        "population": "qualified zones and all upstream atomic confirmed intervals",
    },
    "merge_ratio": {
        "evaluator_id": "r2_t02_metric_eval__merge_ratio",
        "numerator": "distinct event zones with component_count > 1",
        "denominator": "qualified_event_count",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "open_event_ratio": {
        "evaluator_id": "r2_t02_metric_eval__open_event_ratio",
        "numerator": "distinct RIGHT_CENSORED qualified event zones",
        "denominator": "qualified_event_count",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "nonzero_years": {
        "evaluator_id": "r2_t02_metric_eval__nonzero_years",
        "numerator": "distinct years of first qualified component start",
        "denominator": "qualified event population",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "max_year_share": {
        "evaluator_id": "r2_t02_metric_eval__max_year_share",
        "numerator": "maximum qualified event count in one start year",
        "denominator": "qualified_event_count",
        "population": "qualified zones, including explicit right-censored open zones",
    },
    "short_interval_drop_rate": {
        "evaluator_id": "r2_t02_metric_eval__short_interval_drop_rate",
        "numerator": "normally ended atomic intervals with confirmed_day_count < d",
        "denominator": "all observed normally ended atomic intervals",
        "population": "natural_state_exit only; all censor and quality/missing breaks excluded",
    },
}


def nearest_order_statistic(
    values: Iterable[float | int], q: float
) -> float | int | None:
    """Frozen nearest-order statistic: sorted_values[ceil(q*n)-1]."""
    ordered = sorted(values)
    if not ordered:
        return None
    if not 0 < q <= 1:
        raise ValueError("nearest_order_q_out_of_range")
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def reference_hard_gate_metrics(
    *,
    events: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
    eligible_valid_daily_count: int,
    confirmed_state_days: int,
    qualified_confirmed_keys: Iterable[ExactKey],
    retrospective_qualified_confirmed_keys: Iterable[ExactKey],
    asof_qualified_confirmed_keys: Iterable[ExactKey],
    upstream_atomic_durations: Sequence[int],
    d: int,
) -> dict[str, int | float | None]:
    """Exact hand-checkable implementation of the frozen reference hard-gate metrics."""
    event_by_id = {str(row["scan_event_id"]): row for row in events}
    qualified_event_count = len(event_by_id)
    qualified_days = sum(
        int(row["confirmed_day_count"]) for row in components if bool(row["qualified"])
    )
    qualified_key_count = len(set(qualified_confirmed_keys))
    retrospective_key_count = len(set(retrospective_qualified_confirmed_keys))
    asof_key_count = len(set(asof_qualified_confirmed_keys))
    normal = [
        row
        for row in components
        if bool(row.get("normally_ended"))
        and row.get("termination_reason") == "natural_state_exit"
        and row.get("censor_status") == "not_censored"
    ]
    event_q95 = nearest_order_statistic(
        [int(row["zone_span_days"]) for row in event_by_id.values()], 0.95
    )
    atomic_q95 = nearest_order_statistic(upstream_atomic_durations, 0.95)
    return {
        "qualified_event_count": qualified_event_count,
        "unique_securities": len(
            {str(row["security_id"]) for row in event_by_id.values()}
        ),
        "retained_confirmed_day_ratio": _ratio(qualified_days, confirmed_state_days),
        "bridged_day_ratio": _ratio(
            sum(
                int(row["raw_false_bridged_day_count"]) for row in event_by_id.values()
            ),
            sum(int(row["zone_span_days"]) for row in event_by_id.values()),
        ),
        "merge_ratio": _ratio(
            sum(int(row["component_count"]) > 1 for row in event_by_id.values()),
            qualified_event_count,
        ),
        "open_event_ratio": _ratio(
            sum(row["status"] == "RIGHT_CENSORED" for row in event_by_id.values()),
            qualified_event_count,
        ),
        "nonzero_years": len(
            {str(row["start_date"])[:4] for row in event_by_id.values()}
        ),
        "max_year_share": _max_year_share(event_by_id.values()),
        "duration_q95_ratio": _ratio(event_q95, atomic_q95),
        "short_interval_drop_rate": _ratio(
            sum(int(row["confirmed_day_count"]) < d for row in normal), len(normal)
        ),
        "confirmed_event_coverage": _ratio(
            qualified_key_count, eligible_valid_daily_count
        ),
        "retrospective_qualified_confirmed_coverage": _ratio(
            retrospective_key_count, eligible_valid_daily_count
        ),
        "asof_qualified_confirmed_coverage": _ratio(
            asof_key_count, eligible_valid_daily_count
        ),
    }


def strict_core_comparison(
    primary_events: Mapping[str, set[ExactKey]],
    strict_events: Mapping[str, set[ExactKey]],
    *,
    primary_confirmed_keys: set[ExactKey],
    strict_confirmed_keys: set[ExactKey],
) -> dict[str, int | float | str | None]:
    """Compare strict-core containment using exact security-date membership."""
    strict_core_keys = primary_confirmed_keys & strict_confirmed_keys
    strict_component_keys = (
        set().union(*strict_events.values()) if strict_events else set()
    )
    primary_with_strict = {
        event_id
        for event_id, keys in primary_events.items()
        if keys & strict_component_keys
    }
    crossing = {
        strict_id
        for strict_id, strict_keys in strict_events.items()
        if sum(
            bool(strict_keys & primary_keys) for primary_keys in primary_events.values()
        )
        > 1
    }
    subset_ok = strict_confirmed_keys <= primary_confirmed_keys and not crossing
    strict_count = len(primary_with_strict)
    shell_events = len(primary_events) - strict_count
    shell_days = len(primary_confirmed_keys - strict_core_keys)
    return {
        "strict_core_confirmed_day_count": len(strict_core_keys),
        "strict_core_confirmed_day_share": _ratio(
            len(strict_core_keys), len(primary_confirmed_keys)
        ),
        "strict_core_event_count": strict_count,
        "strict_core_event_share": _ratio(strict_count, len(primary_events)),
        "shell_only_event_count": shell_events,
        "shell_only_confirmed_day_count": shell_days,
        "shell_only_confirmed_day_share": _ratio(
            shell_days, len(primary_confirmed_keys)
        ),
        "strict_core_subset_status": "passed" if subset_ok else "failed",
    }


def deterministic_window_comparison(
    primary_confirmed: set[ExactKey],
    comparison_confirmed: set[ExactKey],
    *,
    primary_eligible: set[ExactKey],
    comparison_eligible: set[ExactKey],
    primary_events: Mapping[str, set[ExactKey]],
    comparison_events: Mapping[str, set[ExactKey]],
    primary_event_spans: Mapping[str, set[ExactKey]] | None = None,
    comparison_event_spans: Mapping[str, set[ExactKey]] | None = None,
    primary_components: Mapping[str, set[ExactKey]] | None = None,
    comparison_components: Mapping[str, set[ExactKey]] | None = None,
) -> dict[str, int | float | None]:
    """Frozen exact-key daily comparison and deterministic greedy 1:1 event match."""
    intersection = primary_confirmed & comparison_confirmed
    union = primary_confirmed | comparison_confirmed
    primary_spans = primary_event_spans or primary_events
    comparison_spans = comparison_event_spans or comparison_events
    candidates: list[tuple[str, str, str, str, str]] = []
    overlapping_primary: set[str] = set()
    for primary_id, pkeys in primary_events.items():
        pspan = primary_spans[primary_id]
        pstart = min(date for _, date in pspan)
        security = _single_security(primary_id, pkeys)
        for comparison_id, ckeys in comparison_events.items():
            cspan = comparison_spans[comparison_id]
            if security != _single_security(comparison_id, ckeys):
                continue
            if _date_spans_overlap(pspan, cspan):
                overlapping_primary.add(primary_id)
            if not pkeys & ckeys:
                continue
            cstart = min(date for _, date in cspan)
            candidates.append((pstart, cstart, primary_id, comparison_id, security))
    matched_primary: set[str] = set()
    matched_comparison: set[str] = set()
    for _, _, primary_id, comparison_id, _ in sorted(candidates):
        if primary_id in matched_primary or comparison_id in matched_comparison:
            continue
        matched_primary.add(primary_id)
        matched_comparison.add(comparison_id)
    primary_component_map = primary_components or {}
    comparison_component_map = comparison_components or {}
    overlapping_components = {
        primary_id
        for primary_id, primary_span in primary_component_map.items()
        if any(
            _date_spans_overlap(primary_span, comparison_span)
            for comparison_span in comparison_component_map.values()
        )
    }
    overlapping_comparison_components = {
        comparison_id
        for comparison_id, comparison_span in comparison_component_map.items()
        if any(
            _date_spans_overlap(comparison_span, primary_span)
            for primary_span in primary_component_map.values()
        )
    }
    return {
        "intersection_confirmed_days": len(intersection),
        "W120_only_confirmed_days": len(primary_confirmed - comparison_confirmed),
        "W250_only_confirmed_days": len(comparison_confirmed - primary_confirmed),
        "union_confirmed_days": len(union),
        "confirmed_day_jaccard": _ratio(len(intersection), len(union)),
        "W120_own_eligible_days": len(primary_eligible),
        "W250_own_eligible_days": len(comparison_eligible),
        "common_eligible_days": len(primary_eligible & comparison_eligible),
        "matched_event_count": len(matched_primary),
        # Frozen wording is "events with overlapping zone spans": count primary events,
        # never many-to-many pairs.
        "overlapping_event_count": len(overlapping_primary),
        "W120_only_event_count": len(primary_events) - len(matched_primary),
        "W250_only_event_count": len(comparison_events) - len(matched_comparison),
        "component_overlap_count": len(overlapping_components),
        "W120_only_component_count": len(primary_component_map)
        - len(overlapping_components),
        "W250_only_component_count": len(comparison_component_map)
        - len(overlapping_comparison_components),
    }


def create_metric_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Build corrected T03 profiles from source-level scan tables."""
    if not con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='transition_entity_ledger'"
    ).fetchone()[0]:
        con.execute(
            """CREATE TEMP TABLE transition_entity_ledger(candidate_cell_id VARCHAR,
            security_id VARCHAR,transition_ordinal INTEGER,entity_kind VARCHAR,
            entity_id VARCHAR,from_state VARCHAR,to_state VARCHAR,reason_code VARCHAR)"""
        )
    atomic_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('route_atomic_interval')").fetchall()
    }
    if "source_geometry_affected" not in atomic_columns:
        con.execute(
            "ALTER TABLE route_atomic_interval ADD COLUMN source_geometry_affected BOOLEAN DEFAULT false"
        )
    event_columns = {
        row[1] for row in con.execute("PRAGMA table_info('event_zone')").fetchall()
    }
    if "bridged_day_count" not in event_columns:
        con.execute(
            "ALTER TABLE event_zone ADD COLUMN bridged_day_count INTEGER DEFAULT 0"
        )
    if "zone_revision" not in event_columns:
        con.execute("ALTER TABLE event_zone ADD COLUMN zone_revision INTEGER DEFAULT 0")
    membership_columns = {
        row[1]
        for row in con.execute(
            "PRAGMA table_info('event_zone_membership_daily')"
        ).fetchall()
    }
    for column in ("prequalification_member", "unqualified_reentry_member"):
        if column not in membership_columns:
            con.execute(
                f"ALTER TABLE event_zone_membership_daily ADD COLUMN {column} BOOLEAN DEFAULT false"
            )
    con.execute(_CORE_PROFILE_SQL)
    _create_strict_core_profile(con)
    _create_window_profile(con)
    con.execute(_FINAL_PROFILE_SQL)
    con.execute(_DIAGNOSTIC_PROFILE_SQL)


def _create_strict_core_profile(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP TABLE IF EXISTS strict_core_shell_profile")
    con.execute(
        """CREATE TABLE strict_core_shell_profile(
        primary_candidate_cell_id VARCHAR, sidecar_candidate_cell_id VARCHAR,
        strict_core_confirmed_day_count BIGINT, strict_core_confirmed_day_share DOUBLE,
        strict_core_event_count BIGINT, strict_core_event_share DOUBLE,
        shell_only_event_count BIGINT, shell_only_confirmed_day_count BIGINT,
        shell_only_confirmed_day_share DOUBLE, strict_core_subset_status VARCHAR)"""
    )
    for primary, sidecar in con.execute(
        "SELECT primary_candidate_cell_id,sidecar_candidate_cell_id FROM strict_pairs ORDER BY 1,2"
    ).fetchall():
        primary_events = _event_key_sets(con, primary)
        strict_events = _event_key_sets(con, sidecar)
        primary_days = _confirmed_keys(con, primary)
        strict_days = _confirmed_keys(con, sidecar)
        value = strict_core_comparison(
            primary_events,
            strict_events,
            primary_confirmed_keys=primary_days,
            strict_confirmed_keys=strict_days,
        )
        con.execute(
            "INSERT INTO strict_core_shell_profile VALUES (?,?,?,?,?,?,?,?,?,?)",
            [primary, sidecar, *value.values()],
        )


def _create_window_profile(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP TABLE IF EXISTS window_overlap_comparison")
    con.execute("DROP TABLE IF EXISTS window_supplemental_source")
    con.execute(
        """CREATE TABLE window_overlap_comparison(
        primary_candidate_cell_id VARCHAR, comparison_candidate_cell_id VARCHAR,
        intersection_confirmed_days BIGINT, W120_only_confirmed_days BIGINT,
        W250_only_confirmed_days BIGINT, union_confirmed_days BIGINT,
        confirmed_day_jaccard DOUBLE, W120_own_eligible_days BIGINT,
        W250_own_eligible_days BIGINT, common_eligible_days BIGINT,
        matched_event_count BIGINT, overlapping_event_count BIGINT)"""
    )
    con.execute(
        """CREATE TABLE window_supplemental_source(
        primary_candidate_cell_id VARCHAR,comparison_candidate_cell_id VARCHAR,
        W120_only_event_count BIGINT,W250_only_event_count BIGINT,
        component_overlap_count BIGINT,W120_only_component_count BIGINT,
        W250_only_component_count BIGINT)"""
    )
    for primary, comparison in con.execute(
        "SELECT primary_candidate_cell_id,comparison_candidate_cell_id FROM window_pairs ORDER BY 1,2"
    ).fetchall():
        value = deterministic_window_comparison(
            _confirmed_keys(con, primary),
            _confirmed_keys(con, comparison),
            primary_eligible=_eligible_keys(con, primary),
            comparison_eligible=_eligible_keys(con, comparison),
            primary_events=_event_key_sets(con, primary),
            comparison_events=_event_key_sets(con, comparison),
            primary_event_spans=_event_span_sets(con, primary),
            comparison_event_spans=_event_span_sets(con, comparison),
            primary_components=_component_span_sets(con, primary),
            comparison_components=_component_span_sets(con, comparison),
        )
        con.execute(
            "INSERT INTO window_overlap_comparison VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [primary, comparison, *list(value.values())[:10]],
        )
        con.execute(
            "INSERT INTO window_supplemental_source VALUES (?,?,?,?,?,?,?)",
            [primary, comparison, *list(value.values())[10:]],
        )


def _event_key_sets(
    con: duckdb.DuckDBPyConnection, cell: str
) -> dict[str, set[ExactKey]]:
    output: dict[str, set[ExactKey]] = {}
    rows = con.execute(
        """SELECT scan_event_id,security_id,CAST(trade_date AS VARCHAR)
        FROM event_zone_membership_daily
        WHERE candidate_cell_id=? AND event_zone_member AND confirmed_state
          AND retrospective_component_member ORDER BY 1,2,3""",
        [cell],
    ).fetchall()
    for event_id, security, trade_date in rows:
        output.setdefault(event_id, set()).add((security, trade_date))
    return output


def _component_span_sets(
    con: duckdb.DuckDBPyConnection, cell: str
) -> dict[str, set[ExactKey]]:
    output: dict[str, set[ExactKey]] = {}
    if not _table_exists(con, "qualified_component"):
        return output
    rows = con.execute(
        """SELECT q.component_id,m.security_id,CAST(m.trade_date AS VARCHAR)
        FROM qualified_component q JOIN event_zone_membership_daily m
          ON m.candidate_cell_id=q.candidate_cell_id AND m.security_id=q.security_id
         AND m.trade_date BETWEEN q.start_date AND q.end_date
        WHERE q.candidate_cell_id=? AND q.qualified AND m.confirmed_state
        ORDER BY 1,2,3""",
        [cell],
    ).fetchall()
    for component_id, security, trade_date in rows:
        output.setdefault(component_id, set()).add((security, trade_date))
    return output


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name=?",
            [table],
        ).fetchone()[0]
    )


def _event_span_sets(
    con: duckdb.DuckDBPyConnection, cell: str
) -> dict[str, set[ExactKey]]:
    output: dict[str, set[ExactKey]] = {}
    rows = con.execute(
        """SELECT scan_event_id,security_id,CAST(trade_date AS VARCHAR)
        FROM event_zone_membership_daily
        WHERE candidate_cell_id=? AND event_zone_member ORDER BY 1,2,3""",
        [cell],
    ).fetchall()
    for event_id, security, trade_date in rows:
        output.setdefault(event_id, set()).add((security, trade_date))
    return output


def _confirmed_keys(con: duckdb.DuckDBPyConnection, cell: str) -> set[ExactKey]:
    return {
        (security, trade_date)
        for security, trade_date in con.execute(
            """SELECT security_id,CAST(trade_date AS VARCHAR)
            FROM atomic_confirmed_daily WHERE candidate_cell_id=? AND confirmed_state""",
            [cell],
        ).fetchall()
    }


def _eligible_keys(con: duckdb.DuckDBPyConnection, cell: str) -> set[ExactKey]:
    return {
        (security, trade_date)
        for security, trade_date in con.execute(
            """SELECT security_id,CAST(trade_date AS VARCHAR)
            FROM atomic_confirmed_daily
            WHERE candidate_cell_id=? AND eligible AND quality_state='valid'""",
            [cell],
        ).fetchall()
    }


def _single_security(event_id: str, keys: set[ExactKey]) -> str:
    securities = {security for security, _ in keys}
    if len(securities) != 1:
        raise ValueError(f"event_security_not_unique:{event_id}")
    return next(iter(securities))


def _date_spans_overlap(left: set[ExactKey], right: set[ExactKey]) -> bool:
    if not left or not right:
        return False
    left_security = _single_security("left_span", left)
    if left_security != _single_security("right_span", right):
        return False
    left_dates = [date for _, date in left]
    right_dates = [date for _, date in right]
    return min(left_dates) <= max(right_dates) and min(right_dates) <= max(left_dates)


def _max_year_share(events: Iterable[Mapping[str, Any]]) -> float | None:
    counts: dict[str, int] = {}
    for row in events:
        year = str(row["start_date"])[:4]
        counts[year] = counts.get(year, 0) + 1
    return _ratio(max(counts.values(), default=0), sum(counts.values()))


def _ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


_CORE_PROFILE_SQL = r"""
CREATE TABLE atomic_baseline_profile AS
SELECT c.candidate_cell_id,c.route_id,
       count(DISTINCT (r.security_id,r.trade_date)) FILTER
         (WHERE r.eligible AND r.quality_state='valid') eligible_days,
       count(DISTINCT (r.security_id,r.trade_date)) FILTER
         (WHERE r.eligible AND r.quality_state='valid' AND r.confirmed_state) confirmed_state_days,
       confirmed_state_days::DOUBLE/nullif(eligible_days,0) confirmed_state_coverage,
       (SELECT count(*) FROM route_atomic_interval i WHERE i.route_id=c.route_id)
         atomic_confirmed_interval_count
FROM cell_registry c JOIN route_daily r USING(route_id) GROUP BY 1,2;

CREATE TABLE d_qualification_profile AS
WITH component AS (
 SELECT q.candidate_cell_id,
        count(*) FILTER (WHERE q.qualified) qualified_component_count,
        count(*) FILTER (WHERE NOT q.qualified AND l.normally_ended) unqualified_component_count,
        sum(q.confirmed_day_count) FILTER (WHERE q.qualified) qualified_days
 FROM qualified_component q JOIN component_source_lineage l
   USING(candidate_cell_id,security_id,component_id) GROUP BY 1
), member AS (
 SELECT candidate_cell_id,
        count(DISTINCT (security_id,trade_date)) FILTER
          (WHERE eligible AND quality_state='valid' AND confirmed_state
             AND retrospective_component_member AND event_zone_member) retrospective_days,
        count(DISTINCT (security_id,trade_date)) FILTER
          (WHERE eligible AND quality_state='valid' AND confirmed_state
             AND component_qualified_as_of AND event_zone_member) asof_days
 FROM event_zone_membership_daily GROUP BY 1
)
SELECT c.candidate_cell_id,c.d,
       coalesce(x.qualified_component_count,0) qualified_component_count,
       coalesce(x.unqualified_component_count,0) unqualified_component_count,
       coalesce(x.qualified_days,0)::DOUBLE/nullif(a.confirmed_state_days,0)
         retained_confirmed_day_ratio,
       coalesce(m.retrospective_days,0)::DOUBLE/nullif(a.eligible_days,0)
         retrospective_qualified_confirmed_coverage,
       coalesce(m.asof_days,0)::DOUBLE/nullif(a.eligible_days,0)
         asof_qualified_confirmed_coverage
FROM cell_registry c JOIN atomic_baseline_profile a USING(candidate_cell_id)
LEFT JOIN component x USING(candidate_cell_id) LEFT JOIN member m USING(candidate_cell_id);

CREATE TABLE dg_event_zone_profile AS
WITH pending AS (
 SELECT candidate_cell_id,
   count(*) FILTER (WHERE prior_state='QUALIFIED_ACTIVE') active_zone_count,
   count(*) FILTER (WHERE prior_state='GAP_PENDING') gap_pending_zone_count,
   count(*) FILTER (WHERE prior_state='REENTRY_PENDING_QUALIFICATION') reentry_pending_zone_count
 FROM (SELECT candidate_cell_id,entity_id,to_state,
        lag(to_state) OVER (PARTITION BY candidate_cell_id,security_id,entity_id ORDER BY transition_ordinal) prior_state
       FROM transition_entity_ledger WHERE entity_kind='event_zone')
 WHERE to_state='RIGHT_CENSORED' GROUP BY 1
), zone AS (
 SELECT candidate_cell_id,count(DISTINCT scan_event_id) qualified_event_count,
        sum(confirmed_day_count) confirmed_days,sum(zone_span_days) span_days,
        sum(raw_false_bridged_day_count) raw_false_days,
        sum(preconfirmation_gap_day_count) preconfirmation_days,
        sum(total_nonconfirmed_gap_day_count) nonconfirmed_days,
        max(max_raw_false_gap_days) max_raw_false_gap_days,
        max(max_total_gap_span_days) max_total_gap_span_days
 FROM event_zone GROUP BY 1
), coverage AS (
 SELECT candidate_cell_id,count(DISTINCT (security_id,trade_date)) qualified_confirmed_days
 FROM event_zone_membership_daily
 WHERE eligible AND quality_state='valid' AND confirmed_state
   AND retrospective_component_member AND event_zone_member GROUP BY 1
), reentry AS (
 SELECT candidate_cell_id,count(DISTINCT reentry_attempt_id) unqualified_reentry_count
 FROM reentry_attempt WHERE outcome='unqualified_reentry' GROUP BY 1
)
SELECT c.candidate_cell_id,c.d,c.g,coalesce(z.qualified_event_count,0) qualified_event_count,
       coalesce(v.qualified_confirmed_days,0)::DOUBLE/nullif(a.eligible_days,0)
         confirmed_event_coverage,
       coalesce(pn.active_zone_count,0) active_zone_count,
       coalesce(pn.gap_pending_zone_count,0) gap_pending_zone_count,
       coalesce(pn.reentry_pending_zone_count,0) reentry_pending_zone_count,
       coalesce(r.unqualified_reentry_count,0) unqualified_reentry_count,
       coalesce(z.confirmed_days,0)::DOUBLE/nullif(z.span_days,0) confirmed_density,
       coalesce(z.raw_false_days,0) raw_false_bridged_day_count,
       coalesce(z.preconfirmation_days,0) preconfirmation_gap_day_count,
       coalesce(z.nonconfirmed_days,0) total_nonconfirmed_gap_day_count,
       coalesce(z.raw_false_days,0)::DOUBLE/nullif(z.span_days,0) raw_false_bridged_day_ratio,
       coalesce(z.nonconfirmed_days,0)::DOUBLE/nullif(z.span_days,0) nonconfirmed_gap_ratio,
       coalesce(z.max_raw_false_gap_days,0) max_raw_false_gap_days,
       coalesce(z.max_total_gap_span_days,0) max_total_gap_span_days
FROM cell_registry c JOIN atomic_baseline_profile a USING(candidate_cell_id)
LEFT JOIN zone z USING(candidate_cell_id) LEFT JOIN coverage v USING(candidate_cell_id)
LEFT JOIN reentry r USING(candidate_cell_id) LEFT JOIN pending pn USING(candidate_cell_id);

CREATE TABLE transition_aggregate_profile AS
SELECT candidate_cell_id,from_state,to_state,reason_code,count(*) transition_count,
       count(*) FILTER (WHERE to_state='FINALIZED_WITH_QUALITY_BREAK'
         OR reason_code LIKE '%quality%') hard_break_count
FROM transition_profile GROUP BY ALL;

CREATE VIEW strict_pairs AS
SELECT p.candidate_cell_id primary_candidate_cell_id,s.candidate_cell_id sidecar_candidate_cell_id
FROM cell_registry p JOIN cell_registry s
 ON p.state_line=s.state_line AND p.W=s.W AND p.d=s.d AND p.g=s.g
AND p.candidate_role='primary' AND s.candidate_role='strict_core_reference';

CREATE VIEW strict_core_window_comparison AS
SELECT x.primary_candidate_cell_id,x.sidecar_candidate_cell_id,
       p.security_id,p.trade_date,p.confirmed_state primary_confirmed_state,
       coalesce(s.confirmed_state,false) strict_core_confirmed_state,
       (coalesce(s.confirmed_state,false) AND NOT p.confirmed_state) subset_violation
FROM strict_pairs x JOIN atomic_confirmed_daily p
 ON p.candidate_cell_id=x.primary_candidate_cell_id
LEFT JOIN atomic_confirmed_daily s ON s.candidate_cell_id=x.sidecar_candidate_cell_id
 AND s.security_id=p.security_id AND s.trade_date=p.trade_date
UNION ALL
SELECT x.primary_candidate_cell_id,x.sidecar_candidate_cell_id,
       s.security_id,s.trade_date,false primary_confirmed_state,
       s.confirmed_state strict_core_confirmed_state,s.confirmed_state subset_violation
FROM strict_pairs x JOIN atomic_confirmed_daily s
 ON s.candidate_cell_id=x.sidecar_candidate_cell_id
LEFT JOIN atomic_confirmed_daily p ON p.candidate_cell_id=x.primary_candidate_cell_id
 AND p.security_id=s.security_id AND p.trade_date=s.trade_date
WHERE p.security_id IS NULL;

CREATE VIEW window_pairs AS
SELECT a.candidate_cell_id primary_candidate_cell_id,b.candidate_cell_id comparison_candidate_cell_id
FROM cell_registry a JOIN cell_registry b
 ON a.candidate_role=b.candidate_role AND a.state_line=b.state_line
AND a.d=b.d AND a.g=b.g AND a.W=120 AND b.W=250;

CREATE TABLE parameter_response_audit AS
WITH response AS (
 SELECT c.route_id,c.d,count(DISTINCT qualified_event_count) event_count_variants,
        count(DISTINCT raw_false_bridged_day_count) bridge_count_variants
 FROM dg_event_zone_profile p JOIN cell_registry c USING(candidate_cell_id)
 GROUP BY c.route_id,c.d
)
SELECT route_id,d,'g_response' audit_name,
       CASE WHEN event_count_variants>1 OR bridge_count_variants>1
         THEN 'responsive' ELSE 'invariant_requires_explanation' END status,
       event_count_variants,bridge_count_variants FROM response;
"""


_FINAL_PROFILE_SQL = r"""
CREATE TABLE metric_results AS
WITH event_numbered AS (
 SELECT e.*,row_number() OVER (PARTITION BY candidate_cell_id ORDER BY zone_span_days,scan_event_id) rn,
        count(*) OVER (PARTITION BY candidate_cell_id) n
 FROM event_zone e
), event_metric AS (
 SELECT candidate_cell_id,count(DISTINCT scan_event_id) qualified_event_count,
        count(DISTINCT security_id) unique_securities,
        count(*) FILTER (WHERE component_count>1)::DOUBLE/nullif(count(*),0) merge_ratio,
        count(*) FILTER (WHERE status='RIGHT_CENSORED')::DOUBLE/nullif(count(*),0) open_event_ratio,
        max(zone_span_days) FILTER (WHERE rn=CAST(ceil(0.95*n) AS BIGINT)) event_q95
 FROM event_numbered GROUP BY 1
), atomic_numbered AS (
 SELECT i.route_id,i.confirmed_day_count,
        row_number() OVER (PARTITION BY i.route_id ORDER BY i.confirmed_day_count,i.interval_id) rn,
        count(*) OVER (PARTITION BY i.route_id) n
 FROM route_atomic_interval i
), atomic_q95 AS (
 SELECT route_id,max(confirmed_day_count) FILTER
   (WHERE rn=CAST(ceil(0.95*n) AS BIGINT)) atomic_q95 FROM atomic_numbered GROUP BY 1
), year_metric AS (
 SELECT candidate_cell_id,count(*) nonzero_years,max(year_count) max_year_count,
        sum(year_count) total_year_count
 FROM (SELECT e.candidate_cell_id,year(q.start_date) event_year,
              count(DISTINCT e.scan_event_id) year_count
       FROM event_zone e JOIN qualified_component q
         ON q.candidate_cell_id=e.candidate_cell_id AND q.security_id=e.security_id
        AND q.component_id=e.first_component_id GROUP BY 1,2) GROUP BY 1
), drop_metric AS (
 SELECT c.candidate_cell_id,
        count(*) FILTER (WHERE l.normally_ended AND q.confirmed_day_count<c.d)::DOUBLE/
          nullif(count(*) FILTER (WHERE l.normally_ended),0) short_interval_drop_rate
 FROM cell_registry c JOIN qualified_component q USING(candidate_cell_id)
 JOIN component_source_lineage l USING(candidate_cell_id,security_id,component_id) GROUP BY 1
)
SELECT c.candidate_cell_id,c.route_id,c.state_line,c.W,c.d,c.g,
       p.qualified_event_count,coalesce(e.unique_securities,0) unique_securities,
       q.retained_confirmed_day_ratio,d.short_interval_drop_rate,
       p.raw_false_bridged_day_ratio bridged_day_ratio,e.merge_ratio,e.open_event_ratio,
       coalesce(y.nonzero_years,0) nonzero_years,
       y.max_year_count::DOUBLE/nullif(y.total_year_count,0) max_year_share,
       e.event_q95::DOUBLE/nullif(a.atomic_q95,0) duration_q95_ratio
FROM cell_registry c JOIN dg_event_zone_profile p USING(candidate_cell_id)
JOIN d_qualification_profile q USING(candidate_cell_id)
LEFT JOIN event_metric e USING(candidate_cell_id) LEFT JOIN year_metric y USING(candidate_cell_id)
LEFT JOIN drop_metric d USING(candidate_cell_id) LEFT JOIN atomic_q95 a USING(route_id);
"""

_DIAGNOSTIC_PROFILE_SQL = r"""
CREATE TABLE atomic_interval_diagnostic_profile AS
WITH ranked AS (
 SELECT route_id,confirmed_day_count,termination_reason,source_geometry_affected,
  row_number() OVER(PARTITION BY route_id ORDER BY confirmed_day_count,interval_id) rn,
  count(*) OVER(PARTITION BY route_id) n
 FROM route_atomic_interval
) SELECT route_id,count(*) atomic_confirmed_interval_count,
 avg(confirmed_day_count) atomic_duration_mean,median(confirmed_day_count) atomic_duration_median,
 max(confirmed_day_count) FILTER(WHERE rn=ceil(.90*n)) atomic_duration_q90,
 max(confirmed_day_count) FILTER(WHERE rn=ceil(.95*n)) atomic_duration_q95,
 count(*) FILTER(WHERE confirmed_day_count=1) atomic_singleton_count,
 count(*) FILTER(WHERE confirmed_day_count=1)::DOUBLE/nullif(count(*),0) atomic_fragment_rate,
 count(*) FILTER(WHERE termination_reason='natural_state_exit') natural_exit_count,
 count(*) FILTER(WHERE termination_reason='quality_interruption') quality_interruption_count,
 count(*) FILTER(WHERE termination_reason='sample_end_censoring') right_censored_atomic_count
FROM ranked GROUP BY 1;

CREATE TABLE component_diagnostic_profile AS
WITH base AS (
 SELECT c.candidate_cell_id,c.d,q.*,l.normally_ended,l.censor_status,
   (c.d-1)::INTEGER qualification_delay_observations
 FROM cell_registry c JOIN qualified_component q USING(candidate_cell_id)
 JOIN component_source_lineage l USING(candidate_cell_id,security_id,component_id)
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY candidate_cell_id ORDER BY qualification_delay_observations,component_id) rn,
   count(*) OVER(PARTITION BY candidate_cell_id) n FROM base WHERE qualified
), member AS (
 SELECT candidate_cell_id,
  count(*) FILTER(WHERE confirmed_state AND retrospective_component_member) retrospective_days,
  count(*) FILTER(WHERE confirmed_state AND component_qualified_as_of) asof_days,
  count(*) FILTER(WHERE confirmed_state AND prequalification_member) prequalification_days
 FROM event_zone_membership_daily GROUP BY 1
), reentry AS (
 SELECT candidate_cell_id,count(*) unqualified_reentry_count FROM reentry_attempt
 WHERE outcome='unqualified_reentry' GROUP BY 1
) SELECT b.candidate_cell_id,
 count(*) FILTER(WHERE b.qualified) qualified_component_count,
 count(*) FILTER(WHERE NOT b.qualified) unqualified_component_count,
 count(*) FILTER(WHERE b.qualified)::DOUBLE/nullif(count(*),0) component_qualification_rate,
 sum(b.confirmed_day_count) FILTER(WHERE b.qualified) qualified_confirmed_day_count,
 coalesce(m.retrospective_days,0) retrospective_qualified_confirmed_day_count,
 coalesce(m.asof_days,0) asof_qualified_confirmed_day_count,
 coalesce(m.prequalification_days,0) prequalification_confirmed_day_count,
 count(*) FILTER(WHERE b.censor_status='right_censored') prequalification_right_censored_count,
 avg(b.qualification_delay_observations) FILTER(WHERE b.qualified) qualification_delay_observations_mean,
 median(b.qualification_delay_observations) FILTER(WHERE b.qualified) qualification_delay_observations_median,
 max(r.qualification_delay_observations) FILTER(WHERE r.rn=ceil(.90*r.n)) qualification_delay_observations_q90,
 max(r.qualification_delay_observations) FILTER(WHERE r.rn=ceil(.95*r.n)) qualification_delay_observations_q95,
 coalesce(x.unqualified_reentry_count,0) unqualified_reentry_count,
 coalesce(x.unqualified_reentry_count,0)::DOUBLE/nullif(count(*) FILTER(WHERE NOT b.qualified),0) unqualified_reentry_rate
FROM base b LEFT JOIN ranked r USING(candidate_cell_id,security_id,component_id)
LEFT JOIN member m USING(candidate_cell_id) LEFT JOIN reentry x USING(candidate_cell_id)
GROUP BY b.candidate_cell_id,m.retrospective_days,m.asof_days,m.prequalification_days,x.unqualified_reentry_count;

CREATE TABLE event_zone_diagnostic_profile AS
WITH ranked AS (
 SELECT e.*,
 row_number() OVER(PARTITION BY candidate_cell_id ORDER BY zone_span_days,scan_event_id) duration_rn,
 row_number() OVER(PARTITION BY candidate_cell_id ORDER BY component_count,scan_event_id) component_rn,
 row_number() OVER(PARTITION BY candidate_cell_id ORDER BY bridge_count,scan_event_id) bridge_rn,
 count(*) OVER(PARTITION BY candidate_cell_id) n
 FROM event_zone e
), security_ranked AS (
 SELECT candidate_cell_id,security_id,count(*) event_count,
  row_number() OVER(PARTITION BY candidate_cell_id ORDER BY count(*),security_id) rn,
  count(*) OVER(PARTITION BY candidate_cell_id) n
 FROM event_zone GROUP BY 1,2
), security_profile AS (
 SELECT candidate_cell_id,avg(event_count) events_per_security_mean,
  median(event_count) events_per_security_median,
  max(event_count) FILTER(WHERE rn=ceil(.90*n)) events_per_security_q90,
  max(event_count) events_per_security_max FROM security_ranked GROUP BY 1
), year_count AS (
 SELECT e.candidate_cell_id,year(q.start_date) event_year,count(*) year_events
 FROM event_zone e JOIN qualified_component q
  ON q.candidate_cell_id=e.candidate_cell_id AND q.security_id=e.security_id
 AND q.component_id=e.first_component_id GROUP BY 1,2
), year_profile AS (
 SELECT candidate_cell_id,count(*) nonzero_years,
  sum(year_events)::DOUBLE/nullif(count(*),0) events_per_year,
  max(year_events)::DOUBLE/nullif(sum(year_events),0) max_year_share
 FROM year_count GROUP BY 1
) SELECT r.candidate_cell_id,
 count(*) qualified_event_count,
 count(*) FILTER(WHERE r.status='FINALIZED') natural_finalized_zone_count,
 count(*) FILTER(WHERE r.status='FINALIZED_WITH_QUALITY_BREAK') quality_break_zone_count,
 count(*) FILTER(WHERE r.status='RIGHT_CENSORED') right_censored_zone_count,
 avg(r.component_count) component_count_mean,median(r.component_count) component_count_median,
 max(r.component_count) FILTER(WHERE r.component_rn=ceil(.90*r.n)) component_count_q90,
 max(r.component_count) FILTER(WHERE r.component_rn=ceil(.95*r.n)) component_count_q95,max(r.component_count) component_count_max,
 avg(r.bridge_count) bridge_count_mean,median(r.bridge_count) bridge_count_median,
 max(r.bridge_count) FILTER(WHERE r.bridge_rn=ceil(.90*r.n)) bridge_count_q90,
 max(r.bridge_count) FILTER(WHERE r.bridge_rn=ceil(.95*r.n)) bridge_count_q95,max(r.bridge_count) bridge_count_max,
 sum(r.zone_span_days) zone_span_days_sum,avg(r.zone_span_days) duration_mean,
 median(r.zone_span_days) duration_median,max(r.zone_span_days) FILTER(WHERE r.duration_rn=ceil(.90*r.n)) duration_q90,
 max(r.zone_span_days) FILTER(WHERE r.duration_rn=ceil(.95*r.n)) duration_q95,max(r.zone_span_days) max_zone_span,
 sum(r.confirmed_day_count)::DOUBLE/nullif(sum(r.zone_span_days),0) confirmed_density,
 sum(r.bridge_count) bridged_gap_count,sum(r.bridged_day_count) bridged_day_count,
 sum(r.raw_false_bridged_day_count) raw_false_bridged_day_count,
 sum(r.preconfirmation_gap_day_count) preconfirmation_gap_day_count,
 sum(r.total_nonconfirmed_gap_day_count) total_nonconfirmed_gap_day_count,
 sum(r.bridged_day_count)::DOUBLE/nullif(sum(r.zone_span_days),0) bridged_day_ratio,
 sum(r.raw_false_bridged_day_count)::DOUBLE/nullif(sum(r.zone_span_days),0) raw_false_bridged_day_ratio,
 sum(r.total_nonconfirmed_gap_day_count)::DOUBLE/nullif(sum(r.zone_span_days),0) nonconfirmed_gap_ratio,
 max(r.max_raw_false_gap_days) max_single_gap,
 count(*) FILTER(WHERE r.component_count>1)::DOUBLE/nullif(count(*),0) merge_ratio,
 sum(r.zone_revision) zone_revision_count,
 max(r.confirmed_day_count)::DOUBLE/nullif(sum(r.confirmed_day_count),0) top_zone_confirmed_day_share,
 count(*) FILTER(WHERE r.status='RIGHT_CENSORED')::DOUBLE/nullif(count(*),0) open_event_ratio,
 max(r.zone_span_days)::DOUBLE/nullif(sum(r.zone_span_days),0) mega_zone_concentration,
 p.active_zone_count,p.gap_pending_zone_count,p.reentry_pending_zone_count,
 p.confirmed_event_coverage,
 sum(r.zone_span_days)::DOUBLE/nullif(ab.eligible_days,0) zone_span_coverage,
 s.events_per_security_mean,s.events_per_security_median,
 s.events_per_security_q90,s.events_per_security_max,
 y.events_per_year,y.nonzero_years,y.max_year_share,
 max(r.zone_span_days) FILTER(WHERE r.duration_rn=ceil(.95*r.n))::DOUBLE/
   nullif(a.atomic_duration_q95,0) duration_q95_ratio
FROM ranked r JOIN cell_registry c USING(candidate_cell_id)
JOIN atomic_interval_diagnostic_profile a USING(route_id)
JOIN dg_event_zone_profile p USING(candidate_cell_id)
JOIN atomic_baseline_profile ab USING(candidate_cell_id)
LEFT JOIN security_profile s USING(candidate_cell_id)
LEFT JOIN year_profile y USING(candidate_cell_id)
GROUP BY r.candidate_cell_id,p.active_zone_count,p.gap_pending_zone_count,
 p.reentry_pending_zone_count,p.confirmed_event_coverage,a.atomic_duration_q95,
 ab.eligible_days,s.events_per_security_mean,s.events_per_security_median,
 s.events_per_security_q90,s.events_per_security_max,y.events_per_year,y.nonzero_years,y.max_year_share;

INSERT INTO event_zone_diagnostic_profile BY NAME
SELECT c.candidate_cell_id,0::BIGINT qualified_event_count,
 0::BIGINT natural_finalized_zone_count,0::BIGINT quality_break_zone_count,
 0::BIGINT right_censored_zone_count,0::BIGINT bridged_gap_count,
 0::BIGINT bridged_day_count,0::BIGINT raw_false_bridged_day_count,
 0::BIGINT preconfirmation_gap_day_count,0::BIGINT total_nonconfirmed_gap_day_count,
 0::BIGINT zone_span_days_sum,p.active_zone_count,p.gap_pending_zone_count,
 p.reentry_pending_zone_count,p.confirmed_event_coverage,0::DOUBLE zone_span_coverage,
 0::DOUBLE events_per_security_mean,0::DOUBLE events_per_security_median,
 0::BIGINT events_per_security_q90,0::BIGINT events_per_security_max,
 0::DOUBLE events_per_year,0::BIGINT nonzero_years,NULL::DOUBLE max_year_share
FROM cell_registry c JOIN dg_event_zone_profile p USING(candidate_cell_id)
WHERE NOT EXISTS(SELECT 1 FROM event_zone_diagnostic_profile e
                 WHERE e.candidate_cell_id=c.candidate_cell_id);

CREATE TABLE strict_core_diagnostic_profile AS
SELECT b.*,b.shell_only_confirmed_day_share expansion_shell_confirmed_day_share,
 b.shell_only_event_count::DOUBLE/nullif(b.strict_core_event_count+b.shell_only_event_count,0) shell_only_zone_ratio,
 (SELECT count(*) FROM qualified_component q WHERE q.candidate_cell_id=b.sidecar_candidate_cell_id AND q.qualified)
   strict_core_qualified_component_count,
 (SELECT count(*) FROM qualified_component q WHERE q.candidate_cell_id=b.sidecar_candidate_cell_id AND q.qualified)::DOUBLE/nullif(
   (SELECT count(*) FROM qualified_component q WHERE q.candidate_cell_id=b.primary_candidate_cell_id AND q.qualified),0)
   strict_core_qualified_component_share,
 (SELECT count(*) FROM qualified_component p
   WHERE p.candidate_cell_id=b.primary_candidate_cell_id AND p.qualified AND NOT EXISTS(
    SELECT 1 FROM qualified_component s WHERE s.candidate_cell_id=b.sidecar_candidate_cell_id
     AND s.qualified AND s.security_id=p.security_id
     AND s.start_date<=p.end_date AND p.start_date<=s.end_date)) shell_only_qualified_component_count,
 b.strict_core_confirmed_day_count::DOUBLE/nullif(
   (SELECT sum(zone_span_days) FROM event_zone e WHERE e.candidate_cell_id=b.sidecar_candidate_cell_id),0)
   strict_core_confirmed_density
FROM strict_core_shell_profile b;

CREATE TABLE window_diagnostic_profile AS
SELECT w.*,s.W120_only_event_count,s.W250_only_event_count,s.component_overlap_count,
 s.W120_only_component_count,s.W250_only_component_count,
 intersection_confirmed_days::DOUBLE/nullif(W120_own_eligible_days,0) W120_own_overlap_rate,
 intersection_confirmed_days::DOUBLE/nullif(W250_own_eligible_days,0) W250_own_overlap_rate,
 intersection_confirmed_days::DOUBLE/nullif(common_eligible_days,0) common_overlap_rate,
 matched_event_count::DOUBLE/nullif(matched_event_count+overlapping_event_count,0) event_match_rate
FROM window_overlap_comparison w JOIN window_supplemental_source s
 USING(primary_candidate_cell_id,comparison_candidate_cell_id);

CREATE TABLE parameter_invariant_profile AS
WITH gp AS (
 SELECT ca.route_id,ca.d,a.candidate_cell_id left_id,b.candidate_cell_id right_id,
  a.qualified_event_count event_a,b.qualified_event_count event_b,
  ea.bridged_gap_count bridge_a,eb.bridged_gap_count bridge_b,
  ea.bridged_day_count bridge_days_a,eb.bridged_day_count bridge_days_b,
  ea.zone_span_days_sum span_a,eb.zone_span_days_sum span_b,
  aa.confirmed_state_days confirmed_a,ab.confirmed_state_days confirmed_b,
  da.retrospective_qualified_confirmed_day_count retrospective_a,
  db.retrospective_qualified_confirmed_day_count retrospective_b,
  da.asof_qualified_confirmed_day_count asof_a,db.asof_qualified_confirmed_day_count asof_b
 FROM dg_event_zone_profile a JOIN cell_registry ca USING(candidate_cell_id)
 JOIN cell_registry cb ON cb.route_id=ca.route_id AND cb.d=ca.d AND cb.g=ca.g+1
 JOIN dg_event_zone_profile b ON b.candidate_cell_id=cb.candidate_cell_id
 JOIN event_zone_diagnostic_profile ea ON ea.candidate_cell_id=a.candidate_cell_id
 JOIN event_zone_diagnostic_profile eb ON eb.candidate_cell_id=b.candidate_cell_id
 JOIN atomic_baseline_profile aa ON aa.candidate_cell_id=a.candidate_cell_id
 JOIN atomic_baseline_profile ab ON ab.candidate_cell_id=b.candidate_cell_id
 JOIN component_diagnostic_profile da ON da.candidate_cell_id=a.candidate_cell_id
 JOIN component_diagnostic_profile db ON db.candidate_cell_id=b.candidate_cell_id
), dp AS (
 SELECT ca.route_id,ca.g,
  a.qualified_component_count component_a,b.qualified_component_count component_b,
  da.retrospective_qualified_confirmed_day_count retrospective_a,
  db.retrospective_qualified_confirmed_day_count retrospective_b,
  da.asof_qualified_confirmed_day_count asof_a,db.asof_qualified_confirmed_day_count asof_b,
  da.qualification_delay_observations_mean delay_a,
  db.qualification_delay_observations_mean delay_b
 FROM d_qualification_profile a JOIN cell_registry ca USING(candidate_cell_id)
 JOIN cell_registry cb ON cb.route_id=ca.route_id AND cb.g=ca.g AND cb.d=ca.d+1
 JOIN d_qualification_profile b ON b.candidate_cell_id=cb.candidate_cell_id
 JOIN component_diagnostic_profile da ON da.candidate_cell_id=a.candidate_cell_id
 JOIN component_diagnostic_profile db ON db.candidate_cell_id=b.candidate_cell_id
), g0 AS (
 SELECT c.route_id,c.d,p.qualified_event_count,q.qualified_component_count,
  e.bridged_gap_count,e.bridged_day_count
 FROM cell_registry c JOIN dg_event_zone_profile p USING(candidate_cell_id)
 JOIN d_qualification_profile q USING(candidate_cell_id)
 JOIN event_zone_diagnostic_profile e USING(candidate_cell_id) WHERE c.g=0
)
SELECT 'g_event_count_nonincreasing' check_id,route_id||':d='||d "scope",count(*) FILTER(WHERE event_b>event_a) observed_violations,'=0' expected_rule FROM gp GROUP BY 1,2
UNION ALL SELECT 'g_bridge_count_nondecreasing',route_id||':d='||d,count(*) FILTER(WHERE bridge_b<bridge_a),'=0' FROM gp GROUP BY 1,2
UNION ALL SELECT 'g_bridged_days_nondecreasing',route_id||':d='||d,count(*) FILTER(WHERE bridge_days_b<bridge_days_a),'=0' FROM gp GROUP BY 1,2
UNION ALL SELECT 'g_zone_coverage_nondecreasing',route_id||':d='||d,count(*) FILTER(WHERE span_b<span_a),'=0' FROM gp GROUP BY 1,2
UNION ALL SELECT 'g_confirmed_days_invariant',route_id||':d='||d,count(*) FILTER(WHERE confirmed_b<>confirmed_a),'=0' FROM gp GROUP BY 1,2
UNION ALL SELECT 'g_retrospective_days_invariant',route_id||':d='||d,count(*) FILTER(WHERE retrospective_b<>retrospective_a),'=0' FROM gp GROUP BY 1,2
UNION ALL SELECT 'g_asof_days_invariant',route_id||':d='||d,count(*) FILTER(WHERE asof_b<>asof_a),'=0' FROM gp GROUP BY 1,2
UNION ALL SELECT 'd_component_nonincreasing',route_id||':g='||g,count(*) FILTER(WHERE component_b>component_a),'=0' FROM dp GROUP BY 1,2
UNION ALL SELECT 'd_retrospective_days_nonincreasing',route_id||':g='||g,count(*) FILTER(WHERE retrospective_b>retrospective_a),'=0' FROM dp GROUP BY 1,2
UNION ALL SELECT 'd_asof_days_nonincreasing',route_id||':g='||g,count(*) FILTER(WHERE asof_b>asof_a),'=0' FROM dp GROUP BY 1,2
UNION ALL SELECT 'd_qualification_delay_nondecreasing',route_id||':g='||g,count(*) FILTER(WHERE delay_b<delay_a),'=0' FROM dp GROUP BY 1,2
UNION ALL SELECT 'g_zero_identity',route_id||':d='||d,count(*) FILTER(WHERE qualified_event_count<>qualified_component_count OR bridged_gap_count<>0 OR bridged_day_count<>0),'=0' FROM g0 GROUP BY 1,2;
"""
