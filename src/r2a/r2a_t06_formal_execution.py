"""Fail-closed staged formal runner for R2A-T06.

The committed preparation config keeps this runner disabled.  A future owner
authorization commit must bind the reviewed execution SHA, exact-SHA Quality
success and immutable manifest before this module discovers the Score input.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator

from src.r2a.r2a_t02_request_identity import build_canonical_request
from src.r2a.r2a_t03_dynamic_evaluator import evaluate_dynamic_request
from src.r2a.r2a_t03_output_contract import validate_dynamic_evaluation_output
from src.r2a.r2a_t06_consecutive_failure_exit import (
    REQUEST_ORDER,
    T06Error,
    build_t06_candidate,
)
from src.r2a.r2a_t06_formal_input_manifest import (
    APPROVED_IMPLEMENTATION_SHA,
    FormalInputManifestError,
    canonical_json_bytes,
    load_formal_execution_config,
    sha256_file,
    validate_manifest,
    validate_repository_relative_path,
    verify_committed_contract_bindings,
    verify_formal_accepted_metadata,
)
from src.r2a.r2a_t06_formal_result_analysis import (
    FormalResultAnalysisError,
    analyze_persisted_formal_artifacts,
    render_persisted_result_analysis,
)
from src.r2a.r2a_t06_result_package import (
    SCIENTIFIC_FILES,
    ResultPackageError,
    artifact_manifest,
    build_scientific_tables,
    create_stage_root,
    preserve_failed_stage,
    publish_stage_atomic,
    scientific_inventory,
    verify_artifact_manifest,
    write_scientific_stage,
)
from src.r2a.r2a_t06_validator import (
    T06ValidationError,
    validate_t06_candidate,
    validate_t06_result_package,
)

ROOT = Path(__file__).resolve().parents[2]
FORMAL_CONFIG_PATH = ROOT / "configs/r2a/r2a_t06_formal_execution.v1.json"
AUTHORIZATION_SCHEMA_PATH = (
    ROOT / "schemas/r2a/r2a_t06_formal_authorization.schema.json"
)
FORMAL_REQUIRED_FILES = SCIENTIFIC_FILES
M_ORDER = (1, 2, 3)


class FormalExecutionError(RuntimeError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalExecutionError("json_input_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise FormalExecutionError("json_object_required", str(path))
    return value


def _validate_authorization_schema(authorization: Mapping[str, Any]) -> None:
    schema = _json(AUTHORIZATION_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(authorization)), key=str
    )
    if errors:
        raise FormalExecutionError(
            "formal_authorization_schema_invalid", errors[0].message
        )


def _git(repo_root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=repo_root, text=True, capture_output=True, check=False
    )
    if process.returncode:
        raise FormalExecutionError("git_preflight_failed", process.stderr.strip())
    return process.stdout.strip()


def inspect_git_preflight(repo_root: str | Path = ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    head = _git(root, "rev-parse", "HEAD")
    parent = _git(root, "rev-parse", "HEAD^")
    return {
        "head": head,
        "parent": parent,
        "clean": _git(root, "status", "--porcelain") == "",
    }


def _forbidden_path(value: Any, forbidden: set[str], prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key).lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if (
                name in forbidden
                or name.startswith("future_")
                or name.endswith("_return")
            ):
                return path
            found = _forbidden_path(nested, forbidden, path)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _forbidden_path(nested, forbidden, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _path_inside_data_root(repo_root: Path, relative: str) -> Path:
    safe = validate_repository_relative_path(relative)
    target = repo_root / safe
    data_root = (repo_root / "data").resolve()
    resolved = target.resolve(strict=False)
    if resolved != data_root and data_root not in resolved.parents:
        raise FormalExecutionError("input_path_outside_repository_data_root", relative)
    current = target
    while current != repo_root:
        try:
            file_attributes = getattr(current.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            file_attributes = 0
        if current.is_symlink() or bool(
            file_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise FormalExecutionError("input_reparse_or_symlink_rejected", relative)
        current = current.parent
    return target


def assert_formal_execution_authorized(
    authorization: Mapping[str, Any] | None,
    *,
    config: Mapping[str, Any] | None = None,
) -> None:
    loaded = dict(config or load_formal_execution_config())
    if authorization is None:
        raise FormalExecutionError("owner_formal_authorization_missing")
    _validate_authorization_schema(authorization)
    if loaded.get("formal_run_allowed") is not True:
        raise FormalExecutionError("formal_run_not_authorized_preparation_stage")
    if authorization.get("owner_authorized") is not True:
        raise FormalExecutionError("owner_formal_authorization_missing")


def _attempt_marker_path(run_root: Path) -> Path:
    return run_root.with_name(run_root.name + ".attempt-consumed.json")


def _run_state_conflicts(run_root: Path) -> list[Path]:
    parent = run_root.parent
    run_id = run_root.name
    patterns = (
        f".{run_id}.staging-*",
        f".{run_id}.staging-*.failed",
        f".{run_id}.reserved*",
        f"{run_id}.failed",
        f"{run_id}.reserved*",
    )
    conflicts = [run_root] if run_root.exists() else []
    for pattern in patterns:
        conflicts.extend(parent.glob(pattern))
    return sorted(set(conflicts))


def consume_formal_attempt(
    run_root: Path,
    authorization: Mapping[str, Any],
    *,
    consumed_at: str | None = None,
) -> Path:
    """Atomically and permanently consume the one authorized formal attempt."""

    marker = _attempt_marker_path(run_root)
    if marker.exists():
        raise FormalExecutionError("formal_attempt_already_consumed")
    conflicts = _run_state_conflicts(run_root)
    if conflicts:
        if run_root in conflicts:
            raise FormalExecutionError("run_root_collision", str(run_root))
        raise FormalExecutionError(
            "formal_run_state_conflict", ",".join(str(path) for path in conflicts)
        )
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": "R2A-T06",
        "run_id": authorization["run_id"],
        "run_root_relative_path": authorization["run_root_relative_path"],
        "authorization_revision": authorization["authorization_revision"],
        "reviewed_formal_execution_sha": authorization["reviewed_formal_execution_sha"],
        "authorization_commit_sha": authorization["authorization_commit_sha"],
        "manifest_sha256": authorization["manifest_sha256"],
        "consumed_at": consumed_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "formal_attempt_limit": authorization["formal_attempt_limit"],
        "attempt_number": 1,
        "status": "consumed",
    }
    content = canonical_json_bytes(payload)
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as error:
        raise FormalExecutionError("formal_attempt_already_consumed") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # A successfully created marker is never removed, even if its write fails.
        raise
    return marker


def _validate_score_identity(
    score_path: Path, score_release: Mapping[str, Any]
) -> dict[str, Any]:
    if not score_path.is_file():
        raise FormalExecutionError("score_file_missing", str(score_path))
    try:
        byte_size = score_path.stat().st_size
    except OSError as error:
        raise FormalExecutionError("score_identity_validation_failed") from error
    if byte_size != int(score_release["byte_size"]):
        raise FormalExecutionError("score_byte_size_mismatch")
    try:
        digest = sha256_file(score_path)
    except OSError as error:
        raise FormalExecutionError("score_identity_validation_failed") from error
    if digest != score_release["sha256"]:
        raise FormalExecutionError("score_sha256_mismatch")
    return {"sha256": digest, "byte_size": byte_size, "status": "passed"}


def preflight_formal_execution(
    *,
    authorization: Mapping[str, Any] | None,
    manifest_bytes: bytes | None,
    config: Mapping[str, Any] | None = None,
    repo_root: str | Path = ROOT,
    git_state: Mapping[str, Any] | None = None,
    input_discovery: Callable[[Path], Any] | None = None,
) -> dict[str, Any]:
    """Complete Stage 0 before the Score path is handed to any reader."""

    loaded = deepcopy(dict(config or load_formal_execution_config()))
    assert_formal_execution_authorized(authorization, config=loaded)
    assert authorization is not None
    if manifest_bytes is None:
        raise FormalExecutionError("authorized_manifest_missing")
    if authorization["approved_implementation_sha"] != APPROVED_IMPLEMENTATION_SHA:
        raise FormalExecutionError("approved_implementation_sha_mismatch")
    reviewed = str(authorization["reviewed_formal_execution_sha"])
    if not (
        authorization["execution_parent_sha"] == reviewed
        and authorization["authorization_commit_parent"] == reviewed
        and authorization["quality_sha"] == reviewed
        and authorization["quality_status"] == "completed"
        and authorization["quality_conclusion"] == "success"
    ):
        raise FormalExecutionError("authorization_exact_sha_binding_mismatch")
    if (
        authorization["formal_attempts_consumed"]
        >= authorization["formal_attempt_limit"]
    ):
        raise FormalExecutionError("formal_attempt_limit_exhausted")
    if hashlib.sha256(manifest_bytes).hexdigest() != authorization["manifest_sha256"]:
        raise FormalExecutionError("authorized_manifest_hash_mismatch")
    if len(manifest_bytes) != authorization["manifest_byte_size"]:
        raise FormalExecutionError("authorized_manifest_size_mismatch")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalExecutionError("authorized_manifest_invalid") from error
    try:
        validate_manifest(manifest)
    except FormalInputManifestError as error:
        raise FormalExecutionError(error.reason_code, str(error)) from error
    if (
        manifest.get("manifest_status") != "authorized_immutable"
        or manifest.get("superseded") is not False
    ):
        raise FormalExecutionError("authorized_manifest_status_invalid")
    if not (
        manifest["approved_implementation_sha"] == APPROVED_IMPLEMENTATION_SHA
        and manifest["reviewed_formal_execution_sha"] == reviewed
        and manifest["authorization_parent_sha"] == reviewed
        and manifest["authorization_commit_sha"]
        == authorization["authorization_commit_sha"]
        and manifest["authorization_revision"]
        == authorization["authorization_revision"]
    ):
        raise FormalExecutionError("manifest_authorization_binding_mismatch")
    state = dict(git_state or inspect_git_preflight(repo_root))
    if state.get("clean") is not True:
        raise FormalExecutionError("formal_worktree_not_clean")
    if state.get("head") != authorization["authorization_commit_sha"]:
        raise FormalExecutionError("authorization_head_mismatch")
    if state.get("parent") != reviewed:
        raise FormalExecutionError("authorization_parent_mismatch")
    if git_state is None:
        try:
            verify_committed_contract_bindings(
                repo_root, reviewed, manifest["committed_contract_bindings"]
            )
        except FormalInputManifestError as error:
            raise FormalExecutionError(error.reason_code, str(error)) from error
    elif state.get("committed_contract_bindings_verified") is not True:
        raise FormalExecutionError("committed_contract_bindings_not_verified")
    if manifest["execution_plan"] != loaded["execution_plan"]:
        raise FormalExecutionError("unauthorized_execution_plan_change")
    if manifest["accepted_counts"] != loaded["accepted_counts"]:
        raise FormalExecutionError("accepted_counts_binding_mismatch")
    if manifest["requests"] != loaded["requests"]:
        raise FormalExecutionError("request_identity_binding_mismatch")
    forbidden = {str(value).lower() for value in loaded["forbidden_input_fields"]}
    found = _forbidden_path(manifest, forbidden)
    if found:
        raise FormalExecutionError("forbidden_input_field", found)
    root = Path(repo_root).resolve()
    run_root = _path_inside_data_root(root, authorization["run_root_relative_path"])
    expected_parent = loaded["run_root_policy"]["parent_relative_path"]
    if run_root.parent != (root / expected_parent).resolve(strict=False):
        raise FormalExecutionError("run_root_parent_mismatch")
    for identity in manifest["accepted_handoffs"].values():
        _path_inside_data_root(root, identity["relative_path"])
    if git_state is None:
        try:
            verify_formal_accepted_metadata(root, loaded)
        except FormalInputManifestError as error:
            raise FormalExecutionError(error.reason_code, str(error)) from error
    elif state.get("accepted_metadata_verified") is not True:
        raise FormalExecutionError("accepted_metadata_not_verified")
    attempt_marker = consume_formal_attempt(run_root, authorization)
    score_path = _path_inside_data_root(
        root, manifest["score_release"]["relative_path"]
    )
    score_identity = _validate_score_identity(score_path, manifest["score_release"])
    if input_discovery is not None:
        input_discovery(score_path)
    return {
        "status": "passed",
        "head": state["head"],
        "reviewed_formal_execution_sha": reviewed,
        "run_root": str(run_root),
        "score_path": str(score_path),
        "score_identity": score_identity,
        "attempt_marker": str(attempt_marker),
        "manifest": manifest,
    }


def _request_summary(output_path: Path) -> dict[str, Any]:
    try:
        with duckdb.connect(str(output_path), read_only=True) as connection:
            request_row = connection.execute(
                "SELECT request_id, request_hash, score_release_id, "
                "evaluator_version, output_schema_version FROM dynamic_request"
            ).fetchone()
            scope_row = connection.execute(
                "SELECT evaluated_security_count, date_min, date_max, "
                "spine_row_count FROM evaluation_scope"
            ).fetchone()
            if request_row is None or scope_row is None:
                raise FormalExecutionError("request_receipt_metadata_missing")
            return {
                "request_id": str(request_row[0]),
                "request_hash": str(request_row[1]),
                "score_release_id": str(request_row[2]),
                "evaluator_version": str(request_row[3]),
                "output_schema_version": str(request_row[4]),
                "evaluated_security_count": int(scope_row[0]),
                "date_min": str(scope_row[1]),
                "date_max": str(scope_row[2]),
                "spine_row_count": int(scope_row[3]),
                "daily_joint_state_count": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_joint_states"
                    ).fetchone()[0]
                ),
                "daily_dimension_state_count": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_dimension_states"
                    ).fetchone()[0]
                ),
                "confirmed_interval_count": int(
                    connection.execute(
                        "SELECT count(*) FROM confirmed_intervals"
                    ).fetchone()[0]
                ),
                "raw_true": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_joint_states "
                        "WHERE raw_state IS TRUE"
                    ).fetchone()[0]
                ),
                "confirmed_true": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_joint_states "
                        "WHERE confirmed_state IS TRUE"
                    ).fetchone()[0]
                ),
                "intervals": int(
                    connection.execute(
                        "SELECT count(*) FROM confirmed_intervals"
                    ).fetchone()[0]
                ),
                "securities_with_interval": int(
                    connection.execute(
                        "SELECT count(DISTINCT security_id) FROM confirmed_intervals"
                    ).fetchone()[0]
                ),
            }
    except duckdb.Error as error:
        raise FormalExecutionError(
            "request_summary_failed", str(output_path)
        ) from error


def execute_request_sequence(
    *,
    requests: Sequence[Mapping[str, Any]],
    output_dir: Path,
    evaluate: Callable[[Mapping[str, Any], Path], Any],
    validate: Callable[[Mapping[str, Any], Path], Mapping[str, Any]],
    summarize: Callable[[Path], Mapping[str, Any]],
    expected_counts: Mapping[str, Mapping[str, int]],
    score_release: Mapping[str, Any],
    evaluator_identity: Mapping[str, Any],
    expected_spine_row_count: int,
    request_concurrency: int = 1,
    on_event: Callable[[str, Mapping[str, Any]], None] | None = None,
) -> tuple[dict[str, Path], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    names = tuple(str(item["logical_request_name"]) for item in requests)
    if names != REQUEST_ORDER:
        raise FormalExecutionError("request_order_mutation")
    if request_concurrency != 1:
        raise FormalExecutionError("q_level_concurrency_rejected")
    output_dir.mkdir(parents=True, exist_ok=False)
    outputs: dict[str, Path] = {}
    receipts: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    evaluated: Counter[str] = Counter()
    for request in requests:
        name = str(request["logical_request_name"])
        target = output_dir / f"{name}.duckdb"
        if target.exists():
            raise FormalExecutionError(
                "partial_request_output_or_resume_rejected", name
            )
        evaluated[name] += 1
        if on_event:
            on_event("request_started", {"logical_request_name": name})
        evaluate(request, target)
        if not target.is_file():
            raise FormalExecutionError("partial_request_output", name)
        validation = dict(validate(request, target))
        if validation.get("status") != "passed":
            raise FormalExecutionError("request_validator_blocked", name)
        actual = {"logical_request_name": name, **dict(summarize(target))}
        expected_identity = {
            "request_id": request["request_id"],
            "request_hash": request["request_hash"],
            "score_release_id": score_release["score_release_id"],
            "evaluator_version": evaluator_identity["evaluator_version"],
            "output_schema_version": evaluator_identity["output_schema_version"],
            "evaluated_security_count": score_release["security_count"],
            "date_min": score_release["date_min"],
            "date_max": score_release["date_max"],
            "spine_row_count": expected_spine_row_count,
            "daily_joint_state_count": expected_spine_row_count,
            "daily_dimension_state_count": expected_spine_row_count * 2,
            "confirmed_interval_count": expected_counts[name]["intervals"],
            **expected_counts[name],
        }
        reason_codes = {
            "request_id": "request_id_mismatch",
            "request_hash": "request_hash_mismatch",
            "score_release_id": "score_release_id_mismatch",
            "evaluator_version": "evaluator_version_mismatch",
            "output_schema_version": "output_schema_version_mismatch",
            "evaluated_security_count": "evaluated_security_count_mismatch",
            "date_min": "date_min_mismatch",
            "date_max": "date_max_mismatch",
            "spine_row_count": "spine_row_count_mismatch",
            "daily_joint_state_count": "daily_joint_state_count_mismatch",
            "daily_dimension_state_count": "daily_dimension_state_count_mismatch",
            "confirmed_interval_count": "confirmed_interval_count_mismatch",
        }
        for key, expected in expected_identity.items():
            if actual.get(key) != expected:
                raise FormalExecutionError(
                    reason_codes.get(key, "accepted_t04_t05_count_mismatch"), name
                )
        actual["status"] = "passed"
        if on_event:
            on_event(
                "request_validated",
                {"logical_request_name": name, "receipt": actual},
            )
        if on_event:
            on_event(
                "request_reconciled",
                {"logical_request_name": name, "receipt": actual},
            )
        outputs[name] = target
        receipts[name] = actual
        summaries[name] = actual
    if set(evaluated.values()) != {1}:
        raise FormalExecutionError("request_evaluation_count_invalid")
    return outputs, receipts, summaries


def load_daily_facts(
    output_path: Path, request: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Read accepted T03 daily facts and C/A activity without changing semantics."""

    query = """
        SELECT j.security_id, j.trading_date, j.observation_sequence,
               j.expected_observation_status, j.joint_validity_status,
               j.joint_ready, j.joint_reason_codes, j.raw_state,
               j.confirmed_state AS confirmed_state_v1,
               j.confirmed_interval_ordinal,
               max(CASE WHEN d.dimension_id='C'
                        THEN d.dimension_active END) AS c_active,
               max(CASE WHEN d.dimension_id='A'
                        THEN d.dimension_active END) AS a_active,
               max(CASE WHEN d.dimension_id='C' THEN
                   least(d.score_dimension-d.main_threshold,
                         d.score_dimension_min-d.weak_threshold) END) AS c_margin,
               max(CASE WHEN d.dimension_id='A' THEN
                   least(d.score_dimension-d.main_threshold,
                         d.score_dimension_min-d.weak_threshold) END) AS a_margin
          FROM daily_joint_states j
          JOIN daily_dimension_states d USING
               (request_id, security_id, trading_date, observation_sequence)
         WHERE d.dimension_id IN ('C','A')
         GROUP BY ALL
         ORDER BY j.security_id, j.observation_sequence
    """
    try:
        with duckdb.connect(str(output_path), read_only=True) as connection:
            cursor = connection.execute(query)
            columns = [item[0] for item in cursor.description]
            records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except duckdb.Error as error:
        raise FormalExecutionError(
            "daily_fact_load_failed", str(output_path)
        ) from error
    output = []
    for row in records:
        output.append(
            {
                "logical_request_name": request["logical_request_name"],
                "security_id": str(row["security_id"]),
                "trading_date": str(row["trading_date"]),
                "observation_sequence": int(row["observation_sequence"]),
                "expected_observation_status": row["expected_observation_status"],
                "joint_validity_status": row["joint_validity_status"],
                "joint_ready": row["joint_ready"],
                "joint_reason_codes": list(row["joint_reason_codes"] or []),
                "raw_state": row["raw_state"],
                "confirmed_state_v1": row["confirmed_state_v1"],
                "confirmed_interval_ordinal": row["confirmed_interval_ordinal"],
                "dimension_active": {"C": row["c_active"], "A": row["a_active"]},
                "dimension_margin": {"C": row["c_margin"], "A": row["a_margin"]},
            }
        )
    return output


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes({"payload": value})).hexdigest()


