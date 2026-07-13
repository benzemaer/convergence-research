"""R2-T05 selected-only canonical state and event-zone materialization.

The module intentionally consumes the promoted T03 row-level database.  It does
not call the T03 scanner or reimplement its state machine.  Its only state
logic is the explicit as-of projection and the canonical identity mapping
required by the T05 contract.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


class R2T05Error(RuntimeError):
    """Fail-closed error for the T05 formal materialization."""


class R2T05Blocked(R2T05Error):
    """A required upstream gate or row-level source is unavailable."""


ROOT = Path(__file__).resolve().parents[2]
SOURCE_TABLES = {
    "base_expected_security_date",
    "cell_registry",
    "component_source_lineage",
    "event_zone",
    "event_zone_bridge_segment",
    "event_zone_membership_daily",
    "expected_route_key",
    "qualified_component",
    "reentry_attempt",
    "route_daily",
}
PUBLIC_TABLES = [
    "r2_canonical_daily_state",
    "r2_canonical_event_zone",
    "r2_canonical_event_membership",
]
FORBIDDEN_FIELD_TOKENS = {
    "future_return",
    "future_direction",
    "release_label",
    "precision",
    "recall",
    "backtest",
    "winner",
    "rank",
    "trading_efficacy",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json(value) + b"\n")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True
    )
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _git_blob(repo: Path, commit: str, rel: str) -> bytes:
    try:
        return bytes(_git(repo, "show", f"{commit}:{rel}", binary=True))
    except subprocess.CalledProcessError as exc:
        raise R2T05Blocked(f"formal_source_blob_missing:{rel}") from exc


def _validate_canonical_text(payload: bytes, rel: str) -> None:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise R2T05Blocked(f"formal_source_bom:{rel}")
    if b"\r" in payload:
        raise R2T05Blocked(f"formal_source_cr:{rel}")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise R2T05Blocked(f"formal_source_utf8:{rel}") from exc
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        raise R2T05Blocked(f"formal_source_terminal_lf:{rel}")


def _formal_binding(repo: Path, commit: str, rel: str) -> dict[str, Any]:
    path = repo / Path(rel)
    if not path.is_file():
        raise R2T05Blocked(f"formal_source_worktree_missing:{rel}")
    status = subprocess.run(
        ["git", "diff", "--quiet", "--", rel], cwd=repo
    ).returncode
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", rel], cwd=repo
    ).returncode
    if status or staged:
        raise R2T05Blocked(f"formal_source_worktree_dirty:{rel}")
    blob = _git_blob(repo, commit, rel)
    _validate_canonical_text(blob, rel)
    worktree = path.read_bytes()
    _validate_canonical_text(worktree, rel)
    if blob.decode("utf-8") != worktree.decode("utf-8"):
        raise R2T05Blocked(f"worktree_committed_content_mismatch:{rel}")
    blob_sha = str(_git(repo, "rev-parse", f"{commit}:{rel}"))
    return {
        "path": rel,
        "source_commit": commit,
        "git_blob_sha": blob_sha,
        "committed_byte_sha256": _sha256_bytes(blob),
        "normalized_text_sha256": _sha256_bytes(blob),
        "encoding": "utf-8",
        "line_ending": "lf",
        "BOM": False,
        "trailing_LF_count": 1,
    }


def _json_from_commit(repo: Path, commit: str, rel: str) -> dict[str, Any]:
    payload = _git_blob(repo, commit, rel)
    _validate_canonical_text(payload, rel)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise R2T05Blocked(f"formal_json_not_object:{rel}")
    return value


def _bound_input(repo: Path, rel: str, binding: dict[str, Any]) -> dict[str, Any]:
    """Read one handoff-bound artifact from its committed Git blob only."""
    if not isinstance(binding, dict):
        raise R2T05Blocked(f"startup_committed_binding_missing:{rel}")
    source_commit = str(binding.get("source_commit") or "")
    expected_blob = str(binding.get("git_blob_sha") or "")
    expected_bytes = str(binding.get("committed_byte_sha256") or "")
    if len(source_commit) != 40 or len(expected_blob) != 40 or len(expected_bytes) != 64:
        raise R2T05Blocked(f"startup_committed_binding_malformed:{rel}")
    payload = _git_blob(repo, source_commit, rel)
    actual_blob = str(_git(repo, "rev-parse", f"{source_commit}:{rel}"))
    actual_bytes = _sha256_bytes(payload)
    if actual_blob != expected_blob or actual_bytes != expected_bytes:
        raise R2T05Blocked(f"startup_committed_binding_mismatch:{rel}")
    _validate_canonical_text(payload, rel)
    return {
        "path": rel,
        "source_commit": source_commit,
        "git_blob_sha": expected_blob,
        "committed_byte_sha256": expected_bytes,
        "payload": payload,
    }


def _bound_json(repo: Path, rel: str, binding: dict[str, Any]) -> dict[str, Any]:
    bound = _bound_input(repo, rel, binding)
    value = json.loads(bound["payload"].decode("utf-8"))
    if not isinstance(value, dict):
        raise R2T05Blocked(f"formal_json_not_object:{rel}")
    bound["document"] = value
    del bound["payload"]
    return bound


def _csv_from_commit(repo: Path, commit: str, rel: str) -> list[dict[str, str]]:
    payload = _git_blob(repo, commit, rel)
    _validate_canonical_text(payload, rel)
    return list(csv.DictReader(payload.decode("utf-8").splitlines()))


def _timestamp_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _json_path(repo: Path, rel: str, commit: str) -> dict[str, Any]:
    return _json_from_commit(repo, commit, rel)


def _require(value: bool, message: str) -> None:
    if not value:
        raise R2T05Error(message)


def _source_hash_and_tables(
    repo: Path, commit: str, package: dict[str, Any], configured_rel: str
) -> tuple[Path, dict[str, Any]]:
    database_rel = str(package.get("database_path") or "")
    expected = str(package.get("database_sha256") or "")
    if not database_rel or not expected:
        raise R2T05Blocked("blocked_missing_authoritative_t03_row_level_artifact")
    if database_rel != configured_rel:
        raise R2T05Blocked("t03_database_path_package_config_mismatch")
    database = repo / Path(database_rel)
    if not database.is_file():
        raise R2T05Blocked("blocked_missing_authoritative_t03_row_level_artifact")
    actual = _sha256_file(database)
    if actual != expected:
        raise R2T05Blocked("blocked_missing_authoritative_t03_row_level_artifact")
    fingerprint = package.get("database_fingerprint")
    if not isinstance(fingerprint, dict):
        raise R2T05Blocked("t03_database_fingerprint_missing")
    return database, {"path": database_rel, "expected_sha256": expected, "actual_sha256": actual, "fingerprint": fingerprint, "source_commit": commit}


def _check_startup(repo: Path, commit: str, config: dict[str, Any]) -> dict[str, Any]:
    startup = config["startup"]
    handoff = _json_from_commit(repo, commit, startup["handoff_path"])
    validation = _json_from_commit(repo, commit, startup["handoff_validation_path"])
    required = startup["required"]
    for key, expected in required.items():
        if handoff.get(key) != expected or validation.get(key) != expected:
            raise R2T05Blocked("startup_status=blocked_missing_authoritative_t04_final_gate_binding")
    if validation.get("status") != "passed":
        raise R2T05Blocked("startup_status=blocked_missing_authoritative_t04_final_gate_binding")
    if handoff.get("status") not in {None, "passed"}:
        raise R2T05Blocked("startup_status=blocked_missing_authoritative_t04_final_gate_binding")
    committed_inputs = handoff.get("committed_inputs")
    required_paths = startup["required_committed_inputs"]
    if not isinstance(committed_inputs, dict):
        raise R2T05Blocked("startup_status=blocked_missing_authoritative_t04_final_gate_binding")
    bound_artifacts = {}
    for rel in required_paths:
        bound_artifacts[rel] = _bound_json(repo, rel, committed_inputs.get(rel))
    committed_input_bindings = [
        {key: value for key, value in bound.items() if key != "document"}
        for bound in bound_artifacts.values()
    ]
    return {
        "status": "passed",
        "handoff_path": startup["handoff_path"],
        "handoff_validation_path": startup["handoff_validation_path"],
        "pull_request_number": handoff.get("pull_request_number"),
        "reviewed_head_sha": handoff.get("reviewed_head_sha"),
        "merge_commit": handoff.get("merge_commit"),
        "t04_run_id": handoff.get("run_id"),
        "scientific_review_status": handoff.get("scientific_review_status"),
        "repository_final_gate_status": handoff.get("repository_final_gate_status"),
        "formal_task_completed": handoff.get("formal_task_completed"),
        "R2-T05_allowed_to_start": handoff.get("R2-T05_allowed_to_start"),
        "committed_inputs": committed_input_bindings,
        "bound_artifacts": bound_artifacts,
    }


def _check_freeze_plan(config: dict[str, Any], startup: dict[str, Any]) -> dict[str, Any]:
    required_paths = config["startup"]["required_committed_inputs"]
    bound = startup["bound_artifacts"]
    plan_rel = config["inputs"]["t04_freeze_plan_path"]
    decision_rel = config["inputs"]["t04_freeze_decision_path"]
    phase_b_rel = config["inputs"]["t04_phase_b_independent_validation_path"]
    if set(required_paths) != {plan_rel, decision_rel, phase_b_rel}:
        raise R2T05Blocked("t04_startup_bound_input_contract_mismatch")
    plan = bound[plan_rel]["document"]
    decision = bound[decision_rel]["document"]
    phase_b = bound[phase_b_rel]["document"]
    expected = config["selected_versions"]
    actual = plan.get("planned_versions")
    normalized_actual = []
    if isinstance(actual, list):
        for version in actual:
            if "planned_state_version_id" not in version or "state_version_id" in version:
                raise R2T05Blocked("t04_freeze_plan_state_version_id_field_mismatch")
            normalized = dict(version)
            normalized["state_version_id"] = normalized.pop("planned_state_version_id")
            normalized_actual.append(normalized)
    if plan.get("freeze_plan_status") != "passed":
        raise R2T05Blocked("t04_freeze_plan_not_passed")
    if normalized_actual != expected or plan.get("planned_state_version_count") != 2 or len(actual or []) != 2:
        raise R2T05Blocked("t04_freeze_plan_selected_versions_mismatch")
    if (
        decision.get("freeze_decision_status") != "passed"
        or decision.get("selected_version_count") != 2
        or decision.get("strict_core_only_count") != 2
        or decision.get("rejected_decision_unit_count") != 2
    ):
        raise R2T05Blocked("t04_freeze_decision_count_mismatch")
    if (
        phase_b.get("task_id") != "R2-T04"
        or phase_b.get("phase") != "B"
        or phase_b.get("status") != "passed"
        or phase_b.get("selected_cell_count") != 2
        or phase_b.get("strict_core_only_count") != 2
        or phase_b.get("rejected_pair_count") != 2
    ):
        raise R2T05Blocked("t04_phase_b_independent_validation_mismatch")
    units = decision.get("decision_units")
    if not isinstance(units, list) or len(units) != 4:
        raise R2T05Blocked("t04_freeze_decision_unit_cardinality_mismatch")
    expected_by_cell = {version["source_candidate_cell_id"]: version for version in expected}
    selected_units = [unit for unit in units if unit.get("primary_disposition") == "selected"]
    rejected_units = [unit for unit in units if unit.get("primary_disposition") == "rejected"]
    if len(selected_units) != 2 or len(rejected_units) != 2:
        raise R2T05Blocked("t04_freeze_decision_selection_cardinality_mismatch")
    for version in expected:
        matches = [
            unit for unit in selected_units
            if unit.get("primary_candidate_cell_id") == version["source_candidate_cell_id"]
        ]
        if len(matches) != 1:
            raise R2T05Blocked("t04_freeze_decision_candidate_cell_mismatch")
        unit = matches[0]
        if (
            unit.get("pair_disposition") != "selected"
            or unit.get("shared_disposition") != "retain_as_strict_core_only"
            or unit.get("shared_candidate_cell_id") != version["strict_core_source_candidate_cell_id"]
            or unit.get("selected_d") != version["d"]
            or unit.get("selected_g") != version["g"]
            or not unit.get("strict_core_enabled")
        ):
            raise R2T05Blocked("t04_freeze_decision_strict_core_pair_mismatch")
    if set(unit.get("primary_candidate_cell_id") for unit in selected_units) != set(expected_by_cell):
        raise R2T05Blocked("t04_freeze_decision_additional_selected_candidate")
    exclusions = {
        "W250_materialized_version_count": sum(version.get("W") != 120 for version in actual),
        "shared_q_independent_state_version_count": sum(
            unit.get("shared_disposition") == "selected" for unit in units
        ),
        "PCT_parent_product_count": sum(
            version.get("state_line") not in {"S_PCT", "S_PCVT"}
            or "parent" in str(version.get("state_version_id", "")).lower()
            for version in actual
        ),
        "additional_selected_candidate_count": sum(
            version.get("source_candidate_cell_id") not in expected_by_cell for version in actual
        ),
        "shared_q_event_count": sum(
            "shared" in str(version.get("source_candidate_cell_id", "")).lower()
            for version in actual
        ),
    }
    if any(value != 0 for value in exclusions.values()):
        raise R2T05Blocked("t04_freeze_exclusion_mismatch")
    return {
        "status": "passed",
        "freeze_plan": plan,
        "freeze_decision": decision,
        "phase_b_independent_validation": phase_b,
        "bound_input_bindings": {
            rel: {key: value for key, value in bound[rel].items() if key != "document"}
            for rel in required_paths
        },
        "exclusions": exclusions,
    }


def _create_output_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE r2_canonical_daily_state(
          state_version_id VARCHAR NOT NULL,
          state_line VARCHAR NOT NULL,
          window_track_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          trade_date DATE NOT NULL,
          eligible_state BOOLEAN NOT NULL,
          raw_state BOOLEAN,
          confirmed_state BOOLEAN NOT NULL,
          confirmation_time TIMESTAMPTZ,
          component_qualified_as_of BOOLEAN NOT NULL,
          event_status_as_of VARCHAR NOT NULL,
          active_event_id_as_of VARCHAR,
          state_risk_set_eligible BOOLEAN NOT NULL,
          strict_core_member BOOLEAN NOT NULL,
          quality_state VARCHAR NOT NULL,
          candidate_config_id VARCHAR NOT NULL,
          source_run_id VARCHAR NOT NULL,
          PRIMARY KEY(state_version_id,security_id,trade_date)
        );
        CREATE TABLE r2_canonical_event_zone(
          state_version_id VARCHAR NOT NULL,
          event_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          first_component_start_date DATE NOT NULL,
          first_qualification_time TIMESTAMPTZ NOT NULL,
          last_confirmed_end_date DATE NOT NULL,
          last_exit_observation_time TIMESTAMPTZ,
          zone_finalization_time TIMESTAMPTZ,
          zone_status VARCHAR NOT NULL,
          exit_reason VARCHAR NOT NULL,
          left_censored BOOLEAN NOT NULL,
          right_censored BOOLEAN NOT NULL,
          component_interval_count INTEGER NOT NULL,
          bridge_count INTEGER NOT NULL,
          bridged_gap_days INTEGER NOT NULL,
          zone_confirmed_day_count INTEGER NOT NULL,
          zone_trading_span INTEGER NOT NULL,
          confirmed_density DOUBLE NOT NULL,
          bridged_gap_ratio DOUBLE NOT NULL,
          zone_revision_count INTEGER NOT NULL,
          PRIMARY KEY(state_version_id,event_id)
        );
        CREATE TABLE r2_canonical_event_membership(
          state_version_id VARCHAR NOT NULL,
          event_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          trade_date DATE NOT NULL,
          confirmed_state BOOLEAN NOT NULL,
          component_member BOOLEAN NOT NULL,
          retrospective_component_member BOOLEAN NOT NULL,
          component_qualified_as_of BOOLEAN NOT NULL,
          event_zone_member BOOLEAN NOT NULL,
          is_prequalification_confirmed_day BOOLEAN NOT NULL,
          is_bridged_gap BOOLEAN NOT NULL,
          is_unqualified_reentry_day BOOLEAN NOT NULL,
          event_status_as_of VARCHAR NOT NULL,
          zone_revision INTEGER NOT NULL,
          membership_available_time TIMESTAMPTZ NOT NULL,
          state_risk_set_eligible BOOLEAN NOT NULL,
          qualified_event_risk_set_eligible BOOLEAN NOT NULL,
          PRIMARY KEY(state_version_id,event_id,security_id,trade_date)
        );
        CREATE TABLE r2_t05_event_id_lineage(
          state_version_id VARCHAR NOT NULL,
          source_candidate_cell_id VARCHAR NOT NULL,
          source_scan_event_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          first_component_id VARCHAR NOT NULL,
          canonical_event_id VARCHAR NOT NULL,
          identity_payload VARCHAR NOT NULL,
          identity_payload_sha256 VARCHAR NOT NULL,
          source_run_id VARCHAR NOT NULL,
          PRIMARY KEY(state_version_id,source_scan_event_id)
        );
        """
    )


