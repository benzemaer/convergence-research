from __future__ import annotations

from collections.abc import Iterable, Sequence
from hashlib import sha256

import numpy as np

VALID = np.int8(0)
UNKNOWN = np.int8(1)
DIAGNOSTIC_REQUIRED = np.int8(2)
BLOCKED = np.int8(3)

RAW_NULL = np.int8(-1)
RAW_FALSE = np.int8(0)
RAW_TRUE = np.int8(1)

MASK64 = np.uint64(0xFFFFFFFFFFFFFFFF)
SPLITMIX_GAMMA = np.uint64(0x9E3779B97F4A7C15)
SPLITMIX_M1 = np.uint64(0xBF58476D1CE4E5B9)
SPLITMIX_M2 = np.uint64(0x94D049BB133111EB)


def ordered_and(
    raw_layers: Sequence[np.ndarray], status_layers: Sequence[np.ndarray]
) -> tuple[np.ndarray, np.ndarray]:
    """Rebuild R0's short-circuiting ordered three-valued AND."""
    if not raw_layers or len(raw_layers) != len(status_layers):
        raise ValueError("raw_layers and status_layers must be non-empty and aligned")
    raw = np.asarray(raw_layers[0], dtype=np.int8).copy()
    status = np.asarray(status_layers[0], dtype=np.int8).copy()
    if raw.shape != status.shape:
        raise ValueError("raw/status shape mismatch")
    for next_raw_like, next_status_like in zip(
        raw_layers[1:], status_layers[1:], strict=True
    ):
        next_raw = np.asarray(next_raw_like, dtype=np.int8)
        next_status = np.asarray(next_status_like, dtype=np.int8)
        if next_raw.shape != raw.shape or next_status.shape != raw.shape:
            raise ValueError("layer shape mismatch")
        active = raw == RAW_TRUE
        raw[active] = next_raw[active]
        status[active] = next_status[active]
    status[raw != RAW_NULL] = VALID
    return raw, status