def compare_formal_builds(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    left_hash = _fingerprint(left)
    right_hash = _fingerprint(right)
    return {
        "status": "passed" if left_hash == right_hash else "failed",
        "left_fingerprint": left_hash,
        "right_fingerprint": right_hash,
        "full_table_match": left_hash == right_hash,
    }


def _m1_baseline_keys(
    source: Mapping[str, Sequence[Mapping[str, Any]]],
) -> set[tuple[str, str, int]]:
    keys: set[tuple[str, str, int]] = set()
    for name in REQUEST_ORDER:
        active: dict[str, bool] = defaultdict(bool)
        for row in sorted(
            source[name],
            key=lambda item: (item["security_id"], item["observation_sequence"]),
        ):
            security = str(row["security_id"])
            if not active[security] and row["confirmed_state_v1"] is True:
                active[security] = True
            elif (
                active[security]
                and row["joint_ready"] is True
                and row["raw_state"] is False
            ):
                keys.add((name, security, int(row["observation_sequence"])))
                active[security] = False
            elif active[security] and row["joint_ready"] is not True:
                active[security] = False
    return keys


def _m1_candidate_keys(candidate: Mapping[str, Any]) -> set[tuple[str, str, int]]:
    return {
        (
            str(result["logical_request_name"]),
            str(row["security_id"]),
            int(row["exit_trigger_observation_sequence"]),
        )
        for result in candidate["candidates"]
        if int(result["exit_confirmation_m"]) == 1
        for row in result["trigger_rows"]
        if row["disposition"] == "EXIT_RECOGNIZED"
    }


def build_and_validate_lifecycle(
    source: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_before = _fingerprint(source)
    first = build_t06_candidate(source, worker_count=1)
    validation = validate_t06_candidate(source, first)
    second = build_t06_candidate(source, worker_count=1)
    determinism = compare_formal_builds(
        {"candidate": first, "compact_tables": build_scientific_tables(first)},
        {"candidate": second, "compact_tables": build_scientific_tables(second)},
    )
    if determinism["status"] != "passed":
        raise FormalExecutionError("two_build_determinism_mismatch")
    parallel = build_t06_candidate(source, worker_count=4)
    parallel_receipt = compare_formal_builds(
        {"candidate": first, "compact_tables": build_scientific_tables(first)},
        {"candidate": parallel, "compact_tables": build_scientific_tables(parallel)},
    )
    if parallel_receipt["status"] != "passed":
        raise FormalExecutionError("worker_1_worker_4_mismatch")
    if source_before != _fingerprint(source):
        raise FormalExecutionError("accepted_daily_fact_mutation")
    m1_match = _m1_candidate_keys(first) == _m1_baseline_keys(source)
    if not m1_match:
        raise FormalExecutionError("m1_baseline_reproduction_failed")
    receipt = {
        "status": "passed",
        "independent_recalculation": validation["independent_recalculation"],
        "accepted_daily_fact_immutability": True,
        "m1_baseline_exact_reproduction": True,
        "quality_interruption_fail_closed": (
            validation["quality_interruption_validation"] == "passed"
        ),
        "recognized_cancelled_set_nesting": (
            validation["recognized_episode_set_nesting"] == "passed"
            and validation["cancelled_episode_set_nesting"] == "passed"
        ),
        "trigger_anchored_false_run": (
            validation["false_run_inventory_recalculation"] == "passed"
        ),
        "hazard_recalculation": (
            validation["recovery_hazard_recalculation"] == "passed"
        ),
        "online_replay_equivalence": validation["online_replay_equivalence"],
        "parallel_consistency": True,
        "deterministic_output": True,
        "cross_q_nesting": validation["cross_q_nesting"] == "passed",
        "availability_evaluability_reconciliation": True,
    }
    return (
        first,
        receipt,
        {"canonical_builds": determinism, "worker_1_vs_4": parallel_receipt},
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _log(path: Path, event: str, **details: Any) -> None:
    record = {"event": event, **details}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        )


def _result_package_validation(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": receipt["status"],
        "independent_recalculation": receipt["independent_recalculation"],
        "accepted_daily_fact_immutability": receipt["accepted_daily_fact_immutability"],
        "online_replay_equivalence": receipt["online_replay_equivalence"],
        "deterministic_output": receipt["deterministic_output"],
        "parallel_consistency": receipt["parallel_consistency"],
        "cross_q_nesting": receipt["cross_q_nesting"],
    }


def run_formal_execution(
    *,
    authorization: Mapping[str, Any] | None,
    manifest_bytes: bytes | None,
    config: Mapping[str, Any] | None = None,
    repo_root: str | Path = ROOT,
    git_state: Mapping[str, Any] | None = None,
    evaluate_request: Callable[[Mapping[str, Any], Path, Path], Any] | None = None,
    validate_request: Callable[[Mapping[str, Any], Path], Mapping[str, Any]]
    | None = None,
    summarize_request: Callable[[Path], Mapping[str, Any]] = _request_summary,
    load_facts: Callable[
        [Path, Mapping[str, Any]], list[dict[str, Any]]
    ] = load_daily_facts,
    build_lifecycle: Callable[
        [Mapping[str, Sequence[Mapping[str, Any]]]],
        tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ] = build_and_validate_lifecycle,
) -> dict[str, Any]:
    loaded = deepcopy(dict(config or load_formal_execution_config()))
    preflight = preflight_formal_execution(
        authorization=authorization,
        manifest_bytes=manifest_bytes,
        config=loaded,
        repo_root=repo_root,
        git_state=git_state,
    )
    assert authorization is not None and manifest_bytes is not None
    manifest = preflight["manifest"]
    final_root = Path(preflight["run_root"])
    stage = create_stage_root(final_root.parent, authorization["run_id"])
    log_path = stage / "execution_log.jsonl"
    manifest_sealed = False
    _log(
        log_path,
        "stage_0_preflight_passed",
        reviewed_sha=preflight["reviewed_formal_execution_sha"],
    )
    try:
        score_path = Path(preflight["score_path"])

        def default_evaluate(request: Mapping[str, Any], target: Path) -> Any:
            canonical = build_canonical_request(
                {
                    "selected_dimensions": request["selected_dimensions"],
                    "q_by_dimension": request["q_by_dimension"],
                    "confirmation_k": request["confirmation_k"],
                }
            )
            if (
                canonical["request_id"] != request["request_id"]
                or canonical["request_hash"] != request["request_hash"]
            ):
                raise FormalExecutionError(
                    "canonical_request_identity_mismatch",
                    str(request["logical_request_name"]),
                )
            return evaluate_dynamic_request(
                score_database=score_path,
                canonical_request=canonical,
                output_database=target,
            )

        def default_validate(
            request: Mapping[str, Any], target: Path
        ) -> Mapping[str, Any]:
            with duckdb.connect(str(target), read_only=True) as connection:
                summary = validate_dynamic_evaluation_output(connection)
            if (
                summary.request_id != request["request_id"]
                or summary.request_hash != request["request_hash"]
            ):
                raise FormalExecutionError(
                    "request_identity_reconciliation_failed",
                    str(request["logical_request_name"]),
                )
            return {
                "status": "passed",
                "request_id": summary.request_id,
                "request_hash": summary.request_hash,
            }

        def evaluate_adapter(request: Mapping[str, Any], target: Path) -> Any:
            if evaluate_request is not None:
                return evaluate_request(request, target, score_path)
            return default_evaluate(request, target)

        outputs, request_receipts, request_summaries = execute_request_sequence(
            requests=manifest["requests"],
            output_dir=stage / "request-results",
            evaluate=evaluate_adapter,
            validate=validate_request or default_validate,
            summarize=summarize_request,
            expected_counts=manifest["accepted_counts"],
            score_release=manifest["score_release"],
            evaluator_identity=manifest["evaluator_identity"],
            expected_spine_row_count=manifest["accepted_coverage"]["spine_row_count"],
            request_concurrency=manifest["execution_plan"]["request_concurrency"],
            on_event=lambda event, details: _log(log_path, event, **details),
        )
        _log(log_path, "stage_1_four_q_reconciled", summaries=request_summaries)
        source = {
            name: load_facts(outputs[name], manifest["requests"][index])
            for index, name in enumerate(REQUEST_ORDER)
        }
        candidate, validation_receipt, determinism_receipt = build_lifecycle(source)
        _log(log_path, "stages_2_to_4_lifecycle_validated")
        run_summary = {
            "run_id": authorization["run_id"],
            "task_id": "R2A-T06",
            "status": "formal_completed_pending_owner_review",
            "approved_implementation_sha": APPROVED_IMPLEMENTATION_SHA,
            "reviewed_formal_execution_sha": authorization[
                "reviewed_formal_execution_sha"
            ],
            "request_order": list(REQUEST_ORDER),
            "m_candidate_order": list(M_ORDER),
            "request_summaries": request_summaries,
            "accepted_counts": manifest["accepted_counts"],
            "request_validation_receipts": request_receipts,
            "selected_exit_confirmation_m": None,
            "winner_selected": False,
            "formal_run_executed": True,
            "real_score_data_read": True,
            "formal_artifacts_generated": True,
            "R2A-T06_DONE": "absent",
            "R2A-T07_allowed_to_start": False,
            "R3_allowed_to_start": False,
        }
        placeholder = "Persisted artifact analysis pending.\n"
        scientific = write_scientific_stage(
            stage,
            candidate=candidate,
            manifest=manifest,
            run_summary=run_summary,
            validation_receipt=validation_receipt,
            result_analysis=placeholder,
        )
        preliminary = analyze_persisted_formal_artifacts(scientific)
        report = render_persisted_result_analysis(preliminary)
        (scientific / "result_analysis.md").write_text(
            report, encoding="utf-8", newline="\n"
        )
        analysis = analyze_persisted_formal_artifacts(scientific)
        _write_json(stage / "formal_authorization.json", dict(authorization))
        _write_json(stage / "determinism_receipt.json", determinism_receipt)
        _write_json(stage / "anomaly_scan.json", analysis)
        _log(
            log_path,
            "stage_6_actual_artifact_analysis_completed",
            status=analysis["status"],
        )
        files = scientific_inventory(scientific)
        package = {
            "task_id": "R2A-T06",
            "package_schema_version": "r2a_t06_result_package.v1",
            "status": "formal_completed_pending_owner_review",
            "scope_id": "r2a_t06_consecutive_failure_exit_confirmation.v1",
            "q_selection_status": "not_selected",
            "canonical_dynamic_request_selected": False,
            "winner_selected": False,
            "accepted_run_id": authorization["run_id"],
            "reviewed_implementation_sha": APPROVED_IMPLEMENTATION_SHA,
            "reviewed_execution_sha": authorization["reviewed_formal_execution_sha"],
            "owner_result_review": "pending",
            "result_analysis_status": analysis["result_analysis_status"],
            "blocking_anomaly_count": analysis["blocking_anomaly_count"],
            "selected_exit_confirmation_m": None,
            "selection_principle": "minimum_sufficient_complexity",
            "selection_evidence": [],
            "formal_run_executed": True,
            "real_score_data_read": True,
            "formal_artifacts_generated": True,
            "R2A-T06_DONE": "absent",
            "R2A-T07_allowed_to_start": False,
            "R3_allowed_to_start": False,
            "files": files,
            "validation": _result_package_validation(validation_receipt),
        }
        validate_t06_result_package(package)
        _write_json(stage / "result_package.json", package)
        _log(log_path, "stage_7_atomic_publication_ready")
        _write_json(stage / "artifact_manifest.json", artifact_manifest(stage))
        manifest_sealed = True
        publication_receipt = verify_artifact_manifest(stage)
        publish_stage_atomic(stage, final_root)
        post_publish_receipt = verify_artifact_manifest(final_root)
        return {
            "run_root": str(final_root),
            "result_package": package,
            "analysis": analysis,
            "publication_receipt": publication_receipt,
            "post_publish_receipt": post_publish_receipt,
        }
    except Exception as error:
        if stage.exists():
            if not manifest_sealed:
                _log(
                    log_path,
                    "formal_run_failed_closed",
                    reason_code=getattr(
                        error, "reason_code", "formal_execution_failed"
                    ),
                    detail=str(error),
                )
            preserve_failed_stage(stage)
        if isinstance(error, FormalExecutionError):
            raise
        if isinstance(
            error,
            T06Error
            | T06ValidationError
            | FormalResultAnalysisError
            | ResultPackageError
            | duckdb.Error,
        ):
            raise FormalExecutionError(
                getattr(error, "reason_code", "formal_execution_failed"), str(error)
            ) from error
        raise FormalExecutionError("formal_execution_failed", str(error)) from error


def run_formal(
    authorization: Mapping[str, Any] | None = None,
    *,
    manifest_bytes: bytes | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return run_formal_execution(
        authorization=authorization,
        manifest_bytes=manifest_bytes,
        config=config,
    )


__all__ = [
    "FORMAL_REQUIRED_FILES",
    "FormalExecutionError",
    "assert_formal_execution_authorized",
    "build_and_validate_lifecycle",
    "compare_formal_builds",
    "consume_formal_attempt",
    "execute_request_sequence",
    "inspect_git_preflight",
    "load_daily_facts",
    "preflight_formal_execution",
    "run_formal",
    "run_formal_execution",
]
