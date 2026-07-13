# ruff: noqa: E501
from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import ROOT, repo_rel, write_csv, write_json


class R2T03IndependentValidationError(RuntimeError):
    pass


ScopedEntityKey = tuple[str, str]
STRICT_CORE_FIELDS = (
    "strict_core_confirmed_day_count",
    "strict_core_confirmed_day_share",
    "strict_core_event_count",
    "strict_core_event_share",
    "shell_only_event_count",
    "shell_only_confirmed_day_count",
    "shell_only_confirmed_day_share",
    "strict_core_subset_status",
)
WINDOW_CORE_FIELDS = (
    "intersection_confirmed_days",
    "W120_only_confirmed_days",
    "W250_only_confirmed_days",
    "union_confirmed_days",
    "confirmed_day_jaccard",
    "W120_own_eligible_days",
    "W250_own_eligible_days",
    "common_eligible_days",
    "matched_event_count",
    "overlapping_event_count",
)
WINDOW_SUPPLEMENTAL_FIELDS = (
    "W120_only_event_count",
    "W250_only_event_count",
    "component_overlap_count",
    "W120_only_component_count",
    "W250_only_component_count",
)
CORE_METRIC_FIELDS = (
    "qualified_event_count",
    "unique_securities",
    "retained_confirmed_day_ratio",
    "confirmed_event_coverage",
    "retrospective_qualified_confirmed_coverage",
    "asof_qualified_confirmed_coverage",
    "short_interval_drop_rate",
    "bridged_day_ratio",
    "merge_ratio",
    "open_event_ratio",
    "nonzero_years",
    "max_year_share",
    "duration_q95_ratio",
    "unqualified_reentry_count",
    "qualified_component_count",
    "unqualified_component_count",
    "raw_false_bridged_day_count",
    "preconfirmation_gap_day_count",
    "total_nonconfirmed_gap_day_count",
)
STRICT_DIAGNOSTIC_FIELDS = (
    "expansion_shell_confirmed_day_share",
    "strict_core_qualified_component_count",
    "strict_core_qualified_component_share",
    "shell_only_qualified_component_count",
    "strict_core_confirmed_density",
)
ATOMIC_DIAGNOSTIC_FIELDS = (
    "atomic_diag_interval_count",
    "atomic_diag_duration_mean",
    "atomic_diag_duration_median",
    "atomic_diag_duration_q90",
    "atomic_diag_duration_q95",
    "atomic_diag_singleton_count",
    "atomic_diag_fragment_rate",
    "atomic_diag_natural_exit_count",
    "atomic_diag_quality_interruption_count",
    "atomic_diag_right_censored_count",
)
COMPONENT_DIAGNOSTIC_FIELDS = (
    "component_diag_qualified_count",
    "component_diag_unqualified_count",
    "component_diag_qualification_rate",
    "component_diag_qualified_days",
    "component_diag_retrospective_days",
    "component_diag_asof_days",
    "component_diag_prequalification_days",
    "component_diag_prequalification_right_censored",
    "component_diag_delay_mean",
    "component_diag_delay_median",
    "component_diag_delay_q90",
    "component_diag_delay_q95",
    "component_diag_unqualified_reentry_count",
    "component_diag_unqualified_reentry_rate",
)
EVENT_DIAGNOSTIC_FIELDS = (
    "event_diag_count",
    "event_diag_natural_count",
    "event_diag_quality_count",
    "event_diag_right_censored_count",
    "event_diag_component_q90",
    "event_diag_component_q95",
    "event_diag_component_mean",
    "event_diag_component_median",
    "event_diag_component_max",
    "event_diag_bridge_q90",
    "event_diag_bridge_q95",
    "event_diag_bridge_mean",
    "event_diag_bridge_median",
    "event_diag_bridge_max",
    "event_diag_duration_q90",
    "event_diag_duration_q95",
    "event_diag_zone_span_sum",
    "event_diag_zone_span_coverage",
    "event_diag_duration_mean",
    "event_diag_duration_median",
    "event_diag_max_zone_span",
    "event_diag_duration_q95_ratio",
    "event_diag_confirmed_density",
    "event_diag_bridge_count",
    "event_diag_bridged_days",
    "event_diag_raw_false_days",
    "event_diag_preconfirmation_days",
    "event_diag_total_gap_days",
    "event_diag_bridged_day_ratio",
    "event_diag_raw_false_ratio",
    "event_diag_nonconfirmed_ratio",
    "event_diag_max_single_gap",
    "event_diag_top_zone_share",
    "event_diag_merge_ratio",
    "event_diag_revision_count",
    "event_diag_mega_zone_concentration",
    "event_diag_open_ratio",
    "event_diag_active_pending",
    "event_diag_gap_pending",
    "event_diag_reentry_pending",
    "event_diag_confirmed_coverage",
    "event_diag_events_per_security_mean",
    "event_diag_events_per_security_median",
    "event_diag_events_per_security_q90",
    "event_diag_events_per_security_max",
    "event_diag_events_per_year",
    "event_diag_nonzero_years",
    "event_diag_max_year_share",
)
TRANSITION_SOURCE_FIELDS = (
    "qualification",
    "unqualified_close",
    "event_creation",
    "event_terminal",
    "accepted_bridge_paths",
    "rejected_reentry_paths",
)
TRANSITION_FIELDS = tuple(f"transition_{field}" for field in TRANSITION_SOURCE_FIELDS)


def _independent_dense_input(
    sparse_rows: Sequence[Mapping[str, Any]],
    expected_dates: Sequence[str],
    expected_empty_status: Mapping[str, str],
    *,
    security_id: str,
) -> list[dict[str, Any]]:
    """Construct dense raw input independently from sparse source and D2 status."""
    sparse = {str(row["trade_date"]): dict(row) for row in sparse_rows}
    if len(sparse) != len(sparse_rows):
        raise R2T03IndependentValidationError("oracle_duplicate_sparse_daily_key")
    dense = []
    for trade_date in expected_dates:
        if trade_date in sparse:
            dense.append(sparse[trade_date])
            continue
        reason = expected_empty_status.get(trade_date)
        if reason not in {"suspended", "listing_pause"}:
            raise R2T03IndependentValidationError(
                f"oracle_unclassified_expected_empty:{security_id}:{trade_date}:{reason}"
            )
        dense.append(
            {
                "security_id": security_id,
                "trade_date": trade_date,
                "eligible": False,
                "quality_state": "expected_empty",
                "raw_state": None,
                "available_time": f"{trade_date}T15:00:00+08:00",
                "expected_empty_reason": reason,
                "source_row_present": False,
            }
        )
    unexpected = set(sparse) - set(expected_dates)
    if unexpected:
        raise R2T03IndependentValidationError(
            f"oracle_sparse_row_outside_expected:{sorted(unexpected)[0]}"
        )
    return dense


def _build_base_oracle(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_dates: Sequence[str],
    k: int = 3,
) -> dict[str, Any]:
    """Replay K-confirmation exactly once for one route-security source timeline."""
    by_date = {str(row["trade_date"]): row for row in rows}
    if len(by_date) != len(rows):
        raise R2T03IndependentValidationError("oracle_duplicate_daily_key")
    timeline: list[dict[str, Any]] = []
    streak = 0
    active = False
    confirmed_start = ""
    last_confirmed = ""
    for trade_date in expected_dates:
        if trade_date not in by_date:
            raise R2T03IndependentValidationError(
                f"missing_expected_trading_row:{trade_date}"
            )
        source = by_date[trade_date]
        eligible_valid = bool(source["eligible"]) and source["quality_state"] == "valid"
        raw = source.get("raw_state")
        hard_break = not eligible_valid or raw is None
        streak = streak + 1 if eligible_valid and raw is True else 0
        confirmed = bool(eligible_valid and raw is True and streak >= k)
        reason = ""
        confirmation_time = ""
        confirmed_end = ""
        exit_time = ""
        if not active and confirmed:
            active = True
            confirmed_start = trade_date
            reason = "k3_confirmation"
            confirmation_time = str(source["available_time"])
        elif active and not confirmed:
            reason = "quality_interruption" if hard_break else "natural_state_exit"
            confirmed_end = last_confirmed
            exit_time = str(source["available_time"])
            active = False
            confirmed_start = ""
        elif active and confirmed:
            reason = "confirmed_maintained"
        elif hard_break:
            reason = "hard_break_reset"
        elif raw is False:
            reason = "ordinary_false"
        timeline.append(
            {
                **source,
                "trade_date": trade_date,
                "confirmed_state": confirmed,
                "confirmed_start_date": confirmed_start if confirmed else "",
                "confirmation_time": confirmation_time,
                "confirmed_end_date": confirmed_end,
                "exit_observation_time": exit_time,
                "state_risk_set_eligible": confirmed and eligible_valid,
                "reason_code": reason,
                "hard_break": hard_break,
            }
        )
        if confirmed:
            last_confirmed = trade_date
    intervals: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for index, row in enumerate(timeline):
        if row["confirmed_state"]:
            if current is None:
                current = {"start": index, "end": index, "confirmed_day_count": 1}
            else:
                current["end"] = index
                current["confirmed_day_count"] += 1
        elif current is not None:
            current["termination_reason"] = (
                "quality_interruption" if row["hard_break"] else "natural_state_exit"
            )
            intervals.append(current)
            current = None
    if current is not None:
        current["termination_reason"] = "sample_end_censoring"
        intervals.append(current)

    return {
        "timeline": timeline,
        "atomic_intervals": intervals,
        "eligible_valid_keys": {
            (str(row["security_id"]), row["trade_date"])
            for row in timeline
            if row["eligible"] and row["quality_state"] == "valid"
        },
        "confirmed_keys": {
            (str(row["security_id"]), row["trade_date"])
            for row in timeline
            if row["confirmed_state"]
        },
        "atomic_spans": [interval["confirmed_day_count"] for interval in intervals],
    }


