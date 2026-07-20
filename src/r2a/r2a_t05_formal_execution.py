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
from collections import Counter
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
    ANALYSIS_DIMENSIONS,
    CONFIG_PATH,
    FORMAL_AUTHORIZATION_PATH,
    FORMAL_AUTHORIZATION_SCHEMA_PATH,
    FORMAL_SCOPE_ID,
    REVIEWED_FORMAL_EXECUTION_SHA,
    ROOT,
    SCORE_DIMENSIONS,
    FormalInputManifestError,
    _resolve_repository_path,
    load_authorized_input_manifest,
    load_formal_execution_config,
    sha256_file,
)
from src.r2a.r2a_t05_formal_result_analysis import (
    FormalResultAnalysisError,
    analyze_persisted_formal_artifacts,
    render_persisted_result_analysis,
)
from src.r2a.r2a_t05_result_analysis import analyze_candidate
from src.r2a.r2a_t05_validator import detect_result_anomalies, validate_t05_candidate

FORMAL_CONFIG_PATH = CONFIG_PATH
FORMAL_CONFIG_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_formal_execution.schema.json"
RESULT_PACKAGE_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_result_package.schema.json"
AUTHORIZATION_CONFIG_PATH = FORMAL_AUTHORIZATION_PATH
AUTHORIZATION_SCHEMA_PATH = FORMAL_AUTHORIZATION_SCHEMA_PATH
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
PROTECTED_EXECUTION_PATHS = (
    "configs/r2a/r2a_t05_formal_execution.v1.json",
    "schemas/r2a/r2a_t05_formal_execution.schema.json",
    "schemas/r2a/r2a_t05_formal_input_manifest.schema.json",
    "src/r2a/r2a_t05_formal_execution.py",
    "src/r2a/r2a_t05_formal_input_manifest.py",
    "scripts/r2a/build_r2a_t05_formal_input_manifest.py",
    "scripts/r2a/run_r2a_t05_formal.py",
    "tests/r2a/test_r2a_t05_formal_execution_preparation.py",
)
AUTHORIZATION_WHITELIST = (
    "configs/r2a/r2a_t05_formal_authorization.v1.json",
    "docs/tasks/R2A-T05_CA退出机制与跨q结构分解.md",
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


def load_formal_authorization(
    path: str | Path = AUTHORIZATION_CONFIG_PATH,
) -> dict[str, Any]:
    """Load the separate authorization metadata without inferring permission."""

    authorization_path = Path(path)
    payload = _json(authorization_path)
    if (
        payload.get("authorization_status") == "not_authorized"
        and payload.get("authorization_head") is not None
    ):
        raise FormalExecutionError("unauthorized_future_head_fabricated")
    schema = _json(AUTHORIZATION_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            payload
        ),
        key=str,
    )
    if errors:
        raise FormalExecutionError(
            "formal_authorization_schema_invalid", errors[0].message
        )
    if payload.get("authorization_status") == "not_authorized":
        if (
            payload.get("reviewed_formal_execution_sha")
            != REVIEWED_FORMAL_EXECUTION_SHA
        ):
            raise FormalExecutionError("unauthorized_reviewed_execution_mismatch")
        if payload.get("formal_run_allowed") is not False:
            raise FormalExecutionError("unauthorized_metadata_allows_formal_run")
        if payload.get("authorization_head") is not None:
            raise FormalExecutionError("unauthorized_future_head_fabricated")
    return payload


def _authorization_diff_paths(
    repo_root: Path, parent: str, head: str
) -> tuple[str, ...]:
    output = _git(repo_root, "diff", "--name-only", parent, head)
    return tuple(line for line in output.splitlines() if line)


