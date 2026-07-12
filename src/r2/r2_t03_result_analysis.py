# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import jsonschema

from src.common.canonical_io import (
    ROOT,
    current_commit,
    repo_rel,
    write_json,
    write_markdown,
)


def build_result_package(output_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    summary = _json(output_dir / "r2_t03_experiment_summary.json")
    runtime = _json(output_dir / "r2_t03_runtime_gate_validation.json")
    independent = _json(output_dir / "r2_t03_independent_validation.json")
    with (output_dir / "r2_t03_runtime_gate_results.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        scientific_failures = [
            row
            for row in csv.DictReader(handle)
            if row["status"] == "failed" and row["blocking"] == "False"
        ]
    database = output_dir / "r2_t03_event_zone_scan.duckdb"
    con = duckdb.connect(str(database), read_only=True)
    try:
        anomaly = _anomaly_scan(con)
        metrics = _analysis_metric_rows(con)
        table_rows = {
            row[0]: con.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0]
            for row in con.execute("SHOW TABLES").fetchall()
            if row[0] not in {"strict_pairs", "window_pairs"}
        }
    finally:
        con.close()
    write_json(output_dir / "r2_t03_anomaly_scan.json", anomaly)
    write_markdown(
        output_dir / "r2_t03_result_analysis.md",
        _analysis_markdown(metrics, anomaly, runtime, scientific_failures),
    )
    package = {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "execution_commit": summary["execution_commit"],
        "engineering_validation_status": runtime["status"],
        "independent_validation_status": independent["status"],
        "anomaly_scan_status": anomaly["status"],
        "scientific_review_status": "pending_independent_scientific_review",
        "author_package_lifecycle": "author_draft",
        "actual_scan_executed": True,
        "cell_count": summary["cell_count"],
        "selection_path_not_independently_confirmed": True,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    _validate(package, root / "schemas/r2/r2_t03_result_package.schema.json")
    write_json(output_dir / "r2_t03_result_package.json", package)
    manifest = _manifest(output_dir, summary["execution_commit"], table_rows, root)
    _validate(manifest, root / "schemas/r2/r2_t03_output_manifest.schema.json")
    write_json(output_dir / "r2_t03_output_manifest.json", manifest)
    return package


def validate_committed_artifacts(
    output_dir: Path, *, root: Path = ROOT
) -> dict[str, Any]:
    commit = current_commit(root)
    manifest = _json(output_dir / "r2_t03_output_manifest.json")
    failures = []
    bindings = []
    manifest_rel = repo_rel(output_dir / "r2_t03_output_manifest.json", root)
    manifest_blob = _git_blob(commit, manifest_rel, root)
    bindings.append(
        {
            "path": manifest_rel,
            "source_commit": commit,
            "committed_byte_sha256": hashlib.sha256(manifest_blob).hexdigest(),
            "working_tree_matches_committed": (
                (output_dir / "r2_t03_output_manifest.json").read_bytes()
                == manifest_blob
            ),
        }
    )
    if not bindings[-1]["working_tree_matches_committed"]:
        failures.append(f"working_tree:{manifest_rel}")
    for artifact in manifest["artifacts"]:
        path = root / artifact["path"]
        blob = _git_blob(commit, artifact["path"], root)
        digest = hashlib.sha256(blob).hexdigest()
        if digest != artifact["sha256"]:
            failures.append(f"hash:{artifact['path']}")
        if len(blob) != artifact["size_bytes"]:
            failures.append(f"size:{artifact['path']}")
        bindings.append(
            {
                "path": artifact["path"],
                "source_commit": commit,
                "committed_byte_sha256": digest,
                "working_tree_matches_committed": path.read_bytes() == blob,
            }
        )
        if not bindings[-1]["working_tree_matches_committed"]:
            failures.append(f"working_tree:{artifact['path']}")
    summary = _json(output_dir / "r2_t03_experiment_summary.json")
    package = _json(output_dir / "r2_t03_result_package.json")
    if manifest["artifact_count"] != len(manifest["artifacts"]):
        failures.append("artifact_count")
    if not (
        package["execution_commit"]
        == manifest["execution_commit"]
        == summary["execution_commit"]
    ):
        failures.append("execution_commit_identity")
    if not (
        package["run_id"] == manifest["run_id"] == summary["run_id"] == output_dir.name
    ):
        failures.append("run_id_identity")
    large = manifest["large_artifacts"][0]
    if large["database_fingerprint"] != manifest["database_fingerprint"]:
        failures.append("manifest_database_fingerprint_identity")
    database = root / large["path"]
    if not database.is_file():
        failures.append("large_database_missing")
    else:
        actual_bytes = database.read_bytes()
        if hashlib.sha256(actual_bytes).hexdigest() != large["sha256"]:
            failures.append("large_database_hash")
        if len(actual_bytes) != large["size_bytes"]:
            failures.append("large_database_size")
        from src.r2.r2_t03_event_zone_scan import _database_fingerprint

        with duckdb.connect(str(database), read_only=True) as con:
            actual_rows = {
                name: con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                for name in large["table_row_counts"]
            }
            actual_fingerprint = _database_fingerprint(con)
        if actual_rows != large["table_row_counts"]:
            failures.append("large_database_table_rows")
        if actual_fingerprint != large["database_fingerprint"]:
            failures.append("large_database_fingerprint")
        if actual_fingerprint != manifest["database_fingerprint"]:
            failures.append("manifest_database_fingerprint")
    if (
        _json(output_dir / "r2_t03_post_validation_fingerprint.json")
        != manifest["post_validation_fingerprint"]
    ):
        failures.append("post_validation_fingerprint")
    import subprocess

    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", manifest["execution_commit"], commit],
        cwd=root,
    ).returncode:
        failures.append("execution_commit_not_ancestor")
    report = {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "status": "passed" if not failures else "failed",
        "artifact_commit": commit,
        "binding_count": len(bindings),
        "bindings": bindings,
        "failures": failures,
        "scientific_review_status": "pending_independent_scientific_review",
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }
    write_json(output_dir / "r2_t03_committed_artifact_validation.json", report)
    if failures:
        raise RuntimeError("committed_artifact_validation_failed:" + failures[0])
    return report


