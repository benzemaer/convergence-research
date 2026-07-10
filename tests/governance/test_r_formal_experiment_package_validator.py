from __future__ import annotations

import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from src.governance.r_formal_experiment_package_validator import (
    FormalExperimentPackageValidationError,
    validate_formal_experiment_package,
)

MANDATORY_CHECKS = [
    "primary_output_nonempty",
    "all_zero_check",
    "all_one_check",
    "all_null_check",
    "validity_rate_check",
    "coverage_check",
    "parameter_response_check",
    "baseline_challenger_check",
    "nested_invariant_check",
    "funnel_accounting_check",
    "denominator_integrity_check",
    "sample_size_check",
    "upstream_consistency_check",
    "scale_shift_check",
    "time_alignment_check",
    "future_leakage_check",
    "post_hoc_selection_check",
    "conclusion_support_check",
]

ANALYSIS_HEADINGS = [
    "## 1. 研究目标与预注册问题",
    "## 2. 输入 package、lineage、时间与样本范围",
    "## 3. 参数网格与 reference baseline",
    "## 4. 核心结果",
    "## 5. 预期结果与实际结果对照",
    "## 6. coverage / NULL / unknown / blocked / denominator 检查",
    "## 7. baseline 与至少两个 challenger 对照",
    "## 8. 参数响应与敏感性",
    "## 9. 层级、漏斗、守恒关系与不变量",
    "## 10. 异常结果及根因调查",
    "## 11. 替代解释与反证检查",
    "## 12. 研究限制",
    "## 13. 可以支持的结论",
    "## 14. 不可以支持的结论",
    "## 15. 下游 gate 建议",
]


