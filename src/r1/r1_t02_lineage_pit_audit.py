from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG = ROOT / "configs/r1/r1_t02_r0_lineage_pit_audit.v1.json"
DEFAULT_R1_T01_CONFIG = (
    ROOT / "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"
)
DEFAULT_R1_T01_EVIDENCE = (
    ROOT / "docs/evidence/r1/R1-T01_validation_protocol_manifest_lock_evidence.md"
)
DEFAULT_R0_T10_EVIDENCE = (
    ROOT / "docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md"
)
DEFAULT_R0_T11_EVIDENCE = (
    ROOT / "docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md"
)

FORBIDDEN_FIELD_TOKENS = (
    "future_return",
    "forward_return",
    "future_volatility",
    "future_breakout",
    "future_path",
    "backtest",
    "portfolio",
    "trade_signal",
    "trading_signal",
    "pnl",
    "alpha",
    "raw_external",
    "marketdb",
    ".day",
    "jointlift",
    "empirical_p",
    "z_score",
    "r2_decision_matrix",
    "freeze_candidate",
    "review_candidate",
)
R0_STRICT_PAST_EVIDENCE = (
    ROOT
    / "docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md"
)
REQUIRED_FORBIDDEN_GUARDS = (
    "no_future_fields",
    "no_backtest_fields",
    "no_portfolio_fields",
    "no_trade_signal_fields",
    "no_raw_external_marketdb_day_source",
    "no_synthetic_contract_grid",
    "no_return_fields",
    "no_legacy_v1",
)
EXPECTED_STATES = ("S_P", "S_PC", "S_PCT", "S_PCVT")
EXPECTED_W = [120, 250, 500]
EXPECTED_Q = [0.1, 0.2, 0.3]
EXPECTED_K = [2, 3, 5]
EXPECTED_BASELINE = "R0_W250_Q20_K3_WEAK_D010"


@dataclass
class AuditContext:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)

    def pass_check(self, key: str) -> None:
        self.checks[key] = "passed"

    def fail_check(self, key: str, message: str) -> None:
        self.checks[key] = "blocked"
        self.errors.append(f"{key}:{message}")

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")


