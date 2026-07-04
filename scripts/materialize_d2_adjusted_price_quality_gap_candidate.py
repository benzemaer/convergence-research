"""Materialize local D2-T10 adjusted price, quality, and gap candidate artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT_PATH = (
    ROOT / "configs/d2/adjusted_price_quality_gap_candidate_contract.v1.json"
)
DEFAULT_SOURCE_REGISTRY_PATH = (
    ROOT / "configs/d2/formal_source_registry_contract.v1.json"
)

RAW_REQUIRED_FIELDS = [
    "data_version",
    "universe_id",
    "time_segment_id",
    "security_id",
    "trading_date",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "volume",
    "amount",
    "trading_status",
    "price_limit_status",
    "source_registry_id",
    "source_snapshot_id",
    "observed_at",
    "run_id",
]
ADJUSTED_FIELDS = [
    "data_version",
    "universe_id",
    "time_segment_id",
    "security_id",
    "trading_date",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adjustment_factor",
    "adjustment_method",
    "adjustment_event_source",
    "factor_as_of_time",
    "adjustment_revision",
    "history_revision_class",
    "source_registry_id",
    "source_snapshot_id",
    "observed_at",
    "run_id",
    "quality_status",
    "quality_blocking_flag",
    "quality_blocking_reasons",
]
QUALITY_FIELDS = [
    "data_version",
    "universe_id",
    "time_segment_id",
    "security_id",
    "trading_date",
    "raw_ohlc_integrity_status",
    "adjusted_ohlc_integrity_status",
    "raw_adjusted_reconciliation_status",
    "amount_volume_unit_status",
    "daily_vwap_range_status",
    "trading_status_readiness",
    "price_limit_status_readiness",
    "suspension_status_readiness",
    "st_status_readiness",
    "duplicate_key_status",
    "quality_blocking_flag",
    "quality_warning_flag",
    "quality_blocking_reasons",
    "quality_warning_reasons",
    "source_registry_id",
    "source_snapshot_id",
    "observed_at",
    "run_id",
]
GAP_FIELDS = [
    "data_version",
    "security_id",
    "trading_date",
    "previous_trading_date",
    "raw_prev_close",
    "raw_open",
    "raw_gap_ratio",
    "adj_prev_close",
    "adj_open",
    "adj_gap_ratio",
    "mechanical_gap_candidate_flag",
    "mechanical_gap_reason",
    "corporate_action_event_ref",
    "adjustment_factor_change",
    "gap_attribution_status",
    "source_registry_id",
    "source_snapshot_id",
    "observed_at",
    "run_id",
]
PROHIBITED_FIELDS = {
    "source_symbol",
    "thscode",
    "ts_code",
    "code",
    "vendor_payload",
    "raw_vendor_payload",
    "raw_rows",
    "qfq_rows",
    "hfq_rows",
    "future_return",
    "label",
    "pcvt_value",
    "pcvt_score",
    "pcvt_state",
    "state",
    "q_threshold",
    "backtest_signal",
    "portfolio_return",
    "trade",
    "order",
    "position",
}
FORBIDDEN_ANY_PATH_TOKENS = ("marketdb", ".duckdb", ".day")
FORBIDDEN_METADATA_TOKENS = ("data/raw", "data/external", ".parquet")
FORBIDDEN_OUTPUT_TOKENS = ("data/raw", "data/external")


class AdjustedPriceQualityGapMaterializationError(ValueError):
    """Raised when D2-T10 candidate materialization gates fail."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _normalize_path(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _guard_any_path(path: Path, label: str) -> None:
    normalized = _normalize_path(path)
    for token in FORBIDDEN_ANY_PATH_TOKENS:
        if token in normalized:
            raise AdjustedPriceQualityGapMaterializationError(
                f"{label} path is forbidden: {path}"
            )


def _guard_metadata_path(path: Path, label: str) -> None:
    _guard_any_path(path, label)
    normalized = _normalize_path(path)
    for token in FORBIDDEN_METADATA_TOKENS:
        if token in normalized:
            raise AdjustedPriceQualityGapMaterializationError(
                f"{label} path is forbidden: {path}"
            )


