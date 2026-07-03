"""Build or verify the deterministic governance-document compendium."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "A股收敛状态量化交易研究_基础文档集_合订本.md"
SOURCES = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "docs/00_研究章程.md",
    ROOT / "docs/01_研究方案与预分析计划.md",
    ROOT / "docs/02_数据治理与时点一致性规范.md",
    ROOT / "docs/03_可复现研究工程标准.md",
    ROOT / "docs/04_阶段与门禁框架.md",
    ROOT / "docs/05_证据与产物治理政策.md",
)
HEADER = "# A股收敛状态量化交易研究：基础文档集（合订本）"
NOTICE = "<!-- 由 scripts/build_compendium.py 生成；请勿手工编辑。 -->"


def render() -> str:
    sections = [HEADER, NOTICE]
    for source in SOURCES:
        text = source.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()
        sections.append(text)
    return "\n\n\n---\n\n".join(sections) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed compendium differs from generated content",
    )
    args = parser.parse_args()
    expected = render()

    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"{OUTPUT.name} is stale; run: python scripts/build_compendium.py")
            return 1
        print(f"{OUTPUT.name} is up to date")
        return 0

    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print(f"generated {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
