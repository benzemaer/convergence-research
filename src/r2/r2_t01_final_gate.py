from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "R2-T01"
RUN_ID = "R2-T01-20260712T0020Z"
REVIEWED_HEAD = "22b2edcfdb728864ade14fed33c8a0f92d53f250"
REVIEW_ID = 4678346540
REVIEW_SOURCE = (
    "https://github.com/benzemaer/convergence-research/pull/91"
    "#pullrequestreview-4678346540"
)
AUTHOR_PACKAGE_SHA256 = (
    "fca9e9288035843bc79e2efe0adc3222c29afc7af35d16224efdb942afae3506"
)
REVIEWED_ARTIFACTS = {
    "r2_t01_shortlist_registry.csv": (
        "9b625cdf06132a8a0488d1b304f41633306287d39f0986208f4ce11f0b042d4d"
    ),
    "r2_t01_primary_shortlist.csv": (
        "cfe9a18cdfef22fa2a5aa7f0658be2784819b95b775de814f08f97d1e95b6144"
    ),
    "r2_t01_candidate_disposition_registry.csv": (
        "6cfff0f33b062a547a81ca8b7c227605b4dbda923ea9aae669262e0023f2de67"
    ),
    "r2_t01_role_assignment_audit.csv": (
        "38c58ea82e42715cc4a901c3b44fce04e3e1dff6ad7e236973a231e0da3555e7"
    ),
    "r2_t01_source_reconciliation.csv": (
        "33999d92619a512ae92535355a53129b0d1a4e434007f7e887fd99fe2f544310"
    ),
    "r2_t01_evidence_snapshot.csv": (
        "8bf2a408de97e49f12ef39403d384370618c05ac79389841c1dfca41cbf54fd9"
    ),
    "r2_t01_result_analysis.md": (
        "2ca49099b759c024f3288a7f38743bb1e597b299ae4ec37842cc4b874d870b26"
    ),
    "r2_t01_evidence.md": (
        "bfb08ad1e00c81f7ebef4dbf4588d2b48f9f95ae0bc76301bb72e34253e31475"
    ),
}


class R2T01FinalGateError(RuntimeError):
    pass


def finalize_r2_t01_reviewed_package(
    *,
    output_dir: Path,
    review_record_path: Path,
    review_markdown_path: Path,
    final_evidence_path: Path,
    task_index_path: Path,
) -> dict[str, Any]:
    author_path = _write_reviewed_snapshot(output_dir)
    _require_hash(author_path, AUTHOR_PACKAGE_SHA256, "author_package")
    author = _load(author_path)
    review = _load(review_record_path)
    _validate_review(review)
    _validate_artifacts(output_dir)
    _validate_lineage()
    _validate_documents(final_evidence_path, task_index_path)
    package = {
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "status": "completed",
        "reviewed_author_package_path": _rel(author_path),
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "scientific_review_record_path": _rel(review_record_path),
        "scientific_review_record_sha256": sha256_file(review_record_path),
        "scientific_review_markdown_path": _rel(review_markdown_path),
        "scientific_review_markdown_sha256": sha256_file(review_markdown_path),
        "review_id": REVIEW_ID,
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
        "downstream_gate_allowed": True,
        "R2-T02_allowed_to_start": True,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "downstream_gate_scope": "R2-T02_only",
        "blocking_findings": [],
    }
    package_path = output_dir / "r2_t01_final_gate_package.json"
    write_json_atomic(package_path, package)
    completed = dict(author)
    completed.update(package)
    completed["review_phase"] = "independent_review_complete"
    completed["gate_status"] = {
        "engineering_validator_status": "passed",
        "result_artifact_status": "passed",
        "author_result_analysis_status": "passed",
        "scientific_review_status": "passed",
        "anomaly_resolution_status": "passed",
        "review_phase": "independent_review_complete",
        "readme_gate_updated": True,
    }
    completed["formal_evidence_path"] = _rel(final_evidence_path)
    completed["formal_evidence_sha256"] = sha256_file(final_evidence_path)
    completed["scientific_review_md_path"] = _rel(review_markdown_path)
    completed["scientific_review_md_sha256"] = sha256_file(review_markdown_path)
    completed["readme_sha256"] = sha256_file(task_index_path)
    completed["expected_downstream_gate_marker"] = "R2-T02_allowed_to_start: true"
    completed["final_gate_package_path"] = _rel(package_path)
    completed["final_gate_package_sha256"] = sha256_file(package_path)
    write_json_atomic(output_dir / "r2_t01_result_package.json", completed)
    return package


