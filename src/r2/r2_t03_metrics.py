# ruff: noqa: E501
from __future__ import annotations

import duckdb


def create_metric_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Build the frozen T02 profile contracts from the executed scan tables."""
    con.execute(
        """
        CREATE TABLE atomic_baseline_profile AS
        SELECT c.candidate_cell_id, c.route_id,
               count(*) FILTER (WHERE r.eligible) AS eligible_days,
               count(*) FILTER (WHERE r.confirmed_state) AS confirmed_state_days,
               count(*) FILTER (WHERE r.confirmed_state)::DOUBLE /
                 nullif(count(*) FILTER (WHERE r.eligible), 0) AS confirmed_state_coverage,
               (SELECT count(*) FROM route_atomic_interval i
                 WHERE i.route_id=c.route_id) AS atomic_confirmed_interval_count
        FROM cell_registry c JOIN route_daily r USING(route_id)
        GROUP BY c.candidate_cell_id, c.route_id;

        CREATE TABLE d_qualification_profile AS
        WITH component AS (
          SELECT candidate_cell_id,
                 count(*) FILTER (WHERE qualified) qualified_component_count,
                 count(*) FILTER (WHERE NOT qualified) unqualified_component_count,
                 sum(confirmed_day_count) FILTER (WHERE qualified) qualified_days
          FROM qualified_component GROUP BY candidate_cell_id
        ), member AS (
          SELECT candidate_cell_id,
                 count(*) FILTER (WHERE qualified_event_risk_set_eligible) asof_days
          FROM event_zone_membership_daily GROUP BY candidate_cell_id
        )
        SELECT c.candidate_cell_id, c.d,
               coalesce(x.qualified_component_count,0) qualified_component_count,
               coalesce(x.unqualified_component_count,0) unqualified_component_count,
               coalesce(x.qualified_days,0)::DOUBLE /
                 nullif(a.confirmed_state_days,0) retrospective_qualified_confirmed_coverage,
               coalesce(m.asof_days,0)::DOUBLE /
                 nullif(a.confirmed_state_days,0) asof_qualified_confirmed_coverage
        FROM cell_registry c JOIN atomic_baseline_profile a USING(candidate_cell_id)
        LEFT JOIN component x USING(candidate_cell_id)
        LEFT JOIN member m USING(candidate_cell_id);

        CREATE TABLE dg_event_zone_profile AS
        WITH zone AS (
          SELECT candidate_cell_id, count(*) qualified_event_count,
                 count(*) FILTER (WHERE status='QUALIFIED_ACTIVE') active_zone_count,
                 count(*) FILTER (WHERE status='GAP_PENDING') gap_pending_zone_count,
                 count(*) FILTER (WHERE status='REENTRY_PENDING_QUALIFICATION') reentry_pending_zone_count,
                 sum(confirmed_day_count) confirmed_days,
                 sum(zone_span_days) span_days,
                 sum(raw_false_bridged_day_count) raw_false_days,
                 sum(preconfirmation_gap_day_count) preconfirmation_days,
                 sum(total_nonconfirmed_gap_day_count) nonconfirmed_days,
                 max(max_raw_false_gap_days) max_raw_false_gap_days,
                 max(max_total_gap_span_days) max_total_gap_span_days
          FROM event_zone GROUP BY candidate_cell_id
        ), reentry AS (
          SELECT candidate_cell_id,
                 count(*) FILTER (WHERE unqualified_reentry_member) unqualified_reentry_count
          FROM event_zone_membership_daily GROUP BY candidate_cell_id
        )
        SELECT c.candidate_cell_id, c.d, c.g,
               coalesce(z.qualified_event_count,0) qualified_event_count,
               coalesce(z.confirmed_days,0)::DOUBLE /
                 nullif(a.confirmed_state_days,0) confirmed_event_coverage,
               coalesce(z.active_zone_count,0) active_zone_count,
               coalesce(z.gap_pending_zone_count,0) gap_pending_zone_count,
               coalesce(z.reentry_pending_zone_count,0) reentry_pending_zone_count,
               coalesce(r.unqualified_reentry_count,0) unqualified_reentry_count,
               coalesce(z.confirmed_days,0)::DOUBLE / nullif(z.span_days,0) confirmed_density,
               coalesce(z.raw_false_days,0) raw_false_bridged_day_count,
               coalesce(z.preconfirmation_days,0) preconfirmation_gap_day_count,
               coalesce(z.nonconfirmed_days,0) total_nonconfirmed_gap_day_count,
               coalesce(z.raw_false_days,0)::DOUBLE / nullif(z.span_days,0) raw_false_bridged_day_ratio,
               coalesce(z.nonconfirmed_days,0)::DOUBLE / nullif(z.span_days,0) nonconfirmed_gap_ratio,
               coalesce(z.max_raw_false_gap_days,0) max_raw_false_gap_days,
               coalesce(z.max_total_gap_span_days,0) max_total_gap_span_days
        FROM cell_registry c JOIN atomic_baseline_profile a USING(candidate_cell_id)
        LEFT JOIN zone z USING(candidate_cell_id) LEFT JOIN reentry r USING(candidate_cell_id);

        CREATE TABLE transition_aggregate_profile AS
        SELECT candidate_cell_id, from_state, to_state, reason_code,
               count(*) transition_count,
               count(*) FILTER (WHERE to_state='FINALIZED_WITH_QUALITY_BREAK'
                 OR reason_code LIKE '%quality%') hard_break_count
        FROM transition_profile GROUP BY ALL;

        CREATE VIEW strict_pairs AS
        SELECT p.candidate_cell_id primary_candidate_cell_id,
               s.candidate_cell_id sidecar_candidate_cell_id
        FROM cell_registry p JOIN cell_registry s
          ON p.state_line=s.state_line AND p.W=s.W AND p.d=s.d AND p.g=s.g
         AND p.candidate_role='primary' AND s.candidate_role='strict_core_reference';

        CREATE VIEW strict_core_window_comparison AS
        SELECT x.primary_candidate_cell_id, x.sidecar_candidate_cell_id,
               p.security_id, p.trade_date,
               p.confirmed_state primary_confirmed_state,
               s.confirmed_state strict_core_confirmed_state,
               (s.confirmed_state AND NOT p.confirmed_state) subset_violation
        FROM strict_pairs x
        JOIN atomic_confirmed_daily p ON p.candidate_cell_id=x.primary_candidate_cell_id
        JOIN atomic_confirmed_daily s ON s.candidate_cell_id=x.sidecar_candidate_cell_id
          AND s.security_id=p.security_id AND s.trade_date=p.trade_date;

        CREATE TABLE strict_core_shell_profile AS
        WITH days AS (
          SELECT primary_candidate_cell_id, sidecar_candidate_cell_id,
                 count(*) FILTER (WHERE primary_confirmed_state) primary_days,
                 count(*) FILTER (WHERE strict_core_confirmed_state) strict_days
          FROM strict_core_window_comparison GROUP BY 1,2
        ), event_counts AS (
          SELECT candidate_cell_id, count(*) event_count FROM event_zone GROUP BY 1
        ), events AS (
          SELECT x.primary_candidate_cell_id, x.sidecar_candidate_cell_id,
                 coalesce(p.event_count,0) primary_events,
                 coalesce(s.event_count,0) strict_events
          FROM strict_pairs x
          LEFT JOIN event_counts p ON p.candidate_cell_id=x.primary_candidate_cell_id
          LEFT JOIN event_counts s ON s.candidate_cell_id=x.sidecar_candidate_cell_id
        )
        SELECT d.primary_candidate_cell_id, d.sidecar_candidate_cell_id,
               d.strict_days::DOUBLE/nullif(d.primary_days,0) strict_core_confirmed_day_share,
               e.strict_events::DOUBLE/nullif(e.primary_events,0) strict_core_event_share,
               greatest(e.primary_events-e.strict_events,0) shell_only_event_count,
               greatest(d.primary_days-d.strict_days,0)::DOUBLE/nullif(d.primary_days,0)
                 shell_only_confirmed_day_share
        FROM days d JOIN events e USING(primary_candidate_cell_id,sidecar_candidate_cell_id);

        CREATE VIEW window_pairs AS
        SELECT a.candidate_cell_id primary_candidate_cell_id,
               b.candidate_cell_id comparison_candidate_cell_id
        FROM cell_registry a JOIN cell_registry b
          ON a.candidate_role=b.candidate_role AND a.state_line=b.state_line
         AND a.d=b.d AND a.g=b.g AND a.W=120 AND b.W=250;

        CREATE TABLE window_overlap_comparison AS
        WITH daily AS (
          SELECT x.primary_candidate_cell_id, x.comparison_candidate_cell_id,
                 count(*) FILTER (WHERE a.confirmed_state AND b.confirmed_state) intersection_days,
                 count(*) FILTER (WHERE a.confirmed_state OR b.confirmed_state) union_days
          FROM window_pairs x
          JOIN atomic_confirmed_daily a ON a.candidate_cell_id=x.primary_candidate_cell_id
          JOIN atomic_confirmed_daily b ON b.candidate_cell_id=x.comparison_candidate_cell_id
            AND b.security_id=a.security_id AND b.trade_date=a.trade_date GROUP BY 1,2
        ), bounds AS (
          SELECT candidate_cell_id, security_id, scan_event_id,
                 min(trade_date) start_date, max(trade_date) end_date
          FROM event_zone_membership_daily WHERE event_zone_member GROUP BY 1,2,3
        ), overlap AS (
          SELECT x.primary_candidate_cell_id, x.comparison_candidate_cell_id,
                 count(*) overlapping_event_count,
                 count(*) FILTER (WHERE a.start_date=b.start_date AND a.end_date=b.end_date)
                   matched_event_count
          FROM window_pairs x JOIN bounds a ON a.candidate_cell_id=x.primary_candidate_cell_id
          JOIN bounds b ON b.candidate_cell_id=x.comparison_candidate_cell_id
            AND b.security_id=a.security_id AND a.start_date<=b.end_date AND b.start_date<=a.end_date
          GROUP BY 1,2
        )
        SELECT d.primary_candidate_cell_id, d.comparison_candidate_cell_id,
               d.intersection_days intersection_confirmed_days,
               d.intersection_days::DOUBLE/nullif(d.union_days,0) confirmed_day_jaccard,
               coalesce(o.matched_event_count,0) matched_event_count,
               coalesce(o.overlapping_event_count,0) overlapping_event_count
        FROM daily d LEFT JOIN overlap o USING(primary_candidate_cell_id,comparison_candidate_cell_id);

        CREATE TABLE parameter_response_audit AS
        WITH response AS (
          SELECT c.route_id, c.d,
                 count(DISTINCT qualified_event_count) event_count_variants,
                 count(DISTINCT raw_false_bridged_day_count) bridge_count_variants
          FROM dg_event_zone_profile p JOIN cell_registry c USING(candidate_cell_id)
          GROUP BY c.route_id,c.d
        )
        SELECT route_id, d, 'g_response' audit_name,
               CASE WHEN event_count_variants>1 OR bridge_count_variants>1
                    THEN 'responsive' ELSE 'invariant_requires_explanation' END status,
               event_count_variants, bridge_count_variants FROM response;

        CREATE TABLE metric_results AS
        WITH event_metric AS (
          SELECT candidate_cell_id, count(DISTINCT security_id) unique_securities,
                 sum(bridge_count)::DOUBLE/nullif(count(*),0) merge_ratio,
                 count(*) FILTER (WHERE status='RIGHT_CENSORED')::DOUBLE/nullif(count(*),0)
                   open_event_ratio,
                 quantile_cont(zone_span_days,0.95)::DOUBLE /
                   nullif(quantile_cont(zone_span_days,0.5),0) duration_q95_ratio
          FROM event_zone GROUP BY 1
        ), year_metric AS (
          SELECT candidate_cell_id, count(*) nonzero_years,
                 max(year_count) max_year_count, sum(year_count) total_year_count
          FROM (
            SELECT candidate_cell_id, year(membership_available_time) event_year,
                   count(DISTINCT scan_event_id) year_count
            FROM event_zone_membership_daily GROUP BY 1,2
          ) GROUP BY 1
        )
        SELECT c.candidate_cell_id, c.route_id, c.state_line, c.W, c.d, c.g,
               p.qualified_event_count,
               coalesce(e.unique_securities,0) unique_securities,
               p.confirmed_event_coverage retained_confirmed_day_ratio,
               (q.unqualified_component_count::DOUBLE /
                 nullif(q.qualified_component_count+q.unqualified_component_count,0)) short_interval_drop_rate,
               p.raw_false_bridged_day_ratio bridged_day_ratio,
               e.merge_ratio, e.open_event_ratio,
               coalesce(y.nonzero_years,0) nonzero_years,
               y.max_year_count::DOUBLE/nullif(y.total_year_count,0) max_year_share,
               e.duration_q95_ratio
        FROM cell_registry c JOIN dg_event_zone_profile p USING(candidate_cell_id)
        JOIN d_qualification_profile q USING(candidate_cell_id)
        LEFT JOIN event_metric e USING(candidate_cell_id)
        LEFT JOIN year_metric y USING(candidate_cell_id);
        """
    )
