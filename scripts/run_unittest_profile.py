from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import unittest
from collections import defaultdict
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
    parser.add_argument(
        "--slowest-files",
        type=int,
        default=10,
        metavar="N",
        help="Report the N slowest test files (default: 10; use 0 to disable).",
    )
    args = parser.parse_args(argv)
    if args.slowest_files < 0:
        parser.error("--slowest-files must be non-negative")

    profiles = _load_profiles(PROFILE_CONFIG)
    if args.profile not in profiles:
        print(f"unknown unittest profile: {args.profile}", file=sys.stderr)
        return 2

    suite = _build_suite(profiles[args.profile])
    runner = unittest.TextTestRunner(
        verbosity=2 if args.verbose else 1,
        resultclass=TimingTestResult,
    )
    started = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - started
    print(
        "unittest_profile="
        f"{args.profile} tests={result.testsRun} failures={len(result.failures)} "
        f"errors={len(result.errors)} skipped={len(result.skipped)} "
        f"elapsed_seconds={elapsed:.3f}"
    )
    if args.slowest_files:
        _print_slowest_files(result, args.slowest_files)
    return 0 if result.wasSuccessful() else 1


class TimingTestResult(unittest.TextTestResult):
    """Collect additive test-case runtime by source test file."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.file_elapsed_seconds: dict[str, float] = defaultdict(float)
        self.file_test_counts: dict[str, int] = defaultdict(int)
        self._test_started: float | None = None

    def startTest(self, test: unittest.case.TestCase) -> None:
        self._test_started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.case.TestCase) -> None:
        elapsed = time.perf_counter() - (self._test_started or time.perf_counter())
        test_file = _test_file(test)
        self.file_elapsed_seconds[test_file] += elapsed
        self.file_test_counts[test_file] += 1
        self._test_started = None
        super().stopTest(test)


def _test_file(test: unittest.case.TestCase) -> str:
    module = sys.modules.get(test.__class__.__module__)
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        return test.__class__.__module__
    path = Path(module_file).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _print_slowest_files(result: TimingTestResult, limit: int) -> None:
    ranked = sorted(
        result.file_elapsed_seconds.items(), key=lambda item: (-item[1], item[0])
    )[:limit]
    print(f"slowest_test_files count={len(ranked)} requested={limit}")
    for rank, (test_file, elapsed) in enumerate(ranked, start=1):
        print(
            f"slowest_test_file rank={rank} file={test_file} "
            f"tests={result.file_test_counts[test_file]} "
            f"elapsed_seconds={elapsed:.3f}"
        )


def _load_profiles(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("unittest profile config must contain a profiles object")
    return profiles


def _build_suite(profile: dict[str, Any]) -> unittest.TestSuite:
    loader = unittest.TestLoader()
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