def _anomaly_scan(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    queries = {
        "zero_event_cells": "SELECT count(*) FROM dg_event_zone_profile WHERE qualified_event_count=0",
        "one_event_cells": "SELECT count(*) FROM dg_event_zone_profile WHERE qualified_event_count=1",
        "null_metric_cells": "SELECT count(*) FROM dg_event_zone_profile WHERE qualified_event_count IS NULL OR confirmed_event_coverage IS NULL",
        "parameter_nonresponsive_groups": "SELECT count(*) FROM parameter_response_audit WHERE status<>'responsive'",
        "subset_violations": "SELECT count(*) FROM strict_core_window_comparison WHERE subset_violation",
        "availability_violations": "SELECT count(*) FROM event_zone_membership_daily WHERE membership_available_time<available_time OR evaluation_time<>membership_available_time",
        "risk_set_violations": "SELECT count(*) FROM event_zone_membership_daily WHERE qualified_event_risk_set_eligible IS DISTINCT FROM (state_risk_set_eligible AND event_zone_member AND component_qualified_as_of AND NOT is_raw_false_bridge AND NOT is_preconfirmation_gap)",
        "dense_interval_lineage_mismatch": "SELECT count(*) FROM route_atomic_interval WHERE upstream_source_interval_id IS NULL",
        "transition_closure": "SELECT count(*) FROM (SELECT e.scan_event_id FROM event_zone e LEFT JOIN transition_entity_ledger t ON t.candidate_cell_id=e.candidate_cell_id AND t.security_id=e.security_id AND t.entity_id=e.scan_event_id AND t.to_state IN ('FINALIZED','FINALIZED_WITH_QUALITY_BREAK','RIGHT_CENSORED') GROUP BY e.candidate_cell_id,e.security_id,e.scan_event_id HAVING count(t.entity_id)<>1)",
        "event_overlap_within_cell_security": "SELECT count(*) FROM event_zone a JOIN event_zone b ON a.candidate_cell_id=b.candidate_cell_id AND a.security_id=b.security_id AND a.scan_event_id<b.scan_event_id JOIN qualified_component qa ON qa.candidate_cell_id=a.candidate_cell_id AND qa.security_id=a.security_id AND qa.component_id=a.first_component_id JOIN qualified_component qb ON qb.candidate_cell_id=b.candidate_cell_id AND qb.security_id=b.security_id AND qb.component_id=b.first_component_id WHERE qa.start_date<=qb.end_date AND qb.start_date<=qa.end_date",
        "pending_status_timeline_gap": "SELECT count(*) FROM event_zone_membership_daily WHERE event_zone_member AND zone_status_as_of IS NULL",
        "bridge_gap_domination": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(nonconfirmed_gap_ratio,0)>.5 OR coalesce(bridged_day_ratio,0)>.5",
        "mega_zone_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(mega_zone_concentration,0)>.5",
        "max_zone_span_extreme": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(max_zone_span,0)>250",
        "top_zone_confirmed_day_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE coalesce(top_zone_confirmed_day_share,0)>.5",
        "duration_order_of_magnitude_shift": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE duration_q95_ratio>10 OR duration_q95_ratio<.1",
        "right_censor_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE right_censored_zone_count::DOUBLE/nullif(qualified_event_count,0)>.5",
        "quality_break_concentration": "SELECT count(*) FROM event_zone_diagnostic_profile WHERE quality_break_zone_count::DOUBLE/nullif(qualified_event_count,0)>.5",
        "upstream_confirmed_day_conservation": "SELECT count(*) FROM (SELECT q.candidate_cell_id,sum(q.confirmed_day_count) component_days,a.confirmed_state_days FROM qualified_component q JOIN atomic_baseline_profile a USING(candidate_cell_id) GROUP BY 1,3 HAVING component_days<>confirmed_state_days)",
        "window_own_common_denominator_mismatch": "SELECT count(*) FROM window_overlap_comparison WHERE intersection_confirmed_days>W120_own_eligible_days OR intersection_confirmed_days>W250_own_eligible_days OR common_eligible_days>least(W120_own_eligible_days,W250_own_eligible_days)",
        "asof_backfill": "SELECT count(*) FROM event_zone_membership_daily WHERE component_qualified_as_of AND membership_available_time<available_time",
    }
    observed = {name: con.execute(sql).fetchone()[0] for name, sql in queries.items()}
    engineering_ids = {
        "null_metric_cells",
        "subset_violations",
        "availability_violations",
        "risk_set_violations",
        "dense_interval_lineage_mismatch",
        "transition_closure",
        "event_overlap_within_cell_security",
        "pending_status_timeline_gap",
        "upstream_confirmed_day_conservation",
        "window_own_common_denominator_mismatch",
        "asof_backfill",
    }
    scientific_ids = {
        "zero_event_cells",
        "one_event_cells",
        "parameter_nonresponsive_groups",
        "bridge_gap_domination",
        "mega_zone_concentration",
        "max_zone_span_extreme",
        "top_zone_confirmed_day_concentration",
        "duration_order_of_magnitude_shift",
        "right_censor_concentration",
        "quality_break_concentration",
    }
    engineering = [name for name in engineering_ids if observed[name]]
    scientific = [name for name in scientific_ids if observed[name]]
    ranges = con.execute(
        "SELECT min(qualified_event_count),max(qualified_event_count),"
        "min(confirmed_event_coverage),max(confirmed_event_coverage) FROM dg_event_zone_profile"
    ).fetchone()
    return {
        "task_id": "R2-T03",
        "status": "passed" if not engineering else "investigation_required",
        "checks": observed,
        "failures": engineering + scientific,
        "blocking_engineering_anomalies": engineering,
        "scientific_investigation_items": scientific,
        "nonblocking_descriptive_warnings": [],
        "event_count_range": [ranges[0], ranges[1]],
        "confirmed_event_coverage_range": [ranges[2], ranges[3]],
        "downstream_progression_blocked": bool(engineering),
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }


def _analysis_metric_rows(con: duckdb.DuckDBPyConnection) -> list[tuple[Any, ...]]:
    """Read semantically distinct coverage fields from their authoritative tables."""
    return con.execute(
        """SELECT m.state_line,m.W,m.d,m.g,m.qualified_event_count,
        p.confirmed_event_coverage,m.retained_confirmed_day_ratio,
        q.retrospective_qualified_confirmed_coverage,q.asof_qualified_confirmed_coverage,
        m.bridged_day_ratio FROM metric_results m
        JOIN dg_event_zone_profile p USING(candidate_cell_id)
        JOIN d_qualification_profile q USING(candidate_cell_id) ORDER BY 1,2,3,4"""
    ).fetchall()


def _analysis_markdown(
    metrics: list[tuple[Any, ...]],
    anomaly: dict[str, Any],
    runtime: dict[str, Any],
    scientific_failures: list[dict[str, str]],
) -> str:
    by_state: dict[str, list[tuple[Any, ...]]] = {}
    for row in metrics:
        by_state.setdefault(row[0], []).append(row)
    lines = [
        "# R2-T03 实际结果合理性与异常扫描",
        "",
        f"工程 runtime gate：`{runtime['status']}`；异常扫描：`{anomaly['status']}`。本报告是 author-draft，未设置 scientific PASS，R2-T04 与 R3 均保持关闭。",
        "",
        "## 直接统计事实",
        "",
    ]
    for state, rows in sorted(by_state.items()):
        events = [row[4] for row in rows]
        coverage = [row[5] for row in rows if row[5] is not None]
        retained = [row[6] for row in rows if row[6] is not None]
        lines.append(
            f"- `{state}` 的 36 个 cell 中，事件数范围为 {min(events)}–{max(events)}，confirmed-event coverage 范围为 {min(coverage):.6f}–{max(coverage):.6f}，retained confirmed-day ratio 范围为 {min(retained):.6f}–{max(retained):.6f}。"
        )
    lines.extend(
        [
            "",
            "## 有限推断与边界",
            "",
            "本扫描只审计状态机、区间几何、参数响应和守恒关系，不使用未来收益、方向或回测指标。primary 与 shared-q sidecar 的比较用于集合与几何诊断，不构成参数选择。availability policy、expected-key adapter 与 interval adapter 已解决；successor actual result 仍须由正式运行和独立验证确认。",
            "",
            "## 异常结论",
            "",
            f"异常项：{', '.join(anomaly['failures']) if anomaly['failures'] else '无阻断异常'}。无论本项结果如何，本 author-draft 都不授权推进 R2-T04；后续仍需独立 scientific review。",
            "",
            "## 冻结 scientific gate 诊断",
            "",
            (
                f"共有 {len(scientific_failures)} 个非工程阻断的冻结 gate 失败；"
                "这些结果全部保留为 scientific review 输入，不用于选取或排除 cell。"
                if scientific_failures
                else "冻结 scientific gate 未报告失败。"
            ),
            "",
            *[
                f"- `{row['candidate_cell_id']}`：`{row['check_id']}` observed={row['observed_value']}，规则 `{row['expected_rule']}`。"
                for row in scientific_failures
            ],
        ]
    )
    return "\n".join(lines) + "\n"


def _manifest(
    output_dir: Path, execution_commit: str, tables: dict[str, int], root: Path
) -> dict[str, Any]:
    excluded = {
        "r2_t03_output_manifest.json",
        "r2_t03_committed_artifact_validation.json",
        "r2_t03_event_zone_scan.duckdb",
    }
    artifacts = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name not in excluded:
            data = path.read_bytes()
            artifacts.append(
                {
                    "path": repo_rel(path, root),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                }
            )
    database = output_dir / "r2_t03_event_zone_scan.duckdb"
    database_bytes = database.read_bytes()
    summary = _json(output_dir / "r2_t03_experiment_summary.json")
    post = _json(output_dir / "r2_t03_post_validation_fingerprint.json")
    return {
        "task_id": "R2-T03",
        "run_id": output_dir.name,
        "execution_commit": execution_commit,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "large_artifacts": [
            {
                "path": repo_rel(database, root),
                "sha256": hashlib.sha256(database_bytes).hexdigest(),
                "size_bytes": len(database_bytes),
                "lifecycle": "local_large_artifact_not_committed",
                "table_row_counts": tables,
                "database_fingerprint": summary["database_fingerprint"],
            }
        ],
        "database_tables": tables,
        "config_sha256": summary["config_sha256"],
        "source_readiness_sha256": summary["source_readiness_sha256"],
        "input_binding_sha256": summary["input_binding_sha256"],
        "database_fingerprint": summary["database_fingerprint"],
        "post_validation_fingerprint": post,
        "status": "passed",
    }


def _git_blob(commit: str, path: str, root: Path) -> bytes:
    import subprocess

    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=root)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value: dict[str, Any], schema_path: Path) -> None:
    jsonschema.Draft202012Validator(_json(schema_path)).validate(value)
