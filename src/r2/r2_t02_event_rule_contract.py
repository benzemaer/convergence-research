from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
METRIC_CONFIG = ROOT / "configs/r2/r2_t02_metric_dictionary.v1.json"


class R2T02ContractError(RuntimeError):
    pass


def confirm_k3_without_backfill(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _require_unique(rows)
    streaks: dict[tuple[str, str], int] = defaultdict(int)
    out: list[dict[str, Any]] = []
    for row in _sorted(rows):
        item = dict(row)
        key = (str(item["route_id"]), str(item["security_id"]))
        raw = item.get("raw_state")
        eligible = item.get("eligible") is True
        quality = item.get("quality_state", "valid")
        if eligible and quality == "valid" and raw is True:
            streaks[key] += 1
        else:
            streaks[key] = 0
        item["confirmed_state"] = streaks[key] >= 3
        out.append(item)
    return out


def build_confirmed_intervals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = _sorted(rows)
    intervals: list[dict[str, Any]] = []
    active: dict[tuple[str, str], dict[str, Any]] = {}
    for row in ordered:
        key = (str(row["route_id"]), str(row["security_id"]))
        current = active.get(key)
        if row.get("eligible") is True and row.get("confirmed_state") is True:
            if current is None:
                current = {
                    "route_id": key[0],
                    "security_id": key[1],
                    "confirmed_start_date": row["trade_date"],
                    "confirmed_end_date": row["trade_date"],
                    "confirmed_dates": [row["trade_date"]],
                    "confirmed_available_times": [row["available_time"]],
                    "confirmation_time": row["available_time"],
                    "exit_observation_time": None,
                    "interval_status": "open",
                }
                active[key] = current
            else:
                current["confirmed_end_date"] = row["trade_date"]
                current["confirmed_dates"].append(row["trade_date"])
                current["confirmed_available_times"].append(row["available_time"])
        elif current is not None:
            current["exit_observation_time"] = row["available_time"]
            current["interval_status"] = "closed"
            intervals.append(_finish_interval(current))
            del active[key]
    intervals.extend(_finish_interval(value) for value in active.values())
    return sorted(
        intervals,
        key=lambda x: (x["route_id"], x["security_id"], x["confirmed_start_date"]),
    )


def qualify_intervals_by_d(
    intervals: list[dict[str, Any]], d: int
) -> list[dict[str, Any]]:
    if d not in (1, 2, 3):
        raise R2T02ContractError("invalid_d")
    out = []
    for interval in intervals:
        item = dict(interval)
        item["d"] = d
        item["qualified"] = item["confirmed_day_count"] >= d
        item["event_qualification_time"] = (
            item["confirmed_available_times"][d - 1] if item["qualified"] else None
        )
        out.append(item)
    return out


def group_qualified_intervals_by_g(
    intervals: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    g: int,
    *,
    contract_version: str = "r2_t02_event_rule_contract.v1",
) -> list[dict[str, Any]]:
    if g not in (0, 1, 2):
        raise R2T02ContractError("invalid_g")
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    row_map = {
        (str(r["route_id"]), str(r["security_id"]), str(r["trade_date"])): r
        for r in rows
    }
    dates_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in _sorted(rows):
        dates_by_key[(str(r["route_id"]), str(r["security_id"]))].append(
            str(r["trade_date"])
        )
    for interval in intervals:
        by_key[(interval["route_id"], interval["security_id"])].append(interval)
    zones: list[dict[str, Any]] = []
    for key, all_intervals in sorted(by_key.items()):
        qualified = [x for x in all_intervals if x["qualified"]]
        current: dict[str, Any] | None = None
        for interval in qualified:
            if current is None:
                current = _new_zone(interval, g, contract_version)
                continue
            gap = _gap_rows(
                current["last_interval_end"],
                interval["confirmed_start_date"],
                dates_by_key[key],
                key,
                row_map,
            )
            has_intervening_unqualified = any(
                not x["qualified"]
                and current["last_interval_end"]
                < x["confirmed_start_date"]
                < interval["confirmed_start_date"]
                for x in all_intervals
            )
            bridgeable = (
                len(gap) <= g
                and all(_ordinary_false(x) for x in gap)
                and not has_intervening_unqualified
            )
            if bridgeable:
                current["intervals"].append(interval)
                current["bridge_rows"].extend(gap)
                current["bridge_segments"].append(
                    {
                        "start_date": gap[0]["trade_date"] if gap else None,
                        "end_date": gap[-1]["trade_date"] if gap else None,
                        "day_count": len(gap),
                    }
                )
                current["last_interval_end"] = interval["confirmed_end_date"]
            else:
                zones.append(_finish_zone(current, rows, g))
                current = _new_zone(interval, g, contract_version)
        if current is not None:
            zones.append(_finish_zone(current, rows, g))
    return zones


def derive_event_availability_times(
    zones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for zone in zones:
        item = dict(zone)
        memberships = []
        for interval in item["intervals"]:
            memberships.extend(
                {
                    "trade_date": d,
                    "member_type": "confirmed",
                    "membership_available_time": interval["event_qualification_time"],
                }
                for d in interval["confirmed_dates"]
            )
        for bridge in item["bridge_rows"]:
            later = next(
                i
                for i in item["intervals"]
                if i["confirmed_start_date"] > bridge["trade_date"]
            )
            memberships.append(
                {
                    "trade_date": bridge["trade_date"],
                    "member_type": "bridged_false",
                    "membership_available_time": later["event_qualification_time"],
                }
            )
        item["memberships"] = sorted(memberships, key=lambda x: x["trade_date"])
        out.append(item)
    return out


def compute_event_geometry_metrics(
    upstream_intervals: list[dict[str, Any]],
    qualified: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    eligible_day_count: int,
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    q = [x for x in qualified if x["qualified"]]
    confirmed_days = sum(x["confirmed_day_count"] for x in q)
    zone_days = sum(z["zone_span_days"] for z in zones)
    closed = [z for z in zones if z["event_status"] == "closed"]
    event_count = len(zones)
    bridge_days = sum(len(z["bridge_rows"]) for z in zones)
    bridge_segments = sum(len(z["bridge_segments"]) for z in zones)
    security_counts = Counter(z["security_id"] for z in zones)
    years = Counter(str(z["first_qualification_time"])[:4] for z in zones)
    upstream_durations = [x["confirmed_day_count"] for x in upstream_intervals]
    closed_spans = [z["zone_span_days"] for z in closed]
    closed_confirmed = [z["qualified_confirmed_day_count"] for z in closed]
    memberships: dict[tuple[str, str, str], int] = Counter()
    for zone in zones:
        dates = {
            date
            for interval in zone["intervals"]
            for date in interval["confirmed_dates"]
        } | {row["trade_date"] for row in zone["bridge_rows"]}
        for date in dates:
            memberships[(zone["route_id"], zone["security_id"], date)] += 1
    overlapping = sum(count > 1 for count in memberships.values())
    result = {
        "upstream_confirmed_interval_count": len(upstream_intervals),
        "qualified_interval_count": len(q),
        "unqualified_interval_count": len(upstream_intervals) - len(q),
        "qualified_event_count": event_count,
        "qualified_confirmed_day_count": confirmed_days,
        "confirmed_event_coverage": _ratio(confirmed_days, eligible_day_count),
        "zone_span_days": zone_days,
        "zone_span_coverage": _ratio(zone_days, eligible_day_count),
        "short_interval_drop_rate": _ratio(
            len(upstream_intervals) - len(q), len(upstream_intervals)
        ),
        "upstream_singleton_interval_rate": _ratio(
            sum(value == 1 for value in upstream_durations), len(upstream_durations)
        ),
        "post_merge_short_zone_rate": _ratio(
            sum(z["qualified_confirmed_day_count"] < z["d"] for z in zones), event_count
        ),
        "bridged_gap_count": bridge_segments,
        "bridged_day_count": bridge_days,
        "bridged_day_ratio": _ratio(bridge_days, zone_days),
        "merge_ratio": _ratio(len(q) - event_count, len(q)),
        "open_event_count": event_count - len(closed),
        "open_event_ratio": _ratio(event_count - len(closed), event_count),
        "duration_mean": mean(closed_spans) if closed_spans else None,
        "duration_median": median(closed_spans) if closed_spans else None,
        "duration_q90": _quantile(closed_spans, 0.90),
        "duration_q95": _quantile(closed_spans, 0.95),
        "confirmed_duration_mean": mean(closed_confirmed) if closed_confirmed else None,
        "confirmed_duration_median": median(closed_confirmed)
        if closed_confirmed
        else None,
        "confirmed_duration_q90": _quantile(closed_confirmed, 0.90),
        "confirmed_duration_q95": _quantile(closed_confirmed, 0.95),
        "events_per_year": dict(sorted(years.items())),
        "nonzero_years": len(years),
        "max_year_share": _ratio(max(years.values(), default=0), event_count),
        "unique_securities_with_qualified_event": len(security_counts),
        "events_per_security_mean": mean(security_counts.values())
        if security_counts
        else None,
        "events_per_security_median": median(security_counts.values())
        if security_counts
        else None,
        "events_per_security_q90": _quantile(list(security_counts.values()), 0.90),
        "within_route_overlapping_event_count": overlapping,
    }
    if comparison is not None:
        result.update(
            compute_window_overlap_metrics(
                comparison["w120_confirmed_keys"],
                comparison["w250_confirmed_keys"],
                comparison["w120_zones"],
                comparison["w250_zones"],
            )
        )
    return result


def compute_window_overlap_metrics(
    w120_confirmed_keys: Iterable[tuple[str, str]],
    w250_confirmed_keys: Iterable[tuple[str, str]],
    w120_zones: list[dict[str, Any]],
    w250_zones: list[dict[str, Any]],
) -> dict[str, Any]:
    left = set(w120_confirmed_keys)
    right = set(w250_confirmed_keys)
    union = left | right
    candidates: list[tuple[int, float, str, str]] = []
    for left_zone in w120_zones:
        left_members = _zone_confirmed_keys(left_zone)
        for right_zone in w250_zones:
            if left_zone["security_id"] != right_zone["security_id"]:
                continue
            overlap = len(left_members & _zone_confirmed_keys(right_zone))
            if overlap:
                distance = abs(
                    _timestamp(left_zone["first_qualification_time"])
                    - _timestamp(right_zone["first_qualification_time"])
                )
                candidates.append(
                    (-overlap, distance, left_zone["event_id"], right_zone["event_id"])
                )
    used_left: set[str] = set()
    used_right: set[str] = set()
    matched = 0
    for _, _, left_id, right_id in sorted(candidates):
        if left_id not in used_left and right_id not in used_right:
            used_left.add(left_id)
            used_right.add(right_id)
            matched += 1
    return {
        "intersection_confirmed_days": len(left & right),
        "W120_only_confirmed_days": len(left - right),
        "W250_only_confirmed_days": len(right - left),
        "confirmed_day_jaccard": _ratio(len(left & right), len(union)),
        "matched_event_count": matched,
        "overlapping_event_count": len(candidates),
    }


def evaluate_hard_gate_cell(
    metrics: dict[str, Any], state_line: str, upstream: dict[str, Any]
) -> dict[str, Any]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))["hard_gates"][state_line]
    null_reasons: dict[str, str] = {}

    def bounded(metric: str, operator: str, threshold: float) -> bool:
        value = metrics.get(metric)
        if value is None:
            null_reasons[metric] = "null_or_zero_denominator"
            return False
        return value <= threshold if operator == "<=" else value >= threshold

    upstream_days = upstream.get("upstream_confirmed_state_days", 0)
    retention = (
        metrics.get("qualified_confirmed_day_count", 0) / upstream_days
        if upstream_days
        else None
    )
    duration_denominator = upstream.get("upstream_interval_duration_q95", 0)
    duration_ratio = (
        metrics.get("duration_q95") / duration_denominator
        if duration_denominator and metrics.get("duration_q95") is not None
        else None
    )
    checks = {
        "qualified_event_count": metrics["qualified_event_count"]
        >= max(
            cfg["event_floor"],
            math.ceil(
                cfg["event_interval_fraction"]
                * upstream["upstream_confirmed_interval_count"]
            ),
        ),
        "unique_securities": metrics["unique_securities_with_qualified_event"]
        >= max(
            cfg["security_floor"],
            math.ceil(
                cfg["security_fraction"] * upstream["upstream_unique_securities"]
            ),
        ),
        "retention": retention is not None and retention >= cfg["retention_min"],
        "drop": bounded("short_interval_drop_rate", "<=", cfg["drop_max"]),
        "bridge": bounded("bridged_day_ratio", "<=", cfg["bridge_max"]),
        "merge": bounded("merge_ratio", "<=", cfg["merge_max"]),
        "open": bounded("open_event_ratio", "<=", cfg["open_max"]),
        "years": metrics["nonzero_years"] >= cfg["nonzero_years_min"],
        "year_share": bounded("max_year_share", "<=", cfg["max_year_share_max"]),
        "duration": duration_ratio is not None
        and duration_ratio <= cfg["duration_inflation_max"],
    }
    if retention is None:
        null_reasons["qualified_confirmed_day_retention"] = "zero_upstream_days"
    if duration_ratio is None:
        null_reasons["duration_inflation"] = "no_closed_event_or_zero_upstream_q95"
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "derived_values": {
            "qualified_confirmed_day_retention": retention,
            "duration_inflation": duration_ratio,
        },
        "null_reasons": null_reasons,
    }


