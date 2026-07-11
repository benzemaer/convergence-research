# ruff: noqa: E501

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "R1-T14-02"
REVIEWED_HEAD = "c6bd78ce7f97271de83739d8196097116463a23a"
REVIEW_COMMENT_ID = 4945024905
REVIEW_SOURCE = (
    "https://github.com/benzemaer/convergence-research/pull/89#issuecomment-4945024905"
)
AUTHOR_PACKAGE_SHA256 = (
    "cb5c6c454f7023059ea237c32d574aca13e5b82343ba6ee36e6839711a13eb25"
)
REVIEWED_ARTIFACTS = {
    "r1_t14_02_candidate_registry.csv": "d5bd0d247b2c31e3dfe561a218fbc4a9f989edfa7b7b49aab07360b5201dcf5a",
    "r1_t14_02_candidate_decision_matrix.csv": "a7a65b23582f820d7a7e959db97cb441a668aa917abbd3f880716d18c1a9a466",
    "r1_t14_02_existence_profile.csv": "762e533f950d6e26ba4bdfd526c232d5694e221a9496bf4ff3351abd80efb2ed",
    "r1_t14_02_null_results.csv": "88758396d80c82f94c2e0dda40bb1705559f53ca945f307ed8e5e26ca7e964c8",
    "r1_t14_02_family_max_statistic.csv": "16a3a6782cc6b8f3f2646127f73e67a633525b5c755f573992c630d49895419c",
    "r1_t14_02_multiplicity_results.csv": "3ac955d1ac0dd2778c97fba8ba5978f372639f4f9e8929c0ad282cdf339fe179",
    "r1_t14_02_result_analysis.md": "ffc117e6b0184c78f726ed63759ad0ffca5702712e212d34d0846be3f6ea51ac",
}


class R1T1402FinalGateError(RuntimeError):
    pass


def finalize_r1_t14_02(
    *,
    run_dir: Path,
    review_record_path: Path,
    review_markdown_path: Path,
    final_evidence_path: Path,
    task_index_path: Path,
) -> dict[str, Any]:
    author_package_path = run_dir / "r1_t14_02_result_package.json"
    _require_hash(author_package_path, AUTHOR_PACKAGE_SHA256, "author_package")
    author_package = _load_json(author_package_path)
    review = _load_json(review_record_path)
    _validate_review(review, author_package)
    _validate_reviewed_artifacts(run_dir, author_package)
    _validate_repository_lineage()
    _validate_final_documents(final_evidence_path, task_index_path)

    package = {
        "task_id": TASK_ID,
        "run_id": author_package["run_id"],
        "status": "completed",
        "reviewed_author_package_path": _rel(author_package_path),
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "scientific_review_record_path": _rel(review_record_path),
        "scientific_review_record_sha256": sha256_file(review_record_path),
        "scientific_review_markdown_path": _rel(review_markdown_path),
        "scientific_review_markdown_sha256": sha256_file(review_markdown_path),
        "review_comment_id": REVIEW_COMMENT_ID,
        "review_source": REVIEW_SOURCE,
        "reviewed_pr_head_commit": REVIEWED_HEAD,
        "final_evidence_path": _rel(final_evidence_path),
        "final_evidence_sha256": sha256_file(final_evidence_path),
        "task_index_path": _rel(task_index_path),
        "task_index_sha256": sha256_file(task_index_path),
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R1-T10_allowed_to_start": True,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "downstream_gate_scope": "R1-T10_only",
        "blocking_findings": [],
    }
    output = run_dir / "r1_t14_02_final_gate_package.json"
    write_json_atomic(output, package)
    return package


