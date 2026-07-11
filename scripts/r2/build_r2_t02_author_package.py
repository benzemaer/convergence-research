import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.r2.r2_t02_author_package import build_author_package  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--code-commit")
    a = p.parse_args()
    commit = (
        a.code_commit
        or subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    )
    build_author_package(a.output_dir, commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
