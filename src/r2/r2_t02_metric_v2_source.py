# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "configs/r2/r2_t02_metric_dictionary.v2.json"

LAYERS = {
    "atomic_confirmed_state_baseline": [
        "eligible_days",
        "confirmed_state_days",
        "confirmed_state_coverage",
        "atomic_confirmed_interval_count",
        "atomic_duration_mean",
        "atomic_duration_median",
        "atomic_duration_q90",
        "atomic_duration_q95",
        "atomic_singleton_count",
        "atomic_fragment_rate",
        "natural_exit_count",
        "quality_interruption_count",
        "left_censored_atomic_count",
        "right_censored_atomic_count",
        "upstream_reconciliation_status",
    ],
    "d_qualified_component": [
        "qualified_component_count",
        "unqualified_component_count",
        "component_qualification_rate",
        "qualified_confirmed_days_retrospective",
        "qualified_confirmed_days_as_of",
        "retrospective_qualified_coverage",
        "asof_qualified_risk_set_coverage",
        "prequalification_confirmed_days",
        "retained_confirmed_day_ratio",
        "short_interval_drop_rate",
        "qualification_delay_confirmed_days",
        "qualification_delay_calendar_mean",
        "qualification_delay_calendar_median",
        "unqualified_reentry_count",
        "unqualified_reentry_rate",
        "prequalification_right_censored_count",
    ],
    "g_grouped_event_zone": [
        "total_event_zone_count",
        "natural_finalized_zone_count",
        "quality_break_zone_count",
        "right_censored_zone_count",
        "active_zone_count",
        "gap_pending_zone_count",
        "reentry_pending_zone_count",
        "zone_confirmed_day_count",
        "zone_span_days",
        "confirmed_event_coverage",
        "zone_span_coverage",
        "component_interval_count_mean",
        "component_interval_count_p90",
        "bridge_count_mean",
        "bridge_count_p90",
        "bridged_gap_days",
        "max_single_gap_days",
        "bridged_gap_ratio",
        "confirmed_density",
        "merge_ratio",
        "zone_revision_count",
        "mega_zone_ratio",
        "max_zone_span",
        "top_zone_confirmed_day_share",
        "nonzero_years",
        "max_year_share",
        "within_route_overlapping_event_count",
    ],
    "strict_core_shell": [
        "strict_core_confirmed_day_share",
        "expansion_shell_confirmed_day_share",
        "strict_core_qualified_component_share",
        "shell_only_qualified_component_count",
        "zones_with_strict_core_ratio",
        "shell_only_zone_ratio",
        "strict_core_density_within_zone",
        "subset_status",
    ],
    "window_comparison": [
        "confirmed_state_overlap",
        "qualified_component_overlap",
        "event_zone_overlap",
        "intersection_days",
        "W120_only_days",
        "W250_only_days",
        "confirmed_jaccard",
        "matched_event_count",
        "overlapping_event_count",
    ],
}


def definition(layer: str, metric_id: str) -> dict[str, str]:
    is_rate = metric_id.endswith(
        ("_rate", "_ratio", "_coverage", "_share", "_density", "_jaccard")
    )
    is_status = metric_id.endswith("_status")
    is_duration = "duration_" in metric_id or metric_id.endswith(
        ("_mean", "_median", "_p90", "_q90", "_q95")
    )
    entity = "eligible_day"
    if "interval" in metric_id or "atomic" in metric_id:
        entity = "atomic_confirmed_interval"
    elif (
        "component" in metric_id
        or "qualification" in metric_id
        or "reentry" in metric_id
    ):
        entity = "confirmed_component"
    elif "zone" in metric_id or "bridge" in metric_id or "event" in metric_id:
        entity = "event_zone"
    elif layer == "window_comparison":
        entity = "paired_window_route"
    aggregation = (
        "exact contract invariant status"
        if is_status
        else (
            "explicit numerator divided by the corresponding eligible entity population"
            if is_rate
            else "distribution statistic over the named entity"
            if is_duration
            else "count distinct entities satisfying the metric predicate"
        )
    )
    denominator = (
        "not_applicable"
        if not is_rate
        else f"eligible {entity} population in the same route/cell/scope"
    )
    censoring = (
        "exclude right-censored and open entities from duration/failure denominators"
        if is_duration or "drop" in metric_id
        else "include observed-to-date entities; classify censoring separately"
    )
    keys = {
        "eligible_day": "route_id,candidate_role,security_id,trading_date",
        "atomic_confirmed_interval": "route_id,candidate_role,security_id,atomic_interval_id",
        "confirmed_component": "route_id,candidate_role,d,security_id,component_id",
        "event_zone": "route_id,candidate_role,d,g,security_id,scan_event_id,zone_revision",
        "paired_window_route": "state_line,candidate_role,d,g,W120_entity_id,W250_entity_id",
    }
    if "year" in metric_id:
        deduplication_key = (
            "route_id,candidate_role,d,g,security_id,event_year,scan_event_id"
        )
    elif "bridge" in metric_id or "gap" in metric_id:
        deduplication_key = (
            "route_id,candidate_role,d,g,security_id,scan_event_id,bridge_segment_id"
        )
    else:
        deduplication_key = keys[entity]
    if is_status:
        open_policy = "evaluate the exact contract invariant over both finalized and explicitly censored records"
    elif (
        "right_censored" in metric_id or "active" in metric_id or "pending" in metric_id
    ):
        open_policy = "include only the explicitly named right-censored/open state as observed at sample end"
    elif is_duration:
        open_policy = "exclude open and right-censored entities from completed-duration distributions"
    elif "coverage" in metric_id or "days" in metric_id:
        open_policy = "include observed confirmed membership through the evaluation cutoff without fabricated closure"
    elif "count" in metric_id:
        open_policy = "count finalized entities; open entities enter only when the metric name explicitly requests them"
    else:
        open_policy = "apply the declared censoring policy and expose open entities in separate state counts"
    return {
        "metric_id": metric_id,
        "layer": layer,
        "entity_level": entity,
        "numerator_or_aggregation": aggregation,
        "denominator": denominator,
        "deduplication_key": deduplication_key,
        "included_rows": "eligible rows in the declared layer and denominator scope",
        "excluded_rows": "unknown,diagnostic_required,blocked,ineligible,missing_observation",
        "censoring_policy": censoring,
        "open_event_policy": open_policy,
        "denominator_scope": "own_eligible or exact common_W120_W250 within state_line and candidate_role",
        "expected_parameter_response": "exact invariant or preregistered directional diagnostic; total zones need not be monotone in d",
        "hard_gate_usage": "exact invariant, preregistered hard-gate input, or disclosed diagnostic without winner score",
        "null_or_zero_denominator_policy": "return null plus explicit reason; hard-gate inputs fail closed",
        "availability_basis": "as-of observed rows; retrospective membership carries membership_available_time and is never backfilled",
    }


def main() -> None:
    metrics = [
        definition(layer, metric) for layer, names in LAYERS.items() for metric in names
    ]
    OUTPUT.write_text(
        json.dumps(
            {"dictionary_version": "r2_t02_metric_dictionary.v2", "metrics": metrics},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
