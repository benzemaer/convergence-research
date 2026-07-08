from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.candidate_artifact_engine import (
    CONFIRMATION_DAYS_K_VALUES,
    DIMENSIONS,
    LOW_QUANTILE_Q_VALUES,
    PERCENTILE_WINDOW_VALUES,
    STATE_SUFFIX_BY_NAME,
    WEAK_DELTA,
    build_candidate_configs,
)
from src.r0.formal_run_identity import FormalRunIdentityError, validate_full_git_sha
from src.r0.upstream_artifact_io import write_json_atomic

MANIFEST_SCHEMA_VERSION = "r0_t10_05_authorized_input_manifest.v1"
SUMMARY_SCHEMA_VERSION = "r0_t10_05_authorized_input_manifest_summary.v1"
MANIFEST_TYPE = "r0_t10_05_authorized_input_manifest"
AUTHORIZED_MANIFEST_NAME = "r0_t10_05_authorized_input_manifest.json"
AUTHORIZED_SUMMARY_NAME = "r0_t10_05_authorized_input_manifest_summary.json"
BASELINE_CONFIG_ID = "R0_W250_Q20_K3_WEAK_D010"
REPOSITORY = "benzemaer/convergence-research"

EVIDENCE_PATHS = {
    "R0-T04": Path(
        "docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md"
    ),
    "R0-T05": Path(
        "docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md"
    ),
    "R0-T06": Path(
        "docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md"
    ),
    "R0-T07": Path(
        "docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md"
    ),
}

GATE_FIELDS = {
    "R0-T04": "R0-T05_allowed_to_start",
    "R0-T05": "R0-T06_allowed_to_start",
    "R0-T06": "R0-T07_allowed_to_start",
    "R0-T07": "R0-T10-05_allowed_to_start",
}

FORBIDDEN_KEYS = {
    "rows",
    "row_payload",
    "raw_rows",
    "input_payload",
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
}
FORBIDDEN_PATH_FRAGMENTS = ("data/raw", "data/external", "MarketDB", ".day")
LEGACY_V1_FIELDS = {
    "VolShrink20_60_raw",
    "V1_VolShrink20_60",
    "VolShrink20_60",
    "volume_shrink_20_60",
}


class R0T10AuthorizedInputManifestError(RuntimeError):
    pass


def build_authorized_input_manifest(
    *,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    r0_t04_evidence: str | Path = EVIDENCE_PATHS["R0-T04"],
    r0_t05_evidence: str | Path = EVIDENCE_PATHS["R0-T05"],
    r0_t06_evidence: str | Path = EVIDENCE_PATHS["R0-T06"],
    r0_t07_evidence: str | Path = EVIDENCE_PATHS["R0-T07"],
) -> dict[str, Any]:
    try:
        full_code_commit = validate_full_git_sha(code_commit)
    except FormalRunIdentityError as exc:
        raise R0T10AuthorizedInputManifestError("short_code_commit_forbidden") from exc

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    evidence_paths = {
        "R0-T04": Path(r0_t04_evidence),
        "R0-T05": Path(r0_t05_evidence),
        "R0-T06": Path(r0_t06_evidence),
        "R0-T07": Path(r0_t07_evidence),
    }
    created_at = _utc_now()
    try:
        evidence = _load_evidence_set(evidence_paths)
        artifacts = _input_artifacts(evidence)
        _validate_prerequisites(evidence, artifacts)
    except R0T10AuthorizedInputManifestError as exc:
        summary = _summary(
            run_id=run_id,
            code_commit=full_code_commit,
            created_at=created_at,
            output_dir=root,
            status="blocked",
            reason_codes=(str(exc),),
            manifest_path=None,
            manifest_hash=None,
        )
        write_json_atomic(root / AUTHORIZED_SUMMARY_NAME, summary)
        return summary

    manifest = _manifest(
        run_id=run_id,
        code_commit=full_code_commit,
        created_at=created_at,
        evidence=evidence,
        artifacts=artifacts,
    )
    _assert_no_row_payload(manifest)
    manifest_path = root / AUTHORIZED_MANIFEST_NAME
    write_json_atomic(manifest_path, manifest)
    manifest_hash = sha256_file(manifest_path)
    summary = _summary(
        run_id=run_id,
        code_commit=full_code_commit,
        created_at=created_at,
        output_dir=root,
        status="completed",
        reason_codes=("valid_no_blocker",),
        manifest_path=manifest_path,
        manifest_hash=manifest_hash,
    )
    summary.update(
        {
            "authorized_r0_input": True,
            "source_evidence": manifest["source_evidence"],
            "input_artifacts": manifest["input_artifacts"],
            "coverage": manifest["coverage"],
            "grid": manifest["grid"],
            "forbidden_guards": manifest["forbidden_guards"],
            "row_payload_embedded": False,
            "R0-T10-05_full_grid_allowed_to_start": True,
        }
    )
    write_json_atomic(root / AUTHORIZED_SUMMARY_NAME, summary)
    return summary


