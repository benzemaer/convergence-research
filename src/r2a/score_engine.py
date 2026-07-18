"""Strict-past W120 score engine used only for the R2A A dimension."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any

PERCENTILE_WINDOW = 120
TIE_METHOD = "midrank"
ENGINE_VERSION = "r2a_t01_a_score_engine.v1"
VALIDITY_ORDER = {"valid": 0, "unknown": 1, "diagnostic_required": 2, "blocked": 3}
DIMENSION_ORDER = ("P", "C", "A", "V", "T")
COMPONENTS_BY_DIMENSION = {
    "P": ("P1_NATR14", "P2_LogRange20"),
    "C": ("C1_LogMASpread_5_60", "C2_AdjVWAPSpread_5_60"),
    "A": (
        "A1_LogBodyCenterToMACloudCenter_5_60",
        "A2_BodyCenterOutsideMACloudRate20_5_60",
    ),
    "V": ("V1_TurnoverShrink20_60", "V2_AmountLevel20Pct"),
    "T": ("T1_ER20", "T2_AbsTrendT20"),
}
A_COMPONENTS = COMPONENTS_BY_DIMENSION["A"]
ALL_COMPONENTS = tuple(
    component
    for dimension in DIMENSION_ORDER
    for component in COMPONENTS_BY_DIMENSION[dimension]
)


class ScoreContractError(ValueError):
    """Raised when an input violates the frozen W120 score contract."""


@dataclass(frozen=True)
class ComponentScore:
    security_id: str
    trading_date: str
    observation_sequence: int
    indicator_id: str
    raw_value: float | None
    percentile_window: int
    reference_observation_count: int
    reference_sequence_start: int | None
    reference_sequence_end: int | None
    eligible: bool
    percentile: float | None
    score: float | None
    validity_status: str
    reason_codes: tuple[str, ...]
    tie_method: str = TIE_METHOD
    current_observation_excluded: bool = True
    score_engine_version: str = ENGINE_VERSION

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


@dataclass(frozen=True)
class DimensionScore:
    security_id: str
    trading_date: str
    observation_sequence: int
    dimension_id: str
    percentile_window: int
    eligible_dimension: bool
    score_dimension: float | None
    score_dimension_min: float | None
    validity_status: str
    reason_codes: tuple[str, ...]
    score_engine_version: str = ENGINE_VERSION

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def compute_component_scores(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    percentile_window: int = PERCENTILE_WINDOW,
    worker_count: int = 1,
) -> tuple[ComponentScore, ...]:
    """Compute A1/A2 scores using exactly 120 strictly prior valid observations."""

    if percentile_window != PERCENTILE_WINDOW:
        raise ScoreContractError("only_w120_allowed")
    if worker_count < 1:
        raise ScoreContractError("worker_count_must_be_positive")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, int]] = set()
    for source in raw_rows:
        row = _normalise_raw_row(source)
        key = (row["security_id"], row["indicator_id"], row["observation_sequence"])
        if key in seen:
            raise ScoreContractError("duplicate_component_observation_key")
        seen.add(key)
        groups[key[:2]].append(row)

    items = sorted(groups.items())
    if worker_count == 1:
        scored = [_score_group(key, rows) for key, rows in items]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            scored = list(
                executor.map(lambda item: _score_group(item[0], item[1]), items)
            )
    return tuple(
        sorted(
            (result for group in scored for result in group),
            key=lambda row: (
                row.security_id,
                row.observation_sequence,
                row.indicator_id,
            ),
        )
    )


def compute_a_dimension_scores(
    component_scores: Sequence[ComponentScore | Mapping[str, Any]],
) -> tuple[DimensionScore, ...]:
    """Compute A mean/min only when both A components are ready."""

    grouped: dict[tuple[str, str, int], dict[str, Mapping[str, Any]]] = defaultdict(
        dict
    )
    for item in component_scores:
        row = item.as_dict() if isinstance(item, ComponentScore) else dict(item)
        indicator_id = str(row.get("indicator_id", ""))
        if indicator_id not in A_COMPONENTS:
            raise ScoreContractError("non_a_component_for_a_dimension")
        key = (
            str(row["security_id"]),
            str(row["trading_date"]),
            int(row["observation_sequence"]),
        )
        if indicator_id in grouped[key]:
            raise ScoreContractError("duplicate_a_component_score")
        grouped[key][indicator_id] = row

    output: list[DimensionScore] = []
    for (security_id, trading_date, sequence), components in sorted(grouped.items()):
        rows = [components.get(component) for component in A_COMPONENTS]
        ready = all(_component_ready(row) for row in rows)
        if ready:
            scores = [float(row["score"]) for row in rows if row is not None]
            output.append(
                DimensionScore(
                    security_id=security_id,
                    trading_date=trading_date,
                    observation_sequence=sequence,
                    dimension_id="A",
                    percentile_window=PERCENTILE_WINDOW,
                    eligible_dimension=True,
                    score_dimension=0.5 * scores[0] + 0.5 * scores[1],
                    score_dimension_min=min(scores),
                    validity_status="valid",
                    reason_codes=("valid_no_blocker",),
                )
            )
            continue

        present_rows = [row for row in rows if row is not None]
        status = _worst_status(
            str(row.get("validity_status", "unknown")) for row in present_rows
        )
        reasons = ["a_components_incomplete"]
        if len(present_rows) != 2:
            reasons.append("missing_a_component_score")
        for row in present_rows:
            reasons.extend(str(code) for code in row.get("reason_codes", ()))
        output.append(
            DimensionScore(
                security_id=security_id,
                trading_date=trading_date,
                observation_sequence=sequence,
                dimension_id="A",
                percentile_window=PERCENTILE_WINDOW,
                eligible_dimension=False,
                score_dimension=None,
                score_dimension_min=None,
                validity_status=status,
                reason_codes=_stable_reasons(reasons),
            )
        )
    return tuple(output)


def _score_group(
    key: tuple[str, str], rows: Sequence[dict[str, Any]]
) -> tuple[ComponentScore, ...]:
    security_id, indicator_id = key
    ordered = sorted(rows, key=lambda row: row["observation_sequence"])
    sequences = [row["observation_sequence"] for row in ordered]
    if sequences and sequences != list(range(sequences[0], sequences[-1] + 1)):
        raise ScoreContractError("component_observation_sequence_gap")

    history: list[tuple[int, float]] = []
    output: list[ComponentScore] = []
    for row in ordered:
        reference = history[-PERCENTILE_WINDOW:]
        status = row["validity_status"]
        raw_value = row["raw_value"]
        if status == "valid" and raw_value is None:
            raise ScoreContractError("valid_raw_value_must_be_finite")

        ready = status == "valid" and len(reference) == PERCENTILE_WINDOW
        if ready:
            values = [value for _, value in reference]
            less = sum(value < raw_value for value in values)
            equal = sum(value == raw_value for value in values)
            percentile = (less + 0.5 * equal) / PERCENTILE_WINDOW
            score = 1.0 - percentile
            reasons = ("valid_no_blocker",)
        else:
            percentile = None
            score = None
            reasons = list(row["reason_codes"])
            if status == "valid":
                reasons.append("insufficient_strict_past_history")
            else:
                reasons.append("current_observation_not_valid")
            reasons = _stable_reasons(reasons)

        output.append(
            ComponentScore(
                security_id=security_id,
                trading_date=row["trading_date"],
                observation_sequence=row["observation_sequence"],
                indicator_id=indicator_id,
                raw_value=raw_value,
                percentile_window=PERCENTILE_WINDOW,
                reference_observation_count=len(reference),
                reference_sequence_start=reference[0][0] if reference else None,
                reference_sequence_end=reference[-1][0] if reference else None,
                eligible=ready,
                percentile=percentile,
                score=score,
                validity_status="valid" if ready else status,
                reason_codes=tuple(reasons),
            )
        )
        if status == "valid" and raw_value is not None:
            history.append((row["observation_sequence"], raw_value))
    return tuple(output)


def _normalise_raw_row(source: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "security_id",
        "trading_date",
        "observation_sequence",
        "indicator_id",
        "validity_status",
    }
    missing = sorted(required - set(source))
    if missing:
        raise ScoreContractError(f"missing_required_fields:{','.join(missing)}")
    indicator_id = str(source["indicator_id"])
    if indicator_id not in A_COMPONENTS:
        raise ScoreContractError("only_a1_a2_allowed")
    status = str(source["validity_status"])
    if status not in VALIDITY_ORDER:
        raise ScoreContractError("invalid_validity_status")
    sequence = int(source["observation_sequence"])
    if sequence < 0:
        raise ScoreContractError("observation_sequence_must_be_non_negative")
    value = source.get("raw_value")
    numeric: float | None
    if value is None:
        numeric = None
    else:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ScoreContractError("raw_value_not_numeric") from exc
        if not math.isfinite(numeric):
            if status == "valid":
                raise ScoreContractError("valid_raw_value_must_be_finite")
            numeric = None
    return {
        "security_id": str(source["security_id"]),
        "trading_date": str(source["trading_date"]),
        "observation_sequence": sequence,
        "indicator_id": indicator_id,
        "raw_value": numeric,
        "validity_status": status,
        "reason_codes": _stable_reasons(source.get("reason_codes", (status,))),
    }


def _component_ready(row: Mapping[str, Any] | None) -> bool:
    if row is None or row.get("validity_status") != "valid" or not row.get("eligible"):
        return False
    score = row.get("score")
    try:
        return score is not None and math.isfinite(float(score))
    except (TypeError, ValueError):
        return False


def _worst_status(statuses: Sequence[str] | Any) -> str:
    values = list(statuses)
    if not values:
        return "unknown"
    return max(values, key=lambda value: VALIDITY_ORDER.get(value, 1))


def _stable_reasons(values: Sequence[Any]) -> tuple[str, ...]:
    reasons = sorted({str(value) for value in values if str(value)})
    return tuple(reasons or ["unspecified_non_ready"])