def validate_r2_t01_final_gate(*, output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    package_path = output_dir / "r2_t01_final_gate_package.json"
    package = _load(package_path)
    expected = {
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "status": "completed",
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "review_id": REVIEW_ID,
        "reviewed_pr_head_commit": REVIEWED_HEAD,
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2-T02_allowed_to_start": True,
        "R3_allowed_to_start": False,
        "downstream_gate_scope": "R2-T02_only",
        "selection_path_not_independently_confirmed": True,
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
        path = ROOT / str(package.get(f"{prefix}_path", ""))
        if not path.is_file() or sha256_file(path) != package.get(f"{prefix}_sha256"):
            errors.append(f"final_gate_hash_mismatch:{prefix}")
    try:
        _validate_review(_load(ROOT / package["scientific_review_record_path"]))
        _validate_artifacts(output_dir)
        _validate_lineage()
        _validate_documents(
            ROOT / package["final_evidence_path"], ROOT / package["task_index_path"]
        )
        completed = _load(output_dir / "r2_t01_result_package.json")
        for key, value in expected.items():
            if completed.get(key) != value:
                errors.append(f"completed_result_package_field:{key}")
        if completed.get("final_gate_package_sha256") != sha256_file(package_path):
            errors.append("completed_result_package_final_gate_hash")
    except (KeyError, FileNotFoundError, R2T01FinalGateError) as exc:
        errors.append(f"final_gate_cross_validation:{exc}")
    result = {
        "task_id": TASK_ID,
        "validation_mode": "repository_final_gate",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "final_gate_package_path": _rel(package_path),
        "final_gate_package_sha256": sha256_file(package_path),
        "formal_task_completed": not errors,
        "R2-T02_allowed_to_start": not errors,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
    }
    write_json_atomic(output_dir / "r2_t01_final_gate_validation_result.json", result)
    if errors:
        raise R2T01FinalGateError(json.dumps(result, ensure_ascii=False))
    return result


def _write_reviewed_snapshot(output_dir: Path) -> Path:
    path = output_dir / "r2_t01_reviewed_author_package.json"
    rel = f"data/generated/r2/r2_t01/{RUN_ID}/r2_t01_result_package.json"
    content = subprocess.run(
        ["git", "show", f"{REVIEWED_HEAD}:{rel}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    path.write_bytes(content)
    return path


def _validate_review(review: dict[str, Any]) -> None:
    expected = {
        "task_id": TASK_ID,
        "reviewer_identity": "benzemaer",
        "reviewer_role": "independent_scientific_reviewer",
        "implementation_actor": "codex",
        "independence_attestation": True,
        "review_id": REVIEW_ID,
        "review_source": REVIEW_SOURCE,
        "reviewed_pr_head_commit": REVIEWED_HEAD,
        "reviewed_run_id": RUN_ID,
        "reviewed_author_package_sha256": AUTHOR_PACKAGE_SHA256,
        "reviewed_result_package_sha256": AUTHOR_PACKAGE_SHA256,
        "reviewed_code_commit": "c0be8673c0fba95002132913d8b6d87ddf9538f4",
        "reviewed_summary_sha256": (
            "278f3bde230885d3887a8a2e127ff4af706e2c90d3de25942eff61383bc371d9"
        ),
        "reviewed_analysis_sha256": REVIEWED_ARTIFACTS["r2_t01_result_analysis.md"],
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "blocking_findings": [],
        "downstream_gate_recommendation": True,
        "downstream_gate_scope": "R2-T02_only",
        "selection_path_not_independently_confirmed": True,
    }
    for key, value in expected.items():
        if review.get(key) != value:
            raise R2T01FinalGateError(f"scientific_review_binding:{key}")
    if review["reviewer_identity"] == review["implementation_actor"]:
        raise R2T01FinalGateError("scientific_review_not_independent")
    if not review.get("independent_recomputations"):
        raise R2T01FinalGateError("scientific_review_analysis_missing")


def _validate_artifacts(output_dir: Path) -> None:
    for name, expected in REVIEWED_ARTIFACTS.items():
        _require_hash(output_dir / name, expected, name)


def _validate_lineage() -> None:
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", REVIEWED_HEAD, "HEAD"],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        raise R2T01FinalGateError("reviewed_head_not_ancestor")
    protected = [
        "src/r2/r2_t01_candidate_convergence_shortlist.py",
        "src/r2/r2_t01_candidate_convergence_shortlist_validator.py",
        "src/r2/r2_t01_author_package.py",
        "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json",
        "schemas/r2/r2_t01_candidate_convergence_shortlist.schema.json",
        f"data/generated/r2/r2_t01/{RUN_ID}/r2_t01_shortlist_registry.csv",
        f"data/generated/r2/r2_t01/{RUN_ID}/r2_t01_result_analysis.md",
    ]
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{REVIEWED_HEAD}..HEAD", "--", *protected],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if changed:
        raise R2T01FinalGateError(f"reviewed_scientific_files_changed:{changed}")


def _validate_documents(final_evidence: Path, task_index: Path) -> None:
    evidence = final_evidence.read_text(encoding="utf-8")
    index = task_index.read_text(encoding="utf-8")
    for marker in (
        "scientific_review_status=passed",
        "independent_review_status=passed",
        "repository_final_gate_status=passed",
        "formal_task_completed=true",
        "R2-T02_allowed_to_start=true",
        "R3_allowed_to_start=false",
        "selection_path_not_independently_confirmed=true",
    ):
        if marker not in evidence:
            raise R2T01FinalGateError(f"final_evidence_marker_missing:{marker}")
    current = index.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
    for marker in (
        "R2-T01_status: completed",
        "R2-T01_scientific_review_status: passed",
        "R2-T01_independent_review_status: passed",
        "R2-T02_allowed_to_start: true",
        "R3_allowed_to_start: false",
    ):
        if marker not in current:
            raise R2T01FinalGateError(f"task_index_marker_missing:{marker}")


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha256_file(path) != expected:
        raise R2T01FinalGateError(f"hash_mismatch:{label}")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()
