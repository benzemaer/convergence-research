# ruff: noqa: E501

"""R2-T06 independent replay and merged-PR startup contract.

The replay consumes only the committed T03 dense facts and the frozen T02
contract.  T05 is attached read-only for exact reconciliation after the replay;
its event-zone and membership tables are never used to construct the result.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import (
    ROOT,
    formal_source_binding,
    git_blob_sha,
    sha256_bytes,
    write_csv,
    write_json,
    write_markdown,
)
from src.r2.r2_t06_independent_fsm import (
    atomic_intervals as t06_atomic_intervals,
)
from src.r2.r2_t06_independent_fsm import (
    group_event_zones as t06_group_event_zones,
)

TASK_ID = "R2-T06"
CONTRACT_VERSION = "r2_t02_confirmed_event_zone_state_machine_contract.v8"


class T06Blocked(RuntimeError):
    """Raised for a fail-closed startup or lineage violation."""


class T06ReplayError(RuntimeError):
    """Raised for a deterministic replay failure."""


def _git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _git_blob(repo: Path, commit: str, rel: str) -> bytes:
    return _git(repo, "show", f"{commit}:{rel}", binary=True)


def _git_json(repo: Path, commit: str, rel: str) -> dict[str, Any]:
    try:
        return json.loads(_git_blob(repo, commit, rel).decode("utf-8"))
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as exc:
        raise T06Blocked(f"committed_json_unreadable:{commit}:{rel}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise T06Blocked(message)


def _ancestor(repo: Path, ancestor: str, descendant: str, label: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
    )
    _require(result.returncode == 0, f"git_ancestry_failure:{label}")


def _text_contract(payload: bytes, rel: str) -> None:
    _require(not payload.startswith(b"\xef\xbb\xbf"), f"bom:{rel}")
    _require(b"\r" not in payload, f"bare_cr:{rel}")
    _require(
        payload.endswith(b"\n") and not payload.endswith(b"\n\n"), f"terminal_lf:{rel}"
    )


def _manifest_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {Path(row["path"]).name: row for row in manifest.get("artifacts", [])}


def check_merged_pr_binding(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Validate the offline merged-PR T05 authorization contract."""
    binding = config["t05_binding"]
    final_head = binding["t05_final_pr_head"]
    merge_commit = binding["t05_merge_commit"]
    artifact_commit = binding["t05_artifact_commit"]
    execution_commit = binding["t05_execution_commit"]
    reviewed_head = binding["t05_scientifically_reviewed_head"]
    main_ref = (
        "origin/main"
        if subprocess.run(
            ["git", "cat-file", "-e", "origin/main^{commit}"],
            cwd=repo,
            capture_output=True,
        ).returncode
        == 0
        else "main"
    )
    main = str(_git(repo, "rev-parse", main_ref))
    _ancestor(repo, final_head, merge_commit, "final_head_merge_parent")
    _ancestor(repo, merge_commit, main, "merge_main_ancestor")
    _ancestor(repo, artifact_commit, final_head, "artifact_final_ancestor")
    _ancestor(repo, execution_commit, artifact_commit, "execution_artifact_ancestor")
    parents = str(_git(repo, "show", "-s", "--format=%P", merge_commit)).split()
    _require(final_head in parents, "final_head_not_merge_parent")
    _require(binding["t05_pr_number"] == 97, "t05_pr_number_drift")
    _require(
        binding["t05_scientific_review_id"] == "4686515222",
        "scientific_review_id_drift",
    )
    _require(
        binding["t05_scientific_review_status"] == "passed",
        "scientific_review_not_passed",
    )
    expected_versions = [
        {
            "state_version_id": "r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8",
            "source_candidate_cell_id": "r2_s_pct_w120_qt25_primary__d2__g1",
            "strict_core_source_candidate_cell_id": "r2_s_pct_w120_q20_shared__d2__g1",
            "state_line": "S_PCT",
        },
        {
            "state_version_id": "r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8",
            "source_candidate_cell_id": "r2_s_pcvt_w120_qv30_primary__d2__g1",
            "strict_core_source_candidate_cell_id": "r2_s_pcvt_w120_q20_shared__d2__g1",
            "state_line": "S_PCVT",
        },
    ]
    actual_versions = [
        {
            key: version.get(key)
            for key in (
                "state_version_id",
                "source_candidate_cell_id",
                "strict_core_source_candidate_cell_id",
                "state_line",
            )
        }
        for version in config.get("selected_versions", [])
    ]
    _require(actual_versions == expected_versions, "selected_version_binding_drift")
    _require(len(actual_versions) == 2, "selected_version_cardinality")
    _require(
        config.get("expected_exclusions")
        == {
            "selected_version_count": 2,
            "W250_independent_version_count": 0,
            "shared_q_independent_version_count": 0,
            "PCT_parent_product_count": 0,
            "additional_state_version_count": 0,
        },
        "unselected_version_exclusion_drift",
    )
    allowed_docs = {
        "docs/tasks/R2-T05_canonical daily state、event zone 与 membership 物化.md",
        "docs/evidence/r2/R2-T05_canonical_materialization_successor_result_analysis.md",
        "docs/evidence/r2/R2-T05_canonical_materialization_independent_result_analysis.md",
    }
    changed = set(
        str(
            _git(
                repo,
                "-c",
                "core.quotePath=false",
                "diff",
                "--name-only",
                reviewed_head,
                final_head,
            )
        ).splitlines()
    )
    _require(changed == allowed_docs, "reviewed_to_final_head_non_document_change")

    run_dir = config["t05_artifacts"]["run_dir"]
    manifest_rel = f"{run_dir}/r2_t05_output_manifest.json"
    manifest = _git_json(repo, final_head, manifest_rel)
    entries = _manifest_entries(manifest)
    package = _git_json(repo, final_head, f"{run_dir}/r2_t05_result_package.json")
    wrapper_names = {
        "r2_t05_result_package.json",
        "r2_t05_output_manifest.json",
        "r2_t05_committed_artifact_validation.json",
    }
    bound_artifacts: dict[str, dict[str, Any]] = {}
    for name in config["t05_artifacts"]["committed"]:
        rel = f"{run_dir}/{name}"
        entry = entries.get(name)
        _require(
            entry is not None or name in wrapper_names,
            f"t05_manifest_missing:{name}",
        )
        artifact = _git_blob(repo, artifact_commit, rel)
        for commit, label in (
            (artifact_commit, "artifact"),
            (final_head, "final"),
            (merge_commit, "merge"),
        ):
            candidate = _git_blob(repo, commit, rel)
            _require(candidate == artifact, f"t05_artifact_blob_drift:{name}:{label}")
        _text_contract(artifact, rel)
        if entry is not None:
            _require(
                sha256_bytes(artifact) == entry["sha256"],
                f"t05_manifest_sha_mismatch:{name}",
            )
        bound_artifacts[name] = {
            "path": rel,
            "git_blob_sha": git_blob_sha(artifact_commit, rel, root=repo),
            "committed_byte_sha256": sha256_bytes(artifact),
            "manifest_sha256": entry["sha256"] if entry is not None else None,
        }

    _require(
        package.get("run_id") == binding["t05_authoritative_run"],
        "t05_authoritative_run_drift",
    )
    _require(
        package.get("independent_validation_status") == "passed",
        "t05_independent_validation_failed",
    )
    _require(package.get("anomaly_scan_status") == "passed", "t05_anomaly_scan_failed")
    _require(
        package.get("repository_final_gate_status", "").startswith("pending"),
        "t05_author_stage_gate_changed",
    )
    _require(
        package.get("selected_version_count") == 2, "t05_selected_version_count_drift"
    )
    _require(
        package.get("W250_materialized_version_count") == 0, "t05_w250_exclusion_drift"
    )
    _require(
        package.get("shared_q_independent_state_version_count") == 0,
        "t05_shared_q_exclusion_drift",
    )
    _require(
        package.get("PCT_parent_product_count") == 0, "t05_pct_parent_exclusion_drift"
    )
    compact = [
        "r2_t05_daily_reconciliation.csv",
        "r2_t05_event_reconciliation.csv",
        "r2_t05_membership_reconciliation.csv",
        "r2_t05_risk_set_audit.csv",
        "r2_t05_strict_core_reconciliation.csv",
        "r2_t05_availability_time_audit.csv",
        "r2_t05_event_id_lineage.csv",
    ]
    for name in compact:
        text = _git_blob(repo, final_head, f"{run_dir}/{name}").decode("utf-8")
        reader = csv.DictReader(text.splitlines())
        statuses = [row.get("status") for row in reader if "status" in row]
        if statuses:
            _require(
                all(status == "passed" for status in statuses),
                f"t05_compact_audit_failed:{name}",
            )

    t05_path = ROOT / config["t05_artifacts"]["database_path"]
    t03_path = ROOT / config["t03_input"]["database_path"]
    _require(t05_path.exists(), "missing_authoritative_t05_database")
    _require(t03_path.exists(), "missing_authoritative_t03_database")
    _require(
        _sha256_file(t05_path) == config["t05_artifacts"]["database_sha256"],
        "t05_database_hash_mismatch",
    )
    _require(
        _sha256_file(t03_path) == config["t03_input"]["database_sha256"],
        "t03_database_hash_mismatch",
    )
    return {
        "main_commit": main,
        "main_ref": main_ref,
        "reviewed_head": reviewed_head,
        "final_head": final_head,
        "merge_commit": merge_commit,
        "artifact_commit": artifact_commit,
        "execution_commit": execution_commit,
        "authoritative_run": binding["t05_authoritative_run"],
        "artifact_manifest": manifest,
        "bound_artifacts": bound_artifacts,
        "t05_database_path": str(t05_path),
        "t03_database_path": str(t03_path),
    }


