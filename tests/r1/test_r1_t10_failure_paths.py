import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.r1.r1_t10_r1_gate_r2_decision_matrix_validator import validate

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/generated/r1/r1_t10/R1-T10-20260711T2000Z"

FIXTURE_FILES = [
    "r1_t10_anomaly_scan.json",
    "r1_t10_decision_recomputation.csv",
    "r1_t10_optional_task_trigger_matrix.csv",
    "r1_t10_readme_transition_artifact.json",
    "r1_t10_r2_decision_matrix.csv",
    "r1_t10_stage_acceptance_checklist.csv",
    "r1_t10_upstream_gate_reconciliation.csv",
]


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


class FailClosed(unittest.TestCase):
    def _fixture(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        dst = Path(temp.name)
        for name in FIXTURE_FILES:
            shutil.copy2(OUT / name, dst / name)
        self.assertEqual(validate(dst)["status"], "passed")
        return dst

    def _mutate_matrix(self, fn, expected_error: str) -> None:
        d = self._fixture()
        path = d / "r1_t10_r2_decision_matrix.csv"
        rows = _read_rows(path)
        fn(rows)
        _write_rows(path, rows)
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn(expected_error, result["errors"])

    def test_missing_row(self):
        self._mutate_matrix(lambda r: r.pop(), "matrix_row_count_must_equal_12")

    def test_cross_window_parent(self):
        def mutate(rows):
            row = next(x for x in rows if x["state_line"] == "S_PCVT")
            row["same_parameter_parent_id"] = "W999_bad"

        self._mutate_matrix(mutate, "cross_window_parent:shared_S_PCVT_W250")

    def test_v25_upgrade(self):
        def mutate(rows):
            row = next(
                x
                for x in rows
                if x["request_role"] == "immediate_neighbor" and x["qV"] == "0.25"
            )
            row["overall_handoff_status"] = "review_candidate"

        self._mutate_matrix(mutate, "v25_must_not_advance")

    def test_upstream_fail_is_specific(self):
        d = self._fixture()
        path = d / "r1_t10_upstream_gate_reconciliation.csv"
        rows = _read_rows(path)
        rows[0]["reconciliation_status"] = "failed"
        _write_rows(path, rows)
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn("upstream_reconciliation_failed_count:1", result["errors"])

    def test_superseded_source_is_specific(self):
        d = self._fixture()
        path = d / "r1_t10_upstream_gate_reconciliation.csv"
        rows = _read_rows(path)
        rows[0]["non_superseded"] = "false"
        rows[0]["reconciliation_status"] = "failed"
        _write_rows(path, rows)
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn("upstream_non_superseded_failed:R1-T01", result["errors"])

    def test_duplicate_source_is_specific(self):
        d = self._fixture()
        path = d / "r1_t10_upstream_gate_reconciliation.csv"
        rows = _read_rows(path)
        rows[0]["package_unique"] = "false"
        rows[0]["reconciliation_status"] = "failed"
        _write_rows(path, rows)
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn("upstream_package_unique_failed:R1-T01", result["errors"])

    def test_review_gate_fail_is_specific(self):
        d = self._fixture()
        path = d / "r1_t10_upstream_gate_reconciliation.csv"
        rows = _read_rows(path)
        rows[3]["scientific_gate"] = "needs_revision"
        rows[3]["reconciliation_status"] = "failed"
        _write_rows(path, rows)
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn("upstream_scientific_gate_failed:R1-T04", result["errors"])

    def test_final_gate_fail_is_specific(self):
        d = self._fixture()
        path = d / "r1_t10_upstream_gate_reconciliation.csv"
        rows = _read_rows(path)
        rows[3]["repository_gate"] = "failed"
        rows[3]["reconciliation_status"] = "failed"
        _write_rows(path, rows)
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn("upstream_repository_gate_failed:R1-T04", result["errors"])

    def test_source_hash_mismatch_is_specific(self):
        def mutate(rows):
            row = rows[0]
            hashes = json.loads(row["source_artifact_hashes"])
            hashes["R1-T04"]["sha256"] = "0" * 64
            row["source_artifact_hashes"] = json.dumps(hashes, separators=(",", ":"))

        self._mutate_matrix(mutate, "source_hash_mismatch:shared_S_PCT_W250:R1-T04")

    def test_missing_marginal_is_specific(self):
        def mutate(rows):
            row = next(x for x in rows if x["formal_vector_id"])
            row["target_marginal"] = ""

        self._mutate_matrix(
            mutate,
            "mandatory_numeric_field_missing:target_marginal:"
            "q_W250_K3_P20_C20_T25_V20_S_PCT",
        )

    def test_wrong_nested_family_is_specific(self):
        def mutate(rows):
            row = next(
                x
                for x in rows
                if x["handoff_row_id"] == "q_W120_K3_P20_C20_T25_V20_S_PCT"
            )
            row["nested_joint_lift"] = "1.7920173314062566"

        self._mutate_matrix(
            mutate,
            "nested_family_lift_mismatch:q_W120_K3_P20_C20_T25_V20_S_PCT",
        )

    def test_warning_loss_is_specific(self):
        def mutate(rows):
            rows[0]["warning_codes"] = "[]"

        self._mutate_matrix(mutate, "warnings_empty:shared_S_PCT_W250")

    def test_precedence_mismatch_science_fail_is_do_not_freeze(self):
        def mutate(rows):
            row = next(x for x in rows if x["handoff_row_id"] == "shared_S_PCT_W250")
            row["existence_status"] = "failed"
            row["overall_handoff_status"] = "blocked_return_to_R0"

        self._mutate_matrix(mutate, "decision_recomputation_mismatch")

    def test_optional_trigger_conflict_is_specific(self):
        d = self._fixture()
        path = d / "r1_t10_optional_task_trigger_matrix.csv"
        rows = _read_rows(path)
        rows[0]["trigger_status"] = "triggered"
        rows[0]["blocking_R2_handoff"] = "true"
        _write_rows(path, rows)
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn("optional_trigger_conflict:R1-T11", result["errors"])

    def test_illegal_readme_transition_is_specific(self):
        d = self._fixture()
        path = d / "r1_t10_readme_transition_artifact.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["allowed_field_changes"] = []
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        result = validate(d)
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            "transition_unallowed_field_changes:"
            "R1-T10_independent_review_status,"
            "R1-T10_scientific_review_status,R1-T10_status",
            result["errors"],
        )
