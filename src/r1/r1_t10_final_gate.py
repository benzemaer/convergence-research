from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "R1-T10"
RUN_ID = "R1-T10-20260711T2000Z"
REVIEWED_HEAD = "b2b10e188b73dc9e8740d14b0e7d34563a90ac46"
REVIEW_COMMENT_ID = 4946072671
REVIEW_SOURCE = (
    "https://github.com/benzemaer/convergence-research/pull/90#issuecomment-4946072671"
)
AUTHOR_PACKAGE_SHA256 = (
    "7140f452eecb1969ba415e3628ca3ed6d1d10aff7fd79e87e5448933c9aa710b"
)
REVIEWED_ARTIFACTS = {
    "r1_t10_anomaly_scan.json": (
        "0680d2034fbe0703f801e348940f20dfe79bfc463ea6d4fcd3237a6ae7a41670"
    ),
    "r1_t10_engineering_validation_result.json": (
        "4b97041bf643272a90f6425441b13658f8071ba627932f90f7debc28f92c3749"
    ),
    "r1_t10_evidence.md": (
        "2acf738ea03a90b49c27688c3073491aecf2003fff0970c0b2becf2e107b81b7"
    ),
    "r1_t10_r2_decision_matrix.csv": (
        "c3dddd698a0876743e822a55864be06074f94c14a4cd142b44de062a35d83134"
    ),
    "r1_t10_result_analysis.md": (
        "5a4b5aba829cf1469acd0059402102a1c59d0f447b8a2d12fde68c71e424e07d"
    ),
}


class R1T10FinalGateError(RuntimeError):
    pass


def finalize_r1_t10(
    *,
    run_dir: Path,
    review_record_path: Path,
    review_markdown_path: Path,
    final_evidence_path: Path,
    task_index_path: Path,
) -> dict[str, Any]:
    author_package_path = _write_reviewed_author_package_snapshot(run_dir)
    _require_hash(author_package_path, AUTHOR_PACKAGE_SHA256, "author_package")
    author_package = _load_json(author_package_path)
    review = _load_json(review_record_path)
    _validate_review(review, author_package)
    _validate_reviewed_artifacts(run_dir, author_package)
    _validate_repository_lineage()
    _validate_final_documents(final_evidence_path, task_index_path)

    package = {
        "task_id": TASK_ID,
        "run_id": RUN_ID,
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
        "R2_allowed_to_start": True,
        "selection_path_not_independently_confirmed": True,
        "downstream_gate_scope": "R2-T01_only",
        "blocking_findings": [],
    }
    output = run_dir / "r1_t10_final_gate_package.json"
    write_json_atomic(output, package)
    _write_completed_result_package(
        run_dir=run_dir,
        author_package=author_package,
        final_gate_package=package,
    )
    return package