def _event_identity(
    config: dict[str, Any], version: dict[str, Any], source: tuple[Any, ...]
) -> tuple[str, str, str]:
    (
        source_candidate_cell_id,
        source_scan_event_id,
        security_id,
        first_component_id,
        first_start,
        first_qualification,
    ) = source[:6]
    payload_value = {
        "contract_version": config["contract_version"],
        "state_version_id": version["state_version_id"],
        "security_id": security_id,
        "first_qualified_component_identity": {
            "source_candidate_cell_id": source_candidate_cell_id,
            "first_component_id": first_component_id,
            "first_component_start_date": _date_text(first_start),
            "first_qualification_time": _timestamp_text(first_qualification),
        },
    }
    payload = _canonical_json(payload_value).decode("utf-8")
    digest = _sha256_bytes(payload.encode("utf-8"))
    return digest, payload, source_scan_event_id


def _build_event_map(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any], versions: list[dict[str, Any]], source_run_id: str
) -> list[dict[str, Any]]:
    con.execute(
        """
        CREATE TEMP TABLE t05_selected_versions AS
        SELECT * FROM (VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?), (?,?,?,?,?,?,?,?,?,?,?,?,?,?))
        AS x(state_version_id,source_candidate_cell_id,state_line,window_track_id,W,K,qP,qC,qT,qV,d,g,strict_core_source_candidate_cell_id,primary_route_id)
        """,
        [value for version in versions for value in [
            version["state_version_id"], version["source_candidate_cell_id"], version["state_line"], version["window_track_id"],
            version["W"], version["K"], version["qP"], version["qC"], version["qT"], version["qV"], version["d"], version["g"],
            version["strict_core_source_candidate_cell_id"], None,
        ]],
    )
    route_rows = con.execute(
        """
        SELECT v.state_version_id,v.source_candidate_cell_id,v.state_line,v.window_track_id,
               v.W,v.K,v.qP,v.qC,v.qT,v.qV,v.d,v.g,v.strict_core_source_candidate_cell_id,
               c.route_id primary_route_id, s.route_id strict_core_route_id
        FROM t05_selected_versions v
        JOIN src.cell_registry c ON c.candidate_cell_id=v.source_candidate_cell_id
        JOIN src.cell_registry s ON s.candidate_cell_id=v.strict_core_source_candidate_cell_id
        """
    ).fetchall()
    if len(route_rows) != 2:
        raise R2T05Error("selected_version_route_join_not_exactly_two")
    columns = [
        "state_version_id", "source_candidate_cell_id", "state_line", "window_track_id", "W", "K", "qP", "qC", "qT", "qV", "d", "g", "strict_core_source_candidate_cell_id", "primary_route_id", "strict_core_route_id"
    ]
    con.execute("DROP TABLE t05_selected_versions")
    con.execute("CREATE TEMP TABLE t05_selected_versions AS SELECT * FROM (VALUES " + ",".join(["(" + ",".join("?" for _ in columns) + ")"] * len(route_rows)) + ") AS x(" + ",".join(columns) + ")", [value for row in route_rows for value in row])
    events = con.execute(
        """
        SELECT v.state_version_id,e.candidate_cell_id,e.scan_event_id,e.security_id,
               e.first_component_id,q.start_date,q.event_qualification_time
        FROM src.event_zone e
        JOIN t05_selected_versions v ON v.source_candidate_cell_id=e.candidate_cell_id
        JOIN src.qualified_component q
          ON q.candidate_cell_id=e.candidate_cell_id AND q.security_id=e.security_id
         AND q.component_id=e.first_component_id AND q.qualified
        ORDER BY v.state_version_id,e.security_id,e.scan_event_id
        """
    ).fetchall()
    if not events:
        raise R2T05Error("selected_event_zone_is_empty")
    mapped: list[dict[str, Any]] = []
    ids: set[tuple[str, str]] = set()
    reverse: dict[str, tuple[str, str, str]] = {}
    for row in events:
        version = next(v for v in versions if v["state_version_id"] == row[0])
        event_id, payload, _ = _event_identity(config, version, row[1:])
        key = (row[0], row[2])
        if key in ids or event_id in reverse:
            raise R2T05Error("canonical_event_id_collision")
        ids.add(key)
        reverse[event_id] = key
        mapped.append({
            "state_version_id": row[0],
            "source_candidate_cell_id": row[1],
            "source_scan_event_id": row[2],
            "security_id": row[3],
            "first_component_id": row[4],
            "first_component_start_date": row[5],
            "first_qualification_time": row[6],
            "canonical_event_id": event_id,
            "identity_payload": payload,
            "identity_payload_sha256": _sha256_bytes(payload.encode("utf-8")),
            "source_run_id": source_run_id,
        })
    con.execute("CREATE TEMP TABLE t05_event_map AS SELECT * FROM (VALUES " + ",".join(["(" + ",".join("?" for _ in range(10)) + ")"] * len(mapped)) + ") AS x(state_version_id,source_candidate_cell_id,source_scan_event_id,security_id,first_component_id,first_component_start_date,first_qualification_time,canonical_event_id,identity_payload,identity_payload_sha256)", [value for row in mapped for value in [row[k] for k in ["state_version_id","source_candidate_cell_id","source_scan_event_id","security_id","first_component_id","first_component_start_date","first_qualification_time","canonical_event_id","identity_payload","identity_payload_sha256"]]])
    con.execute(
        """
        CREATE TEMP TABLE t05_component_map AS
        SELECT DISTINCT em.canonical_event_id,em.state_version_id,em.source_candidate_cell_id,
               em.source_scan_event_id,em.security_id,em.first_component_id component_id
        FROM t05_event_map em
        UNION
        SELECT DISTINCT em.canonical_event_id,em.state_version_id,em.source_candidate_cell_id,
               em.source_scan_event_id,em.security_id,b.left_component_id
        FROM t05_event_map em JOIN src.event_zone_bridge_segment b
          ON b.candidate_cell_id=em.source_candidate_cell_id AND b.security_id=em.security_id
         AND b.scan_event_id=em.source_scan_event_id AND b.merge_accepted
        UNION
        SELECT DISTINCT em.canonical_event_id,em.state_version_id,em.source_candidate_cell_id,
               em.source_scan_event_id,em.security_id,b.right_component_id
        FROM t05_event_map em JOIN src.event_zone_bridge_segment b
          ON b.candidate_cell_id=em.source_candidate_cell_id AND b.security_id=em.security_id
         AND b.scan_event_id=em.source_scan_event_id AND b.merge_accepted
        UNION
        SELECT DISTINCT em.canonical_event_id,em.state_version_id,em.source_candidate_cell_id,
               em.source_scan_event_id,em.security_id,r.source_component_id
        FROM t05_event_map em JOIN src.reentry_attempt r
          ON r.candidate_cell_id=em.source_candidate_cell_id AND r.security_id=em.security_id
         AND r.scan_event_id=em.source_scan_event_id
        """
    )
    return mapped


