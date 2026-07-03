from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/build_compendium.py"
SPEC = importlib.util.spec_from_file_location("build_compendium", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CompendiumTest(unittest.TestCase):
    def test_committed_compendium_matches_sources(self) -> None:
        committed = MODULE.OUTPUT.read_text(encoding="utf-8")
        self.assertEqual(committed, MODULE.render())

    def test_sources_are_unique_and_ordered(self) -> None:
        self.assertEqual(len(MODULE.SOURCES), len(set(MODULE.SOURCES)))
        self.assertEqual(MODULE.SOURCES[0].name, "README.md")
        self.assertEqual(MODULE.SOURCES[1].name, "AGENTS.md")


if __name__ == "__main__":
    unittest.main()
