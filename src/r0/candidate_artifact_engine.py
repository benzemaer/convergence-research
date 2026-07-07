from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID = "valid"
UNKNOWN = "unknown"
DIAGNOSTIC_REQUIRED = "diagnostic_required"
BLOCKED = "blocked"

CANDIDATE_ARTIFACT_ENGINE_VERSION = "r0_t08_main_grid_candidate_artifact.v1"
CONFIG_SCHEMA_VERSION = "r0_t08_candidate_config.v1"
METRIC_VARIANT_ID = "pcvt_baseline_v0_4"
STATE_DEFINITION_DRAFT_VERSION = "r0_candidate_state_v0_4"
CONFIG_HASH_ALGORITHM = "sha256_canonical_json_v1"
CONTENT_HASH_ALGORITHM = "sha256_canonical_jsonl_v1"

PERCENTILE_WINDOW_VALUES = (120, 250, 500)
LOW_QUANTILE_Q_VALUES = (0.10, 0.20, 0.30)
CONFIRMATION_DAYS_K_VALUES = (2, 3, 5)
BASELINE_PERCENTILE_WINDOW_W = 250
BASELINE_LOW_QUANTILE_Q = 0.20
BASELINE_CONFIRMATION_DAYS_K = 3
DIMENSION_RULE = "weak"
WEAK_DELTA = 0.10

RAW_METRIC_FIELD_BY_INDICATOR = {
    "P1_NATR14": "NATR14_raw",
    "P2_LogRange20": "LogRange20_raw",
    "C1_LogMASpread_5_60": "LogMASpread_5_60_raw",
    "C2_AdjVWAPSpread_5_60": "AdjVWAPSpread_5_60_raw",
    "T1_ER20": "ER20_raw",
    "T2_AbsTrendT20": "AbsTrendT20_raw",
    "V1_TurnoverShrink20_60": "TurnoverShrink20_60_raw",
    "V2_LogAmount20_base": "LogAmount20_raw",
}
INDICATOR_SUFFIX_BY_ID = {
    "P1_NATR14": "P1",
    "P2_LogRange20": "P2",
    "C1_LogMASpread_5_60": "C1",
    "C2_AdjVWAPSpread_5_60": "C2",
    "T1_ER20": "T1",
    "T2_AbsTrendT20": "T2",
    "V1_TurnoverShrink20_60": "V1",
    "V2_AmountLevel20Pct": "V2",
}
DIMENSIONS = ("P", "C", "T", "V")
STATE_SUFFIX_BY_NAME = {
    "S_P": "P",
    "S_PC": "PC",
    "S_PCT": "PCT",
    "S_PCVT": "PCVT",
}
DAILY_REQUIRED_FIELDS = (
    "security_id",
    "trading_date",
    "candidate_config_id",
    "config_hash",
    "run_id",
    "code_commit",
    "input_data_version",
    "metric_variant_id",
    "state_definition_draft_version",
    "percentile_window_W",
    "low_quantile_q",
    "confirmation_days_K",
    "dimension_rule",
    "weak_delta",
    "NATR14_raw",
    "LogRange20_raw",
    "LogMASpread_5_60_raw",
    "AdjVWAPSpread_5_60_raw",
    "ER20_raw",
    "AbsTrendT20_raw",
    "TurnoverShrink20_60_raw",
    "LogAmount20_raw",
    "AmountLevel20Pct",
    "P_raw",
    "C_raw",
    "T_raw",
    "V_raw",
    "S_P_raw",
    "S_PC_raw",
    "S_PCT_raw",
    "S_PCVT_raw",
    "exclusive_state_layer",
    "streak_P",
    "streak_PC",
    "streak_PCT",
    "streak_PCVT",
    "S_P_conf",
    "S_PC_conf",
    "S_PCT_conf",
    "S_PCVT_conf",
    "validity_state",
    "unknown_reason_codes",
    "source_lineage",
    "artifact_engine_version",
)
INTERVAL_REQUIRED_FIELDS = (
    "security_id",
    "state_level",
    "candidate_config_id",
    "config_hash",
    "run_id",
    "code_commit",
    "input_data_version",
    "metric_variant_id",
    "state_definition_draft_version",
    "percentile_window_W",
    "low_quantile_q",
    "confirmation_days_K",
    "dimension_rule",
    "weak_delta",
    "confirmed_interval_id",
    "raw_start_date",
    "confirmation_time",
    "confirmed_start_date",
    "last_raw_active_date",
    "termination_time",
    "termination_type",
    "raw_length",
    "confirmed_length",
    "is_open_interval",
    "validity_status",
    "reason_codes",
    "source_lineage",
    "artifact_engine_version",
)
FORBIDDEN_OUTPUT_FIELDS = {
    "future_label",
    "future_labels",
    "future_return",
    "future_returns",
    "future_volatility",
    "breakout_direction",
    "release_direction",
    "win_rate",
    "pnl",
    "return",
    "returns",
    "backtest",
    "portfolio",
    "trade_signal",
    "buy_signal",
    "sell_signal",
}
LEGACY_V1_FIELD_NAMES = {
    "VolShrink20_60_raw",
    "V1_VolShrink20_60",
    "VolShrink20_60",
    "volume_shrink_20_60",
}
PROHIBITED_SOURCES = (
    "d1.raw_market_prices",
    "d2.adjusted_market_prices",
    "d2.market_price_quality_flags",
    "d2.membership_alignment",
    "d3.generated",
    "data/raw",
    "data/external",
    "data/generated",
    "MarketDB",
    ".day",
)
ALLOWED_LINEAGE_SOURCES = {
    "synthetic_in_memory_r0_grid_inputs",
    "r0_t04_raw_metric_engine",
    "r0_t05_strict_past_percentile_score",
    "r0_t06_weak_dimension_nested_state",
    "r0_t07_confirmation_streak_interval",
}