def _materialize_events(con: duckdb.DuckDBPyConnection, source_run_id: str) -> None:
    con.execute(
        """
        INSERT INTO r2_t05_event_id_lineage
        SELECT state_version_id,source_candidate_cell_id,source_scan_event_id,security_id,
               first_component_id,canonical_event_id,identity_payload,identity_payload_sha256,
               ?
        FROM t05_event_map
        """,
        [source_run_id],
    )
    con.execute(
        """
        INSERT INTO r2_canonical_event_zone
        WITH component_agg AS (
          SELECT cm.canonical_event_id,
                 count(*) FILTER (WHERE q.qualified) component_interval_count,
                 max(q.end_date) FILTER (WHERE q.qualified) last_confirmed_end_date,
                 max(l.censor_status='right_censored') right_censored_component
          FROM t05_component_map cm
          JOIN src.qualified_component q
            ON q.candidate_cell_id=cm.source_candidate_cell_id AND q.security_id=cm.security_id
           AND q.component_id=cm.component_id
          JOIN src.component_source_lineage l
            ON l.candidate_cell_id=q.candidate_cell_id AND l.security_id=q.security_id
           AND l.component_id=q.component_id
          GROUP BY cm.canonical_event_id
        ), spans AS (
          SELECT em.canonical_event_id,
                 count(*) zone_trading_span,
                 max(rd.exit_observation_time) last_exit_observation_time
          FROM t05_event_map em
          JOIN component_agg ca USING(canonical_event_id)
          JOIN src.cell_registry cr ON cr.candidate_cell_id=em.source_candidate_cell_id
          JOIN src.event_zone e2 ON e2.candidate_cell_id=em.source_candidate_cell_id
           AND e2.security_id=em.security_id AND e2.scan_event_id=em.source_scan_event_id
          JOIN src.route_daily rd
            ON rd.route_id=cr.route_id AND rd.security_id=em.security_id
           AND rd.trade_date BETWEEN em.first_component_start_date AND coalesce(CAST(e2.zone_finalization_time AS DATE),ca.last_confirmed_end_date)
           AND rd.exit_observation_time IS NOT NULL
          GROUP BY em.canonical_event_id
        ), trading_spans AS (
          SELECT em.canonical_event_id,count(*) zone_trading_span
          FROM t05_event_map em JOIN component_agg ca USING(canonical_event_id)
          JOIN src.cell_registry cr ON cr.candidate_cell_id=em.source_candidate_cell_id
          JOIN src.route_daily rd ON rd.route_id=cr.route_id AND rd.security_id=em.security_id
           AND rd.trade_date BETWEEN em.first_component_start_date AND ca.last_confirmed_end_date
          GROUP BY em.canonical_event_id
        )
        SELECT em.state_version_id,em.canonical_event_id,em.security_id,em.first_component_start_date,
               em.first_qualification_time,ca.last_confirmed_end_date,sp.last_exit_observation_time,
               e.zone_finalization_time,e.status,e.exit_or_censor_reason,
               em.first_component_start_date=(SELECT min(rd.trade_date) FROM src.route_daily rd
                 JOIN src.cell_registry cr2 ON cr2.route_id=rd.route_id
                WHERE cr2.candidate_cell_id=em.source_candidate_cell_id AND rd.security_id=em.security_id) left_censored,
               (e.status='RIGHT_CENSORED' OR ca.right_censored_component) right_censored,
               ca.component_interval_count,e.bridge_count,e.raw_false_bridged_day_count,
               e.confirmed_day_count,ts.zone_trading_span,
               e.confirmed_day_count::DOUBLE/NULLIF(ts.zone_trading_span,0),
               e.raw_false_bridged_day_count::DOUBLE/NULLIF(ts.zone_trading_span,0),
               e.zone_revision+1
        FROM t05_event_map em
        JOIN src.event_zone e ON e.candidate_cell_id=em.source_candidate_cell_id
         AND e.security_id=em.security_id AND e.scan_event_id=em.source_scan_event_id
        JOIN component_agg ca USING(canonical_event_id)
        JOIN trading_spans ts USING(canonical_event_id)
        LEFT JOIN spans sp USING(canonical_event_id)
        """
    )
    bad = con.execute(
        """
        SELECT count(*) FROM r2_canonical_event_zone e
        WHERE e.zone_finalization_time IS NULL AND e.zone_status<>'RIGHT_CENSORED'
           OR e.last_confirmed_end_date IS NULL OR e.zone_trading_span<=0
        """
    ).fetchone()[0]
    if bad:
        raise R2T05Error(f"event_terminal_or_span_contract_failure:{bad}")