def _validate_authorization_binding(
    *,
    repo_root: Path,
    head: str,
    authorization: Mapping[str, Any],
) -> None:
    if authorization.get("authorization_status") != "authorized_pending_execution":
        return
    parent = str(authorization.get("authorization_parent"))
    authorization_head = str(authorization.get("authorization_head"))
    reviewed_execution = str(authorization.get("reviewed_formal_execution_sha"))
    if authorization_head != head:
        raise FormalExecutionError("authorization_head_mismatch", authorization_head)
    if parent != reviewed_execution:
        raise FormalExecutionError("authorization_parent_mismatch")
    parents = _git(repo_root, "rev-list", "--parents", "-n", "1", head).split()
    if len(parents) != 2 or parents[1] != parent:
        raise FormalExecutionError("authorization_parent_not_exact")
    changed = _authorization_diff_paths(repo_root, parent, head)
    whitelist = tuple(
        str(path) for path in authorization["authorization_diff_whitelist"]
    )
    if whitelist != AUTHORIZATION_WHITELIST:
        raise FormalExecutionError("authorization_diff_whitelist_mismatch")
    if any(path not in whitelist for path in changed):
        raise FormalExecutionError("authorization_diff_outside_whitelist", changed)
    if "configs/r2a/r2a_t05_formal_authorization.v1.json" not in changed:
        raise FormalExecutionError("authorization_metadata_not_changed")
    if authorization.get("formal_run_allowed") is not True:
        raise FormalExecutionError("authorized_metadata_does_not_allow_formal_run")
    if authorization.get("authorized_manifest_sha256") is None:
        raise FormalExecutionError("authorized_manifest_identity_missing")


