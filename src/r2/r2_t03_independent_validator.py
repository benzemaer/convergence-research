# ruff: noqa: E501
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import ROOT, repo_rel, write_csv, write_json


class R2T03IndependentValidationError(RuntimeError):
    pass


def source_timeline_oracle(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_dates: Sequence[str],
    d: int,
    g: int,
    k: int = 3,
) -> dict[str, Any]:
    """Independent source-level oracle; imports no production scanner or metric helper."""
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

    components = [
        {
            **interval,
            "component_id": f"component_{index:03d}",
            "qualified": interval["confirmed_day_count"] >= d,
        }
        for index, interval in enumerate(intervals, start=1)
    ]
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
        elif component["termination_reason"] == "natural_state_exit":
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
        zones.append(open_zone)
        transition_counts["event_terminal"] += 1

    eligible_valid_keys = {
        (str(row["security_id"]), row["trade_date"])
        for row in timeline
        if row["eligible"] and row["quality_state"] == "valid"
    }
    confirmed_keys = {
        (str(row["security_id"]), row["trade_date"])
        for row in timeline
        if row["confirmed_state"]
    }
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
    atomic_spans = [interval["confirmed_day_count"] for interval in intervals]
    return {
        "timeline": timeline,
        "atomic_intervals": intervals,
        "components": components,
        "zones": zones,
        "confirmed_keys": confirmed_keys,
        "qualified_confirmed_keys": qualified_keys,
        "eligible_valid_keys": eligible_valid_keys,
        "qualified_asof_keys": qualified_asof_keys,
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
    primary_events: Mapping[str, set[tuple[str, str]]],
    strict_events: Mapping[str, set[tuple[str, str]]],
    primary_days: set[tuple[str, str]],
    strict_days: set[tuple[str, str]],
) -> dict[str, Any]:
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
    }


def independent_window_oracle(
    primary_days: set[tuple[str, str]],
    comparison_days: set[tuple[str, str]],
    primary_eligible: set[tuple[str, str]],
    comparison_eligible: set[tuple[str, str]],
    primary_events: Mapping[str, set[tuple[str, str]]],
    comparison_events: Mapping[str, set[tuple[str, str]]],
    primary_event_spans: Mapping[str, set[tuple[str, str]]] | None = None,
    comparison_event_spans: Mapping[str, set[tuple[str, str]]] | None = None,
) -> dict[str, Any]:
    intersection, union = primary_days & comparison_days, primary_days | comparison_days
    candidate_pairs = []
    overlapping_primary: set[str] = set()
    primary_spans = primary_event_spans or primary_events
    comparison_spans = comparison_event_spans or comparison_events
    for primary_id, pkeys in primary_events.items():
        pspan = primary_spans[primary_id]
        for comparison_id, ckeys in comparison_events.items():
            cspan = comparison_spans[comparison_id]
            if {key[0] for key in pkeys} != {key[0] for key in ckeys}:
                continue
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
    used_primary: set[str] = set()
    used_comparison: set[str] = set()
    for _, _, primary_id, comparison_id in sorted(candidate_pairs):
        if primary_id not in used_primary and comparison_id not in used_comparison:
            used_primary.add(primary_id)
            used_comparison.add(comparison_id)
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
    }


def compare_oracle_metric_targets(
    expected: Mapping[str, Any], production: Mapping[str, Any]
) -> list[str]:
    return [
        f"independent_metric_mismatch:{metric}"
        for metric, value in expected.items()
        if metric not in production or not _equal(value, production[metric])
    ]


