"""Validate repository-local storage policy and reject retired runtime locators."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/local_storage_policy.v1.json"
SCHEMA = ROOT / "schemas/local_storage_policy.schema.json"
ACTIVE_GLOBS = (
    "src/**/*",
    "scripts/**/*",
    "configs/**/*",
    "HANDOFF.md",
    "docs/tasks/**/*",
    "docs/stages/**/*",
    ".github/workflows/**/*",
)


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    file_attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(file_attributes & reparse_flag)


def _active_files() -> list[Path]:
    paths: set[Path] = set()
    for pattern in ACTIVE_GLOBS:
        paths.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(paths)


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [
        f"config:{error.message}"
        for error in Draft202012Validator(schema).iter_errors(config)
    ]
    retired_name = config["retired_external_root_names"][0]
    forbidden = (
        "D:" + "\\Code\\" + retired_name,
        retired_name + "\\",
        retired_name + "/",
    )
    for path in _active_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in forbidden:
            if pattern in text:
                errors.append(
                    f"retired_locator:{path.relative_to(ROOT).as_posix()}:{pattern}"
                )
    for relative in config["active_repository_roots"]:
        path = ROOT / relative
        if path.exists() and _is_reparse(path):
            errors.append(f"active_root_reparse_point:{relative}")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"local_storage_policy_status=passed checked_files={len(_active_files())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