@dataclass(frozen=True)
class CandidateConfig:
    candidate_config_id: str
    config_hash: str
    percentile_window_W: int
    low_quantile_q: float
    confirmation_days_K: int
    dimension_rule: str
    weak_delta: float
    is_baseline_config: bool
    metric_variant_id: str = field(default=METRIC_VARIANT_ID)
    state_definition_draft_version: str = field(default=STATE_DEFINITION_DRAFT_VERSION)
    config_schema_version: str = field(default=CONFIG_SCHEMA_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_config_id": self.candidate_config_id,
            "config_hash": self.config_hash,
            "percentile_window_W": self.percentile_window_W,
            "low_quantile_q": self.low_quantile_q,
            "confirmation_days_K": self.confirmation_days_K,
            "dimension_rule": self.dimension_rule,
            "weak_delta": self.weak_delta,
            "is_baseline_config": self.is_baseline_config,
            "metric_variant_id": self.metric_variant_id,
            "state_definition_draft_version": self.state_definition_draft_version,
            "config_schema_version": self.config_schema_version,
        }


@dataclass(frozen=True)
class GuardResult:
    validity_status: str
    reason_codes: tuple[str, ...]
    artifact_engine_version: str = field(default=CANDIDATE_ARTIFACT_ENGINE_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "validity_status": self.validity_status,
            "reason_codes": list(self.reason_codes),
            "artifact_engine_version": self.artifact_engine_version,
        }


def build_candidate_configs() -> tuple[CandidateConfig, ...]:
    configs: list[CandidateConfig] = []
    for window in PERCENTILE_WINDOW_VALUES:
        for q in LOW_QUANTILE_Q_VALUES:
            for confirmation_k in CONFIRMATION_DAYS_K_VALUES:
                payload = _config_hash_payload(window, q, confirmation_k)
                configs.append(
                    CandidateConfig(
                        candidate_config_id=_candidate_config_id(
                            window, q, confirmation_k
                        ),
                        config_hash=_hash_object(payload),
                        percentile_window_W=window,
                        low_quantile_q=q,
                        confirmation_days_K=confirmation_k,
                        dimension_rule=DIMENSION_RULE,
                        weak_delta=WEAK_DELTA,
                        is_baseline_config=(
                            window == BASELINE_PERCENTILE_WINDOW_W
                            and _same_float(q, BASELINE_LOW_QUANTILE_Q)
                            and confirmation_k == BASELINE_CONFIRMATION_DAYS_K
                        ),
                    )
                )
    return tuple(sorted(configs, key=lambda item: item.candidate_config_id))


