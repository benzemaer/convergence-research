"""Pure in-memory implementation for EXP-C01.

The module intentionally consumes only strict-past indicator score rows.  It does
not calculate raw metrics, percentiles, future labels, or trading outcomes.
DuckDB access belongs to the thin runner and is read-only.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

TASK_ID = "EXP-C01"
W = 120
Q = 0.20
WEAK_DELTA = 0.10
SCORE_THRESHOLD = 0.80
BASELINE_MIN_THRESHOLD = 0.70
FLOAT_EPSILON = 1e-12

C1_ID = "C1_LogMASpread_5_60"
C2_ID = "C2_AdjVWAPSpread_5_60"
INDICATOR_IDS = (C1_ID, C2_ID)
BASELINE_VARIANT = "baseline_pair"
C1_VARIANT = "c1_only"
C2_VARIANT = "c2_only"
VARIANT_IDS = (BASELINE_VARIANT, C1_VARIANT, C2_VARIANT)
CANDIDATE_VARIANTS = (C1_VARIANT, C2_VARIANT)
VALIDITY_STATUSES = ("valid", "unknown", "blocked", "diagnostic_required")

OUTPUT_FILES = {
    "variant_profile": "exp_c01_variant_profile.csv",
    "overlap_profile": "exp_c01_overlap_profile.csv",
    "score_comparison": "exp_c01_score_comparison.csv",
    "year_profile": "exp_c01_year_profile.csv",
    "security_profile": "exp_c01_security_profile.csv",
    "availability_profile": "exp_c01_availability_profile.csv",
    "manifest": "exp_c01_manifest.json",
    "validator_result": "exp_c01_validator_result.json",
    "anomaly_scan": "exp_c01_anomaly_scan.json",
    "result_analysis": "exp_c01_result_analysis.md",
}

CSV_FIELDS = {
    "variant_profile": (
        "variant_id",
        "W",
        "q",
        "weak_delta",
        "denominator_scope",
        "eligible_row_count",
        "active_true_count",
        "active_false_count",
        "active_rate",
        "transition_count",
        "transition_rate_per_100_valid_steps",
        "valid_step_count",
        "valid_block_count",
        "true_to_false_transition_count",
        "false_to_true_transition_count",
        "segment_count",
        "segment_start_count",
        "segment_duration_sum",
        "mean_segment_duration",
        "median_segment_duration",
        "q90_segment_duration",
        "max_segment_duration",
        "singleton_segment_count",
        "singleton_segment_ratio",
        "unique_security_count",
        "nonzero_year_count",
        "max_year_active_share",
    ),
    "overlap_profile": (
        "left_variant",
        "right_variant",
        "W",
        "q",
        "weak_delta",
        "denominator_scope",
        "common_valid_rows",
        "n11",
        "n10",
        "n01",
        "n00",
        "left_true_count",
        "right_true_count",
        "jaccard",
        "left_given_right",
        "right_given_left",
        "baseline_retention",
        "candidate_precision",
        "symmetric_difference_count",
        "symmetric_difference_rate",
    ),
    "score_comparison": (
        "comparison_id",
        "W",
        "q",
        "common_valid_rows",
        "pooled_spearman",
        "per_security_spearman_median",
        "per_security_spearman_q25",
        "per_security_spearman_q75",
        "mean_absolute_score_difference",
        "median_absolute_score_difference",
        "q90_absolute_score_difference",
        "q95_absolute_score_difference",
    ),
    "year_profile": (
        "calendar_year",
        "candidate_variant",
        "baseline_variant",
        "W",
        "q",
        "common_valid_rows",
        "baseline_true_count",
        "candidate_true_count",
        "active_rate",
        "baseline_active_rate",
        "candidate_active_rate",
        "jaccard",
        "baseline_retention",
        "candidate_precision",
        "symmetric_difference_rate",
    ),
    "security_profile": (
        "security_id",
        "candidate_variant",
        "baseline_variant",
        "W",
        "q",
        "valid_row_count",
        "baseline_true_count",
        "candidate_true_count",
        "jaccard",
        "baseline_retention",
        "candidate_precision",
    ),
    "availability_profile": (
        "indicator_id",
        "W",
        "q",
        "availability_scope",
        "input_row_count",
        "native_valid_count",
        "native_invalid_count",
        "pair_common_valid_count",
        "availability_gain_vs_pair",
    ),
}


class InputContractError(ValueError):
    """Raised when an input row violates the frozen EXP-C01 contract."""


@dataclass(frozen=True)
class IndicatorRow:
    security_id: str
    trading_date: str
    indicator_id: str
    score: float | None
    eligible: bool
    validity_status: str

    @property
    def key(self) -> tuple[str, str]:
        return self.security_id, self.trading_date


@dataclass(frozen=True)
class Observation:
    security_id: str
    trading_date: str
    c1: IndicatorRow | None
    c2: IndicatorRow | None
    pair_common_valid: bool
    score_mean: float | None
    score_min: float | None
    baseline_active: bool | None
    c1_active: bool | None
    c2_active: bool | None

    @property
    def key(self) -> tuple[str, str]:
        return self.security_id, self.trading_date

    @property
    def calendar_year(self) -> int:
        return int(self.trading_date[:4])

    def active_for(self, variant_id: str) -> bool | None:
        if variant_id == BASELINE_VARIANT:
            return self.baseline_active
        if variant_id == C1_VARIANT:
            return self.c1_active
        if variant_id == C2_VARIANT:
            return self.c2_active
        raise ValueError(f"unknown variant: {variant_id}")


def normalize_indicator_rows(
    rows: Iterable[Mapping[str, Any] | IndicatorRow],
    *,
    percentile_window: int = W,
) -> tuple[IndicatorRow, ...]:
    """Normalize and fail closed on malformed or out-of-scope score rows."""

    normalized: list[IndicatorRow] = []
    seen: set[tuple[str, str, str]] = set()
    for row_like in rows:
        if isinstance(row_like, IndicatorRow):
            row = row_like
            if percentile_window != W:
                raise InputContractError("only W=120 is supported")
        else:
            row = _normalise_indicator_mapping(row_like, percentile_window)
        if row.indicator_id not in INDICATOR_IDS:
            raise InputContractError(
                f"indicator outside C1/C2 scope: {row.indicator_id}"
            )
        key = (*row.key, row.indicator_id)
        if key in seen:
            raise InputContractError(f"duplicate indicator key: {key}")
        seen.add(key)
        normalized.append(row)
    return tuple(sorted(normalized, key=_indicator_sort_key))


def build_observations(
    rows: Iterable[Mapping[str, Any] | IndicatorRow],
    *,
    percentile_window: int = W,
) -> tuple[Observation, ...]:
    normalized = normalize_indicator_rows(rows, percentile_window=percentile_window)
    by_key: dict[tuple[str, str], dict[str, IndicatorRow]] = defaultdict(dict)
    for row in normalized:
        by_key[row.key][row.indicator_id] = row

    observations: list[Observation] = []
    for security_id, trading_date in sorted(by_key):
        items = by_key[(security_id, trading_date)]
        c1 = items.get(C1_ID)
        c2 = items.get(C2_ID)
        pair_valid = _is_native_valid(c1) and _is_native_valid(c2)
        mean_score = None
        min_score = None
        if pair_valid:
            assert c1 is not None and c2 is not None
            assert c1.score is not None and c2.score is not None
            mean_score = (c1.score + c2.score) / 2.0
            min_score = min(c1.score, c2.score)
        baseline_active = (
            (
                pair_valid
                and mean_score is not None
                and min_score is not None
                and _meets(mean_score, SCORE_THRESHOLD)
                and _meets(min_score, BASELINE_MIN_THRESHOLD)
            )
            if pair_valid
            else None
        )
        c1_active = (
            (
                pair_valid
                and c1 is not None
                and c1.score is not None
                and _meets(c1.score, SCORE_THRESHOLD)
            )
            if pair_valid
            else None
        )
        c2_active = (
            (
                pair_valid
                and c2 is not None
                and c2.score is not None
                and _meets(c2.score, SCORE_THRESHOLD)
            )
            if pair_valid
            else None
        )
        observations.append(
            Observation(
                security_id=security_id,
                trading_date=trading_date,
                c1=c1,
                c2=c2,
                pair_common_valid=pair_valid,
                score_mean=mean_score,
                score_min=min_score,
                baseline_active=baseline_active,
                c1_active=c1_active,
                c2_active=c2_active,
            )
        )
    return tuple(observations)


def build_profiles(
    rows: Iterable[Mapping[str, Any] | IndicatorRow],
    *,
    dimension_score_rows: Iterable[Mapping[str, Any]] | None = None,
    dimension_state_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]] | dict[str, Any] | tuple[Observation, ...]]:
    """Build all small formal artifacts from normalized in-memory rows."""

    normalized = normalize_indicator_rows(rows)
    observations = build_observations(normalized)
    result: dict[str, Any] = {
        "variant_profile": build_variant_profiles(observations),
        "overlap_profile": build_overlap_profiles(observations),
        "score_comparison": build_score_comparisons(observations),
        "year_profile": build_year_profiles(observations),
        "security_profile": build_security_profiles(observations),
        "availability_profile": build_availability_profile(normalized, observations),
        "observations": observations,
    }
    if dimension_score_rows is not None or dimension_state_rows is not None:
        if dimension_score_rows is None or dimension_state_rows is None:
            raise InputContractError(
                "dimension score and dimension state are both required "
                "for reconciliation"
            )
        result["baseline_reconciliation"] = reconcile_baseline(
            observations,
            dimension_score_rows,
            dimension_state_rows,
        )
    return result


def build_variant_profiles(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    return [_variant_profile(observations, variant_id) for variant_id in VARIANT_IDS]


def build_overlap_profiles(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    pairs = (
        (BASELINE_VARIANT, C1_VARIANT),
        (BASELINE_VARIANT, C2_VARIANT),
        (C1_VARIANT, C2_VARIANT),
    )
    valid = tuple(
        observation for observation in observations if observation.pair_common_valid
    )
    output: list[dict[str, Any]] = []
    for left_variant, right_variant in pairs:
        counts = _binary_counts(
            (item.active_for(left_variant), item.active_for(right_variant))
            for item in valid
        )
        left_true = counts["n11"] + counts["n10"]
        right_true = counts["n11"] + counts["n01"]
        left_given_right = _ratio(counts["n11"], right_true)
        right_given_left = _ratio(counts["n11"], left_true)
        union = counts["n11"] + counts["n10"] + counts["n01"]
        output.append(
            {
                "left_variant": left_variant,
                "right_variant": right_variant,
                "W": W,
                "q": Q,
                "weak_delta": WEAK_DELTA,
                "denominator_scope": "pair_common_valid",
                "common_valid_rows": len(valid),
                **counts,
                "left_true_count": left_true,
                "right_true_count": right_true,
                "jaccard": _ratio(counts["n11"], union),
                "left_given_right": left_given_right,
                "right_given_left": right_given_left,
                "baseline_retention": (
                    right_given_left if left_variant == BASELINE_VARIANT else None
                ),
                "candidate_precision": (
                    left_given_right if left_variant == BASELINE_VARIANT else None
                ),
                "symmetric_difference_count": counts["n10"] + counts["n01"],
                "symmetric_difference_rate": _ratio(
                    counts["n10"] + counts["n01"], len(valid)
                ),
            }
        )
    return output


def build_score_comparisons(
    observations: Sequence[Observation],
) -> list[dict[str, Any]]:
    valid = tuple(
        observation for observation in observations if observation.pair_common_valid
    )
    definitions = (
        ("c1_vs_c2", lambda item: (item.c1.score, item.c2.score)),
        ("c1_vs_baseline_mean", lambda item: (item.c1.score, item.score_mean)),
        ("c2_vs_baseline_mean", lambda item: (item.c2.score, item.score_mean)),
    )
    result: list[dict[str, Any]] = []
    for comparison_id, value_fn in definitions:
        pairs = [value_fn(item) for item in valid]
        cleaned = [
            (float(left), float(right), item.security_id)
            for item, (left, right) in zip(valid, pairs, strict=True)
            if left is not None and right is not None
        ]
        left_values = [item[0] for item in cleaned]
        right_values = [item[1] for item in cleaned]
        differences = [
            abs(left - right) for left, right in zip(left_values, right_values)
        ]
        per_security: list[float] = []
        by_security: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for left, right, security_id in cleaned:
            by_security[security_id].append((left, right))
        for security_id in sorted(by_security):
            security_pairs = by_security[security_id]
            correlation = _spearman(
                [item[0] for item in security_pairs],
                [item[1] for item in security_pairs],
            )
            if correlation is not None:
                per_security.append(correlation)
        result.append(
            {
                "comparison_id": comparison_id,
                "W": W,
                "q": Q,
                "common_valid_rows": len(cleaned),
                "pooled_spearman": _spearman(left_values, right_values),
                "per_security_spearman_median": _quantile(per_security, 0.50),
                "per_security_spearman_q25": _quantile(per_security, 0.25),
                "per_security_spearman_q75": _quantile(per_security, 0.75),
                "mean_absolute_score_difference": _mean(differences),
                "median_absolute_score_difference": _quantile(differences, 0.50),
                "q90_absolute_score_difference": _quantile(differences, 0.90),
                "q95_absolute_score_difference": _quantile(differences, 0.95),
            }
        )
    return result


def build_year_profiles(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    valid = tuple(
        observation for observation in observations if observation.pair_common_valid
    )
    years = sorted({item.calendar_year for item in valid})
    result: list[dict[str, Any]] = []
    for candidate in CANDIDATE_VARIANTS:
        for year in years:
            items = tuple(item for item in valid if item.calendar_year == year)
            stats = _relative_overlap_stats(items, candidate)
            result.append(
                {
                    "calendar_year": year,
                    "candidate_variant": candidate,
                    "baseline_variant": BASELINE_VARIANT,
                    "W": W,
                    "q": Q,
                    **stats,
                }
            )
    return result


def build_security_profiles(
    observations: Sequence[Observation],
) -> list[dict[str, Any]]:
    valid = tuple(
        observation for observation in observations if observation.pair_common_valid
    )
    by_security: dict[str, list[Observation]] = defaultdict(list)
    for item in valid:
        by_security[item.security_id].append(item)
    result: list[dict[str, Any]] = []
    for candidate in CANDIDATE_VARIANTS:
        for security_id in sorted(by_security):
            items = tuple(by_security[security_id])
            stats = _relative_overlap_stats(items, candidate)
            result.append(
                {
                    "security_id": security_id,
                    "candidate_variant": candidate,
                    "baseline_variant": BASELINE_VARIANT,
                    "W": W,
                    "q": Q,
                    "valid_row_count": stats["common_valid_rows"],
                    "baseline_true_count": stats["baseline_true_count"],
                    "candidate_true_count": stats["candidate_true_count"],
                    "jaccard": stats["jaccard"],
                    "baseline_retention": stats["baseline_retention"],
                    "candidate_precision": stats["candidate_precision"],
                }
            )
    return result


def build_availability_profile(
    rows: Sequence[IndicatorRow],
    observations: Sequence[Observation],
) -> list[dict[str, Any]]:
    row_counts = {indicator_id: 0 for indicator_id in INDICATOR_IDS}
    native_valid_counts = {indicator_id: 0 for indicator_id in INDICATOR_IDS}
    for row in rows:
        row_counts[row.indicator_id] += 1
        if _is_native_valid(row):
            native_valid_counts[row.indicator_id] += 1
    pair_count = sum(1 for item in observations if item.pair_common_valid)
    output = []
    for indicator_id in INDICATOR_IDS:
        output.append(
            {
                "indicator_id": indicator_id,
                "W": W,
                "q": Q,
                "availability_scope": "native_valid",
                "input_row_count": row_counts[indicator_id],
                "native_valid_count": native_valid_counts[indicator_id],
                "native_invalid_count": row_counts[indicator_id]
                - native_valid_counts[indicator_id],
                "pair_common_valid_count": pair_count,
                "availability_gain_vs_pair": native_valid_counts[indicator_id]
                - pair_count,
            }
        )
    output.append(
        {
            "indicator_id": "pair_common_valid",
            "W": W,
            "q": Q,
            "availability_scope": "pair_common_valid",
            "input_row_count": len(observations),
            "native_valid_count": pair_count,
            "native_invalid_count": len(observations) - pair_count,
            "pair_common_valid_count": pair_count,
            "availability_gain_vs_pair": 0,
        }
    )
    return output


def reconcile_baseline(
    observations: Sequence[Observation],
    dimension_score_rows: Iterable[Mapping[str, Any]],
    dimension_state_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare an independent pair rebuild to authoritative C score/state rows."""

    expected = {
        item.key: {
            "score_dimension": item.score_mean,
            "score_dimension_min": item.score_min,
            "eligible_dimension": item.pair_common_valid,
            "validity_status": _expected_pair_status(
                item.c1, item.c2, item.pair_common_valid
            ),
            "dimension_active_weak": item.baseline_active,
        }
        for item in observations
    }
    dimension = _reference_map(dimension_score_rows, "dimension_score")
    state = _reference_map(dimension_state_rows, "dimension_state")
    expected_keys = set(expected)
    dimension_keys = set(dimension)
    state_keys = set(state)
    key_count_mismatch = int(
        len(expected_keys) != len(dimension_keys)
        or len(expected_keys) != len(state_keys)
        or expected_keys != dimension_keys
        or expected_keys != state_keys
    )
    score_mean_mismatch = 0
    score_min_mismatch = 0
    eligible_mismatch = 0
    dimension_validity_mismatch = 0
    active_mismatch = 0
    state_validity_mismatch = 0
    for key, expected_row in expected.items():
        actual_dimension = dimension.get(key)
        actual_state = state.get(key)
        if actual_dimension is None:
            score_mean_mismatch += 1
            score_min_mismatch += 1
            eligible_mismatch += 1
            dimension_validity_mismatch += 1
        else:
            score_mean_mismatch += int(
                not _same_number(
                    expected_row["score_dimension"],
                    actual_dimension.get("score_dimension"),
                )
            )
            score_min_mismatch += int(
                not _same_number(
                    expected_row["score_dimension_min"],
                    actual_dimension.get("score_dimension_min"),
                )
            )
            eligible_mismatch += int(
                expected_row["eligible_dimension"]
                is not (actual_dimension.get("eligible_dimension") is True)
            )
            dimension_validity_mismatch += int(
                expected_row["validity_status"]
                != str(actual_dimension.get("validity_status"))
            )
        if actual_state is None:
            active_mismatch += 1
            state_validity_mismatch += 1
        else:
            active_mismatch += int(
                not _same_bool_or_null(
                    expected_row["dimension_active_weak"],
                    actual_state.get("dimension_active_weak"),
                )
            )
            state_validity_mismatch += int(
                expected_row["validity_status"]
                != str(actual_state.get("validity_status"))
            )
    validity_mismatch = dimension_validity_mismatch + state_validity_mismatch
    mismatch_total = (
        key_count_mismatch
        + score_mean_mismatch
        + score_min_mismatch
        + eligible_mismatch
        + active_mismatch
        + validity_mismatch
    )
    return {
        "expected_key_count": len(expected_keys),
        "dimension_score_key_count": len(dimension_keys),
        "dimension_state_key_count": len(state_keys),
        "key_count": len(expected_keys),
        "key_count_mismatch": key_count_mismatch,
        "score_mean_mismatch": score_mean_mismatch,
        "score_min_mismatch": score_min_mismatch,
        "eligible_mismatch": eligible_mismatch,
        "active_mismatch": active_mismatch,
        "validity_mismatch": validity_mismatch,
        "dimension_validity_mismatch": dimension_validity_mismatch,
        "state_validity_mismatch": state_validity_mismatch,
        "mismatch_total": mismatch_total,
        "status": "passed" if mismatch_total == 0 else "failed",
    }


