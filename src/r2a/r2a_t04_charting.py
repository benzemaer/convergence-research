"""Deterministic chart sampling and rendering for R2A-T04."""

from __future__ import annotations

import csv
import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

MANUAL_REVIEW_FIELDS = (
    "ma_convergence_visible",
    "price_near_ma_cloud",
    "volatility_contraction_visible",
    "volume_contraction_visible",
    "amount_contraction_visible",
    "release_after_confirmation",
    "release_direction",
    "confirmation_too_late",
    "looks_tradeable",
    "review_confidence",
    "review_notes",
)


class R2AT04ChartError(ValueError):
    pass


def _stable_key(request_hash: str, row: Mapping[str, Any]) -> tuple[str, str, str]:
    security_id = str(row["security_id"])
    confirmation_date = str(row["confirmation_date"])
    digest = hashlib.sha256(
        f"{request_hash}:{security_id}:{confirmation_date}".encode()
    ).hexdigest()
    return digest, security_id, confirmation_date


def deterministic_chart_sample(
    rows: Sequence[Mapping[str, Any]],
    *,
    request_hash: str,
    target_count: int = 12,
    per_security_cap: int = 2,
) -> tuple[dict[str, Any], ...]:
    """Select the frozen strata, deduplicate, enforce cap, then hash-fill."""

    if target_count != 12:
        raise R2AT04ChartError("chart_sample_target_must_equal_12")
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        key = (str(row["security_id"]), str(row["confirmation_date"]))
        if key in unique:
            raise R2AT04ChartError("duplicate_interval_key")
        unique[key] = row
    candidates = list(unique.values())
    if len(candidates) < target_count:
        raise R2AT04ChartError("insufficient_unique_intervals")
    by_hash = sorted(candidates, key=lambda row: _stable_key(request_hash, row))
    strata: list[tuple[str, list[dict[str, Any]]]] = []
    for label, year_min, year_max in (
        ("hash_2016_2019", 2016, 2019),
        ("hash_2020_2022", 2020, 2022),
        ("hash_2023_2026", 2023, 2026),
    ):
        eligible = [
            row
            for row in by_hash
            if year_min <= int(str(row["confirmation_date"])[:4]) <= year_max
        ]
        strata.append((label, eligible[:1]))

    def finite(row: Mapping[str, Any], field: str) -> float | None:
        value = row.get(field)
        if value is None:
            return None
        converted = float(value)
        return converted if math.isfinite(converted) else None

    mfe = [row for row in candidates if finite(row, "mfe20") is not None]
    mfe.sort(key=lambda row: (-float(row["mfe20"]), _stable_key(request_hash, row)))
    strata.append(("highest_mfe20", mfe[:2]))
    mae = [row for row in candidates if finite(row, "mae20") is not None]
    mae.sort(
        key=lambda row: (-abs(float(row["mae20"])), _stable_key(request_hash, row))
    )
    strata.append(("largest_abs_mae20", mae[:2]))
    strength = [
        row for row in candidates if finite(row, "release_strength_atr") is not None
    ]
    strength.sort(
        key=lambda row: (
            float(row["release_strength_atr"]),
            _stable_key(request_hash, row),
        )
    )
    strata.append(("lowest_release_strength_atr", strength[:2]))
    duration = sorted(
        candidates,
        key=lambda row: (
            int(row["confirmed_observation_count"]),
            _stable_key(request_hash, row),
        ),
    )
    strata.extend(
        [
            ("shortest_duration", duration[:1]),
            ("median_duration", duration[(len(duration) - 1) // 2 :][:1]),
            ("longest_duration", duration[-1:]),
        ]
    )
    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str]] = set()
    security_counts: dict[str, int] = {}

    def add(row: Mapping[str, Any], stratum: str) -> bool:
        key = (str(row["security_id"]), str(row["confirmation_date"]))
        security_id = key[0]
        if (
            key in selected_keys
            or security_counts.get(security_id, 0) >= per_security_cap
        ):
            return False
        selected_keys.add(key)
        security_counts[security_id] = security_counts.get(security_id, 0) + 1
        selected.append({**dict(row), "sample_stratum": stratum})
        return True

    for stratum, entries in strata:
        for row in entries:
            add(row, stratum)
    for row in by_hash:
        if len(selected) == target_count:
            break
        add(row, "stable_hash_fill")
    if len(selected) != target_count:
        raise R2AT04ChartError("per_security_cap_prevents_target_count")
    return tuple(selected)


def write_visual_review_worksheet(
    path: Path, registry_rows: Iterable[Mapping[str, Any]]
) -> None:
    rows = [dict(row) for row in registry_rows]
    base_fields = list(rows[0]) if rows else ["logical_request_name", "chart_path"]
    if any(
        field in row and row[field] not in (None, "")
        for row in rows
        for field in MANUAL_REVIEW_FIELDS
    ):
        raise R2AT04ChartError("manual_review_field_prefilled")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=[*base_fields, *MANUAL_REVIEW_FIELDS]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, **{field: "" for field in MANUAL_REVIEW_FIELDS}})