def assemble_candidate_daily_rows(
    *,
    raw_metric_results: Sequence[Mapping[str, Any] | Any] = (),
    indicator_score_results: Sequence[Mapping[str, Any] | Any] = (),
    dimension_score_results: Sequence[Mapping[str, Any] | Any] = (),
    nested_daily_state_results: Sequence[Mapping[str, Any] | Any] = (),
    daily_confirmation_results: Sequence[Mapping[str, Any] | Any] = (),
    run_id: str,
    code_commit: str,
    input_data_version: str,
    source_lineage: Sequence[str] = ("synthetic_in_memory_r0_grid_inputs",),
    as_of_time: str | None = None,
) -> tuple[dict[str, Any], ...]:
    configs = build_candidate_configs()
    raw_by_key = _index_latest(raw_metric_results, _raw_metric_key)
    indicator_by_key = _index_latest(indicator_score_results, _indicator_score_key)
    dimension_by_key = _index_latest(dimension_score_results, _dimension_score_key)
    nested_by_key = _index_latest(nested_daily_state_results, _nested_state_key)
    confirmation_by_key = _index_latest(
        daily_confirmation_results, _daily_confirmation_key
    )
    security_dates = _candidate_security_dates(nested_by_key, confirmation_by_key)

    rows: list[dict[str, Any]] = []
    for config in configs:
        for security_id, trading_date in sorted(security_dates):
            rows.append(
                _candidate_daily_row(
                    config=config,
                    security_id=security_id,
                    trading_date=trading_date,
                    raw_by_key=raw_by_key,
                    indicator_by_key=indicator_by_key,
                    dimension_by_key=dimension_by_key,
                    nested_by_key=nested_by_key,
                    confirmation_by_key=confirmation_by_key,
                    run_id=run_id,
                    code_commit=code_commit,
                    input_data_version=input_data_version,
                    source_lineage=source_lineage,
                    as_of_time=as_of_time,
                )
            )
    return tuple(sorted(rows, key=_daily_sort_key))


def assemble_confirmed_interval_rows(
    *,
    confirmed_interval_results: Sequence[Mapping[str, Any] | Any],
    run_id: str,
    code_commit: str,
    input_data_version: str,
    source_lineage: Sequence[str] = ("synthetic_in_memory_r0_grid_inputs",),
) -> tuple[dict[str, Any], ...]:
    config_by_params = {
        (
            config.percentile_window_W,
            config.low_quantile_q,
            config.confirmation_days_K,
        ): config
        for config in build_candidate_configs()
    }
    rows: list[dict[str, Any]] = []
    for item in confirmed_interval_results:
        row = _normalise_row(item)
        key = (
            int(row["percentile_window_W"]),
            float(row["q"]),
            int(row["confirmation_k"]),
        )
        config = config_by_params.get(key)
        if config is None:
            continue
        rows.append(
            {
                "security_id": str(row["security_id"]),
                "state_level": str(row["state_name"]),
                "candidate_config_id": config.candidate_config_id,
                "config_hash": config.config_hash,
                "run_id": run_id,
                "code_commit": code_commit,
                "input_data_version": input_data_version,
                "metric_variant_id": config.metric_variant_id,
                "state_definition_draft_version": (
                    config.state_definition_draft_version
                ),
                "percentile_window_W": config.percentile_window_W,
                "low_quantile_q": config.low_quantile_q,
                "confirmation_days_K": config.confirmation_days_K,
                "dimension_rule": config.dimension_rule,
                "weak_delta": config.weak_delta,
                "confirmed_interval_id": str(row["interval_id"]),
                "raw_start_date": row.get("raw_start_date"),
                "confirmation_time": row.get("confirmation_date"),
                "confirmed_start_date": row.get("confirmed_start_date"),
                "last_raw_active_date": (
                    row.get("last_observed_date")
                    if row.get("is_open_interval") is True
                    else row.get("interval_end_date")
                ),
                "termination_time": (
                    None
                    if row.get("is_open_interval") is True
                    else row.get("last_observed_date")
                ),
                "termination_type": row.get("termination_reason"),
                "raw_length": row.get("duration_raw_days"),
                "confirmed_length": row.get("duration_confirmed_days"),
                "is_open_interval": row.get("is_open_interval") is True,
                "validity_status": row.get("validity_status", UNKNOWN),
                "reason_codes": list(row.get("reason_codes", ())),
                "source_lineage": list(source_lineage),
                "artifact_engine_version": CANDIDATE_ARTIFACT_ENGINE_VERSION,
            }
        )
    return tuple(sorted(rows, key=_interval_sort_key))