def _variant_profile(
    observations: Sequence[Observation], variant_id: str
) -> dict[str, Any]:
    by_security: dict[str, list[Observation]] = defaultdict(list)
    for item in observations:
        by_security[item.security_id].append(item)

    true_count = 0
    false_count = 0
    transition_count = 0
    true_to_false = 0
    false_to_true = 0
    valid_block_count = 0
    segment_start_count = 0
    segment_durations: list[int] = []
    valid_security_ids: set[str] = set()
    year_valid_counts: dict[int, int] = defaultdict(int)
    year_true_counts: dict[int, int] = defaultdict(int)

    for security_id in sorted(by_security):
        previous_valid = False
        previous_active: bool | None = None
        current_segment = 0
        for item in by_security[security_id]:
            active = item.active_for(variant_id) if item.pair_common_valid else None
            if active is None:
                if current_segment:
                    segment_durations.append(current_segment)
                    current_segment = 0
                previous_valid = False
                previous_active = None
                continue

            valid_security_ids.add(security_id)
            year_valid_counts[item.calendar_year] += 1
            if active:
                true_count += 1
                year_true_counts[item.calendar_year] += 1
            else:
                false_count += 1

            if not previous_valid:
                valid_block_count += 1
            elif active != previous_active:
                transition_count += 1
                if previous_active and not active:
                    true_to_false += 1
                elif not previous_active and active:
                    false_to_true += 1

            if active:
                if not previous_valid or previous_active is False:
                    segment_start_count += 1
                    current_segment = 1
                else:
                    current_segment += 1
            elif current_segment:
                segment_durations.append(current_segment)
                current_segment = 0
            previous_valid = True
            previous_active = active
        if current_segment:
            segment_durations.append(current_segment)

    valid_count = true_count + false_count
    year_shares = [
        year_true_counts[year] / year_valid_counts[year]
        for year in year_valid_counts
        if year_valid_counts[year]
    ]
    return {
        "variant_id": variant_id,
        "W": W,
        "q": Q,
        "weak_delta": WEAK_DELTA,
        "denominator_scope": "pair_common_valid",
        "eligible_row_count": valid_count,
        "active_true_count": true_count,
        "active_false_count": false_count,
        "active_rate": _ratio(true_count, valid_count),
        "transition_count": transition_count,
        "transition_rate_per_100_valid_steps": (
            transition_count * 100.0 / valid_count if valid_count else None
        ),
        "valid_step_count": valid_count,
        "valid_block_count": valid_block_count,
        "true_to_false_transition_count": true_to_false,
        "false_to_true_transition_count": false_to_true,
        "segment_count": len(segment_durations),
        "segment_start_count": segment_start_count,
        "segment_duration_sum": sum(segment_durations),
        "mean_segment_duration": _mean(segment_durations),
        "median_segment_duration": _quantile(segment_durations, 0.50),
        "q90_segment_duration": _quantile(segment_durations, 0.90),
        "max_segment_duration": max(segment_durations) if segment_durations else None,
        "singleton_segment_count": sum(
            1 for duration in segment_durations if duration == 1
        ),
        "singleton_segment_ratio": (
            sum(1 for duration in segment_durations if duration == 1)
            / len(segment_durations)
            if segment_durations
            else None
        ),
        "unique_security_count": len(valid_security_ids),
        "nonzero_year_count": sum(
            1 for year in year_valid_counts if year_true_counts[year] > 0
        ),
        "max_year_active_share": max(year_shares) if year_shares else None,
    }


