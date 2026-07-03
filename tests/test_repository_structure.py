from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "docs/00_研究章程.md",
    "docs/01_研究方案与预分析计划.md",
    "docs/02_数据治理与时点一致性规范.md",
    "docs/03_可复现研究工程标准.md",
    "docs/04_阶段与门禁框架.md",
    "docs/05_证据与产物治理政策.md",
    "schemas/dataset_manifest.schema.json",
    "schemas/run_manifest.schema.json",
    "schemas/artifact_manifest.schema.json",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class RepositoryStructureTest(unittest.TestCase):
    def test_required_governance_files_exist(self) -> None:
        missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
        self.assertEqual(missing, [])

    def test_relative_markdown_links_resolve(self) -> None:
        broken: list[str] = []
        for markdown in ROOT.rglob("*.md"):
            if ".git" in markdown.parts:
                continue
            text = markdown.read_text(encoding="utf-8")
            for target in MARKDOWN_LINK.findall(text):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                path_text = target.split("#", maxsplit=1)[0]
                if path_text and not (markdown.parent / path_text).resolve().exists():
                    broken.append(f"{markdown.relative_to(ROOT)} -> {target}")
        self.assertEqual(broken, [])


if __name__ == "__main__":
    unittest.main()
