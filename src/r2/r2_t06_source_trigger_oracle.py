# ruff: noqa: E501

"""Source-fact oracle for the R2-T06 event-zone acceptance gate.

The oracle is deliberately ledger-oriented: it derives confirmed intervals,
materializes every inter-component gap as a trigger table, uses accepted edges
to form maximal partitions, and only then projects event and membership facts.
It consumes dense source observations and the frozen transition registry; it
does not consume any event-zone or membership result table.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import duckdb

CONTRACT_VERSION = "r2_t02_confirmed_event_zone_state_machine_contract.v8"

ATOMIC_FIELDS = (
    "route_id",
    "security_id",
    "ordinal",
    "start_date",
    "end_date",
    "confirmed_day_count",
    "termination_reason",
    "exit_observation_time",
)
COMPONENT_FIELDS = (
    "route_id",
    "security_id",
    "component_id",
    "start_date",
    "end_date",
    "confirmed_day_count",
    "qualified",
    "qualification_time",
)
EVENT_FIELDS = (
    "state_version_id",
    "event_id",
    "security_id",
    "first_component_start_date",
    "first_qualification_time",
    "last_confirmed_end_date",
    "last_exit_observation_time",
    "zone_finalization_time",
    "zone_status",
    "exit_reason",
    "left_censored",
    "right_censored",
    "component_interval_count",
    "bridge_count",
    "bridged_gap_days",
    "zone_confirmed_day_count",
    "zone_trading_span",
    "confirmed_density",
    "bridged_gap_ratio",
    "zone_revision_count",
)
MEMBERSHIP_FIELDS = (
    "state_version_id",
    "event_id",
    "security_id",
    "trade_date",
    "confirmed_state",
    "component_member",
    "retrospective_component_member",
    "component_qualified_as_of",
    "event_zone_member",
    "is_prequalification_confirmed_day",
    "is_bridged_gap",
    "is_unqualified_reentry_day",
    "event_status_as_of",
    "zone_revision",
    "membership_available_time",
    "state_risk_set_eligible",
    "qualified_event_risk_set_eligible",
)
TRANSITION_FIELDS = (
    "state_version_id",
    "event_id",
    "security_id",
    "from_state",
    "to_state",
    "reason_code",
    "trigger_trade_date",
)


def _date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _dt(value: Any) -> datetime:
    text = str(value).replace("Z", "+00:00").replace("T", " ")
    return datetime.fromisoformat(text)


def _time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return _dt(value).isoformat(sep=" ")


def _date_text(value: Any) -> str:
    return _date(value).isoformat()


def _max_time(left: str, right: str | None) -> str:
    if right is None or _dt(left) >= _dt(right):
        return left
    return right


@dataclass
class Fact:
    row_index: int
    trade_date: date
    available_time: str
    eligible: bool
    quality_state: str
    raw_state: bool | None
    source_row_present: bool
    expected_empty_reason: str | None
    confirmed_state: bool = False
    hard_break: bool = False

    @property
    def valid_true(self) -> bool:
        return bool(
            self.source_row_present
            and self.eligible
            and self.quality_state == "valid"
            and self.raw_state is True
        )

    @property
    def state_risk(self) -> bool:
        return bool(
            self.eligible and self.quality_state == "valid" and self.confirmed_state
        )


@dataclass
class Interval:
    ordinal: int
    start_index: int
    end_index: int
    confirmed_day_count: int
    termination_reason: str
    exit_index: int


@dataclass
class Component:
    ordinal: int
    start_index: int
    end_index: int
    confirmed_day_count: int
    qualified: bool
    qualification_index: int | None
    termination_reason: str
    exit_index: int

    @property
    def component_id(self) -> str:
        return f"component_{self.ordinal:03d}"


@dataclass
class Trigger:
    kind: str
    available_time: str | None
    status: str
    reason: str


@dataclass
class Gap:
    rows: list[Fact]
    raw_false_rows: list[Fact]
    preconfirmation_rows: list[Fact]
    raw_false_gap_count: int
    early_trigger: Trigger | None


@dataclass
class OracleBundle:
    atomic: list[dict[str, Any]] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    memberships: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    accepted_reentry_count: int = 0
    unqualified_reentry_count: int = 0
    quality_break_count: int = 0
    right_censor_count: int = 0

    def extend(self, other: OracleBundle) -> None:
        self.atomic.extend(other.atomic)
        self.components.extend(other.components)
        self.events.extend(other.events)
        self.memberships.extend(other.memberships)
        self.transitions.extend(other.transitions)
        self.accepted_reentry_count += other.accepted_reentry_count
        self.unqualified_reentry_count += other.unqualified_reentry_count
        self.quality_break_count += other.quality_break_count
        self.right_censor_count += other.right_censor_count


def _derive_intervals(
    rows: list[Fact], K: int = 3
) -> tuple[list[Interval], list[Component]]:
    streak = 0
    current_start: int | None = None
    intervals: list[Interval] = []
    for index, row in enumerate(rows):
        row.hard_break = not (
            row.source_row_present
            and row.eligible
            and row.quality_state == "valid"
            and row.raw_state is not None
        )
        if row.valid_true:
            streak += 1
        else:
            streak = 0
        row.confirmed_state = row.valid_true and streak >= K
        if row.confirmed_state and current_start is None:
            current_start = index
        elif not row.confirmed_state and current_start is not None:
            intervals.append(
                Interval(
                    len(intervals) + 1,
                    current_start,
                    index - 1,
                    index - current_start,
                    "quality_interruption" if row.hard_break else "natural_state_exit",
                    index,
                )
            )
            current_start = None
    if current_start is not None:
        intervals.append(
            Interval(
                len(intervals) + 1,
                current_start,
                len(rows) - 1,
                len(rows) - current_start,
                "sample_end_censoring",
                len(rows) - 1,
            )
        )
    components = [
        Component(
            interval.ordinal,
            interval.start_index,
            interval.end_index,
            interval.confirmed_day_count,
            interval.confirmed_day_count >= 2,
            interval.start_index + 1 if interval.confirmed_day_count >= 2 else None,
            interval.termination_reason,
            interval.exit_index,
        )
        for interval in intervals
    ]
    return intervals, components


def _atomic_records(
    route_id: str, security_id: str, rows: list[Fact], intervals: list[Interval]
) -> list[dict[str, Any]]:
    records = []
    for interval in intervals:
        records.append(
            {
                "route_id": route_id,
                "security_id": security_id,
                "ordinal": interval.ordinal,
                "start_date": _date_text(rows[interval.start_index].trade_date),
                "end_date": _date_text(rows[interval.end_index].trade_date),
                "confirmed_day_count": interval.confirmed_day_count,
                "termination_reason": interval.termination_reason,
                "exit_observation_time": _time(
                    rows[interval.exit_index].available_time
                ),
            }
        )
    return records


def _component_records(
    route_id: str, security_id: str, rows: list[Fact], components: list[Component]
) -> list[dict[str, Any]]:
    records = []
    for component in components:
        records.append(
            {
                "route_id": route_id,
                "security_id": security_id,
                "component_id": component.component_id,
                "start_date": _date_text(rows[component.start_index].trade_date),
                "end_date": _date_text(rows[component.end_index].trade_date),
                "confirmed_day_count": component.confirmed_day_count,
                "qualified": component.qualified,
                "qualification_time": (
                    _time(rows[component.qualification_index].available_time)
                    if component.qualification_index is not None
                    else None
                ),
            }
        )
    return records


def _gap(rows: list[Fact], left: Component, right: Component, g: int) -> Gap:
    gap_rows = rows[left.end_index + 1 : right.start_index]
    raw_false_rows: list[Fact] = []
    preconfirmation_rows: list[Fact] = []
    raw_false_count = 0
    early_trigger: Trigger | None = None
    for row in gap_rows:
        if row.hard_break and early_trigger is None:
            early_trigger = Trigger(
                "HARD_BREAK",
                row.available_time,
                "FINALIZED_WITH_QUALITY_BREAK",
                "quality_break",
            )
        if row.eligible and row.quality_state == "valid" and row.raw_state is False:
            raw_false_count += 1
            raw_false_rows.append(row)
            if raw_false_count == g + 1 and early_trigger is None:
                early_trigger = Trigger(
                    "G_PLUS_ONE_RAW_FALSE",
                    row.available_time,
                    "FINALIZED",
                    "raw_false_gap_exceeds_g",
                )
        elif row.valid_true and not row.confirmed_state:
            preconfirmation_rows.append(row)
    return Gap(
        gap_rows, raw_false_rows, preconfirmation_rows, raw_false_count, early_trigger
    )


def _trailing_trigger(rows: list[Fact], start_index: int, g: int) -> Trigger | None:
    raw_false_count = 0
    for row in rows[start_index + 1 :]:
        if row.hard_break:
            return Trigger(
                "HARD_BREAK",
                row.available_time,
                "FINALIZED_WITH_QUALITY_BREAK",
                "quality_break",
            )
        if row.eligible and row.quality_state == "valid" and row.raw_state is False:
            raw_false_count += 1
            if raw_false_count == g + 1:
                return Trigger(
                    "G_PLUS_ONE_RAW_FALSE",
                    row.available_time,
                    "FINALIZED",
                    "raw_false_gap_exceeds_g",
                )
    return None


def _union_find(size: int, edges: Iterable[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(size))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left, right in edges:
        union(left, right)
    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(size):
        groups[find(index)].append(index)
    return sorted(groups.values(), key=lambda group: group[0])


def _event_identity(
    state_version_id: str,
    candidate_cell_id: str,
    security_id: str,
    component: Component,
    rows: list[Fact],
) -> tuple[str, str]:
    qtime = _time(rows[component.qualification_index].available_time)
    payload = {
        "contract_version": CONTRACT_VERSION,
        "state_version_id": state_version_id,
        "security_id": security_id,
        "first_qualified_component_identity": {
            "source_candidate_cell_id": candidate_cell_id,
            "first_component_id": component.component_id,
            "first_component_start_date": rows[
                component.start_index
            ].trade_date.isoformat(),
            "first_qualification_time": qtime,
        },
    }
    text = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), text


def _exit_time(rows: list[Fact], component: Component) -> str:
    return rows[component.exit_index].available_time


def _event_last_exit_time(
    rows: list[Fact], first_date: date, end_date: date, finalization_time: str | None
) -> str | None:
    upper = _date(finalization_time) if finalization_time else end_date
    values = [
        rows[index].available_time
        for index in range(1, len(rows))
        if first_date <= rows[index].trade_date <= upper
        and rows[index - 1].confirmed_state
        and not rows[index].confirmed_state
    ]
    return max(values, key=_dt) if values else None


def _add_transition(
    bundle: OracleBundle,
    state: str,
    event_id: str,
    security_id: str,
    first_start: date,
    from_state: str,
    to_state: str,
    reason: str,
    timed: str | None = None,
) -> None:
    bundle.transitions.append(
        {
            "state_version_id": state,
            "event_id": event_id,
            "security_id": security_id,
            "from_state": from_state,
            "to_state": to_state,
            "reason_code": reason,
            # The committed replay ledger uses the event start date for
            # transitions without an explicit available_time.
            "trigger_trade_date": _date_text(_date(timed) if timed else first_start),
        }
    )


def _membership_row(
    state: str,
    event_id: str,
    security_id: str,
    row: Fact,
    *,
    component_member: bool,
    retrospective: bool,
    component_qualified: bool,
    event_zone_member: bool,
    prequalification: bool,
    bridged: bool,
    unqualified: bool,
    status: str,
    revision: int,
    available_time: str,
    qualified_risk: bool,
    state_risk: bool | None = None,
) -> dict[str, Any]:
    return {
        "state_version_id": state,
        "event_id": event_id,
        "security_id": security_id,
        "trade_date": _date_text(row.trade_date),
        "confirmed_state": row.confirmed_state,
        "component_member": component_member,
        "retrospective_component_member": retrospective,
        "component_qualified_as_of": component_qualified,
        "event_zone_member": event_zone_member,
        "is_prequalification_confirmed_day": prequalification,
        "is_bridged_gap": bridged,
        "is_unqualified_reentry_day": unqualified,
        "event_status_as_of": status,
        "zone_revision": revision,
        "membership_available_time": _time(available_time),
        "state_risk_set_eligible": row.state_risk if state_risk is None else state_risk,
        "qualified_event_risk_set_eligible": qualified_risk,
    }


def _append_component_membership(
    output: list[dict[str, Any]],
    state: str,
    event_id: str,
    security_id: str,
    rows: list[Fact],
    component: Component,
    base_time: str,
    revision: int,
    qualified_revision: int,
    prequalification_status: str,
    event_zone_member: bool,
    unqualified: bool = False,
) -> None:
    for index in range(component.start_index, component.end_index + 1):
        row = rows[index]
        component_qualified = bool(
            component.qualified
            and component.qualification_index is not None
            and index >= component.qualification_index
        )
        active = bool(event_zone_member and component_qualified)
        status = "QUALIFIED_ACTIVE" if active else prequalification_status
        row_revision = qualified_revision if active else revision
        output.append(
            _membership_row(
                state,
                event_id,
                security_id,
                row,
                component_member=bool(event_zone_member or unqualified),
                retrospective=event_zone_member,
                component_qualified=component_qualified,
                event_zone_member=event_zone_member,
                prequalification=not component_qualified,
                bridged=False,
                unqualified=unqualified,
                status=status,
                revision=row_revision,
                available_time=_max_time(row.available_time, base_time),
                qualified_risk=bool(active and row.state_risk and not unqualified),
            )
        )


def _append_gap_membership(
    output: list[dict[str, Any]],
    state: str,
    event_id: str,
    security_id: str,
    gap: Gap,
    base_time: str,
    revision: int,
) -> None:
    for row in gap.raw_false_rows:
        output.append(
            _membership_row(
                state,
                event_id,
                security_id,
                row,
                component_member=False,
                retrospective=False,
                component_qualified=False,
                event_zone_member=True,
                prequalification=False,
                bridged=True,
                unqualified=False,
                status="GAP_PENDING",
                revision=revision,
                available_time=base_time,
                qualified_risk=False,
                state_risk=False,
            )
        )
    for row in gap.preconfirmation_rows:
        output.append(
            _membership_row(
                state,
                event_id,
                security_id,
                row,
                component_member=False,
                retrospective=False,
                component_qualified=False,
                event_zone_member=True,
                prequalification=True,
                bridged=False,
                unqualified=False,
                status="GAP_PENDING",
                revision=revision,
                available_time=base_time,
                qualified_risk=False,
                state_risk=False,
            )
        )


def _build_security_bundle(
    route_id: str,
    state: str,
    candidate_cell_id: str,
    security_id: str,
    rows: list[Fact],
    d: int,
    g: int,
) -> OracleBundle:
    bundle = OracleBundle()
    intervals, components = _derive_intervals(rows)
    for component in components:
        component.qualified = component.confirmed_day_count >= d
        component.qualification_index = (
            component.start_index + d - 1 if component.qualified else None
        )
    bundle.atomic.extend(_atomic_records(route_id, security_id, rows, intervals))
    bundle.components.extend(
        _component_records(route_id, security_id, rows, components)
    )

    gaps = [
        _gap(rows, left, right, g) for left, right in zip(components, components[1:])
    ]
    accepted_edges: list[tuple[int, int]] = []
    for index, gap in enumerate(gaps):
        left, right = components[index], components[index + 1]
        if left.qualified and right.qualified and gap.early_trigger is None:
            if gap.raw_false_gap_count > 0:
                accepted_edges.append((index, index + 1))
    groups = _union_find(len(components), accepted_edges)
    for positions in groups:
        qualified_positions = [
            index for index in positions if components[index].qualified
        ]
        if not qualified_positions:
            continue
        first_position = qualified_positions[0]
        last_position = qualified_positions[-1]
        first_component = components[first_position]
        last_component = components[last_position]
        event_id, identity = _event_identity(
            state, candidate_cell_id, security_id, first_component, rows
        )
        current_revision = 0
        memberships: list[dict[str, Any]] = []
        base_time = rows[first_component.qualification_index].available_time  # type: ignore[index]
        _append_component_membership(
            memberships,
            state,
            event_id,
            security_id,
            rows,
            first_component,
            base_time,
            0,
            0,
            "COMPONENT_FORMING",
            True,
        )
        for position in qualified_positions[1:]:
            previous = position - 1
            gap = gaps[previous]
            next_component = components[position]
            _append_gap_membership(
                memberships,
                state,
                event_id,
                security_id,
                gap,
                rows[next_component.qualification_index].available_time,  # type: ignore[index]
                current_revision,
            )
            current_revision += 1
            _append_component_membership(
                memberships,
                state,
                event_id,
                security_id,
                rows,
                next_component,
                rows[next_component.qualification_index].available_time,  # type: ignore[index]
                current_revision - 1,
                current_revision,
                "REENTRY_PENDING_QUALIFICATION",
                True,
            )
            bundle.accepted_reentry_count += 1
        next_position = (
            last_position + 1 if last_position + 1 < len(components) else None
        )
        next_component = (
            components[next_position] if next_position is not None else None
        )
        final_trigger: Trigger
        final_gap: Gap | None = (
            gaps[last_position] if next_position is not None else None
        )
        unqualified_component: Component | None = None
        if final_gap is not None and final_gap.early_trigger is not None:
            final_trigger = final_gap.early_trigger
        elif next_component is None:
            trailing = _trailing_trigger(rows, last_component.end_index, g)
            final_trigger = trailing or Trigger(
                "RIGHT_CENSOR",
                None,
                "RIGHT_CENSORED",
                "sample_end_open_zone",
            )
        elif next_component.qualified:
            qualification_time = rows[next_component.qualification_index].available_time  # type: ignore[index]
            final_trigger = Trigger(
                "UNQUALIFIED_REENTRY_EXIT",
                qualification_time,
                "FINALIZED",
                "unqualified_reentry_blocks_merge",
            )
        else:
            unqualified_component = next_component
            if next_component.termination_reason == "sample_end_censoring":
                final_trigger = Trigger(
                    "RIGHT_CENSOR",
                    None,
                    "RIGHT_CENSORED",
                    "sample_end_before_requalification",
                )
            elif next_component.termination_reason == "quality_interruption":
                final_trigger = Trigger(
                    "HARD_BREAK",
                    _exit_time(rows, next_component),
                    "FINALIZED_WITH_QUALITY_BREAK",
                    "quality_break",
                )
            else:
                final_trigger = Trigger(
                    "UNQUALIFIED_REENTRY_EXIT",
                    _exit_time(rows, next_component),
                    "FINALIZED",
                    "unqualified_reentry_blocks_merge",
                )
        unqualified_path = unqualified_component is not None
        if unqualified_path:
            base = (
                rows[unqualified_component.end_index].available_time
                if final_trigger.status == "RIGHT_CENSORED"
                else _exit_time(rows, unqualified_component)
            )
            _append_component_membership(
                memberships,
                state,
                event_id,
                security_id,
                rows,
                unqualified_component,
                base,
                0,
                0,
                "REENTRY_PENDING_QUALIFICATION",
                False,
                True,
            )
            bundle.unqualified_reentry_count += 1
        if final_trigger.available_time is not None:
            terminal_date = _date(final_trigger.available_time)
            if not any(
                row["trade_date"] == terminal_date.isoformat() for row in memberships
            ):
                terminal = next(row for row in rows if row.trade_date == terminal_date)
                memberships.append(
                    _membership_row(
                        state,
                        event_id,
                        security_id,
                        terminal,
                        component_member=False,
                        retrospective=False,
                        component_qualified=False,
                        event_zone_member=False,
                        prequalification=False,
                        bridged=False,
                        unqualified=False,
                        status=final_trigger.status,
                        revision=current_revision,
                        available_time=final_trigger.available_time,
                        qualified_risk=False,
                        state_risk=False,
                    )
                )
        first_date = rows[first_component.start_index].trade_date
        last_date = rows[last_component.end_index].trade_date
        end_date = (
            _date(final_trigger.available_time)
            if final_trigger.available_time
            else last_date
        )
        span = sum(first_date <= row.trade_date <= last_date for row in rows)
        accepted_gaps = [gaps[pos - 1] for pos in qualified_positions[1:]]
        bridge_days = sum(gap.raw_false_gap_count for gap in accepted_gaps)
        confirmed_days = sum(
            components[pos].confirmed_day_count for pos in qualified_positions
        )
        event = {
            "state_version_id": state,
            "event_id": event_id,
            "security_id": security_id,
            "first_component_start_date": first_date.isoformat(),
            "first_qualification_time": _time(base_time),
            "last_confirmed_end_date": last_date.isoformat(),
            "last_exit_observation_time": _event_last_exit_time(
                rows, first_date, end_date, final_trigger.available_time
            ),
            "zone_finalization_time": _time(final_trigger.available_time),
            "zone_status": final_trigger.status,
            "exit_reason": final_trigger.reason,
            "left_censored": first_component.start_index == 0,
            "right_censored": final_trigger.status == "RIGHT_CENSORED",
            "component_interval_count": len(qualified_positions),
            "bridge_count": len(accepted_gaps),
            "bridged_gap_days": bridge_days,
            "zone_confirmed_day_count": confirmed_days,
            "zone_trading_span": span,
            "confirmed_density": confirmed_days / span if span else 0.0,
            "bridged_gap_ratio": bridge_days / span if span else 0.0,
            "zone_revision_count": current_revision + 1,
        }
        event["identity_payload"] = identity
        bundle.events.append(event)
        bundle.memberships.extend(memberships)
        if final_trigger.status == "FINALIZED_WITH_QUALITY_BREAK":
            bundle.quality_break_count += 1
        if final_trigger.status == "RIGHT_CENSORED":
            bundle.right_censor_count += 1
        first_start = first_date
        _add_transition(
            bundle,
            state,
            event_id,
            security_id,
            first_start,
            "COMPONENT_FORMING",
            "QUALIFIED_ACTIVE",
            "d_qualification",
        )
        for position in qualified_positions[1:]:
            _add_transition(
                bundle,
                state,
                event_id,
                security_id,
                first_start,
                "QUALIFIED_ACTIVE",
                "GAP_PENDING",
                "gap_pending",
            )
            _add_transition(
                bundle,
                state,
                event_id,
                security_id,
                first_start,
                "GAP_PENDING",
                "REENTRY_PENDING_QUALIFICATION",
                "reentry_pending",
            )
            _add_transition(
                bundle,
                state,
                event_id,
                security_id,
                first_start,
                "REENTRY_PENDING_QUALIFICATION",
                "QUALIFIED_ACTIVE",
                "reentry_reaches_d_merge",
            )
        if final_gap is not None and final_gap.rows:
            _add_transition(
                bundle,
                state,
                event_id,
                security_id,
                first_start,
                "QUALIFIED_ACTIVE",
                "GAP_PENDING",
                "gap_pending",
            )
        if unqualified_path:
            _add_transition(
                bundle,
                state,
                event_id,
                security_id,
                first_start,
                "GAP_PENDING",
                "REENTRY_PENDING_QUALIFICATION",
                "unqualified_reentry_observed",
            )
            _add_transition(
                bundle,
                state,
                event_id,
                security_id,
                first_start,
                "REENTRY_PENDING_QUALIFICATION",
                final_trigger.status,
                final_trigger.reason,
            )
        else:
            _add_transition(
                bundle,
                state,
                event_id,
                security_id,
                first_start,
                "GAP_PENDING",
                final_trigger.status,
                final_trigger.reason,
                None,
            )
    return bundle


def _source_groups(
    con: duckdb.DuckDBPyConnection, route_id: str
) -> Iterable[tuple[str, list[Fact]]]:
    rows = con.execute(
        """
        SELECT security_id,trade_date,cast(available_time AS VARCHAR),eligible,
               quality_state,raw_state,source_row_present,expected_empty_reason
        FROM src.route_dense_input WHERE route_id=? ORDER BY security_id,trade_date
        """,
        [route_id],
    ).fetchall()
    current: str | None = None
    bucket: list[Fact] = []
    for index, row in enumerate(rows):
        security_id = str(row[0])
        if current is not None and security_id != current:
            yield current, bucket
            bucket = []
        current = security_id
        bucket.append(
            Fact(
                len(bucket),
                _date(row[1]),
                str(row[2]),
                bool(row[3]),
                str(row[4]),
                None if row[5] is None else bool(row[5]),
                bool(row[6]),
                row[7],
            )
        )
    if current is not None:
        yield current, bucket


def build_source_oracle(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> OracleBundle:
    bundle = OracleBundle()
    for version in config["selected_versions"]:
        route = con.execute(
            "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
            [version["source_candidate_cell_id"]],
        ).fetchone()[0]
        for security_id, rows in _source_groups(con, route):
            bundle.extend(
                _build_security_bundle(
                    route,
                    version["state_version_id"],
                    version["source_candidate_cell_id"],
                    security_id,
                    rows,
                    int(version["d"]),
                    int(version["g"]),
                )
            )
    return bundle


def _counter_mismatch(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> int:
    left = Counter(tuple(row.get(field) for field in fields) for row in expected)
    right = Counter(tuple(row.get(field) for field in fields) for row in actual)
    return sum((left - right).values()) + sum((right - left).values())


def _key_mismatch(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]], keys: tuple[str, ...]
) -> int:
    return _counter_mismatch(expected, actual, keys)


def _field_mismatch(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    keys: tuple[str, ...],
    fields: tuple[str, ...],
) -> int:
    expected_map = {tuple(row.get(key) for key in keys): row for row in expected}
    actual_map = {tuple(row.get(key) for key in keys): row for row in actual}
    mismatch = len(set(expected_map) ^ set(actual_map))
    for key in set(expected_map) & set(actual_map):
        mismatch += sum(
            expected_map[key].get(field) != actual_map[key].get(field)
            for field in fields
        )
    return mismatch


def compare_source_oracle(
    expected: OracleBundle, actual: OracleBundle
) -> dict[str, int]:
    event_keys = ("state_version_id", "event_id", "security_id")
    membership_keys = ("state_version_id", "event_id", "security_id", "trade_date")
    transition_keys = (
        "state_version_id",
        "event_id",
        "security_id",
        "from_state",
        "to_state",
        "reason_code",
    )
    checks = {
        "source_trigger_atomic_interval_mismatch": _counter_mismatch(
            expected.atomic, actual.atomic, ATOMIC_FIELDS
        ),
        "source_trigger_component_mismatch": _counter_mismatch(
            expected.components, actual.components, COMPONENT_FIELDS
        ),
        "source_trigger_event_partition_mismatch": _key_mismatch(
            expected.events, actual.events, event_keys
        ),
        "source_trigger_event_boundary_mismatch": _field_mismatch(
            expected.events,
            actual.events,
            event_keys,
            (
                "first_component_start_date",
                "first_qualification_time",
                "last_confirmed_end_date",
                "zone_status",
                "exit_reason",
                "left_censored",
                "right_censored",
            ),
        ),
        "source_trigger_transition_mismatch": _key_mismatch(
            expected.transitions, actual.transitions, transition_keys
        ),
        "source_trigger_transition_time_mismatch": _field_mismatch(
            expected.transitions,
            actual.transitions,
            transition_keys,
            ("trigger_trade_date",),
        ),
        "source_trigger_membership_key_mismatch": _key_mismatch(
            expected.memberships, actual.memberships, membership_keys
        ),
        "source_trigger_membership_flag_mismatch": _field_mismatch(
            expected.memberships,
            actual.memberships,
            membership_keys,
            (
                "confirmed_state",
                "component_member",
                "retrospective_component_member",
                "component_qualified_as_of",
                "event_zone_member",
                "is_prequalification_confirmed_day",
                "is_bridged_gap",
                "is_unqualified_reentry_day",
                "event_status_as_of",
                "zone_revision",
                "state_risk_set_eligible",
                "qualified_event_risk_set_eligible",
            ),
        ),
        "source_trigger_membership_availability_mismatch": _field_mismatch(
            expected.memberships,
            actual.memberships,
            membership_keys,
            ("membership_available_time",),
        ),
        "source_trigger_finalization_time_mismatch": _field_mismatch(
            expected.events,
            actual.events,
            event_keys,
            ("zone_finalization_time",),
        ),
        "source_trigger_maximal_partition_mismatch": _field_mismatch(
            expected.events,
            actual.events,
            event_keys,
            (
                "component_interval_count",
                "bridge_count",
                "bridged_gap_days",
                "zone_confirmed_day_count",
                "zone_trading_span",
                "zone_revision_count",
            ),
        ),
        "source_trigger_bridge_mismatch": _field_mismatch(
            expected.events,
            actual.events,
            event_keys,
            ("bridge_count", "bridged_gap_days"),
        ),
        "source_trigger_accepted_reentry_mismatch": abs(
            expected.accepted_reentry_count - actual.accepted_reentry_count
        ),
        "source_trigger_unqualified_reentry_mismatch": abs(
            expected.unqualified_reentry_count - actual.unqualified_reentry_count
        ),
        "source_trigger_quality_break_mismatch": abs(
            expected.quality_break_count - actual.quality_break_count
        ),
        "source_trigger_right_censor_mismatch": abs(
            expected.right_censor_count - actual.right_censor_count
        ),
    }
    return checks


def replay_bundle(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> OracleBundle:
    bundle = OracleBundle()
    selected_states = {
        version["state_version_id"] for version in config["selected_versions"]
    }
    route_by_state = {
        version["state_version_id"]: con.execute(
            "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
            [version["source_candidate_cell_id"]],
        ).fetchone()[0]
        for version in config["selected_versions"]
    }
    route_marks = ",".join("?" for _ in route_by_state.values())
    atomic = con.execute(
        f"SELECT route_id,security_id,ordinal,cast(start_date as varchar),cast(end_date as varchar),confirmed_day_count,termination_reason,cast(exit_observation_time as varchar) FROM r2_t06_replayed_atomic_interval WHERE route_id IN ({route_marks})",
        list(route_by_state.values()),
    ).fetchall()
    bundle.atomic = [dict(zip(ATOMIC_FIELDS, row)) for row in atomic]
    for row in bundle.atomic:
        row["start_date"] = _date_text(row["start_date"])
        row["end_date"] = _date_text(row["end_date"])
        row["exit_observation_time"] = _time(row["exit_observation_time"])
    component = con.execute(
        f"SELECT route_id,security_id,component_id,cast(start_date as varchar),cast(end_date as varchar),confirmed_day_count,qualified,cast(qualification_time as varchar) FROM r2_t06_replayed_component WHERE route_id IN ({route_marks})",
        list(route_by_state.values()),
    ).fetchall()
    bundle.components = [dict(zip(COMPONENT_FIELDS, row)) for row in component]
    for row in bundle.components:
        row["start_date"] = _date_text(row["start_date"])
        row["end_date"] = _date_text(row["end_date"])
        row["qualification_time"] = _time(row["qualification_time"])
    event = con.execute(
        "SELECT state_version_id,event_id,security_id,cast(first_component_start_date as varchar),cast(first_qualification_time as varchar),cast(last_confirmed_end_date as varchar),cast(last_exit_observation_time as varchar),cast(zone_finalization_time as varchar),zone_status,exit_reason,left_censored,right_censored,component_interval_count,bridge_count,bridged_gap_days,zone_confirmed_day_count,zone_trading_span,confirmed_density,bridged_gap_ratio,zone_revision_count FROM r2_t06_replayed_event_zone WHERE state_version_id IN (?,?)",
        list(selected_states),
    ).fetchall()
    bundle.events = [dict(zip(EVENT_FIELDS, row)) for row in event]
    for row in bundle.events:
        for field_name in (
            "first_component_start_date",
            "last_confirmed_end_date",
        ):
            row[field_name] = _date_text(row[field_name])
        for field_name in (
            "first_qualification_time",
            "last_exit_observation_time",
            "zone_finalization_time",
        ):
            row[field_name] = _time(row[field_name])
    membership = con.execute(
        "SELECT state_version_id,event_id,security_id,cast(trade_date as varchar),confirmed_state,component_member,retrospective_component_member,component_qualified_as_of,event_zone_member,is_prequalification_confirmed_day,is_bridged_gap,is_unqualified_reentry_day,event_status_as_of,zone_revision,cast(membership_available_time as varchar),state_risk_set_eligible,qualified_event_risk_set_eligible FROM r2_t06_replayed_event_membership WHERE state_version_id IN (?,?)",
        list(selected_states),
    ).fetchall()
    bundle.memberships = [dict(zip(MEMBERSHIP_FIELDS, row)) for row in membership]
    for row in bundle.memberships:
        row["trade_date"] = _date_text(row["trade_date"])
        row["membership_available_time"] = _time(row["membership_available_time"])
    transition = con.execute(
        "SELECT state_version_id,event_id,security_id,from_state,to_state,reason_code,cast(trigger_trade_date as varchar) FROM r2_t06_replayed_transition_ledger WHERE state_version_id IN (?,?)",
        list(selected_states),
    ).fetchall()
    bundle.transitions = [dict(zip(TRANSITION_FIELDS, row)) for row in transition]
    for row in bundle.transitions:
        row["trigger_trade_date"] = _date_text(row["trigger_trade_date"])
    bundle.accepted_reentry_count = sum(
        row["reason_code"] == "reentry_reaches_d_merge" for row in bundle.transitions
    )
    bundle.unqualified_reentry_count = sum(
        row["is_unqualified_reentry_day"] for row in bundle.memberships
    )
    bundle.quality_break_count = sum(
        row["zone_status"] == "FINALIZED_WITH_QUALITY_BREAK" for row in bundle.events
    )
    bundle.right_censor_count = sum(row["right_censored"] for row in bundle.events)
    return bundle


def source_trigger_validation(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> tuple[dict[str, int], dict[str, int]]:
    expected = build_source_oracle(con, config)
    actual = replay_bundle(con, config)
    checks = compare_source_oracle(expected, actual)
    summary = {
        "expected_atomic_interval_count": len(expected.atomic),
        "expected_component_count": len(expected.components),
        "expected_event_count": len(expected.events),
        "expected_membership_count": len(expected.memberships),
        "expected_transition_count": len(expected.transitions),
        "accepted_reentry_count": expected.accepted_reentry_count,
        "unqualified_reentry_count": expected.unqualified_reentry_count,
        "quality_break_count": expected.quality_break_count,
        "right_censor_count": expected.right_censor_count,
    }
    return checks, summary


__all__ = [
    "OracleBundle",
    "build_source_oracle",
    "compare_source_oracle",
    "replay_bundle",
    "source_trigger_validation",
]