def _relative_overlap_stats(
    observations: Sequence[Observation], candidate_variant: str
) -> dict[str, Any]:
    counts = _binary_counts(
        (
            item.active_for(BASELINE_VARIANT),
            item.active_for(candidate_variant),
        )
        for item in observations
    )
    baseline_true = counts["n11"] + counts["n10"]
    candidate_true = counts["n11"] + counts["n01"]
    union = counts["n11"] + counts["n10"] + counts["n01"]
    return {
        "common_valid_rows": len(observations),
        "baseline_true_count": baseline_true,
        "candidate_true_count": candidate_true,
        "active_rate": _ratio(candidate_true, len(observations)),
        "baseline_active_rate": _ratio(baseline_true, len(observations)),
        "candidate_active_rate": _ratio(candidate_true, len(observations)),
        "jaccard": _ratio(counts["n11"], union),
        "baseline_retention": _ratio(counts["n11"], baseline_true),
        "candidate_precision": _ratio(counts["n11"], candidate_true),
        "symmetric_difference_rate": _ratio(
            counts["n10"] + counts["n01"], len(observations)
        ),
    }


def _binary_counts(pairs: Iterable[tuple[bool | None, bool | None]]) -> dict[str, int]:
    counts = {"n11": 0, "n10": 0, "n01": 0, "n00": 0}
    for left, right in pairs:
        if left is None or right is None:
            raise InputContractError("binary comparison received an invalid step")
        if left and right:
            counts["n11"] += 1
        elif left and not right:
            counts["n10"] += 1
        elif not left and right:
            counts["n01"] += 1
        else:
            counts["n00"] += 1
    return counts


