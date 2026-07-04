"""Configure local-only D2 source environment variables."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

REQUIRED_KEYS = ("HITHINK_API_KEY", "TUSHARE_TOKEN")
LOCAL_ENV_KEYS = ("HITHINK_API_KEY", "TUSHARE_TOKEN", "TNSKHDATA_TOKEN")


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={values.get(key, '')}\n" for key in LOCAL_ENV_KEYS),
        encoding="utf-8",
    )


def configure_env_file(path: Path, overwrite: bool = False) -> int:
    if not sys.stdin.isatty():
        print(
            "Non-interactive shell: set HITHINK_API_KEY/TUSHARE_TOKEN in the "
            "environment or provide a local .env file.",
            file=sys.stderr,
        )
        return 2
    values = _parse_env_file(path)
    for key in LOCAL_ENV_KEYS:
        if values.get(key) and not overwrite:
            continue
        values[key] = getpass.getpass(f"{key}: ")
    _write_env_file(path, values)
    print(f"Wrote local environment file: {path}")
    return 0


def check_env(path: Path | None) -> int:
    file_values = _parse_env_file(path) if path else {}
    missing = [
        key
        for key in REQUIRED_KEYS
        if not (os.environ.get(key) or file_values.get(key))
    ]
    if missing:
        print(
            "Missing required environment keys: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1
    print("Required D2 source environment keys are present.")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.local", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.check:
        return check_env(args.env_file)
    return configure_env_file(args.env_file, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