def build_candidate_manifest(
    *,
    daily_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    run_id: str,
    created_at: str,
    code_commit: str,
    repository: str,
    input_data_version: str,
    input_sources: Sequence[str],
    input_hashes: Mapping[str, str],
    input_row_counts: Mapping[str, int],
) -> dict[str, Any]:
    configs = [config.as_dict() for config in build_candidate_configs()]
    baseline = next(config for config in configs if config["is_baseline_config"])
    daily_hash = content_hash(daily_rows)
    interval_hash = content_hash(interval_rows)
    manifest_id = _hash_object(
        {
            "task_id": "R0-T08",
            "run_id": run_id,
            "code_commit": code_commit,
            "daily_content_hash": daily_hash,
            "interval_content_hash": interval_hash,
            "candidate_config_count": len(configs),
        }
    )
    return {
        "manifest_id": manifest_id,
        "task_id": "R0-T08",
        "artifact_engine_version": CANDIDATE_ARTIFACT_ENGINE_VERSION,
        "run_id": run_id,
        "created_at": created_at,
        "code_commit": code_commit,
        "repository": repository,
        "input_data_version": input_data_version,
        "state_definition_draft_version": STATE_DEFINITION_DRAFT_VERSION,
        "metric_variant_id": METRIC_VARIANT_ID,
        "candidate_config_count": len(configs),
        "candidate_configs": configs,
        "baseline_candidate_config_id": baseline["candidate_config_id"],
        "input_sources": list(input_sources),
        "input_hashes": dict(sorted(input_hashes.items())),
        "input_row_counts": dict(sorted(input_row_counts.items())),
        "daily_state_artifact": "candidate_daily_state_rows.jsonl",
        "interval_artifact": "confirmed_interval_rows.jsonl",
        "daily_row_count": len(daily_rows),
        "interval_row_count": len(interval_rows),
        "daily_content_hash": daily_hash,
        "interval_content_hash": interval_hash,
        "config_hash_algorithm": CONFIG_HASH_ALGORITHM,
        "content_hash_algorithm": CONTENT_HASH_ALGORITHM,
        "schema_versions": {
            "candidate_config": CONFIG_SCHEMA_VERSION,
            "candidate_daily_state": "r0_t08_candidate_daily_state.v1",
            "confirmed_interval": "r0_t08_confirmed_interval.v1",
            "manifest": "r0_t08_candidate_manifest.v1",
        },
        "contract_ids": [
            "R0_T04_RAW_METRIC_ENGINE_CONTRACT_V1",
            "R0_T05_STRICT_PAST_PERCENTILE_SCORE_CONTRACT_V1",
            "R0_T06_WEAK_DIMENSION_NESTED_STATE_CONTRACT_V1",
            "R0_T07_CONFIRMATION_STREAK_INTERVAL_CONTRACT_V1",
            "R0_T08_MAIN_GRID_CANDIDATE_ARTIFACT_CONTRACT_V1",
        ],
        "quality_summary": _quality_summary(daily_rows, interval_rows, configs),
        "field_availability": _field_availability(daily_rows, interval_rows),
        "forbidden_output_guard": assert_no_forbidden_candidate_outputs(
            {"daily_rows": list(daily_rows), "interval_rows": list(interval_rows)}
        ).as_dict(),
        "lineage_guard": check_candidate_lineage(input_sources).as_dict(),
    }


