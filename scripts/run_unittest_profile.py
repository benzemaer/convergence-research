from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILE_CONFIG = ROOT / "configs/ci/unittest_profiles.v1.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a unittest profile.")
    parser.add_argument("--profile", required=True, help="Profile name to run.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose tests.")
    args = parser.parse_args(argv)

    profiles = _load_profiles(PROFILE_CONFIG)
    if args.profile not in profiles:
        print(f"unknown unittest profile: {args.profile}", file=sys.stderr)
        return 2

    suite = _build_suite(profiles[args.profile])
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    started = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - started
    print(
        "unittest_profile="
        f"{args.profile} tests={result.testsRun} failures={len(result.failures)} "
        f"errors={len(result.errors)} skipped={len(result.skipped)} "
        f"elapsed_seconds={elapsed:.3f}"
    )
    return 0 if result.wasSuccessful() else 1


def _load_profiles(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("unittest profile config must contain a profiles object")
    return profiles


def _build_suite(profile: dict[str, Any]) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for test_file in profile.get("files", []):
        suite.addTests(_load_tests_from_file(loader, ROOT / test_file))
    for item in profile.get("discover", []):
        suite.addTests(
            loader.discover(
                start_dir=item["start_dir"],
                pattern=item.get("pattern", "test*.py"),
            )
        )
    if suite.countTestCases() == 0:
        raise ValueError("unittest profile selected zero tests")
    return suite


def _load_tests_from_file(
    loader: unittest.TestLoader, path: Path
) -> unittest.TestSuite:
    if not path.exists():
        raise FileNotFoundError(path)
    module_name = "_unittest_profile_" + "_".join(path.with_suffix("").parts[-4:])
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load test file: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return loader.loadTestsFromModule(module)


if __name__ == "__main__":
    raise SystemExit(main())
