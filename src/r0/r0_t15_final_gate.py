from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r0_t15_layer_q_vector_materializer import ROOT

REVIEWED_HEAD = "3210c35a6a5a5679792bfd455969e78664fc5e13"
REVIEW_COMMENT_ID = 4943245857
REVIEW_SOURCE = (
    "https://github.com/benzemaer/convergence-research/pull/88#issuecomment-4943245857"
)
REVIEWED_PACKAGE_SHA256 = (
    "078cb456c21ef995bcb8e052191ef948d5ea5129e82f7549eef5ed4b3ab917b0"
)
REVIEWED_ANALYSIS_SHA256 = (
    "13d6bcd192ef05ecd227278f9e51452ddcedd91469c05badfd983af8ee8aef1f"
)
REVIEWED_EVIDENCE_SHA256 = (
    "3b6848a197c4a7e36909f1badebdeeea87fdfba9fe84c3aa4026363532801c84"
)


class R0T15FinalGateError(RuntimeError):
    pass


def finalize_r0_t15_reviewed_package(
    *,
    run_dir: str | Path,
    review_record_path: str | Path,
    review_markdown_path: str | Path,
    analysis_path: str | Path,
    evidence_path: str | Path,
    readme_path: str | Path,
) -> dict[str, Any]:
    """Bind the external REV1 PASS while keeping every downstream gate closed.

    The reviewed handoff is immutable.  The reviewed REV1 package and documents are
    archived byte-for-byte before the current package/documents become the
    repository-final-gate candidate.  Merge authorization is deliberately outside
    this function because the merge commit does not exist yet.
    """
    run_dir = Path(run_dir)
    review_record_path = Path(review_record_path)
    review_markdown_path = Path(review_markdown_path)
    analysis_path = Path(analysis_path)
    evidence_path = Path(evidence_path)
    readme_path = Path(readme_path)
    package_path = run_dir / "r0_t15_result_package.json"
    handoff_path = run_dir / "r0_t15_authorized_handoff_manifest.json"
    revision_path = run_dir / "r0_t15_author_revision.json"
    attestation_path = run_dir / "r0_t15_local_duckdb_attestation.json"
    revision_validation_path = (
        run_dir / "r0_t15_author_revision_package_validation_result.json"
    )
    reviewed_package_archive = run_dir / "r0_t15_result_package.reviewed_rev1.json"
    reviewed_analysis_archive = run_dir / "r0_t15_result_analysis.reviewed_rev1.md"
    reviewed_evidence_archive = run_dir / "r0_t15_evidence.reviewed_rev1.md"
    run_analysis_path = run_dir / "r0_t15_result_analysis.md"
    run_evidence_path = run_dir / "r0_t15_evidence.md"

    required_files = (
        package_path,
        handoff_path,
        revision_path,
        attestation_path,
        revision_validation_path,
        review_record_path,
        review_markdown_path,
        analysis_path,
        evidence_path,
        readme_path,
    )
    missing = [str(path) for path in required_files if not path.is_file()]
    if missing:
        raise R0T15FinalGateError(f"final_gate_input_missing:{missing}")
    if sha256_file(package_path) != REVIEWED_PACKAGE_SHA256:
        raise R0T15FinalGateError("reviewed_rev1_package_hash_mismatch")
    if sha256_file(analysis_path) != REVIEWED_ANALYSIS_SHA256:
        raise R0T15FinalGateError("reviewed_rev1_analysis_hash_mismatch")
    if sha256_file(evidence_path) != REVIEWED_EVIDENCE_SHA256:
        raise R0T15FinalGateError("reviewed_rev1_evidence_hash_mismatch")

    package = _load_json(package_path)
    review = _load_json(review_record_path)
    expected_review = {
        "task_id": "R0-T15",
        "revision_id": "R0-T15-REV1",
        "external_review_status": "passed",
        "independent_review_status": "passed",
        "reviewer_identity": "benzemaer",
        "reviewer_role": "independent_materialization_reviewer",
        "implementation_actor": "codex",
        "independence_attestation": True,
        "review_comment_id": REVIEW_COMMENT_ID,
        "review_source": REVIEW_SOURCE,
        "reviewed_pr_head_commit": REVIEWED_HEAD,
        "reviewed_result_package_sha256": REVIEWED_PACKAGE_SHA256,
        "reviewed_handoff_sha256": (
            "438d2f09ee7a853547a037521ba4ca133bd18bf1fa5dfef91f97db5f670393c3"
        ),
        "reviewed_artifact_manifest_sha256": (
            "664b6d4558978806db80912aa5e544e0c81824b188a5ea71fece8e20507a8c51"
        ),
        "reviewed_candidate_registry_sha256": (
            "02fdaf1b94780ef42115a9109ae9f1fd6b90a6e019925a5067ad1bac96d4944f"
        ),
        "external_direct_duckdb_byte_review_performed": False,
        "independent_byte_validation_status": "not_performed",
        "blocking_findings": [],
        "downstream_gate_recommendation": True,
        "downstream_gate_scope": "R0-T15_repository_final_gate_only",
    }
    for key, expected in expected_review.items():
        if review.get(key) != expected:
            raise R0T15FinalGateError(f"external_review_binding_mismatch:{key}")
    if review.get("closed_prior_blockers") != [
        "stale_handoff_artifact_manifest_hash",
        "stale_handoff_candidate_registry_hash",
    ]:
        raise R0T15FinalGateError("external_review_closed_blockers_invalid")
    if review.get("reviewer_identity") == review.get("implementation_actor"):
        raise R0T15FinalGateError("external_review_not_independent")

    for prefix, path in (
        ("reviewed_handoff", handoff_path),
        ("reviewed_author_revision", revision_path),
        ("reviewed_local_duckdb_attestation", attestation_path),
        ("reviewed_author_revision_validation", revision_validation_path),
    ):
        if review.get(f"{prefix}_path") != _rel(path):
            raise R0T15FinalGateError(f"external_review_path_mismatch:{prefix}")
        if review.get(f"{prefix}_sha256") != sha256_file(path):
            raise R0T15FinalGateError(f"external_review_hash_mismatch:{prefix}")

    _archive_exact(package_path, reviewed_package_archive, REVIEWED_PACKAGE_SHA256)
    _archive_exact(analysis_path, reviewed_analysis_archive, REVIEWED_ANALYSIS_SHA256)
    _archive_exact(evidence_path, reviewed_evidence_archive, REVIEWED_EVIDENCE_SHA256)

    analysis = analysis_path.read_text(encoding="utf-8")
    analysis = _replace_once(
        analysis,
        "新的 canonical handoff/package 等待外部重新审阅。当前必须保持",
        (
            "新的 canonical handoff/package 已由外部复审评论 `4943245857` "
            "在 reviewed HEAD `3210c35a6a5a5679792bfd455969e78664fc5e13` 上判定 "
            "PASS。repository final gate 通过但 PR 尚未合并时仍必须保持"
        ),
    )
    analysis = _replace_once(
        analysis,
        (
            "当前不能声称外部 reviewer 已直接验证 1.8GB DuckDB 字节，不能声称 "
            "#88 已通过 repository final gate，也不能启动 R1-T14-02。"
        ),
        (
            "仍不能声称外部 reviewer 已直接验证 1.8GB DuckDB 字节。外部 reviewer "
            "已对 committed REV1 lineage 给出 PASS，repository final gate validator "
            "也已通过；但 #88 merge 尚未发生，因此仍不能启动 R1-T14-02。"
        ),
    )
    analysis = _replace_once(
        analysis,
        (
            "只有外部 reviewer 对 REV1 handoff/package、cross-file validator 与本地字节"
            "审查边界重新给出 PASS 后，才可建立 #88 repository final gate。此前不更新 "
            "README 到 R1-T14-02，不触碰 #89 的 authoritative dependency，也不把旧 #89 "
            "结果作为当前 evidence。"
        ),
        (
            "外部 reviewer 已对 REV1 给出 PASS，repository final gate validator "
            "也已通过。本 final-gate commit 只将 README 标记为 "
            "`final_gate_passed_pending_merge`；"
            "在 #88 合并前不授权 R1-T14-02，不触碰 #89 的 authoritative dependency，"
            "也不把旧 #89 结果作为当前 evidence。"
        ),
    )
    analysis = _final_gate_statuses(analysis)
    analysis += (
        "\n## 8. 外部复审记录与 merge 边界\n\n"
        "外部复审评论 `4943245857` 绑定 reviewed HEAD "
        "`3210c35a6a5a5679792bfd455969e78664fc5e13`、REV1 package "
        "`078cb456...` 与 handoff `438d2f09...`，结论为 PASS，blocking "
        "findings 为空。复审没有直接读取四张 local-only DuckDB，因此 "
        "`external_direct_duckdb_byte_review_performed=false` 与 "
        "`independent_byte_validation_status=not_performed` 继续保留。"
        "被复审的 package、analysis 与 evidence 已按原字节归档；canonical "
        "handoff 不作修改。repository final gate 的作用域仅到 #88 merge candidate，"
        "不会提前打开 R1-T14-02、R1-T10 或 R2。\n"
    )

    evidence = evidence_path.read_text(encoding="utf-8")
    evidence = _replace_once(
        evidence,
        "external_review_comment_id=4941872279",
        (
            "prior_external_review_comment_id=4941872279\n"
            "external_rereview_comment_id=4943245857\n"
            "reviewed_pr_head_commit=3210c35a6a5a5679792bfd455969e78664fc5e13"
        ),
    )
    evidence = _replace_once(
        evidence,
        (
            "REV1 是等待 external rereview 的 author revision，不替代独立审阅、"
            "不完成 #88、"
            "不推进 README 到 R1-T14-02，也不授权 #89 继续使用旧依赖。"
        ),
        (
            "REV1 外部复审已通过，repository final gate 也已通过，但 #88 "
            "merge 尚未发生。因此本提交仍不完成 R0-T15、不推进 README 到 "
            "R1-T14-02，也不授权 #89 继续使用旧依赖。"
        ),
    )
    evidence = _final_gate_statuses(evidence)
    evidence += (
        "\n## 外部复审与 final gate 事实\n\n"
        "```text\n"
        "external_review_status=passed\n"
        "external_rereview_comment_id=4943245857\n"
        "reviewed_result_package_sha256=078cb456c21ef995bcb8e052191ef948d5ea5129e82f7549eef5ed4b3ab917b0\n"
        "reviewed_handoff_sha256=438d2f09ee7a853547a037521ba4ca133bd18bf1fa5dfef91f97db5f670393c3\n"
        "repository_merge_status=pending\n"
        "```\n\n"
        "被复审的 REV1 package、analysis 与 evidence 已按原字节归档。"
        "canonical handoff 未修改；"
        "本 PASS 不包含外部 DuckDB byte-for-byte 复核，也不自动恢复旧 #89。\n"
    )

    analysis_path.write_text(analysis, encoding="utf-8", newline="\n")
    evidence_path.write_text(evidence, encoding="utf-8", newline="\n")
    run_analysis_path.write_text(analysis, encoding="utf-8", newline="\n")
    run_evidence_path.write_text(evidence, encoding="utf-8", newline="\n")

    readme = readme_path.read_text(encoding="utf-8")
    readme = _replace_once(
        readme,
        "R0_q_vector_materialization_status: revision_pending_external_rereview",
        "R0_q_vector_materialization_status: final_gate_passed_pending_merge",
    )
    readme_path.write_text(readme, encoding="utf-8", newline="\n")

    changed_paths = {
        _rel(run_dir / "r0_t15_final_gate_validation_result.json"),
        _rel(run_analysis_path),
        _rel(run_evidence_path),
        _rel(analysis_path),
        _rel(evidence_path),
        _rel(readme_path),
    }
    committed = [
        item
        for item in package.get("committed_artifacts", [])
        if isinstance(item, dict) and item.get("path") not in changed_paths
    ]
    for path in (
        reviewed_package_archive,
        reviewed_analysis_archive,
        reviewed_evidence_archive,
        review_record_path,
        review_markdown_path,
        analysis_path,
        run_analysis_path,
        evidence_path,
        run_evidence_path,
        readme_path,
    ):
        committed.append(_artifact(path))
    paths = [item["path"] for item in committed]
    if len(paths) != len(set(paths)):
        raise R0T15FinalGateError("final_committed_artifact_duplicate")

    package.update(
        {
            "status": "review_passed_final_gate_passed_pending_merge",
            "R0_q_vector_materialization_status": "final_gate_passed_pending_merge",
            "independent_review_status": "passed",
            "repository_final_gate_status": "passed",
            "repository_merge_status": "pending",
            "formal_task_completed": False,
            "R1-T14-02_allowed_to_start": False,
            "R1-T10_allowed_to_start": False,
            "R2_allowed_to_start": False,
            "selection_path_not_independently_confirmed": True,
            "external_direct_duckdb_byte_review_performed": False,
            "implementation_actor": "codex",
            "reviewed_pr_head_commit": REVIEWED_HEAD,
            "external_review_record_path": _rel(review_record_path),
            "external_review_record_sha256": sha256_file(review_record_path),
            "external_review_markdown_path": _rel(review_markdown_path),
            "external_review_markdown_sha256": sha256_file(review_markdown_path),
            "reviewed_author_revision_package_path": _rel(reviewed_package_archive),
            "reviewed_author_revision_package_sha256": sha256_file(
                reviewed_package_archive
            ),
            "reviewed_result_analysis_path": _rel(reviewed_analysis_archive),
            "reviewed_result_analysis_sha256": sha256_file(reviewed_analysis_archive),
            "reviewed_formal_evidence_path": _rel(reviewed_evidence_archive),
            "reviewed_formal_evidence_sha256": sha256_file(reviewed_evidence_archive),
            "result_analysis_sha256": sha256_file(analysis_path),
            "run_copy_result_analysis_sha256": sha256_file(run_analysis_path),
            "formal_evidence_sha256": sha256_file(evidence_path),
            "run_copy_formal_evidence_sha256": sha256_file(run_evidence_path),
            "readme_path": _rel(readme_path),
            "readme_sha256": sha256_file(readme_path),
            "final_gate_validation_path": _rel(
                run_dir / "r0_t15_final_gate_validation_result.json"
            ),
            "final_gate_scope": "R0-T15_merge_candidate_only",
            "committed_artifacts": committed,
            "review_history": [
                {
                    "pr_number": 88,
                    "comment_id": 4941872279,
                    "outcome": "needs_revision",
                    "blocking_findings": [
                        "stale_handoff_artifact_manifest_hash",
                        "stale_handoff_candidate_registry_hash",
                    ],
                },
                {
                    "pr_number": 88,
                    "comment_id": REVIEW_COMMENT_ID,
                    "outcome": "passed",
                    "blocking_findings": [],
                    "reviewed_pr_head_commit": REVIEWED_HEAD,
                },
            ],
        }
    )
    package["gate_status"].update(
        {
            "independent_review_status": "passed",
            "external_review_status": "passed",
            "repository_final_gate_status": "passed",
            "repository_merge_status": "pending",
            "goal_internal_continuation_gate_status": (
                "closed_pending_repository_merge"
            ),
            "goal_internal_continuation_allowed": False,
            "goal_internal_t14_02_authorized": False,
            "repository_t14_02_gate_passed": False,
        }
    )
    write_json_atomic(package_path, package)
    return package