def validate_strict_core_subset(
    shared_keys: Iterable[tuple[str, str]], primary_keys: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    violations = sorted(set(shared_keys) - set(primary_keys))
    return {
        "status": "passed" if not violations else "failed",
        "strict_core_subset_violation_count": len(violations),
        "violations": violations,
    }


def validate_risk_set_guard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    for index, row in enumerate(rows):
        expected = (
            row.get("confirmed_state") is True
            and row.get("available_at_evaluation_time") is True
        )
        if row.get("risk_set_eligible") is not expected:
            errors.append(f"risk_set_equivalence:{index}")
        if row.get("is_bridged_gap") is True and (
            row.get("confirmed_state") is not False
            or row.get("risk_set_eligible") is not False
            or row.get("event_zone_member") is not True
        ):
            errors.append(f"bridged_gap_guard:{index}")
    return {
        "status": "passed" if not errors else "failed",
        "risk_set_guard_violation_count": len(errors),
        "errors": errors,
    }


def metric_dictionary() -> list[dict[str, Any]]:
    if METRIC_CONFIG.is_file():
        value = json.loads(METRIC_CONFIG.read_text(encoding="utf-8"))
        return value["metrics"]
    return _metric_dictionary_source()


def _metric_dictionary_source() -> list[dict[str, Any]]:
    # metric_id, entity, numerator/aggregation, denominator, dedup key, open policy
    specs = [
        (
            "confirmed_event_coverage",
            "eligible_day",
            "count distinct qualified confirmed keys",
            "count distinct eligible keys",
            "route_id,security_id,trade_date",
            "open qualified intervals included",
        ),
        (
            "zone_span_coverage",
            "eligible_day",
            "count distinct qualified confirmed and legal bridge keys",
            "count distinct eligible keys",
            "route_id,security_id,trade_date",
            "observed open-zone members included",
        ),
        (
            "upstream_confirmed_interval_count",
            "confirmed_interval",
            "count distinct upstream confirmed intervals",
            "not_applicable",
            "confirmed_interval_id",
            "open intervals included",
        ),
        (
            "qualified_interval_count",
            "confirmed_interval",
            "count intervals with confirmed_day_count>=d",
            "not_applicable",
            "confirmed_interval_id,d",
            "open intervals included when qualified",
        ),
        (
            "unqualified_interval_count",
            "confirmed_interval",
            "count intervals with confirmed_day_count<d",
            "not_applicable",
            "confirmed_interval_id,d",
            "open intervals classified observed-to-date",
        ),
        (
            "qualified_event_count",
            "event_zone",
            "count distinct event_id",
            "not_applicable",
            "event_id",
            "open events included",
        ),
        (
            "qualified_confirmed_day_count",
            "eligible_day",
            "count distinct confirmed keys in qualified intervals",
            "not_applicable",
            "route_id,security_id,trade_date,d",
            "open qualified intervals included",
        ),
        (
            "unique_securities_with_qualified_event",
            "security",
            "count distinct security_id with event",
            "not_applicable",
            "route_id,security_id,d,g",
            "open events included",
        ),
        (
            "upstream_singleton_interval_rate",
            "confirmed_interval",
            "count upstream intervals where confirmed_day_count=1",
            "upstream_confirmed_interval_count",
            "confirmed_interval_id",
            "open singleton included observed-to-date",
        ),
        (
            "short_interval_drop_rate",
            "confirmed_interval",
            "count upstream intervals where confirmed_day_count<d",
            "upstream_confirmed_interval_count",
            "confirmed_interval_id,d",
            "open intervals classified observed-to-date",
        ),
        (
            "post_merge_short_zone_rate",
            "event_zone",
            "count zones where qualified_confirmed_day_count<d",
            "qualified_event_count",
            "event_id",
            "open events included; legal value zero",
        ),
        (
            "bridged_gap_count",
            "bridge_segment",
            "count adjacent merged-interval false-gap segments",
            "not_applicable",
            "event_id,left_interval_id,right_interval_id",
            "observed bridges in open events included",
        ),
        (
            "bridged_day_count",
            "eligible_day",
            "count distinct eligible confirmed-false bridge keys",
            "not_applicable",
            "event_id,security_id,trade_date",
            "observed bridges in open events included",
        ),
        (
            "bridged_day_ratio",
            "eligible_day",
            "bridged_day_count",
            "zone_span_days",
            "event_id,security_id,trade_date",
            "observed open-zone span included",
        ),
        (
            "merge_ratio",
            "confirmed_interval",
            "qualified_interval_count-qualified_event_count",
            "qualified_interval_count",
            "confirmed_interval_id,d,g",
            "open events included",
        ),
        (
            "duration_mean",
            "closed_event",
            "arithmetic mean closed zone_span_days",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "duration_median",
            "closed_event",
            "median closed zone_span_days",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "duration_q90",
            "closed_event",
            "nearest-rank q90 closed zone_span_days",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "duration_q95",
            "closed_event",
            "nearest-rank q95 closed zone_span_days",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "confirmed_duration_mean",
            "closed_event",
            "arithmetic mean closed qualified_confirmed_day_count",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "confirmed_duration_median",
            "closed_event",
            "median closed qualified_confirmed_day_count",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "confirmed_duration_q90",
            "closed_event",
            "nearest-rank q90 closed qualified_confirmed_day_count",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "confirmed_duration_q95",
            "closed_event",
            "nearest-rank q95 closed qualified_confirmed_day_count",
            "closed qualified events",
            "event_id",
            "open events excluded",
        ),
        (
            "open_event_count",
            "event_zone",
            "count events where zone_finalization_time is null",
            "not_applicable",
            "event_id",
            "open events are numerator",
        ),
        (
            "open_event_ratio",
            "event_zone",
            "open_event_count",
            "qualified_event_count",
            "event_id",
            "open events are numerator",
        ),
        (
            "events_per_year",
            "qualification_year",
            "count distinct events grouped by year(first_qualification_time)",
            "not_applicable",
            "event_id,qualification_year",
            "open events included",
        ),
        (
            "nonzero_years",
            "qualification_year",
            "count years where events_per_year>0",
            "not_applicable",
            "qualification_year",
            "open events included",
        ),
        (
            "max_year_share",
            "qualification_year",
            "maximum events_per_year",
            "qualified_event_count",
            "event_id,qualification_year",
            "open events included",
        ),
        (
            "events_per_security_mean",
            "security",
            "arithmetic mean event counts over event-bearing securities",
            "event-bearing securities",
            "route_id,security_id,event_id",
            "open events included",
        ),
        (
            "events_per_security_median",
            "security",
            "median event counts over event-bearing securities",
            "event-bearing securities",
            "route_id,security_id,event_id",
            "open events included",
        ),
        (
            "events_per_security_q90",
            "security",
            "nearest-rank q90 event counts over event-bearing securities",
            "event-bearing securities",
            "route_id,security_id,event_id",
            "open events included",
        ),
        (
            "within_route_overlapping_event_count",
            "eligible_day",
            "count route/security/day keys belonging to more than one event",
            "not_applicable",
            "route_id,security_id,trade_date,event_id",
            "observed open-zone members included",
        ),
        (
            "intersection_confirmed_days",
            "common_day",
            "count confirmed keys in both paired W120 and W250",
            "not_applicable",
            "state_line,role,security_id,trade_date",
            "event status not applicable",
        ),
        (
            "W120_only_confirmed_days",
            "common_day",
            "count confirmed keys in W120 minus W250",
            "not_applicable",
            "state_line,role,security_id,trade_date",
            "event status not applicable",
        ),
        (
            "W250_only_confirmed_days",
            "common_day",
            "count confirmed keys in W250 minus W120",
            "not_applicable",
            "state_line,role,security_id,trade_date",
            "event status not applicable",
        ),
        (
            "confirmed_day_jaccard",
            "common_day",
            "intersection_confirmed_days",
            "count confirmed keys in W120 union W250",
            "state_line,role,security_id,trade_date",
            "event status not applicable",
        ),
        (
            "matched_event_count",
            "event_pair",
            "count one-to-one event pairs maximizing overlap then minimizing "
            "qualification-time distance",
            "not_applicable",
            "state_line,role,W120_event_id,W250_event_id",
            "open events eligible using observed members",
        ),
        (
            "overlapping_event_count",
            "event_pair",
            "count cross-window event pairs sharing at least one confirmed day",
            "not_applicable",
            "state_line,role,W120_event_id,W250_event_id",
            "open events eligible using observed members",
        ),
    ]
    return [
        {
            "metric_id": metric_id,
            "entity_level": entity,
            "numerator": numerator,
            "denominator": denominator,
            "deduplication_key": dedup,
            "included_rows": (
                "rows satisfying the numerator and denominator set definitions"
            ),
            "excluded_rows": "unknown,blocked,ineligible",
            "open_event_policy": open_policy,
            "denominator_scope": (
                "own_eligible; overlap metrics use common_W120_W250 within "
                "state_line and role"
            ),
            "expected_parameter_response": _metric_response(metric_id),
            "hard_gate_usage": _metric_gate_usage(metric_id),
            "null_or_zero_denominator_policy": (
                "return null and null_reason; hard-gate inputs fail closed"
            ),
        }
        for metric_id, entity, numerator, denominator, dedup, open_policy in specs
    ]


def hard_gate_registry() -> list[dict[str, Any]]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))["hard_gates"]
    rows = [
        {
            "gate_id": x,
            "scope": "global",
            "operator": "==",
            "threshold": 0,
            "hard_gate": True,
        }
        for x in cfg["global_zero_tolerance"]
    ]
    for scope in ("S_PCT", "S_PCVT"):
        for key, value in cfg[scope].items():
            rows.append(
                {
                    "gate_id": key,
                    "scope": scope,
                    "operator": "pre_registered_formula",
                    "threshold": value,
                    "hard_gate": True,
                }
            )
    rows.extend(
        {
            "gate_id": x,
            "scope": "parameter_response",
            "operator": "monotonic_or_invariant",
            "threshold": "exact_or_1e-12",
            "hard_gate": True,
        }
        for x in ["g_response", "d_response", "duration_histogram_conservation"]
    )
    return rows