def validate_r1_t14_02_final_gate(*, run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    package_path = run_dir / "r1_t14_02_final_gate_package.json"
    package = _load_optional(package_path)
    expected = {
        "task_id": TASK_ID,
        "run_id": "R1-T14-02-20260711T1100Z",
        "status": "completed",
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "review_comment_id": REVIEW_COMMENT_ID,
        "review_source": REVIEW_SOURCE,
        "reviewed_pr_head_commit": REVIEWED_HEAD,
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R1-T10_allowed_to_start": True,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "downstream_gate_scope": "R1-T10_only",
        "blocking_findings": [],
    }
    for key, value in expected.items():
        if package.get(key) != value:
            errors.append(f"final_gate_field_mismatch:{key}")
    for prefix in (
        "reviewed_author_package",
        "scientific_review_record",
        "scientific_review_markdown",
        "final_evidence",
        "task_index",
    ):
        path_value = package.get(f"{prefix}_path")
        hash_value = package.get(f"{prefix}_sha256")
        path = ROOT / str(path_value or "")
        if not path_value or not path.is_file() or sha256_file(path) != hash_value:
            if prefix != "task_index" or not _t10_author_draft_binds_current_index():
                errors.append(f"final_gate_hash_mismatch:{prefix}")
    try:
        author_package = _load_json(
            ROOT / str(package.get("reviewed_author_package_path", ""))
        )
        review = _load_json(
            ROOT / str(package.get("scientific_review_record_path", ""))
        )
        _validate_review(review, author_package)
        _validate_reviewed_artifacts(run_dir, author_package)
        _validate_repository_lineage()
        _validate_final_documents(
            ROOT / str(package.get("final_evidence_path", "")),
            ROOT / str(package.get("task_index_path", "")),
        )
    except (R1T1402FinalGateError, FileNotFoundError, KeyError, TypeError) as exc:
        errors.append(f"final_gate_cross_validation:{exc}")
    result = {
        "task_id": TASK_ID,
        "validation_mode": "repository_final_gate",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "final_gate_package_path": _rel(package_path),
        "final_gate_package_sha256": (
            sha256_file(package_path) if package_path.is_file() else None
        ),
        "formal_task_completed": not errors,
        "R1-T10_allowed_to_start": not errors,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
    }
    write_json_atomic(run_dir / "r1_t14_02_final_gate_validation_result.json", result)
    if errors:
        raise R1T1402FinalGateError(json.dumps(result, ensure_ascii=False))
    return result


def _t10_author_draft_binds_current_index() -> bool:
    package_path = (
        ROOT
        / "data/generated/r1/r1_t10/R1-T10-20260711T2000Z/r1_t10_result_package.json"
    )
    if not package_path.is_file():
        return False
    package = _load_json(package_path)
    index_path = ROOT / str(package.get("task_index_path", ""))
    return (
        package.get("task_id") == "R1-T10"
        and package.get("status") == "author_draft_complete"
        and package.get("scientific_review_status") == "pending"
        and package.get("R2_allowed_to_start") is False
        and index_path == ROOT / "docs/tasks/README.md"
        and index_path.is_file()
        and sha256_file(index_path) == package.get("task_index_sha256")
    )


def _validate_review(review: dict[str, Any], author_package: dict[str, Any]) -> None:
    expected = {
        "task_id": TASK_ID,
        "reviewer_identity": "benzemaer",
        "reviewer_role": "independent_scientific_reviewer",
        "implementation_actor": "codex",
        "independence_attestation": True,
        "review_comment_id": REVIEW_COMMENT_ID,
        "review_source": REVIEW_SOURCE,
        "reviewed_pr_head_commit": REVIEWED_HEAD,
        "reviewed_run_id": author_package.get("run_id"),
        "reviewed_execution_commit": author_package.get("code_commit"),
        "reviewed_result_package_sha256": AUTHOR_PACKAGE_SHA256,
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "reviewed_config_sha256": author_package.get("config_sha256"),
        "reviewed_analysis_sha256": author_package.get("result_analysis_sha256"),
        "scientific_review_status": "passed",
        "selection_path_not_independently_confirmed": True,
        "blocking_findings": [],
        "downstream_gate_recommendation": True,
        "downstream_gate_scope": "R1-T10_only",
    }
    for key, value in expected.items():
        if review.get(key) != value:
            raise R1T1402FinalGateError(f"scientific_review_binding:{key}")
    if review["reviewer_identity"] == review["implementation_actor"]:
        raise R1T1402FinalGateError("scientific_review_not_independent")
    if not review.get("independent_recomputations") or not review.get(
        "alternative_explanations"
    ):
        raise R1T1402FinalGateError("scientific_review_analysis_missing")


def _validate_reviewed_artifacts(run_dir: Path, author_package: dict[str, Any]) -> None:
    for name, expected_hash in REVIEWED_ARTIFACTS.items():
        _require_hash(run_dir / name, expected_hash, name)
    for artifact in author_package.get("committed_artifacts", []):
        path = ROOT / str(artifact.get("path", ""))
        _require_hash(path, str(artifact.get("sha256", "")), str(path))


def _validate_repository_lineage() -> None:
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", REVIEWED_HEAD, "HEAD"],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        raise R1T1402FinalGateError("reviewed_head_not_ancestor")
    protected = [
        "src/r1/r1_t14_02_formal_structural_revalidation.py",
        "src/r1/r1_t14_02_formal_structural_revalidation_validator.py",
        "configs/r1/r1_t14_02_formal_structural_revalidation.v3.json",
        "docs/experiments/r1/R1-T14-02_层级q向量正式结构复验_result_analysis.md",
    ]
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{REVIEWED_HEAD}..HEAD", "--", *protected],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if changed:
        raise R1T1402FinalGateError(f"reviewed_scientific_files_changed:{changed}")


def _validate_final_documents(final_evidence: Path, task_index: Path) -> None:
    evidence = final_evidence.read_text(encoding="utf-8")
    index = task_index.read_text(encoding="utf-8")
    for marker in (
        "scientific_review_status=passed",
        "independent_review_status=passed",
        "repository_final_gate_status=passed",
        "formal_task_completed=true",
        "R1-T10_allowed_to_start=true",
        "R2_allowed_to_start=false",
        "selection_path_not_independently_confirmed=true",
    ):
        if marker not in evidence:
            raise R1T1402FinalGateError(f"final_evidence_marker_missing:{marker}")
    current = index.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
    for marker in (
        "current_task: R1-T10 R1 验收门禁与 R2 交接矩阵",
        "R1-T14-02_status: completed",
        "R1-T14-02_scientific_review_status: passed",
        "R1-T14-02_independent_review_status: passed",
        "R1-T14-02_allowed_to_start: false",
        "R1-T10_allowed_to_start: true",
        "R2_allowed_to_start: false",
    ):
        if marker not in current:
            raise R1T1402FinalGateError(f"task_index_marker_missing:{marker}")


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha256_file(path) != expected:
        raise R1T1402FinalGateError(f"hash_mismatch:{label}")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _load_optional(path: Path) -> dict[str, Any]:
    return _load_json(path) if path.is_file() else {}


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()