def run_r1_t02_lineage_pit_audit(
    *,
    output_dir: Path,
    run_id: str | None = None,
    code_commit: str = "unknown",
    root: Path = ROOT,
    config_path: Path = DEFAULT_CONFIG,
    r1_t01_config_path: Path = DEFAULT_R1_T01_CONFIG,
    r1_t01_evidence_path: Path = DEFAULT_R1_T01_EVIDENCE,
    r0_t10_evidence_path: Path = DEFAULT_R0_T10_EVIDENCE,
    r0_t11_evidence_path: Path = DEFAULT_R0_T11_EVIDENCE,
    r0_strict_past_evidence_path: Path = R0_STRICT_PAST_EVIDENCE,
    strict_artifact_hashes: bool = True,
) -> dict[str, Any]:
    ctx = AuditContext(root=root)
    run_id = run_id or _default_run_id()
    config = _load_json(config_path, ctx, "config_json")
    r1_t01_config = _load_json(r1_t01_config_path, ctx, "r1_t01_config_json")
    r1_t01_evidence = _parse_evidence(r1_t01_evidence_path)
    r0_t10_evidence = _parse_evidence(r0_t10_evidence_path)
    r0_t11_evidence = _parse_evidence(r0_t11_evidence_path)
    r0_strict_past_evidence = _parse_evidence(r0_strict_past_evidence_path)

    _check_evidence_status(ctx, "r1_t01_evidence", r1_t01_evidence, "R1-T01")
    _check_evidence_status(ctx, "r0_t10_05_evidence", r0_t10_evidence, "R0-T10-05")
    _check_evidence_status(ctx, "r0_t11_evidence", r0_t11_evidence, "R0-T11")
    _check_evidence_status(
        ctx,
        "strict_past_evidence_chain_check",
        r0_strict_past_evidence,
        "R0-T10-02",
    )
    _check_config_contract(ctx, config)
    _check_r1_t01_lock(ctx, r1_t01_config, r1_t01_evidence)

    auth_path = _resolve_manifest_path(
        ctx,
        r1_t01_config,
        r0_t10_evidence,
        "authorized_input_manifest_path",
    )
    full_grid_path = _resolve_manifest_path(
        ctx,
        r1_t01_config,
        r0_t10_evidence,
        "full_grid_manifest_path",
        evidence_key="global_manifest_path",
    )
    authorized = _load_json(auth_path, ctx, "authorized_input_manifest_json")
    full_grid = _load_json(full_grid_path, ctx, "full_grid_manifest_json")

    counts = _audit_authorized_manifest(ctx, authorized)
    full_grid_counts = _audit_full_grid_manifest(ctx, full_grid)
    counts.update(full_grid_counts)
    _check_hashes(ctx, r1_t01_config, auth_path, full_grid_path)
    if strict_artifact_hashes:
        _check_config_artifact_hashes(ctx, full_grid)
    else:
        ctx.warnings.append("strict_artifact_hashes disabled")
        ctx.checks["config_artifact_hashes"] = "skipped"
    _check_forbidden_tokens(ctx, authorized, "authorized_input_manifest")
    _check_forbidden_tokens(ctx, full_grid, "full_grid_manifest")
    _check_row_payload_absence(ctx, authorized, full_grid)
    _check_unknown_blocked_semantics(ctx, authorized, full_grid)
    _check_evidence_chain_hash(ctx, r0_t10_evidence_path, r0_t11_evidence)

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "r1_t02_lineage_pit_audit_summary.json"
    status = "completed" if not ctx.errors else "blocked"
    summary: dict[str, Any] = {
        "task_id": "R1-T02",
        "run_id": run_id,
        "status": status,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "code_commit": code_commit,
        "config_path": ctx.relative(config_path),
        "config_sha256": sha256_file(config_path) if config_path.exists() else None,
        "r1_t01_config_path": ctx.relative(r1_t01_config_path),
        "r1_t01_config_sha256": sha256_file(r1_t01_config_path)
        if r1_t01_config_path.exists()
        else None,
        "r1_t01_evidence_path": ctx.relative(r1_t01_evidence_path),
        "r1_t01_evidence_sha256": sha256_file(r1_t01_evidence_path)
        if r1_t01_evidence_path.exists()
        else None,
        "r0_t10_05_evidence_path": ctx.relative(r0_t10_evidence_path),
        "r0_t10_05_evidence_sha256": sha256_file(r0_t10_evidence_path)
        if r0_t10_evidence_path.exists()
        else None,
        "r0_t11_evidence_path": ctx.relative(r0_t11_evidence_path),
        "r0_t11_evidence_sha256": sha256_file(r0_t11_evidence_path)
        if r0_t11_evidence_path.exists()
        else None,
        "r0_strict_past_evidence_path": ctx.relative(r0_strict_past_evidence_path),
        "r0_strict_past_evidence_sha256": sha256_file(r0_strict_past_evidence_path)
        if r0_strict_past_evidence_path.exists()
        else None,
        "authorized_input_manifest_path": ctx.relative(auth_path),
        "authorized_input_manifest_sha256": sha256_file(auth_path)
        if auth_path.exists()
        else None,
        "full_grid_manifest_path": ctx.relative(full_grid_path),
        "full_grid_manifest_sha256": sha256_file(full_grid_path)
        if full_grid_path.exists()
        else None,
        "checks": ctx.checks,
        "counts": counts,
        "warnings": ctx.warnings,
        "blocked_reasons": ctx.errors,
        "row_payload_embedded": False,
        "point_in_time_scope": "manifest_and_lineage_only",
        "strict_past_artifact_field_check": "evidence_chain_only"
        if status == "completed"
        else "blocked",
        "confirmation_time_backfill_check": "skipped_zero_interval_input_fact"
        if counts.get("confirmed_interval_row_count_total") == 0
        else "passed",
        "validation_result_path": None,
        "validation_result_sha256": None,
        "downstream_gates": {
            "R1-T03_allowed_to_start": status == "completed",
            "R1-T07_allowed_to_start": False,
            "R2_allowed_to_start": False,
        },
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary["summary_path"] = ctx.relative(summary_path)
    summary["summary_sha256"] = sha256_file(summary_path)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def attach_validation_result(
    summary_path: Path, validation_result_path: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["validation_result_path"] = _display_path(validation_result_path, root)
    summary["validation_result_sha256"] = sha256_file(validation_result_path)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary["summary_sha256"] = sha256_file(summary_path)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id() -> str:
    return "R1-T02-" + datetime.now(UTC).strftime("%Y%m%dT%H%MZ")


def _load_json(path: Path, ctx: AuditContext, check_key: str) -> dict[str, Any]:
    if not path.exists():
        ctx.fail_check(check_key, f"missing:{ctx.relative(path)}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        ctx.fail_check(check_key, str(exc))
        return {}
    if not isinstance(payload, dict):
        ctx.fail_check(check_key, "top_level_not_object")
        return {}
    ctx.pass_check(check_key)
    return payload


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


def _check_evidence_status(
    ctx: AuditContext, key: str, evidence: dict[str, str], task_id: str
) -> None:
    if not evidence:
        ctx.fail_check(key, "missing_or_unparseable")
        return
    if evidence.get("task_id") != task_id:
        ctx.fail_check(key, "task_id_mismatch")
        return
    if evidence.get("status") != "completed":
        ctx.fail_check(key, "status_not_completed")
        return
    if evidence.get("validator_status") not in {None, "passed"}:
        ctx.fail_check(key, "validator_not_passed")
        return
    ctx.pass_check(key)


def _check_config_contract(ctx: AuditContext, config: dict[str, Any]) -> None:
    required_paths = (
        "r1_t01_config_path",
        "r1_t01_evidence_path",
        "r0_input_package_lock_source",
    )
    missing_paths = [key for key in required_paths if not config.get(key)]
    required_checks = set(config.get("required_checks", []))
    missing_checks = {
        "strict_past_evidence_chain_check",
        "strict_past_artifact_field_check",
        "unknown_blocked_semantics_check",
        "confirmation_time_backfill_check",
        "forbidden_column_absence_check",
        "row_payload_absence_check",
        "validation_result_path_hash_check",
    } - required_checks
    zero_policy = config.get("zero_interval_policy", {})
    strict_artifacts = config.get("strict_artifacts", {})
    if missing_paths:
        ctx.fail_check("r1_t02_config_contract", "missing:" + ",".join(missing_paths))
    elif missing_checks:
        ctx.fail_check(
            "r1_t02_config_contract",
            "missing_checks:" + ",".join(sorted(missing_checks)),
        )
    elif zero_policy.get("confirmed_interval_row_count_total_zero_handling") != (
        "treat_as_input_fact_and_do_not_backfill"
    ):
        ctx.fail_check("r1_t02_config_contract", "zero_interval_policy_mismatch")
    elif strict_artifacts.get("hash_check") is not True:
        ctx.fail_check("r1_t02_config_contract", "strict_artifacts_hash_check_missing")
    else:
        ctx.pass_check("r1_t02_config_contract")


def _check_r1_t01_lock(
    ctx: AuditContext, config: dict[str, Any], evidence: dict[str, str]
) -> None:
    lock = config.get("r0_input_package_lock", {})
    downstream = config.get("downstream_authorization", {})
    if evidence.get("R1-T02_allowed_to_start") != "true":
        ctx.fail_check("r1_t01_gate", "R1-T02_not_allowed")
        return
    r1_t02_allowed = (
        downstream.get("R1_T02_allowed_to_start_when_validator_status_passed") is True
        or downstream.get("R1_T02_allowed_to_start_after_validator_pass") is True
    )
    if not r1_t02_allowed:
        ctx.fail_check("r1_t01_gate", "config_gate_not_true")
        return
    if downstream.get("downstream_R2_allowed_to_start") is not False:
        ctx.fail_check("r1_t01_gate", "R2_not_blocked")
        return
    if lock.get("selected_config_count") != 27:
        ctx.fail_check("r1_t01_gate", "selected_config_count_not_27")
        return
    ctx.pass_check("r1_t01_gate")


def _resolve_manifest_path(
    ctx: AuditContext,
    r1_t01_config: dict[str, Any],
    evidence: dict[str, str],
    lock_key: str,
    evidence_key: str | None = None,
) -> Path:
    lock = r1_t01_config.get("r0_input_package_lock", {})
    text = lock.get(lock_key) or evidence.get(evidence_key or lock_key) or ""
    path = (ctx.root / text).resolve() if text else Path("__missing__")
    return path


def _audit_authorized_manifest(
    ctx: AuditContext, manifest: dict[str, Any]
) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    if manifest.get("manifest_type") != "r0_t10_05_authorized_input_manifest":
        ctx.fail_check("authorized_manifest_contract", "manifest_type_mismatch")
        return counts
    if manifest.get("authorized_r0_input") is not True:
        ctx.fail_check("authorized_manifest_contract", "authorized_r0_input_not_true")
    elif manifest.get("row_payload_embedded") is not False:
        ctx.fail_check("authorized_manifest_contract", "row_payload_embedded_not_false")
    else:
        ctx.pass_check("authorized_manifest_contract")
    guards = manifest.get("forbidden_guards", {})
    missing_guards = [
        key for key in REQUIRED_FORBIDDEN_GUARDS if guards.get(key) is not True
    ]
    if missing_guards:
        ctx.fail_check("forbidden_guards", ",".join(missing_guards))
    else:
        ctx.pass_check("forbidden_guards")
    coverage = manifest.get("coverage", {})
    grid = manifest.get("grid", {})
    W_values = coverage.get("W") or coverage.get("W_coverage") or grid.get("W_values")
    q_values = coverage.get("q") or coverage.get("q_coverage") or grid.get("q_values")
    K_values = coverage.get("K") or coverage.get("K_coverage") or grid.get("K_values")
    state_names = coverage.get("state_names") or coverage.get("state_name_coverage")
    if W_values != EXPECTED_W or q_values != EXPECTED_Q or K_values != EXPECTED_K:
        ctx.fail_check("authorized_grid_coverage", "W_q_K_mismatch")
    elif state_names != list(EXPECTED_STATES):
        ctx.fail_check("authorized_grid_coverage", "state_names_mismatch")
    elif grid.get("selected_config_count") != 27:
        ctx.fail_check("authorized_grid_coverage", "selected_count_not_27")
    elif grid.get("baseline_config_id") != EXPECTED_BASELINE:
        ctx.fail_check("authorized_grid_coverage", "baseline_mismatch")
    else:
        ctx.pass_check("authorized_grid_coverage")
    counts["authorized_selected_config_count"] = grid.get("selected_config_count")
    counts["authorized_security_count"] = coverage.get("security_count")
    counts["authorized_date_min"] = coverage.get("date_min")
    counts["authorized_date_max"] = coverage.get("date_max")
    return counts


def _audit_full_grid_manifest(
    ctx: AuditContext, manifest: dict[str, Any]
) -> dict[str, Any]:
    counts = {
        "selected_config_count": manifest.get("selected_config_count"),
        "completed_config_count": manifest.get("completed_config_count"),
        "failed_config_count": manifest.get("failed_config_count"),
        "daily_candidate_row_count_total": manifest.get(
            "daily_candidate_row_count_total"
        ),
        "confirmed_interval_row_count_total": manifest.get(
            "confirmed_interval_row_count_total"
        ),
        "daily_confirmed_true_count_total": manifest.get(
            "daily_confirmed_true_count_total"
        ),
        "confirmed_interval_zero_config_count": manifest.get(
            "confirmed_interval_zero_config_count"
        ),
        "zero_interval_reason": manifest.get("zero_interval_reason"),
    }
    candidates = manifest.get("candidate_configs", [])
    selected_ids = manifest.get("selected_config_ids", [])
    artifacts = manifest.get("artifacts_by_config", {})
    if manifest.get("manifest_type") != "r0_t10_05_full_grid_manifest":
        ctx.fail_check("full_grid_manifest_contract", "manifest_type_mismatch")
    elif manifest.get("status") != "completed":
        ctx.fail_check("full_grid_manifest_contract", "status_not_completed")
    elif manifest.get("row_payload_embedded") is not False:
        ctx.fail_check("full_grid_manifest_contract", "row_payload_embedded_not_false")
    elif (
        manifest.get("selected_config_count") != 27
        or len(candidates) != 27
        or len(selected_ids) != 27
    ):
        ctx.fail_check("full_grid_manifest_contract", "config_count_not_27")
    elif (
        manifest.get("completed_config_count") != 27
        or manifest.get("failed_config_count") != 0
    ):
        ctx.fail_check("full_grid_manifest_contract", "completion_count_mismatch")
    else:
        ctx.pass_check("full_grid_manifest_contract")
    if _grid_values(candidates, "percentile_window_W") != EXPECTED_W:
        ctx.fail_check("full_grid_candidate_snapshots", "W_coverage_mismatch")
    elif _grid_values(candidates, "low_quantile_q") != EXPECTED_Q:
        ctx.fail_check("full_grid_candidate_snapshots", "q_coverage_mismatch")
    elif _grid_values(candidates, "confirmation_days_K") != EXPECTED_K:
        ctx.fail_check("full_grid_candidate_snapshots", "K_coverage_mismatch")
    elif not any(item.get("is_baseline_config") is True for item in candidates):
        ctx.fail_check("full_grid_candidate_snapshots", "baseline_snapshot_missing")
    elif set(selected_ids) != set(artifacts):
        ctx.fail_check("full_grid_candidate_snapshots", "artifact_config_set_mismatch")
    else:
        ctx.pass_check("full_grid_candidate_snapshots")
    if manifest.get("confirmed_interval_row_count_total") == 0:
        if manifest.get("daily_confirmed_true_count_total") != 0:
            ctx.fail_check("zero_interval_consistency", "daily_confirmed_true_not_zero")
        elif manifest.get("confirmed_interval_zero_config_count") != 27:
            ctx.fail_check("zero_interval_consistency", "zero_config_count_not_27")
        elif (
            manifest.get("zero_interval_reason")
            != "no_confirmed_segments_in_r0_t07_input"
        ):
            ctx.fail_check("zero_interval_consistency", "reason_mismatch")
        else:
            ctx.pass_check("zero_interval_consistency")
    else:
        ctx.pass_check("zero_interval_consistency")
    return counts


def _grid_values(items: list[dict[str, Any]], key: str) -> list[Any]:
    values = sorted({item.get(key) for item in items})
    return values


def _check_hashes(
    ctx: AuditContext,
    r1_t01_config: dict[str, Any],
    auth_path: Path,
    full_grid_path: Path,
) -> None:
    lock = r1_t01_config.get("r0_input_package_lock", {})
    mismatches = []
    if auth_path.exists() and lock.get(
        "authorized_input_manifest_sha256"
    ) != sha256_file(auth_path):
        mismatches.append("authorized_input_manifest_sha256")
    if full_grid_path.exists() and lock.get("full_grid_manifest_sha256") != sha256_file(
        full_grid_path
    ):
        mismatches.append("full_grid_manifest_sha256")
    if mismatches:
        ctx.fail_check("locked_manifest_hashes", ",".join(mismatches))
    else:
        ctx.pass_check("locked_manifest_hashes")


def _check_config_artifact_hashes(ctx: AuditContext, manifest: dict[str, Any]) -> None:
    artifacts = manifest.get("artifacts_by_config", {})
    mismatches: list[str] = []
    for config_id, meta in artifacts.items():
        for path_key, hash_key in (
            ("config_snapshot_path", None),
            ("DONE_path", None),
            ("daily_duckdb_path", "daily_duckdb_sha256"),
            ("daily_parquet_path", "daily_parquet_sha256"),
            ("interval_duckdb_path", "interval_duckdb_sha256"),
            ("interval_parquet_path", "interval_parquet_sha256"),
        ):
            raw_path = meta.get(path_key)
            if not raw_path:
                mismatches.append(f"{config_id}:{path_key}:missing")
                continue
            path = ctx.root / raw_path
            if not path.exists():
                mismatches.append(f"{config_id}:{path_key}:not_found")
                continue
            expected_hash = meta.get(hash_key) if hash_key else None
            if expected_hash and sha256_file(path) != expected_hash:
                mismatches.append(f"{config_id}:{hash_key}:mismatch")
    if mismatches:
        ctx.fail_check("config_artifact_hashes", ",".join(mismatches[:10]))
    else:
        ctx.pass_check("config_artifact_hashes")


def _check_forbidden_tokens(ctx: AuditContext, value: Any, label: str) -> None:
    found: set[str] = set()
    _collect_forbidden_tokens(value, found)
    if found:
        ctx.fail_check(f"{label}_forbidden_token_check", ",".join(sorted(found)))
    else:
        ctx.pass_check(f"{label}_forbidden_token_check")
    if label == "full_grid_manifest":
        if found:
            ctx.fail_check("forbidden_column_absence_check", ",".join(sorted(found)))
        else:
            ctx.pass_check("forbidden_column_absence_check")


def _collect_forbidden_tokens(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "forbidden_guards":
                continue
            text_key = str(key).lower()
            for token in FORBIDDEN_FIELD_TOKENS:
                if token in text_key:
                    found.add(token)
            _collect_forbidden_tokens(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_forbidden_tokens(item, found)
    elif isinstance(value, str):
        text = value.lower()
        for token in FORBIDDEN_FIELD_TOKENS:
            if token in text:
                found.add(token)


def _check_row_payload_absence(
    ctx: AuditContext, authorized: dict[str, Any], full_grid: dict[str, Any]
) -> None:
    if (
        authorized.get("row_payload_embedded") is False
        and full_grid.get("row_payload_embedded") is False
    ):
        ctx.pass_check("row_payload_absence_check")
    else:
        ctx.fail_check("row_payload_absence_check", "row_payload_embedded_not_false")


def _check_unknown_blocked_semantics(
    ctx: AuditContext, authorized: dict[str, Any], full_grid: dict[str, Any]
) -> None:
    forbidden_guard = authorized.get("forbidden_guards", {}).get("no_legacy_v1") is True
    has_unknown_coercion = _contains_text(full_grid, "fillna(0)") or _contains_text(
        full_grid, "unknown_to_false"
    )
    if forbidden_guard and not has_unknown_coercion:
        ctx.pass_check("unknown_blocked_semantics_check")
    else:
        ctx.fail_check("unknown_blocked_semantics_check", "unknown_or_blocked_coercion")


def _contains_text(value: Any, token: str) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_text(key, token) or _contains_text(item, token)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_text(item, token) for item in value)
    return token.lower() in str(value).lower()


def _check_evidence_chain_hash(
    ctx: AuditContext, r0_t10_path: Path, r0_t11_evidence: dict[str, str]
) -> None:
    if not r0_t10_path.exists():
        ctx.fail_check("r0_evidence_chain_hash", "r0_t10_missing")
        return
    expected_path = ctx.relative(r0_t10_path)
    if r0_t11_evidence.get("R0-T10-05_evidence_path") != expected_path:
        ctx.fail_check("r0_evidence_chain_hash", "r0_t11_path_mismatch")
        return
    if r0_t11_evidence.get("R0-T10-05_evidence_sha256") != sha256_file(r0_t10_path):
        ctx.fail_check("r0_evidence_chain_hash", "r0_t11_hash_mismatch")
        return
    ctx.pass_check("r0_evidence_chain_hash")


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