def _guard_output_dir(path: Path) -> None:
    _guard_any_path(path, "output-dir")
    normalized = _normalize_path(path)
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in normalized:
            raise AdjustedPriceQualityGapMaterializationError(
                f"output-dir is forbidden: {path}"
            )


def _parse_observed_at(value: str | None) -> str:
    if not value:
        raise AdjustedPriceQualityGapMaterializationError("source_observed_at required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdjustedPriceQualityGapMaterializationError(
            f"source_observed_at is not parseable: {value}"
        ) from exc
    if parsed.tzinfo is None:
        raise AdjustedPriceQualityGapMaterializationError(
            "source_observed_at must include timezone"
        )
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_run_id(raw_candidate_artifact: Path, observed_at: str) -> str:
    seed = (
        f"{raw_candidate_artifact}|{observed_at}|{_sha256_file(raw_candidate_artifact)}"
    )
    return "d2_t10_candidate_" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def _validate_contracts(contracts: dict[str, dict[str, Any]]) -> None:
    contract = contracts["contract"]
    source_registry = contracts["source_registry"]
    if (
        contract.get("contract_id")
        != "D2_ADJUSTED_PRICE_QUALITY_GAP_CANDIDATE_CONTRACT_V1"
    ):
        raise AdjustedPriceQualityGapMaterializationError("wrong D2-T10 contract")
    if contract.get("task_id") != "D2-T10":
        raise AdjustedPriceQualityGapMaterializationError("wrong D2-T10 task id")
    if source_registry.get("contract_id") != contract["source_registry_contract"]:
        raise AdjustedPriceQualityGapMaterializationError("source registry mismatch")
    if contract.get("local_candidate_artifact_write_authorized") is not True:
        raise AdjustedPriceQualityGapMaterializationError(
            "local candidate artifact write is not authorized"
        )
    for key in [
        "formal_source_acceptance_authorized",
        "formal_ingestion_authorized",
        "duckdb_write_authorized",
        "real_data_materialization_authorized",
        "manifest_creation_authorized",
        "data_version_release_authorized",
        "d3_generation_authorized",
        "r0_state_generation_authorized",
    ]:
        if contract.get(key) is not False:
            raise AdjustedPriceQualityGapMaterializationError(
                f"{key} must remain false"
            )


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return [dict(row) for row in loaded]
    if isinstance(loaded, dict) and isinstance(loaded.get("rows"), list):
        return [dict(row) for row in loaded["rows"]]
    raise AdjustedPriceQualityGapMaterializationError(f"expected rows: {path}")


def _read_raw_candidate_frame(path: Path) -> Any:
    if not path.exists():
        raise AdjustedPriceQualityGapMaterializationError(
            f"raw candidate artifact does not exist: {path}"
        )
    if path.suffix.lower() == ".parquet":
        import pandas as pd
        import pyarrow.parquet as pq

        available = set(pq.ParquetFile(path).schema.names)
        missing = sorted(set(RAW_REQUIRED_FIELDS) - available)
        if missing:
            raise AdjustedPriceQualityGapMaterializationError(
                f"raw candidate parquet missing fields: {', '.join(missing)}"
            )
        return pd.read_parquet(path, columns=RAW_REQUIRED_FIELDS)
    import pandas as pd

    frame = pd.DataFrame(_load_json_rows(path))
    missing = sorted(set(RAW_REQUIRED_FIELDS) - set(frame.columns))
    if missing:
        raise AdjustedPriceQualityGapMaterializationError(
            f"raw candidate rows missing fields: {', '.join(missing)}"
        )
    return frame


def _date_series(values: Any) -> Any:
    import pandas as pd

    text = values.astype(str)
    numeric = pd.to_numeric(values, errors="coerce")
    parsed_ms = pd.to_datetime(
        numeric.where(numeric > 10_000_000_000), unit="ms", errors="coerce"
    )
    parsed_yyyymmdd = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    parsed_general = pd.to_datetime(text, errors="coerce")
    return (
        parsed_ms.fillna(parsed_yyyymmdd)
        .fillna(parsed_general)
        .dt.strftime("%Y-%m-%d")
        .fillna(text)
    )


