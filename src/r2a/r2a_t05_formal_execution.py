"""Fail-closed orchestration for the R2A-T05 formal execution entry.

This module contains the future formal path and its preparation-only gates.  A
formal run is not possible with the committed candidate configuration because
``formal_run_allowed`` is deliberately false.  The preparation functions do
not create a RunRoot and do not open the Score database.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from src.r2a.r2a_t02_request_identity import load_canonical_request
from src.r2a.r2a_t03_dynamic_evaluator import evaluate_dynamic_request
from src.r2a.r2a_t03_output_contract import validate_dynamic_evaluation_output
from src.r2a.r2a_t05_ca_exit_decomposition import (
    REQUEST_ORDER,
    build_t05_candidate,
    load_t05_config,
)
from src.r2a.r2a_t05_formal_input_manifest import (
    CONFIG_PATH,
    FORMAL_SCOPE_ID,
    ROOT,
    FormalInputManifestError,
    _resolve_repository_path,
    load_authorized_input_manifest,
    load_formal_execution_config,
    sha256_file,
)
from src.r2a.r2a_t05_result_analysis import analyze_candidate
from src.r2a.r2a_t05_validator import detect_result_anomalies, validate_t05_candidate

FORMAL_CONFIG_PATH = CONFIG_PATH
FORMAL_CONFIG_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_formal_execution.schema.json"
RESULT_PACKAGE_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_result_package.schema.json"
RUN_PARENT_RELATIVE = "data/generated/r2a/r2a_t05/formal-runs"
RUN_ID_PATTERN = re.compile(r"^R2A-T05-\d{8}T\d{9}Z$")
COMPACT_REVIEW_DIR = "compact-review"
REQUEST_OUTPUT_DIR = "request-results"
T03_OUTPUT_TABLES = (
    "dynamic_request",
    "evaluation_scope",
    "daily_dimension_states",
    "daily_joint_states",
    "confirmed_intervals",
)
PROTECTED_CORE_PATHS = (
    "configs/r2a/r2a_t05_ca_exit_decomposition.v1.json",
    "schemas/r2a/r2a_t05_ca_exit_decomposition.schema.json",
    "schemas/r2a/r2a_t05_result_package.schema.json",
    "src/r2a/r2a_t05_ca_exit_decomposition.py",
    "src/r2a/r2a_t05_validator.py",
    "src/r2a/r2a_t05_result_analysis.py",
    "tests/r2a/test_r2a_t05_ca_exit_decomposition.py",
    "tests/r2a/test_r2a_t05_validator.py",
    "tests/r2a/test_r2a_t05_result_package_schema.py",
)


class FormalExecutionError(RuntimeError):
    """Raised when any formal preparation or execution gate blocks."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalExecutionError("json_input_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise FormalExecutionError("json_object_required", str(path))
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload, ensure_ascii=False, indent=2, sort_keys=True, default=str
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise FormalExecutionError("artifact_write_failed", str(path)) from error


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(text.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
    except OSError as error:
        raise FormalExecutionError("artifact_write_failed", str(path)) from error


def _json_cell(value: Any) -> Any:
    if isinstance(value, dict | list | tuple):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    return value


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _json_cell(row.get(key)) for key in fields})
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise FormalExecutionError("artifact_write_failed", str(path)) from error


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or " ".join(args)
        raise FormalExecutionError("git_command_failed", detail)
    return result.stdout.strip()


