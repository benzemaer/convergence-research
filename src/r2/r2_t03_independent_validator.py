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
        timeline.append(
            {
                **source,
                "trade_date": trade_date,
                "confirmed_state": bool(eligible_valid and raw is True and streak >= k),
                "hard_break": hard_break,
            }
        )
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
        hard_break = any(row["hard_break"] for row in gap)
        raw_false = [
            row
            for row in gap
            if row["eligible"]
            and row["quality_state"] == "valid"
            and row.get("raw_state") is False
        ]
        mergeable_gap = not hard_break and len(raw_false) <= g
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
            open_zone["component_count"] += 1
            open_zone["bridge_count"] += 1
            open_zone["raw_false_bridged_day_count"] += len(raw_false)
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
        trailing_hard_break = any(row["hard_break"] for row in trailing)
        trailing_raw_false = sum(
            row["eligible"]
            and row["quality_state"] == "valid"
            and row.get("raw_state") is False
            for row in trailing
        )
        open_zone["status"] = (
            "FINALIZED_WITH_QUALITY_BREAK"
            if trailing_hard_break
            else "FINALIZED"
            if trailing_raw_false > g
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
    normally_ended = [
        component
        for component in components
        if component["termination_reason"] == "natural_state_exit"
    ]
    event_spans = [zone["zone_span_days"] for zone in zones]
    atomic_spans = [interval["confirmed_day_count"] for interval in intervals]
    return {
        "atomic_intervals": intervals,
        "components": components,
        "zones": zones,
        "confirmed_keys": confirmed_keys,
        "qualified_confirmed_keys": qualified_keys,
        "eligible_valid_keys": eligible_valid_keys,
        "qualified_event_count": len(zones),
        "bridge_count": sum(zone["bridge_count"] for zone in zones),
        "membership_count": sum(zone["zone_span_days"] for zone in zones),
        "confirmed_event_coverage": _oracle_ratio(
            len(qualified_keys), len(eligible_valid_keys)
        ),
        "merge_ratio": _oracle_ratio(
            sum(zone["component_count"] > 1 for zone in zones), len(zones)
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
            aggregate_events = 0
            aggregate_numerator = 0
            aggregate_denominator = 0
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
                    }
                    for row in con.execute(
                        """SELECT security_id,CAST(trade_date AS VARCHAR),eligible,quality_state,raw_state
                        FROM route_daily WHERE route_id=? AND security_id=? ORDER BY trade_date""",
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
                    _assert_source_interval_oracle_matches_upstream(
                        con, route_id, security_id, expected, oracle["atomic_intervals"]
                    )
                    reconciled_route_security.add(route_security)
                aggregate_events += oracle["qualified_event_count"]
                aggregate_numerator += len(oracle["qualified_confirmed_keys"])
                aggregate_denominator += len(oracle["eligible_valid_keys"])
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
                "qualified_event_count": aggregate_events,
                "confirmed_event_coverage": _oracle_ratio(
                    aggregate_numerator, aggregate_denominator
                ),
            }
            observed = con.execute(
                """SELECT qualified_event_count,confirmed_event_coverage
                FROM dg_event_zone_profile WHERE candidate_cell_id=?""",
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
        "oracle_source_tables": ["route_daily", "expected_route_key"],
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
        "zone_span_days": int(component["confirmed_day_count"]),
        "confirmed_keys": _component_keys(component, timeline),
        "span_keys": _component_keys(component, timeline),
        "status": "QUALIFIED_ACTIVE",
    }


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
    upstream = [
        (str(start), str(end), int(count), str(reason))
        for start, end, count, reason in con.execute(
            """SELECT CAST(start_date AS VARCHAR),CAST(end_date AS VARCHAR),
            confirmed_day_count,termination_reason FROM authorized_upstream_interval
            WHERE route_id=? AND security_id=? ORDER BY 1,2,3,4""",
            [route_id, security_id],
        ).fetchall()
    ]
    if rebuilt != upstream:
        raise R2T03IndependentValidationError(
            f"upstream_interval_row_reconciliation_failed:{route_id}:{security_id}"
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