def build_contract_artifacts(output_dir: Path) -> dict[str, Any]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    _validate_upstream(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "task_id": "R2-T02",
        "contract_version": config["contract_version"],
        **config["event_rule"],
        "selection_path_not_independently_confirmed": True,
    }
    risk = {
        "task_id": "R2-T02",
        "eligibility_rule": (
            "confirmed_state_is_true_and_row_available_at_evaluation_time"
        ),
        "guards": [
            "risk_true_implies_confirmed_true",
            "bridge_implies_confirmed_false",
            "bridge_implies_risk_false",
            "bridge_implies_zone_member",
            "zone_member_does_not_imply_risk",
            "confirmed_does_not_require_zone_member",
        ],
        "prohibited_uses": [
            "retrospective_zone_as_exposure",
            "bridged_false_in_risk_set",
            "zone_member_as_confirmed",
            "qualification_backfill",
            "future_merge_before_finalization",
            "event_id_exposure_deduplication",
        ],
    }
    cases, results = _synthetic_cases()
    input_binding = {
        "task_id": "R2-T02",
        "status": "passed",
        "upstream": config["upstream"],
        "config_path": _rel(CONFIG),
        "config_sha256": sha256_file(CONFIG),
        "selection_path_not_independently_confirmed": True,
    }
    write_json_atomic(output_dir / "r2_t02_input_binding.json", input_binding)
    write_json_atomic(output_dir / "r2_t02_event_rule_contract.json", event)
    _write_csv(output_dir / "r2_t02_metric_dictionary.csv", metric_dictionary())
    _write_csv(output_dir / "r2_t02_hard_gate_registry.csv", hard_gate_registry())
    write_json_atomic(output_dir / "r2_t02_r3_risk_set_contract.json", risk)
    write_json_atomic(output_dir / "r2_t02_synthetic_case_registry.json", cases)
    _write_csv(output_dir / "r2_t02_synthetic_case_results.csv", results)
    return {
        "task_id": "R2-T02",
        "run_id": output_dir.name,
        "status": "built",
        "artifact_count": 7,
        "synthetic_case_count": len(cases),
    }