def source_timeline_oracle(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_dates: Sequence[str],
    d: int,
    g: int,
    k: int = 3,
) -> dict[str, Any]:
    """Compatibility wrapper around the independent two-stage oracle."""
    return _derive_cell_oracle(
        _build_base_oracle(rows, expected_dates=expected_dates, k=k), d=d, g=g
    )


def _derive_cell_oracle(base: Mapping[str, Any], *, d: int, g: int) -> dict[str, Any]:
    """Derive one d-by-g cell without replaying the shared K3 base timeline."""
    timeline = base["timeline"]
    intervals = base["atomic_intervals"]

    components = [
        {
            **interval,
            "component_id": f"component_{index:03d}",
            "qualified": interval["confirmed_day_count"] >= d,
        }
        for index, interval in enumerate(intervals, start=1)
    ]
    prequalification_confirmed_keys = set().union(
        *(
            {
                (str(timeline[index]["security_id"]), timeline[index]["trade_date"])
                for index in range(
                    int(component["start"]),
                    min(int(component["start"]) + d - 1, int(component["end"]) + 1),
                )
            }
            for component in components
            if component["qualified"]
        ),
        set(),
    )
    zones: list[dict[str, Any]] = []
    open_zone: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    unqualified_reentry_count = 0
    transition_counts = {
        "qualification": 0,
        "unqualified_close": 0,
        "event_creation": 0,
        "event_terminal": 0,
        "accepted_bridge_paths": 0,
        "rejected_reentry_paths": 0,
    }
    for component in components:
        if component["qualified"]:
            transition_counts["qualification"] += 1
        elif component["termination_reason"] != "sample_end_censoring":
            transition_counts["unqualified_close"] += 1
        if open_zone is None:
            if component["qualified"]:
                open_zone = _new_oracle_zone(component, timeline, len(zones) + 1)
                transition_counts["event_creation"] += 1
            previous = component
            continue
        assert previous is not None
        gap = timeline[previous["end"] + 1 : component["start"]]
        decision = _earliest_oracle_decision(gap, g)
        hard_break = decision == "quality_break"
        raw_false = [
            row
            for row in gap
            if row["eligible"]
            and row["quality_state"] == "valid"
            and row.get("raw_state") is False
        ]
        mergeable_gap = decision is None and len(raw_false) <= g
        if not component["qualified"]:
            if mergeable_gap:
                prequalification_confirmed_keys.update(
                    _component_keys(component, timeline)
                )
                if component["termination_reason"] == "natural_state_exit":
                    unqualified_reentry_count += 1
                transition_counts["rejected_reentry_paths"] += 1
                open_zone["status"] = (
                    "RIGHT_CENSORED"
                    if component["termination_reason"] == "sample_end_censoring"
                    else "FINALIZED_WITH_QUALITY_BREAK"
                    if component["termination_reason"] == "quality_interruption"
                    else "FINALIZED"
                )
                if open_zone["status"] == "RIGHT_CENSORED":
                    open_zone["censor_prior_state"] = "REENTRY_PENDING_QUALIFICATION"
                zones.append(open_zone)
                transition_counts["event_terminal"] += 1
                open_zone = None
            else:
                open_zone["status"] = (
                    "FINALIZED_WITH_QUALITY_BREAK" if hard_break else "FINALIZED"
                )
                zones.append(open_zone)
                transition_counts["event_terminal"] += 1
                open_zone = None
            previous = component
            continue
        if mergeable_gap and previous["qualified"]:
            preconfirmation = [
                row
                for row in gap
                if row["eligible"]
                and row["quality_state"] == "valid"
                and row.get("raw_state") is True
                and not row["confirmed_state"]
            ]
            open_zone["component_count"] += 1
            open_zone["bridge_count"] += 1
            open_zone["raw_false_bridged_day_count"] += len(raw_false)
            open_zone["preconfirmation_gap_day_count"] += len(preconfirmation)
            open_zone["total_nonconfirmed_gap_day_count"] += len(raw_false) + len(
                preconfirmation
            )
            open_zone["max_raw_false_gap_days"] = max(
                open_zone["max_raw_false_gap_days"], len(raw_false)
            )
            open_zone["zone_span_days"] += len(gap) + component["confirmed_day_count"]
            open_zone["confirmed_keys"].update(_component_keys(component, timeline))
            open_zone["span_keys"].update(
                (str(row["security_id"]), str(row["trade_date"])) for row in gap
            )
            open_zone["span_keys"].update(_component_keys(component, timeline))
            transition_counts["accepted_bridge_paths"] += 1
        else:
            open_zone["status"] = (
                "FINALIZED_WITH_QUALITY_BREAK" if hard_break else "FINALIZED"
            )
            zones.append(open_zone)
            transition_counts["event_terminal"] += 1
            open_zone = _new_oracle_zone(component, timeline, len(zones) + 1)
            transition_counts["event_creation"] += 1
        previous = component
    if open_zone is not None:
        assert previous is not None
        trailing = timeline[int(previous["end"]) + 1 :]
        trailing_decision = _earliest_oracle_decision(trailing, g)
        trailing_hard_break = trailing_decision == "quality_break"
        open_zone["status"] = (
            "FINALIZED_WITH_QUALITY_BREAK"
            if trailing_hard_break
            else "FINALIZED"
            if trailing_decision == "raw_false_gap_exceeds_g"
            else "RIGHT_CENSORED"
        )
        if open_zone["status"] == "RIGHT_CENSORED":
            open_zone["censor_prior_state"] = (
                "REENTRY_PENDING_QUALIFICATION"
                if previous.get("qualified") is False
                else "GAP_PENDING"
                if trailing
                else "QUALIFIED_ACTIVE"
            )
        zones.append(open_zone)
        transition_counts["event_terminal"] += 1

    eligible_valid_keys = base["eligible_valid_keys"]
    confirmed_keys = base["confirmed_keys"]
    qualified_keys = set().union(*(zone["confirmed_keys"] for zone in zones), set())
    qualified_asof_keys = set().union(
        *(
            {
                (
                    str(timeline[index]["security_id"]),
                    str(timeline[index]["trade_date"]),
                )
                for index in range(
                    int(component["start"]) + d - 1, int(component["end"]) + 1
                )
            }
            for component in components
            if component["qualified"]
        ),
        set(),
    )
    normally_ended = [
        component
        for component in components
        if component["termination_reason"] == "natural_state_exit"
    ]
    event_spans = [zone["zone_span_days"] for zone in zones]
    atomic_spans = base["atomic_spans"]
    return {
        "timeline": timeline,
        "atomic_intervals": intervals,
        "components": components,
        "zones": zones,
        "confirmed_keys": confirmed_keys,
        "qualified_confirmed_keys": qualified_keys,
        "eligible_valid_keys": eligible_valid_keys,
        "qualified_asof_keys": qualified_asof_keys,
        "prequalification_confirmed_keys": prequalification_confirmed_keys,
        "qualified_event_count": len(zones),
        "bridge_count": sum(zone["bridge_count"] for zone in zones),
        "membership_count": sum(zone["zone_span_days"] for zone in zones),
        "unique_security_count": int(bool(zones)),
        "qualified_component_count": sum(
            component["qualified"] for component in components
        ),
        "unqualified_component_count": sum(
            not component["qualified"]
            and component["termination_reason"] == "natural_state_exit"
            for component in components
        ),
        "prequalification_right_censored_count": sum(
            not component["qualified"]
            and component["termination_reason"] == "sample_end_censoring"
            for component in components
        ),
        "raw_false_bridged_day_count": sum(
            zone["raw_false_bridged_day_count"] for zone in zones
        ),
        "preconfirmation_gap_day_count": sum(
            zone["preconfirmation_gap_day_count"] for zone in zones
        ),
        "total_nonconfirmed_gap_day_count": sum(
            zone["total_nonconfirmed_gap_day_count"] for zone in zones
        ),
        "open_event_count": sum(zone["status"] == "RIGHT_CENSORED" for zone in zones),
        "merged_event_count": sum(zone["component_count"] > 1 for zone in zones),
        "event_spans": event_spans,
        "atomic_spans": atomic_spans,
        "event_years": [zone["start_year"] for zone in zones],
        "confirmed_event_coverage": _oracle_ratio(
            len(qualified_keys), len(eligible_valid_keys)
        ),
        "merge_ratio": _oracle_ratio(
            sum(zone["component_count"] > 1 for zone in zones), len(zones)
        ),
        "open_event_ratio": _oracle_ratio(
            sum(zone["status"] == "RIGHT_CENSORED" for zone in zones), len(zones)
        ),
        "retained_confirmed_day_ratio": _oracle_ratio(
            len(qualified_keys), len(confirmed_keys)
        ),
        "retrospective_qualified_confirmed_coverage": _oracle_ratio(
            len(qualified_keys), len(eligible_valid_keys)
        ),
        "asof_qualified_confirmed_coverage": _oracle_ratio(
            len(qualified_asof_keys), len(eligible_valid_keys)
        ),
        "bridged_day_ratio": _oracle_ratio(
            sum(zone["raw_false_bridged_day_count"] for zone in zones),
            sum(zone["zone_span_days"] for zone in zones),
        ),
        "duration_q95_ratio": _oracle_ratio(
            _oracle_nearest(event_spans, 0.95), _oracle_nearest(atomic_spans, 0.95)
        ),
        "short_interval_drop_rate": _oracle_ratio(
            sum(component["confirmed_day_count"] < d for component in normally_ended),
            len(normally_ended),
        ),
        "unqualified_reentry_count": unqualified_reentry_count,
        "transition_closure": transition_counts,
    }