def validate_r1_t10_final_gate(*, run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    package_path = run_dir / "r1_t10_final_gate_package.json"
    package = _load_optional(package_path)
    expected = {
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "status": "completed",
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "review_comment_id": REVIEW_COMMENT_ID,
        "review_source": REVIEW_SOURCE,
        "reviewed_pr_head_commit": REVIEWED_HEAD,
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2_allowed_to_start": True,
        "selection_path_not_independently_confirmed": True,
        "downstream_gate_scope": "R2-T01_only",
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
        _validate_completed_result_package(run_dir, package)
    except (R1T10FinalGateError, FileNotFoundError, KeyError, TypeError) as exc:
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
        "R2_allowed_to_start": not errors,
        "selection_path_not_independently_confirmed": True,
    }
    write_json_atomic(run_dir / "r1_t10_final_gate_validation_result.json", result)
    if errors:
        raise R1T10FinalGateError(json.dumps(result, ensure_ascii=False))
    return result


def _write_completed_result_package(
    *,
    run_dir: Path,
    author_package: dict[str, Any],
    final_gate_package: dict[str, Any],
) -> None:
    package = dict(author_package)
    package.update(
        {
            "status": "completed",
            "review_phase": "independent_review_complete",
            "scientific_review_status": "passed",
            "independent_review_status": "passed",
            "repository_final_gate_status": "passed",
            "formal_task_completed": True,
            "downstream_gate_allowed": True,
            "R2_allowed_to_start": True,
            "blocking_findings": [],
            "unresolved_findings": [],
            "review_comment_id": REVIEW_COMMENT_ID,
            "review_source": REVIEW_SOURCE,
            "reviewed_pr_head_commit": REVIEWED_HEAD,
            "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
            "final_gate_package_path": _rel(run_dir / "r1_t10_final_gate_package.json"),
            "final_gate_package_sha256": sha256_file(
                run_dir / "r1_t10_final_gate_package.json"
            ),
        }
    )
    package["task_index_sha256"] = sha256_file(ROOT / "docs/tasks/README.md")
    write_json_atomic(run_dir / "r1_t10_result_package.json", package)


def _validate_completed_result_package(
    run_dir: Path, final_gate_package: dict[str, Any]
) -> None:
    package = _load_json(run_dir / "r1_t10_result_package.json")
    expected = {
        "status": "completed",
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "downstream_gate_allowed": True,
        "R2_allowed_to_start": True,
        "selection_path_not_independently_confirmed": True,
        "final_gate_package_sha256": sha256_file(
            run_dir / "r1_t10_final_gate_package.json"
        ),
    }
    for key, value in expected.items():
        if package.get(key) != value:
            raise R1T10FinalGateError(f"completed_result_package_field:{key}")
    if package.get("review_comment_id") != final_gate_package["review_comment_id"]:
        raise R1T10FinalGateError("completed_result_package_review_binding")


def _write_reviewed_author_package_snapshot(run_dir: Path) -> Path:
    path = run_dir / "r1_t10_reviewed_author_package.json"
    rel = f"data/generated/r1/r1_t10/{RUN_ID}/r1_t10_result_package.json"
    content = subprocess.run(
        ["git", "show", f"{REVIEWED_HEAD}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    path.write_bytes(content)
    return path


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
        "reviewed_run_id": RUN_ID,
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "reviewed_result_package_sha256": AUTHOR_PACKAGE_SHA256,
        "reviewed_matrix_sha256": REVIEWED_ARTIFACTS["r1_t10_r2_decision_matrix.csv"],
        "reviewed_analysis_sha256": REVIEWED_ARTIFACTS["r1_t10_result_analysis.md"],
        "reviewed_evidence_sha256": REVIEWED_ARTIFACTS["r1_t10_evidence.md"],
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "selection_path_not_independently_confirmed": True,
        "blocking_findings": [],
        "downstream_gate_recommendation": True,
        "downstream_gate_scope": "R2-T01_only",
    }
    for key, value in expected.items():
        if review.get(key) != value:
            raise R1T10FinalGateError(f"scientific_review_binding:{key}")
    if author_package.get("status") != "author_draft_complete":
        raise R1T10FinalGateError("reviewed_author_package_status_invalid")
    if review["reviewer_identity"] == review["implementation_actor"]:
        raise R1T10FinalGateError("scientific_review_not_independent")
    if not review.get("independent_recomputations") or not review.get(
        "alternative_explanations"
    ):
        raise R1T10FinalGateError("scientific_review_analysis_missing")


def _validate_reviewed_artifacts(run_dir: Path, author_package: dict[str, Any]) -> None:
    for name, expected_hash in REVIEWED_ARTIFACTS.items():
        _require_hash(run_dir / name, expected_hash, name)
    for rel, meta in author_package.get("committed_artifacts", {}).items():
        if rel.endswith("r1_t10_result_package.json"):
            continue
        _require_hash(ROOT / rel, str(meta.get("sha256", "")), rel)


def _validate_repository_lineage() -> None:
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", REVIEWED_HEAD, "HEAD"],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        raise R1T10FinalGateError("reviewed_head_not_ancestor")
    protected = [
        "src/r1/r1_t10_precedence_validator.py",
        "src/r1/r1_t10_r1_gate_r2_decision_matrix.py",
        "src/r1/r1_t10_r1_gate_r2_decision_matrix_validator.py",
        "data/generated/r1/r1_t10/R1-T10-20260711T2000Z/r1_t10_r2_decision_matrix.csv",
        "data/generated/r1/r1_t10/R1-T10-20260711T2000Z/r1_t10_result_analysis.md",
        "data/generated/r1/r1_t10/R1-T10-20260711T2000Z/r1_t10_evidence.md",
    ]
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{REVIEWED_HEAD}..HEAD", "--", *protected],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if changed:
        raise R1T10FinalGateError(f"reviewed_scientific_files_changed:{changed}")


def _validate_final_documents(final_evidence: Path, task_index: Path) -> None:
    evidence = final_evidence.read_text(encoding="utf-8")
    index = task_index.read_text(encoding="utf-8")
    for marker in (
        "scientific_review_status=passed",
        "independent_review_status=passed",
        "repository_final_gate_status=passed",
        "formal_task_completed=true",
        "R2_allowed_to_start=true",
        "selection_path_not_independently_confirmed=true",
        "downstream_gate_scope=R2-T01_only",
    ):
        if marker not in evidence:
            raise R1T10FinalGateError(f"final_evidence_marker_missing:{marker}")
    current = index.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
    for marker in (
        "current_stage: R1",
        "current_task: R1-T10 R1 验收门禁与 R2 交接矩阵",
        "next_planned_task: R2-T01 参数候选收敛",
        "R1-T10_status: completed",
        "R1-T10_scientific_review_status: passed",
        "R1-T10_independent_review_status: passed",
        "R2_allowed_to_start: true",
    ):
        if marker not in current:
            raise R1T10FinalGateError(f"task_index_marker_missing:{marker}")


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha256_file(path) != expected:
        raise R1T10FinalGateError(f"hash_mismatch:{label}")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _load_optional(path: Path) -> dict[str, Any]:
    return _load_json(path) if path.is_file() else {}


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()
