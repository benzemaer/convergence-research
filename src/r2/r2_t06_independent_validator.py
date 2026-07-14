# ruff: noqa: E501

"""Independent R2-T06 validator.

This module does not import the T06 runner.  It checks the committed startup
binding, recomputes component qualification from dense facts, and reconciles
the replay tables with the frozen T05 canonical tables.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import (
    ROOT,
    read_csv,
    write_csv,
    write_json,
    write_markdown,
)
from src.r2.r2_t06_source_trigger_oracle import source_trigger_validation

TASK_ID = "R2-T06"

AUDIT_FILES = (
    "r2_t06_atomic_interval_reconciliation.csv",
    "r2_t06_component_qualification_reconciliation.csv",
    "r2_t06_event_transition_reconciliation.csv",
    "r2_t06_event_zone_reconciliation.csv",
    "r2_t06_membership_reconciliation.csv",
    "r2_t06_no_lookahead_audit.csv",
    "r2_t06_exit_censor_audit.csv",
    "r2_t06_event_id_revision_audit.csv",
    "r2_t06_strict_core_risk_set_audit.csv",
    "r2_t06_unselected_exclusion_audit.csv",
    "r2_t06_count_geometry_reconciliation.csv",
)


class T06ValidationError(RuntimeError):
    """Raised when an independent validation assertion fails."""


def _git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fail(errors: list[str], condition: bool, code: str) -> None:
    if not condition:
        errors.append(code)


def _exact_mismatch(
    con: duckdb.DuckDBPyConnection, left: str, right: str, columns: str
) -> int:
    return int(
        con.execute(
            f"SELECT (SELECT count(*) FROM (SELECT {columns} FROM {left} EXCEPT ALL SELECT {columns} FROM {right})) + (SELECT count(*) FROM (SELECT {columns} FROM {right} EXCEPT ALL SELECT {columns} FROM {left}))"
        ).fetchone()[0]
    )


def _attach_readonly(con: duckdb.DuckDBPyConnection, path: str, alias: str) -> None:
    literal = path.replace("'", "''")
    con.execute(f"ATTACH '{literal}' AS {alias} (READ_ONLY)")


def _independent_intervals(
    rows: list[tuple[Any, ...]], d: int
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    intervals: list[tuple[Any, ...]] = []
    components: list[tuple[Any, ...]] = []
    streak = 0
    current: dict[str, Any] | None = None
    interval_ordinal = 0
    for index, row in enumerate(rows):
        trade_date, available_time, eligible, quality, raw_state, source_present = row
        valid_true = bool(
            source_present and eligible and quality == "valid" and raw_state is True
        )
        hard_break = not (
            source_present and eligible and quality == "valid" and raw_state is not None
        )
        streak = streak + 1 if valid_true else 0
        confirmed = valid_true and streak >= 3
        if confirmed and current is None:
            interval_ordinal += 1
            current = {
                "ordinal": interval_ordinal,
                "start_index": index,
                "start_date": trade_date,
                "end_date": trade_date,
                "count": 1,
            }
        elif confirmed and current is not None:
            current["end_date"] = trade_date
            current["count"] += 1
        elif current is not None:
            termination = "quality_interruption" if hard_break else "natural_state_exit"
            intervals.append(
                (
                    current["ordinal"],
                    current["start_date"],
                    current["end_date"],
                    current["count"],
                    termination,
                )
            )
            current = None
        if current is not None and confirmed:
            qualification_index = current["start_index"] + d - 1
            if current["count"] >= d:
                components.append(
                    (
                        f"component_{current['ordinal']:03d}",
                        current["start_date"],
                        current["end_date"],
                        current["count"],
                        True,
                    )
                )
            elif index >= qualification_index:
                components.append(
                    (
                        f"component_{current['ordinal']:03d}",
                        current["start_date"],
                        current["end_date"],
                        current["count"],
                        True,
                    )
                )
    if current is not None:
        intervals.append(
            (
                current["ordinal"],
                current["start_date"],
                current["end_date"],
                current["count"],
                "sample_end_censoring",
            )
        )
    # Components are interval-level identities; rebuild them from the completed
    # interval list so an interval that exits on its first non-confirmed row is
    # never accidentally retained as qualified.
    components = [
        (
            f"component_{ordinal:03d}",
            start_date,
            end_date,
            count,
            count >= d,
        )
        for ordinal, start_date, end_date, count, _termination in intervals
    ]
    return intervals, components


def _independent_lineage_checks(
    con: duckdb.DuckDBPyConnection,
    config: dict[str, Any],
    root: Path,
    checks: dict[str, int],
) -> None:
    route_map: dict[str, tuple[str, str, int]] = {}
    for version in config["selected_versions"]:
        route = con.execute(
            "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
            [version["source_candidate_cell_id"]],
        ).fetchone()
        if route is None:
            checks["independent_route_binding"] = 1
            continue
        route_map[version["state_version_id"]] = (
            route[0],
            version["source_candidate_cell_id"],
            int(version["d"]),
        )
    interval_mismatch = 0
    component_mismatch = 0
    components_by_route_security: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    for state, (route, _cell, d) in route_map.items():
        source_rows = con.execute(
            """
            SELECT route_id,security_id,trade_date,available_time,
                   eligible,quality_state,raw_state,source_row_present
            FROM src.route_dense_input WHERE route_id=? ORDER BY security_id,trade_date
            """,
            [route],
        ).fetchall()
        current_security: str | None = None
        bucket: list[tuple[Any, ...]] = []
        for row in source_rows + [(None, None, None, None, None, None, None, None)]:
            if current_security is not None and row[1] != current_security:
                intervals, components = _independent_intervals(bucket, d)
                observed_intervals = [
                    tuple(item)
                    for item in con.execute(
                        "SELECT ordinal,start_date,end_date,confirmed_day_count,termination_reason FROM r2_t06_replayed_atomic_interval WHERE route_id=? AND security_id=?",
                        [route, current_security],
                    ).fetchall()
                ]
                interval_mismatch += len(set(intervals) ^ set(observed_intervals))
                observed_components = [
                    tuple(item)
                    for item in con.execute(
                        "SELECT component_id,start_date,end_date,confirmed_day_count,qualified FROM r2_t06_replayed_component WHERE route_id=? AND security_id=?",
                        [route, current_security],
                    ).fetchall()
                ]
                component_mismatch += len(set(components) ^ set(observed_components))
                components_by_route_security[(route, current_security)] = components
                bucket = []
            if row[1] is None:
                break
            current_security = row[1]
            bucket.append(row[2:])
    checks["independent_interval_lineage_mismatch"] = interval_mismatch
    checks["independent_component_lineage_mismatch"] = component_mismatch

    event_identity_mismatch = 0
    for state, (route, cell, _d) in route_map.items():
        event_rows = con.execute(
            """
            SELECT event_id,security_id,
                   CAST(first_component_start_date AS VARCHAR),
                   CAST(first_qualification_time AS VARCHAR)
            FROM r2_t06_replayed_event_zone WHERE state_version_id=?
            """,
            [state],
        ).fetchall()
        for event_id, security, start_date, qtime in event_rows:
            components = components_by_route_security.get((route, security), [])
            component = next(
                (item for item in components if str(item[1]) == start_date and item[4]),
                None,
            )
            if component is None or qtime is None:
                event_identity_mismatch += 1
                continue
            payload = {
                "contract_version": config["contract_version"],
                "state_version_id": state,
                "security_id": security,
                "first_qualified_component_identity": {
                    "source_candidate_cell_id": cell,
                    "first_component_id": component[0],
                    "first_component_start_date": str(start_date),
                    "first_qualification_time": str(
                        datetime.fromisoformat(str(qtime).replace("Z", "+00:00"))
                    ),
                },
            }
            expected = hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            event_identity_mismatch += int(expected != event_id)
    checks["independent_event_identity_mismatch"] = event_identity_mismatch

    transition_path = root / config["t02_contracts"]["transition_registry"]
    if not transition_path.exists():
        checks["independent_transition_registry_mismatch"] = 1
    else:
        allowed = {
            (row["from_state"], row["to_state"], row["reason_code"])
            for row in read_csv(transition_path)
        }
        checks["independent_transition_registry_mismatch"] = sum(
            int((from_state, to_state, reason) not in allowed)
            for from_state, to_state, reason in con.execute(
                "SELECT from_state,to_state,reason_code FROM r2_t06_replayed_transition_ledger"
            ).fetchall()
        )

    source_overlay_mismatch = 0
    for state, (route, cell, _d) in route_map.items():
        source_overlay_mismatch += int(
            con.execute(
                """
                WITH ranked AS (
                  SELECT d.event_status_as_of,s.zone_status_as_of,
                         row_number() OVER (
                           PARTITION BY d.security_id,d.trade_date
                           ORDER BY s.available_time DESC,s.evaluation_time DESC,
                                    s.scan_event_id DESC
                         ) rn
                  FROM r2_t06_replayed_daily_state d
                  JOIN src.route_dense_input r
                    ON r.route_id=? AND r.security_id=d.security_id
                   AND r.trade_date=d.trade_date
                  JOIN src.event_zone_membership_daily s
                    ON s.candidate_cell_id=? AND s.security_id=d.security_id
                   AND s.trade_date=d.trade_date
                   AND s.available_time<=try_cast(r.available_time AS TIMESTAMPTZ)
                  WHERE d.state_version_id=?
                )
                SELECT count(*) FROM ranked
                WHERE rn=1 AND event_status_as_of IS DISTINCT FROM zone_status_as_of
                """,
                [route, cell, state],
            ).fetchone()[0]
        )
    checks["independent_current_event_overlay_mismatch"] = source_overlay_mismatch


def _audit_status_errors(output_dir: Path, config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name in AUDIT_FILES:
        path = output_dir / name
        if not path.exists():
            errors.append(f"audit_missing:{name}")
            continue
        rows = read_csv(path)
        if not rows:
            errors.append(f"audit_empty:{name}")
        for index, row in enumerate(rows):
            if row.get("status") != "passed":
                errors.append(f"audit_failed:{name}:{index}")
            try:
                if int(row.get("mismatch_count", "1")) != 0:
                    errors.append(f"audit_mismatch:{name}:{index}")
            except ValueError:
                errors.append(f"audit_mismatch_not_integer:{name}:{index}")
    configured = {
        name
        for name in config["output"]["compact_artifacts"]
        if name.endswith(".csv")
        and name
        not in {
            "r2_t06_replay_version_registry.csv",
            "r2_t06_daily_state_reconciliation.csv",
        }
    }
    errors.extend(
        f"audit_not_registered:{name}" for name in configured - set(AUDIT_FILES)
    )
    return errors


SOURCE_TRIGGER_AUDITS = {
    "r2_t06_event_transition_reconciliation.csv": (
        "source_trigger_transition_mismatch",
        "source_trigger_transition_time_mismatch",
    ),
    "r2_t06_event_zone_reconciliation.csv": (
        "source_trigger_event_partition_mismatch",
        "source_trigger_event_boundary_mismatch",
        "source_trigger_maximal_partition_mismatch",
        "source_trigger_finalization_time_mismatch",
        "source_trigger_bridge_mismatch",
    ),
    "r2_t06_membership_reconciliation.csv": (
        "source_trigger_membership_key_mismatch",
        "source_trigger_membership_flag_mismatch",
        "source_trigger_membership_availability_mismatch",
        "source_trigger_accepted_reentry_mismatch",
        "source_trigger_unqualified_reentry_mismatch",
    ),
    "r2_t06_no_lookahead_audit.csv": (
        "source_trigger_membership_availability_mismatch",
        "source_trigger_finalization_time_mismatch",
        "source_trigger_transition_time_mismatch",
    ),
    "r2_t06_exit_censor_audit.csv": (
        "source_trigger_quality_break_mismatch",
        "source_trigger_right_censor_mismatch",
        "source_trigger_finalization_time_mismatch",
    ),
}


def _write_source_trigger_audits(
    output_dir: Path, checks: dict[str, int], summary: dict[str, int]
) -> None:
    fields = [
        "audit",
        "scope",
        "observed",
        "expected",
        "mismatch_count",
        "status",
        "details",
    ]
    details = json.dumps(
        summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    for filename, check_names in SOURCE_TRIGGER_AUDITS.items():
        mismatch = sum(checks.get(name, 1) for name in check_names)
        write_csv(
            output_dir / filename,
            [
                {
                    "audit": "source_trigger_oracle",
                    "scope": "committed dense source facts and trigger ledger",
                    "observed": ";".join(
                        f"{name}={checks.get(name, 1)}" for name in check_names
                    ),
                    "expected": "all source-trigger mismatches equal zero",
                    "mismatch_count": mismatch,
                    "status": "passed" if mismatch == 0 else "failed",
                    "details": details,
                }
            ],
            fields,
        )


def _startup_checks(root: Path, config: dict[str, Any], errors: list[str]) -> None:
    binding = config["t05_binding"]
    refs = [
        (binding["t05_final_pr_head"], binding["t05_merge_commit"]),
        (binding["t05_merge_commit"], str(_git(root, "rev-parse", "origin/main"))),
        (binding["t05_artifact_commit"], binding["t05_final_pr_head"]),
        (binding["t05_execution_commit"], binding["t05_artifact_commit"]),
    ]
    for ancestor, descendant in refs:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            capture_output=True,
        )
        _fail(
            errors,
            result.returncode == 0,
            f"startup_ancestry:{ancestor[:8]}:{descendant[:8]}",
        )
    parents = str(
        _git(root, "show", "-s", "--format=%P", binding["t05_merge_commit"])
    ).split()
    _fail(errors, binding["t05_final_pr_head"] in parents, "startup_merge_parent")
    changed = set(
        str(
            _git(
                root,
                "-c",
                "core.quotePath=false",
                "diff",
                "--name-only",
                binding["t05_scientifically_reviewed_head"],
                binding["t05_final_pr_head"],
            )
        ).splitlines()
    )
    allowed = {
        "docs/tasks/R2-T05_canonical daily state、event zone 与 membership 物化.md",
        "docs/evidence/r2/R2-T05_canonical_materialization_successor_result_analysis.md",
        "docs/evidence/r2/R2-T05_canonical_materialization_independent_result_analysis.md",
    }
    _fail(errors, changed == allowed, "startup_reviewed_head_diff")
    t03 = ROOT / config["t03_input"]["database_path"]
    t05 = ROOT / config["t05_artifacts"]["database_path"]
    _fail(errors, t03.exists(), "startup_t03_database_missing")
    _fail(errors, t05.exists(), "startup_t05_database_missing")
    if t03.exists():
        _fail(
            errors,
            _sha256_file(t03) == config["t03_input"]["database_sha256"],
            "startup_t03_hash",
        )
    if t05.exists():
        _fail(
            errors,
            _sha256_file(t05) == config["t05_artifacts"]["database_sha256"],
            "startup_t05_hash",
        )


def validate_run(
    config_path: Path, output_dir: Path, root: Path = ROOT
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    _startup_checks(root, config, errors)
    database = output_dir / config["output"]["database_name"]
    _fail(errors, database.exists(), "output_database_missing")
    if not database.exists():
        raise T06ValidationError(";".join(errors))
    t05 = root / config["t05_artifacts"]["database_path"]
    t03 = root / config["t03_input"]["database_path"]
    con = duckdb.connect(str(database))
    _attach_readonly(con, str(t05), "canon")
    _attach_readonly(con, str(t03), "src")
    checks: dict[str, int] = {}
    try:
        daily_columns = "state_version_id,security_id,trade_date,eligible_state,raw_state,confirmed_state,confirmation_time,component_qualified_as_of,event_status_as_of,active_event_id_as_of,state_risk_set_eligible,qualified_event_risk_set_eligible,strict_core_member,quality_state,candidate_config_id"
        event_columns = "state_version_id,event_id,security_id,first_component_start_date,first_qualification_time,last_confirmed_end_date,last_exit_observation_time,zone_finalization_time,zone_status,exit_reason,left_censored,right_censored,component_interval_count,bridge_count,bridged_gap_days,zone_confirmed_day_count,zone_trading_span,confirmed_density,bridged_gap_ratio,zone_revision_count"
        membership_columns = "state_version_id,event_id,security_id,trade_date,confirmed_state,component_member,retrospective_component_member,component_qualified_as_of,event_zone_member,is_prequalification_confirmed_day,is_bridged_gap,is_unqualified_reentry_day,event_status_as_of,zone_revision,membership_available_time,state_risk_set_eligible,qualified_event_risk_set_eligible"
        checks["daily_exact_t05"] = _exact_mismatch(
            con,
            "r2_t06_replayed_daily_state",
            "canon.r2_canonical_daily_state",
            daily_columns,
        )
        checks["event_exact_t05"] = _exact_mismatch(
            con,
            "r2_t06_replayed_event_zone",
            "canon.r2_canonical_event_zone",
            event_columns,
        )
        checks["membership_exact_t05"] = _exact_mismatch(
            con,
            "r2_t06_replayed_event_membership",
            "canon.r2_canonical_event_membership",
            membership_columns,
        )
        checks["daily_qualified_key_mismatch"] = int(
            con.execute(
                "SELECT (SELECT count(*) FROM (SELECT state_version_id,security_id,trade_date FROM r2_t06_replayed_daily_state WHERE qualified_event_risk_set_eligible EXCEPT SELECT state_version_id,security_id,trade_date FROM r2_t06_replayed_event_membership WHERE qualified_event_risk_set_eligible))+(SELECT count(*) FROM (SELECT state_version_id,security_id,trade_date FROM r2_t06_replayed_event_membership WHERE qualified_event_risk_set_eligible EXCEPT SELECT state_version_id,security_id,trade_date FROM r2_t06_replayed_daily_state WHERE qualified_event_risk_set_eligible))"
            ).fetchone()[0]
        )
        checks["qualified_risk_formula_violation"] = int(
            con.execute(
                "SELECT count(*) FROM r2_t06_replayed_daily_state WHERE qualified_event_risk_set_eligible AND (NOT state_risk_set_eligible OR NOT confirmed_state OR NOT component_qualified_as_of OR active_event_id_as_of IS NULL)"
            ).fetchone()[0]
        )
        checks["strict_core_subset_violation"] = int(
            con.execute(
                "SELECT count(*) FROM r2_t06_replayed_daily_state WHERE strict_core_member AND NOT confirmed_state"
            ).fetchone()[0]
        )
        checks["active_event_fk_violation"] = int(
            con.execute(
                "SELECT count(*) FROM r2_t06_replayed_daily_state d LEFT JOIN r2_t06_replayed_event_zone e ON e.state_version_id=d.state_version_id AND e.event_id=d.active_event_id_as_of AND e.security_id=d.security_id WHERE d.active_event_id_as_of IS NOT NULL AND e.event_id IS NULL"
            ).fetchone()[0]
        )
        checks["membership_lookahead_violation"] = int(
            con.execute(
                "SELECT count(*) FROM r2_t06_replayed_event_membership m JOIN src.cell_registry c ON c.candidate_cell_id=(SELECT source_candidate_cell_id FROM (VALUES (?,?),(?,?)) x(state_version_id,source_candidate_cell_id) WHERE x.state_version_id=m.state_version_id) JOIN src.route_dense_input r ON r.route_id=c.route_id AND r.security_id=m.security_id AND r.trade_date=m.trade_date WHERE m.membership_available_time<try_cast(r.available_time AS TIMESTAMPTZ)",
                [
                    config["selected_versions"][0]["state_version_id"],
                    config["selected_versions"][0]["source_candidate_cell_id"],
                    config["selected_versions"][1]["state_version_id"],
                    config["selected_versions"][1]["source_candidate_cell_id"],
                ],
            ).fetchone()[0]
        )
        checks["qualified_component_lineage_mismatch"] = int(
            con.execute(
                "SELECT count(*) FROM r2_t06_replayed_component c WHERE c.qualified IS DISTINCT FROM (c.confirmed_day_count>=2) OR (c.qualified AND c.qualification_time IS NULL) OR (NOT c.qualified AND c.qualification_time IS NOT NULL)"
            ).fetchone()[0]
        )
        checks["qualified_component_prequalification_violation"] = int(
            con.execute(
                "SELECT count(*) FROM r2_t06_replayed_event_membership WHERE is_prequalification_confirmed_day AND qualified_event_risk_set_eligible"
            ).fetchone()[0]
        )
        checks["unqualified_reentry_risk_violation"] = int(
            con.execute(
                "SELECT count(*) FROM r2_t06_replayed_event_membership WHERE is_unqualified_reentry_day AND qualified_event_risk_set_eligible"
            ).fetchone()[0]
        )
        checks["transition_ledger_empty"] = int(
            con.execute(
                "SELECT CASE WHEN count(*)=0 THEN 1 ELSE 0 END FROM r2_t06_replayed_transition_ledger"
            ).fetchone()[0]
        )
        _independent_lineage_checks(con, config, root, checks)
        source_trigger_checks, source_trigger_summary = source_trigger_validation(
            con, config
        )
        checks.update(source_trigger_checks)
    finally:
        con.close()
    _write_source_trigger_audits(output_dir, checks, source_trigger_summary)
    errors.extend(_audit_status_errors(output_dir, config))
    errors.extend(name for name, value in checks.items() if value)
    result = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "passed" if not errors else "failed",
        "errors": sorted(set(errors)),
        "checks": checks,
        "source_trigger_oracle": True,
        "source_trigger_summary": source_trigger_summary,
        "independent_component_transition_lineage": True,
        "formal_task_completed": False,
        "R2-T07_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t06_independent_validation.json", result)
    write_json(
        output_dir / "r2_t06_anomaly_scan.json",
        {
            "task_id": TASK_ID,
            "run_id": output_dir.name,
            "status": result["status"],
            "anomaly_count": len(errors),
            "anomalies": sorted(set(errors)),
        },
    )
    write_markdown(
        output_dir / "r2_t06_result_analysis.md",
        "# R2-T06 实际结果分析\n\n"
        + "正式回放基于 committed T03 dense facts 独立重建确认、component、event zone、membership 与 daily as-of。\n\n"
        + "## 验收\n\n"
        + "\n".join(f"- `{key}`: `{value}`" for key, value in checks.items())
        + "\n\n## Source-trigger oracle\n\n"
        + "\n".join(
            f"- `{key}`: `{value}`" for key, value in source_trigger_summary.items()
        )
        + "\n\n结论："
        + result["status"]
        + "。author-stage 不推进科学审阅或下游 gate。\n",
    )
    write_json(
        output_dir / "r2_t06_committed_artifact_validation.json",
        {
            "task_id": TASK_ID,
            "run_id": output_dir.name,
            "status": "pending_committed_artifact_validation",
            "validated_commit": None,
        },
    )
    package = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "execution_status": "validated" if result["status"] == "passed" else "failed",
        "independent_validation_status": result["status"],
        "anomaly_scan_status": result["status"],
        "repository_final_gate_status": "pending_author_stage",
        "scientific_review_status": "pending_independent_scientific_review",
        "formal_task_completed": False,
        "R2-T06_formal_run_allowed": True,
        "R2-T07_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "output_manifest_path": f"{output_dir.relative_to(root).as_posix()}/r2_t06_output_manifest.json",
    }
    write_json(output_dir / "r2_t06_result_package.json", package)
    excluded = {
        "r2_t06_output_manifest.json",
        "r2_t06_result_package.json",
        "r2_t06_committed_artifact_validation.json",
    }
    artifacts = []
    for path in sorted(output_dir.iterdir()):
        if path.name in excluded or not path.is_file():
            continue
        artifacts.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    write_json(
        output_dir / "r2_t06_output_manifest.json",
        {
            "task_id": TASK_ID,
            "run_id": output_dir.name,
            "status": result["status"],
            "artifact_count": len(artifacts),
            "artifact_hash_basis": "committed_artifact_bytes",
            "artifacts": artifacts,
        },
    )
    return result


__all__ = ["T06ValidationError", "validate_run"]