def write_candidate_artifacts(
    output_dir: str | Path,
    *,
    daily_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    daily_path = target / "candidate_daily_state_rows.jsonl"
    interval_path = target / "confirmed_interval_rows.jsonl"
    manifest_path = target / "candidate_manifest.json"
    _write_jsonl(daily_path, daily_rows)
    _write_jsonl(interval_path, interval_rows)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return {
        "daily_path": str(daily_path),
        "interval_path": str(interval_path),
        "manifest_path": str(manifest_path),
        "daily_content_hash": file_content_hash(daily_path),
        "interval_content_hash": file_content_hash(interval_path),
        "manifest_content_hash": file_content_hash(manifest_path),
    }


def content_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = "\n".join(_canonical_json(row) for row in rows)
    if payload:
        payload += "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_content_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assert_no_forbidden_candidate_outputs(payload: Mapping[str, Any]) -> GuardResult:
    forbidden_reasons = [
        "forbidden_output_field"
        for key in _walk_keys(payload)
        if str(key).lower() in FORBIDDEN_OUTPUT_FIELDS
    ]
    legacy_reasons = [
        "legacy_v1_field_forbidden"
        for value in _walk_keys_and_sequence_strings(payload)
        if value in LEGACY_V1_FIELD_NAMES
    ]
    reasons = [*forbidden_reasons, *legacy_reasons]
    if reasons:
        return GuardResult(BLOCKED, _unique_reasons(reasons))
    return GuardResult(VALID, ("valid_no_blocker",))


def check_candidate_lineage(lineage: Mapping[str, Any] | Sequence[Any]) -> GuardResult:
    sources = _lineage_sources(lineage)
    if not sources:
        return GuardResult(UNKNOWN, ("candidate_lineage_missing",))
    if any(_is_prohibited_source(source) for source in sources):
        return GuardResult(BLOCKED, ("direct_real_data_source_forbidden",))
    if not any(source in ALLOWED_LINEAGE_SOURCES for source in sources):
        return GuardResult(UNKNOWN, ("candidate_lineage_missing",))
    return GuardResult(VALID, ("valid_no_blocker",))


def _candidate_daily_row(
    *,
    config: CandidateConfig,
    security_id: str,
    trading_date: str,
    raw_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]],
    indicator_by_key: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
    dimension_by_key: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
    nested_by_key: Mapping[tuple[str, str, int, float, float], Mapping[str, Any]],
    confirmation_by_key: Mapping[
        tuple[str, str, int, float, float, int, str], Mapping[str, Any]
    ],
    run_id: str,
    code_commit: str,
    input_data_version: str,
    source_lineage: Sequence[str],
    as_of_time: str | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "security_id": security_id,
        "trading_date": trading_date,
        "candidate_config_id": config.candidate_config_id,
        "config_hash": config.config_hash,
        "run_id": run_id,
        "code_commit": code_commit,
        "input_data_version": input_data_version,
        "metric_variant_id": config.metric_variant_id,
        "state_definition_draft_version": config.state_definition_draft_version,
        "percentile_window_W": config.percentile_window_W,
        "low_quantile_q": config.low_quantile_q,
        "confirmation_days_K": config.confirmation_days_K,
        "dimension_rule": config.dimension_rule,
        "weak_delta": config.weak_delta,
        "as_of_time": as_of_time,
        "source_lineage": list(source_lineage),
        "artifact_engine_version": CANDIDATE_ARTIFACT_ENGINE_VERSION,
    }
    reasons: list[str] = []
    statuses: list[str] = []
    _attach_raw_metrics(row, raw_by_key, security_id, trading_date)
    _attach_indicator_scores(
        row, indicator_by_key, security_id, trading_date, config, reasons, statuses
    )
    _attach_dimension_scores(
        row, dimension_by_key, security_id, trading_date, config, reasons, statuses
    )
    _attach_nested_state(
        row, nested_by_key, security_id, trading_date, config, reasons, statuses
    )
    _attach_confirmations(
        row, confirmation_by_key, security_id, trading_date, config, reasons, statuses
    )
    row["validity_state"] = _combined_status(statuses, reasons)
    row["unknown_reason_codes"] = _unique_reasons(reasons) or ["valid_no_blocker"]
    return row


def _attach_raw_metrics(
    row: dict[str, Any],
    raw_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]],
    security_id: str,
    trading_date: str,
) -> None:
    for indicator_id, field_name in RAW_METRIC_FIELD_BY_INDICATOR.items():
        raw = raw_by_key.get((security_id, trading_date, indicator_id))
        row[field_name] = raw.get("raw_value") if raw is not None else None


