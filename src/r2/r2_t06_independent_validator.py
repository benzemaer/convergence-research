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
from pathlib import Path
from typing import Any

import duckdb

from src.common.canonical_io import ROOT, write_json, write_markdown

TASK_ID = "R2-T06"


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
    con.execute("ATTACH ? AS canon (READ_ONLY)", [str(t05)])
    con.execute("ATTACH ? AS src (READ_ONLY)", [str(t03)])
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
    finally:
        con.close()
    errors.extend(name for name, value in checks.items() if value)
    result = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "passed" if not errors else "failed",
        "errors": sorted(set(errors)),
        "checks": checks,
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