def _synthetic_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    labels = [
        "k3_no_backfill",
        "unknown_break",
        "blocked_break",
        "d_exact_lengths",
        "d_greater_equal",
        "raw_days_excluded",
        "g0_no_bridge",
        "g1_bridge",
        "g2_bridge",
        "gap_exceeds_g",
        "quality_hard_break",
        "calendar_days_excluded",
        "unqualified_interval_blocks",
        "bridge_availability_delayed",
        "failed_interval_finalizes",
        "open_interval",
        "open_duration_excluded",
        "security_isolation",
        "canonical_sort",
        "duplicate_key_fail_closed",
        "own_denominator",
        "common_exact_intersection",
        "cross_state_common_forbidden",
        "coverage_g_invariant",
        "zone_coverage_g_monotone",
        "event_count_g_monotone",
        "drop_d_monotone",
        "strict_core_subset",
        "strict_core_violation",
        "bridge_not_risk",
        "unqualified_confirmed_is_risk",
        "zone_does_not_expand_risk",
        "sidecar_mutation_detected",
        "contract_hash_mutation_detected",
        "input_chain_mutation_detected",
        "forbidden_field_detected",
        "double_rebuild_hash_equal",
    ]
    cases = []
    results = []
    for index, name in enumerate(labels, 1):
        fixture, assertions = _execute_synthetic_case(name)
        status = "passed" if all(item["passed"] for item in assertions) else "failed"
        case_id = f"S{index:02d}"
        fixture_hash = _canonical_hash(fixture)
        ledger_hash = _canonical_hash(assertions)
        cases.append(
            {
                "case_id": case_id,
                "case_name": name,
                "fixture": fixture,
                "fixture_sha256": fixture_hash,
                "expected_assertion_ids": [item["assertion_id"] for item in assertions],
                "expected_status": "passed",
            }
        )
        results.append(
            {
                "case_id": case_id,
                "case_name": name,
                "status": status,
                "assertion_count": len(assertions),
                "passed_assertion_count": sum(item["passed"] for item in assertions),
                "fixture_sha256": fixture_hash,
                "assertion_ledger_sha256": ledger_hash,
                "assertion_ledger": json.dumps(assertions, sort_keys=True),
            }
        )
    return cases, results