def _read_adjustment_frame(path: Path) -> Any:
    import pandas as pd

    if not path.exists():
        raise AdjustedPriceQualityGapMaterializationError(
            f"adjustment-events-path does not exist: {path}"
        )
    if path.suffix.lower() == ".parquet":
        raw = pd.read_parquet(path)
    else:
        raw = pd.DataFrame(_load_json_rows(path))
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "security_id",
                "trading_date",
                "adjustment_factor",
                "factor_as_of_time",
                "adjustment_revision",
                "corporate_action_event_ref",
            ]
        )
    security_col = "security_id" if "security_id" in raw.columns else None
    date_col = next(
        (
            col
            for col in ["trading_date", "event_date", "ex_date", "ex_date_ms"]
            if col in raw.columns
        ),
        None,
    )
    factor_col = next(
        (col for col in ["adjustment_factor", "factor"] if col in raw.columns),
        None,
    )
    frame = pd.DataFrame()
    if security_col and date_col:
        frame["security_id"] = raw[security_col].astype(str)
        frame["trading_date"] = _date_series(raw[date_col])
    else:
        return pd.DataFrame(
            columns=[
                "security_id",
                "trading_date",
                "adjustment_factor",
                "factor_as_of_time",
                "adjustment_revision",
                "corporate_action_event_ref",
            ]
        )
    frame["adjustment_factor"] = (
        pd.to_numeric(raw[factor_col], errors="coerce") if factor_col else None
    )
    frame["factor_as_of_time"] = (
        raw["factor_as_of_time"] if "factor_as_of_time" in raw else None
    )
    frame["adjustment_revision"] = (
        raw["adjustment_revision"] if "adjustment_revision" in raw else None
    )
    frame["corporate_action_event_ref"] = [
        f"hithink_adjustment_event:{sec}:{date}"
        for sec, date in zip(frame["security_id"], frame["trading_date"], strict=False)
    ]
    return frame.drop_duplicates(["security_id", "trading_date"], keep="last")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_frame_or_jsonl(
    path_base: Path, frame: Any, fields: list[str]
) -> tuple[Path, str]:
    parquet_path = path_base.with_suffix(".parquet")
    try:
        frame[fields].to_parquet(parquet_path, index=False)
        return parquet_path, "parquet"
    except Exception:
        jsonl_path = path_base.with_suffix(".jsonl")
        _write_jsonl(jsonl_path, frame[fields].to_dict("records"))
        return jsonl_path, "jsonl"


def _append_reason_column(frame: Any, reason: str, mask: Any) -> None:
    if bool(mask.any()):
        frame.loc[mask, "quality_blocking_reasons"] = frame.loc[
            mask, "quality_blocking_reasons"
        ].map(lambda reasons: [*reasons, reason])