def load_authorized_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = _load_json(manifest_path)
    if manifest.get("manifest_type") != MANIFEST_TYPE:
        raise R0T10AuthorizedInputManifestError("authorized_manifest_type_invalid")
    if manifest.get("authorized_r0_input") is not True:
        raise R0T10AuthorizedInputManifestError("authorized_r0_input_not_true")
    try:
        validate_full_git_sha(str(manifest.get("code_commit", "")))
    except FormalRunIdentityError as exc:
        raise R0T10AuthorizedInputManifestError("short_code_commit_forbidden") from exc
    _assert_no_row_payload(manifest)
    if _contains_forbidden_path(manifest):
        raise R0T10AuthorizedInputManifestError(
            "raw_external_marketdb_day_source_forbidden"
        )
    return manifest


def selected_config_ids() -> list[str]:
    return [str(config.candidate_config_id) for config in build_candidate_configs()]


def config_id_list_hash(config_ids: Sequence[str]) -> str:
    return _hash_object({"config_ids": list(config_ids)})


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_evidence_set(paths: Mapping[str, Path]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for task_id, path in paths.items():
        if not path.exists():
            raise R0T10AuthorizedInputManifestError(f"{task_id}_evidence_missing")
        fields = _parse_evidence(path)
        fields["evidence_path"] = path.as_posix()
        fields["evidence_sha256"] = sha256_file(path)
        result[task_id] = fields
    return result


def _parse_evidence(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    fields: dict[str, Any] = {}
    for line in text.splitlines():
        if not line.startswith("`") or "`:" not in line:
            continue
        key_end = line.find("`:")
        key = line[1:key_end].strip()
        value_text = line[key_end + 2 :].strip()
        coded_values = re.findall(r"`([^`]*)`", value_text)
        if coded_values:
            value = ", ".join(item.strip() for item in coded_values)
        else:
            value = value_text.strip()
        fields.setdefault(key, value.strip())
    return fields


def _input_artifacts(
    evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    t04 = evidence["R0-T04"]
    t05 = evidence["R0-T05"]
    t06 = evidence["R0-T06"]
    t07 = evidence["R0-T07"]
    return {
        "r0_t04_raw_metric": _artifact(
            t04,
            "output_duckdb",
            "output_duckdb_sha256",
            "r0_t04_raw_metric_results",
            "row_count",
        ),
        "r0_t05_indicator_score": _artifact(
            t05,
            "indicator_score_duckdb",
            "indicator_score_duckdb_sha256",
            "r0_t05_indicator_score_results",
            "indicator_score_row_count",
        ),
        "r0_t05_dimension_score": _artifact(
            t05,
            "dimension_score_duckdb",
            "dimension_score_duckdb_sha256",
            "r0_t05_dimension_score_results",
            "dimension_score_row_count",
        ),
        "r0_t05_common_eligible": _artifact(
            t05,
            "common_eligible_duckdb",
            "common_eligible_duckdb_sha256",
            "r0_t05_common_eligible_sample_results",
            "common_eligible_row_count",
        ),
        "r0_t06_indicator_state": _artifact(
            t06,
            "indicator_state_duckdb_path",
            "indicator_state_duckdb_sha256",
            "r0_t06_indicator_state_results",
            "indicator_state_row_count",
        ),
        "r0_t06_dimension_state": _artifact(
            t06,
            "dimension_state_duckdb_path",
            "dimension_state_duckdb_sha256",
            "r0_t06_dimension_state_results",
            "dimension_state_row_count",
        ),
        "r0_t06_nested_daily_state": _artifact(
            t06,
            "nested_daily_state_duckdb_path",
            "nested_daily_state_duckdb_sha256",
            "r0_t06_nested_daily_state_results",
            "nested_daily_state_row_count",
        ),
        "r0_t07_daily_confirmation": _artifact(
            t07,
            "daily_confirmation_duckdb_path",
            "daily_confirmation_duckdb_sha256",
            "r0_t07_daily_confirmation_results",
            "daily_confirmation_row_count",
        ),
        "r0_t07_confirmed_interval": _artifact(
            t07,
            "confirmed_interval_duckdb_path",
            "confirmed_interval_duckdb_sha256",
            "r0_t07_confirmed_interval_results",
            "confirmed_interval_row_count",
        ),
    }


def _artifact(
    evidence: Mapping[str, Any],
    path_key: str,
    hash_key: str,
    table: str,
    row_count_key: str,
) -> dict[str, Any]:
    path = str(evidence.get(path_key, ""))
    return {
        "path": path,
        "sha256": str(evidence.get(hash_key, "")),
        "table": table,
        "row_count": _int_value(evidence.get(row_count_key, "0")),
        "security_count": _int_value(
            evidence.get("security_count", evidence.get("input_security_count", "0"))
        ),
        "date_min": str(evidence.get("date_min", evidence.get("input_date_min", ""))),
        "date_max": str(evidence.get("date_max", evidence.get("input_date_max", ""))),
    }


def _validate_prerequisites(
    evidence: Mapping[str, Mapping[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    for task_id, fields in evidence.items():
        if str(fields.get("status")) != "completed":
            raise R0T10AuthorizedInputManifestError(f"{task_id}_evidence_not_completed")
        if str(fields.get(GATE_FIELDS[task_id], "")).lower() != "true":
            raise R0T10AuthorizedInputManifestError(
                f"{task_id}_downstream_gate_not_open"
            )
        validator_status = str(
            fields.get("validator_status", fields.get("Validation result", "passed"))
        )
        if validator_status not in {"passed", ""}:
            raise R0T10AuthorizedInputManifestError(f"{task_id}_validator_not_passed")
    for name, artifact in artifacts.items():
        path = Path(str(artifact["path"]))
        if not path.exists():
            raise R0T10AuthorizedInputManifestError(f"{name}_artifact_missing")
        if sha256_file(path) != artifact["sha256"]:
            raise R0T10AuthorizedInputManifestError(f"{name}_artifact_hash_mismatch")
    for task_id in ("R0-T04", "R0-T05", "R0-T07"):
        try:
            validate_full_git_sha(str(evidence[task_id]["code_commit"]))
        except (KeyError, FormalRunIdentityError) as exc:
            raise R0T10AuthorizedInputManifestError(
                f"{task_id}_code_commit_not_full_sha"
            ) from exc
    if "run_code_commit_argument" not in evidence["R0-T06"]:
        try:
            validate_full_git_sha(str(evidence["R0-T06"]["code_commit"]))
        except (KeyError, FormalRunIdentityError) as exc:
            raise R0T10AuthorizedInputManifestError(
                "R0-T06_code_commit_not_full_sha"
            ) from exc


def _manifest(
    *,
    run_id: str,
    code_commit: str,
    created_at: str,
    evidence: Mapping[str, Mapping[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    config_ids = selected_config_ids()
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_type": MANIFEST_TYPE,
        "authorized_r0_input": True,
        "run_id": run_id,
        "code_commit": code_commit,
        "created_at": created_at,
        "repository": REPOSITORY,
        "source_evidence": {
            task_id: {
                "path": fields["evidence_path"],
                "sha256": fields["evidence_sha256"],
                "status": fields["status"],
                "gate_field": GATE_FIELDS[task_id],
                "gate_value": str(fields.get(GATE_FIELDS[task_id], "")).lower()
                == "true",
            }
            for task_id, fields in evidence.items()
        },
        "input_artifacts": artifacts,
        "coverage": {
            "security_count": artifacts["r0_t07_daily_confirmation"]["security_count"],
            "date_min": artifacts["r0_t07_daily_confirmation"]["date_min"],
            "date_max": artifacts["r0_t07_daily_confirmation"]["date_max"],
            "W_coverage": [120, 250, 500],
            "q_coverage": [0.10, 0.20, 0.30],
            "K_coverage": [2, 3, 5],
            "weak_delta": WEAK_DELTA,
            "state_name_coverage": list(STATE_SUFFIX_BY_NAME.keys()),
            "indicator_coverage": _split_coverage(
                evidence["R0-T05"].get("indicator_coverage", "")
            ),
            "dimension_coverage": list(DIMENSIONS),
        },
        "grid": {
            "W_values": list(PERCENTILE_WINDOW_VALUES),
            "q_values": list(LOW_QUANTILE_Q_VALUES),
            "K_values": list(CONFIRMATION_DAYS_K_VALUES),
            "weak_delta": WEAK_DELTA,
            "dimension_rule": "weak",
            "selected_config_count": len(config_ids),
            "selected_config_ids": config_ids,
            "config_id_list_hash": config_id_list_hash(config_ids),
            "baseline_config_id": BASELINE_CONFIG_ID,
        },
        "forbidden_guards": {
            "no_future_fields": True,
            "no_return_fields": True,
            "no_backtest_fields": True,
            "no_portfolio_fields": True,
            "no_trade_signal_fields": True,
            "no_legacy_v1": True,
            "no_synthetic_contract_grid": True,
            "no_raw_external_marketdb_day_source": True,
        },
        "row_payload_embedded": False,
        "status": "completed",
        "reason_codes": ["valid_no_blocker"],
    }


def _summary(
    *,
    run_id: str,
    code_commit: str,
    created_at: str,
    output_dir: Path,
    status: str,
    reason_codes: Sequence[str],
    manifest_path: Path | None,
    manifest_hash: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": "R0-T10-05",
        "run_id": run_id,
        "code_commit": code_commit,
        "created_at": created_at,
        "output_dir": output_dir.as_posix(),
        "authorized_input_manifest_path": None
        if manifest_path is None
        else manifest_path.as_posix(),
        "authorized_input_manifest_sha256": manifest_hash,
        "status": status,
        "reason_codes": list(reason_codes),
        "row_payload_embedded": False,
        "R0-T10-05_full_grid_allowed_to_start": status == "completed",
    }


def _assert_no_row_payload(payload: Any) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_KEYS or lowered in {
                item.lower() for item in LEGACY_V1_FIELDS
            }:
                raise R0T10AuthorizedInputManifestError(
                    f"row_or_forbidden_payload_field:{key}"
                )
            _assert_no_row_payload(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_row_payload(item)


def _contains_forbidden_path(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        return any(_contains_forbidden_path(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_forbidden_path(value) for value in payload)
    if isinstance(payload, str):
        normalized = payload.replace("\\", "/")
        return any(fragment in normalized for fragment in FORBIDDEN_PATH_FRAGMENTS)
    return False


def _split_coverage(value: Any) -> list[str]:
    text = str(value).replace("`", "")
    if not text:
        return []
    parts = re.split(r"[,/]", text)
    return [part.strip() for part in parts if part.strip()]


def _int_value(value: Any) -> int:
    return int(str(value).replace(",", "").strip())


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise R0T10AuthorizedInputManifestError(f"expected JSON object: {path}")
    return payload


def _hash_object(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
