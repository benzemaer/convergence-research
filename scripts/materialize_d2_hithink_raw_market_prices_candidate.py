"""Materialize local D2-T09 HiThink raw market prices candidate artifacts."""

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
    ROOT / "configs/d2/hithink_raw_market_prices_candidate_artifact_contract.v1.json"
)
DEFAULT_SOURCE_REGISTRY_PATH = (
    ROOT / "configs/d2/formal_source_registry_contract.v1.json"
)
DEFAULT_PROBE_CONTRACT_PATH = (
    ROOT / "configs/d2/hithink_raw_ohlcv_probe_contract.v1.json"
)
DEFAULT_PLAN_CONTRACT_PATH = (
    ROOT
    / "configs/d2/hithink_raw_market_prices_candidate_materialization_contract.v1.json"
)

TARGET_FIELDS = [
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
RAW_REQUIRED_SEMANTIC_FIELDS = [
    "security_code_or_thscode",
    "trading_date",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "volume",
    "amount",
]
PROHIBITED_ROW_FIELDS = {
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
    "backtest_signal",
    "portfolio_return",
}
FORBIDDEN_METADATA_INPUT_TOKENS = (
    "data/raw",
    "data/external",
    "marketdb",
    ".parquet",
    ".duckdb",
    ".day",
)
FORBIDDEN_OUTPUT_TOKENS = ("data/raw", "data/external")


class CandidateArtifactMaterializationError(ValueError):
    """Raised when candidate artifact materialization gates fail."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return [dict(row) for row in loaded]
    if isinstance(loaded, dict) and isinstance(loaded.get("rows"), list):
        return [dict(row) for row in loaded["rows"]]
    raise CandidateArtifactMaterializationError(
        f"expected row list JSON payload: {path}"
    )


def _normalize_path(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _reject_forbidden_metadata_input_path(path: Path, label: str) -> None:
    normalized = _normalize_path(path)
    for token in FORBIDDEN_METADATA_INPUT_TOKENS:
        if token in normalized:
            raise CandidateArtifactMaterializationError(
                f"{label} path is forbidden for stage 3: {path}"
            )


def _reject_forbidden_output_dir(path: Path) -> None:
    normalized = _normalize_path(path)
    for token in FORBIDDEN_OUTPUT_TOKENS:
        if token in normalized:
            raise CandidateArtifactMaterializationError(
                f"output-dir is forbidden for stage 3: {path}"
            )


def _parse_observed_at(value: str | None) -> str:
    if not value:
        raise CandidateArtifactMaterializationError(
            "source_observed_at is required and must not be derived from trading_date"
        )
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateArtifactMaterializationError(
            f"source_observed_at is not parseable: {value}"
        ) from exc
    if parsed.tzinfo is None:
        raise CandidateArtifactMaterializationError(
            "source_observed_at must include timezone"
        )
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_run_id(raw_k_path: Path, observed_at: str) -> str:
    seed = f"{raw_k_path}|{observed_at}|{_sha256_file(raw_k_path)}"
    return "d2_t09_candidate_" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def _load_raw_rows(path: Path, columns: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        raise CandidateArtifactMaterializationError(
            f"explicit raw-k-path does not exist: {path}"
        )
    if path.suffix.lower() in {".json", ".jsonl"}:
        return _load_json_rows(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    try:
        import pandas as pd

        frame = pd.read_parquet(path, columns=list(dict.fromkeys(columns)))
        return frame.to_dict(orient="records")
    except Exception as exc:
        raise CandidateArtifactMaterializationError(
            "raw-k-path must be explicit JSON/CSV or readable parquet"
        ) from exc


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_artifact(path_base: Path, rows: list[dict[str, Any]]) -> tuple[Path, str]:
    parquet_path = path_base.with_suffix(".parquet")
    try:
        import pandas as pd

        pd.DataFrame(rows, columns=TARGET_FIELDS).to_parquet(parquet_path, index=False)
        return parquet_path, "parquet"
    except Exception:
        jsonl_path = path_base.with_suffix(".jsonl")
        _write_jsonl(jsonl_path, rows)
        return jsonl_path, "jsonl"


def _validate_contracts(contracts: dict[str, dict[str, Any]]) -> None:
    contract = contracts["artifact_contract"]
    source_registry = contracts["source_registry"]
    probe_contract = contracts["probe_contract"]
    plan_contract = contracts["plan_contract"]
    artifact_contract_id = "D2_HITHINK_RAW_MARKET_PRICES_CANDIDATE_ARTIFACT_CONTRACT_V1"
    expected = {
        "artifact_contract": artifact_contract_id,
        "source_registry": contract["formal_source_registry_contract"],
        "probe_contract": contract["raw_ohlcv_probe_contract"],
        "plan_contract": contract["candidate_materialization_plan_contract"],
    }
    actual = {
        "artifact_contract": contract.get("contract_id"),
        "source_registry": source_registry.get("contract_id"),
        "probe_contract": probe_contract.get("contract_id"),
        "plan_contract": plan_contract.get("contract_id"),
    }
    for label, contract_id in expected.items():
        if actual[label] != contract_id:
            raise CandidateArtifactMaterializationError(
                f"{label} contract mismatch: {actual[label]}"
            )
    if contract.get("local_candidate_artifact_write_authorized") is not True:
        raise CandidateArtifactMaterializationError(
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
            raise CandidateArtifactMaterializationError(f"{key} must remain false")
    if source_registry["source_hierarchy"]["primary_source"]["source_id"] != (
        "hithink_financial_api"
    ):
        raise CandidateArtifactMaterializationError(
            "HiThink must remain primary source"
        )


def _resolved_raw_fields(probe_report: dict[str, Any]) -> dict[str, str]:
    resolved = probe_report["raw_k_schema_report"]["resolved_fields"]
    missing = [field for field in RAW_REQUIRED_SEMANTIC_FIELDS if field not in resolved]
    if missing:
        joined = ", ".join(missing)
        raise CandidateArtifactMaterializationError(
            f"missing raw required fields; fallback repair required: {joined}"
        )
    return dict(resolved)


def _load_security_mapping(rows: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in rows:
        if row.get("mapping_status") == "accepted":
            source_symbol = row.get("source_symbol")
            security_id = row.get("security_id")
            if source_symbol and security_id:
                mapping[str(source_symbol)] = str(security_id)
    return mapping


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _candidate_rows(
    raw_rows: list[dict[str, Any]],
    resolved: dict[str, str],
    security_mapping: dict[str, str],
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    output_rows: list[dict[str, Any]] = []
    dropped = 0
    for raw in raw_rows:
        source_symbol = str(raw.get(resolved["security_code_or_thscode"], ""))
        security_id = security_mapping.get(source_symbol)
        if not security_id:
            dropped += 1
            continue
        row = {
            "data_version": params["data_version"],
            "universe_id": params["universe_id"],
            "time_segment_id": params["time_segment_id"],
            "security_id": security_id,
            "trading_date": _date_text(raw.get(resolved["trading_date"])),
            "raw_open": _to_float(raw.get(resolved["raw_open"])),
            "raw_high": _to_float(raw.get(resolved["raw_high"])),
            "raw_low": _to_float(raw.get(resolved["raw_low"])),
            "raw_close": _to_float(raw.get(resolved["raw_close"])),
            "volume": _to_float(raw.get(resolved["volume"])),
            "amount": _to_float(raw.get(resolved["amount"])),
            "trading_status": raw.get("trading_status") or "unknown",
            "price_limit_status": raw.get("price_limit_status") or "unknown",
            "source_registry_id": "hithink_financial_api",
            "source_snapshot_id": params["source_snapshot_id"],
            "observed_at": params["observed_at"],
            "run_id": params["run_id"],
        }
        extra = set(row) - set(TARGET_FIELDS)
        prohibited = set(row) & PROHIBITED_ROW_FIELDS
        if extra or prohibited:
            raise CandidateArtifactMaterializationError(
                "candidate row contains non-target or prohibited fields"
            )
        output_rows.append({field: row[field] for field in TARGET_FIELDS})
    return output_rows, dropped


def _quality_summary(
    input_count: int,
    rows: list[dict[str, Any]],
    dropped_unmapped: int,
) -> dict[str, Any]:
    null_ohlc = 0
    nonpositive_ohlc = 0
    order_violation = 0
    negative_volume = 0
    negative_amount = 0
    for row in rows:
        values = [
            row[field] for field in ["raw_open", "raw_high", "raw_low", "raw_close"]
        ]
        if any(value is None for value in values):
            null_ohlc += 1
            continue
        raw_open, raw_high, raw_low, raw_close = values
        if any(value <= 0 for value in values):
            nonpositive_ohlc += 1
        if raw_high < max(raw_open, raw_close, raw_low):
            order_violation += 1
        if raw_low > min(raw_open, raw_close, raw_high):
            order_violation += 1
        if row["volume"] is not None and row["volume"] < 0:
            negative_volume += 1
        if row["amount"] is not None and row["amount"] < 0:
            negative_amount += 1
    key_counts: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = (
            row["data_version"],
            row["universe_id"],
            row["time_segment_id"],
            row["security_id"],
            row["trading_date"],
            row["source_snapshot_id"],
        )
        key_counts[key] = key_counts.get(key, 0) + 1
    duplicate_key_count = sum(count - 1 for count in key_counts.values() if count > 1)
    reasons = []
    if null_ohlc:
        reasons.append("null_ohlc")
    if nonpositive_ohlc:
        reasons.append("nonpositive_ohlc")
    if order_violation:
        reasons.append("ohlc_order_violation")
    if negative_volume:
        reasons.append("negative_volume")
    if negative_amount:
        reasons.append("negative_amount")
    if duplicate_key_count:
        reasons.append("duplicate_key")
    unknown_trading = sum(1 for row in rows if row["trading_status"] == "unknown")
    unknown_limit = sum(1 for row in rows if row["price_limit_status"] == "unknown")
    if unknown_trading or unknown_limit:
        reasons.append("unknown_status_blocks_future_d2_acceptance")
    dates = sorted(row["trading_date"] for row in rows if row["trading_date"])
    return {
        "row_count_input": input_count,
        "row_count_output": len(rows),
        "dropped_unmapped_security_count": dropped_unmapped,
        "security_count_output": len({row["security_id"] for row in rows}),
        "trading_date_min": dates[0] if dates else None,
        "trading_date_max": dates[-1] if dates else None,
        "null_ohlc_count": null_ohlc,
        "nonpositive_ohlc_count": nonpositive_ohlc,
        "ohlc_order_violation_count": order_violation,
        "negative_volume_count": negative_volume,
        "negative_amount_count": negative_amount,
        "unknown_trading_status_count": unknown_trading,
        "unknown_price_limit_status_count": unknown_limit,
        "duplicate_key_count": duplicate_key_count,
        "candidate_blocking_flag": bool(reasons),
        "candidate_blocking_reasons": reasons,
    }


def _file_hash_summary(paths: dict[str, Path]) -> dict[str, Any]:
    return {
        name: {
            "path": str(path),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for name, path in paths.items()
    }


def materialize_hithink_raw_market_prices_candidate(
    raw_k_path: Path,
    probe_report: dict[str, Any],
    security_mapping: dict[str, Any],
    contracts: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    _validate_contracts(contracts)
    observed_at = _parse_observed_at(params.get("source_observed_at"))
    raw_hash = _sha256_file(raw_k_path)
    run_id = params.get("run_id") or _stable_run_id(raw_k_path, observed_at)
    source_snapshot_id = "candidate_local_snapshot_" + raw_hash[:16]
    data_version = "D2_T09_HITHINK_RAW_CANDIDATE_" + run_id
    output_dir = Path(params["output_dir"])
    _reject_forbidden_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved = _resolved_raw_fields(probe_report)
    columns = list(resolved.values())
    for optional_field in ["trading_status", "price_limit_status"]:
        if optional_field not in columns:
            columns.append(optional_field)
    raw_rows = _load_raw_rows(raw_k_path, columns)
    mapping_rows = security_mapping.get("rows", security_mapping)
    if not isinstance(mapping_rows, list):
        raise CandidateArtifactMaterializationError(
            "security mapping must be a row list"
        )
    mapping = _load_security_mapping([dict(row) for row in mapping_rows])
    candidate_params = {
        "data_version": data_version,
        "universe_id": params["universe_id"],
        "time_segment_id": params["time_segment_id"],
        "source_snapshot_id": source_snapshot_id,
        "observed_at": observed_at,
        "run_id": run_id,
    }
    candidate_rows, dropped = _candidate_rows(
        raw_rows, resolved, mapping, candidate_params
    )
    quality = _quality_summary(len(raw_rows), candidate_rows, dropped)
    artifact_path, artifact_format = _write_artifact(
        output_dir / "candidate_raw_market_prices", candidate_rows
    )
    materialization_report = {
        "status": "candidate_blocked"
        if quality["candidate_blocking_flag"]
        else "candidate_created",
        "contract_id": contracts["artifact_contract"]["contract_id"],
        "target_table": "d1.raw_market_prices",
        "artifact_format": artifact_format,
        "artifact_path": str(artifact_path),
        "row_count_output": quality["row_count_output"],
        "formal_source_acceptance_authorized": False,
        "formal_ingestion_authorized": False,
        "duckdb_written": False,
        "accepted_manifest_created": False,
        "data_version_published": False,
        "d3_artifact_generated": False,
        "r0_state_generated": False,
    }
    quality_path = output_dir / "candidate_quality_summary.json"
    report_path = output_dir / "candidate_materialization_report.json"
    _write_json(quality_path, quality)
    _write_json(report_path, materialization_report)
    hash_paths = {
        "candidate_raw_market_prices_artifact": artifact_path,
        "candidate_quality_summary": quality_path,
        "candidate_materialization_report": report_path,
    }
    hash_summary = _file_hash_summary(hash_paths)
    hash_path = output_dir / "candidate_file_hash_summary.json"
    _write_json(hash_path, hash_summary)
    return {
        "status": materialization_report["status"],
        "candidate_raw_market_prices_artifact": str(artifact_path),
        "candidate_quality_summary": str(quality_path),
        "candidate_materialization_report": str(report_path),
        "candidate_file_hash_summary": str(hash_path),
        "artifact_format": artifact_format,
        "quality_summary": quality,
        "file_hash_summary": hash_summary,
        "duckdb_written": False,
        "accepted_manifest_created": False,
        "data_version_published": False,
        "d3_artifact_generated": False,
        "r0_state_generated": False,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT_PATH, type=Path)
    parser.add_argument(
        "--source-registry", default=DEFAULT_SOURCE_REGISTRY_PATH, type=Path
    )
    parser.add_argument(
        "--probe-contract", default=DEFAULT_PROBE_CONTRACT_PATH, type=Path
    )
    parser.add_argument(
        "--plan-contract", default=DEFAULT_PLAN_CONTRACT_PATH, type=Path
    )
    parser.add_argument("--raw-k-path", required=True, type=Path)
    parser.add_argument("--probe-report", required=True, type=Path)
    parser.add_argument("--security-mapping", required=True, type=Path)
    parser.add_argument("--universe-id", required=True)
    parser.add_argument("--time-segment-id", required=True)
    parser.add_argument("--source-observed-at", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _reject_forbidden_metadata_input_path(args.probe_report, "probe-report")
    _reject_forbidden_metadata_input_path(args.security_mapping, "security-mapping")
    _reject_forbidden_output_dir(args.output_dir)
    report = materialize_hithink_raw_market_prices_candidate(
        raw_k_path=args.raw_k_path,
        probe_report=_load_json(args.probe_report),
        security_mapping=_load_json(args.security_mapping),
        contracts={
            "artifact_contract": _load_json(args.contract),
            "source_registry": _load_json(args.source_registry),
            "probe_contract": _load_json(args.probe_contract),
            "plan_contract": _load_json(args.plan_contract),
        },
        params={
            "universe_id": args.universe_id,
            "time_segment_id": args.time_segment_id,
            "source_observed_at": args.source_observed_at,
            "output_dir": args.output_dir,
        },
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