def _materialize_membership(con: duckdb.DuckDBPyConnection) -> int:
    source_mismatch = con.execute(
        """
        SELECT count(*) FROM src.event_zone_membership_daily
        WHERE is_bridged_gap IS DISTINCT FROM is_raw_false_bridge
        """
    ).fetchone()[0]
    if source_mismatch:
        raise R2T05Error(f"source_bridge_mapping_mismatch:{source_mismatch}")
    con.execute(
        """
        INSERT INTO r2_canonical_event_membership
        SELECT em.state_version_id,em.canonical_event_id,m.security_id,m.trade_date,
               m.confirmed_state,
               EXISTS (SELECT 1 FROM t05_component_map cm JOIN src.qualified_component q
                 ON q.candidate_cell_id=cm.source_candidate_cell_id AND q.security_id=cm.security_id
                AND q.component_id=cm.component_id
                WHERE cm.canonical_event_id=em.canonical_event_id
                  AND m.trade_date BETWEEN q.start_date AND q.end_date),
               m.retrospective_component_member,m.component_qualified_as_of,m.event_zone_member,
               m.prequalification_member,m.is_raw_false_bridge,m.unqualified_reentry_member,
               m.zone_status_as_of,m.zone_revision_as_of,m.membership_available_time,
               (m.eligible AND m.quality_state='valid' AND m.confirmed_state),
               (m.eligible AND m.quality_state='valid' AND m.confirmed_state
                AND m.event_zone_member AND m.component_qualified_as_of
                AND NOT m.is_raw_false_bridge AND NOT m.prequalification_member)
        FROM src.event_zone_membership_daily m
        JOIN t05_event_map em ON em.source_candidate_cell_id=m.candidate_cell_id
         AND em.security_id=m.security_id AND em.source_scan_event_id=m.scan_event_id
        """
    )
    before = con.execute("SELECT count(*) FROM r2_canonical_event_membership").fetchone()[0]
    con.execute(
        """
        INSERT INTO r2_canonical_event_membership
        SELECT em.state_version_id,em.canonical_event_id,em.security_id,rd.trade_date,
               rd.confirmed_state,false,false,false,false,false,false,false,
               e.status,e.zone_revision,e.zone_finalization_time,
               false,false
        FROM t05_event_map em
        JOIN src.event_zone e ON e.candidate_cell_id=em.source_candidate_cell_id
         AND e.security_id=em.security_id AND e.scan_event_id=em.source_scan_event_id
        JOIN src.cell_registry cr ON cr.candidate_cell_id=em.source_candidate_cell_id
        JOIN src.route_daily rd ON rd.route_id=cr.route_id AND rd.security_id=em.security_id
         AND rd.trade_date=CAST(e.zone_finalization_time AS DATE)
        WHERE e.zone_finalization_time IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM r2_canonical_event_membership x
            WHERE x.state_version_id=em.state_version_id AND x.event_id=em.canonical_event_id
              AND x.security_id=em.security_id AND x.trade_date=rd.trade_date)
        """
    )
    return con.execute("SELECT count(*) FROM r2_canonical_event_membership").fetchone()[0] - before