def _quality_frames(
    raw: Any, adjustment: Any, observed_at: str, run_id: str
) -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any]]:
    import pandas as pd

    frame = raw.copy()
    for field in ["raw_open", "raw_high", "raw_low", "raw_close", "volume", "amount"]:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    merged = frame.merge(adjustment, on=["security_id", "trading_date"], how="left")
    merged["adjustment_factor"] = pd.to_numeric(
        merged["adjustment_factor"], errors="coerce"
    )
    missing_factor = merged["adjustment_factor"].isna()
    merged.loc[missing_factor, "adjustment_factor"] = 1.0
    for raw_field, adj_field in [
        ("raw_open", "adj_open"),
        ("raw_high", "adj_high"),
        ("raw_low", "adj_low"),
        ("raw_close", "adj_close"),
    ]:
        merged[adj_field] = merged[raw_field] * merged["adjustment_factor"]
    factor_asof_missing = merged["factor_as_of_time"].isna() | (
        merged["factor_as_of_time"].astype(str).str.strip() == ""
    )
    revision_missing = merged["adjustment_revision"].isna() | (
        merged["adjustment_revision"].astype(str).str.strip() == ""
    )
    merged["factor_as_of_time"] = merged["factor_as_of_time"].where(
        ~factor_asof_missing, None
    )
    merged["adjustment_revision"] = merged["adjustment_revision"].where(
        ~revision_missing, None
    )
    merged["adjustment_method"] = "forward_adjusted_candidate"
    merged["adjustment_event_source"] = "hithink_adjustment_events"
    merged.loc[missing_factor, "adjustment_event_source"] = "raw_equivalent_fallback"
    merged["history_revision_class"] = "final_revised_history"
    merged["run_id"] = run_id
    merged["observed_at"] = observed_at
    merged["quality_blocking_reasons"] = [[] for _ in range(len(merged))]

    raw_ohlc = merged[["raw_open", "raw_high", "raw_low", "raw_close"]]
    adj_ohlc = merged[["adj_open", "adj_high", "adj_low", "adj_close"]]
    raw_null_or_nonpositive = raw_ohlc.isna().any(axis=1) | (raw_ohlc <= 0).any(axis=1)
    adj_null_or_nonpositive = adj_ohlc.isna().any(axis=1) | (adj_ohlc <= 0).any(axis=1)
    raw_order_violation = (
        merged["raw_high"] < merged[["raw_open", "raw_close", "raw_low"]].max(axis=1)
    ) | (merged["raw_low"] > merged[["raw_open", "raw_close", "raw_high"]].min(axis=1))
    adj_order_violation = (
        merged["adj_high"] < merged[["adj_open", "adj_close", "adj_low"]].max(axis=1)
    ) | (merged["adj_low"] > merged[["adj_open", "adj_close", "adj_high"]].min(axis=1))
    null_volume = merged["volume"].isna()
    null_amount = merged["amount"].isna()
    duplicate_key = merged.duplicated(
        [
            "data_version",
            "universe_id",
            "time_segment_id",
            "security_id",
            "trading_date",
            "source_snapshot_id",
        ],
        keep=False,
    )
    unknown_trading = merged["trading_status"].fillna("unknown") == "unknown"
    unknown_limit = merged["price_limit_status"].fillna("unknown") == "unknown"

    _append_reason_column(
        merged, "adjustment_factor_missing_or_unresolved", missing_factor
    )
    _append_reason_column(merged, "factor_as_of_time_missing", factor_asof_missing)
    _append_reason_column(merged, "adjustment_revision_missing", revision_missing)
    _append_reason_column(
        merged,
        "adjustment_factor_direction_unverified",
        pd.Series(True, index=merged.index),
    )
    _append_reason_column(
        merged, "raw_ohlc_null_or_nonpositive", raw_null_or_nonpositive
    )
    _append_reason_column(
        merged, "adjusted_ohlc_null_or_nonpositive", adj_null_or_nonpositive
    )
    _append_reason_column(merged, "raw_ohlc_order_violation", raw_order_violation)
    _append_reason_column(merged, "adjusted_ohlc_order_violation", adj_order_violation)
    _append_reason_column(merged, "null_volume", null_volume)
    _append_reason_column(merged, "null_amount", null_amount)
    _append_reason_column(merged, "negative_volume", merged["volume"] < 0)
    _append_reason_column(merged, "negative_amount", merged["amount"] < 0)
    _append_reason_column(merged, "duplicate_key", duplicate_key)
    _append_reason_column(
        merged, "trading_status_unknown_blocks_d2_acceptance", unknown_trading
    )
    _append_reason_column(
        merged, "price_limit_status_unknown_blocks_d2_acceptance", unknown_limit
    )
    _append_reason_column(
        merged,
        "suspension_status_unknown_blocks_d2_acceptance",
        pd.Series(True, index=merged.index),
    )
    _append_reason_column(
        merged,
        "st_status_unknown_blocks_d2_acceptance",
        pd.Series(True, index=merged.index),
    )
    _append_reason_column(
        merged,
        "amount_volume_unit_unknown_blocks_d2_acceptance",
        pd.Series(True, index=merged.index),
    )
    merged["quality_blocking_flag"] = merged["quality_blocking_reasons"].map(bool)
    merged["quality_status"] = merged["quality_blocking_flag"].map(
        {True: "candidate_blocked", False: "candidate_passed"}
    )

    quality = pd.DataFrame(index=merged.index)
    for field in [
        "data_version",
        "universe_id",
        "time_segment_id",
        "security_id",
        "trading_date",
        "source_registry_id",
        "source_snapshot_id",
        "observed_at",
        "run_id",
    ]:
        quality[field] = merged[field]
    quality["raw_ohlc_integrity_status"] = "passed"
    quality.loc[
        raw_null_or_nonpositive | raw_order_violation, "raw_ohlc_integrity_status"
    ] = "blocked"
    quality["adjusted_ohlc_integrity_status"] = "passed"
    quality.loc[
        adj_null_or_nonpositive | adj_order_violation, "adjusted_ohlc_integrity_status"
    ] = "blocked"
    quality["raw_adjusted_reconciliation_status"] = "candidate_requires_review"
    quality["amount_volume_unit_status"] = "unknown"
    vwap = merged["amount"] / merged["volume"]
    quality["daily_vwap_range_status"] = "passed"
    quality.loc[
        merged["volume"].isna()
        | merged["amount"].isna()
        | (merged["volume"] <= 0)
        | (vwap < merged["raw_low"])
        | (vwap > merged["raw_high"]),
        "daily_vwap_range_status",
    ] = "unknown_or_blocked"
    quality["trading_status_readiness"] = "known"
    quality.loc[unknown_trading, "trading_status_readiness"] = "unknown_blocking"
    quality["price_limit_status_readiness"] = "known"
    quality.loc[unknown_limit, "price_limit_status_readiness"] = "unknown_blocking"
    quality["suspension_status_readiness"] = "unknown_blocking"
    quality["st_status_readiness"] = "unknown_blocking"
    quality["duplicate_key_status"] = "passed"
    quality.loc[duplicate_key, "duplicate_key_status"] = "blocked"
    quality["quality_blocking_flag"] = merged["quality_blocking_flag"]
    quality["quality_warning_flag"] = True
    quality["quality_blocking_reasons"] = merged["quality_blocking_reasons"]
    quality["quality_warning_reasons"] = [
        ["amount_volume_unit_unknown", "factor_direction_candidate_requires_review"]
        for _ in range(len(quality))
    ]

    ordered = merged.sort_values(["security_id", "trading_date"]).copy()
    ordered["previous_trading_date"] = ordered.groupby("security_id")[
        "trading_date"
    ].shift(1)
    ordered["raw_prev_close"] = ordered.groupby("security_id")["raw_close"].shift(1)
    ordered["adj_prev_close"] = ordered.groupby("security_id")["adj_close"].shift(1)
    ordered["previous_factor"] = ordered.groupby("security_id")[
        "adjustment_factor"
    ].shift(1)
    ordered["raw_gap_ratio"] = (ordered["raw_open"] / ordered["raw_prev_close"]) - 1.0
    ordered["adj_gap_ratio"] = (ordered["adj_open"] / ordered["adj_prev_close"]) - 1.0
    ordered["adjustment_factor_change"] = (
        ordered["adjustment_factor"] - ordered["previous_factor"]
    )
    gap = pd.DataFrame(index=ordered.index)
    for field in [
        "data_version",
        "security_id",
        "trading_date",
        "previous_trading_date",
        "raw_prev_close",
        "raw_open",
        "raw_gap_ratio",
        "adj_prev_close",
        "adj_open",
        "adj_gap_ratio",
        "adjustment_factor_change",
        "source_registry_id",
        "source_snapshot_id",
        "observed_at",
        "run_id",
    ]:
        gap[field] = ordered[field]
    factor_change = ordered["adjustment_factor_change"].abs().fillna(0) > 0
    raw_gap_large = ordered["raw_gap_ratio"].abs().fillna(0) >= 0.03
    adj_gap_smaller = ordered["adj_gap_ratio"].abs().fillna(999) < ordered[
        "raw_gap_ratio"
    ].abs().fillna(0)
    mechanical = raw_gap_large & adj_gap_smaller & factor_change
    gap["mechanical_gap_candidate_flag"] = mechanical
    gap["mechanical_gap_reason"] = "none"
    gap.loc[mechanical, "mechanical_gap_reason"] = "candidate_mechanical_gap"
    no_event = ordered["corporate_action_event_ref"].isna() | (
        ordered["corporate_action_event_ref"].astype(str).str.strip() == ""
    )
    gap["corporate_action_event_ref"] = ordered["corporate_action_event_ref"].where(
        ~no_event, None
    )
    gap["gap_attribution_status"] = "none"
    gap.loc[mechanical, "gap_attribution_status"] = "candidate_mechanical_gap"
    gap.loc[raw_gap_large & no_event, "gap_attribution_status"] = (
        "unknown_or_unverified"
    )
    gap.loc[raw_gap_large & no_event, "mechanical_gap_reason"] = (
        "missing_adjustment_event_gap_unknown"
    )

    dates = sorted(merged["trading_date"].dropna().astype(str).tolist())
    reconciliation_reasons = sorted(
        {
            reason
            for reasons in merged["quality_blocking_reasons"]
            for reason in reasons
            if reason
            in {
                "adjustment_factor_missing_or_unresolved",
                "factor_as_of_time_missing",
                "adjustment_revision_missing",
                "adjustment_factor_direction_unverified",
            }
        }
    )
    reconciliation = {
        "row_count_raw_candidate": int(len(raw)),
        "row_count_adjusted_candidate": int(len(merged)),
        "security_count_raw_candidate": int(raw["security_id"].nunique()),
        "security_count_adjusted_candidate": int(merged["security_id"].nunique()),
        "trading_date_min": dates[0] if dates else None,
        "trading_date_max": dates[-1] if dates else None,
        "missing_adjustment_factor_count": int(missing_factor.sum()),
        "factor_as_of_time_missing_count": int(factor_asof_missing.sum()),
        "adjustment_revision_missing_count": int(revision_missing.sum()),
        "adjustment_factor_direction_unverified_count": int(len(merged)),
        "raw_adjusted_row_mismatch_count": int(len(raw) - len(merged)),
        "candidate_blocking_flag": True,
        "candidate_blocking_reasons": reconciliation_reasons,
    }
    readiness_reasons = []
    if bool(unknown_trading.any()):
        readiness_reasons.append("trading_status_unknown_blocks_d2_acceptance")
    if bool(unknown_limit.any()):
        readiness_reasons.append("price_limit_status_unknown_blocks_d2_acceptance")
    readiness_reasons.extend(
        [
            "suspension_status_unknown_blocks_d2_acceptance",
            "st_status_unknown_blocks_d2_acceptance",
        ]
    )
    readiness = {
        "trading_status_known_count": int((~unknown_trading).sum()),
        "trading_status_unknown_count": int(unknown_trading.sum()),
        "price_limit_status_known_count": int((~unknown_limit).sum()),
        "price_limit_status_unknown_count": int(unknown_limit.sum()),
        "suspension_status_known_count": 0,
        "suspension_status_unknown_count": int(len(merged)),
        "st_status_known_count": 0,
        "st_status_unknown_count": int(len(merged)),
        "limit_price_known_count": int((~unknown_limit).sum()),
        "limit_price_unknown_count": int(unknown_limit.sum()),
        "readiness_blocking_flag": True,
        "readiness_blocking_reasons": readiness_reasons,
        "recommended_next_source_probe": (
            "D2-T11 source status resolution for trading calendar, suspension, "
            "ST, and limit-price states"
        ),
    }
    return (
        merged[ADJUSTED_FIELDS],
        quality[QUALITY_FIELDS],
        gap[GAP_FIELDS],
        reconciliation,
        readiness,
    )


