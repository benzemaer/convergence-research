from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

SHANGHAI_OFFSET = timezone(timedelta(hours=8))
EOD_CUTOFF = time(15, 0, 0)
TERMINATION_REASON_MAP = {
    "raw_state_false": "natural_state_exit",
    "end_of_input_open": "sample_end_censoring",
    "raw_state_blocked": "quality_interruption",
    "raw_state_diagnostic_required": "quality_interruption",
    "raw_state_unknown": "quality_interruption",
}


class R2T03AdapterError(RuntimeError):
    pass


def eod_available_time(trade_date: str | date) -> str:
    value = (
        trade_date
        if isinstance(trade_date, date)
        else datetime.strptime(str(trade_date).replace("-", ""), "%Y%m%d").date()
    )
    return datetime.combine(value, EOD_CUTOFF, SHANGHAI_OFFSET).isoformat()


def build_base_expected_keys(
    universe: Iterable[str],
    calendar_rows: Iterable[Mapping[str, Any]],
    lifecycle_rows: Iterable[Mapping[str, Any]],
    *,
    date_min: str,
    date_max: str,
) -> list[tuple[str, str]]:
    securities = list(universe)
    if len(securities) != len(set(securities)):
        raise R2T03AdapterError("duplicate_security_universe_key")
    lifecycle: dict[str, tuple[str, str]] = {}
    for row in lifecycle_rows:
        security = str(row["security_id"])
        if security in lifecycle:
            raise R2T03AdapterError("duplicate_stock_lifecycle_key")
        lifecycle[security] = (str(row["list_date"]), str(row.get("delist_date") or ""))
    if set(securities) - set(lifecycle):
        raise R2T03AdapterError("missing_source_mapping")
    open_dates = sorted(
        {
            str(row["trade_date"])
            for row in calendar_rows
            if str(row["is_open"]) in {"1", "True", "true"}
            and date_min <= str(row["trade_date"]) <= date_max
        }
    )
    output = []
    for security in sorted(securities):
        listed, delisted = lifecycle[security]
        output.extend(
            (security, trading_date)
            for trading_date in open_dates
            if trading_date >= listed and (not delisted or trading_date <= delisted)
        )
    if len(output) != len(set(output)):
        raise R2T03AdapterError("duplicate_expected_security_date")
    return output


def expand_expected_route_keys(
    base_keys: Iterable[tuple[str, str]], route_ids: Iterable[str]
) -> list[tuple[str, str, str]]:
    routes = list(route_ids)
    if len(routes) != 8 or len(set(routes)) != 8:
        raise R2T03AdapterError("route_registry_not_exactly_8")
    base = list(base_keys)
    if len(base) != len(set(base)):
        raise R2T03AdapterError("duplicate_expected_security_date")
    return [
        (route, security, trading_date)
        for route in sorted(routes)
        for security, trading_date in base
    ]


def assert_expected_completeness(
    expected: Iterable[tuple[str, str, str]], observed: Iterable[tuple[str, str, str]]
) -> None:
    expected_rows, observed_rows = list(expected), list(observed)
    if len(expected_rows) != len(set(expected_rows)):
        raise R2T03AdapterError("duplicate_expected_route_key")
    expected_set, observed_set = set(expected_rows), set(observed_rows)
    if observed_set - expected_set:
        raise R2T03AdapterError("observed_row_outside_expected_keys")
    if expected_set - observed_set:
        raise R2T03AdapterError("expected_row_absent_from_observed")


def normalize_termination_reason(source_reason: str) -> str:
    if source_reason is None or not str(source_reason).strip():
        raise R2T03AdapterError("empty_source_termination_reason")
    try:
        return TERMINATION_REASON_MAP[str(source_reason)]
    except KeyError as exc:
        raise R2T03AdapterError(
            f"unregistered_source_termination_reason:{source_reason}"
        ) from exc


def derive_source_termination_reason(decision_row: Mapping[str, Any] | None) -> str:
    """Disambiguate R0's legacy raw_state_false_or_invalid using its daily surface."""
    if decision_row is None:
        return "end_of_input_open"
    quality = str(
        decision_row.get("quality_state")
        or decision_row.get("validity_status")
        or "unknown"
    )
    if quality == "blocked":
        return "raw_state_blocked"
    if quality == "diagnostic_required":
        return "raw_state_diagnostic_required"
    if quality != "valid" or decision_row.get("raw_state") is None:
        return "raw_state_unknown"
    if decision_row.get("raw_state") is False:
        return "raw_state_false"
    raise R2T03AdapterError("interval_terminal_decision_not_an_exit")


def normalize_interval_row(row: Mapping[str, Any]) -> dict[str, Any]:
    source_reason = str(row.get("source_termination_reason") or "")
    reason = normalize_termination_reason(source_reason)
    is_open = bool(row["is_open_interval"])
    if is_open != (source_reason == "end_of_input_open"):
        raise R2T03AdapterError("source_open_flag_reason_mismatch")
    start = str(row.get("confirmed_start_date") or row.get("confirmation_date") or "")
    end = str(
        row.get("last_observed_date") if is_open else row.get("interval_end_date") or ""
    )
    duration = int(row["confirmed_duration_observations"])
    if not start or not end or end < start or duration < 1:
        raise R2T03AdapterError("invalid_normalized_interval_geometry")
    return {
        "route_id": str(row["route_id"]),
        "security_id": str(row["security_id"]),
        "source_interval_id": str(row["source_interval_id"]),
        "start_date": start,
        "end_date": end,
        "confirmed_day_count": duration,
        "termination_reason": reason,
        "source_termination_reason": source_reason,
        "is_open_interval": is_open,
        "source_kind": str(row["source_kind"]),
        "source_artifact_sha256": str(row["source_artifact_sha256"]),
    }


def reconcile_interval_multiset(
    rebuilt: Iterable[Mapping[str, Any]], upstream: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    fields = (
        "route_id",
        "security_id",
        "source_interval_id",
        "start_date",
        "end_date",
        "confirmed_day_count",
        "termination_reason",
    )

    def rows(values: Iterable[Mapping[str, Any]]) -> Counter[tuple[Any, ...]]:
        result: Counter[tuple[Any, ...]] = Counter()
        for value in values:
            missing = [field for field in fields if field not in value]
            if missing:
                raise R2T03AdapterError(
                    f"interval_reconciliation_missing_field:{missing[0]}"
                )
            result[tuple(value[field] for field in fields)] += 1
        return result

    left, right = rows(rebuilt), rows(upstream)
    missing, unexpected = right - left, left - right
    pk = fields[:3]
    left_pk = Counter(key[: len(pk)] for key in left.elements())
    right_pk = Counter(key[: len(pk)] for key in right.elements())
    return {
        "status": "passed" if not missing and not unexpected else "failed",
        "rebuilt_row_count": sum(left.values()),
        "upstream_row_count": sum(right.values()),
        "rebuilt_duplicate_primary_key_count": sum(
            n - 1 for n in left_pk.values() if n > 1
        ),
        "upstream_duplicate_primary_key_count": sum(
            n - 1 for n in right_pk.values() if n > 1
        ),
        "missing_multiset_row_count": sum(missing.values()),
        "unexpected_multiset_row_count": sum(unexpected.values()),
        "field_mismatch_row_count": sum(missing.values()) + sum(unexpected.values()),
    }
