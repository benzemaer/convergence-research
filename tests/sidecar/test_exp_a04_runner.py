# ruff: noqa: E501

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sidecar.run_exp_a04_cross_layer_diagnostics import build_parser, run
from src.sidecar.exp_a04_cross_layer_diagnostics import OUTPUT_FILES
from tests.sidecar.test_exp_a04_cross_layer_diagnostics import make_inputs


class ExpA04RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.config = Path(
            "configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json"
        ).resolve()
        self.a_path, self.p_path = make_inputs(self.root)

    def _args(
        self, output: Path, failure: Path, run_id: str = "SYNTH-A04-20260717T000000000Z"
    ):
        parser = build_parser()
        return parser.parse_args(
            [
                "--allow-synthetic-fixture",
                "--a01-raw",
                str(self.a_path),
                "--pcvt-raw",
                str(self.p_path),
                "--output-dir",
                str(output),
                "--failure-root",
                str(failure),
                "--run-id",
                run_id,
                "--config",
                str(self.config),
            ]
        )

    def test_synthetic_runner_publishes_only_compact_outputs(self) -> None:
        output = self.root / "out"
        result = run(self._args(output, self.root / "failure"))
        self.assertEqual(result, 0)
        self.assertEqual({path.name for path in output.iterdir()}, set(OUTPUT_FILES))
        self.assertFalse(list(output.glob("*.duckdb")))
        manifest = json.loads(
            (output / "exp_a04_manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["formal_run_executed"])
        self.assertFalse(manifest["EXP_A05_started"])

    def test_duplicate_failure_preserves_compact_diagnostics_without_raw_copy(
        self,
    ) -> None:
        import duckdb

        connection = duckdb.connect(str(self.p_path))
        connection.execute(
            "INSERT INTO r0_t04_raw_metric_results VALUES ('S0','2016-01-01','P1_NATR14',4.0,'valid')"
        )
        connection.close()
        output = self.root / "out"
        failure = self.root / "failure"
        result = run(self._args(output, failure))
        self.assertEqual(result, 1)
        self.assertFalse(output.exists())
        package = failure / "SYNTH-A04-20260717T000000000Z" / "package"
        self.assertTrue((package.parent / "failure_summary.json").is_file())
        self.assertFalse(list(package.rglob("*.duckdb")))

    def test_formal_gate_rejects_bad_sha_before_raw_connect(self) -> None:
        args = self._args(self.root / "out", self.root / "failure")
        args.allow_synthetic_fixture = False
        args.allow_formal_run = True
        args.reviewed_implementation_sha = "not-a-sha"
        args.input_manifest = self.root / "manifest.json"
        connect_calls: list[object] = []
        with patch(
            "scripts.sidecar.run_exp_a04_cross_layer_diagnostics.duckdb.connect",
            side_effect=lambda *a, **k: connect_calls.append((a, k)),
        ):
            result = run(args)
        self.assertEqual(result, 1)
        self.assertEqual(connect_calls, [])

    def test_same_fixture_has_byte_identical_csv_outputs(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        self.assertEqual(
            run(
                self._args(
                    first, self.root / "failure1", "SYNTH-A04-20260717T000000000Z"
                )
            ),
            0,
        )
        self.assertEqual(
            run(
                self._args(
                    second, self.root / "failure2", "SYNTH-A04-20260717T000000001Z"
                )
            ),
            0,
        )
        csv_names = [name for name in OUTPUT_FILES if name.endswith(".csv")]
        for name in csv_names:
            self.assertEqual(
                (first / name).read_bytes(), (second / name).read_bytes(), name
            )


if __name__ == "__main__":
    unittest.main()