def render_diagnostic_chart(
    *,
    path: Path,
    title: str,
    rows: Sequence[Mapping[str, Any]],
    markers: Mapping[str, str | None],
    dpi: int = 90,
) -> None:
    """Render one three-panel PNG without changing the fixed sample inventory."""

    if not rows:
        raise R2AT04ChartError("chart_context_empty")
    x = list(range(len(rows)))
    dates = [str(row["trading_date"]) for row in rows]
    figure, axes = plt.subplots(3, 1, figsize=(11.5, 7.5), sharex=True)
    figure.suptitle(title, fontsize=7)
    price = axes[0]
    price.fill_between(
        x,
        [float(row["adj_low"]) for row in rows],
        [float(row["adj_high"]) for row in rows],
        color="#c7d9f1",
        alpha=0.55,
        label="adj high/low",
    )
    for field, color in (
        ("adj_close", "black"),
        ("ma5", "#d62728"),
        ("ma10", "#ff7f0e"),
        ("ma20", "#2ca02c"),
        ("ma30", "#1f77b4"),
        ("ma60", "#9467bd"),
    ):
        price.plot(
            x, [row.get(field) for row in rows], label=field, lw=0.8, color=color
        )
    price.legend(ncol=4, fontsize=5, loc="upper left")
    participation = axes[1]
    participation.plot(
        x, [row.get("volume_shares") for row in rows], label="volume shares", lw=0.7
    )
    participation.plot(
        x, [row.get("volume_ma20") for row in rows], label="volume MA20", lw=0.7
    )
    participation.plot(
        x, [row.get("volume_ma60") for row in rows], label="volume MA60", lw=0.7
    )
    amount_axis = participation.twinx()
    amount_axis.plot(
        x,
        [row.get("amount_yuan") for row in rows],
        label="amount CNY",
        color="#9467bd",
        lw=0.6,
        alpha=0.7,
    )
    amount_axis.plot(
        x,
        [row.get("amount_ma20") for row in rows],
        label="amount MA20",
        color="#8c564b",
        lw=0.6,
    )
    amount_axis.plot(
        x,
        [row.get("amount_ma60") for row in rows],
        label="amount MA60",
        color="#e377c2",
        lw=0.6,
    )
    participation.legend(ncol=3, fontsize=5, loc="upper left")
    amount_axis.legend(ncol=3, fontsize=5, loc="upper right")
    state = axes[2]
    dimensions = [
        dimension
        for dimension in ("P", "C", "A", "V", "T")
        if any(row.get(f"score_{dimension}") is not None for row in rows)
    ]
    for dimension in dimensions:
        values = [row.get(f"score_{dimension}") for row in rows]
        state.plot(x, values, label=f"{dimension} mean", lw=0.8)
        state.plot(
            x,
            [row.get(f"min_{dimension}") for row in rows],
            label=f"{dimension} min",
            lw=0.55,
            linestyle=":",
        )
    state.plot(
        x,
        [row.get("main_threshold") for row in rows],
        label="main threshold",
        color="#555555",
        lw=0.7,
        linestyle="--",
    )
    state.plot(
        x,
        [row.get("weak_threshold") for row in rows],
        label="weak threshold",
        color="#888888",
        lw=0.7,
        linestyle="--",
    )
    state.plot(
        x,
        [row.get("raw_state_numeric") for row in rows],
        label="raw",
        color="black",
        lw=1.0,
    )
    state.plot(
        x,
        [row.get("confirmed_state_numeric") for row in rows],
        label="confirmed",
        color="#d62728",
        lw=1.0,
    )
    state.legend(ncol=4, fontsize=5, loc="upper left")
    date_to_x = {date: index for index, date in enumerate(dates)}
    raw_start = markers.get("raw_start")
    confirmation = markers.get("confirmation")
    confirmed_end = markers.get("confirmed_end")
    termination = markers.get("termination")
    if raw_start in date_to_x and confirmation in date_to_x:
        for axis in axes:
            axis.axvspan(
                date_to_x[raw_start],
                date_to_x[confirmation],
                color="#f4d35e",
                alpha=0.10,
            )
    if confirmation in date_to_x and confirmed_end in date_to_x:
        for axis in axes:
            axis.axvspan(
                date_to_x[confirmation],
                date_to_x[confirmed_end],
                color="#2a9d8f",
                alpha=0.10,
            )
    if termination in date_to_x:
        for axis in axes:
            axis.axvspan(
                date_to_x[termination], len(rows) - 1, color="#e76f51", alpha=0.06
            )
    for label, date in markers.items():
        if date and date in date_to_x:
            for axis in axes:
                axis.axvline(date_to_x[date], lw=0.7, linestyle="--", label=label)
    step = max(1, len(x) // 8)
    axes[-1].set_xticks(x[::step], dates[::step], rotation=30, ha="right", fontsize=6)
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=dpi, format="png", metadata={"Title": title})
    plt.close(figure)
    if path.stat().st_size > 1_000_000:
        raise R2AT04ChartError("chart_exceeds_one_mb", str(path))
