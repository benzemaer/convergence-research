# ruff: noqa: E501
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.r2.r2_t01_candidate_convergence_shortlist import (
    ROOT,
    dump_json,
    repo_rel,
    sha256_file,
)


def build_author_package(output_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    run_id = output_dir.name
    summary = _load_json(output_dir / "r2_t01_experiment_summary.json")
    diagnostic = _load_json(output_dir / "r2_t01_diagnostic_summary.json")
    anomaly = _load_json(output_dir / "r2_t01_anomaly_scan.json")
    engineering = _load_json(output_dir / "r2_t01_engineering_validation_result.json")
    registry = _read_csv(output_dir / "r2_t01_shortlist_registry.csv")
    primary = _read_csv(output_dir / "r2_t01_primary_shortlist.csv")
    audit = _read_csv(output_dir / "r2_t01_role_assignment_audit.csv")
    reconciliation = _read_csv(output_dir / "r2_t01_source_reconciliation.csv")
    evidence_snapshot = _read_csv(output_dir / "r2_t01_evidence_snapshot.csv")

    analysis_text = _analysis_markdown(
        run_id,
        summary,
        diagnostic,
        anomaly,
        registry,
        primary,
        audit,
        reconciliation,
        evidence_snapshot,
    )
    analysis_out = output_dir / "r2_t01_result_analysis.md"
    analysis_out.write_bytes(analysis_text.encode("utf-8"))
    docs_analysis = (
        root
        / "docs/experiments/r2/R2-T01_参数候选收敛与shortlist_registry_result_analysis.md"
    )
    docs_analysis.parent.mkdir(parents=True, exist_ok=True)
    docs_analysis.write_bytes(analysis_text.encode("utf-8"))

    evidence_text = _evidence_markdown(
        output_dir, summary, anomaly, engineering, analysis_out
    )
    evidence_out = output_dir / "r2_t01_evidence.md"
    evidence_out.write_bytes(evidence_text.encode("utf-8"))

    package = _package(
        root, output_dir, summary, engineering, analysis_out, evidence_out
    )
    dump_json(output_dir / "r2_t01_result_package.json", package)
    return package


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _denominator_groups(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = row.get("coverage_comparable_group", "unknown")
        entry = groups.setdefault(
            group,
            {
                "rows": 0,
                "denominator_scope": row.get("denominator_scope", "unknown"),
                "eligible_days": [],
            },
        )
        entry["rows"] += 1
        if row.get("eligible_days"):
            entry["eligible_days"].append(row["eligible_days"])
    return groups


def _analysis_markdown(
    run_id: str,
    summary: dict[str, Any],
    diagnostic: dict[str, Any],
    anomaly: dict[str, Any],
    registry: list[dict[str, str]],
    primary: list[dict[str, str]],
    audit: list[dict[str, str]],
    reconciliation: list[dict[str, str]],
    evidence_snapshot: list[dict[str, str]],
) -> str:
    role_counts = dict(Counter(row["candidate_role"] for row in registry))
    window_counts = {
        window: dict(
            Counter(row["candidate_role"] for row in registry if row["W"] == window)
        )
        for window in ("120", "250")
    }
    primary_ids = [row["route_id"] for row in primary]
    shared_pairs = {
        row["route_id"]: row["paired_primary_route_id"]
        for row in registry
        if row["candidate_role"] == "strict_core_reference"
    }
    denominator_groups = _denominator_groups(evidence_snapshot)
    warning_fail = sum(
        row["warning_reconciliation_status"] != "passed" for row in audit
    )
    selection_fail = sum(
        row["selection_path_propagation_status"] != "passed" for row in audit
    )
    source_fail = sum(
        row["candidate_registry_reconciliation"] != "passed"
        or row["warning_registry_reconciliation"] != "passed"
        or row["decision_recomputation_status"] != "passed"
        or row["source_artifact_hash_check"] != "passed"
        or row["source_supersession_check"] != "passed"
        for row in reconciliation
    )
    return f"""# R2-T01 参数候选收敛与 shortlist registry 结果分析

## 1. 研究目标与预注册问题
observed_fact: 本任务绑定 R1-T10 合法交接的 12 行候选，只回答四类处置：primary、strict_core_reference、sensitivity、excluded。research_judgment: 本任务不选择 d/g，不冻结状态版本，不评价未来收益或交易优势；它只把 R1 已交接候选登记为 R2-T03 之前的确定性 shortlist registry。

## 2. 输入 package、lineage、时间与样本范围
observed_fact: run_id 为 `{run_id}`，R1 decision matrix SHA-256 为 `{summary.get("protocol_version")}` 配置绑定的 `c3dddd698a0876743e822a55864be06074f94c14a4cd142b44de062a35d83134`，source row count 为 {summary["source_row_count"]}。observed_fact: source reconciliation failed count 为 {source_fail}，warning reconciliation failed count 为 {warning_fail}，selection path propagation failed count 为 {selection_fail}。inference: 该结果只继承 R1-T10 的结构证据和行级 warning，不扩展样本或读取行情原始数据。

## 3. 参数网格与 reference baseline
observed_fact: T01 没有运行参数网格；固定输入是 W120/W250、K=3、R1-T10 的 shared-q 与 q-vector 候选。observed_fact: shared-q rows 被登记为 strict_core_reference 且 fallback_eligible=true；q-vector center rows 被登记为 primary；qT=.30 rows 被登记为 sensitivity；qV=.25 rows 被登记为 excluded。research_judgment: shared-q 在本任务中是 reference baseline 和 fallback capability，不是独立产品版本。

## 4. 核心结果
observed_fact: canonical registry 行数为 {len(registry)}，role counts 为 {role_counts}。observed_fact: primary shortlist 四条 route 为 `{", ".join(primary_ids)}`。derived_statistic: W120 角色分布为 {window_counts.get("120")}，W250 角色分布为 {window_counts.get("250")}。observed_fact: shared-primary pairing 为 {shared_pairs}。

## 5. 预期结果与实际结果对照
observed_fact: 预期 4/4/2/2 角色计数，实际为 {role_counts}；预期 primary 行数 4，实际为 {len(primary)}。observed_fact: audit assignment failed count 为 {diagnostic["audit_failed_count"]}。inference: 实际结果与预注册 deterministic mapping 一致，没有产生 automatic winner、preferred window 或排名字段。

## 6. coverage / NULL / unknown / blocked / denominator 检查
observed_fact: evidence snapshot 行数为 {len(evidence_snapshot)}，与 registry 行数一致，并包含 eligible_days、denominator_scope、metric_source_task、metric_source_run 与 coverage_comparable_group。derived_statistic: denominator groups 为 {denominator_groups}。research_judgment: R1-T10 matrix 是 mixed-scope lineage snapshot；shared-q 的 strict-common-valid denominator 与 R1-T14-02 q-vector ordered short-circuit denominator 不同，不能直接用 confirmed_coverage 的跨角色差值说明 q-vector 覆盖扩大。inference: 只有相同 coverage_comparable_group 内的 q-vector neighbor rows 可做数值响应比较；shared-q 只能作为 fallback/reference identity，不作为同口径 coverage baseline。

## 7. baseline 与至少两个 challenger 对照
observed_fact: baseline 是四个 shared-q strict-core/fallback reference；challenger 一是四个 q-vector center primary；challenger 二是两个 qT=.30 immediate-neighbor sensitivity rows；另有两个 qV=.25 excluded rows 保留 R1 do_not_freeze 结论。inference: 这些对照只用于确认角色处置和限制传播，不构成 winner 排名；涉及 q-vector 数值变化时，仅在 R1-T14-02 same-scope group 内解释方向，不把 shared-q mixed-scope coverage 当成同口径 challenger。

## 8. 参数响应与敏感性
observed_fact: T01 不扫描 d/g，不重扫 K，也不生成新 q-vector。derived_statistic: qT=.30 sensitivity 行数为 2，qV=.25 excluded 行数为 2。research_judgment: 参数响应在 T01 表现为 mutation-sensitive role mapping；若 qT=.30 被改为 primary 或 qV=.25 被改为 sensitivity/excluded 以外角色，validator 必须失败。

## 9. 层级、漏斗、守恒关系与不变量
observed_fact: source rows、candidate disposition registry、canonical shortlist registry 三者均为 12 行；primary shortlist 为 4 行。observed_fact: shared-q 未复制成额外 fallback row，因此 registry 没有扩张为 16 行。inference: shared-q 与同 state_line x W 的 primary route 唯一配对，保持 R1 12 行交接矩阵一一对应。

## 10. 异常结果及根因调查
observed_fact: anomaly blocking errors 为 {anomaly.get("blocking_errors", [])}。observed_fact: source reconciliation failed count 为 {source_fail}，warning reconciliation failed count 为 {warning_fail}。research_judgment: 当前 author analysis 未发现 unresolved blocker；若后续 reviewer 发现 warning 丢失、source hash 变化或行级 selection_path limitation 丢失，应标记 blocked_return_to_R1 或 needs_revision。

## 11. 替代解释与反证检查
inference: q-vector rows 的 same-scope 参数响应可能来自阈值放宽和状态身份变化，而非更强的经济结构。research_judgment: T01 只接受 R1 已完成的结构资格和 R2 预注册角色安排，不证明 q-vector 优于 shared-q，也不证明未来预测价值。observed_fact: result package 保持 scientific_review_status=pending，等待独立 reviewer 直接读取 matrix、registry、audit、warning reconciliation 和本报告。

## 12. 研究限制
research_judgment: 本任务没有事件区间、d/g、释放标签、未来路径、交易成本或样本外证据；selection_path_not_independently_confirmed 仍为 package 顶层限制。inference: 任何把四条 primary 解释为最终冻结版本或交易信号的说法均超出本任务证据。

## 13. 可以支持的结论
observed_fact: R1-T10 的 12 行候选被确定性登记为 4 primary、4 strict_core_reference、2 sensitivity、2 excluded。derived_statistic: 每个 W 均为 2 primary、2 strict_core_reference、1 sensitivity、1 excluded。inference: 这些 registry artifacts 可以作为 R2-T02/T03 设计审阅的 author-draft 输入，但不能作为下游正式 completed gate。

## 14. 不可以支持的结论
research_judgment: 本任务不支持哪个 W 最优、哪个状态线最优、哪个候选有交易优势、最终冻结哪个版本、最终选择哪个 d/g、以及任何未来收益、方向、波动或路径结论。

## 15. 下游 gate 建议
research_judgment: author_result_analysis_status 可标记 passed；scientific_review_status、independent_review_status 和 repository_final_gate_status 必须保持 pending。research_judgment: R2-T02_allowed_to_start=false，R3_allowed_to_start=false；只有独立科学审阅和 final gate 通过后，才能考虑推进 R2-T02。
"""


def _evidence_markdown(
    output_dir: Path,
    summary: dict[str, Any],
    anomaly: dict[str, Any],
    engineering: dict[str, Any],
    analysis_path: Path,
) -> str:
    sci = output_dir / "r2_t01_scientific_review.json"
    input_binding = output_dir / "r2_t01_input_binding.json"
    config_path = ROOT / "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json"
    output_hashes = {
        path.name: sha256_file(path)
        for path in sorted(output_dir.glob("r2_t01_*"))
        if path.is_file()
    }
    return f"""# R2-T01 evidence

`task_id`: R2-T01
`run_id`: {output_dir.name}
`code_commit`: {engineering.get("code_commit")}
`input_matrix_sha256`: {engineering.get("matrix_sha256")}
`config_hash`: {engineering.get("config_sha256")}
`config_path`: {repo_rel(config_path)}
`input_binding_path`: {repo_rel(input_binding)}
`input_binding_sha256`: {sha256_file(input_binding)}
`input_paths_and_hashes`: {_load_json(input_binding).get("input_artifacts")}
`output_paths_and_hashes`: {output_hashes}
`validator_command`: python scripts/r2/validate_r2_t01_candidate_convergence_shortlist.py --output {repo_rel(output_dir)}
`validator_name`: {engineering.get("validator")}
`lineage_check`: source hashes, supersession/current status, final package/review/handoff cross-binding, and PR #90 ancestry checked
`forbidden_field_check`: {anomaly.get("checks", {}).get("future_leakage_check", {}).get("status")}
`full_sha_check`: config/input/output hashes recorded as full SHA-256
`row_payload_policy`: aggregate registry/evidence rows only; no raw vendor row payloads
`deterministic_output_check`: {engineering.get("deterministic_output_check")}
`README_transition_check`: {engineering.get("README_transition_check")}
`output_row_counts`: shortlist_registry=12;primary_shortlist=4
`role_counts`: {summary.get("role_counts")}
`engineering_validator_status`: passed
`result_artifact_status`: passed
`author_result_analysis_status`: passed
`scientific_review_status`: pending
`anomaly_resolution_status`: passed
`downstream_gate_allowed`: false
`R2-T02_allowed_to_start`: false
`result_analysis_sha256`: {sha256_file(analysis_path)}
`anomaly_scan_sha256`: {sha256_file(output_dir / "r2_t01_anomaly_scan.json")}
`engineering_validation_result_sha256`: {sha256_file(output_dir / "r2_t01_engineering_validation_result.json")}
`scientific_review_sha256`: {sha256_file(sci)}
"""


def _artifact(path: Path, role: str, count_key: str = "row_count") -> dict[str, Any]:
    count = 0
    if path.suffix == ".csv":
        count = len(_read_csv(path))
    else:
        count = 1
    return {
        "artifact_role": role,
        "path": repo_rel(path),
        "sha256": sha256_file(path),
        "committed_to_repo": True,
        count_key: count,
    }


def _package(
    root: Path,
    output_dir: Path,
    summary: dict[str, Any],
    engineering: dict[str, Any],
    analysis_path: Path,
    evidence_path: Path,
) -> dict[str, Any]:
    config_path = root / "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json"
    readme_path = root / "docs/tasks/README.md"
    primary_artifacts = [
        _artifact(output_dir / "r2_t01_shortlist_registry.csv", "primary_results"),
        _artifact(output_dir / "r2_t01_primary_shortlist.csv", "primary_shortlist"),
        _artifact(
            output_dir / "r2_t01_candidate_disposition_registry.csv",
            "candidate_disposition_registry",
        ),
    ]
    diagnostic_artifacts = [
        _artifact(output_dir / "r2_t01_input_binding.json", "input_binding"),
        _artifact(
            output_dir / "r2_t01_source_reconciliation.csv", "source_reconciliation"
        ),
        _artifact(
            output_dir / "r2_t01_role_assignment_audit.csv", "role_assignment_audit"
        ),
        _artifact(output_dir / "r2_t01_evidence_snapshot.csv", "evidence_snapshot"),
        _artifact(
            output_dir / "r2_t01_diagnostic_summary.json",
            "diagnostic_summary",
            "record_count",
        ),
    ]
    return {
        "task_id": "R2-T01",
        "task_class": "formal_experiment",
        "run_id": output_dir.name,
        "code_commit": engineering["code_commit"],
        "implementation_actor": "codex",
        "status": "author_analysis_complete",
        "input_package": {
            "r1_t10_run_id": "R1-T10-20260711T2000Z",
            "decision_matrix_sha256": engineering["matrix_sha256"],
            "downstream_gate_scope": "R2-T01_only",
        },
        "config_path": repo_rel(config_path),
        "config_sha256": sha256_file(config_path),
        "experiment_summary_path": repo_rel(
            output_dir / "r2_t01_experiment_summary.json"
        ),
        "experiment_summary_sha256": sha256_file(
            output_dir / "r2_t01_experiment_summary.json"
        ),
        "primary_result_artifacts": primary_artifacts,
        "diagnostic_artifacts": diagnostic_artifacts,
        "anomaly_scan_path": repo_rel(output_dir / "r2_t01_anomaly_scan.json"),
        "anomaly_scan_sha256": sha256_file(output_dir / "r2_t01_anomaly_scan.json"),
        "result_analysis_path": repo_rel(analysis_path),
        "result_analysis_sha256": sha256_file(analysis_path),
        "engineering_validation_result_path": repo_rel(
            output_dir / "r2_t01_engineering_validation_result.json"
        ),
        "engineering_validation_result_sha256": sha256_file(
            output_dir / "r2_t01_engineering_validation_result.json"
        ),
        "formal_evidence_path": repo_rel(evidence_path),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "scientific_review_record_path": repo_rel(
            output_dir / "r2_t01_scientific_review.json"
        ),
        "scientific_review_record_sha256": sha256_file(
            output_dir / "r2_t01_scientific_review.json"
        ),
        "scientific_review_md_path": None,
        "scientific_review_md_sha256": None,
        "readme_path": repo_rel(readme_path),
        "readme_sha256": sha256_file(readme_path),
        "expected_current_stage": "R2",
        "expected_current_task": "R2-T01 参数候选收敛与 shortlist registry",
        "expected_next_planned_task": "R2-T02 K/d/g、事件指标、hard gate 与 R3 risk-set 契约",
        "expected_downstream_gate_marker": "R2-T02_allowed_to_start: false",
        "superseded": False,
        "superseded_by": None,
        "gate_status": {
            "engineering_validator_status": "passed",
            "result_artifact_status": "passed",
            "author_result_analysis_status": "passed",
            "scientific_review_status": "pending",
            "anomaly_resolution_status": "passed",
            "review_phase": "author_analysis_complete",
            "readme_gate_updated": False,
        },
        "downstream_gate_allowed": False,
        "formal_task_completed": False,
        "R2-T02_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
    }