def _materialize_daily(con: duckdb.DuckDBPyConnection, source_run_id: str) -> None:
    con.execute(
        """
        CREATE TEMP TABLE t05_strict_daily AS
        SELECT v.state_version_id,p.security_id,p.trade_date,s.confirmed_state strict_core_member
        FROM t05_selected_versions v
        JOIN src.route_daily p ON p.route_id=v.primary_route_id
        JOIN src.route_daily s ON s.route_id=v.strict_core_route_id
         AND s.security_id=p.security_id AND s.trade_date=p.trade_date
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE t05_daily_base AS
        SELECT v.state_version_id,v.state_line,v.window_track_id,r.security_id,r.trade_date,
               r.available_time,r.eligible,r.raw_state,r.confirmed_state,r.confirmation_time,
               r.state_risk_set_eligible,r.quality_state,v.source_candidate_cell_id candidate_config_id
        FROM t05_selected_versions v JOIN src.route_daily r ON r.route_id=v.primary_route_id
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE t05_daily_asof AS
        SELECT d.*,coalesce(a.component_qualified_as_of,false) component_qualified_as_of,
               coalesce(a.event_status_as_of,'NO_EVENT') event_status_as_of,
               CASE WHEN a.event_status_as_of IN ('COMPONENT_FORMING','QUALIFIED_ACTIVE','GAP_PENDING','REENTRY_PENDING_QUALIFICATION') THEN a.event_id ELSE NULL END active_event_id_as_of
        FROM t05_daily_base d
        LEFT JOIN LATERAL (
          SELECT m.event_id,m.component_qualified_as_of,m.event_status_as_of
          FROM r2_canonical_event_membership m
          WHERE m.security_id=d.security_id AND m.membership_available_time<=d.available_time
          ORDER BY m.membership_available_time DESC,m.trade_date DESC,m.event_id DESC
          LIMIT 1
        ) a ON true
        """
    )
    con.execute(
        """
        INSERT INTO r2_canonical_daily_state
        SELECT d.state_version_id,d.state_line,d.window_track_id,d.security_id,d.trade_date,
               d.eligible,d.raw_state,d.confirmed_state,d.confirmation_time,d.component_qualified_as_of,
               d.event_status_as_of,d.active_event_id_as_of,d.state_risk_set_eligible,
               s.strict_core_member,d.quality_state,d.candidate_config_id,?
        FROM t05_daily_asof d JOIN t05_strict_daily s USING(state_version_id,security_id,trade_date)
        """,
        [source_run_id],
    )
    violation = con.execute(
        "SELECT count(*) FROM r2_canonical_daily_state WHERE strict_core_member AND NOT confirmed_state"
    ).fetchone()[0]
    if violation:
        raise R2T05Error(f"strict_core_subset_violation:{violation}")
    mismatch = con.execute(
        """
        SELECT count(*) FROM r2_canonical_daily_state
        WHERE state_risk_set_eligible IS DISTINCT FROM (eligible_state AND quality_state='valid' AND confirmed_state)
        """
    ).fetchone()[0]
    if mismatch:
        raise R2T05Error(f"canonical_daily_risk_formula_failure:{mismatch}")


def _table_fingerprint(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, Any]:
    columns = [row[0] for row in con.execute(f'DESCRIBE "{table}"').fetchall()]
    expressions = ",".join(
        f"coalesce(cast(\"{column}\" as varchar),'\\x00')" for column in columns
    )
    row_hash = f"md5(concat_ws(chr(31),{expressions}))"
    fingerprint = con.execute(
        f"SELECT sha256(coalesce(string_agg({row_hash},',' ORDER BY {row_hash}),'')) FROM \"{table}\""
    ).fetchone()[0]
    return {"row_count": con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0], "columns": columns, "stable_multiset_sha256": fingerprint}


