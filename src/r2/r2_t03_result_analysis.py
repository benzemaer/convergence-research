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
        metrics = con.execute(
            "SELECT state_line,W,d,g,qualified_event_count,confirmed_event_coverage,"
            "bridged_day_ratio FROM ("
            "SELECT *,retained_confirmed_day_ratio AS confirmed_event_coverage "
            "FROM metric_results) ORDER BY 1,2,3,4"
        ).fetchall()
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
    }
    observed = {name: con.execute(sql).fetchone()[0] for name, sql in queries.items()}
    failures = [name for name, value in observed.items() if value]
    ranges = con.execute(
        "SELECT min(qualified_event_count),max(qualified_event_count),"
        "min(confirmed_event_coverage),max(confirmed_event_coverage) FROM dg_event_zone_profile"
    ).fetchone()
    return {
        "task_id": "R2-T03",
        "status": "passed" if not failures else "investigation_required",
        "checks": observed,
        "failures": failures,
        "event_count_range": [ranges[0], ranges[1]],
        "confirmed_event_coverage_range": [ranges[2], ranges[3]],
        "downstream_progression_blocked": bool(failures),
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }


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
        lines.append(
            f"- `{state}` 的 36 个 cell 中，事件数范围为 {min(events)}–{max(events)}，confirmed-event coverage 范围为 {min(coverage):.6f}–{max(coverage):.6f}。"
        )
    lines.extend(
        [
            "",
            "## 有限推断与边界",
            "",
            "本扫描只审计状态机、区间几何、参数响应和守恒关系，不使用未来收益、方向或回测指标。primary 与 shared-q sidecar 的比较用于集合与几何诊断，不构成参数选择。上游日表未物理提供 `available_time` 与 `eligible` 字段；T03 config 自身不能充当上游证明。在 authoritative availability、route-security expected-key 与 normalized interval reconciliation contracts 解决前，successor formal run 必须 fail closed。",
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
            }
        ],
        "database_tables": tables,
        "status": "passed",
    }


def _git_blob(commit: str, path: str, root: Path) -> bytes:
    import subprocess

    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=root)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value: dict[str, Any], schema_path: Path) -> None:
    jsonschema.Draft202012Validator(_json(schema_path)).validate(value)