def _attach_indicator_scores(
    row: dict[str, Any],
    indicator_by_key: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
    security_id: str,
    trading_date: str,
    config: CandidateConfig,
    reasons: list[str],
    statuses: list[str],
) -> None:
    for indicator_id, suffix in INDICATOR_SUFFIX_BY_ID.items():
        score_row = indicator_by_key.get(
            (security_id, trading_date, config.percentile_window_W, indicator_id)
        )
        if score_row is None:
            row[f"percentile_{suffix}"] = None
            row[f"score_{suffix}"] = None
            row[f"eligible_{suffix}"] = None
            row[f"validity_{suffix}"] = UNKNOWN
            reasons.append("missing_upstream_result")
            statuses.append(UNKNOWN)
            continue
        row[f"percentile_{suffix}"] = score_row.get("percentile")
        row[f"score_{suffix}"] = score_row.get("score")
        row[f"eligible_{suffix}"] = score_row.get("eligible")
        row[f"validity_{suffix}"] = score_row.get("validity_status", UNKNOWN)
        statuses.append(str(score_row.get("validity_status", UNKNOWN)))
        reasons.extend(str(reason) for reason in score_row.get("reason_codes", ()))
        if indicator_id == "V2_AmountLevel20Pct":
            row["AmountLevel20Pct"] = score_row.get("percentile")

    row.setdefault("AmountLevel20Pct", None)


def _attach_dimension_scores(
    row: dict[str, Any],
    dimension_by_key: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
    security_id: str,
    trading_date: str,
    config: CandidateConfig,
    reasons: list[str],
    statuses: list[str],
) -> None:
    for dimension in DIMENSIONS:
        dimension_row = dimension_by_key.get(
            (security_id, trading_date, config.percentile_window_W, dimension)
        )
        if dimension_row is None:
            row[f"score_{dimension}"] = None
            row[f"score_{dimension}_min"] = None
            row[f"eligible_{dimension}"] = None
            reasons.append("missing_upstream_result")
            statuses.append(UNKNOWN)
            continue
        row[f"score_{dimension}"] = dimension_row.get("score_dimension")
        row[f"score_{dimension}_min"] = dimension_row.get("score_dimension_min")
        row[f"eligible_{dimension}"] = dimension_row.get("eligible_dimension")
        statuses.append(str(dimension_row.get("validity_status", UNKNOWN)))
        reasons.extend(str(reason) for reason in dimension_row.get("reason_codes", ()))

    row["eligible_PCT"] = _all_true(
        row.get(f"eligible_{dim}") for dim in ("P", "C", "T")
    )
    row["eligible_PCVT"] = _all_true(row.get(f"eligible_{dim}") for dim in DIMENSIONS)


def _attach_nested_state(
    row: dict[str, Any],
    nested_by_key: Mapping[tuple[str, str, int, float, float], Mapping[str, Any]],
    security_id: str,
    trading_date: str,
    config: CandidateConfig,
    reasons: list[str],
    statuses: list[str],
) -> None:
    nested = nested_by_key.get(
        (
            security_id,
            trading_date,
            config.percentile_window_W,
            config.low_quantile_q,
            config.weak_delta,
        )
    )
    nested_fields = (
        "P_raw",
        "C_raw",
        "T_raw",
        "V_raw",
        "S_P_raw",
        "S_PC_raw",
        "S_PCT_raw",
        "S_PCVT_raw",
        "exclusive_state_layer",
    )
    if nested is None:
        for field_name in nested_fields:
            row[field_name] = None
        reasons.append("missing_upstream_result")
        statuses.append(UNKNOWN)
        return
    for field_name in nested_fields:
        row[field_name] = nested.get(field_name)
    statuses.append(str(nested.get("validity_status", UNKNOWN)))
    reasons.extend(str(reason) for reason in nested.get("reason_codes", ()))


