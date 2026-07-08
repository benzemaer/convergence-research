from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "docs/evidence/r1/R1-T02_r0_lineage_pit_audit_evidence.md"

PLACEHOLDER_COMMITS = {"", "unknown", "placeholder", "tbd", "fixture"}
FORBIDDEN_BASE_COMMITS = {
    "2982ec0d3f674908f9527e938efbd7badf6de81a",
    "718e1803afd8a8aa188ddc5e66a1cdac01b9cea6",
}
REQUIRED_CHECKS = (
    "r1_t01_evidence",
    "r0_t10_05_evidence",
    "r0_t11_evidence",
    "r1_t01_gate",
    "authorized_manifest_contract",
    "forbidden_guards",
    "authorized_grid_coverage",
    "full_grid_manifest_contract",
    "full_grid_candidate_snapshots",
    "zero_interval_consistency",
    "locked_manifest_hashes",
    "config_artifact_hashes",
    "authorized_input_manifest_forbidden_token_check",
    "full_grid_manifest_forbidden_token_check",
    "r0_evidence_chain_hash",
)


class R1T02LineagePitAuditValidationError(RuntimeError):
    pass


def validate_r1_t02_lineage_pit_audit(
    summary_path: Path,
    evidence_path: Path = DEFAULT_EVIDENCE,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    summary = _load_json(summary_path, errors, "summary")
    evidence = _parse_evidence(evidence_path)
    if not evidence:
        errors.append("evidence_missing_or_unparseable")

    _check_summary(summary, summary_path, errors)
    _check_evidence(evidence, summary, summary_path, errors)
    result = {
        "task_id": "R1-T02",
        "validator_status": "passed" if not errors else "failed",
        "summary_path": _display_path(summary_path),
        "summary_sha256": sha256_file(summary_path) if summary_path.exists() else None,
        "evidence_path": _display_path(evidence_path),
        "evidence_sha256": sha256_file(evidence_path) if evidence_path.exists() else None,
        "errors": errors,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if errors:
        raise R1T02LineagePitAuditValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label}_missing")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}_invalid_json:{exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{label}_not_object")
        return {}
    return payload


def _check_summary(
    summary: dict[str, Any], summary_path: Path, errors: list[str]
) -> None:
    if not summary:
        return
    if summary.get("task_id") != "R1-T02":
        errors.append("summary_task_id_mismatch")
    if summary.get("status") != "completed":
        errors.append("summary_status_not_completed")
    if summary.get("row_payload_embedded") is not False:
        errors.append("summary_row_payload_embedded_not_false")
    if summary.get("blocked_reasons"):
        errors.append("summary_has_blocked_reasons")
    gates = summary.get("downstream_gates", {})
    if gates.get("R1-T03_allowed_to_start") is not True:
        errors.append("summary_R1_T03_not_allowed")
    if gates.get("R1-T07_allowed_to_start") is not False:
        errors.append("summary_R1_T07_not_blocked")
    if gates.get("R2_allowed_to_start") is not False:
        errors.append("summary_R2_not_blocked")
    checks = summary.get("checks", {})
    for key in REQUIRED_CHECKS:
        if checks.get(key) != "passed":
            errors.append(f"summary_check_not_passed:{key}")
    counts = summary.get("counts", {})
    expected_counts = {
        "selected_config_count": 27,
        "completed_config_count": 27,
        "failed_config_count": 0,
        "confirmed_interval_row_count_total": 0,
        "daily_confirmed_true_count_total": 0,
        "confirmed_interval_zero_config_count": 27,
    }
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            errors.append(f"summary_count_mismatch:{key}")
    if counts.get("zero_interval_reason") != "no_confirmed_segments_in_r0_t07_input":
        errors.append("summary_zero_interval_reason_mismatch")
    _check_commit(summary.get("code_commit"), errors, "summary_code_commit")


def _check_evidence(
    evidence: dict[str, str],
    summary: dict[str, Any],
    summary_path: Path,
    errors: list[str],
) -> None:
    if not evidence:
        return
    required = {
        "task_id": "R1-T02",
        "status": "completed",
        "validator_status": "passed",
        "R1-T03_allowed_to_start": "true",
        "R1-T07_allowed_to_start": "false",
        "R2_allowed_to_start": "false",
        "row_payload_embedded": "false",
        "forbidden_input_check": "passed",
        "forbidden_output_check": "passed",
        "no_future_label_check": "passed",
        "no_backtest_check": "passed",
        "no_trading_signal_check": "passed",
        "config_artifact_hash_check": "passed",
        "zero_interval_consistency_check": "passed",
        "strict_past_artifact_field_check": "passed",
    }
    for key, expected in required.items():
        if evidence.get(key) != expected:
            errors.append(f"evidence_field_mismatch:{key}")
    if evidence.get("summary_path") != _display_path(summary_path):
        errors.append("evidence_summary_path_mismatch")
    if evidence.get("summary_sha256") != sha256_file(summary_path):
        errors.append("evidence_summary_hash_mismatch")
    for path_key, hash_key in (
        ("authorized_input_manifest_path", "authorized_input_manifest_sha256"),
        ("full_grid_manifest_path", "full_grid_manifest_sha256"),
        ("r1_t01_evidence_path", "r1_t01_evidence_sha256"),
        ("r0_t10_05_evidence_path", "r0_t10_05_evidence_sha256"),
        ("r0_t11_evidence_path", "r0_t11_evidence_sha256"),
    ):
        if evidence.get(path_key) != summary.get(path_key):
            errors.append(f"evidence_path_mismatch:{path_key}")
        if evidence.get(hash_key) != str(summary.get(hash_key)):
            errors.append(f"evidence_hash_mismatch:{hash_key}")
    _check_commit(evidence.get("code_commit"), errors, "evidence_code_commit")


def _check_commit(value: object, errors: list[str], label: str) -> None:
    commit = str(value or "").lower()
    if commit in PLACEHOLDER_COMMITS:
        errors.append(f"{label}_placeholder")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        errors.append(f"{label}_not_full_sha")
    if commit in FORBIDDEN_BASE_COMMITS:
        errors.append(f"{label}_base_commit_forbidden")


def _parse_evidence(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not path.exists():
        return fields
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("`") or "`:" not in line:
            continue
        key_end = line.find("`:")
        key = line[1:key_end].strip()
        value = line[key_end + 2 :].strip().replace("`", "")
        fields.setdefault(key, value)
    return fields


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
