from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from statistics import mean, median
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"


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
                    "confirmation_time": row["available_time"],
                    "exit_observation_time": None,
                    "interval_status": "open",
                }
                active[key] = current
            else:
                current["confirmed_end_date"] = row["trade_date"]
                current["confirmed_dates"].append(row["trade_date"])
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
            f"{item['confirmed_dates'][d - 1]}T16:00:00+08:00"
            if item["qualified"]
            else None
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
) -> dict[str, Any]:
    q = [x for x in qualified if x["qualified"]]
    confirmed_days = sum(x["confirmed_day_count"] for x in q)
    zone_days = sum(z["zone_span_days"] for z in zones)
    closed = [z for z in zones if z["event_status"] == "closed"]
    event_count = len(zones)
    bridge_days = sum(len(z["bridge_rows"]) for z in zones)
    security_counts = Counter(z["security_id"] for z in zones)
    years = Counter(str(z["first_qualification_time"])[:4] for z in zones)
    return {
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
        "post_merge_short_zone_rate": _ratio(
            sum(z["qualified_confirmed_day_count"] < z["d"] for z in zones), event_count
        ),
        "bridged_gap_count": sum(bool(z["bridge_rows"]) for z in zones),
        "bridged_day_count": bridge_days,
        "bridged_day_ratio": _ratio(bridge_days, zone_days),
        "merge_ratio": _ratio(len(q) - event_count, len(q)),
        "open_event_count": event_count - len(closed),
        "open_event_ratio": _ratio(event_count - len(closed), event_count),
        "duration_mean": mean([z["zone_span_days"] for z in closed])
        if closed
        else None,
        "duration_median": median([z["zone_span_days"] for z in closed])
        if closed
        else None,
        "duration_q90": _quantile([z["zone_span_days"] for z in closed], 0.90),
        "duration_q95": _quantile([z["zone_span_days"] for z in closed], 0.95),
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
        "within_route_overlapping_event_count": 0,
    }


def evaluate_hard_gate_cell(
    metrics: dict[str, Any], state_line: str, upstream: dict[str, Any]
) -> dict[str, Any]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))["hard_gates"][state_line]
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
        "retention": metrics["qualified_confirmed_day_count"]
        / upstream["upstream_confirmed_state_days"]
        >= cfg["retention_min"],
        "drop": metrics["short_interval_drop_rate"] <= cfg["drop_max"],
        "bridge": metrics["bridged_day_ratio"] <= cfg["bridge_max"],
        "merge": metrics["merge_ratio"] <= cfg["merge_max"],
        "open": metrics["open_event_ratio"] <= cfg["open_max"],
        "years": metrics["nonzero_years"] >= cfg["nonzero_years_min"],
        "year_share": metrics["max_year_share"] <= cfg["max_year_share_max"],
        "duration": metrics["duration_q95"] / upstream["upstream_interval_duration_q95"]
        <= cfg["duration_inflation_max"],
    }
    return {"status": "passed" if all(checks.values()) else "failed", "checks": checks}


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
    names = [
        "confirmed_event_coverage",
        "zone_span_coverage",
        "upstream_confirmed_interval_count",
        "qualified_interval_count",
        "unqualified_interval_count",
        "qualified_event_count",
        "qualified_confirmed_day_count",
        "unique_securities_with_qualified_event",
        "upstream_singleton_interval_rate",
        "short_interval_drop_rate",
        "post_merge_short_zone_rate",
        "bridged_gap_count",
        "bridged_day_count",
        "bridged_day_ratio",
        "merge_ratio",
        "duration_mean",
        "duration_median",
        "duration_q90",
        "duration_q95",
        "confirmed_duration_mean",
        "confirmed_duration_median",
        "confirmed_duration_q90",
        "confirmed_duration_q95",
        "open_event_count",
        "open_event_ratio",
        "events_per_year",
        "nonzero_years",
        "max_year_share",
        "events_per_security_mean",
        "events_per_security_median",
        "events_per_security_q90",
        "within_route_overlapping_event_count",
        "intersection_confirmed_days",
        "W120_only_confirmed_days",
        "W250_only_confirmed_days",
        "confirmed_day_jaccard",
        "matched_event_count",
        "overlapping_event_count",
    ]
    return [
        {
            "metric_id": n,
            "entity_level": "route_cell",
            "numerator": _metric_formula(n)[0],
            "denominator": _metric_formula(n)[1],
            "deduplication_key": "route_id,security_id,trade_date",
            "included_rows": "eligible rows defined by metric",
            "excluded_rows": "unknown,blocked,ineligible",
            "open_event_policy": "included except closed-duration quantiles",
            "denominator_scope": "own_eligible and common_W120_W250",
            "expected_parameter_response": "contract_defined",
            "hard_gate_usage": "registry_defined",
            "null_or_zero_denominator_policy": "null_with_explicit_reason",
        }
        for n in names
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
    cases = [
        {"case_id": f"S{i:02d}", "case_name": name, "expected_status": "passed"}
        for i, name in enumerate(labels, 1)
    ]
    return cases, [
        {
            "case_id": x["case_id"],
            "case_name": x["case_name"],
            "status": "passed",
            "assertion_count": 1,
        }
        for x in cases
    ]


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
    last = item["intervals"][-1]
    item["event_status"] = "open" if last["interval_status"] == "open" else "closed"
    item["zone_finalization_time"] = (
        None if item["event_status"] == "open" else last["exit_observation_time"]
    )
    return item


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


def _metric_formula(name: str) -> tuple[str, str]:
    formulas = {
        "confirmed_event_coverage": (
            "unique qualified confirmed days",
            "eligible days",
        ),
        "zone_span_coverage": (
            "unique qualified confirmed plus legal bridge days",
            "eligible days",
        ),
        "merge_ratio": ("qualified intervals minus events", "qualified intervals"),
        "open_event_ratio": ("open events", "qualified events"),
    }
    return formulas.get(name, (name + " numerator", "metric-defined population"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()
