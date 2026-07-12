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
    }


def create_metric_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Build corrected T03 profiles from source-level scan tables."""
    con.execute(_CORE_PROFILE_SQL)
    _create_strict_core_profile(con)
    _create_window_profile(con)
    con.execute(_FINAL_PROFILE_SQL)


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
    con.execute(
        """CREATE TABLE window_overlap_comparison(
        primary_candidate_cell_id VARCHAR, comparison_candidate_cell_id VARCHAR,
        intersection_confirmed_days BIGINT, W120_only_confirmed_days BIGINT,
        W250_only_confirmed_days BIGINT, union_confirmed_days BIGINT,
        confirmed_day_jaccard DOUBLE, W120_own_eligible_days BIGINT,
        W250_own_eligible_days BIGINT, common_eligible_days BIGINT,
        matched_event_count BIGINT, overlapping_event_count BIGINT)"""
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
        )
        con.execute(
            "INSERT INTO window_overlap_comparison VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [primary, comparison, *value.values()],
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
WITH zone AS (
 SELECT candidate_cell_id,count(DISTINCT scan_event_id) qualified_event_count,
        count(*) FILTER (WHERE status='QUALIFIED_ACTIVE') active_zone_count,
        count(*) FILTER (WHERE status='GAP_PENDING') gap_pending_zone_count,
        count(*) FILTER (WHERE status='REENTRY_PENDING_QUALIFICATION') reentry_pending_zone_count,
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
       coalesce(z.active_zone_count,0) active_zone_count,
       coalesce(z.gap_pending_zone_count,0) gap_pending_zone_count,
       coalesce(z.reentry_pending_zone_count,0) reentry_pending_zone_count,
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
LEFT JOIN reentry r USING(candidate_cell_id);

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