class FormalExperimentPackageValidatorTest(unittest.TestCase):
    def test_author_draft_valid_package_passes_with_gate_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path = build_fixture(root, final=False)
            result = validate_formal_experiment_package(
                package_path,
                mode="author-draft",
                output_path=root / "out.json",
                root=root,
            )
        self.assertEqual(result["author_package_validator_status"], "passed")
        self.assertFalse(result["formal_task_completed"])
        self.assertFalse(result["downstream_gate_allowed"])

    def test_author_draft_gate_true_fails(self) -> None:
        self.assert_fixture_fails(
            final=False,
            mode="author-draft",
            mutate=lambda package, _root: package.update(
                {"downstream_gate_allowed": True}
            ),
        )

    def test_final_gate_valid_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path = build_fixture(root, final=True)
            result = validate_formal_experiment_package(
                package_path,
                mode="final-gate",
                output_path=root / "out.json",
                root=root,
            )
        self.assertTrue(result["formal_task_completed"])
        self.assertTrue(result["downstream_gate_allowed"])

    def test_review_complete_valid_package_passes_without_authorization(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            package["status"] = "author_analysis_complete"
            package["downstream_gate_allowed"] = False
            package["gate_status"]["readme_gate_updated"] = False
            write_evidence(root / "formal_evidence.md", package)
            package["formal_evidence_sha256"] = sha256_path(root / "formal_evidence.md")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path = build_fixture(root, final=True, mutate=mutate)
            result = validate_formal_experiment_package(
                package_path,
                mode="review-complete",
                output_path=root / "out.json",
                root=root,
            )
        self.assertEqual(result["author_package_validator_status"], "passed")
        self.assertFalse(result["formal_task_completed"])
        self.assertFalse(result["downstream_gate_allowed"])

    def test_pending_review_final_gate_fails(self) -> None:
        self.assert_fixture_fails(
            final=True,
            mode="final-gate",
            mutate=lambda package, _root: package["gate_status"].update(
                {"scientific_review_status": "pending"}
            ),
        )

    def test_needs_revision_or_blocked_review_fails(self) -> None:
        for status in ("needs_revision", "blocked"):
            with self.subTest(status=status):
                self.assert_fixture_fails(
                    final=True,
                    mode="final-gate",
                    mutate=lambda package, _root, status=status: package[
                        "gate_status"
                    ].update({"scientific_review_status": status}),
                )

    def test_unresolved_anomaly_with_gate_true_fails(self) -> None:
        self.assert_fixture_fails(
            final=True,
            mode="final-gate",
            mutate=lambda package, _root: package["gate_status"].update(
                {"anomaly_resolution_status": "unresolved"}
            ),
        )

    def test_all_zero_blocked_anomaly_unexplained_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            scan_path = root / package["anomaly_scan_path"]
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            scan["checks"]["all_zero_check"]["status"] = "blocked"
            scan["blocking_anomalies"] = ["all_zero_check"]
            scan_path.write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
            package["anomaly_scan_sha256"] = sha256_path(scan_path)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_missing_result_analysis_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            (root / package["result_analysis_path"]).unlink()

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_analysis_hash_mismatch_fails(self) -> None:
        self.assert_fixture_fails(
            final=False,
            mode="author-draft",
            mutate=lambda package, _root: package.update(
                {"result_analysis_sha256": "0" * 64}
            ),
        )

    def test_missing_primary_result_artifact_fails(self) -> None:
        self.assert_fixture_fails(
            final=False,
            mode="author-draft",
            mutate=lambda package, _root: package.update(
                {"primary_result_artifacts": []}
            ),
        )

    def test_reviewer_same_as_implementation_actor_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            review_path = root / package["scientific_review_record_path"]
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["reviewer_identity"] = package["implementation_actor"]
            rewrite_review(package, review_path, review)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_independence_attestation_false_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            review_path = root / package["scientific_review_record_path"]
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["independence_attestation"] = False
            rewrite_review(package, review_path, review)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_empty_independent_recomputations_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            review_path = root / package["scientific_review_record_path"]
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["independent_recomputations"] = []
            rewrite_review(package, review_path, review)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_empty_alternative_explanations_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            review_path = root / package["scientific_review_record_path"]
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["alternative_explanations"] = []
            rewrite_review(package, review_path, review)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_superseded_with_gate_true_fails(self) -> None:
        self.assert_fixture_fails(
            final=True,
            mode="final-gate",
            mutate=lambda package, _root: package.update(
                {"superseded": True, "superseded_by": "newer-package"}
            ),
        )

    def test_readme_advanced_in_author_draft_fails(self) -> None:
        self.assert_fixture_fails(
            final=False,
            mode="author-draft",
            mutate=lambda package, _root: package["gate_status"].update(
                {"readme_gate_updated": True}
            ),
        )

    def test_required_heading_missing_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            path = root / package["result_analysis_path"]
            text = path.read_text(encoding="utf-8").replace(ANALYSIS_HEADINGS[3], "")
            path.write_text(text, encoding="utf-8")
            package["result_analysis_sha256"] = sha256_path(path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_anomaly_check_missing_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            scan_path = root / package["anomaly_scan_path"]
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            scan["checks"].pop("parameter_response_check")
            scan_path.write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
            package["anomaly_scan_sha256"] = sha256_path(scan_path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_stale_reviewed_summary_hash_fails(self) -> None:
        self.assert_review_mutation_fails(
            "reviewed_summary_sha256",
            "0" * 64,
        )

    def test_stale_reviewed_analysis_hash_fails(self) -> None:
        self.assert_review_mutation_fails(
            "reviewed_analysis_sha256",
            "0" * 64,
        )

    def test_reviewed_code_commit_mismatch_fails(self) -> None:
        self.assert_review_mutation_fails("reviewed_code_commit", "b" * 40)

    def test_review_implementation_actor_mismatch_fails(self) -> None:
        self.assert_review_mutation_fails("implementation_actor", "someone-else")

    def test_failed_engineering_validation_file_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            path = root / package["engineering_validation_result_path"]
            write_json(path, {"validator_status": "failed", "errors": ["critical"]})
            package["engineering_validation_result_sha256"] = sha256_path(path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_engineering_validation_task_mismatch_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            path = root / package["engineering_validation_result_path"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["task_id"] = "R1-OTHER"
            write_json(path, payload)
            package["engineering_validation_result_sha256"] = sha256_path(path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_engineering_validation_commit_mismatch_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            path = root / package["engineering_validation_result_path"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["code_commit"] = "b" * 40
            write_json(path, payload)
            package["engineering_validation_result_sha256"] = sha256_path(path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_missing_experiment_summary_fails(self) -> None:
        self.assert_fixture_fails(
            final=False,
            mode="author-draft",
            mutate=lambda package, _root: package.update(
                {"experiment_summary_path": None}
            ),
        )

    def test_missing_formal_evidence_fails(self) -> None:
        self.assert_fixture_fails(
            final=False,
            mode="author-draft",
            mutate=lambda package, _root: package.update(
                {"formal_evidence_path": None}
            ),
        )

    def test_missing_scientific_review_markdown_final_gate_fails(self) -> None:
        self.assert_fixture_fails(
            final=True,
            mode="final-gate",
            mutate=lambda package, _root: package.update(
                {"scientific_review_md_path": None}
            ),
        )

    def test_blocked_check_without_blocking_anomaly_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            scan_path = root / package["anomaly_scan_path"]
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            scan["checks"]["all_zero_check"]["status"] = "blocked"
            scan_path.write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
            package["anomaly_scan_sha256"] = sha256_path(scan_path)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_blocking_anomaly_references_passed_check_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            scan_path = root / package["anomaly_scan_path"]
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            scan["blocking_anomalies"] = ["all_zero_check"]
            scan_path.write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
            package["anomaly_scan_sha256"] = sha256_path(scan_path)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_anomaly_task_id_mismatch_fails(self) -> None:
        self.assert_scan_mutation_fails("task_id", "R1-OTHER")

    def test_anomaly_run_id_mismatch_fails(self) -> None:
        self.assert_scan_mutation_fails("run_id", "OTHER-RUN")

    def test_anomaly_code_commit_mismatch_fails(self) -> None:
        self.assert_scan_mutation_fails("code_commit", "b" * 40)

    def test_empty_artifact_references_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            scan_path = root / package["anomaly_scan_path"]
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            scan["checks"]["coverage_check"]["artifact_references"] = []
            scan_path.write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
            package["anomaly_scan_sha256"] = sha256_path(scan_path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_scan_status_inconsistent_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            scan_path = root / package["anomaly_scan_path"]
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            scan["scan_status"] = "blocked"
            scan_path.write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
            package["anomaly_scan_sha256"] = sha256_path(scan_path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_formal_evidence_gate_mismatch_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            path = root / package["formal_evidence_path"]
            text = path.read_text(encoding="utf-8").replace(
                "`downstream_gate_allowed`: false",
                "`downstream_gate_allowed`: true",
            )
            path.write_text(text, encoding="utf-8")
            package["formal_evidence_sha256"] = sha256_path(path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def test_readme_pointer_mismatch_final_gate_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            readme = root / package["readme_path"]
            readme.write_text("current_stage: R2\n", encoding="utf-8")
            package["readme_sha256"] = sha256_path(readme)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def test_author_draft_completed_status_fails(self) -> None:
        self.assert_fixture_fails(
            final=False,
            mode="author-draft",
            mutate=lambda package, _root: package.update({"status": "completed"}),
        )

    def test_absolute_artifact_path_fails(self) -> None:
        def mutate(package: dict, root: Path) -> None:
            package["primary_result_artifacts"][0]["path"] = str(
                (root / "primary.json").resolve()
            )

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)

    def assert_fixture_fails(self, *, final: bool, mode: str, mutate) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path = build_fixture(root, final=final, mutate=mutate)
            with self.assertRaises(FormalExperimentPackageValidationError):
                validate_formal_experiment_package(
                    package_path,
                    mode=mode,
                    output_path=root / "out.json",
                    root=root,
                )

    def assert_review_mutation_fails(self, key: str, value: object) -> None:
        def mutate(package: dict, root: Path) -> None:
            review_path = root / package["scientific_review_record_path"]
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review[key] = value
            rewrite_review(package, review_path, review)

        self.assert_fixture_fails(final=True, mode="final-gate", mutate=mutate)

    def assert_scan_mutation_fails(self, key: str, value: object) -> None:
        def mutate(package: dict, root: Path) -> None:
            scan_path = root / package["anomaly_scan_path"]
            scan = json.loads(scan_path.read_text(encoding="utf-8"))
            scan[key] = value
            write_json(scan_path, scan)
            package["anomaly_scan_sha256"] = sha256_path(scan_path)

        self.assert_fixture_fails(final=False, mode="author-draft", mutate=mutate)


def build_fixture(root: Path, *, final: bool, mutate=None) -> Path:
    write_text(root / "config.json", "{}\n")
    write_json(root / "experiment_summary.json", {"summary": "ok"})
    write_text(root / "primary.json", json.dumps([{"config": "baseline"}]) + "\n")
    write_text(root / "diagnostic.json", '{"records": 1}\n')
    write_json(
        root / "engineering_validation.json",
        {
            "task_id": "R1-TXX",
            "run_id": "R1-TXX-20260710T0000Z",
            "code_commit": "a" * 40,
            "validator_status": "passed",
            "errors": [],
        },
    )
    write_text(root / "analysis.md", analysis_text())
    write_json(root / "anomaly_scan.json", anomaly_scan())
    write_text(root / "README.md", readme_text())
    review_path = root / "scientific_review.json"
    review_md_path = root / "scientific_review.md"
    if final:
        write_json(
            review_path,
            scientific_review(
                summary_sha=sha256_path(root / "experiment_summary.json"),
                analysis_sha=sha256_path(root / "analysis.md"),
            ),
        )
        write_text(review_md_path, "scientific review passed\n")
    write_text(root / "formal_evidence.md", "")

    gate = {
        "engineering_validator_status": "passed",
        "result_artifact_status": "passed",
        "author_result_analysis_status": "passed",
        "scientific_review_status": "passed" if final else "pending",
        "anomaly_resolution_status": "passed",
        "review_phase": "independent_review_complete"
        if final
        else "author_analysis_complete",
        "readme_gate_updated": final,
    }
    package = {
        "task_id": "R1-TXX",
        "task_class": "formal_experiment",
        "run_id": "R1-TXX-20260710T0000Z",
        "code_commit": "a" * 40,
        "implementation_actor": "codex",
        "status": "completed" if final else "author_analysis_complete",
        "input_package": {"path": "input_manifest.json", "sha256": "b" * 64},
        "config_path": "config.json",
        "config_sha256": sha256_path(root / "config.json"),
        "experiment_summary_path": "experiment_summary.json",
        "experiment_summary_sha256": sha256_path(root / "experiment_summary.json"),
        "primary_result_artifacts": [
            {
                "artifact_role": "primary_results",
                "path": "primary.json",
                "sha256": sha256_path(root / "primary.json"),
                "record_count": 1,
                "committed_to_repo": True,
            }
        ],
        "diagnostic_artifacts": [
            {
                "artifact_role": "diagnostic_summary",
                "path": "diagnostic.json",
                "sha256": sha256_path(root / "diagnostic.json"),
                "record_count": 1,
                "committed_to_repo": True,
            }
        ],
        "anomaly_scan_path": "anomaly_scan.json",
        "anomaly_scan_sha256": sha256_path(root / "anomaly_scan.json"),
        "result_analysis_path": "analysis.md",
        "result_analysis_sha256": sha256_path(root / "analysis.md"),
        "engineering_validation_result_path": "engineering_validation.json",
        "engineering_validation_result_sha256": sha256_path(
            root / "engineering_validation.json"
        ),
        "formal_evidence_path": "formal_evidence.md",
        "formal_evidence_sha256": "",
        "scientific_review_record_path": "scientific_review.json" if final else None,
        "scientific_review_record_sha256": sha256_path(review_path) if final else None,
        "scientific_review_md_path": "scientific_review.md" if final else None,
        "scientific_review_md_sha256": sha256_path(review_md_path) if final else None,
        "readme_path": "README.md",
        "readme_sha256": sha256_path(root / "README.md"),
        "expected_current_stage": "R1",
        "expected_current_task": "R1-TNEXT next task",
        "expected_next_planned_task": "R1-TNEXT2 planned task",
        "expected_downstream_gate_marker": "R1-TNEXT_allowed_to_start: true",
        "superseded": False,
        "superseded_by": None,
        "gate_status": gate,
        "downstream_gate_allowed": final,
    }
    write_evidence(root / "formal_evidence.md", package)
    package["formal_evidence_sha256"] = sha256_path(root / "formal_evidence.md")
    if mutate is not None:
        mutate(package, root)
    package_path = root / "result_package.json"
    write_json(package_path, package)
    return package_path


def anomaly_scan() -> dict:
    checks = {
        name: {
            "status": "passed",
            "rationale": f"{name} checked on synthetic artifact.",
            "metrics": {"record_count": 1},
            "artifact_references": ["primary.json"],
        }
        for name in MANDATORY_CHECKS
    }
    return {
        "task_id": "R1-TXX",
        "run_id": "R1-TXX-20260710T0000Z",
        "code_commit": "a" * 40,
        "scan_status": "passed",
        "checks": checks,
        "blocking_anomalies": [],
        "nonblocking_anomalies": [],
        "investigations": [],
        "unresolved_questions": [],
    }


def scientific_review(*, summary_sha: str, analysis_sha: str) -> dict:
    return {
        "reviewer_identity": "independent-reviewer",
        "reviewer_role": "scientific_reviewer",
        "implementation_actor": "codex",
        "independence_attestation": True,
        "reviewed_code_commit": "a" * 40,
        "reviewed_summary_sha256": summary_sha,
        "reviewed_analysis_sha256": analysis_sha,
        "independent_recomputations": [{"metric": "record_count", "value": 1}],
        "baseline_challenger_review": "baseline and challengers checked",
        "parameter_response_review": "parameter response checked",
        "anomaly_review": "anomalies resolved",
        "alternative_explanations": ["sample composition"],
        "blocking_findings": [],
        "nonblocking_findings": [],
        "scientific_review_status": "passed",
        "downstream_gate_recommendation": True,
    }


def readme_text() -> str:
    return (
        "current_stage: R1\n"
        "current_task: R1-TNEXT next task\n"
        "next_planned_task: R1-TNEXT2 planned task\n"
        "R1-TNEXT_allowed_to_start: true\n"
    )


def write_evidence(path: Path, package: dict) -> None:
    gate = package["gate_status"]
    lines = [
        f"`engineering_validator_status`: {gate['engineering_validator_status']}",
        f"`result_artifact_status`: {gate['result_artifact_status']}",
        f"`author_result_analysis_status`: {gate['author_result_analysis_status']}",
        f"`scientific_review_status`: {gate['scientific_review_status']}",
        f"`anomaly_resolution_status`: {gate['anomaly_resolution_status']}",
        f"`downstream_gate_allowed`: {str(package['downstream_gate_allowed']).lower()}",
        f"`result_analysis_sha256`: {package['result_analysis_sha256']}",
        f"`anomaly_scan_sha256`: {package['anomaly_scan_sha256']}",
        "`engineering_validation_result_sha256`: "
        f"{package['engineering_validation_result_sha256']}",
    ]
    if package.get("scientific_review_record_sha256"):
        lines.append(
            f"`scientific_review_sha256`: {package['scientific_review_record_sha256']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analysis_text() -> str:
    sections = "\n\n".join(
        f"{heading}\nobserved_fact: checked." for heading in ANALYSIS_HEADINGS
    )
    return (
        sections
        + "\n\nderived_statistic: checked.\ninference: limited.\n"
        + "research_judgment: gate=false until review.\n"
    )


def rewrite_review(package: dict, path: Path, review: dict) -> None:
    write_json(path, review)
    package["scientific_review_record_sha256"] = sha256_path(path)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def sha256_path(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
