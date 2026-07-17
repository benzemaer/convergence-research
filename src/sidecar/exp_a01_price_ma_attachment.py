"""Pure in-memory raw metrics for the EXP-A01 sidecar exploration.

The implementation consumes a dense, independently authorized expected-
observation sequence merged with the D3-T07 research-candidate observation
table.  It never compresses missing or non-trading slots and never performs a
formal DuckDB run.  Only the three pre-registered raw metrics are calculated.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

TASK_ID = "EXP-A01"
METRIC_ENGINE_VERSION = "exp_a01_price_ma_attachment.v1"
MA_WINDOWS = (5, 10, 20, 30, 60)
A2_ROLLING_WINDOW = 20
A1_REQUIRED_OBSERVATIONS = 60
A2_REQUIRED_OBSERVATIONS = 79
FLOAT64_EPSILON = 2.220446049250313e-16
BOUNDARY_ULPS = 8

A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
INDICATOR_IDS = (A1_ID, A2_ID, A2B_ID)

RAW_METRIC_NAMES = {
    A1_ID: "LogBodyCenterToMACloudCenter_5_60",
    A2_ID: "BodyCenterOutsideMACloudRate20_5_60",
    A2B_ID: "BodyToMACloudGapMean20_5_60",
}
REQUIRED_OBSERVATIONS = {
    A1_ID: A1_REQUIRED_OBSERVATIONS,
    A2_ID: A2_REQUIRED_OBSERVATIONS,
    A2B_ID: A2_REQUIRED_OBSERVATIONS,
}
VALIDITY_STATUSES = ("valid", "unknown", "blocked", "diagnostic_required")
EXPECTED_OBSERVATION_STATUSES = ("present", "listing_pause", "missing", "unresolved")
INDEX_SOURCE_CONTRACT = "EXP_A01_EXPECTED_PRICE_OBSERVATION_INDEX_V1"
REASON_CODES = (
    "valid_no_blocker",
    "window_insufficient",
    "missing_adjusted_open",
    "missing_adjusted_close",
    "missing_required_history",
    "nonpositive_adjusted_open",
    "nonpositive_adjusted_close",
    "nonpositive_MA",
    "adjustment_failure",
    "suspension_in_required_window",
    "listing_pause_in_required_window",
    "invalid_trading_status",
    "reopen_after_suspension",
)
OUTPUT_FIELDS = (
    "security_id",
    "trading_date",
    "indicator_id",
    "raw_metric_name",
    "raw_value",
    "validity_status",
    "reason_codes",
    "input_window_start",
    "input_window_end",
    "required_observation_count",
    "actual_valid_observation_count",
    "metric_engine_version",
)

# These are the controlled values used by the committed D3 quality-readiness
# and D3-T07 contracts.  A01 must not invent a second status vocabulary.
_VALID_TRADING_STATUSES = {
    "listed_open_resolved_daily",
    "normal_trading",
    "limit_up",
    "limit_down",
    "one_price_limit_up",
    "one_price_limit_down",
}
_VALID_DAILY_STATUSES = {"resolved"}
_SUSPENSION_STATUSES = {"suspended"}
_VALID_ADJUSTMENT_STATUSES = {
    "resolved",
    "not_applicable_or_carry_forward",
    "neutral_factor_1_policy",
    "factor_interval_policy",
}
_SEVERE_REASONS = {
    "adjustment_failure",
    "invalid_trading_status",
    "nonpositive_adjusted_open",
    "nonpositive_adjusted_close",
    "nonpositive_MA",
    "suspension_in_required_window",
    "listing_pause_in_required_window",
}


class InputContractError(ValueError):
    """Raised when an input violates the EXP-A01 dense-row contract."""


@dataclass(frozen=True)
class _PriceRow:
    security_id: str
    trading_date: str
    observation_sequence: int
    expected_observation_status: str
    adjusted_open: float | None
    adjusted_close: float | None
    trading_status: str | None
    daily_status: str | None
    effective_adj_factor: float | None
    adjustment_factor_status: str | None
    row_provenance: str
    source_contract: str
    source_ref: str
    row_reasons: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return self.security_id, self.trading_date

    @property
    def sequence_key(self) -> tuple[str, int]:
        return self.security_id, self.observation_sequence

    @property
    def is_valid(self) -> bool:
        return not self.row_reasons


def build_dense_price_rows(
    expected_index_rows: Iterable[Mapping[str, Any]],
    observation_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge an authorized expected index with D3-T07 rows without compression.

    The expected index owns the sequence.  A ``present`` slot must have exactly
    one D3-T07 row; every non-present slot becomes an explicit placeholder with
    no price values.  Reconciliation failures are input-contract failures,
    rather than metric invalidity that can be silently carried forward.
    """

    expected = _normalize_expected_index_rows(expected_index_rows)
    expected_by_key = {
        (row["security_id"], row["trading_date"]): row for row in expected
    }
    observed_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    previous_observed_by_security: dict[str, tuple[int, str]] = {}
    for row_like in observation_rows:
        if not isinstance(row_like, Mapping):
            raise InputContractError("each D3-T07 observation row must be a mapping")
        security_id = _required_text(
            _first_present(row_like, "security_id", "ts_code"), "security_id"
        )
        trading_date = _canonical_date_text(
            _first_present(row_like, "trading_date", "trade_date")
        )
        key = security_id, trading_date
        if key in observed_by_key:
            raise InputContractError(f"duplicate_security_date: {key}")
        expected_row = expected_by_key.get(key)
        if expected_row is None:
            raise InputContractError(f"main_row_missing_expected_index: {key}")
        if expected_row["expected_observation_status"] != "present":
            raise InputContractError(f"non_present_expected_row_in_main: {key}")
        previous_observed = previous_observed_by_security.get(security_id)
        if previous_observed is not None:
            previous_sequence, previous_date = previous_observed
            if expected_row["observation_sequence"] < previous_sequence:
                raise InputContractError(f"non_monotonic_input_sequence: {security_id}")
            if trading_date < previous_date:
                raise InputContractError(f"non_monotonic_trading_date: {security_id}")
        previous_observed_by_security[security_id] = (
            expected_row["observation_sequence"],
            trading_date,
        )
        if _truthy(row_like.get("is_listing_pause")):
            raise InputContractError(f"listing_pause_row_present_in_main: {key}")
        if "observation_sequence" in row_like:
            sequence = _required_sequence(row_like["observation_sequence"])
            if sequence != expected_row["observation_sequence"]:
                raise InputContractError(f"observation_sequence_mismatch: {key}")
        observed_by_key[key] = dict(row_like)

    dense: list[dict[str, Any]] = []
    for expected_row in expected:
        key = expected_row["security_id"], expected_row["trading_date"]
        status = expected_row["expected_observation_status"]
        observed = observed_by_key.get(key)
        if status == "present":
            if observed is None:
                raise InputContractError(
                    f"expected_present_row_missing_from_main: {key}"
                )
            normalized = dict(observed)
            normalized.update(
                {
                    "security_id": key[0],
                    "trading_date": key[1],
                    "observation_sequence": expected_row["observation_sequence"],
                    "expected_observation_status": status,
                    "source_contract": expected_row["source_contract"],
                    "source_ref": expected_row["source_ref"],
                }
            )
        else:
            if observed is not None:
                raise InputContractError(f"non_present_expected_row_in_main: {key}")
            placeholder_status = {
                "listing_pause": "listing_pause",
                "missing": "missing",
                "unresolved": "unresolved",
            }[status]
            normalized = {
                "security_id": key[0],
                "trading_date": key[1],
                "observation_sequence": expected_row["observation_sequence"],
                "expected_observation_status": status,
                "adjusted_open": None,
                "adjusted_close": None,
                "trading_status": placeholder_status,
                "daily_status": placeholder_status,
                "effective_adj_factor": None,
                "adjustment_factor_status": None,
                "is_listing_pause": status == "listing_pause",
                "row_provenance": expected_row["source_ref"],
                "source_contract": expected_row["source_contract"],
                "source_ref": expected_row["source_ref"],
            }
        dense.append(normalized)
    return dense