def independent_strict_core_oracle(
    primary_events: Mapping[str | ScopedEntityKey, set[tuple[str, str]]],
    strict_events: Mapping[str | ScopedEntityKey, set[tuple[str, str]]],
    primary_days: set[tuple[str, str]],
    strict_days: set[tuple[str, str]],
    primary_components: Mapping[str | ScopedEntityKey, set[tuple[str, str]]]
    | None = None,
    strict_components: Mapping[str | ScopedEntityKey, set[tuple[str, str]]]
    | None = None,
    strict_spans: Mapping[str | ScopedEntityKey, set[tuple[str, str]]] | None = None,
) -> dict[str, Any]:
    primary_events = _independent_scoped_map(primary_events, "primary_event")
    strict_events = _independent_scoped_map(strict_events, "strict_event")
    strict_keys = primary_days & strict_days
    strict_component_keys = (
        set().union(*strict_events.values()) if strict_events else set()
    )
    contained = {
        key for key, values in primary_events.items() if values & strict_component_keys
    }
    crossing = any(
        sum(bool(values & primary) for primary in primary_events.values()) > 1
        for values in strict_events.values()
    )
    primary_component_map = _independent_scoped_map(
        primary_components or {}, "primary_component"
    )
    strict_component_map = _independent_scoped_map(
        strict_components or {}, "strict_component"
    )
    strict_components_by_security = _independent_bucket(strict_component_map)
    shell_only_components = sum(
        not any(
            _independent_spans_overlap(values, strict)
            for strict in strict_components_by_security.get(key[0], {}).values()
        )
        for key, values in primary_component_map.items()
    )
    strict_span_count = sum(len(values) for values in (strict_spans or {}).values())
    return {
        "strict_core_confirmed_day_count": len(strict_keys),
        "strict_core_confirmed_day_share": _oracle_ratio(
            len(strict_keys), len(primary_days)
        ),
        "strict_core_event_count": len(contained),
        "strict_core_event_share": _oracle_ratio(len(contained), len(primary_events)),
        "shell_only_event_count": len(primary_events) - len(contained),
        "shell_only_confirmed_day_count": len(primary_days - strict_keys),
        "shell_only_confirmed_day_share": _oracle_ratio(
            len(primary_days - strict_keys), len(primary_days)
        ),
        "strict_core_subset_status": (
            "passed" if strict_days <= primary_days and not crossing else "failed"
        ),
        "strict_core_qualified_component_count": len(strict_component_map),
        "strict_core_qualified_component_share": _oracle_ratio(
            len(strict_component_map), len(primary_component_map)
        ),
        "shell_only_qualified_component_count": shell_only_components,
        "strict_core_confirmed_density": _oracle_ratio(
            len(strict_days), strict_span_count
        ),
    }


def independent_window_oracle(
    primary_days: set[tuple[str, str]],
    comparison_days: set[tuple[str, str]],
    primary_eligible: set[tuple[str, str]],
    comparison_eligible: set[tuple[str, str]],
    primary_events: Mapping[str | ScopedEntityKey, set[tuple[str, str]]],
    comparison_events: Mapping[str | ScopedEntityKey, set[tuple[str, str]]],
    primary_event_spans: Mapping[str | ScopedEntityKey, set[tuple[str, str]]]
    | None = None,
    comparison_event_spans: Mapping[str | ScopedEntityKey, set[tuple[str, str]]]
    | None = None,
    primary_components: Mapping[str | ScopedEntityKey, set[tuple[str, str]]]
    | None = None,
    comparison_components: Mapping[str | ScopedEntityKey, set[tuple[str, str]]]
    | None = None,
) -> dict[str, Any]:
    intersection, union = primary_days & comparison_days, primary_days | comparison_days
    primary_events = _independent_scoped_map(primary_events, "primary_event")
    comparison_events = _independent_scoped_map(comparison_events, "comparison_event")
    candidate_pairs = []
    overlapping_primary: set[ScopedEntityKey] = set()
    primary_spans = _independent_scoped_map(
        primary_event_spans or primary_events, "primary_event_span"
    )
    comparison_spans = _independent_scoped_map(
        comparison_event_spans or comparison_events, "comparison_event_span"
    )
    comparison_events_by_security = _independent_bucket(comparison_events)
    for primary_id, pkeys in primary_events.items():
        pspan = primary_spans[primary_id]
        for comparison_id, ckeys in comparison_events_by_security.get(
            primary_id[0], {}
        ).items():
            cspan = comparison_spans[comparison_id]
            pdates, cdates = ({key[1] for key in pspan}, {key[1] for key in cspan})
            if min(pdates) <= max(cdates) and min(cdates) <= max(pdates):
                overlapping_primary.add(primary_id)
            if not pkeys & ckeys:
                continue
            candidate_pairs.append(
                (
                    min(pdates),
                    min(cdates),
                    primary_id,
                    comparison_id,
                )
            )
    used_primary: set[ScopedEntityKey] = set()
    used_comparison: set[ScopedEntityKey] = set()
    for _, _, primary_id, comparison_id in sorted(candidate_pairs):
        if primary_id not in used_primary and comparison_id not in used_comparison:
            used_primary.add(primary_id)
            used_comparison.add(comparison_id)
    primary_component_map = _independent_scoped_map(
        primary_components or {}, "primary_component"
    )
    comparison_component_map = _independent_scoped_map(
        comparison_components or {}, "comparison_component"
    )
    comparison_components_by_security = _independent_bucket(comparison_component_map)
    primary_components_by_security = _independent_bucket(primary_component_map)
    overlapping_components = {
        key
        for key, values in primary_component_map.items()
        if any(
            _independent_spans_overlap(values, comparison)
            for comparison in comparison_components_by_security.get(key[0], {}).values()
        )
    }
    overlapping_comparison = {
        key
        for key, values in comparison_component_map.items()
        if any(
            _independent_spans_overlap(values, primary)
            for primary in primary_components_by_security.get(key[0], {}).values()
        )
    }
    return {
        "intersection_confirmed_days": len(intersection),
        "W120_only_confirmed_days": len(primary_days - comparison_days),
        "W250_only_confirmed_days": len(comparison_days - primary_days),
        "union_confirmed_days": len(union),
        "confirmed_day_jaccard": _oracle_ratio(len(intersection), len(union)),
        "W120_own_eligible_days": len(primary_eligible),
        "W250_own_eligible_days": len(comparison_eligible),
        "common_eligible_days": len(primary_eligible & comparison_eligible),
        "matched_event_count": len(used_primary),
        "overlapping_event_count": len(overlapping_primary),
        "W120_only_event_count": len(primary_events) - len(used_primary),
        "W250_only_event_count": len(comparison_events) - len(used_comparison),
        "component_overlap_count": len(overlapping_components),
        "W120_only_component_count": len(primary_component_map)
        - len(overlapping_components),
        "W250_only_component_count": len(comparison_component_map)
        - len(overlapping_comparison),
    }


def _independent_scoped_map(
    values: Mapping[str | ScopedEntityKey, set[tuple[str, str]]], label: str
) -> dict[ScopedEntityKey, set[tuple[str, str]]]:
    output: dict[ScopedEntityKey, set[tuple[str, str]]] = {}
    for local_key, exact_keys in values.items():
        securities = {security for security, _ in exact_keys}
        if len(securities) != 1:
            raise R2T03IndependentValidationError(
                f"{label}_security_not_unique:{local_key}"
            )
        security = next(iter(securities))
        if isinstance(local_key, tuple):
            if len(local_key) != 2 or str(local_key[0]) != security:
                raise R2T03IndependentValidationError(
                    f"{label}_scope_mismatch:{local_key}"
                )
            key = (security, str(local_key[1]))
        else:
            key = (security, str(local_key))
        if key in output:
            raise R2T03IndependentValidationError(f"{label}_identity_not_unique:{key}")
        output[key] = exact_keys
    return output


def _independent_bucket(
    values: Mapping[ScopedEntityKey, set[tuple[str, str]]],
) -> dict[str, dict[ScopedEntityKey, set[tuple[str, str]]]]:
    output: dict[str, dict[ScopedEntityKey, set[tuple[str, str]]]] = {}
    for key, exact_keys in values.items():
        output.setdefault(key[0], {})[key] = exact_keys
    return output


def _independent_spans_overlap(
    left: set[tuple[str, str]], right: set[tuple[str, str]]
) -> bool:
    if not left or not right:
        return False
    left_securities = {security for security, _ in left}
    right_securities = {security for security, _ in right}
    if len(left_securities) != 1 or left_securities != right_securities:
        return False
    left_dates = [date for _, date in left]
    right_dates = [date for _, date in right]
    return min(left_dates) <= max(right_dates) and min(right_dates) <= max(left_dates)


def compare_oracle_metric_targets(
    expected: Mapping[str, Any], production: Mapping[str, Any]
) -> list[str]:
    return [
        f"independent_metric_mismatch:{metric}"
        for metric, value in expected.items()
        if metric not in production or not _equal(value, production[metric])
    ]


