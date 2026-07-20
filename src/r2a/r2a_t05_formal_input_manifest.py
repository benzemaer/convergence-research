"""Build and verify the R2A-T05 formal authorized-input manifest.

The builder is intentionally separate from the T05 scientific implementation.
It binds repository-local file identities and score-database metadata without
copying score rows into the manifest.  It never selects a request or derives a
request identity from a request name: the accepted T04 handoff is authoritative.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r2a/r2a_t05_formal_execution.v1.json"
SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_formal_input_manifest.schema.json"
FORMAL_EXECUTION_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_formal_execution.schema.json"
MANIFEST_VERSION = "r2a_t05_formal_input_manifest.v1"
FORMAL_SCOPE_ID = "r2a_t05_ca_exit_mechanism_formal_execution.v1"
TASK_ID = "R2A-T05"
REVIEWED_IMPLEMENTATION_SHA = "55dceba70bc967caa75c597ce17acb93a2dac511"
REQUEST_ORDER = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")
ALLOWED_REPOSITORY_ROOTS = (
    "data/raw",
    "data/external",
    "data/interim",
    "data/generated",
)
RETIRED_EXTERNAL_ROOT_NAMES = ("convergence-research-inputs",)
SCORE_TABLES = (
    "securities",
    "trading_sessions",
    "security_observation_spine",
    "dimension_definitions",
    "dimension_components",
    "daily_component_scores",
    "daily_dimension_scores",
)
FORBIDDEN_FIELD_NAMES = frozenset(
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
        "dimension_id_value",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FormalInputManifestError(RuntimeError):
    """Raised when formal input authorization cannot be established."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


def sha256_file(path: str | Path) -> str:
    """Hash the actual file bytes in bounded chunks."""

    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise FormalInputManifestError("input_file_unreadable", str(path)) from error
    return digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalInputManifestError("json_input_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise FormalInputManifestError("json_object_required", str(path))
    return value


def load_formal_execution_config(path: str | Path = CONFIG_PATH) -> dict[str, Any]:
    """Read and schema-validate the versioned preparation contract."""

    config_path = Path(path)
    config = _read_json_object(config_path)
    schema = _read_json_object(FORMAL_EXECUTION_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            config
        ),
        key=str,
    )
    if errors:
        raise FormalInputManifestError(
            "formal_execution_config_schema_invalid", errors[0].message
        )
    return config


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise FormalInputManifestError("path_stat_failed", str(path)) from error
    file_attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(path.is_symlink() or file_attributes & reparse_flag)


def _reject_retired_or_compatibility_path(relative: str) -> None:
    lowered = relative.replace("\\", "/").lower()
    parts = {part for part in lowered.split("/") if part}
    if any(name.lower() in parts for name in RETIRED_EXTERNAL_ROOT_NAMES):
        raise FormalInputManifestError("retired_external_root_path", relative)
    if "convergence-research-inputs" in lowered:
        raise FormalInputManifestError("compatibility_path_rejected", relative)


def _relative_path(value: str | Path) -> str:
    path = Path(value)
    if path.is_absolute() or path.drive:
        raise FormalInputManifestError("absolute_input_path_rejected", str(value))
    normalized = path.as_posix()
    if not normalized or normalized.startswith("/"):
        raise FormalInputManifestError("invalid_relative_input_path", str(value))
    if "\\" in normalized or any(part == ".." for part in path.parts):
        raise FormalInputManifestError(
            "path_traversal_or_backslash_rejected", str(value)
        )
    _reject_retired_or_compatibility_path(normalized)
    return normalized