def _git_blob_bytes(repo_root: Path, revision: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{revision}:{relative_path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise FormalExecutionError("protected_git_blob_missing", relative_path)
    return bytes(result.stdout)


def _normalized_text_binding(
    data: bytes, relative_path: str
) -> tuple[str, str, bool, int]:
    if data.startswith(b"\xef\xbb\xbf"):
        raise FormalExecutionError("protected_file_bom", relative_path)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FormalExecutionError("protected_file_not_utf8", relative_path) from error
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if b"\r" in data:
        raise FormalExecutionError("protected_file_non_lf", relative_path)
    trailing_lf_count = 1 if data.endswith(b"\n") else 0
    if trailing_lf_count != 1:
        raise FormalExecutionError("protected_file_trailing_lf_contract", relative_path)
    if normalized != data:
        raise FormalExecutionError(
            "protected_file_normalization_mismatch", relative_path
        )
    return (
        hashlib.sha256(data).hexdigest(),
        hashlib.sha256(normalized).hexdigest(),
        False,
        trailing_lf_count,
    )


def inspect_git_preflight(
    *,
    repo_root: str | Path = ROOT,
    config: Mapping[str, Any],
    expected_source_commit: str | None = None,
) -> dict[str, Any]:
    """Validate HEAD, clean worktree and all protected committed blobs."""

    root = Path(repo_root).resolve()
    head = _git(root, "rev-parse", "HEAD")
    reviewed = str(config["reviewed_implementation_sha"])
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise FormalExecutionError("current_git_head_invalid", head)
    if _git(root, "merge-base", "--is-ancestor", reviewed, head) != "":
        # ``git merge-base --is-ancestor`` writes no stdout on success; the
        # command wrapper raises on failure.  This branch is defensive only.
        raise FormalExecutionError("reviewed_implementation_not_ancestor")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise FormalExecutionError("dirty_worktree", status)
    if expected_source_commit is not None and head != expected_source_commit:
        raise FormalExecutionError("manifest_source_commit_mismatch", head)
    if (
        tuple(item["path"] for item in config["protected_implementation_files"])
        != PROTECTED_CORE_PATHS
    ):
        raise FormalExecutionError("protected_file_set_mismatch")

    checked: list[dict[str, Any]] = []
    for protected in config["protected_implementation_files"]:
        relative = str(protected["path"])
        actual_blob = _git(root, "rev-parse", f"{head}:{relative}")
        if actual_blob != protected["git_blob_sha"]:
            raise FormalExecutionError("protected_file_git_blob_mismatch", relative)
        data = _git_blob_bytes(root, head, relative)
        committed_sha, normalized_sha, bom, trailing_lf_count = (
            _normalized_text_binding(data, relative)
        )
        if committed_sha != protected["committed_byte_sha256"]:
            raise FormalExecutionError("protected_file_byte_hash_mismatch", relative)
        if normalized_sha != protected["normalized_text_sha256"]:
            raise FormalExecutionError(
                "protected_file_normalized_hash_mismatch", relative
            )
        if (
            bom is not protected["bom"]
            or trailing_lf_count != protected["trailing_lf_count"]
        ):
            raise FormalExecutionError(
                "protected_file_text_contract_mismatch", relative
            )
        checked.append(
            {"path": relative, "git_blob_sha": actual_blob, "sha256": committed_sha}
        )
    return {"head": head, "worktree_status": "clean", "protected_files": checked}


def _manifest_request_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    requests = manifest.get("requests")
    if not isinstance(requests, list):
        raise FormalExecutionError("manifest_requests_invalid")
    names = tuple(str(item.get("logical_request_name")) for item in requests)
    if names != REQUEST_ORDER:
        raise FormalExecutionError("request_order_mutation", names)
    return {str(item["logical_request_name"]): item for item in requests}


def _validate_config_manifest_identity(
    config: Mapping[str, Any], manifest: Mapping[str, Any]
) -> None:
    if (
        manifest.get("task_id") != "R2A-T05"
        or manifest.get("formal_scope_id") != FORMAL_SCOPE_ID
    ):
        raise FormalExecutionError("manifest_scope_mismatch")
    if (
        manifest.get("reviewed_implementation_sha")
        != config["reviewed_implementation_sha"]
    ):
        raise FormalExecutionError("manifest_reviewed_sha_mismatch")
    if tuple(config["request_order"]) != REQUEST_ORDER:
        raise FormalExecutionError("config_request_order_mismatch")
    if (
        tuple(item["logical_request_name"] for item in config["request_sources"])
        != REQUEST_ORDER
    ):
        raise FormalExecutionError("config_request_source_order_mismatch")
    manifest_requests = _manifest_request_map(manifest)
    config_requests = {
        str(item["logical_request_name"]): item for item in config["requests"]
    }
    for name in REQUEST_ORDER:
        for key in (
            "request_id",
            "request_hash",
            "selected_dimensions",
            "q_by_dimension",
            "confirmation_k",
            "selection_status",
        ):
            if manifest_requests[name].get(key) != config_requests[name].get(key):
                raise FormalExecutionError("request_identity_mismatch", name)
    if manifest.get("accepted_t04_counts") != config.get("accepted_t04_counts"):
        raise FormalExecutionError("accepted_t04_count_mismatch")
    score = manifest.get("score_database", {})
    expected_score = config["accepted_bindings"]["score_release"]
    for key in ("relative_path", "score_release_id", "sha256", "byte_size"):
        if score.get(key) != expected_score.get(key):
            raise FormalExecutionError("score_manifest_identity_mismatch", key)


def preflight_formal_execution(
    *,
    manifest_path: str | Path,
    repo_root: str | Path = ROOT,
    config_path: str | Path = FORMAL_CONFIG_PATH,
    verify_manifest_files: bool = False,
) -> dict[str, Any]:
    """Run all non-mutating preparation gates and return an execution plan."""

    try:
        config = load_formal_execution_config(config_path)
        manifest = load_authorized_input_manifest(
            manifest_path,
            repo_root=repo_root,
            verify_files=verify_manifest_files,
        )
    except (FormalInputManifestError, OSError) as error:
        raise FormalExecutionError(
            getattr(error, "reason_code", "formal_input_preflight_failed"), str(error)
        ) from error
    _validate_config_manifest_identity(config, manifest)
    git = inspect_git_preflight(
        repo_root=repo_root,
        config=config,
        expected_source_commit=str(manifest["source_commit"]),
    )
    return {
        "status": "preflight_passed",
        "task_id": "R2A-T05",
        "formal_scope_id": FORMAL_SCOPE_ID,
        "current_head": git["head"],
        "reviewed_implementation_sha": config["reviewed_implementation_sha"],
        "request_order": list(REQUEST_ORDER),
        "manifest_path": str(Path(manifest_path)),
        "manifest_verified_files": verify_manifest_files,
        "formal_run_allowed": bool(config["formal_run_allowed"]),
        "formal_run_started": False,
        "real_score_data_read": False,
        "formal_artifacts_generated": False,
        "formal_run_attempts_consumed": int(config["formal_run_attempts_consumed"]),
        "R2A-T05_DONE": "absent",
        "R2A-T06_allowed_to_start": False,
    }


def build_run_id(now: datetime | None = None) -> str:
    timestamp = (
        (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%S%f")[:-3]
    )
    run_id = f"R2A-T05-{timestamp}Z"
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise FormalExecutionError("run_id_format_invalid", run_id)
    return run_id


def create_unique_run_root(
    *,
    repo_root: str | Path = ROOT,
    run_id: str | None = None,
) -> tuple[Path, str]:
    """Create exactly one new RunRoot; never resume or overwrite one."""

    root = Path(repo_root).resolve()
    parent, _ = _resolve_repository_path(root, RUN_PARENT_RELATIVE, require_file=False)
    if parent.exists() and parent.is_symlink():
        raise FormalExecutionError("run_parent_reparse_point")
    parent.mkdir(parents=True, exist_ok=True)
    selected = run_id or build_run_id()
    if not RUN_ID_PATTERN.fullmatch(selected):
        raise FormalExecutionError("run_id_format_invalid", selected)
    run_root = parent / selected
    if run_root.exists():
        raise FormalExecutionError("run_root_already_exists", str(run_root))
    prior_runs = [
        child
        for child in parent.iterdir()
        if child.is_dir() and RUN_ID_PATTERN.fullmatch(child.name)
    ]
    if prior_runs:
        raise FormalExecutionError("formal_run_attempt_already_consumed")
    try:
        run_root.mkdir()
    except FileExistsError as error:
        raise FormalExecutionError("run_root_already_exists", str(run_root)) from error
    return run_root, selected


def _request_summary(output_path: Path) -> dict[str, int]:
    try:
        with duckdb.connect(str(output_path), read_only=True) as connection:
            raw_true = int(
                connection.execute(
                    "SELECT count(*) FROM daily_joint_states WHERE raw_state IS TRUE"
                ).fetchone()[0]
            )
            confirmed_true = int(
                connection.execute(
                    "SELECT count(*) FROM daily_joint_states "
                    "WHERE confirmed_state IS TRUE"
                ).fetchone()[0]
            )
            intervals = int(
                connection.execute(
                    "SELECT count(*) FROM confirmed_intervals"
                ).fetchone()[0]
            )
            securities = int(
                connection.execute(
                    "SELECT count(DISTINCT security_id) FROM confirmed_intervals"
                ).fetchone()[0]
            )
    except duckdb.Error as error:
        raise FormalExecutionError(
            "request_summary_failed", str(output_path)
        ) from error
    return {
        "raw_true": raw_true,
        "confirmed_true": confirmed_true,
        "intervals": intervals,
        "securities_with_interval": securities,
    }


def execute_request_sequence(
    *,
    request_order: Sequence[str],
    request_sources: Mapping[str, Path],
    output_dir: Path,
    evaluate: Callable[[str, Path, Path], Any],
    validate: Callable[[str, Path], Mapping[str, Any]],
    expected_counts: Mapping[str, Mapping[str, int]] | None = None,
    summarize: Callable[[Path], Mapping[str, int]] | None = None,
) -> tuple[dict[str, Path], dict[str, Mapping[str, Any]], dict[str, Mapping[str, int]]]:
    """Evaluate and validate four fresh requests in their frozen order."""

    if tuple(request_order) != REQUEST_ORDER or tuple(request_sources) != REQUEST_ORDER:
        raise FormalExecutionError("request_order_mutation")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    receipts: dict[str, Mapping[str, Any]] = {}
    summaries: dict[str, Mapping[str, int]] = {}
    for name in REQUEST_ORDER:
        source = Path(request_sources[name])
        target = output_dir / f"{name}.duckdb"
        if target.exists():
            raise FormalExecutionError(
                "partial_request_output_or_resume_rejected", name
            )
        try:
            evaluate(name, source, target)
        except Exception as error:
            raise FormalExecutionError("request_evaluation_failed", name) from error
        if not target.is_file():
            raise FormalExecutionError("partial_request_output", name)
        try:
            receipt = dict(validate(name, target))
        except Exception as error:
            raise FormalExecutionError("request_validator_failed", name) from error
        if receipt.get("status") != "passed":
            raise FormalExecutionError("request_validator_blocked", name)
        actual = dict((summarize or _request_summary)(target))
        if expected_counts is not None and actual != dict(expected_counts[name]):
            raise FormalExecutionError("accepted_t04_count_mismatch", name)
        outputs[name] = target
        receipts[name] = receipt
        summaries[name] = actual
    return outputs, receipts, summaries


def reconcile_t04_counts(
    summaries: Mapping[str, Mapping[str, int]],
    expected_counts: Mapping[str, Mapping[str, int]],
) -> None:
    if tuple(summaries) != REQUEST_ORDER:
        raise FormalExecutionError("request_summary_order_mismatch")
    for name in REQUEST_ORDER:
        if dict(summaries[name]) != dict(expected_counts[name]):
            raise FormalExecutionError("accepted_t04_count_mismatch", name)


def validate_formal_completion_lifecycle(payload: Mapping[str, Any]) -> None:
    expected = {
        "status": "formal_completed_pending_owner_review",
        "formal_run_started": True,
        "real_score_data_read": True,
        "formal_artifacts_generated": True,
        "R2A-T05_DONE": "absent",
        "R2A-T06_allowed_to_start": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise FormalExecutionError("lifecycle_mismatch", key)


def _write_detail_database(path: Path, candidate: Mapping[str, Any]) -> None:
    try:
        with duckdb.connect(str(path)) as connection:
            connection.execute("CREATE TABLE candidate_json (payload JSON NOT NULL)")
            connection.execute(
                "INSERT INTO candidate_json VALUES (?)",
                [
                    json.dumps(
                        candidate, ensure_ascii=False, sort_keys=True, default=str
                    )
                ],
            )
            connection.execute("CHECKPOINT")
    except duckdb.Error as error:
        raise FormalExecutionError("detail_database_write_failed", str(path)) from error


def _read_detail_database(path: Path) -> dict[str, Any]:
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            row = connection.execute("SELECT payload FROM candidate_json").fetchone()
    except duckdb.Error as error:
        raise FormalExecutionError("detail_database_read_failed", str(path)) from error
    if row is None:
        raise FormalExecutionError("detail_database_payload_missing")
    try:
        payload = json.loads(str(row[0]))
    except (TypeError, json.JSONDecodeError) as error:
        raise FormalExecutionError("detail_database_payload_invalid") from error
    if not isinstance(payload, dict):
        raise FormalExecutionError("detail_database_payload_not_object")
    return payload


def _formal_result_analysis(
    candidate: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    analysis = dict(analyze_candidate(candidate))
    anomalies = sorted(
        set(analysis.get("blocking_anomalies", []))
        | set(detect_result_anomalies(candidate))
    )
    analysis.update(
        {
            "status": "blocked" if anomalies else "formal_result_review_pending_owner",
            "scientific_review_status": "pending_owner_review",
            "blocking_anomalies": anomalies,
            "formal_run_executed": True,
            "formal_artifacts_generated": True,
            "real_score_data_read": True,
            "independent_validator_status": receipt.get("status"),
            "R2A-T05_DONE": "absent",
            "R2A-T06_allowed_to_start": False,
        }
    )
    return analysis


def _render_formal_result_analysis(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
    validation_receipt: Mapping[str, Any],
) -> str:
    reconciliation = candidate.get("request_reconciliation", [])
    lines = [
        "# R2A-T05 formal result analysis",
        "",
        (
            "This package is a formal result candidate pending owner review. The "
            "q20 request is a research anchor, not a selected or optimal q."
        ),
        "",
        "## Required evidence read",
        "",
        f"- T04 request reconciliation rows: {len(reconciliation)}",
        f"- termination records: {len(candidate.get('termination_records', []))}",
        f"- independent validator: {validation_receipt.get('status', 'not_run')}",
        f"- blocking anomalies: {len(analysis.get('blocking_anomalies', []))}",
        "",
        (
            "The review must cover primary termination categories, raw-false "
            "subclasses, signed endpoint margins and gate classes, raw/confirmed "
            "threshold responses, observable quick re-entry denominators, "
            "quality/censoring, q25 parent structure, q20 fragmentation, q25 "
            "shell conservation, global daily identity conservation, year "
            "profile, and security profile."
        ),
        "",
        "## Anomaly scan",
        "",
    ]
    anomalies = list(analysis.get("blocking_anomalies", []))
    if anomalies:
        lines.extend(f"- `{item}`" for item in anomalies)
    else:
        lines.append(
            "No blocking anomaly was found by the independent result-analysis scan."
        )
    lines.extend(
        [
            "",
            "## Lifecycle boundary",
            "",
            (
                "formal_run_started=true; real_score_data_read=true; "
                "formal_artifacts_generated=true; R2A-T05_DONE is absent; "
                "R2A-T06_allowed_to_start=false."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def finalize_formal_candidate(
    candidate: Mapping[str, Any],
    validation_receipt: Mapping[str, Any],
    *,
    analysis_function: Callable[
        [Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
    ]
    | None = None,
) -> tuple[dict[str, Any], str]:
    """Apply the independent-validator and result-analysis promotion gates."""

    if validation_receipt.get("status") != "passed":
        raise FormalExecutionError("independent_validator_blocked")
    analysis = dict(
        (analysis_function or _formal_result_analysis)(candidate, validation_receipt)
    )
    if analysis.get("status") == "blocked" or analysis.get("blocking_anomalies"):
        raise FormalExecutionError("result_analysis_blocked")
    return analysis, _render_formal_result_analysis(
        candidate, analysis, validation_receipt
    )


def _artifact_identity(root: Path, path: Path, storage_class: str) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {
        "relative_path": relative,
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
        "storage_class": storage_class,
    }


def _build_result_package(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    validation: Mapping[str, Any],
    artifacts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    request_identities = [
        {
            key: item[key]
            for key in (
                "logical_request_name",
                "request_id",
                "request_hash",
                "selected_dimensions",
                "q_by_dimension",
                "confirmation_k",
                "selection_status",
            )
        }
        for item in manifest["requests"]
    ]
    package = {
        "$schema": "../../schemas/r2a/r2a_t05_result_package.schema.json",
        "task_id": "R2A-T05",
        "package_schema_version": "r2a_t05_result_package.v1",
        "status": "formal_completed_pending_owner_review",
        "scope_id": "r2a_t05_ca_exit_mechanism_decomposition.v1",
        "research_anchor_q": 2000,
        "research_anchor_role": "exit_mechanism_decomposition",
        "q_selection_status": "not_selected",
        "canonical_dynamic_request_selected": False,
        "formal_run_started": True,
        "real_score_data_read": True,
        "formal_artifacts_generated": True,
        "R2A-T05_DONE": "absent",
        "R2A-T06_allowed_to_start": False,
        "request_identities": request_identities,
        "files": list(artifacts),
        "validation": {
            "status": "passed" if validation.get("status") == "passed" else "blocked",
            "independent_recalculation": bool(
                validation.get("independent_recalculation")
            ),
            "request_identity_match": bool(validation.get("request_identity_match")),
            "t04_reconciliation_match": bool(
                validation.get("t04_reconciliation_match")
            ),
            "cross_q_mapping_unique": bool(validation.get("cross_q_mapping_unique")),
            "daily_identity_conservation": bool(
                validation.get("daily_identity_conservation")
            ),
            "forbidden_input_fields_absent": bool(
                validation.get("forbidden_input_fields_absent")
            ),
            "deterministic_output": bool(validation.get("deterministic_output")),
            "blocking_reasons": list(validation.get("blocking_reasons", [])),
        },
    }
    validate_formal_completion_lifecycle(package)
    schema = _json(RESULT_PACKAGE_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            package
        ),
        key=str,
    )
    if errors:
        raise FormalExecutionError(
            "formal_result_package_schema_invalid", errors[0].message
        )
    return package


def _write_compact_review_package(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    candidate: Mapping[str, Any],
    run_summary: Mapping[str, Any],
    validation_receipt: Mapping[str, Any],
    result_analysis: str,
) -> list[Path]:
    compact = root / COMPACT_REVIEW_DIR
    compact.mkdir(parents=True, exist_ok=False)
    written: list[Path] = []
    request_identity = compact / "request_identity.json"
    _write_json(
        request_identity,
        {"request_order": list(REQUEST_ORDER), "requests": manifest["requests"]},
    )
    written.append(request_identity)
    manifest_copy = compact / "input_manifest.json"
    _write_json(manifest_copy, manifest)
    written.append(manifest_copy)
    summary_path = compact / "run_summary.json"
    _write_json(summary_path, run_summary)
    written.append(summary_path)
    validation_path = compact / "validation_receipt.json"
    _write_json(validation_path, validation_receipt)
    written.append(validation_path)
    analysis_path = compact / "result_analysis.md"
    _write_text(analysis_path, result_analysis)
    written.append(analysis_path)

    csv_sources = {
        "request_reconciliation.csv": "request_reconciliation",
        "termination_reason_profile.csv": "termination_reason_profile",
        "raw_false_exit_decomposition.csv": "raw_false_exit_decomposition",
        "threshold_margin_summary.csv": "threshold_margin_summary",
        "quick_reentry_profile.csv": "quick_reentry_profile",
        "cross_q_parent_structure_summary.csv": "cross_q_structure_summary",
        "cross_q_child_structure_summary.csv": "cross_q_child_structure_summary",
        "year_profile.csv": "year_profile",
        "security_profile.csv": "security_profile",
        "deterministic_interval_samples.csv": "deterministic_interval_samples",
    }
    for filename, key in csv_sources.items():
        target = compact / filename
        _write_csv(target, list(candidate.get(key, [])))
        written.append(target)
    alias = compact / "cross_q_structure_summary.csv"
    _write_csv(alias, list(candidate.get("cross_q_structure_summary", [])))
    written.append(alias)
    return written


def _log_event(path: Path, event: str, **details: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "utc_time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event": event,
        **details,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        )


def run_formal_execution(
    *,
    manifest_path: str | Path,
    repo_root: str | Path = ROOT,
    config_path: str | Path = FORMAL_CONFIG_PATH,
    operator_authorized: bool = False,
) -> dict[str, Any]:
    """Execute the future formal path only after all owner gates pass.

    With the committed preparation config this function stops before reading
    the Score or creating a RunRoot.  The real-run branch is nevertheless kept
    explicit so that a later owner-authorized config cannot bypass the gates.
    """

    config = load_formal_execution_config(config_path)
    preflight = preflight_formal_execution(
        manifest_path=manifest_path,
        repo_root=repo_root,
        config_path=config_path,
        verify_manifest_files=False,
    )
    if not operator_authorized or config["formal_run_allowed"] is not True:
        raise FormalExecutionError("formal_run_not_authorized")
    if config["formal_run_attempts_consumed"] >= config["formal_run_attempt_limit"]:
        raise FormalExecutionError("formal_run_attempt_limit_exhausted")
    if config["formal_run_started"] or config["formal_artifacts_generated"]:
        raise FormalExecutionError("formal_run_lifecycle_already_started")

    try:
        manifest = load_authorized_input_manifest(
            manifest_path,
            repo_root=repo_root,
            verify_files=True,
        )
        run_root, run_id = create_unique_run_root(repo_root=repo_root)
    except (FormalInputManifestError, FormalExecutionError) as error:
        raise FormalExecutionError(
            getattr(error, "reason_code", "formal_run_input_preflight_failed"),
            str(error),
        ) from error

    log_path = run_root / "execution_log.jsonl"
    _log_event(log_path, "formal_run_started", run_id=run_id, preflight=preflight)
    try:
        _write_json(run_root / "input_manifest.json", manifest)
        _write_json(
            run_root / "authorization.json",
            {
                "run_id": run_id,
                "reviewed_implementation_sha": config["reviewed_implementation_sha"],
                "current_head": preflight["current_head"],
                "operator_authorized": True,
                "formal_run_attempt_limit": config["formal_run_attempt_limit"],
                "formal_run_attempts_consumed_before_start": config[
                    "formal_run_attempts_consumed"
                ],
                "run_root_policy": config["run_root_policy"],
            },
        )
        request_map = {
            str(item["logical_request_name"]): item
            for item in config["request_sources"]
        }
        request_paths: dict[str, Path] = {}
        for name in REQUEST_ORDER:
            relative = request_map[name]["relative_path"]
            request_paths[name], _ = _resolve_repository_path(repo_root, relative)

        score_path, _ = _resolve_repository_path(
            repo_root, manifest["score_database"]["relative_path"]
        )
        request_output_dir = run_root / REQUEST_OUTPUT_DIR

        def evaluate(name: str, source: Path, target: Path) -> Any:
            request = load_canonical_request(source)
            _log_event(
                log_path,
                "request_started",
                logical_request_name=name,
                request_id=request["request_id"],
            )
            result = evaluate_dynamic_request(
                score_database=score_path,
                canonical_request=request,
                output_database=target,
            )
            _log_event(
                log_path,
                "request_evaluated",
                logical_request_name=name,
                summary=str(result),
            )
            return result

        def validate(name: str, target: Path) -> Mapping[str, Any]:
            try:
                with duckdb.connect(str(target)) as connection:
                    summary = validate_dynamic_evaluation_output(connection)
            except (duckdb.Error, ValueError) as error:
                raise FormalExecutionError(
                    "request_output_validator_failed", name
                ) from error
            return {
                "status": "passed",
                "logical_request_name": name,
                "request_id": summary.request_id,
                "request_hash": summary.request_hash,
                "evaluated_security_count": summary.evaluated_security_count,
                "daily_dimension_state_count": summary.daily_dimension_state_count,
                "daily_joint_state_count": summary.daily_joint_state_count,
                "confirmed_interval_count": summary.confirmed_interval_count,
            }

        outputs, request_receipts, summaries = execute_request_sequence(
            request_order=REQUEST_ORDER,
            request_sources=request_paths,
            output_dir=request_output_dir,
            evaluate=evaluate,
            validate=validate,
            expected_counts=manifest["accepted_t04_counts"],
        )
        reconcile_t04_counts(summaries, manifest["accepted_t04_counts"])
        _log_event(log_path, "all_requests_validated", summaries=summaries)

        t05_config = load_t05_config()
        candidate = build_t05_candidate(outputs, score_path, config=t05_config)
        independent_validation = validate_t05_candidate(
            candidate,
            request_sources=outputs,
            score_source=score_path,
            config=t05_config,
        )
        detail_path = run_root / "t05_detail.duckdb"
        _write_detail_database(detail_path, candidate)
        candidate = _read_detail_database(detail_path)
        analysis, result_analysis = finalize_formal_candidate(
            candidate,
            independent_validation,
        )

        _write_json(
            run_root / "independent_validation_receipt.json", independent_validation
        )
        _write_json(run_root / "anomaly_scan.json", analysis)
        _write_text(run_root / "result_analysis.md", result_analysis)

        lifecycle = {
            "status": "formal_completed_pending_owner_review",
            "formal_run_started": True,
            "real_score_data_read": True,
            "formal_artifacts_generated": True,
            "R2A-T05_DONE": "absent",
            "R2A-T06_allowed_to_start": False,
        }
        validate_formal_completion_lifecycle(lifecycle)
        run_summary: dict[str, Any] = {
            "run_id": run_id,
            "task_id": "R2A-T05",
            "formal_scope_id": FORMAL_SCOPE_ID,
            "status": "formal_completed_pending_owner_review",
            "request_order": list(REQUEST_ORDER),
            "request_summaries": summaries,
            "request_validation_receipts": request_receipts,
            "reviewed_implementation_sha": config["reviewed_implementation_sha"],
            "formal_execution_head": preflight["current_head"],
            "formal_run_attempt_limit": config["formal_run_attempt_limit"],
            "formal_run_attempts_consumed": 1,
            **lifecycle,
        }
        _write_json(run_root / "run_summary.json", run_summary)
        compact_paths = _write_compact_review_package(
            root=run_root,
            manifest=manifest,
            candidate=candidate,
            run_summary=run_summary,
            validation_receipt=independent_validation,
            result_analysis=result_analysis,
        )
        artifacts = [
            _artifact_identity(run_root, path, "repository_local_ignored")
            for path in (
                *outputs.values(),
                detail_path,
                run_root / "independent_validation_receipt.json",
                run_root / "anomaly_scan.json",
                run_root / "result_analysis.md",
            )
        ]
        artifacts.extend(
            _artifact_identity(run_root, path, "compact_review_artifact")
            for path in compact_paths
        )
        package = _build_result_package(
            root=run_root,
            manifest=manifest,
            validation=independent_validation,
            artifacts=artifacts,
        )
        _write_json(run_root / "result_package.json", package)
        _log_event(log_path, "formal_run_completed_pending_owner_review", run_id=run_id)
        return {
            "run_root": str(run_root),
            "run_id": run_id,
            "run_summary": run_summary,
            "result_package": package,
        }
    except Exception as error:
        _log_event(
            log_path,
            "formal_run_failed_closed",
            reason_code=getattr(error, "reason_code", "formal_execution_failed"),
            detail=str(error),
            R2A_T05_DONE="absent",
            R2A_T06_allowed_to_start=False,
        )
        if isinstance(error, FormalExecutionError):
            raise
        raise FormalExecutionError("formal_execution_failed", str(error)) from error


__all__ = [
    "FORMAL_CONFIG_PATH",
    "FormalExecutionError",
    "PROTECTED_CORE_PATHS",
    "build_run_id",
    "create_unique_run_root",
    "execute_request_sequence",
    "finalize_formal_candidate",
    "inspect_git_preflight",
    "preflight_formal_execution",
    "reconcile_t04_counts",
    "run_formal_execution",
    "validate_formal_completion_lifecycle",
]