def _final_gate_statuses(text: str) -> str:
    replacements = {
        (
            "R0_q_vector_materialization_status="
            "author_revision_complete_pending_rereview"
        ): ("R0_q_vector_materialization_status=final_gate_passed_pending_merge"),
        "independent_review_status=pending_rereview": (
            "independent_review_status=passed"
        ),
        "repository_final_gate_status=pending": "repository_final_gate_status=passed",
        "goal_internal_continuation_gate_status=closed_pending_external_rereview": (
            "goal_internal_continuation_gate_status=closed_pending_repository_merge"
        ),
    }
    for old, new in replacements.items():
        if old not in text:
            raise R0T15FinalGateError(f"final_document_marker_missing:{old}")
        text = text.replace(old, new)
    return text


def _replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise R0T15FinalGateError(f"final_document_replacement_count:{old[:80]}")
    return text.replace(old, new, 1)


def _archive_exact(source: Path, archive: Path, expected_sha256: str) -> None:
    if archive.exists():
        if sha256_file(archive) != expected_sha256:
            raise R0T15FinalGateError(f"reviewed_archive_hash_mismatch:{archive}")
        return
    archive.write_bytes(source.read_bytes())
    if sha256_file(archive) != expected_sha256:
        raise R0T15FinalGateError(f"reviewed_archive_write_mismatch:{archive}")


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "committed_to_repo": True,
        "path": _rel(path),
        "record_count": 1,
        "sha256": sha256_file(path),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