def _resolve_repository_path(
    repo_root: str | Path,
    relative: str | Path,
    *,
    require_file: bool = True,
    allowed_roots: Sequence[str] = ALLOWED_REPOSITORY_ROOTS,
) -> tuple[Path, str]:
    root = Path(repo_root).resolve()
    value_path = Path(relative)
    if value_path.is_absolute():
        try:
            relative = value_path.resolve().relative_to(root).as_posix()
        except ValueError as error:
            raise FormalInputManifestError(
                "absolute_input_path_outside_repository", str(relative)
            ) from error
    normalized = _relative_path(relative)
    candidate = root / normalized
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise FormalInputManifestError(
            "input_outside_repository", normalized
        ) from error
    if not any(
        normalized == allowed or normalized.startswith(f"{allowed}/")
        for allowed in allowed_roots
    ):
        raise FormalInputManifestError("input_root_not_authorized", normalized)

    cursor = root
    for part in Path(normalized).parts:
        cursor /= part
        if cursor.exists() and _is_reparse_point(cursor):
            raise FormalInputManifestError(
                "reparse_point_or_symlink_rejected", normalized
            )
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise FormalInputManifestError(
            "resolved_input_outside_repository", normalized
        ) from error
    if require_file and not resolved.is_file():
        raise FormalInputManifestError("input_file_missing", normalized)
    if require_file and _is_reparse_point(resolved):
        raise FormalInputManifestError("reparse_point_or_symlink_rejected", normalized)
    return resolved, normalized


def _file_identity(
    repo_root: str | Path,
    relative: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_byte_size: int | None = None,
    label: str,
    allow_control_path: bool = False,
) -> tuple[Path, dict[str, Any]]:
    allowed_roots = (
        (*ALLOWED_REPOSITORY_ROOTS, "configs", "schemas")
        if allow_control_path
        else ALLOWED_REPOSITORY_ROOTS
    )
    path, normalized = _resolve_repository_path(
        repo_root,
        relative,
        allowed_roots=allowed_roots,
    )
    try:
        before_size = path.stat().st_size
    except OSError as error:
        raise FormalInputManifestError("input_file_stat_failed", label) from error
    before_hash = sha256_file(path)
    try:
        after_size = path.stat().st_size
    except OSError as error:
        raise FormalInputManifestError("input_file_stat_failed", label) from error
    after_hash = sha256_file(path)
    if before_size != after_size or before_hash != after_hash:
        raise FormalInputManifestError("input_changed_during_binding", label)
    if expected_sha256 is not None and before_hash != expected_sha256:
        raise FormalInputManifestError("input_hash_mismatch", label)
    if expected_byte_size is not None and before_size != expected_byte_size:
        raise FormalInputManifestError("input_byte_size_mismatch", label)
    return path, {
        "relative_path": normalized,
        "sha256": before_hash,
        "byte_size": before_size,
    }


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FormalInputManifestError("git_head_unavailable", result.stderr.strip())
    head = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise FormalInputManifestError("git_head_invalid", head)
    return head


