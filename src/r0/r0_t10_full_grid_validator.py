from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.r0.candidate_artifact_engine import build_candidate_configs
from src.r0.formal_run_identity import FormalRunIdentityError, validate_full_git_sha
from src.r0.r0_t10_authorized_input_manifest_builder import (
    BASELINE_CONFIG_ID,
    load_authorized_manifest,
    sha256_file,
)
from src.r0.r0_t10_full_grid_materializer import (
    DAILY_TABLE,
    GLOBAL_MANIFEST_NAME,
    INTERVAL_TABLE,
    SUMMARY_NAME,
    VALIDATION_RESULT_NAME,
)
from src.r0.upstream_artifact_io import quote_ident, write_json_atomic

FORBIDDEN_FIELDS = {
    "future_label",
    "future_return",
    "future_returns",
    "return",
    "returns",
    "backtest",
    "portfolio",
    "trade_signal",
    "buy_signal",
    "sell_signal",
    "release_direction",
    "breakout_direction",
    "gap_merge",
    "cooldown",
    "r1_analysis",
}
LEGACY_V1_FIELDS = {
    "VolShrink20_60_raw",
    "V1_VolShrink20_60",
    "VolShrink20_60",
    "volume_shrink_20_60",
}
REQUIRED_SOURCE_EVIDENCE = {
    "R0-T04": "R0-T05_allowed_to_start",
    "R0-T05": "R0-T06_allowed_to_start",
    "R0-T06": "R0-T07_allowed_to_start",
    "R0-T07": "R0-T10-05_allowed_to_start",
}
SYNTHETIC_MARKERS = (
    "synthetic",
    "fixture",
    "contract-grid",
    "contract_grid",
    "smoke_fixture",
)
RAW_EXTERNAL_MARKERS = ("data/raw", "data/external", "MarketDB", ".day")


class R0T10FullGridValidationError(RuntimeError):
    pass