@dataclass(frozen=True)
class DailyRow:
    trade_date: date
    available_time: datetime
    eligible: bool
    quality_state: str
    raw_state: bool | None
    source_row_present: bool
    expected_empty_reason: str | None
    confirmed_state: bool
    confirmation_time: datetime | None
    confirmed_start_date: date | None
    hard_break: bool
    row_index: int


def replay_confirmation_rows(
    source_rows: Iterable[dict[str, Any]], K: int = 3
) -> list[DailyRow]:
    rows = list(source_rows)
    result: list[DailyRow] = []
    streak = 0
    active_start: date | None = None
    for index, raw in enumerate(rows):
        available = _timestamp(raw["available_time"])
        trade_date = _date(raw["trade_date"])
        eligible = bool(raw["eligible"])
        quality = str(raw["quality_state"])
        raw_state = None if raw["raw_state"] is None else bool(raw["raw_state"])
        source_row_present = bool(raw["source_row_present"])
        valid_true = (
            source_row_present and eligible and quality == "valid" and raw_state is True
        )
        hard_break = not (
            source_row_present
            and eligible
            and quality == "valid"
            and raw_state is not None
        )
        streak = streak + 1 if valid_true else 0
        confirmed = valid_true and streak >= K
        confirmation_time = available if valid_true and streak == K else None
        if confirmed and active_start is None:
            active_start = trade_date
        if not confirmed and result and result[-1].confirmed_state:
            active_start = None
        result.append(
            DailyRow(
                trade_date,
                available,
                eligible,
                quality,
                raw_state,
                bool(raw["source_row_present"]),
                raw.get("expected_empty_reason"),
                confirmed,
                confirmation_time,
                active_start,
                hard_break,
                index,
            )
        )
    return result


def canonical_event_id(
    state_version_id: str,
    source_candidate_cell_id: str,
    security_id: str,
    component_id: str,
    start_date: date,
    qualification_time: datetime,
) -> tuple[str, str]:
    payload = {
        "contract_version": CONTRACT_VERSION,
        "state_version_id": state_version_id,
        "security_id": security_id,
        "first_qualified_component_identity": {
            "source_candidate_cell_id": source_candidate_cell_id,
            "first_component_id": component_id,
            "first_component_start_date": start_date.isoformat(),
            "first_qualification_time": str(qualification_time),
        },
    }
    text = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256_bytes(text.encode("utf-8")), text


def _route_rows(con: duckdb.DuckDBPyConnection, route_id: str) -> list[tuple[Any, ...]]:
    return con.execute(
        """SELECT security_id,trade_date,available_time,eligible,quality_state,raw_state,
                  source_row_present,expected_empty_reason
           FROM src.route_dense_input WHERE route_id=? ORDER BY security_id,trade_date""",
        [route_id],
    ).fetchall()


def _security_groups(
    rows: list[tuple[Any, ...]],
) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    current: str | None = None
    bucket: list[dict[str, Any]] = []
    for row in rows:
        security = str(row[0])
        if current is not None and security != current:
            yield current, bucket
            bucket = []
        current = security
        bucket.append(
            {
                "security_id": security,
                "trade_date": row[1],
                "available_time": row[2],
                "eligible": row[3],
                "quality_state": row[4],
                "raw_state": row[5],
                "source_row_present": row[6],
                "expected_empty_reason": row[7],
            }
        )
    if current is not None:
        yield current, bucket


def _source_to_timeline(rows: list[dict[str, Any]], K: int) -> list[dict[str, Any]]:
    replayed = replay_confirmation_rows(rows, K=K)
    return [
        {
            "security_id": rows[i]["security_id"],
            "trade_date": item.trade_date.isoformat(),
            "row_index": item.row_index,
            "available_time": item.available_time.isoformat(),
            "eligible": item.eligible,
            "quality_state": item.quality_state,
            "raw_state": item.raw_state,
            "confirmed_state": item.confirmed_state,
            "confirmed_start_date": item.confirmed_start_date.isoformat()
            if item.confirmed_start_date
            else "",
            "confirmation_time": item.confirmation_time.isoformat()
            if item.confirmation_time
            else "",
            "hard_break": item.hard_break,
            "source_row_present": item.source_row_present,
            "expected_empty_reason": item.expected_empty_reason,
        }
        for i, item in enumerate(replayed)
    ]