def _attach_confirmations(
    row: dict[str, Any],
    confirmation_by_key: Mapping[
        tuple[str, str, int, float, float, int, str], Mapping[str, Any]
    ],
    security_id: str,
    trading_date: str,
    config: CandidateConfig,
    reasons: list[str],
    statuses: list[str],
) -> None:
    for state_name, suffix in STATE_SUFFIX_BY_NAME.items():
        confirmation = confirmation_by_key.get(
            (
                security_id,
                trading_date,
                config.percentile_window_W,
                config.low_quantile_q,
                config.weak_delta,
                config.confirmation_days_K,
                state_name,
            )
        )
        if confirmation is None:
            row[f"streak_{suffix}"] = None
            row[f"{state_name}_conf"] = None
            row[f"confirmation_start_date_{suffix}"] = None
            row[f"confirmation_date_{suffix}"] = None
            reasons.append("missing_upstream_result")
            statuses.append(UNKNOWN)
            continue
        row[f"streak_{suffix}"] = confirmation.get("raw_streak")
        row[f"{state_name}_conf"] = confirmation.get("confirmed_state")
        row[f"confirmation_start_date_{suffix}"] = confirmation.get(
            "confirmation_start_date"
        )
        row[f"confirmation_date_{suffix}"] = confirmation.get("confirmation_date")
        statuses.append(str(confirmation.get("validity_status", UNKNOWN)))
        reasons.extend(str(reason) for reason in confirmation.get("reason_codes", ()))


def _quality_summary(
    daily_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
    configs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    config_ids = [str(config["candidate_config_id"]) for config in configs]
    row_count = Counter(str(row["candidate_config_id"]) for row in daily_rows)
    interval_count = Counter(str(row["candidate_config_id"]) for row in interval_rows)
    unknown_count = Counter(
        str(row["candidate_config_id"])
        for row in daily_rows
        if row.get("validity_state") == UNKNOWN
    )
    blocked_count = Counter(
        str(row["candidate_config_id"])
        for row in daily_rows
        if row.get("validity_state") == BLOCKED
    )
    open_interval_count = Counter(
        str(row["candidate_config_id"])
        for row in interval_rows
        if row.get("is_open_interval") is True
    )
    state_frequency: dict[str, dict[str, int]] = {}
    for config_id in config_ids:
        state_frequency[config_id] = dict(
            sorted(
                Counter(
                    str(row.get("exclusive_state_layer"))
                    for row in daily_rows
                    if row["candidate_config_id"] == config_id
                ).items()
            )
        )
    return {
        "row_count_by_config": _counter_for_configs(row_count, config_ids),
        "interval_count_by_config": _counter_for_configs(interval_count, config_ids),
        "unknown_count_by_config": _counter_for_configs(unknown_count, config_ids),
        "blocked_count_by_config": _counter_for_configs(blocked_count, config_ids),
        "state_frequency_by_config": state_frequency,
        "open_interval_count_by_config": _counter_for_configs(
            open_interval_count, config_ids
        ),
    }


def _field_availability(
    daily_rows: Sequence[Mapping[str, Any]],
    interval_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "daily_state_artifact": _availability_for_rows(
            daily_rows, DAILY_REQUIRED_FIELDS
        ),
        "interval_artifact": _availability_for_rows(
            interval_rows, INTERVAL_REQUIRED_FIELDS
        ),
    }


def _availability_for_rows(
    rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> dict[str, Any]:
    missing: dict[str, int] = {}
    unavailable: dict[str, int] = {}
    for field_name in fields:
        missing_count = sum(1 for row in rows if field_name not in row)
        none_count = sum(1 for row in rows if row.get(field_name) is None)
        if missing_count:
            missing[field_name] = missing_count
        if none_count:
            unavailable[field_name] = none_count
    return {
        "row_count": len(rows),
        "required_fields": list(fields),
        "missing_field_counts": missing,
        "null_field_counts": unavailable,
    }


def _candidate_security_dates(
    nested_by_key: Mapping[tuple[str, str, int, float, float], Mapping[str, Any]],
    confirmation_by_key: Mapping[
        tuple[str, str, int, float, float, int, str], Mapping[str, Any]
    ],
) -> tuple[tuple[str, str], ...]:
    pairs = {(key[0], key[1]) for key in nested_by_key}
    pairs.update((key[0], key[1]) for key in confirmation_by_key)
    return tuple(sorted(pairs))


def _index_latest(
    rows: Sequence[Mapping[str, Any] | Any], key_fn: Any
) -> dict[Any, dict[str, Any]]:
    indexed: dict[Any, dict[str, Any]] = {}
    for item in rows:
        row = _normalise_row(item)
        indexed[key_fn(row)] = row
    return indexed


def _raw_metric_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["security_id"]),
        str(row["trading_date"]),
        str(row["indicator_id"]),
    )


