import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t01_author_package import build_author_package
from src.r2.r2_t01_candidate_convergence_shortlist import build_run
from src.r2.r2_t01_candidate_convergence_shortlist_validator import validate_output

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json"


class R2T01AuthorDraft(unittest.TestCase):
    def test_author_package_keeps_review_and_downstream_pending(self):
        base = ROOT / "data/generated/r2/r2_t01"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            out = Path(tmp) / "R2-T01-20260711T0103Z"
            build_run(CONFIG, out)
            validate_output(out, CONFIG)
            package = build_author_package(out)
        self.assertEqual(package["status"], "author_analysis_complete")
        self.assertEqual(package["gate_status"]["scientific_review_status"], "pending")
        self.assertFalse(package["downstream_gate_allowed"])
        self.assertFalse(package["R2-T02_allowed_to_start"])
        self.assertFalse(package["formal_task_completed"])


if __name__ == "__main__":
    unittest.main()