def derive_continuous_blocks(
    security_code: np.ndarray,
    date_year: np.ndarray,
    calendar_ordinal: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split at security/year boundaries and missing master-calendar observations."""
    security_code = np.asarray(security_code)
    date_year = np.asarray(date_year)
    calendar_ordinal = np.asarray(calendar_ordinal)
    if not (
        security_code.shape == date_year.shape == calendar_ordinal.shape
        and security_code.ndim == 1
    ):
        raise ValueError("block inputs must be aligned one-dimensional arrays")
    if not len(security_code):
        empty = np.array([], dtype=np.int64)
        return empty, empty, empty, empty
    starts_new = np.ones(len(security_code), dtype=bool)
    starts_new[1:] = (
        (security_code[1:] != security_code[:-1])
        | (date_year[1:] != date_year[:-1])
        | (calendar_ordinal[1:] - calendar_ordinal[:-1] != 1)
    )
    starts = np.flatnonzero(starts_new).astype(np.int64)
    ends = np.r_[starts[1:], len(security_code)].astype(np.int64)
    lengths = ends - starts
    block_id = np.cumsum(starts_new, dtype=np.int64) - 1
    within = np.arange(len(security_code), dtype=np.int64) - starts[block_id]
    return starts, lengths, block_id, within


def derived_seed(
    root_seed: int,
    candidate_config_id: str,
    null_model_id: str,
    replicate_id: int,
    layer: str,
) -> int:
    payload = (
        f"r1_t08_seed_v1|{root_seed}|{candidate_config_id}|{null_model_id}|"
        f"{replicate_id}|{layer}"
    ).encode()
    return int.from_bytes(sha256(payload).digest()[:8], "little", signed=False)


def deterministic_offsets(block_lengths: np.ndarray, seed: int) -> np.ndarray:
    """Counter-based offsets; zero is reserved for singleton blocks."""
    lengths = np.asarray(block_lengths, dtype=np.int64)
    counters = np.arange(len(lengths), dtype=np.uint64)
    with np.errstate(over="ignore"):
        values = counters * SPLITMIX_GAMMA + np.uint64(seed)
        values = (values ^ (values >> np.uint64(30))) * SPLITMIX_M1
        values = (values ^ (values >> np.uint64(27))) * SPLITMIX_M2
        values ^= values >> np.uint64(31)
    offsets = np.zeros(len(lengths), dtype=np.int64)
    shiftable = lengths > 1
    offsets[shiftable] = 1 + (
        values[shiftable] % (lengths[shiftable] - 1).astype(np.uint64)
    ).astype(np.int64)
    return offsets


def shifted_source_indices(
    target_indices: np.ndarray,
    block_starts: np.ndarray,
    block_lengths: np.ndarray,
    block_id: np.ndarray,
    within_block: np.ndarray,
    offsets: np.ndarray,
) -> np.ndarray:
    targets = np.asarray(target_indices, dtype=np.int64)
    target_blocks = block_id[targets]
    return (
        block_starts[target_blocks]
        + (within_block[targets] - offsets[target_blocks])
        % block_lengths[target_blocks]
    ).astype(np.int64)


def offset_plan_hash(layer_offsets: Iterable[tuple[str, np.ndarray]]) -> str:
    digest = sha256()
    for layer, offsets in layer_offsets:
        digest.update(layer.encode("ascii"))
        digest.update(b"\0")
        digest.update(np.asarray(offsets, dtype="<i8").tobytes())
    return digest.hexdigest()


def sparse_confirmed_metrics(
    true_indices: np.ndarray,
    security_code: np.ndarray,
    *,
    eligible_count: int,
    confirmation_k: int,
) -> dict[str, float | int | None]:
    indices = np.asarray(true_indices, dtype=np.int64)
    if indices.size == 0:
        return {
            "confirmed_day_count": 0,
            "confirmed_coverage": 0.0 if eligible_count else None,
            "interval_count": 0,
            "duration_mean": None,
            "duration_median": None,
            "fragment_count": 0,
            "fragment_rate": None,
        }
    if np.any(indices[1:] <= indices[:-1]):
        raise ValueError("true_indices must be unique and sorted")
    breaks = np.ones(indices.size, dtype=bool)
    breaks[1:] = (indices[1:] != indices[:-1] + 1) | (
        security_code[indices[1:]] != security_code[indices[:-1]]
    )
    run_starts = np.flatnonzero(breaks)
    run_ends = np.r_[run_starts[1:], indices.size]
    raw_lengths = run_ends - run_starts
    confirmed_lengths = raw_lengths[raw_lengths >= confirmation_k] - confirmation_k + 1
    interval_count = int(confirmed_lengths.size)
    confirmed_days = int(confirmed_lengths.sum())
    fragment_count = int(np.count_nonzero(confirmed_lengths == 1))
    return {
        "confirmed_day_count": confirmed_days,
        "confirmed_coverage": (
            float(confirmed_days / eligible_count) if eligible_count else None
        ),
        "interval_count": interval_count,
        "duration_mean": (
            float(np.mean(confirmed_lengths)) if interval_count else None
        ),
        "duration_median": (
            float(np.median(confirmed_lengths)) if interval_count else None
        ),
        "fragment_count": fragment_count,
        "fragment_rate": (
            float(fragment_count / interval_count) if interval_count else None
        ),
    }


def nested_retention_metrics(
    parent_true_indices: np.ndarray,
    shifted_raw: np.ndarray,
    shifted_status: np.ndarray,
) -> dict[str, float | int | None]:
    parent = np.asarray(parent_true_indices, dtype=np.int64)
    raw = np.asarray(shifted_raw, dtype=np.int8)
    status = np.asarray(shifted_status, dtype=np.int8)
    if not (parent.shape == raw.shape == status.shape):
        raise ValueError("nested arrays must be aligned")
    valid = (status == VALID) & (raw != RAW_NULL)
    child_true = int(np.count_nonzero(valid & (raw == RAW_TRUE)))
    child_false = int(np.count_nonzero(valid & (raw == RAW_FALSE)))
    unknown = int(np.count_nonzero(status == UNKNOWN))
    blocked = int(np.count_nonzero(status == BLOCKED))
    diagnostic = int(np.count_nonzero(status == DIAGNOSTIC_REQUIRED))
    denominator = child_true + child_false
    return {
        "parent_eligible_count": denominator,
        "parent_active_count": int(parent.size),
        "child_true_count": child_true,
        "child_false_count": child_false,
        "child_unknown_count": unknown,
        "child_blocked_count": blocked,
        "child_diagnostic_count": diagnostic,
        "nested_retention": (float(child_true / denominator) if denominator else None),
    }


def percentile_interval(values: np.ndarray) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    return (
        float(np.quantile(array, 0.025, method="linear")),
        float(np.quantile(array, 0.975, method="linear")),
    )


def extreme_count(values: np.ndarray, observed: float, tail: str) -> int:
    array = np.asarray(values, dtype=float)
    if tail == "upper":
        return int(np.count_nonzero(array >= observed))
    if tail == "lower":
        return int(np.count_nonzero(array <= observed))
    if tail == "two-sided":
        center = float(np.mean(array))
        return int(np.count_nonzero(np.abs(array - center) >= abs(observed - center)))
    raise ValueError(f"unsupported tail: {tail}")