def _protected_file_record(
    repo_root: Path,
    revision: str,
    protected: Mapping[str, Any],
) -> dict[str, Any]:
    relative = str(protected["path"])
    actual_blob = _git(repo_root, "rev-parse", f"{revision}:{relative}")
    if actual_blob != protected["git_blob_sha"]:
        raise FormalExecutionError("protected_file_git_blob_mismatch", relative)
    data = _git_blob_bytes(repo_root, revision, relative)
    committed_sha, normalized_sha, bom, trailing_lf_count = _normalized_text_binding(
        data, relative
    )
    if committed_sha != protected["committed_byte_sha256"]:
        raise FormalExecutionError("protected_file_byte_hash_mismatch", relative)
    if normalized_sha != protected["normalized_text_sha256"]:
        raise FormalExecutionError("protected_file_normalized_hash_mismatch", relative)
    if (
        bom is not protected["bom"]
        or trailing_lf_count != protected["trailing_lf_count"]
    ):
        raise FormalExecutionError("protected_file_text_contract_mismatch", relative)
    return {"path": relative, "git_blob_sha": actual_blob, "sha256": committed_sha}


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
    authorization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate HEAD, clean worktree and all protected committed blobs.

    The current candidate checks execution bindings at the reviewed predecessor
    ``0b7ef1a...`` because the repair itself changes the execution layer.  A
    future authorization commit supplies the newly reviewed parent and must be
    metadata-only; the runner then additionally compares that parent with the
    authorization HEAD.
    """

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
    if (
        tuple(item["path"] for item in config["protected_execution_files"])
        != PROTECTED_EXECUTION_PATHS
    ):
        raise FormalExecutionError("protected_execution_file_set_mismatch")

    authorization_payload = dict(authorization or {})
    execution_reviewed = str(
        authorization_payload.get(
            "reviewed_formal_execution_sha", config["reviewed_formal_execution_sha"]
        )
    )
    if (
        execution_reviewed != REVIEWED_FORMAL_EXECUTION_SHA
        and not authorization_payload
    ):
        raise FormalExecutionError("reviewed_formal_execution_sha_mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", execution_reviewed):
        raise FormalExecutionError("reviewed_formal_execution_sha_invalid")
    _git(root, "merge-base", "--is-ancestor", execution_reviewed, head)
    if authorization_payload:
        if authorization_payload.get("reviewed_implementation_sha") != reviewed:
            raise FormalExecutionError("authorization_implementation_mismatch")
        if authorization_payload.get("formal_run_attempt_limit") != config.get(
            "formal_run_attempt_limit"
        ):
            raise FormalExecutionError("authorization_attempt_limit_mismatch")
        _validate_authorization_binding(
            repo_root=root, head=head, authorization=authorization_payload
        )

    checked: list[dict[str, Any]] = []
    for protected in config["protected_implementation_files"]:
        checked.append(_protected_file_record(root, head, protected))

    execution_records = (
        authorization_payload.get("protected_execution_files")
        if authorization_payload
        else config["protected_execution_files"]
    )
    if not isinstance(execution_records, list):
        raise FormalExecutionError("protected_execution_bindings_missing")
    execution_checked = []
    for protected in execution_records:
        if protected.get("source_commit") != execution_reviewed:
            raise FormalExecutionError(
                "protected_execution_source_commit_mismatch", protected.get("path")
            )
        execution_checked.append(
            _protected_file_record(root, execution_reviewed, protected)
        )
        if (
            authorization_payload.get("authorization_status")
            == "authorized_pending_execution"
        ):
            relative = str(protected["path"])
            parent_blob = _git(root, "rev-parse", f"{execution_reviewed}:{relative}")
            current_blob = _git(root, "rev-parse", f"{head}:{relative}")
            if parent_blob != current_blob:
                raise FormalExecutionError(
                    "authorization_execution_file_changed", relative
                )
    return {
        "head": head,
        "worktree_status": "clean",
        "protected_files": checked,
        "protected_execution_files": execution_checked,
        "reviewed_formal_execution_sha": execution_reviewed,
        "authorization_status": authorization_payload.get(
            "authorization_status", "not_authorized"
        ),
    }


def _manifest_request_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    requests = manifest.get("requests")
    if not isinstance(requests, list):
        raise FormalExecutionError("manifest_requests_invalid")
    names = tuple(str(item.get("logical_request_name")) for item in requests)
    if names != REQUEST_ORDER:
        raise FormalExecutionError("request_order_mutation", names)
    if any(
        item.get("selected_dimensions") != list(ANALYSIS_DIMENSIONS)
        for item in requests
    ):
        raise FormalExecutionError("t05_selected_dimensions_mismatch")
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
    if (
        manifest.get("reviewed_formal_execution_sha")
        != config["reviewed_formal_execution_sha"]
    ):
        raise FormalExecutionError("manifest_reviewed_formal_execution_sha_mismatch")
    if manifest.get("score_dimension_inventory") != list(SCORE_DIMENSIONS):
        raise FormalExecutionError("score_dimension_inventory_mismatch")
    if manifest.get("analysis_dimension_scope") != list(ANALYSIS_DIMENSIONS):
        raise FormalExecutionError("analysis_dimension_scope_mismatch")
    if manifest.get("selected_dimensions_required") != list(ANALYSIS_DIMENSIONS):
        raise FormalExecutionError("selected_dimensions_required_mismatch")
    if manifest.get("unselected_dimensions_must_not_affect_results") is not True:
        raise FormalExecutionError("unselected_dimension_invariance_missing")
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
        if manifest_requests[name].get("selected_dimensions") != list(
            ANALYSIS_DIMENSIONS
        ):
            raise FormalExecutionError("t05_selected_dimensions_mismatch", name)
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
    authorization_path: str | Path = AUTHORIZATION_CONFIG_PATH,
    verify_manifest_files: bool = False,
) -> dict[str, Any]:
    """Run all non-mutating preparation gates and return an execution plan."""

    try:
        config = load_formal_execution_config(config_path)
        authorization = load_formal_authorization(authorization_path)
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
    if authorization.get("reviewed_implementation_sha") != config.get(
        "reviewed_implementation_sha"
    ):
        raise FormalExecutionError("authorization_implementation_mismatch")
    if authorization.get("formal_run_attempt_limit") != config.get(
        "formal_run_attempt_limit"
    ):
        raise FormalExecutionError("authorization_attempt_limit_mismatch")
    if authorization.get("authorization_status") == "authorized_pending_execution":
        try:
            manifest_file, _ = _resolve_repository_path(repo_root, manifest_path)
            manifest_size = manifest_file.stat().st_size
            manifest_sha = sha256_file(manifest_file)
        except (FormalInputManifestError, OSError) as error:
            raise FormalExecutionError(
                "authorized_manifest_identity_unreadable", str(manifest_path)
            ) from error
        if manifest.get("source_commit") != authorization.get("authorization_parent"):
            raise FormalExecutionError("authorized_manifest_source_commit_mismatch")
        if manifest_sha != authorization.get(
            "authorized_manifest_sha256"
        ) or manifest_size != authorization.get("authorized_manifest_byte_size"):
            raise FormalExecutionError("authorized_manifest_identity_mismatch")
    git = inspect_git_preflight(
        repo_root=repo_root,
        config=config,
        expected_source_commit=str(manifest["source_commit"]),
        authorization=authorization,
    )
    return {
        "status": "preflight_passed",
        "task_id": "R2A-T05",
        "formal_scope_id": FORMAL_SCOPE_ID,
        "current_head": git["head"],
        "reviewed_implementation_sha": config["reviewed_implementation_sha"],
        "reviewed_formal_execution_sha": config["reviewed_formal_execution_sha"],
        "request_order": list(REQUEST_ORDER),
        "manifest_path": str(Path(manifest_path)),
        "manifest_verified_files": verify_manifest_files,
        "formal_run_allowed": bool(config["formal_run_allowed"]),
        "authorization_status": authorization["authorization_status"],
        "authorization_head": authorization.get("authorization_head"),
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


_FORBIDDEN_OUTPUT_FIELD_NAMES = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "adj_open",
        "adj_high",
        "adj_low",
        "adj_close",
        "ohlc",
        "return",
        "returns",
        "future_path",
        "future_return",
        "release_label",
        "direction_label",
        "intensity_label",
    }
)
_DIMENSION_KEYS = frozenset(
    {
        "dimension_id",
        "selected_dimensions",
        "analysis_dimension_scope",
        "component_dimension",
    }
)
_COMPONENT_ID_KEY = "component_id"
_UNSELECTED_COMPONENT_PATTERN = re.compile(r"^[PVT](?:\d+)?$")


def _forbidden_output_field(name: str) -> bool:
    lowered = name.strip().lower()
    return (
        lowered in _FORBIDDEN_OUTPUT_FIELD_NAMES
        or "ohlc" in lowered
        or lowered.startswith("return_")
        or lowered.startswith("future_")
        or lowered.endswith("_return")
        or lowered.endswith("_label")
    )


def _dimension_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = [item.strip() for item in value.strip("[]").split(",") if item]
        if isinstance(decoded, list | tuple):
            return [str(item).strip(" '\"") for item in decoded]
    return []


def _has_unselected_component(value: Any) -> bool:
    values = _dimension_list(value)
    return any(
        _UNSELECTED_COMPONENT_PATTERN.fullmatch(item.strip().upper()) for item in values
    )


def _scan_t05_output_dimensions(value: Any, path: str = "candidate") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if _forbidden_output_field(key_text):
                raise FormalExecutionError(
                    "forbidden_t05_output_field", f"{path}.{key_text}"
                )
            if key_text in {"P", "V", "T"}:
                raise FormalExecutionError(
                    "unselected_dimension_in_t05_output", f"{path}.{key_text}"
                )
            if lowered == _COMPONENT_ID_KEY and _has_unselected_component(child):
                raise FormalExecutionError(
                    "unselected_dimension_in_t05_output", f"{path}.{key_text}"
                )
            if lowered in _DIMENSION_KEYS:
                dimensions = _dimension_list(child)
                if any(dimension in {"P", "V", "T"} for dimension in dimensions):
                    raise FormalExecutionError(
                        "unselected_dimension_in_t05_output", f"{path}.{key_text}"
                    )
                if dimensions != list(ANALYSIS_DIMENSIONS):
                    raise FormalExecutionError(
                        "t05_output_selected_dimensions_mismatch", f"{path}.{key_text}"
                    )
            _scan_t05_output_dimensions(child, f"{path}.{key_text}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, child in enumerate(value):
            if isinstance(child, str) and child in {"P", "V", "T"}:
                raise FormalExecutionError(
                    "unselected_dimension_in_t05_output", f"{path}[{index}]"
                )
            _scan_t05_output_dimensions(child, f"{path}[{index}]")


def validate_t05_output_scope(
    outputs: Mapping[str, Path],
    *,
    candidate: Mapping[str, Any] | None = None,
) -> None:
    """Reject P/V/T or future/price fields at the T05 output boundary."""

    if tuple(outputs) != REQUEST_ORDER:
        raise FormalExecutionError("t05_output_request_order_mismatch")
    for name in REQUEST_ORDER:
        target = Path(outputs[name])
        try:
            with duckdb.connect(str(target), read_only=True) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='main' AND table_type='BASE TABLE'"
                    ).fetchall()
                }
                if tables != set(T03_OUTPUT_TABLES):
                    raise FormalExecutionError(
                        "t05_output_table_inventory_mismatch", name
                    )
                for table in tables:
                    columns = [
                        str(row[1])
                        for row in connection.execute(
                            f'PRAGMA table_info("{table}")'
                        ).fetchall()
                    ]
                    if any(_forbidden_output_field(column) for column in columns):
                        raise FormalExecutionError("forbidden_t05_output_field", name)
                    for column in columns:
                        if column.lower() != _COMPONENT_ID_KEY:
                            continue
                        values = connection.execute(
                            f'SELECT DISTINCT "{column}" FROM "{table}"'
                        ).fetchall()
                        if any(_has_unselected_component(row[0]) for row in values):
                            raise FormalExecutionError(
                                "unselected_dimension_in_t05_output", name
                            )
                selected_rows = connection.execute(
                    "SELECT selected_dimensions FROM dynamic_request"
                ).fetchall()
                if not selected_rows or any(
                    _dimension_list(row[0]) != list(ANALYSIS_DIMENSIONS)
                    for row in selected_rows
                ):
                    raise FormalExecutionError(
                        "t05_output_selected_dimensions_mismatch", name
                    )
                dimensions = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT DISTINCT dimension_id FROM daily_dimension_states"
                    ).fetchall()
                }
                if dimensions - set(ANALYSIS_DIMENSIONS):
                    raise FormalExecutionError(
                        "unselected_dimension_in_t05_output", name
                    )
        except duckdb.Error as error:
            raise FormalExecutionError("t05_output_scope_read_failed", name) from error
    if candidate is not None:
        _scan_t05_output_dimensions(candidate)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _schema_inventory(
    value: Any, path: str = "$"
) -> list[tuple[str, str, tuple[str, ...]]]:
    if isinstance(value, Mapping):
        keys = tuple(sorted(str(key) for key in value))
        inventory = [(path, "object", keys)]
        for key, child in value.items():
            inventory.extend(_schema_inventory(child, f"{path}.{key}"))
        return inventory
    if isinstance(value, list):
        inventory = [(path, "array", ())]
        for index, child in enumerate(value):
            inventory.extend(_schema_inventory(child, f"{path}[{index}]"))
        return inventory
    if value is None:
        return [(path, "null", ())]
    if isinstance(value, bool):
        return [(path, "boolean", ())]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return [(path, "number", ())]
    return [(path, "string", ())]


def _leaf_inventory(value: Any, path: str = "$") -> dict[str, bytes]:
    if isinstance(value, Mapping):
        result: dict[str, bytes] = {}
        for key, child in value.items():
            result.update(_leaf_inventory(child, f"{path}.{key}"))
        return result
    if isinstance(value, list):
        result = {}
        for index, child in enumerate(value):
            result.update(_leaf_inventory(child, f"{path}[{index}]"))
        return result
    return {path: _canonical_json_bytes(value)}


def _compact_row_lists(value: Mapping[str, Any]) -> dict[str, list[bytes]]:
    return {
        str(key): [_canonical_json_bytes(row) for row in child]
        for key, child in value.items()
        if isinstance(child, list)
    }


def compare_formal_builds(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare two complete T05 builder payloads, including order and nulls."""

    left_schema = _schema_inventory(left)
    right_schema = _schema_inventory(right)
    left_schema_set = set(left_schema)
    right_schema_set = set(right_schema)
    schema_mismatch_count = len(left_schema_set ^ right_schema_set)
    left_keys = {(path, keys) for path, kind, keys in left_schema if kind == "object"}
    right_keys = {(path, keys) for path, kind, keys in right_schema if kind == "object"}
    key_mismatch_count = len(left_keys ^ right_keys)

    left_leaves = _leaf_inventory(left)
    right_leaves = _leaf_inventory(right)
    leaf_paths = set(left_leaves) | set(right_leaves)
    value_mismatch_count = sum(
        left_leaves.get(path) != right_leaves.get(path) for path in leaf_paths
    )

    left_rows = _compact_row_lists(left)
    right_rows = _compact_row_lists(right)
    row_mismatch_count = 0
    ordering_mismatch_count = 0
    for key in set(left_rows) | set(right_rows):
        left_values = left_rows.get(key, [])
        right_values = right_rows.get(key, [])
        row_mismatch_count += abs(len(left_values) - len(right_values))
        row_mismatch_count += sum(
            left_value != right_value
            for left_value, right_value in zip(left_values, right_values, strict=False)
        )
        if left_values != right_values and Counter(left_values) == Counter(
            right_values
        ):
            ordering_mismatch_count += 1

    left_fingerprint = hashlib.sha256(_canonical_json_bytes(left)).hexdigest()
    right_fingerprint = hashlib.sha256(_canonical_json_bytes(right)).hexdigest()
    left_termination = hashlib.sha256(
        _canonical_json_bytes(left.get("termination_reason_profile", []))
    ).hexdigest()
    right_termination = hashlib.sha256(
        _canonical_json_bytes(right.get("termination_reason_profile", []))
    ).hexdigest()
    status = (
        "passed"
        if not any(
            (
                schema_mismatch_count,
                key_mismatch_count,
                row_mismatch_count,
                value_mismatch_count,
                ordering_mismatch_count,
            )
        )
        else "blocked"
    )
    return {
        "status": status,
        "build_count": 2,
        "left_fingerprint": left_fingerprint,
        "right_fingerprint": right_fingerprint,
        "schema_mismatch_count": schema_mismatch_count,
        "key_mismatch_count": key_mismatch_count,
        "row_mismatch_count": row_mismatch_count,
        "value_mismatch_count": value_mismatch_count,
        "ordering_mismatch_count": ordering_mismatch_count,
        "termination_inventory": {
            "left_fingerprint": left_termination,
            "right_fingerprint": right_termination,
            "match": left_termination == right_termination,
        },
        "compact_table_row_counts": {
            "left": {key: len(rows) for key, rows in left_rows.items()},
            "right": {key: len(rows) for key, rows in right_rows.items()},
        },
        "detail_payload_fingerprint": {
            "left": left_fingerprint,
            "right": right_fingerprint,
            "match": left_fingerprint == right_fingerprint,
        },
    }