def _new_oracle_cell_context(
    cell_id: str, route_id: str, d: int, g: int
) -> dict[str, Any]:
    return {
        "cell_id": cell_id,
        "route_id": route_id,
        "d": d,
        "g": g,
        "aggregate": {
            key: 0
            for key in (
                "events",
                "unique_securities",
                "qualified",
                "asof",
                "normally_ended",
                "short_drop",
                "raw_false_bridge",
                "preconfirmation",
                "nonconfirmed",
                "zone_span",
                "merged",
                "open",
                "unqualified_reentry",
                "qualified_components",
                "unqualified_components",
                "all_unqualified_components",
                "prequalification_right_censored",
                "prequalification_days",
            )
        },
        "event_spans": [],
        "cell_zones": [],
        "year_counts": {},
        "transition_expected": {key: 0 for key in TRANSITION_SOURCE_FIELDS},
        "events": {},
        "spans": {},
        "components": {},
    }


def _accumulate_oracle_cell(
    context: dict[str, Any], oracle: Mapping[str, Any], security_id: str
) -> None:
    aggregate = context["aggregate"]
    d = context["d"]
    aggregate["events"] += oracle["qualified_event_count"]
    aggregate["unique_securities"] += oracle["unique_security_count"]
    aggregate["qualified"] += len(oracle["qualified_confirmed_keys"])
    aggregate["asof"] += len(oracle["qualified_asof_keys"])
    aggregate["prequalification_days"] += len(oracle["prequalification_confirmed_keys"])
    aggregate["normally_ended"] += sum(
        item["termination_reason"] == "natural_state_exit"
        for item in oracle["components"]
    )
    aggregate["short_drop"] += sum(
        item["termination_reason"] == "natural_state_exit"
        and item["confirmed_day_count"] < d
        for item in oracle["components"]
    )
    for source, target in (
        ("raw_false_bridged_day_count", "raw_false_bridge"),
        ("preconfirmation_gap_day_count", "preconfirmation"),
        ("total_nonconfirmed_gap_day_count", "nonconfirmed"),
        ("membership_count", "zone_span"),
        ("merged_event_count", "merged"),
        ("open_event_count", "open"),
        ("unqualified_reentry_count", "unqualified_reentry"),
        ("qualified_component_count", "qualified_components"),
        ("unqualified_component_count", "unqualified_components"),
        ("prequalification_right_censored_count", "prequalification_right_censored"),
    ):
        aggregate[target] += oracle[source]
    aggregate["all_unqualified_components"] += sum(
        not component["qualified"] for component in oracle["components"]
    )
    context["event_spans"].extend(oracle["event_spans"])
    context["cell_zones"].extend(oracle["zones"])
    for year in oracle["event_years"]:
        context["year_counts"][year] = context["year_counts"].get(year, 0) + 1
    for key in TRANSITION_SOURCE_FIELDS:
        context["transition_expected"][key] += oracle["transition_closure"][key]
    for zone in oracle["zones"]:
        event_id = (security_id, str(zone["scan_event_id"]))
        context["events"][event_id] = set(zone["confirmed_keys"])
        context["spans"][event_id] = set(zone["span_keys"])
    for component in oracle["components"]:
        if component["qualified"]:
            component_id = (
                security_id,
                f"{component['start']}|{component['end']}",
            )
            context["components"][component_id] = _component_keys(
                component, oracle["timeline"]
            )


