import json
import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t04_independent_validator import validate_independently


class R2T04UserDecisionTest(unittest.TestCase):
    def test_template_cannot_open_downstream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            rows = [
                {
                    "candidate_cell_id": f"c{i}",
                    "hard_gate_status": "passed",
                    "gate_count": "1",
                    "passed_gate_count": "1",
                    "failed_gate_count": "0",
                    "missing_evidence_count": "0",
                }
                for i in range(72)
            ]
            (path / "r2_t04_cell_gate_summary.csv").write_text(
                "candidate_cell_id,hard_gate_status,gate_count,passed_gate_count,failed_gate_count,missing_evidence_count\n"
                + "\n".join(",".join(row.values()) for row in rows)
                + "\n",
                encoding="utf-8",
            )
            (path / "r2_t04_hard_gate_report.csv").write_text(
                "status\npassed\n", encoding="utf-8"
            )
            (path / "r2_t04_pareto_objective_registry.csv").write_text(
                "direction\nmax\n", encoding="utf-8"
            )
            (path / "r2_t04_pareto_complexity_comparison.csv").write_text(
                "candidate_cell_id\n" + "\n".join(f"c{i}" for i in range(72)) + "\n",
                encoding="utf-8",
            )
            (path / "r2_t04_automatic_recommendation.json").write_text(
                json.dumps(
                    {"status": "awaiting_user_decision", "user_decision_required": True}
                ),
                encoding="utf-8",
            )
            (path / "r2_t04_user_decision_template.json").write_text(
                json.dumps(
                    {"user_decision_status": "pending", "formal_task_completed": False}
                ),
                encoding="utf-8",
            )
            result = validate_independently(path)
            self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