def _file_hash_summary(paths: dict[str, Path]) -> dict[str, Any]:
    return {
        name: {
            "path": str(path),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for name, path in paths.items()
    }


def materialize_adjusted_price_quality_gap_candidate(
    raw_candidate_artifact: Path,
    raw_candidate_quality_summary: dict[str, Any],
    adjustment_events_path: Path,
    probe_report: dict[str, Any],
    contracts: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    _validate_contracts(contracts)
    observed_at = _parse_observed_at(params.get("source_observed_at"))
    output_dir = Path(params["output_dir"])
    _guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = params.get("run_id") or _stable_run_id(raw_candidate_artifact, observed_at)

    raw_frame = _read_raw_candidate_frame(raw_candidate_artifact)
    for field in PROHIBITED_FIELDS:
        if field in raw_frame.columns:
            raise AdjustedPriceQualityGapMaterializationError(
                f"raw candidate contains prohibited field: {field}"
            )
    adjustment_frame = _read_adjustment_frame(adjustment_events_path)
    adjusted, quality, gap, reconciliation, readiness = _quality_frames(
        raw_frame, adjustment_frame, observed_at, run_id
    )
    artifact_path, artifact_format = _write_frame_or_jsonl(
        output_dir / "adjusted_market_prices_candidate", adjusted, ADJUSTED_FIELDS
    )
    quality_path, quality_format = _write_frame_or_jsonl(
        output_dir / "market_price_quality_flags_candidate", quality, QUALITY_FIELDS
    )
    gap_path, gap_format = _write_frame_or_jsonl(
        output_dir / "mechanical_gap_attribution_candidate", gap, GAP_FIELDS
    )
    readiness_path = output_dir / "trading_constraint_readiness_candidate.json"
    reconciliation_path = output_dir / "raw_adjusted_reconciliation_candidate.json"
    report_path = output_dir / "adjusted_price_quality_gap_materialization_report.json"
    _write_json(readiness_path, readiness)
    _write_json(reconciliation_path, reconciliation)
    report = {
        "status": "candidate_blocked",
        "contract_id": contracts["contract"]["contract_id"],
        "raw_candidate_quality_blocking_flag": raw_candidate_quality_summary.get(
            "candidate_blocking_flag"
        ),
        "probe_report_status": probe_report.get("status", "summary_only"),
        "artifact_format": artifact_format,
        "quality_format": quality_format,
        "gap_format": gap_format,
        "row_count_adjusted_candidate": reconciliation["row_count_adjusted_candidate"],
        "quality_blocking_flag": True,
        "quality_blocking_reasons": sorted(
            {
                reason
                for reasons in adjusted["quality_blocking_reasons"]
                for reason in reasons
            }
        ),
        "duckdb_written": False,
        "accepted_manifest_created": False,
        "data_version_published": False,
        "d3_artifact_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }
    _write_json(report_path, report)
    hash_paths = {
        "adjusted_market_prices_candidate": artifact_path,
        "market_price_quality_flags_candidate": quality_path,
        "mechanical_gap_attribution_candidate": gap_path,
        "trading_constraint_readiness_candidate": readiness_path,
        "raw_adjusted_reconciliation_candidate": reconciliation_path,
        "adjusted_price_quality_gap_materialization_report": report_path,
    }
    hash_summary = _file_hash_summary(hash_paths)
    hash_path = output_dir / "candidate_file_hash_summary.json"
    _write_json(hash_path, hash_summary)
    return {
        "status": "candidate_blocked",
        "adjusted_market_prices_candidate": str(artifact_path),
        "market_price_quality_flags_candidate": str(quality_path),
        "mechanical_gap_attribution_candidate": str(gap_path),
        "trading_constraint_readiness_candidate": str(readiness_path),
        "raw_adjusted_reconciliation_candidate": str(reconciliation_path),
        "adjusted_price_quality_gap_materialization_report": str(report_path),
        "candidate_file_hash_summary": str(hash_path),
        "reconciliation_summary": reconciliation,
        "trading_constraint_readiness": readiness,
        "file_hash_summary": hash_summary,
        "duckdb_written": False,
        "accepted_manifest_created": False,
        "data_version_published": False,
        "d3_artifact_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT_PATH, type=Path)
    parser.add_argument(
        "--source-registry", default=DEFAULT_SOURCE_REGISTRY_PATH, type=Path
    )
    parser.add_argument("--raw-candidate-artifact", required=True, type=Path)
    parser.add_argument("--raw-candidate-quality-summary", required=True, type=Path)
    parser.add_argument("--adjustment-events-path", required=True, type=Path)
    parser.add_argument("--probe-report", required=True, type=Path)
    parser.add_argument("--source-observed-at", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _guard_any_path(args.raw_candidate_artifact, "raw-candidate-artifact")
    _guard_metadata_path(
        args.raw_candidate_quality_summary, "raw-candidate-quality-summary"
    )
    _guard_any_path(args.adjustment_events_path, "adjustment-events-path")
    _guard_metadata_path(args.probe_report, "probe-report")
    _guard_output_dir(args.output_dir)
    report = materialize_adjusted_price_quality_gap_candidate(
        raw_candidate_artifact=args.raw_candidate_artifact,
        raw_candidate_quality_summary=_load_json(args.raw_candidate_quality_summary),
        adjustment_events_path=args.adjustment_events_path,
        probe_report=_load_json(args.probe_report),
        contracts={
            "contract": _load_json(args.contract),
            "source_registry": _load_json(args.source_registry),
        },
        params={
            "source_observed_at": args.source_observed_at,
            "output_dir": args.output_dir,
        },
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