def validate_independently(
    database: Path, output_dir: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    """Formal interface: rebuild from route_daily/expected keys, then compare outputs."""
    con = duckdb.connect(str(database), read_only=True)
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    cell_oracles: dict[str, dict[str, Any]] = {}
    reconciled_route_security: set[tuple[str, str]] = set()
    try:
        cells = con.execute(
            "SELECT candidate_cell_id,route_id,d,g FROM cell_registry ORDER BY 1"
        ).fetchall()
        for cell_id, route_id, d, g in cells:
            aggregate = {
                "events": 0,
                "unique_securities": 0,
                "eligible": 0,
                "confirmed": 0,
                "qualified": 0,
                "asof": 0,
                "normally_ended": 0,
                "short_drop": 0,
                "raw_false_bridge": 0,
                "preconfirmation": 0,
                "nonconfirmed": 0,
                "zone_span": 0,
                "merged": 0,
                "open": 0,
                "unqualified_reentry": 0,
                "qualified_components": 0,
                "unqualified_components": 0,
            }
            event_spans: list[int] = []
            atomic_spans: list[int] = []
            year_counts: dict[str, int] = {}
            transition_expected = {
                key: 0
                for key in (
                    "qualification",
                    "unqualified_close",
                    "event_creation",
                    "event_terminal",
                    "accepted_bridge_paths",
                    "rejected_reentry_paths",
                )
            }
            cell_confirmed: set[tuple[str, str]] = set()
            cell_eligible: set[tuple[str, str]] = set()
            cell_events: dict[str, set[tuple[str, str]]] = {}
            cell_spans: dict[str, set[tuple[str, str]]] = {}
            securities = con.execute(
                "SELECT DISTINCT security_id FROM expected_route_key WHERE route_id=? ORDER BY 1",
                [route_id],
            ).fetchall()
            for (security_id,) in securities:
                source = [
                    {
                        "security_id": row[0],
                        "trade_date": row[1],
                        "eligible": row[2],
                        "quality_state": row[3],
                        "raw_state": row[4],
                        "available_time": row[5],
                        "expected_empty_reason": row[6],
                        "source_row_present": row[7],
                    }
                    for row in con.execute(
                        """SELECT security_id,CAST(trade_date AS VARCHAR),eligible,quality_state,raw_state,
                        CAST(available_time AS VARCHAR),expected_empty_reason,source_row_present
                        FROM route_source_daily WHERE route_id=? AND security_id=? ORDER BY trade_date""",
                        [route_id, security_id],
                    ).fetchall()
                ]
                expected = [
                    value[0]
                    for value in con.execute(
                        """SELECT CAST(trade_date AS VARCHAR) FROM expected_route_key
                        WHERE route_id=? AND security_id=? ORDER BY trade_date""",
                        [route_id, security_id],
                    ).fetchall()
                ]
                oracle = source_timeline_oracle(
                    source, expected_dates=expected, d=d, g=g
                )
                route_security = (route_id, security_id)
                if route_security not in reconciled_route_security:
                    _assert_oracle_daily_matches_canonical(
                        con, route_id, security_id, oracle["timeline"]
                    )
                    _assert_source_interval_oracle_matches_upstream(
                        con, route_id, security_id, expected, oracle["atomic_intervals"]
                    )
                    reconciled_route_security.add(route_security)
                aggregate["events"] += oracle["qualified_event_count"]
                aggregate["unique_securities"] += oracle["unique_security_count"]
                aggregate["eligible"] += len(oracle["eligible_valid_keys"])
                aggregate["confirmed"] += len(oracle["confirmed_keys"])
                aggregate["qualified"] += len(oracle["qualified_confirmed_keys"])
                aggregate["asof"] += len(oracle["qualified_asof_keys"])
                aggregate["normally_ended"] += sum(
                    x["termination_reason"] == "natural_state_exit"
                    for x in oracle["components"]
                )
                aggregate["short_drop"] += sum(
                    x["termination_reason"] == "natural_state_exit"
                    and x["confirmed_day_count"] < d
                    for x in oracle["components"]
                )
                aggregate["raw_false_bridge"] += oracle["raw_false_bridged_day_count"]
                aggregate["preconfirmation"] += oracle["preconfirmation_gap_day_count"]
                aggregate["nonconfirmed"] += oracle["total_nonconfirmed_gap_day_count"]
                aggregate["zone_span"] += oracle["membership_count"]
                aggregate["merged"] += oracle["merged_event_count"]
                aggregate["open"] += oracle["open_event_count"]
                aggregate["unqualified_reentry"] += oracle["unqualified_reentry_count"]
                aggregate["qualified_components"] += oracle["qualified_component_count"]
                aggregate["unqualified_components"] += oracle[
                    "unqualified_component_count"
                ]
                event_spans.extend(oracle["event_spans"])
                atomic_spans.extend(oracle["atomic_spans"])
                for year in oracle["event_years"]:
                    year_counts[year] = year_counts.get(year, 0) + 1
                for key in transition_expected:
                    transition_expected[key] += oracle["transition_closure"][key]
                cell_confirmed.update(oracle["confirmed_keys"])
                cell_eligible.update(oracle["eligible_valid_keys"])
                for zone in oracle["zones"]:
                    event_id = f"{security_id}|{zone['scan_event_id']}"
                    cell_events[event_id] = set(zone["confirmed_keys"])
                    cell_spans[event_id] = set(zone["span_keys"])
            cell_oracles[cell_id] = {
                "confirmed": cell_confirmed,
                "eligible": cell_eligible,
                "events": cell_events,
                "spans": cell_spans,
            }
            expected_values = {
                "qualified_event_count": aggregate["events"],
                "unique_securities": aggregate["unique_securities"],
                "retained_confirmed_day_ratio": _oracle_ratio(
                    aggregate["qualified"], aggregate["confirmed"]
                ),
                "confirmed_event_coverage": _oracle_ratio(
                    aggregate["qualified"], aggregate["eligible"]
                ),
                "retrospective_qualified_confirmed_coverage": _oracle_ratio(
                    aggregate["qualified"], aggregate["eligible"]
                ),
                "asof_qualified_confirmed_coverage": _oracle_ratio(
                    aggregate["asof"], aggregate["eligible"]
                ),
                "short_interval_drop_rate": _oracle_ratio(
                    aggregate["short_drop"], aggregate["normally_ended"]
                ),
                "bridged_day_ratio": _oracle_ratio(
                    aggregate["raw_false_bridge"], aggregate["zone_span"]
                ),
                "merge_ratio": _oracle_ratio(aggregate["merged"], aggregate["events"]),
                "open_event_ratio": _oracle_ratio(
                    aggregate["open"], aggregate["events"]
                ),
                "nonzero_years": len(year_counts),
                "max_year_share": _oracle_ratio(
                    max(year_counts.values(), default=0), sum(year_counts.values())
                ),
                "duration_q95_ratio": _oracle_ratio(
                    _oracle_nearest(event_spans, 0.95),
                    _oracle_nearest(atomic_spans, 0.95),
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
            for metric, production in zip(expected_values, observed):
                independent = expected_values[metric]
                passed = _equal(independent, production)
                rows.append(
                    {
                        "candidate_cell_id": cell_id,
                        "metric_id": metric,
                        "independent_value": independent,
                        "production_value": production,
                        "status": "passed" if passed else "failed",
                    }
                )
                if not passed:
                    failures.append(f"{cell_id}:{metric}")
            _append_transition_comparisons(
                con, cell_id, transition_expected, rows, failures
            )
        _append_source_comparison_checks(con, cell_oracles, rows, failures)
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
        "comparison_count": len(rows),
        "failure_count": len(failures),
        "failures": failures[:100],
        "oracle_source_tables": [
            "route_source_daily",
            "expected_route_key",
            "expected_route_key",
            "authorized_upstream_interval",
            "cell_registry",
        ],
        "forbidden_production_oracle_tables_used": False,
        "production_scanner_imported": False,
        "production_metrics_imported": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_independent_validation.json", report)
    if failures:
        raise R2T03IndependentValidationError(
            "independent_validation_failed:" + failures[0]
        )
    return report


def _new_oracle_zone(
    component: Mapping[str, Any], timeline: Sequence[Mapping[str, Any]], ordinal: int
) -> dict[str, Any]:
    return {
        "scan_event_id": f"oracle_event_{ordinal:03d}",
        "component_count": 1,
        "bridge_count": 0,
        "raw_false_bridged_day_count": 0,
        "preconfirmation_gap_day_count": 0,
        "total_nonconfirmed_gap_day_count": 0,
        "zone_span_days": int(component["confirmed_day_count"]),
        "confirmed_keys": _component_keys(component, timeline),
        "span_keys": _component_keys(component, timeline),
        "status": "QUALIFIED_ACTIVE",
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
            f"{primary}|{sidecar}", independent, observed, rows, failures
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
            f"{primary}|{comparison}", independent, observed, rows, failures
        )


def _append_transition_comparisons(
    con: duckdb.DuckDBPyConnection,
    cell_id: str,
    expected: Mapping[str, int],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    observed = dict(
        zip(
            expected,
            con.execute(
                """SELECT
                count(*) FILTER (WHERE entity_kind='component' AND from_state='COMPONENT_FORMING' AND to_state='QUALIFIED_ACTIVE' AND reason_code='d_qualification'),
                count(*) FILTER (WHERE entity_kind='component' AND to_state='UNQUALIFIED_CLOSED' AND reason_code='normal_short_interval_drop'),
                count(*) FILTER (WHERE entity_kind='event_zone' AND from_state='COMPONENT_FORMING' AND to_state='QUALIFIED_ACTIVE' AND reason_code='d_qualification'),
                count(*) FILTER (WHERE entity_kind='event_zone' AND to_state IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED')),
                count(DISTINCT entity_id) FILTER (WHERE entity_kind='bridge'),
                count(DISTINCT entity_id) FILTER (WHERE entity_kind='reentry')
                FROM transition_entity_ledger WHERE candidate_cell_id=?""",
                [cell_id],
            ).fetchone(),
        )
    )
    _append_comparisons(
        cell_id,
        {f"transition_{k}": v for k, v in expected.items()},
        list(observed.values()),
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
        rows,
        failures,
    )


def _append_comparisons(
    identity: str,
    independent: Mapping[str, Any],
    observed: Sequence[Any],
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    for (metric, expected), actual in zip(independent.items(), observed):
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


def _assert_oracle_daily_matches_canonical(
    con: duckdb.DuckDBPyConnection,
    route_id: str,
    security_id: str,
    timeline: Sequence[Mapping[str, Any]],
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
    production = con.execute(
        """SELECT eligible,quality_state,raw_state,confirmed_state,
        coalesce(CAST(confirmed_start_date AS VARCHAR),''),coalesce(CAST(confirmation_time AS VARCHAR),''),
        coalesce(CAST(confirmed_end_date AS VARCHAR),''),coalesce(CAST(exit_observation_time AS VARCHAR),''),
        state_risk_set_eligible,reason_code,hard_break FROM route_daily
        WHERE route_id=? AND security_id=? ORDER BY trade_date""",
        [route_id, security_id],
    ).fetchall()
    expected = [tuple(row.get(field) for field in fields) for row in timeline]
    normalized_production = [tuple(row) for row in production]
    if len(expected) != len(normalized_production):
        raise R2T03IndependentValidationError(
            f"canonical_daily_row_count_mismatch:{route_id}:{security_id}"
        )
    for index, (left, right) in enumerate(zip(expected, normalized_production)):
        if any(not _equal(a, b) for a, b in zip(left, right)):
            raise R2T03IndependentValidationError(
                f"canonical_daily_field_mismatch:{route_id}:{security_id}:{index}"
            )


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


def _oracle_ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, float) or isinstance(right, float):
        return abs(float(left) - float(right)) <= 1e-12
    return left == right
