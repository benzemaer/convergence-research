from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.r1.r1_t04_state_line_profiles_validator import (
    R1T04ValidationError,
    _require_numeric,
    validate_r1_t04_state_line_profiles,
)


class R1T04ValidatorTest(unittest.TestCase):
    def test_blocked_summary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = root / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "task_id": "R1-T04",
                        "status": "blocked",
                        "output_paths": {},
                        "checks": {},
                        "blocked_reasons": ["input"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(R1T04ValidationError):
                validate_r1_t04_state_line_profiles(summary_path=summary, root=root)

    def test_required_profile_metric_null_is_rejected(self) -> None:
        errors: list[str] = []
        _require_numeric(
            {"both_onset": "", "onset_jaccard": "0.5"},
            ("both_onset", "onset_jaccard"),
            "onset_overlap",
            errors,
        )
        self.assertEqual(errors, ["onset_overlap_missing:both_onset"])


if __name__ == "__main__":
    unittest.main()
