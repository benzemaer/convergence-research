import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts/run_unittest_profile.py"
PROFILE_PATH = ROOT / "configs/ci/unittest_profiles.v1.json"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_unittest_profile", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load unittest profile runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UnittestProfileRunnerTest(unittest.TestCase):
    def test_timing_result_groups_tests_by_file(self):
        runner = _load_runner()
        stream = io.StringIO()
        result = runner.TimingTestResult(stream, True, 1)
        test = unittest.FunctionTestCase(lambda: None)
        test.run(result)
        self.assertEqual(sum(result.file_test_counts.values()), 1)
        self.assertGreaterEqual(sum(result.file_elapsed_seconds.values()), 0.0)

    def test_slowest_file_output_is_ranked_and_bounded(self):
        runner = _load_runner()
        result = runner.TimingTestResult(io.StringIO(), True, 1)
        result.file_elapsed_seconds.update({"tests/b.py": 1.0, "tests/a.py": 2.0})
        result.file_test_counts.update({"tests/a.py": 2, "tests/b.py": 1})
        output = io.StringIO()
        with redirect_stdout(output):
            runner._print_slowest_files(result, 1)
        self.assertIn("count=1 requested=1", output.getvalue())
        self.assertIn("rank=1 file=tests/a.py tests=2", output.getvalue())
        self.assertNotIn("tests/b.py", output.getvalue())

    def test_profiles_are_nonempty_without_duplicate_loading(self):
        runner = _load_runner()
        profiles = runner._load_profiles(PROFILE_PATH)
        for name, profile in profiles.items():
            suite = runner._build_suite(profile)
            test_ids = [test.id() for test in _flatten(suite)]
            self.assertTrue(test_ids, name)
            self.assertEqual(len(test_ids), len(set(test_ids)), name)

    def test_full_discovers_every_test_file(self):
        payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        full = payload["profiles"]["full"]
        self.assertEqual(
            full,
            {"discover": [{"start_dir": "tests", "pattern": "test*.py"}]},
        )
        discovered = {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "tests").rglob("test*.py")
        }
        self.assertTrue(discovered)

    def test_heavy_tests_are_split_without_losing_full_coverage(self):
        runner = _load_runner()
        profiles = runner._load_profiles(PROFILE_PATH)
        r0_smoke = "tests/r0/test_r0_t10_full_grid_materializer_smoke.py"
        r0_full = "tests/r0/test_r0_t10_full_grid_materializer.py"
        r1_smoke = "tests/r1/test_r1_t03_grid_contract_smoke.py"
        r1_full = "tests/r1/test_r1_t03_27_grid_light_profile_contract.py"

        self.assertTrue({r0_smoke, r1_smoke}.issubset(profiles["pr-fast"]["files"]))
        self.assertTrue({r0_full, r1_full}.isdisjoint(profiles["pr-fast"]["files"]))
        self.assertIn(r0_full, profiles["integration"]["files"])

        stage_r1_ids = [
            test.id() for test in _flatten(runner._build_suite(profiles["stage-r1"]))
        ]
        self.assertTrue(
            any(
                "test_r1_t03_27_grid_light_profile_contract" in test_id
                for test_id in stage_r1_ids
            )
        )
        for test_file in (r0_smoke, r0_full, r1_smoke, r1_full):
            self.assertTrue((ROOT / test_file).is_file(), test_file)


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


if __name__ == "__main__":
    unittest.main()
