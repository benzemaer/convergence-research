from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.r1.r1_t04_state_line_profiles_validator import (
    R1T04ValidationError,
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


if __name__ == "__main__":
    unittest.main()