def _finalize_oracle_cell(
    con: duckdb.DuckDBPyConnection,
    context: Mapping[str, Any],
    route_confirmed: set[tuple[str, str]],
    route_eligible: set[tuple[str, str]],
    route_atomic_spans: Sequence[int],
    route_atomic_reasons: Sequence[str],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> dict[str, Any]:
    cell_id, route_id, d, g = (
        context["cell_id"],
        context["route_id"],
        context["d"],
        context["g"],
    )
    aggregate = context["aggregate"]
    event_spans = context["event_spans"]
    zones = context["cell_zones"]
    year_counts = context["year_counts"]
    expected_values = {
        "qualified_event_count": aggregate["events"],
        "unique_securities": aggregate["unique_securities"],
        "retained_confirmed_day_ratio": _oracle_ratio(
            aggregate["qualified"], len(route_confirmed)
        ),
        "confirmed_event_coverage": _oracle_ratio(
            aggregate["qualified"], len(route_eligible)
        ),
        "retrospective_qualified_confirmed_coverage": _oracle_ratio(
            aggregate["qualified"], len(route_eligible)
        ),
        "asof_qualified_confirmed_coverage": _oracle_ratio(
            aggregate["asof"], len(route_eligible)
        ),
        "short_interval_drop_rate": _oracle_ratio(
            aggregate["short_drop"], aggregate["normally_ended"]
        ),
        "bridged_day_ratio": _oracle_ratio(
            aggregate["raw_false_bridge"], aggregate["zone_span"]
        ),
        "merge_ratio": _oracle_ratio(aggregate["merged"], aggregate["events"]),
        "open_event_ratio": _oracle_ratio(aggregate["open"], aggregate["events"]),
        "nonzero_years": len(year_counts),
        "max_year_share": _oracle_ratio(
            max(year_counts.values(), default=0), sum(year_counts.values())
        ),
        "duration_q95_ratio": _oracle_ratio(
            _oracle_nearest(event_spans, 0.95),
            _oracle_nearest(route_atomic_spans, 0.95),
        ),
        "unqualified_reentry_count": aggregate["unqualified_reentry"],
        "qualified_component_count": aggregate["qualified_components"],
        "unqualified_component_count": aggregate["unqualified_components"],
        "raw_false_bridged_day_count": aggregate["raw_false_bridge"],
        "preconfirmation_gap_day_count": aggregate["preconfirmation"],
        "total_nonconfirmed_gap_day_count": aggregate["nonconfirmed"],
    }
    observed = con.execute(
        """SELECT m.qualified_event_count,m.unique_securities,m.retained_confirmed_day_ratio,
        p.confirmed_event_coverage,q.retrospective_qualified_confirmed_coverage,
        q.asof_qualified_confirmed_coverage,m.short_interval_drop_rate,m.bridged_day_ratio,
        m.merge_ratio,m.open_event_ratio,m.nonzero_years,m.max_year_share,m.duration_q95_ratio,
        p.unqualified_reentry_count,q.qualified_component_count,q.unqualified_component_count,
        p.raw_false_bridged_day_count,p.preconfirmation_gap_day_count,p.total_nonconfirmed_gap_day_count
        FROM metric_results m JOIN dg_event_zone_profile p USING(candidate_cell_id)
        JOIN d_qualification_profile q USING(candidate_cell_id) WHERE m.candidate_cell_id=?""",
        [cell_id],
    ).fetchone()
    _assert_independent_field_contract(
        expected_values, CORE_METRIC_FIELDS, "core_metric"
    )
    _append_comparisons(
        cell_id, expected_values, observed, CORE_METRIC_FIELDS, rows, failures
    )
    _append_transition_comparisons(
        con, cell_id, context["transition_expected"], rows, failures
    )
    diagnostic_aggregate = {
        **aggregate,
        "eligible": len(route_eligible),
        "confirmed": len(route_confirmed),
    }
    _append_diagnostic_comparisons(
        con,
        cell_id,
        route_id,
        d,
        diagnostic_aggregate,
        route_atomic_spans,
        route_atomic_reasons,
        zones,
        rows,
        failures,
    )
    return {
        "confirmed": route_confirmed,
        "eligible": route_eligible,
        "events": context["events"],
        "spans": context["spans"],
        "components": context["components"],
        "route_id": route_id,
        "d": d,
        "g": g,
        "bridge_count": sum(int(zone["bridge_count"]) for zone in zones),
        "bridged_days": aggregate["raw_false_bridge"],
        "zone_span_days": aggregate["zone_span"],
        "asof_count": aggregate["asof"],
    }


def _iter_route_security_inputs(con: duckdb.DuckDBPyConnection, route_id: str) -> Any:
    """Stream one route; canonical columns are comparison-only, never oracle input."""
    cursor = con.execute(
        """SELECT k.security_id,CAST(k.trade_date AS VARCHAR),
        s.eligible,s.quality_state,s.raw_state,CAST(s.available_time AS VARCHAR),
        s.expected_empty_reason,s.source_row_present,x.expected_empty_reason,
        r.eligible,r.quality_state,r.raw_state,r.confirmed_state,
        coalesce(CAST(r.confirmed_start_date AS VARCHAR),''),
        coalesce(CAST(r.confirmation_time AS VARCHAR),''),
        coalesce(CAST(r.confirmed_end_date AS VARCHAR),''),
        coalesce(CAST(r.exit_observation_time AS VARCHAR),''),
        r.state_risk_set_eligible,r.reason_code,r.hard_break
        FROM expected_route_key k
        LEFT JOIN route_source_daily s
          ON s.route_id=k.route_id AND s.security_id=k.security_id
         AND s.trade_date=k.trade_date
        LEFT JOIN expected_empty_status x
          ON x.security_id=k.security_id AND x.trade_date=k.trade_date
        JOIN route_daily r
          ON r.route_id=k.route_id AND r.security_id=k.security_id
         AND r.trade_date=k.trade_date
        WHERE k.route_id=? ORDER BY k.security_id,k.trade_date""",
        [route_id],
    )
    current_security: str | None = None
    sparse: list[dict[str, Any]] = []
    expected: list[str] = []
    statuses: dict[str, str] = {}
    production: list[tuple[Any, ...]] = []
    while True:
        batch = cursor.fetchmany(10_000)
        if not batch:
            break
        for value in batch:
            security_id, trade_date = str(value[0]), str(value[1])
            if current_security is not None and security_id != current_security:
                yield current_security, sparse, expected, statuses, production
                sparse, expected, statuses, production = [], [], {}, []
            current_security = security_id
            expected.append(trade_date)
            if value[7] is not None:
                sparse.append(
                    {
                        "security_id": security_id,
                        "trade_date": trade_date,
                        "eligible": value[2],
                        "quality_state": value[3],
                        "raw_state": value[4],
                        "available_time": value[5],
                        "expected_empty_reason": value[6],
                        "source_row_present": value[7],
                    }
                )
            elif value[8] is not None:
                statuses[trade_date] = str(value[8])
            production.append(tuple(value[9:]))
    if current_security is not None:
        yield current_security, sparse, expected, statuses, production


def validate_independently(
    database: Path, output_dir: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    """Stream each route-security base through all nine d-by-g cell oracles."""
    validator_started = time.monotonic()
    con = duckdb.connect(str(database), read_only=True)
    source_con = duckdb.connect(str(database), read_only=True)
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    cell_oracles: dict[str, dict[str, Any]] = {}
    base_replay_count = 0
    cell_derivation_count = 0
    route_timings: dict[str, float] = {}
    try:
        route_rows = con.execute(
            "SELECT DISTINCT route_id FROM cell_registry ORDER BY route_id"
        ).fetchall()
        for (route_id,) in route_rows:
            route_started = time.monotonic()
            route_cells = con.execute(
                """SELECT candidate_cell_id,d,g FROM cell_registry
                WHERE route_id=? ORDER BY d,g,candidate_cell_id""",
                [route_id],
            ).fetchall()
            if len(route_cells) != 9:
                raise R2T03IndependentValidationError(
                    f"route_cell_count_not_nine:{route_id}:{len(route_cells)}"
                )
            contexts = {
                cell_id: _new_oracle_cell_context(cell_id, route_id, d, g)
                for cell_id, d, g in route_cells
            }
            route_confirmed: set[tuple[str, str]] = set()
            route_eligible: set[tuple[str, str]] = set()
            route_atomic_spans: list[int] = []
            route_atomic_reasons: list[str] = []
            security_inputs = _iter_route_security_inputs(source_con, route_id)
            for security_index, (
                security_id,
                source,
                expected,
                statuses,
                production,
            ) in enumerate(security_inputs, start=1):
                dense = _independent_dense_input(
                    source, expected, statuses, security_id=security_id
                )
                base = _build_base_oracle(dense, expected_dates=expected)
                _assert_oracle_daily_matches_canonical(
                    con,
                    route_id,
                    security_id,
                    base["timeline"],
                    production=production,
                )
                _assert_source_interval_oracle_matches_upstream(
                    con, route_id, security_id, expected, base["atomic_intervals"]
                )
                base_replay_count += 1
                route_confirmed.update(base["confirmed_keys"])
                route_eligible.update(base["eligible_valid_keys"])
                route_atomic_spans.extend(base["atomic_spans"])
                route_atomic_reasons.extend(
                    str(item["termination_reason"]) for item in base["atomic_intervals"]
                )
                for cell_id, d, g in route_cells:
                    oracle = _derive_cell_oracle(base, d=d, g=g)
                    _accumulate_oracle_cell(contexts[cell_id], oracle, security_id)
                    cell_derivation_count += 1
                if security_index % 100 == 0:
                    print(
                        f"independent_oracle_heartbeat route_id={route_id} "
                        f"processed_securities={security_index} "
                        f"elapsed_seconds={round(time.monotonic() - route_started, 6)} "
                        f"comparison_rows_accumulated={len(rows)}",
                        flush=True,
                    )
            for cell_id, _, _ in route_cells:
                cell_oracles[cell_id] = _finalize_oracle_cell(
                    con,
                    contexts[cell_id],
                    route_confirmed,
                    route_eligible,
                    route_atomic_spans,
                    route_atomic_reasons,
                    rows,
                    failures,
                )
            route_timings[route_id] = round(time.monotonic() - route_started, 6)
            print(
                f"independent_oracle_route_complete route={route_id} "
                f"seconds={route_timings[route_id]}",
                flush=True,
            )
        expected_base_replays = con.execute(
            "SELECT count(*) FROM (SELECT DISTINCT route_id,security_id FROM expected_route_key)"
        ).fetchone()[0]
        expected_cell_derivations = con.execute(
            """SELECT sum(security_count*cell_count) FROM
            (SELECT route_id,count(DISTINCT security_id) security_count
             FROM expected_route_key GROUP BY route_id) s
            JOIN (SELECT route_id,count(*) cell_count FROM cell_registry GROUP BY route_id) c
            USING(route_id)"""
        ).fetchone()[0]
        _assert_oracle_execution_counts(
            base_replay_count,
            cell_derivation_count,
            expected_base_replays,
            expected_cell_derivations,
        )
        _append_source_comparison_checks(con, cell_oracles, rows, failures)
        _append_parameter_invariant_comparisons(con, cell_oracles, rows, failures)
    finally:
        source_con.close()
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
    total_elapsed = round(time.monotonic() - validator_started, 6)
    slowest_route = max(route_timings, key=route_timings.get) if route_timings else None
    report = {
        "task_id": "R2-T03",
        "status": "passed" if not failures else "failed",
        "database_path": repo_rel(database, root),
        "comparison_count": len(rows),
        "failure_count": len(failures),
        "failures": failures[:100],
        "oracle_source_tables": [
            "route_source_daily",
            "expected_empty_status",
            "expected_route_key",
            "authorized_upstream_interval",
            "cell_registry",
        ],
        "forbidden_production_oracle_tables_used": False,
        "production_scanner_imported": False,
        "production_metrics_imported": False,
        "base_k3_replay_count": base_replay_count,
        "cell_derivation_count": cell_derivation_count,
        "expected_base_k3_replay_count": expected_base_replays,
        "expected_cell_derivation_count": expected_cell_derivations,
        "route_timings_seconds": route_timings,
        "slowest_route": slowest_route,
        "total_elapsed_seconds": total_elapsed,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_independent_validation.json", report)
    if failures:
        raise R2T03IndependentValidationError(
            "independent_validation_failed:" + failures[0]
        )
    return report


def _assert_oracle_execution_counts(
    base_replay_count: int,
    cell_derivation_count: int,
    expected_base_replays: int,
    expected_cell_derivations: int,
) -> None:
    if base_replay_count != expected_base_replays:
        raise R2T03IndependentValidationError(
            f"base_k3_replay_count_mismatch:{base_replay_count}:{expected_base_replays}"
        )
    if cell_derivation_count != expected_cell_derivations:
        raise R2T03IndependentValidationError(
            "cell_derivation_count_mismatch:"
            f"{cell_derivation_count}:{expected_cell_derivations}"
        )


def _new_oracle_zone(
    component: Mapping[str, Any], timeline: Sequence[Mapping[str, Any]], ordinal: int
) -> dict[str, Any]:
    return {
        "scan_event_id": f"oracle_event_{ordinal:03d}",
        "security_id": str(timeline[int(component["start"])]["security_id"]),
        "component_count": 1,
        "bridge_count": 0,
        "raw_false_bridged_day_count": 0,
        "preconfirmation_gap_day_count": 0,
        "total_nonconfirmed_gap_day_count": 0,
        "max_raw_false_gap_days": 0,
        "zone_span_days": int(component["confirmed_day_count"]),
        "confirmed_keys": _component_keys(component, timeline),
        "span_keys": _component_keys(component, timeline),
        "status": "QUALIFIED_ACTIVE",
        "censor_prior_state": None,
        "start_year": str(timeline[int(component["start"])]["trade_date"])[:4],
    }


def _earliest_oracle_decision(rows: Sequence[Mapping[str, Any]], g: int) -> str | None:
    raw_false_count = 0
    for row in rows:
        if bool(row["hard_break"]):
            return "quality_break"
        if (
            row["eligible"]
            and row["quality_state"] == "valid"
            and row.get("raw_state") is False
        ):
            raw_false_count += 1
            if raw_false_count > g:
                return "raw_false_gap_exceeds_g"
    return None


def _append_source_comparison_checks(
    con: duckdb.DuckDBPyConnection,
    cells: Mapping[str, Mapping[str, Any]],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    strict_pairs = con.execute(
        """SELECT p.candidate_cell_id,s.candidate_cell_id
        FROM cell_registry p JOIN cell_registry s
          ON p.state_line=s.state_line AND p.W=s.W AND p.d=s.d AND p.g=s.g
         AND p.candidate_role='primary' AND s.candidate_role='strict_core_reference'
        ORDER BY 1,2"""
    ).fetchall()
    for primary, sidecar in strict_pairs:
        left, right = cells[primary], cells[sidecar]
        independent = independent_strict_core_oracle(
            left["events"],
            right["events"],
            left["confirmed"],
            right["confirmed"],
            left["components"],
            right["components"],
            right["spans"],
        )
        observed = con.execute(
            """SELECT strict_core_confirmed_day_count,strict_core_confirmed_day_share,
            strict_core_event_count,strict_core_event_share,shell_only_event_count,
            shell_only_confirmed_day_count,shell_only_confirmed_day_share,
            strict_core_subset_status FROM strict_core_shell_profile
            WHERE primary_candidate_cell_id=? AND sidecar_candidate_cell_id=?""",
            [primary, sidecar],
        ).fetchone()
        _append_comparisons(
            f"{primary}|{sidecar}",
            {key: independent[key] for key in STRICT_CORE_FIELDS},
            observed,
            STRICT_CORE_FIELDS,
            rows,
            failures,
        )
        expansion_shell = con.execute(
            """SELECT expansion_shell_confirmed_day_share,
            strict_core_qualified_component_count,strict_core_qualified_component_share,
            shell_only_qualified_component_count,strict_core_confirmed_density
            FROM strict_core_diagnostic_profile
            WHERE primary_candidate_cell_id=? AND sidecar_candidate_cell_id=?""",
            [primary, sidecar],
        ).fetchone()
        _append_comparisons(
            f"{primary}|{sidecar}",
            {
                "expansion_shell_confirmed_day_share": independent[
                    "shell_only_confirmed_day_share"
                ],
                "strict_core_qualified_component_count": independent[
                    "strict_core_qualified_component_count"
                ],
                "strict_core_qualified_component_share": independent[
                    "strict_core_qualified_component_share"
                ],
                "shell_only_qualified_component_count": independent[
                    "shell_only_qualified_component_count"
                ],
                "strict_core_confirmed_density": independent[
                    "strict_core_confirmed_density"
                ],
            },
            expansion_shell,
            STRICT_DIAGNOSTIC_FIELDS,
            rows,
            failures,
        )
    window_pairs = con.execute(
        """SELECT a.candidate_cell_id,b.candidate_cell_id
        FROM cell_registry a JOIN cell_registry b
          ON a.candidate_role=b.candidate_role AND a.state_line=b.state_line
         AND a.d=b.d AND a.g=b.g AND a.W=120 AND b.W=250 ORDER BY 1,2"""
    ).fetchall()
    for primary, comparison in window_pairs:
        left, right = cells[primary], cells[comparison]
        independent = independent_window_oracle(
            left["confirmed"],
            right["confirmed"],
            left["eligible"],
            right["eligible"],
            left["events"],
            right["events"],
            left["spans"],
            right["spans"],
            left["components"],
            right["components"],
        )
        observed = con.execute(
            """SELECT intersection_confirmed_days,W120_only_confirmed_days,
            W250_only_confirmed_days,union_confirmed_days,confirmed_day_jaccard,
            W120_own_eligible_days,W250_own_eligible_days,common_eligible_days,
            matched_event_count,overlapping_event_count FROM window_overlap_comparison
            WHERE primary_candidate_cell_id=? AND comparison_candidate_cell_id=?""",
            [primary, comparison],
        ).fetchone()
        _append_comparisons(
            f"{primary}|{comparison}",
            {key: independent[key] for key in WINDOW_CORE_FIELDS},
            observed,
            WINDOW_CORE_FIELDS,
            rows,
            failures,
        )
        supplemental = con.execute(
            """SELECT W120_only_event_count,W250_only_event_count,
            component_overlap_count,W120_only_component_count,W250_only_component_count
            FROM window_diagnostic_profile WHERE primary_candidate_cell_id=?
             AND comparison_candidate_cell_id=?""",
            [primary, comparison],
        ).fetchone()
        _append_comparisons(
            f"{primary}|{comparison}",
            {key: independent[key] for key in WINDOW_SUPPLEMENTAL_FIELDS},
            supplemental,
            WINDOW_SUPPLEMENTAL_FIELDS,
            rows,
            failures,
        )


def _append_parameter_invariant_comparisons(
    con: duckdb.DuckDBPyConnection,
    cells: Mapping[str, Mapping[str, Any]],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    expected: dict[tuple[str, str], int] = {}

    def add(check_id: str, scope: str, violated: bool) -> None:
        expected[(check_id, scope)] = expected.get((check_id, scope), 0) + int(violated)

    values = list(cells.values())
    for left in values:
        g_right = next(
            (
                value
                for value in values
                if value["route_id"] == left["route_id"]
                and value["d"] == left["d"]
                and value["g"] == left["g"] + 1
            ),
            None,
        )
        if g_right is not None:
            scope = f"{left['route_id']}:d={left['d']}"
            add(
                "g_event_count_nonincreasing",
                scope,
                len(g_right["events"]) > len(left["events"]),
            )
            add(
                "g_bridge_count_nondecreasing",
                scope,
                g_right["bridge_count"] < left["bridge_count"],
            )
            add(
                "g_bridged_days_nondecreasing",
                scope,
                g_right["bridged_days"] < left["bridged_days"],
            )
            add(
                "g_zone_coverage_nondecreasing",
                scope,
                g_right["zone_span_days"] < left["zone_span_days"],
            )
            add(
                "g_confirmed_days_invariant",
                scope,
                len(g_right["confirmed"]) != len(left["confirmed"]),
            )
            add(
                "g_retrospective_days_invariant",
                scope,
                sum(len(value) for value in g_right["events"].values())
                != sum(len(value) for value in left["events"].values()),
            )
            add(
                "g_asof_days_invariant",
                scope,
                g_right["asof_count"] != left["asof_count"],
            )
        d_right = next(
            (
                value
                for value in values
                if value["route_id"] == left["route_id"]
                and value["g"] == left["g"]
                and value["d"] == left["d"] + 1
            ),
            None,
        )
        if d_right is not None:
            scope = f"{left['route_id']}:g={left['g']}"
            add(
                "d_component_nonincreasing",
                scope,
                len(d_right["components"]) > len(left["components"]),
            )
            add(
                "d_retrospective_days_nonincreasing",
                scope,
                sum(len(value) for value in d_right["events"].values())
                > sum(len(value) for value in left["events"].values()),
            )
            add(
                "d_asof_days_nonincreasing",
                scope,
                d_right["asof_count"] > left["asof_count"],
            )
            add(
                "d_qualification_delay_nondecreasing",
                scope,
                (d_right["d"] - 1) < (left["d"] - 1),
            )
        if left["g"] == 0:
            scope = f"{left['route_id']}:d={left['d']}"
            add(
                "g_zero_identity",
                scope,
                len(left["events"]) != len(left["components"])
                or left["bridge_count"] != 0
                or left["bridged_days"] != 0,
            )
    observed = {
        (check_id, scope): int(violations)
        for check_id, scope, violations in con.execute(
            "SELECT check_id,scope,observed_violations FROM parameter_invariant_profile"
        ).fetchall()
    }
    for key, value in sorted(expected.items()):
        metric_name = f"parameter_invariant:{key[0]}"
        _append_comparisons(
            key[1],
            {metric_name: value},
            [observed.get(key)],
            (metric_name,),
            rows,
            failures,
        )


def _append_diagnostic_comparisons(
    con: duckdb.DuckDBPyConnection,
    cell_id: str,
    route_id: str,
    d: int,
    aggregate: Mapping[str, int],
    atomic_spans: Sequence[int],
    atomic_reasons: Sequence[str],
    zones: Sequence[Mapping[str, Any]],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    atomic_expected = {
        "atomic_diag_interval_count": len(atomic_spans),
        "atomic_diag_duration_mean": _oracle_mean(atomic_spans),
        "atomic_diag_duration_median": _oracle_median(atomic_spans),
        "atomic_diag_duration_q90": _oracle_nearest(atomic_spans, 0.90),
        "atomic_diag_duration_q95": _oracle_nearest(atomic_spans, 0.95),
        "atomic_diag_singleton_count": sum(value == 1 for value in atomic_spans),
        "atomic_diag_fragment_rate": _oracle_ratio(
            sum(value == 1 for value in atomic_spans), len(atomic_spans)
        ),
        "atomic_diag_natural_exit_count": atomic_reasons.count("natural_state_exit"),
        "atomic_diag_quality_interruption_count": atomic_reasons.count(
            "quality_interruption"
        ),
        "atomic_diag_right_censored_count": atomic_reasons.count(
            "sample_end_censoring"
        ),
    }
    atomic_observed = con.execute(
        """SELECT atomic_confirmed_interval_count,atomic_duration_mean,
        atomic_duration_median,atomic_duration_q90,atomic_duration_q95,
        atomic_singleton_count,atomic_fragment_rate,natural_exit_count,
        quality_interruption_count,right_censored_atomic_count
        FROM atomic_interval_diagnostic_profile WHERE route_id=?""",
        [route_id],
    ).fetchone()
    _append_comparisons(
        cell_id,
        atomic_expected,
        atomic_observed,
        ATOMIC_DIAGNOSTIC_FIELDS,
        rows,
        failures,
    )

    component_expected = {
        "component_diag_qualified_count": aggregate["qualified_components"],
        "component_diag_unqualified_count": aggregate["unqualified_components"],
        "component_diag_qualification_rate": _oracle_ratio(
            aggregate["qualified_components"],
            aggregate["qualified_components"] + aggregate["unqualified_components"],
        ),
        "component_diag_qualified_days": aggregate["qualified"],
        "component_diag_retrospective_days": aggregate["qualified"],
        "component_diag_asof_days": aggregate["asof"],
        "component_diag_prequalification_days": aggregate["prequalification_days"],
        "component_diag_prequalification_right_censored": aggregate[
            "prequalification_right_censored"
        ],
        "component_diag_delay_mean": float(d - 1)
        if aggregate["qualified_components"]
        else None,
        "component_diag_delay_median": float(d - 1)
        if aggregate["qualified_components"]
        else None,
        "component_diag_delay_q90": d - 1
        if aggregate["qualified_components"]
        else None,
        "component_diag_delay_q95": d - 1
        if aggregate["qualified_components"]
        else None,
        "component_diag_unqualified_reentry_count": aggregate["unqualified_reentry"],
        "component_diag_unqualified_reentry_rate": _oracle_ratio(
            aggregate["unqualified_reentry"],
            aggregate["all_unqualified_components"],
        ),
    }
    component_observed = con.execute(
        """SELECT qualified_component_count,unqualified_component_count,
        component_qualification_rate,qualified_confirmed_day_count,
        retrospective_qualified_confirmed_day_count,
        asof_qualified_confirmed_day_count,prequalification_confirmed_day_count,
        prequalification_right_censored_count,
        qualification_delay_observations_mean,qualification_delay_observations_median,
        qualification_delay_observations_q90,qualification_delay_observations_q95,
        unqualified_reentry_count,unqualified_reentry_rate FROM component_diagnostic_profile
        WHERE candidate_cell_id=?""",
        [cell_id],
    ).fetchone()
    _append_comparisons(
        cell_id,
        component_expected,
        component_observed,
        COMPONENT_DIAGNOSTIC_FIELDS,
        rows,
        failures,
    )

    component_counts = [int(zone["component_count"]) for zone in zones]
    bridge_counts = [int(zone["bridge_count"]) for zone in zones]
    durations = [int(zone["zone_span_days"]) for zone in zones]
    confirmed_counts = [len(zone["confirmed_keys"]) for zone in zones]
    security_counts: dict[str, int] = {}
    year_counts: dict[str, int] = {}
    for zone in zones:
        security_counts[str(zone["security_id"])] = (
            security_counts.get(str(zone["security_id"]), 0) + 1
        )
        year_counts[str(zone["start_year"])] = (
            year_counts.get(str(zone["start_year"]), 0) + 1
        )
    security_values = list(security_counts.values())
    total_span = sum(durations)
    total_confirmed = sum(confirmed_counts)
    raw_false_days = sum(int(zone["raw_false_bridged_day_count"]) for zone in zones)
    preconfirmation_days = sum(
        int(zone["preconfirmation_gap_day_count"]) for zone in zones
    )
    total_gap_days = sum(
        int(zone["total_nonconfirmed_gap_day_count"]) for zone in zones
    )
    event_expected = {
        "event_diag_count": len(zones),
        "event_diag_natural_count": sum(
            zone["status"] == "FINALIZED" for zone in zones
        ),
        "event_diag_quality_count": sum(
            zone["status"] == "FINALIZED_WITH_QUALITY_BREAK" for zone in zones
        ),
        "event_diag_right_censored_count": sum(
            zone["status"] == "RIGHT_CENSORED" for zone in zones
        ),
        "event_diag_component_q90": _oracle_nearest(component_counts, 0.90),
        "event_diag_component_q95": _oracle_nearest(component_counts, 0.95),
        "event_diag_component_mean": _oracle_mean(component_counts),
        "event_diag_component_median": _oracle_median(component_counts),
        "event_diag_component_max": max(component_counts, default=None),
        "event_diag_bridge_q90": _oracle_nearest(bridge_counts, 0.90),
        "event_diag_bridge_q95": _oracle_nearest(bridge_counts, 0.95),
        "event_diag_bridge_mean": _oracle_mean(bridge_counts),
        "event_diag_bridge_median": _oracle_median(bridge_counts),
        "event_diag_bridge_max": max(bridge_counts, default=None),
        "event_diag_duration_q90": _oracle_nearest(durations, 0.90),
        "event_diag_duration_q95": _oracle_nearest(durations, 0.95),
        "event_diag_zone_span_sum": total_span,
        "event_diag_zone_span_coverage": _oracle_ratio(
            total_span, aggregate["eligible"]
        ),
        "event_diag_duration_mean": _oracle_mean(durations),
        "event_diag_duration_median": _oracle_median(durations),
        "event_diag_max_zone_span": max(durations, default=None),
        "event_diag_duration_q95_ratio": _oracle_ratio(
            _oracle_nearest(durations, 0.95), _oracle_nearest(atomic_spans, 0.95)
        ),
        "event_diag_confirmed_density": _oracle_ratio(total_confirmed, total_span),
        "event_diag_bridge_count": sum(bridge_counts),
        "event_diag_bridged_days": raw_false_days,
        "event_diag_raw_false_days": raw_false_days,
        "event_diag_preconfirmation_days": preconfirmation_days,
        "event_diag_total_gap_days": total_gap_days,
        "event_diag_bridged_day_ratio": _oracle_ratio(raw_false_days, total_span),
        "event_diag_raw_false_ratio": _oracle_ratio(raw_false_days, total_span),
        "event_diag_nonconfirmed_ratio": _oracle_ratio(total_gap_days, total_span),
        "event_diag_max_single_gap": max(
            (int(zone["max_raw_false_gap_days"]) for zone in zones), default=None
        ),
        "event_diag_top_zone_share": _oracle_ratio(
            max(confirmed_counts, default=0), total_confirmed
        ),
        "event_diag_merge_ratio": _oracle_ratio(
            sum(count > 1 for count in component_counts), len(zones)
        ),
        "event_diag_revision_count": sum(bridge_counts),
        "event_diag_mega_zone_concentration": _oracle_mega_zone_concentration(
            durations
        ),
        "event_diag_open_ratio": _oracle_ratio(
            sum(zone["status"] == "RIGHT_CENSORED" for zone in zones), len(zones)
        ),
        "event_diag_active_pending": sum(
            zone["status"] == "RIGHT_CENSORED"
            and zone.get("censor_prior_state") == "QUALIFIED_ACTIVE"
            for zone in zones
        ),
        "event_diag_gap_pending": sum(
            zone["status"] == "RIGHT_CENSORED"
            and zone.get("censor_prior_state") == "GAP_PENDING"
            for zone in zones
        ),
        "event_diag_reentry_pending": sum(
            zone["status"] == "RIGHT_CENSORED"
            and zone.get("censor_prior_state") == "REENTRY_PENDING_QUALIFICATION"
            for zone in zones
        ),
        "event_diag_confirmed_coverage": _oracle_ratio(
            aggregate["qualified"], aggregate["eligible"]
        ),
        "event_diag_events_per_security_mean": _oracle_mean(security_values),
        "event_diag_events_per_security_median": _oracle_median(security_values),
        "event_diag_events_per_security_q90": _oracle_nearest(security_values, 0.90),
        "event_diag_events_per_security_max": max(security_values, default=0),
        "event_diag_events_per_year": _oracle_ratio(len(zones), len(year_counts)),
        "event_diag_nonzero_years": len(year_counts),
        "event_diag_max_year_share": _oracle_ratio(
            max(year_counts.values(), default=0), len(zones)
        ),
    }
    event_observed = con.execute(
        """SELECT qualified_event_count,natural_finalized_zone_count,
        quality_break_zone_count,right_censored_zone_count,component_count_q90,
        component_count_q95,component_count_mean,component_count_median,component_count_max,
        bridge_count_q90,bridge_count_q95,bridge_count_mean,bridge_count_median,bridge_count_max,
        duration_q90,duration_q95,
        zone_span_days_sum,zone_span_coverage,duration_mean,duration_median,max_zone_span,
        duration_q95_ratio,
        confirmed_density,bridged_gap_count,bridged_day_count,raw_false_bridged_day_count,
        preconfirmation_gap_day_count,total_nonconfirmed_gap_day_count,bridged_day_ratio,
        raw_false_bridged_day_ratio,nonconfirmed_gap_ratio,max_single_gap,
        top_zone_confirmed_day_share,merge_ratio,zone_revision_count,mega_zone_concentration,
        open_event_ratio,active_zone_count,gap_pending_zone_count,reentry_pending_zone_count,
        confirmed_event_coverage,events_per_security_mean,events_per_security_median,
        events_per_security_q90,events_per_security_max,events_per_year,nonzero_years,max_year_share
        FROM event_zone_diagnostic_profile WHERE candidate_cell_id=?""",
        [cell_id],
    ).fetchone()
    _append_comparisons(
        cell_id,
        event_expected,
        event_observed,
        EVENT_DIAGNOSTIC_FIELDS,
        rows,
        failures,
    )


def _append_transition_comparisons(
    con: duckdb.DuckDBPyConnection,
    cell_id: str,
    expected: Mapping[str, int],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    observed_values = con.execute(
        """SELECT
                count(*) FILTER (WHERE entity_kind='component' AND from_state='COMPONENT_FORMING' AND to_state='QUALIFIED_ACTIVE' AND reason_code='d_qualification'),
                count(*) FILTER (WHERE entity_kind='component' AND to_state='UNQUALIFIED_CLOSED' AND reason_code='normal_short_interval_drop'),
                count(*) FILTER (WHERE entity_kind='event_zone' AND from_state='COMPONENT_FORMING' AND to_state='QUALIFIED_ACTIVE' AND reason_code='d_qualification'),
                count(*) FILTER (WHERE entity_kind='event_zone' AND to_state IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED')),
                count(DISTINCT entity_id) FILTER (WHERE entity_kind='bridge'),
                count(DISTINCT entity_id) FILTER (WHERE entity_kind='reentry')
                FROM transition_entity_ledger WHERE candidate_cell_id=?""",
        [cell_id],
    ).fetchone()
    observed = {
        field: observed_values[index]
        for index, field in enumerate(TRANSITION_SOURCE_FIELDS)
    }
    _append_comparisons(
        cell_id,
        {
            field: expected[TRANSITION_SOURCE_FIELDS[index]]
            for index, field in enumerate(TRANSITION_FIELDS)
        },
        [observed[field] for field in TRANSITION_SOURCE_FIELDS],
        TRANSITION_FIELDS,
        rows,
        failures,
    )
    discontinuity = con.execute(
        """SELECT count(*) FROM (SELECT entity_id,transition_ordinal,from_state,
        lag(to_state) OVER (PARTITION BY security_id,entity_id ORDER BY transition_ordinal) prior_to
        FROM transition_entity_ledger WHERE candidate_cell_id=? AND entity_kind='event_zone')
        WHERE transition_ordinal>1 AND from_state<>prior_to""",
        [cell_id],
    ).fetchone()[0]
    _append_comparisons(
        cell_id,
        {"transition_event_entity_discontinuity_count": 0},
        [discontinuity],
        ("transition_event_entity_discontinuity_count",),
        rows,
        failures,
    )


def _append_comparisons(
    identity: str,
    independent: Mapping[str, Any],
    observed: Sequence[Any],
    fields: Sequence[str],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    _assert_independent_field_contract(independent, fields, identity)
    if len(observed) != len(fields):
        raise R2T03IndependentValidationError(
            f"observed_field_count_mismatch:{identity}:{len(observed)}:{len(fields)}"
        )
    for field_index, metric in enumerate(fields):
        expected = independent[metric]
        actual = observed[field_index]
        passed = _equal(expected, actual)
        rows.append(
            {
                "candidate_cell_id": identity,
                "metric_id": metric,
                "independent_value": expected,
                "production_value": actual,
                "status": "passed" if passed else "failed",
            }
        )
        if not passed:
            failures.append(f"{identity}:{metric}")


def _assert_independent_field_contract(
    values: Mapping[str, Any], fields: Sequence[str], label: str
) -> None:
    actual = set(values)
    expected = set(fields)
    if actual != expected:
        raise R2T03IndependentValidationError(
            f"independent_field_contract_failed:{label}:"
            f"missing={sorted(expected - actual)}:extra={sorted(actual - expected)}"
        )


def _assert_source_interval_oracle_matches_upstream(
    con: duckdb.DuckDBPyConnection,
    route_id: str,
    security_id: str,
    expected_dates: Sequence[str],
    intervals: Sequence[Mapping[str, Any]],
) -> None:
    rebuilt = sorted(
        (
            expected_dates[int(row["start"])],
            expected_dates[int(row["end"])],
            int(row["confirmed_day_count"]),
            str(row["termination_reason"]),
        )
        for row in intervals
    )
    production = [
        (str(start), str(end), int(count), str(reason))
        for start, end, count, reason in con.execute(
            """SELECT CAST(start_date AS VARCHAR),CAST(end_date AS VARCHAR),
            confirmed_day_count,termination_reason FROM route_atomic_interval
            WHERE route_id=? AND security_id=? ORDER BY 1,2,3,4""",
            [route_id, security_id],
        ).fetchall()
    ]
    if rebuilt != production:
        raise R2T03IndependentValidationError(
            f"dense_interval_oracle_mismatch:{route_id}:{security_id}"
        )
    lineage_bad = con.execute(
        """SELECT count(*) FROM route_atomic_interval r
        LEFT JOIN authorized_upstream_interval u ON
          r.route_id=u.route_id AND r.security_id=u.security_id
          AND r.upstream_source_interval_id=u.upstream_source_interval_id
        WHERE r.route_id=? AND r.security_id=? AND
          (u.upstream_source_interval_id IS NULL OR r.start_date<u.raw_start_date
           OR r.end_date>u.interval_end_date)""",
        [route_id, security_id],
    ).fetchone()[0]
    if lineage_bad:
        raise R2T03IndependentValidationError(
            f"dense_sparse_lineage_mismatch:{route_id}:{security_id}"
        )
    sparse_dates = {
        row[0]
        for row in con.execute(
            """SELECT CAST(trade_date AS VARCHAR) FROM route_source_daily
            WHERE route_id=? AND security_id=?""",
            [route_id, security_id],
        ).fetchall()
    }
    empty_dates = set(expected_dates) - sparse_dates
    sources = con.execute(
        """SELECT upstream_source_interval_id,CAST(raw_start_date AS VARCHAR),
        CAST(confirmed_start_date AS VARCHAR),CAST(interval_end_date AS VARCHAR),
        CAST(last_observed_date AS VARCHAR),confirmed_day_count,
        normalized_termination_reason FROM authorized_upstream_interval
        WHERE route_id=? AND security_id=?""",
        [route_id, security_id],
    ).fetchall()
    for (
        source_id,
        raw_start,
        confirmed_start,
        end,
        last_observed,
        count,
        reason,
    ) in sources:
        geometry = any(raw_start <= date <= end for date in empty_dates)
        termination = any(end < date <= last_observed for date in empty_dates)
        fragments = con.execute(
            """SELECT CAST(start_date AS VARCHAR),CAST(end_date AS VARCHAR),
            confirmed_day_count,termination_reason,source_geometry_affected,
            source_termination_affected,upstream_source_interval_id
            FROM route_atomic_interval WHERE route_id=? AND security_id=?
             AND upstream_source_interval_id=? ORDER BY 1,2""",
            [route_id, security_id, source_id],
        ).fetchall()
        if not geometry and not termination:
            exact = (confirmed_start, end, int(count), str(reason))
            facts = [(a, b, int(c), str(d)) for a, b, c, d, *_ in fragments]
            if facts != [exact]:
                raise R2T03IndependentValidationError(
                    f"unaffected_source_interval_not_exact:{route_id}:{security_id}:{source_id}"
                )
        for (
            start,
            fragment_end,
            _,
            _,
            marked_geometry,
            marked_termination,
            retained_id,
        ) in fragments:
            if retained_id != source_id or start < raw_start or fragment_end > end:
                raise R2T03IndependentValidationError(
                    f"affected_fragment_source_retention_mismatch:{route_id}:{security_id}:{source_id}"
                )
            if (
                bool(marked_geometry) != geometry
                or bool(marked_termination) != termination
            ):
                raise R2T03IndependentValidationError(
                    f"source_affected_classification_mismatch:{route_id}:{security_id}:{source_id}"
                )


def _assert_oracle_daily_matches_canonical(
    con: duckdb.DuckDBPyConnection,
    route_id: str,
    security_id: str,
    timeline: Sequence[Mapping[str, Any]],
    *,
    production: Sequence[Sequence[Any]] | None = None,
) -> None:
    fields = (
        "eligible",
        "quality_state",
        "raw_state",
        "confirmed_state",
        "confirmed_start_date",
        "confirmation_time",
        "confirmed_end_date",
        "exit_observation_time",
        "state_risk_set_eligible",
        "reason_code",
        "hard_break",
    )
    if production is None:
        production = con.execute(
            """SELECT eligible,quality_state,raw_state,confirmed_state,
            coalesce(CAST(confirmed_start_date AS VARCHAR),''),
            coalesce(CAST(confirmation_time AS VARCHAR),''),
            coalesce(CAST(confirmed_end_date AS VARCHAR),''),
            coalesce(CAST(exit_observation_time AS VARCHAR),''),
            state_risk_set_eligible,reason_code,hard_break FROM route_daily
            WHERE route_id=? AND security_id=? ORDER BY trade_date""",
            [route_id, security_id],
        ).fetchall()
    if len(timeline) != len(production):
        raise R2T03IndependentValidationError(
            f"canonical_daily_row_count_mismatch:{route_id}:{security_id}"
        )
    for index in range(len(timeline)):
        for field_index, field in enumerate(fields):
            left = _normalize_daily_comparison_value(field, timeline[index].get(field))
            right = _normalize_daily_comparison_value(
                field, production[index][field_index]
            )
            if not _equal(left, right):
                raise R2T03IndependentValidationError(
                    "canonical_daily_field_mismatch:"
                    f"{route_id}:{security_id}:{index}:{field}"
                )


def _normalize_daily_comparison_value(field: str, value: Any) -> Any:
    nullable_text = {
        "confirmed_start_date",
        "confirmation_time",
        "confirmed_end_date",
        "exit_observation_time",
        "reason_code",
    }
    if field in nullable_text and value in (None, ""):
        return None
    if field in {"confirmation_time", "exit_observation_time"}:
        normalized = str(value).replace(" ", "T")
        if len(normalized) >= 3 and normalized[-3] in {"+", "-"}:
            normalized += ":00"
        return normalized
    return value


def _component_keys(
    component: Mapping[str, Any], timeline: Sequence[Mapping[str, Any]]
) -> set[tuple[str, str]]:
    return {
        (str(timeline[index]["security_id"]), str(timeline[index]["trade_date"]))
        for index in range(int(component["start"]), int(component["end"]) + 1)
    }


def _oracle_nearest(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def _oracle_mean(values: Sequence[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _oracle_median(values: Sequence[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _oracle_ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _oracle_mega_zone_concentration(durations: Sequence[int]) -> float | None:
    """Independent frozen top-1%-by-count zone span concentration."""
    if not durations:
        return None
    top_n = max(1, math.ceil(0.01 * len(durations)))
    return _oracle_ratio(sum(sorted(durations, reverse=True)[:top_n]), sum(durations))


def _equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, float) or isinstance(right, float):
        return abs(float(left) - float(right)) <= 1e-12
    return left == right