def validate_full_grid(
    *,
    authorized_input_manifest: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    manifest_path = Path(authorized_input_manifest)
    output = Path(output_dir)
    errors: list[str] = []
    try:
        authorized = load_authorized_manifest(manifest_path)
    except Exception as exc:  # noqa: BLE001
        raise R0T10FullGridValidationError(str(exc)) from exc
    global_manifest = _load_json(output / GLOBAL_MANIFEST_NAME)
    summary = _load_json(output / SUMMARY_NAME)
    _check_no_row_payload(authorized, "authorized_manifest", errors)
    _check_no_row_payload(global_manifest, "global_manifest", errors)
    _check_no_row_payload(summary, "summary", errors)
    _check_code_commit(authorized, global_manifest, summary, errors)
    _check_grid(global_manifest, errors)
    _check_authorized_manifest_hash(manifest_path, global_manifest, summary, errors)
    lineage_result = _validate_authorized_manifest_lineage(authorized, errors)

    config_results = _validate_config_artifacts(output, global_manifest, errors)
    daily_true_total = sum(
        item["daily_confirmed_true_count"] for item in config_results.values()
    )
    interval_total = sum(item["interval_row_count"] for item in config_results.values())
    if interval_total == 0 and daily_true_total == 0:
        zero_reason = "no_confirmed_segments_in_r0_t07_input"
    elif interval_total == 0:
        zero_reason = "invalid_daily_confirmed_true_without_interval"
        errors.append("daily_confirmed_true_gt_zero_but_interval_zero")
    else:
        zero_reason = None

    result = {
        "schema_version": "r0_t10_05_full_grid_validation_result.v1",
        "status": "passed" if not errors else "blocked",
        "reason_codes": errors or ["valid_no_blocker"],
        "authorized_input_manifest_path": str(manifest_path),
        "authorized_input_manifest_sha256": sha256_file(manifest_path),
        "output_dir": str(output),
        "global_manifest_path": str(output / GLOBAL_MANIFEST_NAME),
        "global_manifest_sha256": sha256_file(output / GLOBAL_MANIFEST_NAME),
        "summary_path": str(output / SUMMARY_NAME),
        "summary_sha256": sha256_file(output / SUMMARY_NAME),
        "selected_config_count": len(config_results),
        "completed_config_count": sum(
            1 for item in config_results.values() if item["status"] == "completed"
        ),
        "failed_config_count": sum(
            1 for item in config_results.values() if item["status"] == "failed"
        ),
        "daily_candidate_row_count_total": sum(
            item["daily_row_count"] for item in config_results.values()
        ),
        "confirmed_interval_row_count_total": interval_total,
        "daily_confirmed_true_count_total": daily_true_total,
        "confirmed_interval_zero_config_count": sum(
            1 for item in config_results.values() if item["interval_row_count"] == 0
        ),
        "confirmed_interval_row_count_by_config": {
            key: item["interval_row_count"]
            for key, item in sorted(config_results.items())
        },
        "daily_confirmed_true_count_by_config": {
            key: item["daily_confirmed_true_count"]
            for key, item in sorted(config_results.items())
        },
        "zero_interval_reason_if_any": zero_reason,
        "forbidden_field_check": "passed"
        if not any("forbidden_field" in error for error in errors)
        else "blocked",
        "legacy_v1_check": "passed"
        if not any("legacy_v1" in error for error in errors)
        else "blocked",
        "source_evidence_check": lineage_result["source_evidence_check"],
        "input_artifact_hash_check": lineage_result["input_artifact_hash_check"],
        "synthetic_input_check": lineage_result["synthetic_input_check"],
        "raw_external_source_check": lineage_result["raw_external_source_check"],
        "full_code_commit_check": "passed"
        if not any("code_commit" in error for error in errors)
        else "blocked",
        "manifest_contains_row_payload": False,
        "summary_contains_row_payload": False,
        "R0-T11_allowed_to_start": not errors,
        "downstream_gate_allowed": not errors,
    }
    write_json_atomic(output / VALIDATION_RESULT_NAME, result)
    if errors:
        raise R0T10FullGridValidationError(";".join(errors))
    return result


def _validate_authorized_manifest_lineage(
    authorized: Mapping[str, Any], errors: list[str]
) -> dict[str, str]:
    lineage_errors: list[str] = []
    artifact_errors: list[str] = []
    synthetic_errors: list[str] = []
    raw_external_errors: list[str] = []

    _check_no_row_payload(authorized, "authorized_manifest", lineage_errors)
    if _contains_marker(authorized, SYNTHETIC_MARKERS):
        synthetic_errors.append("synthetic_contract_grid_marker_forbidden")
    if _contains_marker(authorized, RAW_EXTERNAL_MARKERS):
        raw_external_errors.append("raw_external_marketdb_day_lineage_forbidden")

    source_evidence = authorized.get("source_evidence")
    if not isinstance(source_evidence, Mapping):
        lineage_errors.append("source_evidence_missing")
    else:
        for task_id, gate_field in REQUIRED_SOURCE_EVIDENCE.items():
            entry = source_evidence.get(task_id)
            if not isinstance(entry, Mapping):
                lineage_errors.append(f"source_evidence_missing:{task_id}")
                continue
            path = Path(str(entry.get("path", "")))
            if not path.exists():
                lineage_errors.append(f"source_evidence_file_missing:{task_id}")
                continue
            if entry.get("sha256") != sha256_file(path):
                lineage_errors.append(f"source_evidence_hash_mismatch:{task_id}")
            evidence = _parse_evidence(path)
            if str(evidence.get("status", "")) != "completed":
                lineage_errors.append(f"source_evidence_not_completed:{task_id}")
            if str(evidence.get(gate_field, "")).lower() != "true":
                lineage_errors.append(f"source_evidence_gate_not_open:{task_id}")
            if (
                task_id in {"R0-T05", "R0-T06", "R0-T07"}
                and str(evidence.get("validator_status", "")) != "passed"
            ):
                lineage_errors.append(f"source_evidence_validator_not_passed:{task_id}")
            if _contains_marker(evidence, SYNTHETIC_MARKERS):
                synthetic_errors.append(f"source_evidence_synthetic_marker:{task_id}")
            if _contains_marker(evidence, RAW_EXTERNAL_MARKERS):
                raw_external_errors.append(f"source_evidence_raw_external:{task_id}")

    input_artifacts = authorized.get("input_artifacts")
    if not isinstance(input_artifacts, Mapping):
        artifact_errors.append("input_artifacts_missing")
    else:
        for artifact_id, artifact in input_artifacts.items():
            if not isinstance(artifact, Mapping):
                artifact_errors.append(f"input_artifact_invalid:{artifact_id}")
                continue
            path = Path(str(artifact.get("path", "")))
            if not path.exists():
                artifact_errors.append(f"input_artifact_missing:{artifact_id}")
                continue
            if artifact.get("sha256") != sha256_file(path):
                artifact_errors.append(f"input_artifact_hash_mismatch:{artifact_id}")
            row_count = artifact.get("row_count")
            if row_count is None:
                artifact_errors.append(
                    f"input_artifact_row_count_missing:{artifact_id}"
                )
            else:
                try:
                    if int(row_count) < 0:
                        artifact_errors.append(
                            f"input_artifact_row_count_negative:{artifact_id}"
                        )
                except (TypeError, ValueError):
                    artifact_errors.append(
                        f"input_artifact_row_count_invalid:{artifact_id}"
                    )
            if _contains_marker(artifact, SYNTHETIC_MARKERS):
                synthetic_errors.append(
                    f"input_artifact_synthetic_marker:{artifact_id}"
                )
            if _contains_marker(artifact, RAW_EXTERNAL_MARKERS):
                raw_external_errors.append(f"input_artifact_raw_external:{artifact_id}")

    errors.extend(lineage_errors)
    errors.extend(artifact_errors)
    errors.extend(synthetic_errors)
    errors.extend(raw_external_errors)
    return {
        "source_evidence_check": "passed" if not lineage_errors else "blocked",
        "input_artifact_hash_check": "passed" if not artifact_errors else "blocked",
        "synthetic_input_check": "passed" if not synthetic_errors else "blocked",
        "raw_external_source_check": "passed" if not raw_external_errors else "blocked",
    }


def _check_code_commit(
    authorized: Mapping[str, Any],
    global_manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    errors: list[str],
) -> None:
    commits = {
        str(authorized.get("code_commit", "")),
        str(global_manifest.get("code_commit", "")),
        str(summary.get("code_commit", "")),
    }
    for commit in commits:
        try:
            validate_full_git_sha(commit)
        except FormalRunIdentityError:
            errors.append("short_code_commit_forbidden")
    if len(commits) != 1:
        errors.append("code_commit_mismatch")


def _check_grid(global_manifest: Mapping[str, Any], errors: list[str]) -> None:
    configs = [config.as_dict() for config in build_candidate_configs()]
    expected = {str(config["candidate_config_id"]) for config in configs}
    actual = set(str(item) for item in global_manifest.get("selected_config_ids", ()))
    if actual != expected:
        errors.append("selected_config_ids_not_exact_grid")
    if len(actual) != 27 or global_manifest.get("selected_config_count") != 27:
        errors.append("selected_config_count_not_27")
    if BASELINE_CONFIG_ID not in actual:
        errors.append("baseline_config_missing")
    if any("_K1_" in config_id for config_id in actual):
        errors.append("K1_config_forbidden")


def _check_authorized_manifest_hash(
    manifest_path: Path,
    global_manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    errors: list[str],
) -> None:
    digest = sha256_file(manifest_path)
    if global_manifest.get("authorized_input_manifest_sha256") != digest:
        errors.append("global_manifest_authorized_input_hash_mismatch")
    if summary.get("authorized_input_manifest_sha256") != digest:
        errors.append("summary_authorized_input_hash_mismatch")


def _validate_config_artifacts(
    output: Path,
    global_manifest: Mapping[str, Any],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    import duckdb  # noqa: PLC0415

    configs = {
        config.candidate_config_id: config.as_dict()
        for config in build_candidate_configs()
    }
    artifacts = global_manifest.get("artifacts_by_config", {})
    if not isinstance(artifacts, Mapping):
        errors.append("artifacts_by_config_missing")
        return {}
    results: dict[str, dict[str, Any]] = {}
    for config_id, config in configs.items():
        config_dir = output / "configs" / config_id
        done = config_dir / "DONE.json"
        failed = config_dir / "FAILED.json"
        if not config_dir.is_dir():
            errors.append(f"config_dir_missing:{config_id}")
            continue
        if done.exists() == failed.exists():
            errors.append(f"done_failed_marker_not_mutually_exclusive:{config_id}")
            continue
        if failed.exists():
            errors.append(f"config_failed:{config_id}")
            results[config_id] = {
                "status": "failed",
                "daily_row_count": 0,
                "interval_row_count": 0,
                "daily_confirmed_true_count": 0,
            }
            continue
        marker = _load_json(done)
        daily = Path(str(marker["daily_artifact_duckdb_path"]))
        interval = Path(str(marker["interval_artifact_duckdb_path"]))
        daily_parquet = Path(str(marker["daily_artifact_parquet_path"]))
        interval_parquet = Path(str(marker["interval_artifact_parquet_path"]))
        for path in (daily, interval, daily_parquet, interval_parquet):
            if not path.exists():
                errors.append(f"artifact_missing:{config_id}:{path.name}")
        if marker.get("daily_duckdb_hash") != sha256_file(daily):
            errors.append(f"daily_duckdb_hash_mismatch:{config_id}")
        if marker.get("interval_duckdb_hash") != sha256_file(interval):
            errors.append(f"interval_duckdb_hash_mismatch:{config_id}")
        conn = duckdb.connect(str(daily), read_only=True)
        try:
            daily_count = int(
                conn.execute(
                    f"SELECT count(*) FROM {quote_ident(DAILY_TABLE)}"
                ).fetchone()[0]
            )
            wrong = int(
                conn.execute(
                    f"""
                    SELECT count(*) FROM {quote_ident(DAILY_TABLE)}
                    WHERE percentile_window_W <> ?
                       OR abs(low_quantile_q - ?) > 0.0000000001
                       OR confirmation_days_K <> ?
                       OR candidate_config_id <> ?
                    """,
                    [
                        config["percentile_window_W"],
                        config["low_quantile_q"],
                        config["confirmation_days_K"],
                        config_id,
                    ],
                ).fetchone()[0]
            )
            true_count = int(
                conn.execute(
                    f"""
                    SELECT count(*)
                    FROM {quote_ident(DAILY_TABLE)}
                    WHERE confirmed_state = true
                    """
                ).fetchone()[0]
            )
            _check_table_fields(conn, DAILY_TABLE, errors, config_id)
        finally:
            conn.close()
        conn = duckdb.connect(str(interval), read_only=True)
        try:
            interval_count = int(
                conn.execute(
                    f"SELECT count(*) FROM {quote_ident(INTERVAL_TABLE)}"
                ).fetchone()[0]
            )
            interval_wrong = int(
                conn.execute(
                    f"""
                    SELECT count(*) FROM {quote_ident(INTERVAL_TABLE)}
                    WHERE percentile_window_W <> ?
                       OR abs(low_quantile_q - ?) > 0.0000000001
                       OR confirmation_days_K <> ?
                       OR candidate_config_id <> ?
                    """,
                    [
                        config["percentile_window_W"],
                        config["low_quantile_q"],
                        config["confirmation_days_K"],
                        config_id,
                    ],
                ).fetchone()[0]
            )
            _check_table_fields(conn, INTERVAL_TABLE, errors, config_id)
        finally:
            conn.close()
        if wrong or interval_wrong:
            errors.append(f"artifact_rows_not_config_filtered:{config_id}")
        if int(marker.get("daily_row_count", -1)) != daily_count:
            errors.append(f"daily_row_count_mismatch:{config_id}")
        if int(marker.get("interval_row_count", -1)) != interval_count:
            errors.append(f"interval_row_count_mismatch:{config_id}")
        if true_count > 0 and interval_count == 0:
            errors.append(f"daily_confirmed_true_without_interval:{config_id}")
        results[config_id] = {
            "status": "completed",
            "daily_row_count": daily_count,
            "interval_row_count": interval_count,
            "daily_confirmed_true_count": true_count,
        }
    return results


def _check_table_fields(
    conn: Any, table: str, errors: list[str], config_id: str
) -> None:
    cols = [
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    ]
    lowered = {col.lower() for col in cols}
    if lowered & FORBIDDEN_FIELDS:
        errors.append(f"forbidden_field:{config_id}")
    if set(cols) & LEGACY_V1_FIELDS:
        errors.append(f"legacy_v1_field:{config_id}")


def _check_no_row_payload(payload: Any, label: str, errors: list[str]) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in {"rows", "row_payload", "input_payload", "raw_rows"}:
                errors.append(f"{label}_contains_row_payload")
            _check_no_row_payload(value, label, errors)
    elif isinstance(payload, list):
        for value in payload:
            _check_no_row_payload(value, label, errors)


def _parse_evidence(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("`") or "`:" not in line:
            continue
        key_end = line.find("`:")
        key = line[1:key_end].strip()
        value_text = line[key_end + 2 :].strip()
        if value_text.startswith("`") and value_text.endswith("`"):
            value = value_text[1:-1]
        else:
            value = value_text.replace("`", "")
        fields.setdefault(key, value.strip())
    return fields


def _contains_marker(payload: Any, markers: tuple[str, ...]) -> bool:
    if isinstance(payload, Mapping):
        return any(_contains_marker(value, markers) for value in payload.values())
    if isinstance(payload, list | tuple):
        return any(_contains_marker(value, markers) for value in payload)
    if isinstance(payload, str):
        lowered = payload.lower()
        return any(marker.lower() in lowered for marker in markers)
    return False


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise R0T10FullGridValidationError(f"expected JSON object: {path}")
    return payload
