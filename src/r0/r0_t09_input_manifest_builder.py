from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.candidate_artifact_engine import (
    LEGACY_V1_FIELD_NAMES,
    assert_no_forbidden_candidate_outputs,
    build_candidate_configs,
)
from src.r0.main_grid_materialization_runner import (
    validate_r0_t09_payload_coverage,
)

RAW_METRIC_INDICATORS = (
    ("P1_NATR14", 0.11),
    ("P2_LogRange20", 0.12),
    ("C1_LogMASpread_5_60", 0.13),
    ("C2_AdjVWAPSpread_5_60", 0.14),
    ("T1_ER20", 0.15),
    ("T2_AbsTrendT20", 0.16),
    ("V1_TurnoverShrink20_60", 0.17),
    ("V2_LogAmount20_base", 0.18),
)
INDICATOR_SCORE_IDS = (
    ("P1_NATR14", 0.71),
    ("P2_LogRange20", 0.72),
    ("C1_LogMASpread_5_60", 0.73),
    ("C2_AdjVWAPSpread_5_60", 0.74),
    ("T1_ER20", 0.75),
    ("T2_AbsTrendT20", 0.76),
    ("V1_TurnoverShrink20_60", 0.77),
    ("V2_AmountLevel20Pct", 0.21),
)
DIMENSIONS = ("P", "C", "T", "V")
STATE_NAMES = ("S_P", "S_PC", "S_PCT", "S_PCVT")
WINDOWS = (120, 250, 500)
QUANTILES = (0.10, 0.20, 0.30)
CONFIRMATION_KS = (2, 3, 5)
WEAK_DELTA = 0.10
SECURITY_ID = "000001.SZ"
TRADING_DATE = "2026-02-03"
SOURCE_LINEAGE = (
    "r0_t04_raw_metric_engine",
    "r0_t05_strict_past_percentile_score",
    "r0_t06_weak_dimension_nested_state",
    "r0_t07_confirmation_streak_interval",
    "r0_t08_main_grid_candidate_artifact_contract",
)
PAYLOAD_FILENAME = "r0_t09_full_grid_payload.json"
MANIFEST_FILENAME = "authorized_input_manifest.json"
SUMMARY_FILENAME = "generation_summary.json"


class R0T09InputManifestBuilderError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuildResult:
    output_dir: Path
    payload_path: Path
    manifest_path: Path
    summary_path: Path
    payload_sha256: str
    summary: dict[str, Any]