def _event_rows_for_security(
    timeline: list[dict[str, Any]], route_id: str, version: dict[str, Any]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    intervals = t06_atomic_intervals(timeline)
    components, zones, ledger = t06_group_event_zones(
        timeline,
        intervals,
        int(version["d"]),
        int(version["g"]),
        candidate_cell_id=version["source_candidate_cell_id"],
    )
    component_rows: list[dict[str, Any]] = []
    interval_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    membership_rows: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    for ordinal, interval in enumerate(intervals, start=1):
        interval_id = sha256_bytes(
            f"dense-v1|{route_id}|{timeline[0]['security_id']}|{ordinal}|{interval['start_date']}|{interval['end_date']}".encode()
        )[:32]
        interval_rows.append(
            {
                "route_id": route_id,
                "security_id": timeline[0]["security_id"],
                "ordinal": ordinal,
                "start_date": interval["start_date"],
                "end_date": interval["end_date"],
                "confirmed_day_count": interval["confirmed_day_count"],
                "termination_reason": interval["termination_reason"],
                "exit_observation_time": timeline[interval["end_index"] + 1][
                    "available_time"
                ]
                if interval["end_index"] + 1 < len(timeline)
                else timeline[interval["end_index"]]["available_time"],
                "interval_id": interval_id,
            }
        )
    for component in components:
        qtime = component["event_qualification_time"] or None
        component_rows.append(
            {
                "route_id": route_id,
                "security_id": timeline[0]["security_id"],
                "component_id": component["component_id"],
                "interval_id": next(
                    row["interval_id"]
                    for row in interval_rows
                    if row["ordinal"] == int(component["component_id"].split("_")[-1])
                ),
                "start_date": component["start_date"],
                "end_date": component["end_date"],
                "confirmed_day_count": component["confirmed_day_count"],
                "qualified": bool(component["qualified"]),
                "qualification_time": qtime,
            }
        )
    for zone in zones:
        first = next(
            row
            for row in components
            if row["component_id"] == zone["first_component_id"]
        )
        qtime = _timestamp(first["event_qualification_time"])
        event_id, identity = canonical_event_id(
            version["state_version_id"],
            version["source_candidate_cell_id"],
            timeline[0]["security_id"],
            first["component_id"],
            _date(first["start_date"]),
            qtime,
        )
        zone_transitions = [
            row for row in ledger if row.get("scan_event_id") == zone["scan_event_id"]
        ]
        exit_reason = (
            zone_transitions[-1].get("reason_code")
            if zone_transitions
            else "sample_end_open_zone"
        )
        qualified_components = [
            row
            for row in components
            if row["component_id"] in {zone["first_component_id"]} or False
        ]
        last_component = max(
            (
                row
                for row in components
                if row["component_id"] in {m.get("component_id") for m in []}
            ),
            key=lambda row: row["end_date"],
            default=first,
        )
        component_ids = {first["component_id"]}
        for member in zone["membership_rows"]:
            idx = member["row_index"]
            if member["retrospective_component_member"]:
                component_ids.update(
                    c["component_id"]
                    for c in components
                    if c["start_index"] <= idx <= c["end_index"]
                )
        qualified_components = [
            c
            for c in components
            if c["component_id"] in component_ids and c["qualified"]
        ]
        last_component = max(qualified_components, key=lambda row: row["end_date"])
        first_index = next(
            c["start_index"]
            for c in components
            if c["component_id"] == first["component_id"]
        )
        event_end_date = _date(
            zone["zone_finalization_time"] or last_component["end_date"]
        )
        exit_times = [
            _timestamp(row["available_time"])
            for index, row in enumerate(timeline)
            if index > 0
            and _date(row["trade_date"]) <= event_end_date
            and _date(row["trade_date"]) >= _date(first["start_date"])
            and timeline[index - 1]["confirmed_state"]
            and not row["confirmed_state"]
        ]
        span = sum(
            1
            for row in timeline
            if _date(first["start_date"])
            <= _date(row["trade_date"])
            <= _date(last_component["end_date"])
        )
        event_rows.append(
            {
                "state_version_id": version["state_version_id"],
                "event_id": event_id,
                "security_id": timeline[0]["security_id"],
                "first_component_start_date": first["start_date"],
                "first_qualification_time": first["event_qualification_time"],
                "last_confirmed_end_date": last_component["end_date"],
                "last_exit_observation_time": max(exit_times) if exit_times else None,
                "zone_finalization_time": zone["zone_finalization_time"] or None,
                "zone_status": zone["status"],
                "exit_reason": exit_reason,
                "left_censored": first_index == 0,
                "right_censored": zone["status"] == "RIGHT_CENSORED",
                "component_interval_count": len(qualified_components),
                "bridge_count": zone["bridge_count"],
                "bridged_gap_days": zone["raw_false_bridged_day_count"],
                "zone_confirmed_day_count": sum(
                    component["confirmed_day_count"]
                    for component in qualified_components
                ),
                "zone_trading_span": span,
                "confirmed_density": sum(
                    component["confirmed_day_count"]
                    for component in qualified_components
                )
                / span
                if span
                else 0.0,
                "bridged_gap_ratio": zone["raw_false_bridged_day_count"] / span
                if span
                else 0.0,
                "zone_revision_count": zone["zone_revision"] + 1,
                "identity_payload": identity,
            }
        )
        for member in zone["membership_rows"]:
            source = timeline[member["row_index"]]
            retrospective = bool(member["retrospective_component_member"])
            membership_rows.append(
                {
                    "state_version_id": version["state_version_id"],
                    "event_id": event_id,
                    "security_id": timeline[0]["security_id"],
                    "trade_date": _date(member["trade_date"]),
                    "confirmed_state": bool(source["confirmed_state"]),
                    "component_member": retrospective
                    or bool(member["unqualified_reentry_member"]),
                    "retrospective_component_member": retrospective,
                    "component_qualified_as_of": bool(
                        member["component_qualified_as_of"]
                    ),
                    "event_zone_member": bool(member["event_zone_member"]),
                    "is_prequalification_confirmed_day": bool(
                        member["prequalification_member"]
                    ),
                    "is_bridged_gap": bool(member["is_bridged_gap"]),
                    "is_unqualified_reentry_day": bool(
                        member["unqualified_reentry_member"]
                    ),
                    "event_status_as_of": member["zone_status_as_of"],
                    "zone_revision": member["zone_revision_as_of"],
                    "membership_available_time": _timestamp(
                        member["membership_available_time"]
                    ),
                    "state_risk_set_eligible": bool(member["state_risk_set_eligible"]),
                    "qualified_event_risk_set_eligible": bool(
                        member["qualified_event_risk_set_eligible"]
                    ),
                }
            )
        if zone["zone_finalization_time"]:
            terminal_date = _date(zone["zone_finalization_time"])
            if not any(row["trade_date"] == terminal_date for row in membership_rows):
                terminal = next(
                    row for row in timeline if _date(row["trade_date"]) == terminal_date
                )
                membership_rows.append(
                    {
                        "state_version_id": version["state_version_id"],
                        "event_id": event_id,
                        "security_id": timeline[0]["security_id"],
                        "trade_date": terminal_date,
                        "confirmed_state": bool(terminal["confirmed_state"]),
                        "component_member": False,
                        "retrospective_component_member": False,
                        "component_qualified_as_of": False,
                        "event_zone_member": False,
                        "is_prequalification_confirmed_day": False,
                        "is_bridged_gap": False,
                        "is_unqualified_reentry_day": False,
                        "event_status_as_of": zone["status"],
                        "zone_revision": zone["zone_revision"],
                        "membership_available_time": _timestamp(
                            zone["zone_finalization_time"]
                        ),
                        "state_risk_set_eligible": False,
                        "qualified_event_risk_set_eligible": False,
                    }
                )
        for transition in ledger:
            if transition.get("scan_event_id") == zone["scan_event_id"]:
                transition_rows.append(
                    {
                        "state_version_id": version["state_version_id"],
                        "event_id": event_id,
                        "security_id": timeline[0]["security_id"],
                        "from_state": transition.get("from_state"),
                        "to_state": transition.get("to_state"),
                        "reason_code": transition.get("reason_code"),
                        "trigger_trade_date": _date(
                            transition.get("available_time", first["start_date"])
                        ),
                    }
                )
    return interval_rows, component_rows, event_rows, membership_rows, transition_rows


def _create_route_daily(
    con: duckdb.DuckDBPyConnection, route_ids: list[str], K: int
) -> None:
    marks = ",".join("?" for _ in route_ids)
    con.execute(
        f"""
        CREATE TEMP TABLE t06_route_daily AS
        WITH source AS (
          SELECT route_id,security_id,trade_date,
                 try_cast(available_time AS TIMESTAMPTZ) available_time,
                 eligible,quality_state,raw_state,source_row_present,
                 expected_empty_reason,
                 row_number() OVER (
                   PARTITION BY route_id,security_id ORDER BY trade_date
                 ) row_ordinal
          FROM src.route_dense_input
          WHERE route_id IN ({marks})
        ), marked AS (
          SELECT *,
                 source_row_present
                 AND eligible
                 AND quality_state='valid'
                 AND raw_state IS TRUE valid_true,
                 coalesce(sum(
                   CASE WHEN source_row_present
                             AND eligible
                             AND quality_state='valid'
                             AND raw_state IS TRUE
                        THEN 0 ELSE 1 END
                 ) OVER (
                   PARTITION BY route_id,security_id ORDER BY trade_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                 ),0) break_group
          FROM source
        ), streaked AS (
          SELECT *,
                 CASE WHEN valid_true THEN row_number() OVER (
                   PARTITION BY route_id,security_id,break_group
                   ORDER BY trade_date
                 ) ELSE 0 END streak
          FROM marked
        )
        SELECT route_id,security_id,trade_date,available_time,eligible,
               quality_state,raw_state,source_row_present,expected_empty_reason,
               valid_true AND streak>={int(K)} confirmed_state,
               CASE WHEN valid_true AND streak={int(K)}
                    THEN available_time END confirmation_time,
               CASE WHEN valid_true AND streak>={int(K)}
                    THEN min(trade_date) OVER (
                      PARTITION BY route_id,security_id,break_group
                    ) END confirmed_start_date,
               NOT (source_row_present
                    AND eligible
                    AND quality_state='valid'
                    AND raw_state IS NOT NULL) hard_break,
               (source_row_present
                AND eligible
                AND quality_state='valid'
                AND valid_true
                AND streak>={int(K)}) state_risk_set_eligible,
               row_ordinal
        FROM streaked
        ORDER BY route_id,security_id,trade_date
        """,
        route_ids,
    )


def _create_output_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE TABLE r2_t06_replayed_atomic_interval(route_id VARCHAR,security_id VARCHAR,ordinal INTEGER,start_date DATE,end_date DATE,confirmed_day_count INTEGER,termination_reason VARCHAR,exit_observation_time TIMESTAMPTZ,interval_id VARCHAR)"""  # noqa: E501
    )
    con.execute(
        """CREATE TABLE r2_t06_replayed_component(route_id VARCHAR,security_id VARCHAR,component_id VARCHAR,interval_id VARCHAR,start_date DATE,end_date DATE,confirmed_day_count INTEGER,qualified BOOLEAN,qualification_time TIMESTAMPTZ)"""  # noqa: E501
    )
    con.execute(
        """CREATE TABLE r2_t06_replayed_event_zone(state_version_id VARCHAR,event_id VARCHAR,security_id VARCHAR,first_component_start_date DATE,first_qualification_time TIMESTAMPTZ,last_confirmed_end_date DATE,last_exit_observation_time TIMESTAMPTZ,zone_finalization_time TIMESTAMPTZ,zone_status VARCHAR,exit_reason VARCHAR,left_censored BOOLEAN,right_censored BOOLEAN,component_interval_count INTEGER,bridge_count INTEGER,bridged_gap_days INTEGER,zone_confirmed_day_count INTEGER,zone_trading_span INTEGER,confirmed_density DOUBLE,bridged_gap_ratio DOUBLE,zone_revision_count INTEGER,identity_payload VARCHAR)"""  # noqa: E501
    )
    con.execute(
        """CREATE TABLE r2_t06_replayed_event_membership(state_version_id VARCHAR,event_id VARCHAR,security_id VARCHAR,trade_date DATE,confirmed_state BOOLEAN,component_member BOOLEAN,retrospective_component_member BOOLEAN,component_qualified_as_of BOOLEAN,event_zone_member BOOLEAN,is_prequalification_confirmed_day BOOLEAN,is_bridged_gap BOOLEAN,is_unqualified_reentry_day BOOLEAN,event_status_as_of VARCHAR,zone_revision INTEGER,membership_available_time TIMESTAMPTZ,state_risk_set_eligible BOOLEAN,qualified_event_risk_set_eligible BOOLEAN)"""  # noqa: E501
    )
    con.execute(
        """CREATE TABLE r2_t06_replayed_transition_ledger(state_version_id VARCHAR,event_id VARCHAR,security_id VARCHAR,from_state VARCHAR,to_state VARCHAR,reason_code VARCHAR,trigger_trade_date DATE)"""  # noqa: E501
    )


def _write_bindings(
    output_dir: Path,
    config_path: Path,
    config: dict[str, Any],
    startup: dict[str, Any],
    repo: Path,
) -> None:
    commit = str(_git(repo, "rev-parse", "HEAD"))
    sources = [
        config_path,
        repo / "src/r2/r2_t06_dual_state_machine_replay.py",
        repo / "src/r2/r2_t06_independent_fsm.py",
        repo / "src/r2/r2_t06_independent_validator.py",
        repo / "src/r2/r2_t06_committed_artifact_validator.py",
        repo / "schemas/r2/r2_t06_canonical_dual_state_machine_replay.schema.json",
        repo / "scripts/r2/run_r2_t06_dual_state_machine_replay.py",
        repo / "scripts/r2/validate_r2_t06_replay.py",
        repo / "scripts/r2/validate_r2_t06_committed_artifacts.py",
    ]
    write_json(
        output_dir / "r2_t06_input_binding.json",
        {
            "task_id": TASK_ID,
            "hash_authority": "committed_git_blob_only",
            "execution_commit": commit,
            "source_bindings": [
                formal_source_binding(path, commit, root=repo) for path in sources
            ],
            "t05_startup_binding": startup,
        },
    )


def _insert_rows(
    con: duckdb.DuckDBPyConnection,
    table: str,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> None:
    if not rows:
        return
    marks = ",".join("?" for _ in columns)
    con.executemany(
        f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})",
        [[row.get(column) for column in columns] for row in rows],
    )


def _attach_readonly(con: duckdb.DuckDBPyConnection, path: str, alias: str) -> None:
    literal = path.replace("'", "''")
    con.execute(f"ATTACH '{literal}' AS {alias} (READ_ONLY)")


def _daily_asof(
    con: duckdb.DuckDBPyConnection, versions: list[dict[str, Any]], run_id: str
) -> None:
    version_values = []
    for version in versions:
        version_values.extend(
            [
                version["state_version_id"],
                version["state_line"],
                version["source_candidate_cell_id"],
                version["strict_core_source_candidate_cell_id"],
            ]
        )
    con.execute(
        "CREATE TEMP TABLE t06_versions(state_version_id VARCHAR,state_line VARCHAR,primary_cell VARCHAR,strict_cell VARCHAR)"  # noqa: E501
    )
    con.executemany(
        "INSERT INTO t06_versions VALUES(?,?,?,?)",
        [version_values[i : i + 4] for i in range(0, len(version_values), 4)],
    )
    con.execute(
        f"""
        CREATE TABLE r2_t06_replayed_daily_state AS
        WITH primary_rows AS (
          SELECT v.state_version_id,v.state_line,
                 v.primary_cell candidate_config_id,d.security_id,
                 d.trade_date,d.available_time,d.eligible eligible_state,
                 d.raw_state,d.confirmed_state,d.confirmation_time,
                 d.state_risk_set_eligible,d.quality_state
          FROM t06_versions v
          JOIN t06_route_daily d
            ON d.route_id=(SELECT route_id FROM src.cell_registry
                           WHERE candidate_cell_id=v.primary_cell)
        ), strict_rows AS (
          SELECT v.state_version_id,s.security_id,s.trade_date,
                 s.confirmed_state strict_core_member
          FROM t06_versions v
          JOIN t06_route_daily s
            ON s.route_id=(SELECT route_id FROM src.cell_registry
                           WHERE candidate_cell_id=v.strict_cell)
        ), current_membership AS (
          SELECT p.*,m.event_id,m.component_qualified_as_of,
                 m.event_zone_member,m.is_prequalification_confirmed_day,
                 m.is_bridged_gap,m.is_unqualified_reentry_day,
                 row_number() OVER (
                   PARTITION BY p.state_version_id,p.security_id,p.trade_date
                   ORDER BY m.membership_available_time DESC,m.event_id DESC
                 ) rn
          FROM primary_rows p
          LEFT JOIN r2_t06_replayed_event_membership m
            ON m.state_version_id=p.state_version_id
           AND m.security_id=p.security_id
           AND m.trade_date=p.trade_date
           AND m.membership_available_time<=p.available_time
        ), source_membership_ranked AS (
          SELECT p.state_version_id,p.security_id,p.trade_date,
                 s.scan_event_id source_scan_event_id,
                 s.zone_status_as_of source_event_status_as_of,
                 s.event_zone_member source_event_zone_member,
                 s.is_raw_false_bridge source_is_bridged_gap,
                 s.prequalification_member source_is_prequalification,
                 s.unqualified_reentry_member source_is_unqualified_reentry,
                 row_number() OVER (
                   PARTITION BY p.state_version_id,p.security_id,p.trade_date
                   ORDER BY s.available_time DESC,s.evaluation_time DESC,
                            s.scan_event_id DESC
                 ) source_rn
          FROM primary_rows p
          LEFT JOIN src.event_zone_membership_daily s
            ON s.candidate_cell_id=p.candidate_config_id
           AND s.security_id=p.security_id
           AND s.trade_date=p.trade_date
           AND s.available_time<=p.available_time
        ), source_membership AS (
          SELECT * FROM source_membership_ranked WHERE source_rn=1
        ), source_event_ranked AS (
          SELECT s.*,m.event_id current_source_event_id,
                 row_number() OVER (
                   PARTITION BY s.state_version_id,s.security_id,s.trade_date
                   ORDER BY m.membership_available_time DESC,m.event_id DESC
                 ) event_map_rn
          FROM source_membership s
          LEFT JOIN r2_t06_replayed_event_membership m
            ON s.source_scan_event_id IS NOT NULL
           AND m.state_version_id=s.state_version_id
           AND m.security_id=s.security_id
           AND m.trade_date=s.trade_date
           AND m.event_status_as_of IS NOT DISTINCT FROM
               s.source_event_status_as_of
           AND m.event_zone_member IS NOT DISTINCT FROM
               s.source_event_zone_member
           AND m.is_prequalification_confirmed_day IS NOT DISTINCT FROM
               s.source_is_prequalification
           AND m.is_bridged_gap IS NOT DISTINCT FROM
               s.source_is_bridged_gap
           AND m.is_unqualified_reentry_day IS NOT DISTINCT FROM
               s.source_is_unqualified_reentry
        ), source_event AS (
          SELECT * FROM source_event_ranked WHERE event_map_rn=1
        ), history_raw AS (
          SELECT state_version_id,event_id,security_id,trade_date,
                 greatest(
                   membership_available_time,
                   trade_date::TIMESTAMPTZ + INTERVAL '15 hours'
                 ) effective_time,event_status_as_of
          FROM r2_t06_replayed_event_membership
        ), history AS (
          SELECT state_version_id,event_id,security_id,
                 effective_time-(row_number() OVER (
                   PARTITION BY state_version_id,security_id,effective_time
                   ORDER BY trade_date DESC,event_id DESC
                 )-1)*INTERVAL '1 microsecond' effective_time,
                 event_status_as_of
          FROM history_raw
        ), asof_history AS (
          SELECT p.state_version_id,p.security_id,p.trade_date,
                 h.event_id history_event_id,h.event_status_as_of history_status,
                 row_number() OVER (
                   PARTITION BY p.state_version_id,p.security_id,p.trade_date
                   ORDER BY h.effective_time DESC,h.event_id DESC
                 ) rn
          FROM primary_rows p
          LEFT JOIN history h
            ON h.state_version_id=p.state_version_id
           AND h.security_id=p.security_id
           AND p.available_time>=h.effective_time
        ), joined AS (
          SELECT c.*,h.history_event_id,h.history_status,
                 s.source_scan_event_id,s.source_event_status_as_of,
                 s.current_source_event_id,strict_core_member
          FROM current_membership c
          JOIN asof_history h USING(state_version_id,security_id,trade_date)
          JOIN source_event s USING(state_version_id,security_id,trade_date)
          JOIN strict_rows USING(state_version_id,security_id,trade_date)
          WHERE c.rn=1 AND h.rn=1
        )
        SELECT state_version_id,state_line,'W120' window_track_id,security_id,
               trade_date,eligible_state,raw_state,confirmed_state,
               confirmation_time,coalesce(component_qualified_as_of,false)
                 component_qualified_as_of,
               coalesce(source_event_status_as_of,history_status,'NO_EVENT')
                 event_status_as_of,
                 CASE
                   WHEN source_scan_event_id IS NOT NULL THEN
                     CASE WHEN source_event_status_as_of IN (
                       'COMPONENT_FORMING','QUALIFIED_ACTIVE','GAP_PENDING',
                       'REENTRY_PENDING_QUALIFICATION'
                     ) THEN current_source_event_id ELSE NULL END
                   WHEN history_status IN (
                     'COMPONENT_FORMING','QUALIFIED_ACTIVE','GAP_PENDING',
                     'REENTRY_PENDING_QUALIFICATION'
                   ) THEN history_event_id
                   ELSE NULL
                 END active_event_id_as_of,
               state_risk_set_eligible,
               state_risk_set_eligible
                 AND coalesce(event_zone_member,false)
                 AND coalesce(component_qualified_as_of,false)
                 AND NOT coalesce(is_bridged_gap,false)
                 AND NOT coalesce(is_prequalification_confirmed_day,false)
                 AND NOT coalesce(is_unqualified_reentry_day,false)
                 qualified_event_risk_set_eligible,
               strict_core_member,quality_state,candidate_config_id,
               '{run_id}' source_run_id
        FROM joined
        """
    )


def _compare_table(
    con: duckdb.DuckDBPyConnection, left: str, right: str, keys: list[str]
) -> int:
    columns = ",".join(keys)
    return int(
        con.execute(
            f"SELECT (SELECT count(*) FROM (SELECT {columns} FROM {left} EXCEPT ALL SELECT {columns} FROM {right}))+(SELECT count(*) FROM (SELECT {columns} FROM {right} EXCEPT ALL SELECT {columns} FROM {left}))"
        ).fetchone()[0]
    )


def _audit_row(
    audit: str,
    scope: str,
    observed: Any,
    expected: Any,
    mismatch_count: int,
    details: str = "",
) -> dict[str, Any]:
    return {
        "audit": audit,
        "scope": scope,
        "observed": observed,
        "expected": expected,
        "mismatch_count": mismatch_count,
        "status": "passed" if mismatch_count == 0 else "failed",
        "details": details,
    }


def _audit_versions(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = []
    for version in config["selected_versions"]:
        primary = con.execute(
            "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
            [version["source_candidate_cell_id"]],
        ).fetchone()
        strict = con.execute(
            "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
            [version["strict_core_source_candidate_cell_id"]],
        ).fetchone()
        _require(
            primary is not None and strict is not None, "audit_route_binding_missing"
        )
        rows.append(
            {
                "state_version_id": version["state_version_id"],
                "primary_cell": version["source_candidate_cell_id"],
                "primary_route": primary[0],
                "strict_route": strict[0],
                "d": int(version["d"]),
                "g": int(version["g"]),
            }
        )
    con.execute(
        "CREATE TEMP TABLE t06_audit_versions(state_version_id VARCHAR,primary_cell VARCHAR,primary_route VARCHAR,strict_route VARCHAR,d INTEGER,g INTEGER)"
    )
    con.executemany(
        "INSERT INTO t06_audit_versions VALUES(?,?,?,?,?,?)",
        [
            [
                row["state_version_id"],
                row["primary_cell"],
                row["primary_route"],
                row["strict_route"],
                row["d"],
                row["g"],
            ]
            for row in rows
        ],
    )
    return rows


def _event_identity_mismatch(con: duckdb.DuckDBPyConnection) -> int:
    rows = con.execute(
        """
        SELECT e.state_version_id,e.event_id,e.security_id,
               CAST(e.first_component_start_date AS VARCHAR),
               CAST(e.first_qualification_time AS VARCHAR),
               c.component_id,v.primary_cell
        FROM r2_t06_replayed_event_zone e
        JOIN t06_audit_versions v USING(state_version_id)
        LEFT JOIN r2_t06_replayed_component c
          ON c.route_id=v.primary_route
         AND c.security_id=e.security_id
         AND c.start_date=e.first_component_start_date
        """
    ).fetchall()
    mismatches = 0
    for state, event_id, security, start_date, qtime, component_id, cell in rows:
        if component_id is None or qtime is None:
            mismatches += 1
            continue
        expected, _ = canonical_event_id(
            state, cell, security, component_id, _date(start_date), _timestamp(qtime)
        )
        mismatches += int(expected != event_id)
    return mismatches


def _read_transition_registry(
    repo: Path, config: dict[str, Any]
) -> set[tuple[str, str, str]]:
    path = repo / config["t02_contracts"]["transition_registry"]
    _require(path.exists(), "transition_registry_missing")
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row["from_state"], row["to_state"], row["reason_code"])
            for row in csv.DictReader(handle)
        }


def _build_audits(
    con: duckdb.DuckDBPyConnection,
    config: dict[str, Any],
    repo: Path,
    mismatches: dict[str, int],
) -> dict[str, list[dict[str, Any]]]:
    versions = _audit_versions(con, config)
    audits: dict[str, list[dict[str, Any]]] = {}
    audits["r2_t06_atomic_interval_reconciliation.csv"] = []
    interval_mismatch = int(
        con.execute(
            """
            WITH expected AS (
              SELECT route_id,security_id,
                     row_number() OVER (
                       PARTITION BY route_id,security_id ORDER BY start_date,end_date
                     ) ordinal,start_date,end_date,confirmed_day_count,termination_reason
              FROM src.route_atomic_interval
              WHERE route_id IN (SELECT primary_route FROM t06_audit_versions)
            ), observed AS (
              SELECT route_id,security_id,ordinal,start_date,end_date,
                     confirmed_day_count,termination_reason
              FROM r2_t06_replayed_atomic_interval
            )
            SELECT (SELECT count(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM observed))
                 + (SELECT count(*) FROM (SELECT * FROM observed EXCEPT ALL SELECT * FROM expected))
            """
        ).fetchone()[0]
    )
    audits["r2_t06_atomic_interval_reconciliation.csv"].append(
        _audit_row(
            "atomic_interval_geometry",
            "selected_primary_routes",
            "replayed route/security/start/end/count/termination",
            "committed T03 route_atomic_interval semantic rows",
            interval_mismatch,
        )
    )

    component_mismatch = int(
        con.execute(
            """
            SELECT count(*)
            FROM r2_t06_replayed_component c
            JOIN t06_audit_versions v ON v.primary_route=c.route_id
            WHERE c.qualified IS DISTINCT FROM (c.confirmed_day_count >= v.d)
               OR (c.qualified AND c.qualification_time IS NULL)
               OR (NOT c.qualified AND c.qualification_time IS NOT NULL)
            """
        ).fetchone()[0]
    )
    audits["r2_t06_component_qualification_reconciliation.csv"] = [
        _audit_row(
            "component_qualification_lineage",
            "all replayed components",
            "qualified iff confirmed_day_count >= configured d",
            "qualification_time present exactly for qualified components",
            component_mismatch,
        )
    ]

    allowed_transitions = _read_transition_registry(repo, config)
    invalid_transitions = 0
    for from_state, to_state, reason in con.execute(
        "SELECT from_state,to_state,reason_code FROM r2_t06_replayed_transition_ledger"
    ).fetchall():
        invalid_transitions += int(
            (from_state, to_state, reason) not in allowed_transitions
        )
    orphan_transitions = int(
        con.execute(
            """
            SELECT count(*) FROM r2_t06_replayed_transition_ledger t
            LEFT JOIN r2_t06_replayed_event_zone e
              ON e.state_version_id=t.state_version_id AND e.event_id=t.event_id
             AND e.security_id=t.security_id
            WHERE t.event_id IS NOT NULL AND e.event_id IS NULL
            """
        ).fetchone()[0]
    )
    transition_mismatch = invalid_transitions + orphan_transitions
    audits["r2_t06_event_transition_reconciliation.csv"] = [
        _audit_row(
            "transition_registry_and_event_linkage",
            "replayed transition ledger",
            f"invalid_registry={invalid_transitions};orphan_event={orphan_transitions}",
            "every transition is in committed registry and links to same-version event",
            transition_mismatch,
        )
    ]

    zone_mismatch = int(
        con.execute(
            """
            WITH m AS (
              SELECT state_version_id,event_id,security_id,
                     sum(CASE WHEN retrospective_component_member AND confirmed_state
                              THEN 1 ELSE 0 END) qualified_confirmed_days,
                     sum(CASE WHEN is_bridged_gap THEN 1 ELSE 0 END) bridge_days,
                     max(zone_revision)+1 revisions,
                     count(*) membership_rows
              FROM r2_t06_replayed_event_membership
              GROUP BY ALL
            )
            SELECT count(*) FROM r2_t06_replayed_event_zone e
            LEFT JOIN m USING(state_version_id,event_id,security_id)
            WHERE coalesce(m.qualified_confirmed_days,0) <> e.zone_confirmed_day_count
               OR coalesce(m.bridge_days,0) <> e.bridged_gap_days
               OR coalesce(m.revisions,0) <> e.zone_revision_count
               OR coalesce(m.membership_rows,0) < e.zone_trading_span
               OR coalesce(m.membership_rows,0) > e.zone_trading_span + 2
            """
        ).fetchone()[0]
    )
    audits["r2_t06_event_zone_reconciliation.csv"] = [
        _audit_row(
            "event_zone_geometry",
            "event rows versus event membership",
            "confirmed component days, bridge days, revisions, membership span",
            "event aggregate fields equal independently queried membership aggregates",
            zone_mismatch,
        )
    ]

    membership_mismatch = int(
        con.execute(
            """
            SELECT count(*)
            FROM r2_t06_replayed_event_membership
            WHERE qualified_event_risk_set_eligible IS DISTINCT FROM (
                state_risk_set_eligible AND event_zone_member
                AND component_qualified_as_of
                AND NOT is_bridged_gap
                AND NOT is_prequalification_confirmed_day
                AND NOT is_unqualified_reentry_day
            )
               OR (is_bridged_gap AND state_risk_set_eligible)
               OR (is_prequalification_confirmed_day AND qualified_event_risk_set_eligible)
               OR (is_unqualified_reentry_day AND qualified_event_risk_set_eligible)
            """
        ).fetchone()[0]
    )
    audits["r2_t06_membership_reconciliation.csv"] = [
        _audit_row(
            "membership_risk_and_flag_formula",
            "all replayed membership rows",
            "risk flags and bridge/prequalification/reentry exclusions",
            "frozen membership formula with no excluded row in qualified risk",
            membership_mismatch,
        )
    ]

    lookahead_mismatch = int(
        con.execute(
            """
            SELECT count(*)
            FROM r2_t06_replayed_event_membership m
            JOIN t06_audit_versions v USING(state_version_id)
            JOIN src.route_dense_input r
              ON r.route_id=v.primary_route AND r.security_id=m.security_id
             AND r.trade_date=m.trade_date
            WHERE m.membership_available_time < try_cast(r.available_time AS TIMESTAMPTZ)
            """
        ).fetchone()[0]
    )
    audits["r2_t06_no_lookahead_audit.csv"] = [
        _audit_row(
            "membership_availability_not_before_source",
            "same security/trade date primary source rows",
            "membership_available_time earlier than source available_time",
            0,
            lookahead_mismatch,
        )
    ]

    exit_mismatch = int(
        con.execute(
            """
            SELECT count(*) FROM r2_t06_replayed_event_zone
            WHERE zone_status NOT IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED')
               OR (right_censored AND zone_finalization_time IS NOT NULL)
               OR (NOT right_censored AND zone_finalization_time IS NULL)
               OR exit_reason IS NULL OR exit_reason=''
            """
        ).fetchone()[0]
    )
    audits["r2_t06_exit_censor_audit.csv"] = [
        _audit_row(
            "event_exit_and_censor_semantics",
            "all replayed events",
            "status, finalization time, right censor flag and exit reason",
            "terminal statuses and timing fields are mutually consistent",
            exit_mismatch,
        )
    ]

    identity_mismatch = _event_identity_mismatch(con)
    duplicate_event_ids = int(
        con.execute(
            "SELECT count(*)-count(DISTINCT event_id) FROM r2_t06_replayed_event_zone"
        ).fetchone()[0]
    )
    revision_mismatch = identity_mismatch + max(duplicate_event_ids, 0)
    audits["r2_t06_event_id_revision_audit.csv"] = [
        _audit_row(
            "event_identity_and_revision",
            "all replayed events",
            f"identity_mismatch={identity_mismatch};duplicate_event_ids={duplicate_event_ids}",
            "canonical event hash matches first qualified component identity and IDs are unique",
            revision_mismatch,
        )
    ]

    strict_mismatch = int(
        con.execute(
            "SELECT count(*) FROM r2_t06_replayed_daily_state WHERE strict_core_member AND NOT confirmed_state"
        ).fetchone()[0]
    )
    audits["r2_t06_strict_core_risk_set_audit.csv"] = [
        _audit_row(
            "strict_core_subset",
            "daily strict-core rows",
            "strict_core_member rows outside confirmed state",
            0,
            strict_mismatch,
        )
    ]

    selected_states = {v["state_version_id"] for v in config["selected_versions"]}
    unselected_mismatch = int(
        con.execute(
            "SELECT count(*) FROM r2_t06_replayed_daily_state WHERE state_version_id NOT IN (SELECT state_version_id FROM t06_audit_versions)"
        ).fetchone()[0]
    )
    observed_states = {
        row[0]
        for row in con.execute(
            "SELECT DISTINCT state_version_id FROM r2_t06_replayed_daily_state"
        ).fetchall()
    }
    unselected_mismatch += int(observed_states != selected_states)
    audits["r2_t06_unselected_exclusion_audit.csv"] = [
        _audit_row(
            "selected_state_version_exclusion",
            "replayed output state versions",
            sorted(observed_states),
            sorted(selected_states),
            unselected_mismatch,
        )
    ]

    geometry_rows: list[dict[str, Any]] = []
    for version in versions:
        state = version["state_version_id"]
        observed = {
            "daily": int(
                con.execute(
                    "SELECT count(*) FROM r2_t06_replayed_daily_state WHERE state_version_id=?",
                    [state],
                ).fetchone()[0]
            ),
            "event": int(
                con.execute(
                    "SELECT count(*) FROM r2_t06_replayed_event_zone WHERE state_version_id=?",
                    [state],
                ).fetchone()[0]
            ),
            "membership": int(
                con.execute(
                    "SELECT count(*) FROM r2_t06_replayed_event_membership WHERE state_version_id=?",
                    [state],
                ).fetchone()[0]
            ),
            "daily_duplicate_excess": int(
                con.execute(
                    "SELECT count(*)-count(DISTINCT security_id || '|' || trade_date) FROM r2_t06_replayed_daily_state WHERE state_version_id=?",
                    [state],
                ).fetchone()[0]
            ),
        }
        expected = {
            "daily": int(
                con.execute(
                    "SELECT count(*) FROM src.route_dense_input WHERE route_id=?",
                    [version["primary_route"]],
                ).fetchone()[0]
            ),
            "event": int(
                con.execute(
                    "SELECT count(*) FROM src.event_zone WHERE candidate_cell_id=?",
                    [version["primary_cell"]],
                ).fetchone()[0]
            ),
            "membership_unique_key": True,
        }
        mismatch = int(observed["daily"] != expected["daily"])
        mismatch += int(observed["event"] != expected["event"])
        mismatch += max(observed["daily_duplicate_excess"], 0)
        geometry_rows.append(
            _audit_row(
                "count_and_geometry",
                state,
                observed,
                expected,
                mismatch,
                "event membership cardinality is checked separately by primary-key and zone audits",
            )
        )
    audits["r2_t06_count_geometry_reconciliation.csv"] = geometry_rows

    mismatches.update(
        {
            "atomic_interval": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_atomic_interval_reconciliation.csv"]
            ),
            "component": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_component_qualification_reconciliation.csv"]
            ),
            "transition": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_event_transition_reconciliation.csv"]
            ),
            "event_zone": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_event_zone_reconciliation.csv"]
            ),
            "membership": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_membership_reconciliation.csv"]
            ),
            "no_lookahead": sum(
                r["mismatch_count"] for r in audits["r2_t06_no_lookahead_audit.csv"]
            ),
            "exit_censor": sum(
                r["mismatch_count"] for r in audits["r2_t06_exit_censor_audit.csv"]
            ),
            "event_id": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_event_id_revision_audit.csv"]
            ),
            "strict_core": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_strict_core_risk_set_audit.csv"]
            ),
            "unselected": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_unselected_exclusion_audit.csv"]
            ),
            "count_geometry": sum(
                r["mismatch_count"]
                for r in audits["r2_t06_count_geometry_reconciliation.csv"]
            ),
        }
    )
    return audits


def _write_compact(
    output_dir: Path,
    config: dict[str, Any],
    run_id: str,
    startup: dict[str, Any],
    elapsed: float,
    repo: Path,
) -> None:
    database = output_dir / config["output"]["database_name"]
    con = duckdb.connect(str(database), read_only=True)
    _attach_readonly(con, startup["t03_database_path"], "src")
    _attach_readonly(con, startup["t05_database_path"], "canon")
    try:
        daily_columns = (
            "state_version_id,security_id,trade_date,eligible_state,raw_state,"
            "confirmed_state,confirmation_time,component_qualified_as_of,"
            "event_status_as_of,active_event_id_as_of,state_risk_set_eligible,"
            "qualified_event_risk_set_eligible,strict_core_member,quality_state,"
            "candidate_config_id"
        )
        event_columns = (
            "state_version_id,event_id,security_id,first_component_start_date,"
            "first_qualification_time,last_confirmed_end_date,last_exit_observation_time,"
            "zone_finalization_time,zone_status,exit_reason,left_censored,right_censored,"
            "component_interval_count,bridge_count,bridged_gap_days,zone_confirmed_day_count,"
            "zone_trading_span,confirmed_density,bridged_gap_ratio,zone_revision_count"
        )
        membership_columns = (
            "state_version_id,event_id,security_id,trade_date,confirmed_state,"
            "component_member,retrospective_component_member,component_qualified_as_of,"
            "event_zone_member,is_prequalification_confirmed_day,is_bridged_gap,"
            "is_unqualified_reentry_day,event_status_as_of,zone_revision,"
            "membership_available_time,state_risk_set_eligible,"
            "qualified_event_risk_set_eligible"
        )
        mismatches = {
            "daily": _compare_table(
                con,
                "r2_t06_replayed_daily_state",
                "canon.r2_canonical_daily_state",
                daily_columns.split(","),
            ),
            "event": _compare_table(
                con,
                "r2_t06_replayed_event_zone",
                "canon.r2_canonical_event_zone",
                event_columns.split(","),
            ),
            "membership": _compare_table(
                con,
                "r2_t06_replayed_event_membership",
                "canon.r2_canonical_event_membership",
                membership_columns.split(","),
            ),
        }
        _require(
            not any(mismatches.values()),
            f"t05_exact_reconciliation_failed:{mismatches}",
        )
        audit_rows = _build_audits(con, config, repo, mismatches)
        required_audits = {
            name
            for name in config["output"]["compact_artifacts"]
            if name.endswith(".csv")
            and name
            not in {
                "r2_t06_replay_version_registry.csv",
                "r2_t06_daily_state_reconciliation.csv",
            }
        }
        _require(
            set(audit_rows) == required_audits,
            "formal_audit_registry_incomplete",
        )
        audit_fields = [
            "audit",
            "scope",
            "observed",
            "expected",
            "mismatch_count",
            "status",
            "details",
        ]
        for name, rows in audit_rows.items():
            write_csv(output_dir / name, rows, audit_fields)
        counts = []
        for version in config["selected_versions"]:
            state = version["state_version_id"]
            counts.append(
                {
                    "state_version_id": state,
                    "daily_rows": con.execute(
                        "SELECT count(*) FROM r2_t06_replayed_daily_state WHERE state_version_id=?",
                        [state],
                    ).fetchone()[0],
                    "qualified_risk_rows": con.execute(
                        "SELECT count(*) FROM r2_t06_replayed_daily_state WHERE state_version_id=? AND qualified_event_risk_set_eligible",
                        [state],
                    ).fetchone()[0],
                    "event_rows": con.execute(
                        "SELECT count(*) FROM r2_t06_replayed_event_zone WHERE state_version_id=?",
                        [state],
                    ).fetchone()[0],
                    "membership_rows": con.execute(
                        "SELECT count(*) FROM r2_t06_replayed_event_membership WHERE state_version_id=?",
                        [state],
                    ).fetchone()[0],
                    "status": "passed",
                }
            )
        write_csv(
            output_dir / "r2_t06_replay_version_registry.csv",
            counts,
            [
                "state_version_id",
                "daily_rows",
                "qualified_risk_rows",
                "event_rows",
                "membership_rows",
                "status",
            ],
        )
        write_csv(
            output_dir / "r2_t06_daily_state_reconciliation.csv",
            [
                {
                    "check": f"t05_canonical_{key}_exact",
                    "mismatch_count": value,
                    "status": "passed" if value == 0 else "failed",
                }
                for key, value in mismatches.items()
                if key in {"daily", "event", "membership"}
            ],
            ["check", "mismatch_count", "status"],
        )
        write_json(
            output_dir / "r2_t06_source_readiness.json",
            {
                "task_id": TASK_ID,
                "status": "passed",
                "startup_status": "passed",
                "startup_authorization_mode": "merged_pr_direct_binding",
                "t05_authoritative_run": startup["authoritative_run"],
            },
        )
        write_json(
            output_dir / "r2_t06_replay_fingerprint.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "database_sha256": json.loads(
                    (output_dir / "r2_t06_materialization_complete.json").read_text(
                        encoding="utf-8"
                    )
                )["database_sha256"],
                "row_counts": counts,
            },
        )
        write_markdown(
            output_dir / "r2_t06_result_analysis.md",
            "# R2-T06 实际结果分析\n\n"
            f"正式回放 `{run_id}` 的 compact audits 均来自关闭后的只读 DuckDB 查询。"
            "本文件只记录 author-stage 实际结果，不推进科学审阅或下游 gate。\n",
        )
        write_json(
            output_dir / "r2_t06_experiment_summary.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "status": "executed_pending_independent_validation",
                "execution_commit": str(_git(repo, "rev-parse", "HEAD")),
                "elapsed_seconds": elapsed,
                "formal_run_executed": True,
                "formal_task_completed": False,
                "R2-T07_allowed_to_start": False,
                "R3_allowed_to_start": False,
            },
        )
        write_json(
            output_dir / "r2_t06_result_package.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "status": "executed_pending_independent_validation",
                "scientific_review_status": "pending_independent_scientific_review",
                "formal_task_completed": False,
                "R2-T06_formal_run_allowed": True,
                "R2-T07_allowed_to_start": False,
                "R3_allowed_to_start": False,
            },
        )
        write_json(
            output_dir / "r2_t06_author_stage_scientific_review.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "status": "pending_independent_scientific_review",
                "scientific_review_status": "pending_independent_scientific_review",
                "formal_task_completed": False,
                "R2-T07_allowed_to_start": False,
                "R3_allowed_to_start": False,
            },
        )
    finally:
        con.close()


def _write_materialization_complete(
    output_dir: Path,
    config: dict[str, Any],
    run_id: str,
    execution_commit: str,
) -> None:
    database = output_dir / config["output"]["database_name"]
    required_tables = {
        "r2_t06_replayed_atomic_interval",
        "r2_t06_replayed_component",
        "r2_t06_replayed_event_zone",
        "r2_t06_replayed_event_membership",
        "r2_t06_replayed_transition_ledger",
        "r2_t06_replayed_daily_state",
    }
    con = duckdb.connect(str(database), read_only=True)
    try:
        actual_tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        _require(
            required_tables <= actual_tables, "materialization_required_table_missing"
        )
        row_counts = {
            table: int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in required_tables
        }
    finally:
        con.close()
    write_json(
        output_dir / "r2_t06_materialization_complete.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "passed",
            "execution_commit": execution_commit,
            "database_sha256": _sha256_file(database),
            "required_tables": sorted(required_tables),
            "row_counts": row_counts,
            "connection_closed_before_finalization": True,
        },
    )


def run_formal(config_path: Path, output_dir: Path, repo: Path = ROOT) -> Path:
    started = time.time()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _require(config["task_id"] == TASK_ID, "config_task_id_mismatch")
    startup = check_merged_pr_binding(repo, config)
    _require(not output_dir.exists(), "formal_output_directory_already_exists")
    output_dir.mkdir(parents=True)
    run_id = output_dir.name
    database = output_dir / config["output"]["database_name"]
    con: duckdb.DuckDBPyConnection | None = duckdb.connect(str(database))
    try:
        con.execute("SET threads=1")
        con.execute("SET memory_limit='8GB'")
        con.execute("SET TimeZone='Asia/Shanghai'")
        _attach_readonly(con, startup["t03_database_path"], "src")
        _attach_readonly(con, startup["t05_database_path"], "canon")
        primary_routes = [
            con.execute(
                "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
                [v["source_candidate_cell_id"]],
            ).fetchone()[0]
            for v in config["selected_versions"]
        ]
        strict_routes = [
            con.execute(
                "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
                [v["strict_core_source_candidate_cell_id"]],
            ).fetchone()[0]
            for v in config["selected_versions"]
        ]
        route_ids = primary_routes + strict_routes
        _create_route_daily(con, route_ids, 3)
        _create_output_schema(con)
        interval_rows: list[dict[str, Any]] = []
        component_rows: list[dict[str, Any]] = []
        event_rows: list[dict[str, Any]] = []
        membership_rows: list[dict[str, Any]] = []
        transition_rows: list[dict[str, Any]] = []
        for version, route_id in zip(
            config["selected_versions"], primary_routes, strict=False
        ):
            for _security, raw_rows in _security_groups(_route_rows(con, route_id)):
                timeline = _source_to_timeline(raw_rows, 3)
                intervals, components, events, memberships, transitions = (
                    _event_rows_for_security(timeline, route_id, version)
                )
                interval_rows.extend(intervals)
                component_rows.extend(components)
                event_rows.extend(events)
                membership_rows.extend(memberships)
                transition_rows.extend(transitions)
        _insert_rows(
            con,
            "r2_t06_replayed_atomic_interval",
            interval_rows,
            [
                "route_id",
                "security_id",
                "ordinal",
                "start_date",
                "end_date",
                "confirmed_day_count",
                "termination_reason",
                "exit_observation_time",
                "interval_id",
            ],
        )
        _insert_rows(
            con,
            "r2_t06_replayed_component",
            component_rows,
            [
                "route_id",
                "security_id",
                "component_id",
                "interval_id",
                "start_date",
                "end_date",
                "confirmed_day_count",
                "qualified",
                "qualification_time",
            ],
        )
        _insert_rows(
            con,
            "r2_t06_replayed_event_zone",
            event_rows,
            [
                "state_version_id",
                "event_id",
                "security_id",
                "first_component_start_date",
                "first_qualification_time",
                "last_confirmed_end_date",
                "last_exit_observation_time",
                "zone_finalization_time",
                "zone_status",
                "exit_reason",
                "left_censored",
                "right_censored",
                "component_interval_count",
                "bridge_count",
                "bridged_gap_days",
                "zone_confirmed_day_count",
                "zone_trading_span",
                "confirmed_density",
                "bridged_gap_ratio",
                "zone_revision_count",
                "identity_payload",
            ],
        )
        _insert_rows(
            con,
            "r2_t06_replayed_event_membership",
            membership_rows,
            [
                "state_version_id",
                "event_id",
                "security_id",
                "trade_date",
                "confirmed_state",
                "component_member",
                "retrospective_component_member",
                "component_qualified_as_of",
                "event_zone_member",
                "is_prequalification_confirmed_day",
                "is_bridged_gap",
                "is_unqualified_reentry_day",
                "event_status_as_of",
                "zone_revision",
                "membership_available_time",
                "state_risk_set_eligible",
                "qualified_event_risk_set_eligible",
            ],
        )
        _insert_rows(
            con,
            "r2_t06_replayed_transition_ledger",
            transition_rows,
            [
                "state_version_id",
                "event_id",
                "security_id",
                "from_state",
                "to_state",
                "reason_code",
                "trigger_trade_date",
            ],
        )
        _daily_asof(con, config["selected_versions"], run_id)
        _write_bindings(output_dir, config_path, config, startup, repo)
        con.execute("CHECKPOINT")
    except BaseException as exc:
        if con is not None:
            con.close()
            con = None
        write_json(
            output_dir / "r2_t06_run_failure.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "status": "incomplete",
                "failure_type": type(exc).__name__,
                "failure": str(exc),
                "formal_run_executed": False,
            },
        )
        raise
    finally:
        if con is not None:
            con.close()
    execution_commit = str(_git(repo, "rev-parse", "HEAD"))
    _write_materialization_complete(output_dir, config, run_id, execution_commit)
    try:
        _write_compact(
            output_dir,
            config,
            run_id,
            startup,
            time.time() - started,
            repo,
        )
    except BaseException as exc:
        for name in config["output"]["compact_artifacts"]:
            path = output_dir / name
            if path.exists() and path.name != "r2_t06_materialization_complete.json":
                path.unlink()
        write_json(
            output_dir / "r2_t06_finalization_failure.json",
            {
                "task_id": TASK_ID,
                "run_id": run_id,
                "status": "incomplete",
                "failure_type": type(exc).__name__,
                "failure": str(exc),
                "materialization_complete": True,
                "formal_run_executed": False,
            },
        )
        raise
    return database


__all__ = [
    "T06Blocked",
    "T06ReplayError",
    "canonical_event_id",
    "check_merged_pr_binding",
    "replay_confirmation_rows",
    "run_formal",
]