def _normalise_indicator_mapping(
    row: Mapping[str, Any], percentile_window: int
) -> IndicatorRow:
    try:
        observed_window = int(row["percentile_window_W"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InputContractError("percentile_window_W is required") from exc
    if observed_window != W or observed_window != percentile_window:
        raise InputContractError(f"only W=120 is supported: {observed_window}")
    try:
        indicator_id = str(row["indicator_id"])
        security_id = str(row["security_id"])
        trading_date = _date_text(row["trading_date"])
        eligible = row["eligible"]
        validity_status = str(row["validity_status"])
    except KeyError as exc:
        raise InputContractError(
            f"missing required indicator field: {exc.args[0]}"
        ) from exc
    if not security_id or not trading_date:
        raise InputContractError("security_id and trading_date must be non-empty")
    if not isinstance(eligible, bool):
        raise InputContractError("eligible must be boolean")
    if validity_status not in VALIDITY_STATUSES:
        raise InputContractError(f"invalid validity_status: {validity_status}")
    score = _finite_score(row.get("score"))
    if eligible and validity_status == "valid" and score is None:
        raise InputContractError("valid eligible row cannot have NULL score")
    if not eligible and score is not None:
        raise InputContractError("ineligible row cannot carry a score")
    return IndicatorRow(
        security_id=security_id,
        trading_date=trading_date,
        indicator_id=indicator_id,
        score=score,
        eligible=eligible,
        validity_status=validity_status,
    )


def _reference_map(
    rows: Iterable[Mapping[str, Any]], source_name: str
) -> dict[tuple[str, str], dict[str, Any]]:
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        try:
            window = int(raw["percentile_window_W"])
            security_id = str(raw["security_id"])
            trading_date = _date_text(raw["trading_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InputContractError(f"invalid {source_name} row") from exc
        if window != W or str(raw.get("dimension")) != "C":
            raise InputContractError(f"out-of-scope {source_name} row")
        key = (security_id, trading_date)
        if key in output:
            raise InputContractError(f"duplicate {source_name} key: {key}")
        output[key] = dict(raw)
    return output


def _expected_pair_status(
    c1: IndicatorRow | None, c2: IndicatorRow | None, pair_valid: bool
) -> str:
    if pair_valid:
        return "valid"
    statuses = [
        row.validity_status for row in (c1, c2) if row is not None and not row.eligible
    ]
    if "blocked" in statuses:
        return "blocked"
    if "diagnostic_required" in statuses:
        return "diagnostic_required"
    return "unknown"


def _is_native_valid(row: IndicatorRow | None) -> bool:
    return bool(
        row is not None
        and row.eligible is True
        and row.validity_status == "valid"
        and row.score is not None
    )


def _same_number(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    try:
        return abs(float(expected) - float(actual)) <= FLOAT_EPSILON
    except (TypeError, ValueError):
        return False


def _same_bool_or_null(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    return expected is (actual is True)


def _date_text(value: Any) -> str:
    if value is None:
        raise InputContractError("trading_date cannot be NULL")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).replace("T", " ").split(" ", 1)[0]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise InputContractError(f"trading_date must be ISO date: {value}") from exc


def _finite_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise InputContractError(f"score must be numeric or NULL: {value}") from exc
    if not math.isfinite(score):
        raise InputContractError("score must be finite")
    if not 0.0 <= score <= 1.0:
        raise InputContractError(f"score outside [0,1]: {score}")
    return score


def _indicator_sort_key(row: IndicatorRow) -> tuple[str, str, str]:
    return row.security_id, row.trading_date, row.indicator_id


def _meets(value: float, threshold: float) -> bool:
    return value + FLOAT_EPSILON >= threshold


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _mean(values: Sequence[int | float]) -> float | None:
    if not values:
        return None
    return float(sum(values)) / len(values)


def _quantile(values: Sequence[int | float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_rankdata(left), _rankdata(right))


def _rankdata(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for position in range(index, end):
            ranks[ordered[position][0]] = rank
        index = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_ss = sum((value - left_mean) ** 2 for value in left)
    right_ss = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_ss * right_ss)
    if denominator <= FLOAT_EPSILON:
        return None
    return numerator / denominator