def build_determinism_receipt(
    build: Callable[[], Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build twice and return the first payload plus an independent receipt."""

    try:
        left = dict(build())
        right = dict(build())
    except Exception as error:
        raise FormalExecutionError("deterministic_build_failed") from error
    receipt = compare_formal_builds(left, right)
    if receipt["status"] != "passed":
        raise FormalExecutionError("determinism_mismatch")
    return left, receipt


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


def _write_artifact_manifest(root: Path) -> dict[str, Any]:
    """Write a non-recursive manifest of every currently persisted artifact."""

    excluded = {"artifact_manifest.json", "result_package.json"}
    identities: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in excluded or path.name.startswith("."):
            continue
        storage_class = (
            "compact_review_artifact"
            if COMPACT_REVIEW_DIR in path.relative_to(root).parts
            else "repository_local_ignored"
        )
        identities.append(_artifact_identity(root, path, storage_class))
    payload = {
        "manifest_version": "r2a_t05_formal_artifact_manifest.v1",
        "self_excluded_files": sorted(excluded),
        "files": identities,
    }
    _write_json(root / "artifact_manifest.json", payload)
    return payload


def _build_result_package(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    validation: Mapping[str, Any],
    determinism_receipt: Mapping[str, Any],
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
            "deterministic_output": determinism_receipt.get("status") == "passed"
            and determinism_receipt.get("build_count") == 2
            and determinism_receipt.get("left_fingerprint")
            == determinism_receipt.get("right_fingerprint"),
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
    authorization_path: str | Path = AUTHORIZATION_CONFIG_PATH,
    operator_authorized: bool = False,
) -> dict[str, Any]:
    """Execute the future formal path only after all owner gates pass.

    With the committed preparation config this function stops before reading
    the Score or creating a RunRoot.  The real-run branch is nevertheless kept
    explicit so that a later owner-authorized config cannot bypass the gates.
    """

    config = load_formal_execution_config(config_path)
    authorization = load_formal_authorization(authorization_path)
    preflight = preflight_formal_execution(
        manifest_path=manifest_path,
        repo_root=repo_root,
        config_path=config_path,
        authorization_path=authorization_path,
        verify_manifest_files=False,
    )
    if (
        not operator_authorized
        or authorization.get("authorization_status") != "authorized_pending_execution"
        or authorization.get("formal_run_allowed") is not True
    ):
        raise FormalExecutionError("formal_run_not_authorized")
    if (
        authorization["formal_run_attempts_consumed_before_start"]
        >= authorization["formal_run_attempt_limit"]
    ):
        raise FormalExecutionError("formal_run_attempt_limit_exhausted")
    if config["formal_run_started"] or config["formal_artifacts_generated"]:
        raise FormalExecutionError("formal_run_lifecycle_already_started")

    try:
        manifest = load_authorized_input_manifest(
            manifest_path,
            repo_root=repo_root,
            verify_files=True,
        )
        manifest_bytes = Path(manifest_path).stat().st_size
        manifest_sha = sha256_file(manifest_path)
        if manifest_sha != authorization.get(
            "authorized_manifest_sha256"
        ) or manifest_bytes != authorization.get("authorized_manifest_byte_size"):
            raise FormalExecutionError("authorized_manifest_identity_mismatch")
        run_root, run_id = create_unique_run_root(repo_root=repo_root)
    except (FormalInputManifestError, FormalExecutionError) as error:
        raise FormalExecutionError(
            getattr(error, "reason_code", "formal_run_input_preflight_failed"),
            str(error),
        ) from error

    log_path = run_root / "execution_log.jsonl"
    _log_event(log_path, "formal_run_started", run_id=run_id, preflight=preflight)
    log_closed = False
    try:
        _write_json(run_root / "input_manifest.json", manifest)
        _write_json(run_root / "formal_authorization.json", authorization)
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
        validate_t05_output_scope(outputs)
        _log_event(log_path, "all_requests_validated", summaries=summaries)

        t05_config = load_t05_config()
        candidate, determinism_receipt = build_determinism_receipt(
            lambda: build_t05_candidate(outputs, score_path, config=t05_config)
        )
        validate_t05_output_scope(outputs, candidate=candidate)
        independent_validation = validate_t05_candidate(
            candidate,
            request_sources=outputs,
            score_source=score_path,
            config=t05_config,
        )
        detail_path = run_root / "t05_detail.duckdb"
        _write_detail_database(detail_path, candidate)
        candidate = _read_detail_database(detail_path)
        _write_json(run_root / "formal_determinism_receipt.json", determinism_receipt)

        _write_json(
            run_root / "independent_validation_receipt.json", independent_validation
        )

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
            "reviewed_formal_execution_sha": authorization[
                "reviewed_formal_execution_sha"
            ],
            "formal_execution_head": preflight["current_head"],
            "authorization_head": authorization["authorization_head"],
            "authorization_parent": authorization["authorization_parent"],
            "authorization_revision": authorization["authorization_revision"],
            "formal_run_attempt_limit": authorization["formal_run_attempt_limit"],
            "formal_run_attempts_consumed": 1,
            "formal_determinism_receipt": determinism_receipt,
            **lifecycle,
        }
        _write_json(run_root / "run_summary.json", run_summary)
        compact_paths = _write_compact_review_package(
            root=run_root,
            manifest=manifest,
            candidate=candidate,
            run_summary=run_summary,
            validation_receipt=independent_validation,
            result_analysis=(
                "Persisted result analysis is generated after the terminal "
                "execution-log event.\n"
            ),
        )
        _write_json(
            run_root / "anomaly_scan.json",
            {"status": "pending", "blocking_anomalies": []},
        )
        _log_event(log_path, "formal_run_completed_pending_owner_review", run_id=run_id)
        log_closed = True
        _write_artifact_manifest(run_root)

        try:
            analysis = analyze_persisted_formal_artifacts(
                run_root,
                expected_counts=manifest["accepted_t04_counts"],
            )
        except FormalResultAnalysisError as error:
            raise FormalExecutionError(
                "result_analysis_readback_failed", str(error)
            ) from error
        result_analysis = render_persisted_result_analysis(analysis)
        _write_json(run_root / "anomaly_scan.json", analysis)
        _write_text(run_root / "result_analysis.md", result_analysis)
        _write_text(
            run_root / COMPACT_REVIEW_DIR / "result_analysis.md", result_analysis
        )
        _write_artifact_manifest(run_root)
        if analysis.get("status") == "blocked" or analysis.get("blocking_anomalies"):
            raise FormalExecutionError("result_analysis_blocked")

        artifacts = [
            _artifact_identity(run_root, path, "repository_local_ignored")
            for path in (
                *outputs.values(),
                run_root / "formal_authorization.json",
                run_root / "input_manifest.json",
                run_root / "execution_log.jsonl",
                run_root / "run_summary.json",
                detail_path,
                run_root / "independent_validation_receipt.json",
                run_root / "formal_determinism_receipt.json",
                run_root / "anomaly_scan.json",
                run_root / "result_analysis.md",
                run_root / "artifact_manifest.json",
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
            determinism_receipt=determinism_receipt,
            artifacts=artifacts,
        )
        _write_json(run_root / "result_package.json", package)
        return {
            "run_root": str(run_root),
            "run_id": run_id,
            "run_summary": run_summary,
            "result_package": package,
        }
    except Exception as error:
        if not log_closed:
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
    "AUTHORIZATION_CONFIG_PATH",
    "FORMAL_CONFIG_PATH",
    "FormalExecutionError",
    "PROTECTED_CORE_PATHS",
    "PROTECTED_EXECUTION_PATHS",
    "build_determinism_receipt",
    "build_run_id",
    "compare_formal_builds",
    "create_unique_run_root",
    "execute_request_sequence",
    "finalize_formal_candidate",
    "inspect_git_preflight",
    "load_formal_authorization",
    "preflight_formal_execution",
    "reconcile_t04_counts",
    "run_formal_execution",
    "validate_t05_output_scope",
    "validate_formal_completion_lifecycle",
]