def _indicator_score_key(row: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(row["security_id"]),
        str(row["trading_date"]),
        int(row["percentile_window_W"]),
        str(row["indicator_id"]),
    )


def _dimension_score_key(row: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(row["security_id"]),
        str(row["trading_date"]),
        int(row["percentile_window_W"]),
        str(row["dimension"]),
    )


def _nested_state_key(row: Mapping[str, Any]) -> tuple[str, str, int, float, float]:
    return (
        str(row["security_id"]),
        str(row["trading_date"]),
        int(row["percentile_window_W"]),
        float(row["q"]),
        float(row["weak_delta"]),
    )


def _daily_confirmation_key(
    row: Mapping[str, Any],
) -> tuple[str, str, int, float, float, int, str]:
    return (
        str(row["security_id"]),
        str(row["trading_date"]),
        int(row["percentile_window_W"]),
        float(row["q"]),
        float(row["weak_delta"]),
        int(row["confirmation_k"]),
        str(row["state_name"]),
    )


def _normalise_row(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    if hasattr(row, "as_dict"):
        return dict(row.as_dict())
    return dict(row)


def _candidate_config_id(window: int, q: float, confirmation_k: int) -> str:
    return f"R0_W{window}_Q{int(round(q * 100)):02d}_K{confirmation_k}_WEAK_D010"


def _config_hash_payload(window: int, q: float, confirmation_k: int) -> dict[str, Any]:
    return {
        "percentile_window_W": window,
        "low_quantile_q": q,
        "confirmation_days_K": confirmation_k,
        "dimension_rule": DIMENSION_RULE,
        "weak_delta": WEAK_DELTA,
        "metric_variant_id": METRIC_VARIANT_ID,
        "state_definition_draft_version": STATE_DEFINITION_DRAFT_VERSION,
    }


def _hash_object(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(_canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _daily_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["candidate_config_id"]),
        str(row["security_id"]),
        str(row["trading_date"]),
    )


def _interval_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["candidate_config_id"]),
        str(row["security_id"]),
        str(row["confirmed_interval_id"]),
    )


def _combined_status(statuses: Sequence[str], reasons: Sequence[str]) -> str:
    if "missing_upstream_result" in reasons:
        return UNKNOWN
    if BLOCKED in statuses:
        return BLOCKED
    if DIAGNOSTIC_REQUIRED in statuses:
        return DIAGNOSTIC_REQUIRED
    if UNKNOWN in statuses:
        return UNKNOWN
    return VALID


def _unique_reasons(reasons: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for reason in reasons:
        if reason and reason not in seen:
            unique.append(reason)
            seen.add(reason)
    return unique


def _counter_for_configs(
    counter: Counter[str], config_ids: Sequence[str]
) -> dict[str, int]:
    return {config_id: int(counter.get(config_id, 0)) for config_id in config_ids}


def _all_true(values: Any) -> bool | None:
    items = list(values)
    if any(value is None for value in items):
        return None
    return all(value is True for value in items)


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(nested))
    elif isinstance(value, list | tuple):
        for nested in value:
            keys.extend(_walk_keys(nested))
    return keys


def _walk_keys_and_sequence_strings(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            values.append(str(key))
            values.extend(_walk_keys_and_sequence_strings(nested))
    elif isinstance(value, list | tuple):
        for nested in value:
            if isinstance(nested, str):
                values.append(nested)
            else:
                values.extend(_walk_keys_and_sequence_strings(nested))
    return values


def _lineage_sources(lineage: Mapping[str, Any] | Sequence[Any]) -> list[str]:
    if isinstance(lineage, Mapping):
        values = lineage.get("sources", lineage.get("input_sources", ()))
    else:
        values = lineage
    sources: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            source = str(value.get("source", ""))
            authorized = value.get("authorized_r0_upstream_manifest") is True
            if source and ("data/generated" not in source or not authorized):
                sources.append(source)
            elif source and authorized:
                sources.append("authorized_r0_upstream_manifest")
        else:
            sources.append(str(value))
    return sources


def _is_prohibited_source(source: str) -> bool:
    return any(pattern in source for pattern in PROHIBITED_SOURCES)


def _same_float(left: float, right: float) -> bool:
    return abs(left - right) < 1e-12