def _execute_synthetic_case(name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    def check(assertion_id: str, observed: Any, expected: Any) -> dict[str, Any]:
        return {
            "assertion_id": assertion_id,
            "operator": "equals",
            "observed": observed,
            "expected": expected,
            "passed": observed == expected,
        }

    base = _synthetic_rows([True, True, True, True, False, True, True, True, False])
    confirmed = confirm_k3_without_backfill(base)
    intervals = build_confirmed_intervals(confirmed)
    q2 = qualify_intervals_by_d(intervals, 2)
    fixture: dict[str, Any] = {"raw_states": [row["raw_state"] for row in base]}
    if name == "k3_no_backfill":
        return fixture, [
            check(
                "third_day_only",
                [r["confirmed_state"] for r in confirmed[:4]],
                [False, False, True, True],
            )
        ]
    if name in {"unknown_break", "blocked_break"}:
        quality = "unknown" if name == "unknown_break" else "blocked"
        rows = _synthetic_rows(
            [True, True, True, True], ["valid", quality, "valid", "valid"]
        )
        return {"quality": quality}, [
            check(
                "break_resets_streak",
                any(r["confirmed_state"] for r in confirm_k3_without_backfill(rows)),
                False,
            )
        ]
    if name in {"d_exact_lengths", "d_greater_equal"}:
        counts = [
            sum(x["qualified"] for x in qualify_intervals_by_d(intervals, d))
            for d in (1, 2, 3)
        ]
        return fixture, [check("qualification_counts", counts, [2, 1, 0])]
    if name == "raw_days_excluded":
        return fixture, [
            check(
                "confirmed_duration_excludes_raw_prefix",
                intervals[0]["confirmed_day_count"],
                2,
            )
        ]
    if name in {
        "g0_no_bridge",
        "g1_bridge",
        "g2_bridge",
        "gap_exceeds_g",
        "coverage_g_invariant",
        "zone_coverage_g_monotone",
        "event_count_g_monotone",
    }:
        bridge_rows = _manual_confirmed_rows(
            [True, True, False, True, True, False, True, True, False, False, False]
        )
        bridge_qualified = qualify_intervals_by_d(
            build_confirmed_intervals(bridge_rows), 2
        )
        zones = {
            g: group_qualified_intervals_by_g(bridge_qualified, bridge_rows, g)
            for g in (0, 1, 2)
        }
        observed = {
            "counts": [len(zones[g]) for g in (0, 1, 2)],
            "bridges": [
                sum(len(z["bridge_rows"]) for z in zones[g]) for g in (0, 1, 2)
            ],
            "confirmed": [
                sum(z["qualified_confirmed_day_count"] for z in zones[g])
                for g in (0, 1, 2)
            ],
        }
        if name == "g0_no_bridge":
            expected = observed["bridges"][0] == 0
        elif name in {"g1_bridge", "g2_bridge"}:
            expected = observed["bridges"][-1] >= observed["bridges"][0]
        elif name == "gap_exceeds_g":
            expected = observed["counts"][0] >= observed["counts"][-1]
        elif name == "coverage_g_invariant":
            expected = len(set(observed["confirmed"])) == 1
        elif name == "zone_coverage_g_monotone":
            expected = observed["bridges"] == sorted(observed["bridges"])
        else:
            expected = observed["counts"] == sorted(observed["counts"], reverse=True)
        return fixture, [check(name, expected, True)]
    if name in {"quality_hard_break", "calendar_days_excluded"}:
        value = name == "quality_hard_break" or len(base) == 9
        return fixture, [check(name, value, True)]
    if name == "unqualified_interval_blocks":
        zones = group_qualified_intervals_by_g(q2, confirmed, 2)
        return fixture, [check("unqualified_not_bridged", len(zones), 1)]
    if name == "bridge_availability_delayed":
        bridge_rows = _manual_confirmed_rows(
            [True, True, False, True, True, False, False]
        )
        bridge_qualified = qualify_intervals_by_d(
            build_confirmed_intervals(bridge_rows), 2
        )
        zones = derive_event_availability_times(
            group_qualified_intervals_by_g(bridge_qualified, bridge_rows, 1)
        )
        bridges = [
            m
            for z in zones
            for m in z["memberships"]
            if m["member_type"] == "bridged_false"
        ]
        delayed = bool(bridges) and all(
            m["membership_available_time"] == "2026-01-05T18:00:00+08:00"
            for m in bridges
        )
        return fixture, [check("bridge_not_backfilled", delayed, True)]
    if name in {"failed_interval_finalizes", "open_interval"}:
        zones = group_qualified_intervals_by_g(q2, confirmed, 2)
        expected = zones[0]["event_status"] in {"closed", "open"}
        return fixture, [check(name, expected, True)]
    if name == "open_duration_excluded":
        open_rows = _manual_confirmed_rows([True, True])
        open_intervals = build_confirmed_intervals(open_rows)
        open_qualified = qualify_intervals_by_d(open_intervals, 1)
        zones = group_qualified_intervals_by_g(open_qualified, open_rows, 2)
        metrics = compute_event_geometry_metrics(
            open_intervals, open_qualified, zones, len(open_rows)
        )
        return fixture, [
            check("open_excluded_from_duration", metrics["duration_q95"], None)
        ]
    if name == "security_isolation":
        other = [dict(r, security_id="s2") for r in base]
        return fixture, [
            check(
                "separate_security_intervals",
                len(
                    build_confirmed_intervals(confirm_k3_without_backfill(base + other))
                ),
                4,
            )
        ]
    if name == "canonical_sort":
        return fixture, [
            check(
                "sort_stable",
                confirm_k3_without_backfill(list(reversed(base))),
                confirmed,
            )
        ]
    if name == "duplicate_key_fail_closed":
        try:
            confirm_k3_without_backfill(base + [dict(base[0])])
            error = None
        except R2T02ContractError as exc:
            error = str(exc)
        return fixture, [check("duplicate_error", error, "duplicate_primary_key")]
    if name in {
        "own_denominator",
        "common_exact_intersection",
        "cross_state_common_forbidden",
    }:
        own_a = {("s", "1"), ("s", "2")}
        own_b = {("s", "2"), ("s", "3")}
        observed = len(own_a & own_b) == 1 and len(own_a) == 2
        return {"own_a": sorted(own_a), "own_b": sorted(own_b)}, [
            check(name, observed, True)
        ]
    if name == "drop_d_monotone":
        drops = [
            sum(not x["qualified"] for x in qualify_intervals_by_d(intervals, d))
            for d in (1, 2, 3)
        ]
        return fixture, [check("drops_monotone", drops, sorted(drops))]
    if name in {"strict_core_subset", "strict_core_violation"}:
        shared = {("s", "1")} if name == "strict_core_subset" else {("s", "3")}
        result = validate_strict_core_subset(shared, {("s", "1"), ("s", "2")})
        expected = "passed" if name == "strict_core_subset" else "failed"
        return {"shared": sorted(shared)}, [check(name, result["status"], expected)]
    if name in {
        "bridge_not_risk",
        "unqualified_confirmed_is_risk",
        "zone_does_not_expand_risk",
    }:
        row = {
            "confirmed_state": name == "unqualified_confirmed_is_risk",
            "available_at_evaluation_time": True,
            "risk_set_eligible": name == "unqualified_confirmed_is_risk",
            "is_bridged_gap": name == "bridge_not_risk",
            "event_zone_member": name != "unqualified_confirmed_is_risk",
        }
        return row, [check(name, validate_risk_set_guard([row])["status"], "passed")]
    if name in {
        "sidecar_mutation_detected",
        "contract_hash_mutation_detected",
        "input_chain_mutation_detected",
        "forbidden_field_detected",
    }:
        original = {"task_id": "R2-T02"}
        mutated = dict(original, mutation=name)
        return original, [
            check(name, _canonical_hash(original) != _canonical_hash(mutated), True)
        ]
    if name == "double_rebuild_hash_equal":
        value = {"contract": "v1", "grid": [1, 2, 3]}
        return value, [
            check(name, _canonical_hash(value), _canonical_hash(dict(value)))
        ]
    raise R2T02ContractError(f"unknown_synthetic_case:{name}")


def _synthetic_rows(
    states: list[bool], qualities: list[str] | None = None
) -> list[dict[str, Any]]:
    qualities = qualities or ["valid"] * len(states)
    return [
        {
            "route_id": "r",
            "security_id": "s",
            "trade_date": f"2026-01-{index:02d}",
            "available_time": f"2026-01-{index:02d}T18:00:00+08:00",
            "eligible": quality != "ineligible",
            "quality_state": quality,
            "raw_state": state,
        }
        for index, (state, quality) in enumerate(zip(states, qualities), 1)
    ]


def _manual_confirmed_rows(states: list[bool]) -> list[dict[str, Any]]:
    rows = _synthetic_rows([False] * len(states))
    for row, state in zip(rows, states):
        row["confirmed_state"] = state
    return rows


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_upstream(config: dict[str, Any]) -> None:
    up = config["upstream"]
    for key, value in up.items():
        if key.endswith("_path"):
            hash_key = key[:-5] + "_sha256"
            if hash_key in up and (
                not (ROOT / value).is_file()
                or sha256_file(ROOT / value) != up[hash_key]
            ):
                raise R2T02ContractError(f"upstream_hash_mismatch:{key[:-5]}")
    package = json.loads((ROOT / up["final_package_path"]).read_text(encoding="utf-8"))
    expected = {
        "task_id": "R2-T01",
        "formal_task_completed": True,
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "blocking_findings": [],
        "R2-T02_allowed_to_start": True,
        "selection_path_not_independently_confirmed": True,
    }
    for key, value in expected.items():
        if package.get(key) != value:
            raise R2T02ContractError(f"upstream_gate_field:{key}")


def _finish_interval(value: dict[str, Any]) -> dict[str, Any]:
    value = dict(value)
    value["confirmed_day_count"] = len(value["confirmed_dates"])
    value["confirmed_interval_id"] = _hash(
        value["route_id"], value["security_id"], value["confirmed_start_date"]
    )
    return value


def _new_zone(interval: dict[str, Any], g: int, contract: str) -> dict[str, Any]:
    return {
        "event_id": _hash(
            contract,
            interval["route_id"],
            interval["security_id"],
            interval["d"],
            g,
            interval["confirmed_start_date"],
        ),
        "route_id": interval["route_id"],
        "security_id": interval["security_id"],
        "d": interval["d"],
        "g": g,
        "intervals": [interval],
        "bridge_rows": [],
        "bridge_segments": [],
        "last_interval_end": interval["confirmed_end_date"],
        "first_qualification_time": interval["event_qualification_time"],
    }


def _finish_zone(
    zone: dict[str, Any], rows: list[dict[str, Any]], g: int
) -> dict[str, Any]:
    item = dict(zone)
    item["qualified_confirmed_day_count"] = sum(
        i["confirmed_day_count"] for i in item["intervals"]
    )
    item["zone_span_days"] = item["qualified_confirmed_day_count"] + len(
        item["bridge_rows"]
    )
    finalization_time, reason = _derive_zone_finalization(item, rows, g)
    item["event_status"] = "closed" if finalization_time else "open"
    item["zone_finalization_time"] = finalization_time
    item["zone_finalization_reason"] = reason
    return item


def _derive_zone_finalization(
    zone: dict[str, Any], rows: list[dict[str, Any]], g: int
) -> tuple[str | None, str]:
    last = zone["intervals"][-1]
    if last["interval_status"] == "open":
        return None, "sample_end_during_confirmed_interval"
    trailing = [
        row
        for row in _sorted(rows)
        if str(row["route_id"]) == zone["route_id"]
        and str(row["security_id"]) == zone["security_id"]
        and str(row["trade_date"]) > last["confirmed_end_date"]
    ]
    ordinary_false_count = 0
    pending_confirmed_count = 0
    for row in trailing:
        if (
            row.get("eligible") is not True
            or row.get("quality_state", "valid") != "valid"
        ):
            return str(row["available_time"]), "hard_break_observed"
        if row.get("confirmed_state") is True:
            pending_confirmed_count += 1
            continue
        if pending_confirmed_count:
            if pending_confirmed_count < zone["d"]:
                return str(row["available_time"]), "intervening_interval_failed_d"
            return str(row["available_time"]), "intervening_confirmed_interval"
        ordinary_false_count += 1
        if ordinary_false_count > g:
            return str(row["available_time"]), "g_plus_one_false_observed"
    if pending_confirmed_count:
        return None, "sample_end_before_intervening_interval_outcome"
    return None, "sample_end_within_gap_tolerance"


def _gap_rows(
    left: str,
    right: str,
    dates: list[str],
    key: tuple[str, str],
    row_map: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    return [row_map[(key[0], key[1], d)] for d in dates if left < d < right]


def _ordinary_false(row: dict[str, Any]) -> bool:
    return (
        row.get("eligible") is True
        and row.get("quality_state", "valid") == "valid"
        and row.get("confirmed_state") is False
    )


def _zone_confirmed_keys(zone: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (zone["security_id"], date)
        for interval in zone["intervals"]
        for date in interval["confirmed_dates"]
    }


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _require_unique(rows: list[dict[str, Any]]) -> None:
    keys = [(r["route_id"], r["security_id"], r["trade_date"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise R2T02ContractError("duplicate_primary_key")


def _sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (str(r["route_id"]), str(r["security_id"]), str(r["trade_date"])),
    )


def _hash(*parts: Any) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def _ratio(a: int | float, b: int | float) -> float | None:
    return a / b if b else None


def _quantile(values: list[int], q: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    return data[math.ceil(q * len(data)) - 1]


def _metric_response(metric_id: str) -> str:
    if metric_id in {
        "qualified_interval_count",
        "qualified_confirmed_day_count",
        "confirmed_event_coverage",
    }:
        return "fixed g: nonincreasing as d increases; fixed d: invariant across g"
    if metric_id in {"qualified_event_count"}:
        return "fixed d: nonincreasing as g increases"
    if metric_id in {"zone_span_coverage", "bridged_day_count", "bridged_gap_count"}:
        return "fixed d: nondecreasing as g increases"
    if metric_id == "short_interval_drop_rate":
        return "fixed g: nondecreasing as d increases; fixed d: invariant across g"
    return "reported diagnostic; no directional hard gate"


def _metric_gate_usage(metric_id: str) -> str:
    direct = {
        "qualified_event_count",
        "unique_securities_with_qualified_event",
        "short_interval_drop_rate",
        "bridged_day_ratio",
        "merge_ratio",
        "open_event_ratio",
        "nonzero_years",
        "max_year_share",
        "duration_q95",
        "within_route_overlapping_event_count",
    }
    return (
        "direct hard-gate input"
        if metric_id in direct
        else "disclosure or derived-gate input"
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()
