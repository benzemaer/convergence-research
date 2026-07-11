from __future__ import annotations

# ruff: noqa: E501
import csv
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "data/generated/r1/r1_t14_02/R1-T14-02-20260710T2340Z"
T05_DIR = ROOT / "data/generated/r1/r1_t05/R1-T05-20260710T0959Z"


def load_json(name: str) -> dict[str, object]:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class R1T1402AuthorDraftContractTests(unittest.TestCase):
    def test_package_preserves_same_sample_and_external_review_boundaries(self) -> None:
        package = load_json("r1_t14_02_result_package.json")
        self.assertEqual(package["status"], "author_draft_complete")
        self.assertTrue(package["selection_path_not_independently_confirmed"])
        self.assertEqual(package["goal_internal_completion_gate_status"], "passed")
        self.assertTrue(package["goal_internal_completion_allowed"])
        self.assertEqual(package["scientific_review_status"], "pending")
        self.assertEqual(package["independent_review_status"], "not_started")
        self.assertEqual(package["repository_final_gate_status"], "pending")
        self.assertFalse(package["downstream_gate_allowed"])
        self.assertFalse(package["R1-T10_allowed_to_start"])
        self.assertFalse(package["R2_allowed_to_start"])
        self.assertFalse(package["formal_task_completed"])

    def test_committed_artifact_hashes_are_current(self) -> None:
        package = load_json("r1_t14_02_result_package.json")
        for artifact in package["committed_artifacts"]:
            path = ROOT / artifact["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"], path
            )

    def test_registry_r0_reconciliation_and_geometry_are_exact(self) -> None:
        registry = rows(RUN_DIR / "r1_t14_02_candidate_registry.csv")
        self.assertEqual(len(registry), 10)
        self.assertEqual(sum(row["baseline_reuse"] == "true" for row in registry), 2)
        self.assertEqual(sum(row["request_role"] == "center" for row in registry), 4)
        self.assertEqual(
            sum(row["request_role"] == "immediate_neighbor" for row in registry), 4
        )
        reconciliation = rows(RUN_DIR / "r1_t14_02_r0_lineage_reconciliation.csv")
        self.assertEqual(len(reconciliation), 12)
        self.assertTrue(all(row["mismatch_count"] == "0" for row in reconciliation))
        intervals = rows(RUN_DIR / "r1_t14_02_interval_profile.csv")
        self.assertTrue(all(row["conservation_mismatch"] == "0" for row in intervals))

    def test_intralayer_reconciles_r1_t05_average_rank_semantics(self) -> None:
        actual = rows(RUN_DIR / "r1_t14_02_intralayer_profile.csv")
        correlation = rows(T05_DIR / "r1_t05_intralayer_correlation.csv")
        compared = 0
        for upstream in correlation:
            if upstream["W"] not in {"120", "250"}:
                continue
            values = {
                float(row["continuous_score_spearman"])
                for row in actual
                if row["W"] == upstream["W"] and row["layer"] == upstream["layer"]
            }
            self.assertEqual(len(values), 1)
            self.assertAlmostEqual(
                values.pop(), float(upstream["pooled_spearman_score"]), places=12
            )
            compared += 1
        self.assertEqual(compared, 8)

    def test_security_level_groups_are_pseudonymized(self) -> None:
        interlayer = rows(RUN_DIR / "r1_t14_02_interlayer_profile.csv")
        security_rows = [
            row for row in interlayer if row["analysis_level"] == "security"
        ]
        self.assertEqual(len(security_rows), 24000)
        self.assertTrue(
            all(
                row["group_id"].startswith("security_sha256_")
                and ".SH" not in row["group_id"]
                and ".SZ" not in row["group_id"]
                for row in security_rows
            )
        )

    def test_multiplicity_uses_complete_five_family_max_statistic(self) -> None:
        maxima = rows(RUN_DIR / "r1_t14_02_family_max_statistic.csv")
        multiplicity = rows(RUN_DIR / "r1_t14_02_multiplicity_results.csv")
        self.assertEqual(len(maxima), 50000)
        self.assertEqual(len(multiplicity), 30)
        self.assertEqual(len({row["family_id"] for row in multiplicity}), 5)
        for row in multiplicity:
            self.assertGreater(float(row["null_sd"]), 0)
            self.assertAlmostEqual(
                float(row["family_adjusted_p"]),
                (int(row["n_family_extreme"]) + 1) / 10001,
                places=15,
            )
            self.assertEqual(row["selection_path_not_independently_confirmed"], "true")

    def test_candidate_decisions_disclose_heterogeneity_without_false_gates(
        self,
    ) -> None:
        decisions = rows(RUN_DIR / "r1_t14_02_candidate_decision_matrix.csv")
        counts = {
            status: sum(row["candidate_status"] == status for row in decisions)
            for status in {row["candidate_status"] for row in decisions}
        }
        self.assertEqual(
            counts, {"formal_structure_supported_with_warning": 4, "review_only": 4}
        )
        self.assertTrue(
            all(
                row["global_and_nested_adjusted_null_pass"] == "true"
                for row in decisions
            )
        )
        self.assertTrue(
            all(row["year_level_delta_conflict"] == "false" for row in decisions)
        )
        self.assertTrue(
            all(row["pooled_security_sign_reversal"] == "false" for row in decisions)
        )
        self.assertTrue(
            all(float(row["security_negative_delta_share"]) > 0 for row in decisions)
        )
        self.assertTrue(
            all(
                row["parent_child_raw_violation_count"] == "0"
                and row["parent_child_confirmed_violation_count"] == "0"
                for row in decisions
            )
        )
        self.assertTrue(
            all(
                row["scientific_review_status"] == "pending"
                and row["formal_task_completed"] == "false"
                for row in decisions
            )
        )

    def test_analysis_records_supersession_and_unsupported_claims(self) -> None:
        analysis = (
            ROOT
            / "docs/experiments/r1/R1-T14-02_层级q向量正式结构复验_result_analysis.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "selection_path_not_independently_confirmed=true",
            "2221Z",
            "2245Z",
            "2306Z",
            "不作为当前 evidence",
            "不支持“独立确认”",
            "scientific_review_status=pending",
            "R1-T10_allowed_to_start=false",
        ):
            self.assertIn(marker, analysis)


if __name__ == "__main__":
    unittest.main()