def compute_a01_metrics(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compute the three A01 raw metrics in deterministic security order."""

    normalized = normalize_price_rows(rows)
    grouped: dict[str, list[_PriceRow]] = defaultdict(list)
    for row in normalized:
        grouped[row.security_id].append(row)

    output: list[dict[str, Any]] = []
    for security_id in sorted(grouped):
        security_rows = grouped[security_id]
        for index, current in enumerate(security_rows):
            output.extend(_compute_for_index(security_rows, index, current))
    return output


def build_raw_metric_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Explicit alias used by future sidecar orchestration code."""

    return compute_a01_metrics(rows)


def compute_metrics(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility alias for callers that use the shorter metric name."""

    return compute_a01_metrics(rows)


def normalize_price_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[_PriceRow, ...]:
    """Normalize already-dense rows and fail closed on stream structure errors."""

    normalized: list[_PriceRow] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_sequences: set[tuple[str, int]] = set()
    previous_by_security: dict[str, tuple[int, str]] = {}

    for row_like in rows:
        if not isinstance(row_like, Mapping):
            raise InputContractError("each input row must be a mapping")
        security_id = _required_text(
            _first_present(row_like, "security_id", "ts_code"), "security_id"
        )
        trading_date = _canonical_date_text(
            _first_present(row_like, "trading_date", "trade_date")
        )
        sequence = _required_sequence(row_like.get("observation_sequence"))
        expected_status = _required_text(
            row_like.get("expected_observation_status"),
            "expected_observation_status",
        ).lower()
        if expected_status not in EXPECTED_OBSERVATION_STATUSES:
            raise InputContractError(
                f"invalid expected_observation_status: {expected_status}"
            )
        source_contract = _required_text(
            row_like.get("source_contract"), "source_contract"
        )
        source_ref = _required_text(row_like.get("source_ref"), "source_ref")
        if source_contract != INDEX_SOURCE_CONTRACT:
            raise InputContractError(
                f"unexpected expected-index source_contract: {source_contract}"
            )
        row_provenance = _required_text(
            row_like.get("row_provenance"), "row_provenance"
        )
        key = security_id, trading_date
        sequence_key = security_id, sequence
        if key in seen_keys:
            raise InputContractError(f"duplicate_security_date: {key}")
        if sequence_key in seen_sequences:
            raise InputContractError(f"duplicate_security_sequence: {sequence_key}")
        seen_keys.add(key)
        seen_sequences.add(sequence_key)

        previous = previous_by_security.get(security_id)
        if previous is not None:
            previous_sequence, previous_date = previous
            if sequence < previous_sequence:
                raise InputContractError(f"non_monotonic_input_sequence: {security_id}")
            if trading_date < previous_date:
                raise InputContractError(f"non_monotonic_trading_date: {security_id}")
            if sequence != previous_sequence + 1:
                raise InputContractError(f"sequence_gap: {security_id}")
            if trading_date == previous_date:
                raise InputContractError(f"duplicate_security_date: {key}")
        previous_by_security[security_id] = sequence, trading_date

        adjusted_open = _optional_float(row_like.get("adjusted_open"))
        adjusted_close = _optional_float(row_like.get("adjusted_close"))
        if expected_status != "present" and (
            adjusted_open is not None or adjusted_close is not None
        ):
            raise InputContractError(f"non_present_slot_has_price: {key}")
        reasons = _row_reason_codes(
            row_like,
            expected_observation_status=expected_status,
            adjusted_open=adjusted_open,
            adjusted_close=adjusted_close,
        )
        normalized.append(
            _PriceRow(
                security_id=security_id,
                trading_date=trading_date,
                observation_sequence=sequence,
                expected_observation_status=expected_status,
                adjusted_open=adjusted_open,
                adjusted_close=adjusted_close,
                trading_status=_optional_text(row_like.get("trading_status")),
                daily_status=_optional_text(row_like.get("daily_status")),
                effective_adj_factor=_optional_float(
                    row_like.get("effective_adj_factor")
                ),
                adjustment_factor_status=_optional_text(
                    row_like.get("adjustment_factor_status")
                ),
                row_provenance=row_provenance,
                source_contract=source_contract,
                source_ref=source_ref,
                row_reasons=tuple(reasons),
            )
        )
    return tuple(normalized)


def _normalize_expected_index_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_sequences: set[tuple[str, int]] = set()
    previous_by_security: dict[str, tuple[int, str]] = {}
    for row_like in rows:
        if not isinstance(row_like, Mapping):
            raise InputContractError("each expected index row must be a mapping")
        security_id = _required_text(row_like.get("security_id"), "security_id")
        trading_date = _canonical_date_text(row_like.get("trading_date"))
        sequence = _required_sequence(row_like.get("observation_sequence"))
        status = _required_text(
            row_like.get("expected_observation_status"),
            "expected_observation_status",
        ).lower()
        if status not in EXPECTED_OBSERVATION_STATUSES:
            raise InputContractError(f"invalid expected_observation_status: {status}")
        source_contract = _required_text(
            row_like.get("source_contract"), "source_contract"
        )
        source_ref = _required_text(row_like.get("source_ref"), "source_ref")
        if source_contract != INDEX_SOURCE_CONTRACT:
            raise InputContractError(
                f"unexpected expected-index source_contract: {source_contract}"
            )
        key = security_id, trading_date
        sequence_key = security_id, sequence
        if key in seen_keys:
            raise InputContractError(f"duplicate_security_date: {key}")
        if sequence_key in seen_sequences:
            raise InputContractError(f"duplicate_security_sequence: {sequence_key}")
        previous = previous_by_security.get(security_id)
        if previous is not None:
            previous_sequence, previous_date = previous
            if sequence < previous_sequence:
                raise InputContractError(f"non_monotonic_input_sequence: {security_id}")
            if trading_date < previous_date:
                raise InputContractError(f"non_monotonic_trading_date: {security_id}")
            if sequence != previous_sequence + 1:
                raise InputContractError(f"sequence_gap: {security_id}")
            if trading_date == previous_date:
                raise InputContractError(f"duplicate_security_date: {key}")
        seen_keys.add(key)
        seen_sequences.add(sequence_key)
        previous_by_security[security_id] = sequence, trading_date
        normalized.append(
            {
                "security_id": security_id,
                "trading_date": trading_date,
                "observation_sequence": sequence,
                "expected_observation_status": status,
                "source_contract": source_contract,
                "source_ref": source_ref,
            }
        )
    return normalized


def _compute_for_index(
    rows: list[_PriceRow],
    index: int,
    current: _PriceRow,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for indicator_id in INDICATOR_IDS:
        required = REQUIRED_OBSERVATIONS[indicator_id]
        start = max(0, index - required + 1)
        window = rows[start : index + 1]
        reasons: list[str] = []
        if len(window) != required:
            reasons.extend(("window_insufficient", "missing_required_history"))
        if (
            len(window) == required
            and window[-1].observation_sequence - window[0].observation_sequence
            != required - 1
        ):
            raise InputContractError("sequence_gap: dense metric window")
        for row in window:
            reasons.extend(row.row_reasons)

        raw_value: float | None = None
        if not reasons:
            try:
                if indicator_id == A1_ID:
                    body, _cloud_low, _cloud_high, cloud_center = _cloud_point(
                        rows, index
                    )
                    raw_value = abs(body - cloud_center)
                else:
                    points = [
                        _cloud_point(rows, point_index)
                        for point_index in range(
                            index - A2_ROLLING_WINDOW + 1, index + 1
                        )
                    ]
                    if indicator_id == A2_ID:
                        outside_values = [
                            1.0 if _is_outside(body, cloud_low, cloud_high) else 0.0
                            for body, cloud_low, cloud_high, _center in points
                        ]
                        raw_value = sum(outside_values) / len(outside_values)
                    else:
                        gaps = [
                            _body_cloud_gap(
                                body, cloud_low, cloud_high, rows, point_index
                            )
                            for point_index, (
                                body,
                                cloud_low,
                                cloud_high,
                                _center,
                            ) in zip(
                                range(
                                    index - A2_ROLLING_WINDOW + 1,
                                    index + 1,
                                ),
                                points,
                                strict=True,
                            )
                        ]
                        raw_value = sum(gaps) / len(gaps)
            except (ArithmeticError, ValueError):
                reasons.append("nonpositive_MA")

        reasons = _ordered_reasons(reasons)
        if reasons or raw_value is None or not math.isfinite(raw_value):
            if not reasons:
                reasons = ["nonpositive_MA"]
            raw_value = None
            status = _status_for_reasons(reasons)
        else:
            if raw_value < 0.0:
                raw_value = None
                reasons = ["nonpositive_MA"]
                status = "blocked"
            elif indicator_id == A2_ID and not 0.0 <= raw_value <= 1.0:
                raw_value = None
                reasons = ["nonpositive_MA"]
                status = "blocked"
            else:
                status = "valid"
                reasons = ["valid_no_blocker"]

        results.append(
            _result_row(
                current=current,
                indicator_id=indicator_id,
                raw_value=raw_value,
                validity_status=status,
                reason_codes=reasons,
                input_window_start=window[0].trading_date if window else None,
                input_window_end=current.trading_date,
                required_observation_count=required,
                actual_valid_observation_count=sum(row.is_valid for row in window),
            )
        )
    return results


def _cloud_point(
    rows: list[_PriceRow], index: int
) -> tuple[float, float, float, float]:
    current = rows[index]
    if not current.is_valid:
        raise ValueError("invalid current observation")
    if current.adjusted_open is None or current.adjusted_close is None:
        raise ValueError("missing current adjusted price")
    body = (math.log(current.adjusted_open) + math.log(current.adjusted_close)) / 2.0
    log_mas = []
    for window_size in MA_WINDOWS:
        window = rows[index - window_size + 1 : index + 1]
        if len(window) != window_size or any(not row.is_valid for row in window):
            raise ValueError("invalid moving-average window")
        closes = [row.adjusted_close for row in window]
        if any(value is None or value <= 0.0 for value in closes):
            raise ValueError("nonpositive moving-average input")
        moving_average = sum(closes) / window_size
        if not math.isfinite(moving_average) or moving_average <= 0.0:
            raise ValueError("nonpositive moving average")
        log_mas.append(math.log(moving_average))
    return body, min(log_mas), max(log_mas), sum(log_mas) / len(log_mas)


def _is_outside(body: float, cloud_low: float, cloud_high: float) -> bool:
    """Use a shared narrow equality zone around both cloud boundaries."""

    low_tolerance = boundary_tolerance(body, cloud_low)
    high_tolerance = boundary_tolerance(body, cloud_high)
    return body < cloud_low - low_tolerance or body > cloud_high + high_tolerance


def boundary_tolerance(left: float, right: float) -> float:
    """Return the fixed scale-aware eight-ULP boundary allowance."""

    return BOUNDARY_ULPS * FLOAT64_EPSILON * max(1.0, abs(left), abs(right))


def _body_cloud_gap(
    body: float,
    cloud_low: float,
    cloud_high: float,
    rows: list[_PriceRow],
    index: int,
) -> float:
    del body
    current = rows[index]
    if current.adjusted_open is None or current.adjusted_close is None:
        raise ValueError("missing body endpoint")
    body_low = min(math.log(current.adjusted_open), math.log(current.adjusted_close))
    body_high = max(math.log(current.adjusted_open), math.log(current.adjusted_close))
    low_tolerance = boundary_tolerance(body_high, cloud_low)
    high_tolerance = boundary_tolerance(body_low, cloud_high)
    if body_high < cloud_low - low_tolerance:
        return cloud_low - body_high
    if body_low > cloud_high + high_tolerance:
        return body_low - cloud_high
    return 0.0


def _row_reason_codes(
    row: Mapping[str, Any],
    *,
    expected_observation_status: str,
    adjusted_open: float | None,
    adjusted_close: float | None,
) -> list[str]:
    reasons: list[str] = []
    if expected_observation_status == "listing_pause":
        reasons.append("listing_pause_in_required_window")
    elif expected_observation_status in {"missing", "unresolved"}:
        reasons.append(
            "missing_required_history"
            if expected_observation_status == "missing"
            else "adjustment_failure"
        )

    if adjusted_open is None:
        reasons.append("missing_adjusted_open")
    elif adjusted_open <= 0.0:
        reasons.append("nonpositive_adjusted_open")
    if adjusted_close is None:
        reasons.append("missing_adjusted_close")
    elif adjusted_close <= 0.0:
        reasons.append("nonpositive_adjusted_close")

    status_value = row.get("trading_status")
    status = str(status_value).strip().lower() if status_value is not None else ""
    if status == "reopen_after_suspension":
        reasons.append("reopen_after_suspension")
    elif status in _SUSPENSION_STATUSES:
        reasons.append("suspension_in_required_window")
    elif status not in _VALID_TRADING_STATUSES:
        reasons.append("invalid_trading_status")

    daily_status = _optional_text(row.get("daily_status"))
    if daily_status is None or daily_status.lower() not in _VALID_DAILY_STATUSES:
        reasons.append("missing_required_history")

    if not _explicit_false(row.get("is_listing_pause")):
        reasons.append("listing_pause_in_required_window")

    adjustment_status = _optional_text(row.get("adjustment_factor_status"))
    factor = _optional_float(row.get("effective_adj_factor"))
    if (
        adjustment_status is None
        or adjustment_status.lower() not in _VALID_ADJUSTMENT_STATUSES
    ):
        reasons.append("adjustment_failure")
    if factor is None or factor <= 0.0:
        reasons.append("adjustment_failure")
    return _ordered_reasons(reasons)


def _result_row(
    *,
    current: _PriceRow,
    indicator_id: str,
    raw_value: float | None,
    validity_status: str,
    reason_codes: list[str],
    input_window_start: str | None,
    input_window_end: str,
    required_observation_count: int,
    actual_valid_observation_count: int,
) -> dict[str, Any]:
    if validity_status not in VALIDITY_STATUSES:
        raise AssertionError(f"invalid status: {validity_status}")
    if validity_status != "valid" and raw_value is not None:
        raise AssertionError("invalid result cannot carry a raw value")
    return {
        "security_id": current.security_id,
        "trading_date": current.trading_date,
        "indicator_id": indicator_id,
        "raw_metric_name": RAW_METRIC_NAMES[indicator_id],
        "raw_value": raw_value,
        "validity_status": validity_status,
        "reason_codes": list(reason_codes),
        "input_window_start": input_window_start,
        "input_window_end": input_window_end,
        "required_observation_count": required_observation_count,
        "actual_valid_observation_count": actual_valid_observation_count,
        "metric_engine_version": METRIC_ENGINE_VERSION,
    }


def _status_for_reasons(reasons: list[str]) -> str:
    if any(reason in _SEVERE_REASONS for reason in reasons):
        return "blocked"
    if "reopen_after_suspension" in reasons:
        return "diagnostic_required"
    return "unknown"


def _ordered_reasons(reasons: Iterable[str]) -> list[str]:
    unique = {str(reason) for reason in reasons if str(reason)}
    order = {reason: index for index, reason in enumerate(REASON_CODES)}
    return sorted(unique, key=lambda reason: (order.get(reason, len(order)), reason))


def _first_present(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _required_text(value: Any, field_name: str) -> str:
    if value is None or not str(value).strip():
        raise InputContractError(f"missing {field_name}")
    return str(value).strip()


def _optional_text(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _required_sequence(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise InputContractError("invalid observation_sequence")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        result = int(value.strip())
    else:
        raise InputContractError("invalid observation_sequence")
    if result < 0:
        raise InputContractError("invalid observation_sequence")
    return result


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _canonical_date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise InputContractError(f"invalid trading_date type: {type(value).__name__}")
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise InputContractError(f"invalid trading_date: {value!r}")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _explicit_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in {"0", "false", "no", "n"}
    return False
