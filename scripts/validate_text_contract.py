from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.canonical_io import TEXT_EXTENSIONS, validate_text_file  # noqa: E402


def _git_lines(args: list[str], root: Path) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def default_text_files(root: Path) -> list[Path]:
    names: set[str] = set()
    names.update(_git_lines(["diff", "--name-only", "--cached"], root))
    names.update(_git_lines(["diff", "--name-only"], root))
    names.update(_git_lines(["diff", "--name-only", "origin/main...HEAD"], root))
    if not names:
        names.update(_git_lines(["ls-files"], root))
    paths: list[Path] = []
    for line in sorted(names):
        path = root / line
        if path.suffix.lower() in TEXT_EXTENSIONS:
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate canonical repository text.")
    parser.add_argument("paths", nargs="*", help="Optional repository-relative paths.")
    args = parser.parse_args(argv)

    paths = (
        [ROOT / item for item in args.paths] if args.paths else default_text_files(ROOT)
    )
    errors: list[str] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        for error in validate_text_file(path):
            errors.append(f"{path.relative_to(ROOT).as_posix()}:{error}")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"text_contract_status=passed checked_files={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