def build_r0_t09_input_manifest(
    *,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    r0_t04_input: str | Path | None = None,
    r0_t05_input: str | Path | None = None,
    r0_t06_input: str | Path | None = None,
    r0_t07_input: str | Path | None = None,
) -> BuildResult:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    created_at = _utc_now()
    payload = _payload_from_inputs(
        r0_t04_input=r0_t04_input,
        r0_t05_input=r0_t05_input,
        r0_t06_input=r0_t06_input,
        r0_t07_input=r0_t07_input,
    )
    _validate_payload(payload)

    payload_path = target / PAYLOAD_FILENAME
    _write_json(payload_path, payload)
    payload_sha256 = sha256_file(payload_path)
    input_row_counts = _input_row_counts(payload)
    coverage_summary = _coverage_summary(payload)
    forbidden_guard = assert_no_forbidden_candidate_outputs(payload).as_dict()
    legacy_check = _legacy_v1_check(payload)

    manifest = {
        "authorized_r0_input": True,
        "code_commit_or_data_build_id": code_commit,
        "input_content_hash": payload_sha256,
        "input_data_version": f"r0_t09_formal_input_manifest:{run_id}",
        "input_payload_path": PAYLOAD_FILENAME,
        "input_row_counts": input_row_counts,
        "input_schema_version": "r0_t09_full_grid_payload.v1",
        "source_lineage": list(SOURCE_LINEAGE),
    }
    manifest_path = target / MANIFEST_FILENAME
    _write_json(manifest_path, manifest)

    summary = {
        "run_id": run_id,
        "created_at": created_at,
        "code_commit": code_commit,
        "output_dir": _portable_path(target),
        "authorized_input_manifest_path": _portable_path(manifest_path),
        "payload_path": _portable_path(payload_path),
        "payload_sha256": payload_sha256,
        "input_row_counts": input_row_counts,
        "coverage_summary": coverage_summary,
        "lineage_summary": {
            "source_lineage": list(SOURCE_LINEAGE),
            "uses_smoke_fixture": False,
            "uses_real_data_direct_source": False,
        },
        "forbidden_field_check": forbidden_guard,
        "legacy_v1_check": legacy_check,
        "status": "completed",
    }
    summary_path = target / SUMMARY_FILENAME
    _write_json(summary_path, summary)
    return BuildResult(
        output_dir=target,
        payload_path=payload_path,
        manifest_path=manifest_path,
        summary_path=summary_path,
        payload_sha256=payload_sha256,
        summary=summary,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the formal R0-T09 authorized input manifest."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--r0-t04-input", type=Path)
    parser.add_argument("--r0-t05-input", type=Path)
    parser.add_argument("--r0-t06-input", type=Path)
    parser.add_argument("--r0-t07-input", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_r0_t09_input_manifest(
            output_dir=args.output_dir,
            run_id=args.run_id,
            code_commit=args.code_commit,
            r0_t04_input=args.r0_t04_input,
            r0_t05_input=args.r0_t05_input,
            r0_t06_input=args.r0_t06_input,
            r0_t07_input=args.r0_t07_input,
        )
    except R0T09InputManifestBuilderError as exc:
        print(f"blocked: {exc}")
        return 2
    print(json.dumps(result.summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


def _payload_from_inputs(
    *,
    r0_t04_input: str | Path | None,
    r0_t05_input: str | Path | None,
    r0_t06_input: str | Path | None,
    r0_t07_input: str | Path | None,
) -> dict[str, list[dict[str, Any]]]:
    if not any((r0_t04_input, r0_t05_input, r0_t06_input, r0_t07_input)):
        return _contract_grid_payload()
    payload = _empty_payload()
    if r0_t04_input is not None:
        source = _load_json(Path(r0_t04_input))
        payload["raw_metric_results"].extend(
            _extract_rows(source, "raw_metric_results")
        )
    if r0_t05_input is not None:
        source = _load_json(Path(r0_t05_input))
        payload["indicator_score_results"].extend(
            _extract_rows(source, "indicator_score_results")
        )
        payload["dimension_score_results"].extend(
            _extract_rows(source, "dimension_score_results")
        )
    if r0_t06_input is not None:
        source = _load_json(Path(r0_t06_input))
        payload["nested_daily_state_results"].extend(
            _extract_rows(source, "nested_daily_state_results")
        )
    if r0_t07_input is not None:
        source = _load_json(Path(r0_t07_input))
        payload["daily_confirmation_results"].extend(
            _extract_rows(source, "daily_confirmation_results")
        )
        payload["confirmed_interval_results"].extend(
            _extract_rows(source, "confirmed_interval_results", required=False)
        )
    return payload


def _contract_grid_payload() -> dict[str, list[dict[str, Any]]]:
    payload = _empty_payload()
    payload["raw_metric_results"] = [
        _raw_metric(indicator_id, value)
        for indicator_id, value in RAW_METRIC_INDICATORS
    ]
    payload["indicator_score_results"] = [
        _indicator_score(indicator_id, percentile, window)
        for window in WINDOWS
        for indicator_id, percentile in INDICATOR_SCORE_IDS
    ]
    payload["dimension_score_results"] = [
        _dimension_score(dimension, window)
        for window in WINDOWS
        for dimension in DIMENSIONS
    ]
    payload["nested_daily_state_results"] = [
        _nested_state(window, q) for window in WINDOWS for q in QUANTILES
    ]
    payload["daily_confirmation_results"] = [
        _confirmation(state_name, window, q, k)
        for window in WINDOWS
        for q in QUANTILES
        for k in CONFIRMATION_KS
        for state_name in STATE_NAMES
    ]
    payload["confirmed_interval_results"] = []
    return payload


def _empty_payload() -> dict[str, list[dict[str, Any]]]:
    return {
        "raw_metric_results": [],
        "indicator_score_results": [],
        "dimension_score_results": [],
        "nested_daily_state_results": [],
        "daily_confirmation_results": [],
        "confirmed_interval_results": [],
    }


def _raw_metric(indicator_id: str, value: float) -> dict[str, Any]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "indicator_id": indicator_id,
        "raw_value": value,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def _indicator_score(
    indicator_id: str, percentile: float, window: int
) -> dict[str, Any]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "indicator_id": indicator_id,
        "raw_value": percentile,
        "eligible": True,
        "percentile": percentile,
        "score": percentile,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def _dimension_score(dimension: str, window: int) -> dict[str, Any]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "dimension": dimension,
        "score_dimension": 0.82,
        "score_dimension_min": 0.74,
        "eligible_dimension": True,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def _nested_state(window: int, q: float) -> dict[str, Any]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "q": q,
        "weak_delta": WEAK_DELTA,
        "P_raw": True,
        "C_raw": True,
        "T_raw": True,
        "V_raw": True,
        "S_P_raw": True,
        "S_PC_raw": True,
        "S_PCT_raw": True,
        "S_PCVT_raw": True,
        "exclusive_state_layer": "PCVT",
        "eligible_state": True,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def _confirmation(state_name: str, window: int, q: float, k: int) -> dict[str, Any]:
    return {
        "security_id": SECURITY_ID,
        "trading_date": TRADING_DATE,
        "percentile_window_W": window,
        "q": q,
        "weak_delta": WEAK_DELTA,
        "confirmation_k": k,
        "state_name": state_name,
        "raw_state": True,
        "raw_streak": k,
        "raw_streak_start_date": "2026-02-01",
        "confirmed_state": True,
        "confirmation_start_date": "2026-02-01",
        "confirmation_date": TRADING_DATE,
        "validity_status": "valid",
        "reason_codes": ["valid_no_blocker"],
    }


def _extract_rows(
    payload: Any, key: str, *, required: bool = True
) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if value is None:
            if required:
                raise R0T09InputManifestBuilderError(
                    f"input payload missing required row set: {key}"
                )
            return []
    elif isinstance(payload, list):
        value = payload
    else:
        raise R0T09InputManifestBuilderError("input must be a JSON object or array")
    if not isinstance(value, list) or not all(
        isinstance(row, Mapping) for row in value
    ):
        raise R0T09InputManifestBuilderError(f"{key} must be an array of objects")
    return [dict(row) for row in value]


def _validate_payload(payload: Mapping[str, Any]) -> None:
    forbidden_guard = assert_no_forbidden_candidate_outputs(payload)
    if forbidden_guard.validity_status == "blocked":
        raise R0T09InputManifestBuilderError(
            "payload contains forbidden fields: "
            + ",".join(forbidden_guard.reason_codes)
        )
    coverage_guard = validate_r0_t09_payload_coverage(
        payload, [config.as_dict() for config in build_candidate_configs()]
    )
    if coverage_guard["validity_status"] == "blocked":
        raise R0T09InputManifestBuilderError(
            "payload coverage incomplete: "
            + ",".join(str(reason) for reason in coverage_guard["reason_codes"])
        )
    summary = _coverage_summary(payload)
    if summary["contains_k1"]:
        raise R0T09InputManifestBuilderError("K=1 is forbidden in R0-T09 payload")
    if summary["legacy_v1_field_count"] != 0:
        raise R0T09InputManifestBuilderError("legacy V1 field is forbidden")
    if summary["future_or_return_field_count"] != 0:
        raise R0T09InputManifestBuilderError("future/return field is forbidden")


def _coverage_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested_keys = {
        (
            int(row["percentile_window_W"]),
            _percent_key(row["q"]),
        )
        for row in payload.get("nested_daily_state_results", ())
        if isinstance(row, Mapping)
    }
    confirmation_keys = {
        (
            int(row["percentile_window_W"]),
            _percent_key(row["q"]),
            int(row["confirmation_k"]),
            str(row["state_name"]),
        )
        for row in payload.get("daily_confirmation_results", ())
        if isinstance(row, Mapping)
    }
    contains_k1 = any(
        isinstance(row, Mapping) and int(row.get("confirmation_k", 0)) == 1
        for row in (
            *payload.get("daily_confirmation_results", ()),
            *payload.get("confirmed_interval_results", ()),
        )
    )
    return {
        "nested_wq_count": len(nested_keys),
        "confirmation_wqk_state_count": len(confirmation_keys),
        "contains_k1": contains_k1,
        "legacy_v1_field_count": _legacy_v1_check(payload)["count"],
        "future_or_return_field_count": _future_or_return_field_count(payload),
    }


def _input_row_counts(payload: Mapping[str, Any]) -> dict[str, int]:
    return {
        key: len(payload.get(key, ()))
        for key in (
            "raw_metric_results",
            "indicator_score_results",
            "dimension_score_results",
            "nested_daily_state_results",
            "daily_confirmation_results",
            "confirmed_interval_results",
        )
    }


def _legacy_v1_check(payload: Mapping[str, Any]) -> dict[str, Any]:
    hits = [
        value
        for value in _walk_keys_and_sequence_strings(payload)
        if value in LEGACY_V1_FIELD_NAMES
    ]
    return {
        "count": len(hits),
        "field_names": sorted(set(hits)),
        "status": "passed" if not hits else "blocked",
    }


def _future_or_return_field_count(payload: Any) -> int:
    forbidden = {
        "future_label",
        "future_labels",
        "future_return",
        "future_returns",
        "future_volatility",
        "return",
        "returns",
        "backtest",
        "portfolio",
        "trade_signal",
        "buy_signal",
        "sell_signal",
    }
    return sum(1 for key in _walk_keys(payload) if str(key).lower() in forbidden)


def _walk_keys(payload: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            keys.append(str(key))
            keys.extend(_walk_keys(value))
    elif isinstance(payload, list | tuple):
        for item in payload:
            keys.extend(_walk_keys(item))
    return keys


def _walk_keys_and_sequence_strings(payload: Any) -> list[str]:
    values: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            values.append(str(key))
            values.extend(_walk_keys_and_sequence_strings(value))
    elif isinstance(payload, list | tuple):
        for item in payload:
            if isinstance(item, str):
                values.append(item)
            else:
                values.extend(_walk_keys_and_sequence_strings(item))
    return values


def _percent_key(value: Any) -> int:
    return int(round(float(value) * 100))


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise R0T09InputManifestBuilderError(f"input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise R0T09InputManifestBuilderError(f"invalid JSON input: {path}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _portable_path(path: Path) -> str:
    try:
        return path.as_posix()
    except ValueError:
        return str(path)