def _handoff_identity(handoff: Mapping[str, Any], name: str) -> dict[str, Any]:
    items = handoff.get("requests")
    if not isinstance(items, list):
        raise FormalInputManifestError("accepted_t04_requests_missing")
    matches = [
        item
        for item in items
        if isinstance(item, Mapping) and item.get("logical_request_name") == name
    ]
    if len(matches) != 1:
        raise FormalInputManifestError("accepted_t04_request_identity_missing", name)
    item = matches[0]
    try:
        return {
            "logical_request_name": str(item["logical_request_name"]),
            "request_id": str(item["request_id"]),
            "request_hash": str(item["request_hash"]),
            "selected_dimensions": [
                str(value) for value in item["selected_dimensions"]
            ],
            "q_by_dimension": {
                key: int(value) for key, value in item["q_by_dimension"].items()
            },
            "confirmation_k": int(item["confirmation_k"]),
            "selection_status": str(item["selection_status"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise FormalInputManifestError(
            "accepted_t04_request_identity_invalid", name
        ) from error


def _verify_handoff_basics(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    label: str,
) -> None:
    if payload.get("task_id") != task_id or payload.get("status") not in {
        "completed_accepted",
        "accepted",
    }:
        raise FormalInputManifestError("accepted_handoff_status_mismatch", label)


def _load_and_bind_upstream(
    *,
    repo_root: Path,
    config: Mapping[str, Any],
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    bindings = config["accepted_bindings"]
    t01_path, t01_identity = _file_identity(
        repo_root,
        bindings["t01_handoff"]["relative_path"],
        expected_sha256=bindings["t01_handoff"]["sha256"],
        label="t01_handoff",
    )
    t01 = _read_json_object(t01_path)
    _verify_handoff_basics(t01, task_id="R2A-T01", label="t01_handoff")
    if (
        t01.get("score_release", {}).get("score_release_id")
        != bindings["score_release"]["score_release_id"]
    ):
        raise FormalInputManifestError("t01_score_release_id_mismatch")

    t03_path, t03_identity = _file_identity(
        repo_root,
        bindings["t03_handoff"]["relative_path"],
        expected_sha256=bindings["t03_handoff"]["sha256"],
        label="t03_handoff",
    )
    t03 = _read_json_object(t03_path)
    _verify_handoff_basics(t03, task_id="R2A-T03", label="t03_handoff")
    if (
        t03.get("evaluator_version") != "r2a_t03_dynamic_evaluator.v1"
        or t03.get("output_schema_version") != "r2a_t03_dynamic_evaluation_output.v1"
        or t03.get("dynamic_protocol_version") != "pcavt_dynamic_state_protocol.v1"
    ):
        raise FormalInputManifestError("t03_evaluator_identity_mismatch")
    t03_config_path, t03_config_identity = _file_identity(
        repo_root,
        bindings["t03_config"]["relative_path"],
        expected_sha256=bindings["t03_config"]["sha256"],
        label="t03_config",
        allow_control_path=True,
    )
    t03_config = _read_json_object(t03_config_path)
    if t03_config.get("evaluator_version") != "r2a_t03_dynamic_evaluator.v1":
        raise FormalInputManifestError("t03_config_identity_mismatch")

    t04_path, t04_identity = _file_identity(
        repo_root,
        bindings["t04_handoff"]["relative_path"],
        expected_sha256=bindings["t04_handoff"]["sha256"],
        label="t04_handoff",
    )
    t04 = _read_json_object(t04_path)
    _verify_handoff_basics(t04, task_id="R2A-T04", label="t04_handoff")
    t04_binding = bindings["t04_handoff"]
    if any(
        t04.get(key) != t04_binding[key]
        for key in ("scope_id", "panel_id", "accepted_run_id")
    ):
        raise FormalInputManifestError("t04_handoff_identity_mismatch")

    handoff_identities = {name: _handoff_identity(t04, name) for name in REQUEST_ORDER}
    config_identities = {
        item["logical_request_name"]: item for item in config["requests"]
    }
    if tuple(config_identities) != REQUEST_ORDER:
        raise FormalInputManifestError("formal_request_order_or_set_mismatch")
    for name in REQUEST_ORDER:
        configured = {
            key: config_identities[name][key]
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
        if configured != handoff_identities[name]:
            raise FormalInputManifestError("formal_request_identity_mismatch", name)
    if handoff_identities["CA_q20_k5"]["q_by_dimension"] != {"C": 2000, "A": 2000}:
        raise FormalInputManifestError("research_anchor_q_mismatch")

    return (
        t01_identity,
        t03_identity,
        t03_config_identity,
        t04_identity,
        {"payload": t04, "identities": handoff_identities},
    )


def _forbidden_field(name: str) -> bool:
    lowered = name.strip().lower()
    if lowered in FORBIDDEN_FIELD_NAMES:
        return True
    return (
        "ohlc" in lowered
        or lowered.startswith("return_")
        or lowered.startswith("future_")
        or lowered.endswith("_return")
        or lowered.endswith("_label")
    )


def _schema_fingerprint(
    connection: duckdb.DuckDBPyConnection,
    table: str,
) -> str:
    if not _IDENTIFIER.fullmatch(table):
        raise FormalInputManifestError("unsafe_score_table_name", table)
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise FormalInputManifestError("score_table_schema_missing", table)
    fields = []
    for row in rows:
        field_name = str(row[1])
        if _forbidden_field(field_name):
            raise FormalInputManifestError(
                "forbidden_score_field", f"{table}.{field_name}"
            )
        fields.append(
            {
                "name": field_name,
                "type": str(row[2]),
                "nullable": not bool(row[3]),
                "primary_key": bool(row[5]),
            }
        )
    encoded = json.dumps(
        fields, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _inspect_score_database(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    try:
        connection = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as error:
        raise FormalInputManifestError(
            "score_database_open_failed", str(path)
        ) from error
    try:
        tables = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' AND table_type='BASE TABLE' "
                "ORDER BY table_name"
            ).fetchall()
        )
        if set(tables) != set(SCORE_TABLES):
            raise FormalInputManifestError("score_table_inventory_mismatch", tables)
        fingerprints = {
            table: _schema_fingerprint(connection, table) for table in SCORE_TABLES
        }
        try:
            security_count = int(
                connection.execute("SELECT count(*) FROM securities").fetchone()[0]
            )
            date_min, date_max = connection.execute(
                "SELECT min(trading_date), max(trading_date) "
                "FROM security_observation_spine"
            ).fetchone()
        except (duckdb.Error, TypeError, ValueError) as error:
            raise FormalInputManifestError("score_coverage_query_failed") from error
        coverage = {
            "security_count": security_count,
            "date_min": str(date_min),
            "date_max": str(date_max),
        }
    finally:
        connection.close()
    return fingerprints, coverage


def _load_request_source(
    *,
    repo_root: Path,
    source: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    path, identity = _file_identity(
        repo_root,
        source["relative_path"],
        expected_sha256=source["sha256"],
        expected_byte_size=int(source["byte_size"]),
        label=f"request_source:{source['logical_request_name']}",
    )
    envelope = _read_json_object(path)
    try:
        from src.r2a.r2a_t02_request_identity import validate_canonical_request

        envelope = validate_canonical_request(envelope)
    except Exception as error:
        raise FormalInputManifestError(
            "request_source_envelope_invalid", source["logical_request_name"]
        ) from error
    actual = {
        "logical_request_name": str(source["logical_request_name"]),
        "request_id": str(envelope.get("request_id")),
        "request_hash": str(envelope.get("request_hash")),
        "selected_dimensions": list(
            envelope.get("spec", {}).get("selected_dimensions", [])
        ),
        "q_by_dimension": dict(envelope.get("spec", {}).get("q_by_dimension", {})),
        "confirmation_k": int(envelope.get("spec", {}).get("confirmation_k", -1)),
        "selection_status": "evaluated_not_selected",
    }
    if actual != dict(expected):
        raise FormalInputManifestError(
            "request_source_identity_mismatch", source["logical_request_name"]
        )
    return {**identity, "logical_request_name": source["logical_request_name"]}


def _validate_manifest(payload: Mapping[str, Any]) -> None:
    schema = _read_json_object(SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            payload
        ),
        key=str,
    )
    if errors:
        raise FormalInputManifestError(
            "formal_input_manifest_schema_invalid", errors[0].message
        )


def _scan_manifest_forbidden_fields(value: Any, path: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _forbidden_field(str(key)):
                raise FormalInputManifestError(
                    "forbidden_manifest_field", f"{path}.{key}"
                )
            _scan_manifest_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, child in enumerate(value):
            _scan_manifest_forbidden_fields(child, f"{path}[{index}]")


def _revalidate_bound_manifest_content(
    *,
    root: Path,
    payload: Mapping[str, Any],
) -> None:
    """Re-read upstream JSON and request envelopes after file hashing."""

    handoffs = payload["accepted_handoffs"]
    t01_path, _ = _resolve_repository_path(root, handoffs["t01"]["relative_path"])
    t01 = _read_json_object(t01_path)
    _verify_handoff_basics(t01, task_id="R2A-T01", label="manifest_t01_handoff")
    t03_path, _ = _resolve_repository_path(root, handoffs["t03"]["relative_path"])
    t03 = _read_json_object(t03_path)
    _verify_handoff_basics(t03, task_id="R2A-T03", label="manifest_t03_handoff")
    if (
        t03.get("evaluator_version") != "r2a_t03_dynamic_evaluator.v1"
        or t03.get("output_schema_version") != "r2a_t03_dynamic_evaluation_output.v1"
        or t03.get("dynamic_protocol_version") != "pcavt_dynamic_state_protocol.v1"
    ):
        raise FormalInputManifestError("t03_evaluator_identity_mismatch")
    t03_config_path, _ = _resolve_repository_path(
        root,
        handoffs["t03_config"]["relative_path"],
        allowed_roots=(*ALLOWED_REPOSITORY_ROOTS, "configs", "schemas"),
    )
    t03_config = _read_json_object(t03_config_path)
    if t03_config.get("evaluator_version") != "r2a_t03_dynamic_evaluator.v1":
        raise FormalInputManifestError("t03_config_identity_mismatch")
    t04_path, _ = _resolve_repository_path(root, handoffs["t04"]["relative_path"])
    t04 = _read_json_object(t04_path)
    _verify_handoff_basics(t04, task_id="R2A-T04", label="manifest_t04_handoff")
    identities = {name: _handoff_identity(t04, name) for name in REQUEST_ORDER}
    manifest_identities = _manifest_request_map_for_input(payload)
    for name in REQUEST_ORDER:
        if manifest_identities[name] != identities[name]:
            raise FormalInputManifestError(
                "request_identity_not_from_accepted_t04_handoff", name
            )
        item = next(
            item for item in t04["requests"] if item["logical_request_name"] == name
        )
        actual_counts = {
            "raw_true": int(item["raw_true_count"]),
            "confirmed_true": int(item["confirmed_true_count"]),
            "intervals": int(item["confirmed_interval_count"]),
            "securities_with_interval": int(item["security_with_interval_count"]),
        }
        if actual_counts != payload["accepted_t04_counts"][name]:
            raise FormalInputManifestError("accepted_t04_count_mismatch", name)
    sources = payload["request_sources"]
    if tuple(item["logical_request_name"] for item in sources) != REQUEST_ORDER:
        raise FormalInputManifestError("request_source_order_or_set_mismatch")
    for source in sources:
        name = str(source["logical_request_name"])
        _load_request_source(
            repo_root=root,
            source=source,
            expected=identities[name],
        )


def _manifest_request_map_for_input(
    payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    requests = payload.get("requests")
    if not isinstance(requests, list):
        raise FormalInputManifestError("manifest_requests_invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in requests:
        name = str(item["logical_request_name"])
        result[name] = {
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
    if tuple(result) != REQUEST_ORDER:
        raise FormalInputManifestError("request_order_or_set_mismatch")
    return result


def build_formal_input_manifest(
    *,
    output_path: str | Path,
    repo_root: str | Path = ROOT,
    config_path: str | Path = CONFIG_PATH,
    config: Mapping[str, Any] | None = None,
    score_database_path: str | Path | None = None,
    source_commit: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Re-read authorized files and build a metadata-only formal manifest.

    The function is intentionally explicit about the Score path.  Callers that
    want to prepare a real formal manifest must opt into the actual repository
    Score path by passing it or using the path frozen in the config.  This
    preparation PR does not call this function on the real Score database.
    """

    root = Path(repo_root).resolve()
    loaded_config = dict(config or load_formal_execution_config(config_path))
    if loaded_config.get("reviewed_implementation_sha") != REVIEWED_IMPLEMENTATION_SHA:
        raise FormalInputManifestError("reviewed_implementation_sha_mismatch")
    if tuple(loaded_config.get("request_order", ())) != REQUEST_ORDER:
        raise FormalInputManifestError("formal_request_order_mismatch")
    output, output_relative = _resolve_repository_path(
        root, output_path, require_file=False
    )
    if output.exists():
        raise FormalInputManifestError(
            "manifest_output_already_exists", output_relative
        )

    t01, t03, t03_config, t04, t04_context = _load_and_bind_upstream(
        repo_root=root,
        config=loaded_config,
    )
    handoff = t04_context["payload"]
    identities = t04_context["identities"]

    score_binding = loaded_config["accepted_bindings"]["score_release"]
    score_relative = score_database_path or score_binding["relative_path"]
    score_path, score_identity = _file_identity(
        root,
        score_relative,
        expected_sha256=score_binding["sha256"],
        expected_byte_size=int(score_binding["byte_size"]),
        label="score_database",
    )
    fingerprints, coverage = _inspect_score_database(score_path)
    expected_coverage = {
        key: score_binding[key] for key in ("security_count", "date_min", "date_max")
    }
    if coverage != expected_coverage:
        raise FormalInputManifestError("score_coverage_mismatch", coverage)

    configured_sources = {
        item["logical_request_name"]: item for item in loaded_config["request_sources"]
    }
    if tuple(configured_sources) != REQUEST_ORDER:
        raise FormalInputManifestError("request_source_order_or_set_mismatch")
    request_sources = [
        _load_request_source(
            repo_root=root,
            source=configured_sources[name],
            expected=identities[name],
        )
        for name in REQUEST_ORDER
    ]

    handoff_counts: dict[str, dict[str, int]] = {}
    for name in REQUEST_ORDER:
        item = next(
            item for item in handoff["requests"] if item["logical_request_name"] == name
        )
        actual_counts = {
            "raw_true": int(item["raw_true_count"]),
            "confirmed_true": int(item["confirmed_true_count"]),
            "intervals": int(item["confirmed_interval_count"]),
            "securities_with_interval": int(item["security_with_interval_count"]),
        }
        if actual_counts != loaded_config["accepted_t04_counts"][name]:
            raise FormalInputManifestError("accepted_t04_count_mismatch", name)
        handoff_counts[name] = actual_counts

    payload = {
        "$schema": "../../schemas/r2a/r2a_t05_formal_input_manifest.schema.json",
        "manifest_version": MANIFEST_VERSION,
        "manifest_type": "r2a_t05_formal_authorized_input",
        "task_id": TASK_ID,
        "formal_scope_id": FORMAL_SCOPE_ID,
        "source_mode": "formal_authorized_repository_local",
        "created_at": created_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_commit": source_commit or _git_head(root),
        "reviewed_implementation_sha": loaded_config["reviewed_implementation_sha"],
        "score_database": {
            **score_identity,
            "score_release_id": score_binding["score_release_id"],
        },
        "score_coverage": coverage,
        "accepted_handoffs": {
            "t01": t01,
            "t03": t03,
            "t03_config": t03_config,
            "t04": t04,
        },
        "request_sources": request_sources,
        "requests": [
            {
                **identities[name],
            }
            for name in REQUEST_ORDER
        ],
        "accepted_t04_counts": handoff_counts,
        "table_inventory": [
            {"table_name": table, "schema_fingerprint": fingerprints[table]}
            for table in SCORE_TABLES
        ],
        "required_schema_fingerprints": fingerprints,
        "authorization": {
            "allowed_repository_roots": list(ALLOWED_REPOSITORY_ROOTS),
            "retired_external_root_names": list(RETIRED_EXTERNAL_ROOT_NAMES),
            "reject_reparse_points": True,
            "reject_compatibility_paths": True,
            "forbidden_data_fields_absent": True,
            "forbidden_data_classes_absent": [
                "OHLC",
                "return",
                "future_path",
                "release_label",
                "P",
                "V",
                "T",
            ],
        },
    }
    _scan_manifest_forbidden_fields(payload)
    _validate_manifest(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(output)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise FormalInputManifestError("manifest_write_failed", str(output)) from error
    return payload


def load_authorized_input_manifest(
    manifest_path: str | Path,
    *,
    repo_root: str | Path = ROOT,
    verify_files: bool = True,
) -> dict[str, Any]:
    """Validate an authorized manifest and optionally re-read every bound file."""

    root = Path(repo_root).resolve()
    path, _ = _resolve_repository_path(root, manifest_path)
    try:
        payload = _read_json_object(path)
    except FormalInputManifestError:
        raise
    _scan_manifest_forbidden_fields(payload)
    _validate_manifest(payload)
    if payload.get("source_mode") != "formal_authorized_repository_local":
        raise FormalInputManifestError("formal_manifest_source_mode_mismatch")
    if not verify_files:
        return payload

    file_entries: list[tuple[str, Mapping[str, Any], bool]] = [
        ("score_database", payload["score_database"], False),
        *[
            (f"accepted_handoff:{key}", entry, key == "t03_config")
            for key, entry in payload["accepted_handoffs"].items()
        ],
        *[
            (f"request_source:{entry['logical_request_name']}", entry, False)
            for entry in payload["request_sources"]
        ],
    ]
    for label, entry, allow_control_path in file_entries:
        if not isinstance(entry, Mapping):
            raise FormalInputManifestError("manifest_file_identity_invalid", label)
        _file_identity(
            root,
            entry["relative_path"],
            expected_sha256=entry["sha256"],
            expected_byte_size=int(entry["byte_size"]),
            label=label,
            allow_control_path=allow_control_path,
        )
    _revalidate_bound_manifest_content(root=root, payload=payload)
    return payload


__all__ = [
    "ALLOWED_REPOSITORY_ROOTS",
    "CONFIG_PATH",
    "FORMAL_EXECUTION_SCHEMA_PATH",
    "FORMAL_SCOPE_ID",
    "FormalInputManifestError",
    "MANIFEST_VERSION",
    "REQUEST_ORDER",
    "ROOT",
    "SCORE_TABLES",
    "build_formal_input_manifest",
    "load_authorized_input_manifest",
    "load_formal_execution_config",
    "sha256_file",
]