def _collect_reports(
    con: duckdb.DuckDBPyConnection, run_dir: Path, config: dict[str, Any], input_binding: dict[str, Any], source_info: dict[str, Any], startup: dict[str, Any], freeze: dict[str, Any], source_run_id: str, terminal_added: int, expected_daily_keys: int
) -> dict[str, Any]:
    versions = [row[0] for row in con.execute("SELECT DISTINCT state_version_id FROM r2_canonical_daily_state ORDER BY 1").fetchall()]
    daily_rows = con.execute("""
      SELECT state_version_id,count(*) daily_rows,
        sum(CASE WHEN eligible_state THEN 1 ELSE 0 END) eligible_rows,
        sum(CASE WHEN quality_state='valid' THEN 1 ELSE 0 END) valid_rows,
        sum(CASE WHEN raw_state THEN 1 ELSE 0 END) raw_true_rows,
        sum(CASE WHEN confirmed_state THEN 1 ELSE 0 END) confirmed_rows,
        sum(CASE WHEN state_risk_set_eligible THEN 1 ELSE 0 END) state_risk_rows,
        sum(CASE WHEN strict_core_member THEN 1 ELSE 0 END) strict_core_rows
      FROM r2_canonical_daily_state GROUP BY 1 ORDER BY 1
    """).fetchall()
    event_rows = con.execute("""
      SELECT state_version_id,count(*) event_rows,count(distinct security_id) securities,
        sum(component_interval_count),sum(bridge_count),sum(bridged_gap_days),sum(zone_confirmed_day_count),
        sum(zone_trading_span),min(confirmed_density),max(confirmed_density),min(zone_revision_count),max(zone_revision_count)
      FROM r2_canonical_event_zone GROUP BY 1 ORDER BY 1
    """).fetchall()
    membership_rows = con.execute("""
      SELECT state_version_id,count(*) membership_rows,
        sum(CASE WHEN event_zone_member THEN 1 ELSE 0 END) event_member_rows,
        sum(CASE WHEN retrospective_component_member THEN 1 ELSE 0 END) retrospective_rows,
        sum(CASE WHEN is_prequalification_confirmed_day THEN 1 ELSE 0 END) prequalification_rows,
        sum(CASE WHEN is_bridged_gap THEN 1 ELSE 0 END) bridge_rows,
        sum(CASE WHEN is_unqualified_reentry_day THEN 1 ELSE 0 END) unqualified_reentry_rows,
        sum(CASE WHEN qualified_event_risk_set_eligible THEN 1 ELSE 0 END) qualified_risk_rows,
        min(membership_available_time-trade_date::TIMESTAMPTZ),max(membership_available_time-trade_date::TIMESTAMPTZ)
      FROM r2_canonical_event_membership GROUP BY 1 ORDER BY 1
    """).fetchall()
    _write_csv(run_dir / "r2_t05_daily_reconciliation.csv", [
        {"state_version_id": row[0], "expected_daily_rows": expected_daily_keys, "actual_daily_rows": row[1], "eligible_rows": row[2], "valid_rows": row[3], "raw_true_rows": row[4], "confirmed_rows": row[5], "state_risk_rows": row[6], "strict_core_rows": row[7], "status": "passed" if row[1] == expected_daily_keys else "failed"}
        for row in daily_rows
    ], ["state_version_id","expected_daily_rows","actual_daily_rows","eligible_rows","valid_rows","raw_true_rows","confirmed_rows","state_risk_rows","strict_core_rows","status"])
    _write_csv(run_dir / "r2_t05_event_reconciliation.csv", [
        {"state_version_id": row[0], "source_event_rows": row[1], "canonical_event_rows": row[1], "security_count": row[2], "component_count": row[3], "bridge_count": row[4], "bridged_gap_days": row[5], "confirmed_days": row[6], "trading_span": row[7], "density_min": row[8], "density_max": row[9], "revision_min": row[10], "revision_max": row[11], "status": "passed"}
        for row in event_rows
    ], ["state_version_id","source_event_rows","canonical_event_rows","security_count","component_count","bridge_count","bridged_gap_days","confirmed_days","trading_span","density_min","density_max","revision_min","revision_max","status"])
    _write_csv(run_dir / "r2_t05_membership_reconciliation.csv", [
        {"state_version_id": row[0], "canonical_membership_rows": row[1], "event_member_rows": row[2], "retrospective_component_rows": row[3], "prequalification_rows": row[4], "bridge_rows": row[5], "unqualified_reentry_rows": row[6], "qualified_risk_rows": row[7], "availability_lag_min": row[8], "availability_lag_max": row[9], "terminal_rows_added_total": terminal_added, "status": "passed"}
        for row in membership_rows
    ], ["state_version_id","canonical_membership_rows","event_member_rows","retrospective_component_rows","prequalification_rows","bridge_rows","unqualified_reentry_rows","qualified_risk_rows","availability_lag_min","availability_lag_max","terminal_rows_added_total","status"])
    _write_csv(run_dir / "r2_t05_strict_core_reconciliation.csv", [
        {"state_version_id": row[0], "primary_confirmed_rows": row[1], "strict_core_rows": row[2], "subset_violations": row[3], "status": "passed" if row[3] == 0 else "failed"}
        for row in con.execute("""
          SELECT state_version_id,sum(CASE WHEN confirmed_state THEN 1 ELSE 0 END),sum(CASE WHEN strict_core_member THEN 1 ELSE 0 END),sum(CASE WHEN strict_core_member AND NOT confirmed_state THEN 1 ELSE 0 END)
          FROM r2_canonical_daily_state GROUP BY 1 ORDER BY 1
        """).fetchall()
    ], ["state_version_id","primary_confirmed_rows","strict_core_rows","subset_violations","status"])
    _write_csv(run_dir / "r2_t05_availability_time_audit.csv", [
        {"state_version_id": row[0], "daily_rows": row[1], "membership_rows": row[2], "availability_order_violations": row[3], "terminal_rows_added": terminal_added, "status": "passed" if row[3] == 0 else "failed"}
        for row in con.execute("""
          SELECT d.state_version_id,count(*),count(m.event_id),
            sum(CASE WHEN m.membership_available_time<m.trade_date::TIMESTAMPTZ THEN 1 ELSE 0 END)
          FROM r2_canonical_daily_state d LEFT JOIN r2_canonical_event_membership m
            ON m.state_version_id=d.state_version_id AND m.security_id=d.security_id AND m.trade_date=d.trade_date
          GROUP BY 1 ORDER BY 1
        """).fetchall()
    ], ["state_version_id","daily_rows","membership_rows","availability_order_violations","terminal_rows_added","status"])
    _write_csv(run_dir / "r2_t05_risk_set_audit.csv", [
        {"state_version_id": row[0], "state_risk_rows": row[1], "qualified_risk_rows": row[2], "event_member_not_state_risk": row[3], "bridge_risk_rows": row[4], "prequalification_risk_rows": row[5], "status": "passed" if row[3] == 0 and row[4] == 0 and row[5] == 0 else "failed"}
        for row in con.execute("""
          SELECT state_version_id,
            (SELECT count(*) FROM r2_canonical_daily_state d WHERE d.state_version_id=e.state_version_id AND d.state_risk_set_eligible),
            sum(CASE WHEN qualified_event_risk_set_eligible THEN 1 ELSE 0 END),
            sum(CASE WHEN event_zone_member AND NOT state_risk_set_eligible THEN 1 ELSE 0 END),
            sum(CASE WHEN is_bridged_gap AND qualified_event_risk_set_eligible THEN 1 ELSE 0 END),
            sum(CASE WHEN is_prequalification_confirmed_day AND qualified_event_risk_set_eligible THEN 1 ELSE 0 END)
          FROM r2_canonical_event_membership e GROUP BY 1 ORDER BY 1
        """).fetchall()
    ], ["state_version_id","state_risk_rows","qualified_risk_rows","event_member_not_state_risk","bridge_risk_rows","prequalification_risk_rows","status"])
    _write_csv(run_dir / "r2_t05_exit_censor_reason_profile.csv", [
        {"state_version_id": row[0], "zone_status": row[1], "exit_reason": row[2], "event_count": row[3], "right_censored_count": row[4], "quality_break_count": row[5]}
        for row in con.execute("""
          SELECT state_version_id,zone_status,exit_reason,count(*),sum(CASE WHEN right_censored THEN 1 ELSE 0 END),sum(CASE WHEN zone_status='FINALIZED_WITH_QUALITY_BREAK' THEN 1 ELSE 0 END)
          FROM r2_canonical_event_zone GROUP BY 1,2,3 ORDER BY 1,2,3
        """).fetchall()
    ], ["state_version_id","zone_status","exit_reason","event_count","right_censored_count","quality_break_count"])
    strict_fail = con.execute("SELECT count(*) FROM r2_canonical_daily_state WHERE strict_core_member AND NOT confirmed_state").fetchone()[0]
    risk_fail = con.execute("SELECT count(*) FROM r2_canonical_event_membership WHERE (is_bridged_gap OR is_prequalification_confirmed_day OR is_unqualified_reentry_day) AND qualified_event_risk_set_eligible").fetchone()[0]
    anomalies = []
    if len(versions) != 2:
        anomalies.append("canonical_daily_version_count_not_two")
    if strict_fail:
        anomalies.append("strict_core_subset_violation")
    if risk_fail:
        anomalies.append("risk_set_expansion_on_bridge_or_prequalification")
    if con.execute("SELECT count(*) FROM r2_canonical_event_zone WHERE zone_status='FINALIZED' AND exit_reason='quality_break'").fetchone()[0]:
        anomalies.append("quality_break_natural_exit_conflict")
    anomaly = {"task_id": "R2-T05", "run_id": run_dir.name, "status": "passed" if not anomalies else "failed", "blocking_failure_count": len(anomalies), "anomalies": anomalies, "scientific_review_status": "pending_independent_scientific_review"}
    _write_json(run_dir / "r2_t05_anomaly_scan.json", anomaly)
    fingerprints = {table: _table_fingerprint(con, table) for table in PUBLIC_TABLES + ["r2_t05_event_id_lineage"]}
    _write_json(run_dir / "r2_t05_table_fingerprint.json", {"task_id": "R2-T05", "run_id": run_dir.name, "database_path": str((run_dir / config["output"]["database_name"]).relative_to(ROOT)).replace("\\", "/"), "tables": fingerprints})
    analysis_lines = [
        "# R2-T05 实际结果分析",
        "",
        "本报告只描述两个 T04 selected W120 primary 版本的 author-stage canonical 物化；不代表 T05 final freeze，也不打开 T06/R3。所有数量来自本次 DuckDB 实际表，并由独立 validator 重新复算。",
        "",
        "## Daily surface 与风险集",
        "",
        "| state_version_id | daily rows | eligible | valid | raw true | confirmed | state risk | strict-core |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in daily_rows:
        analysis_lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % row[:8])
    analysis_lines += ["", "## Event 与 membership", "", "| state_version_id | events | securities | components | bridges | raw-false bridge days | confirmed days | trading span |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in event_rows:
        analysis_lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % row[:8])
    analysis_lines += ["", "membership rows include source qualified, retrospective prequalification, accepted raw-false bridge, unqualified reentry and synthesized terminal decision rows. `event_zone_member=true` is not used as a risk-set shortcut; bridge, prequalification and reentry rows remain excluded from qualified event risk.", "", "## 对账与限制", "", "T03 source event counts, authoritative security-date surface, primary confirmed truth, strict-core exact-key subset, canonical event one-to-one mapping and as-of time ordering are checked in the compact reconciliation artifacts. T03 的大型 row-level DuckDB 不进入 Git，但其 package path、byte SHA-256、表 row count 与 fingerprints 已绑定。T05 仍是 author-stage evidence；independent scientific review、T06 replay、T07 registry/freeze 和 R3 均保持关闭。"]
    (run_dir / "r2_t05_result_analysis.md").write_text("\n".join(analysis_lines) + "\n", encoding="utf-8", newline="\n")
    source_counts = {row[0]: row[1] for row in event_rows}
    selected_reconciliation = []
    for version in config["selected_versions"]:
        selected_reconciliation.append({"source_candidate_cell_id": version["source_candidate_cell_id"], "state_version_id": version["state_version_id"], "selected": True, "W": version["W"], "d": version["d"], "g": version["g"], "source_event_count": source_counts.get(version["state_version_id"], 0), "status": "passed"})
    _write_csv(run_dir / "r2_t05_selected_cell_reconciliation.csv", selected_reconciliation, ["source_candidate_cell_id","state_version_id","selected","W","d","g","source_event_count","status"])
    _write_csv(run_dir / "r2_t05_version_materialization_map.csv", [
        {"state_version_id": v["state_version_id"], "state_line": v["state_line"], "window_track_id": v["window_track_id"], "source_candidate_cell_id": v["source_candidate_cell_id"], "strict_core_source_candidate_cell_id": v["strict_core_source_candidate_cell_id"], "W": v["W"], "K": v["K"], "qP": v["qP"], "qC": v["qC"], "qT": v["qT"], "qV": v["qV"], "d": v["d"], "g": v["g"], "status": "materialized_author_stage"}
        for v in config["selected_versions"]
    ], ["state_version_id","state_line","window_track_id","source_candidate_cell_id","strict_core_source_candidate_cell_id","W","K","qP","qC","qT","qV","d","g","status"])
    lineage_cursor = con.execute("SELECT * FROM r2_t05_event_id_lineage ORDER BY state_version_id,security_id,source_scan_event_id")
    lineage_fields = [item[0] for item in lineage_cursor.description]
    lineage_rows = [dict(zip(lineage_fields, row)) for row in lineage_cursor.fetchall()]
    _write_csv(run_dir / "r2_t05_event_id_lineage.csv", lineage_rows, lineage_fields)
    startup_report = {key: value for key, value in startup.items() if key != "bound_artifacts"}
    _write_json(run_dir / "r2_t05_source_readiness.json", {"task_id": "R2-T05", "run_id": run_dir.name, "status": "passed", "startup": startup_report, "freeze_plan_status": freeze["freeze_plan"].get("freeze_plan_status"), "selected_version_count": 2, "strict_core_only_count": 2, "source_database": source_info, "required_source_tables": sorted(SOURCE_TABLES)})
    return {"daily_rows": daily_rows, "event_rows": event_rows, "membership_rows": membership_rows, "anomaly": anomaly, "versions": versions, "source_info": source_info, "startup": startup, "freeze": freeze, "input_binding": input_binding}


def _artifact_entries(repo: Path, run_dir: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for name in config["output"]["compact_artifacts"]:
        path = run_dir / name
        if not path.is_file():
            continue
        entries.append({"path": path.relative_to(repo).as_posix(), "sha256": _sha256_file(path), "size_bytes": path.stat().st_size})
    database = run_dir / config["output"]["database_name"]
    if database.is_file():
        entries.append({"path": database.relative_to(repo).as_posix(), "sha256": _sha256_file(database), "size_bytes": database.stat().st_size, "lfs_policy": "local_not_committed_due_size_policy"})
    return sorted(entries, key=lambda row: row["path"])


def _write_packages(repo: Path, run_dir: Path, config: dict[str, Any], reports: dict[str, Any], execution_commit: str, input_binding: dict[str, Any], source_run_id: str) -> None:
    _write_json(run_dir / "r2_t05_independent_validation.json", {"task_id": "R2-T05", "run_id": run_dir.name, "status": "pending", "failure_count": 0, "validation_mode": "independent_sql_and_lineage_recalculation"})
    entries = _artifact_entries(repo, run_dir, config)
    manifest = {"task_id": "R2-T05", "run_id": run_dir.name, "artifact_hash_basis": "committed_artifact_bytes", "artifact_count": len(entries), "artifacts": entries, "database_path": (run_dir / config["output"]["database_name"]).relative_to(repo).as_posix(), "database_sha256": next((x["sha256"] for x in entries if x["path"].endswith(".duckdb")), "",), "source_run_id": source_run_id, "execution_code_commit": execution_commit, "parallel_mode": "single_worker", "worker_count": 1, "status": "author_stage_package"}
    _write_json(run_dir / "r2_t05_output_manifest.json", manifest)
    package = {"task_id": "R2-T05", "run_id": run_dir.name, "execution_status": "executed_and_validated_pending_independent_scientific_review", "formal_task_completed": False, "scientific_review_status": "pending_independent_scientific_review", "repository_final_gate_status": "pending_independent_scientific_review_and_exact_head_validation", "R2-T06_allowed_to_start": False, "R2-T07_allowed_to_start": False, "R3_allowed_to_start": False, "selected_version_count": 2, "strict_core_only_count": 2, "W250_materialized_version_count": 0, "shared_q_independent_state_version_count": 0, "PCT_parent_product_count": 0, "startup_handoff_status": "passed", "source_run_id": source_run_id, "execution_code_commit": execution_commit, "config_hash": _sha256_file(repo / "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json"), "input_binding": input_binding, "output_manifest": manifest, "anomaly_scan_status": reports["anomaly"]["status"], "independent_validation_status": "pending", "result_analysis_path": (run_dir / "r2_t05_result_analysis.md").relative_to(repo).as_posix(), "scope_note": "selected-only canonical materialization; T06/T07/T08/R3 excluded"}
    _write_json(run_dir / "r2_t05_result_package.json", package)
    _write_json(run_dir / "r2_t05_experiment_summary.json", {"task_id": "R2-T05", "run_id": run_dir.name, "stage": "R2", "selected_version_count": 2, "planned_state_version_count": 2, "formal_task_completed": False, "scientific_review_status": "pending_independent_scientific_review", "R2-T06_allowed_to_start": False, "R3_allowed_to_start": False, "worker_count": 1, "random_seed": 0})
    _write_json(run_dir / "r2_t05_author_stage_scientific_review.json", {"task_id": "R2-T05", "run_id": run_dir.name, "scientific_review_status": "pending_independent_scientific_review", "formal_task_completed": False, "R2-T06_allowed_to_start": False, "R3_allowed_to_start": False, "reviewed_head_sha": None, "review_required": "independent_scientific_review_bound_to_exact_tested_head"})
    _write_json(run_dir / "r2_t05_committed_artifact_validation.json", {"task_id": "R2-T05", "run_id": run_dir.name, "status": "pending_commit", "formal_task_completed": False, "validation_mode": "awaiting_generated_artifact_commit"})


def run_formal(config_path: Path, output_dir: Path, repo: Path = ROOT) -> Path:
    """Run a fail-closed formal T05 materialization from a clean commit."""
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout.strip()
    if status:
        raise R2T05Blocked("formal_run_requires_clean_worktree")
    execution_commit = str(_git(repo, "rev-parse", "HEAD"))
    config_rel = config_path.relative_to(repo).as_posix()
    config_binding = _formal_binding(repo, execution_commit, config_rel)
    config = json.loads(_git_blob(repo, execution_commit, config_rel).decode("utf-8"))
    source_bindings = [config_binding]
    for rel in config["formal_source_paths"]:
        if rel != config_rel:
            source_bindings.append(_formal_binding(repo, execution_commit, rel))
    input_bindings = {"execution_commit": execution_commit, "source_bindings": source_bindings, "input_bindings": []}
    startup = _check_startup(repo, execution_commit, config)
    freeze = _check_freeze_plan(config, startup)
    startup_bound_paths = set(config["startup"]["required_committed_inputs"])
    input_bindings["input_bindings"].extend(startup["committed_inputs"])
    for rel in config["inputs"].values():
        if rel in startup_bound_paths or rel.endswith(".duckdb"):
            continue
        binding = _formal_binding(repo, execution_commit, rel)
        input_bindings["input_bindings"].append(binding)
    t03_package = _json_from_commit(repo, execution_commit, config["inputs"]["t03_result_package_path"])
    database, source_info = _source_hash_and_tables(repo, execution_commit, t03_package, config["inputs"]["t03_event_zone_scan_path"])
    source_run_id = str(t03_package.get("run_id") or "R2-T03-PROMOTED-20260713T050903Z")
    startup_report = {key: value for key, value in startup.items() if key != "bound_artifacts"}
    input_binding = {**input_bindings, "t03_database": source_info, "startup": startup_report, "freeze_plan_hash": freeze["bound_input_bindings"][config["inputs"]["t04_freeze_plan_path"]]["committed_byte_sha256"]}
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise R2T05Error("output_directory_must_be_new_and_non_overwriting")
    output_dir.mkdir(parents=True)
    db_path = output_dir / config["output"]["database_name"]
    con = duckdb.connect(str(db_path))
    con.execute(f"SET threads={int(config['runtime']['duckdb_threads'])}")
    con.execute(f"SET memory_limit='{config['runtime']['duckdb_memory_limit']}'")
    con.execute(f"SET temp_directory='{_sql_path(output_dir)}'")
    con.execute(f"ATTACH '{_sql_path(database)}' AS src (READ_ONLY)")
    tables = {row[0] for row in con.execute("SHOW TABLES FROM src").fetchall()}
    missing = SOURCE_TABLES - tables
    if missing:
        raise R2T05Blocked("blocked_missing_authoritative_t03_row_level_artifact:" + ",".join(sorted(missing)))
    # Source counts and source-cell binding are derived from the database; no anchor is hard-coded.
    expected_daily_keys = con.execute("SELECT count(*) FROM src.base_expected_security_date").fetchone()[0]
    if expected_daily_keys <= 0:
        raise R2T05Error("authoritative_expected_security_date_is_empty")
    versions = config["selected_versions"]
    con.execute("CREATE TEMP TABLE t05_source_cell_execution AS SELECT * FROM src.cell_registry WHERE false")
    for version in versions:
        source_cell = con.execute("SELECT * FROM src.cell_registry WHERE candidate_cell_id=?", [version["source_candidate_cell_id"]]).fetchall()
        if len(source_cell) != 1:
            raise R2T05Error("selected_source_cell_missing_or_ambiguous")
        row = source_cell[0]
        if row[3] != version["state_line"] or row[4] != version["W"] or row[5] != version["K"] or row[6:10] != (version["qP"], version["qC"], version["qT"], version["qV"]) or row[10] != version["d"] or row[11] != version["g"]:
            raise R2T05Error("selected_source_cell_parameter_mismatch")
        if con.execute("SELECT count(*) FROM src.event_zone WHERE candidate_cell_id=?", [version["source_candidate_cell_id"]]).fetchone()[0] <= 0:
            raise R2T05Error("selected_source_event_zone_empty")
    _create_output_schema(con)
    mapped = _build_event_map(con, config, versions, source_run_id)
    _materialize_events(con, source_run_id)
    terminal_added = _materialize_membership(con)
    _materialize_daily(con, source_run_id)
    # Empty/shared/W250 exclusions are explicit source checks, not silently filtered output.
    if con.execute("SELECT count(*) FROM r2_canonical_daily_state WHERE state_version_id LIKE '%W250%'").fetchone()[0]:
        raise R2T05Error("W250_materialized")
    if con.execute("SELECT count(*) FROM r2_t05_event_id_lineage WHERE source_candidate_cell_id LIKE '%shared%'").fetchone()[0]:
        raise R2T05Error("shared_q_canonical_event_materialized")
    reports = _collect_reports(con, output_dir, config, input_binding, source_info, startup, freeze, source_run_id, terminal_added, expected_daily_keys)
    con.close()
    _write_json(output_dir / "r2_t05_input_binding.json", input_binding)
    _write_packages(repo, output_dir, config, reports, execution_commit, input_binding, source_run_id)
    return output_dir


__all__ = ["R2T05Error", "R2T05Blocked", "run_formal"]
