# ruff: noqa: E501

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.sidecar.exp_a04_cross_layer_diagnostics import build_analysis, write_outputs
from src.sidecar.exp_a04_cross_layer_diagnostics_validator import validate_formal_result
from tests.sidecar.test_exp_a04_cross_layer_diagnostics import make_inputs


class ExpA04ValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.config = json.loads(
            Path("configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.a_path, self.p_path = make_inputs(self.root)
        a = duckdb.connect(str(self.a_path), read_only=True)
        p = duckdb.connect(str(self.p_path), read_only=True)
        self.analysis = build_analysis(a, p, self.config, pcvt_path=self.p_path)
        a.close()
        p.close()
        self.package = self.root / "package"
        write_outputs(
            self.package, self.analysis, run_id="SYNTH-A04-20260717T000000000Z"
        )

    def _validate(self) -> dict[str, object]:
        return validate_formal_result(
            self.package,
            config=self.config,
            a_raw_path=self.a_path,
            pcvt_raw_path=self.p_path,
            run_id="SYNTH-A04-20260717T000000000Z",
            synthetic_fixture=True,
            require_final_manifest=False,
        )

    def test_independent_replay_passes(self) -> None:
        result = self._validate()
        self.assertEqual(result["status"], "passed", result)
        self.assertTrue(result["full_output_aggregate_recompute_performed"])

    def test_persisted_csv_mutation_fails(self) -> None:
        path = self.package / "exp_a04_pairwise_overall.csv"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(",", ",999999,", 1), encoding="utf-8", newline="\n"
        )
        result = self._validate()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(
            any(
                "csv_fields_mismatch" in error or "aggregate_mismatch" in error
                for error in result["errors"]
            )
        )

    def test_persisted_disposition_mutation_fails(self) -> None:
        path = self.package / "exp_a04_cross_layer_disposition.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["candidate_set_for_A05"] = ["A1"]
        path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
        result = self._validate()
        self.assertEqual(result["status"], "failed")
        self.assertIn("candidate_set_auto_reduced", result["errors"])

    def test_disposition_criteria_actual_mutation_fails(self) -> None:
        path = self.package / "exp_a04_cross_layer_disposition.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        criterion = payload["pair_collision_results"][0]["criteria"]["overall_spearman"]
        criterion["actual"] = 0.123456
        path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
        result = self._validate()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(
            any("disposition_semantic_mismatch" in error for error in result["errors"])
        )

    def test_candidate_collision_list_mutation_fails(self) -> None:
        path = self.package / "exp_a04_cross_layer_disposition.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["candidate_collision_summary"]["A1"]["hard_collision_pairs"] = [
            "forged_pair"
        ]
        path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
        result = self._validate()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(
            any("disposition_semantic_mismatch" in error for error in result["errors"])
        )

    def test_missing_pair_year_is_rejected_by_standalone_replay(self) -> None:
        root = Path(tempfile.mkdtemp())
        a_path, p_path = make_inputs(root)
        p = duckdb.connect(str(p_path))
        p.execute(
            "DELETE FROM r0_t04_raw_metric_results WHERE indicator_id='P1_NATR14' AND trading_date LIKE '2017-%'"
        )
        p.close()
        a = duckdb.connect(str(a_path), read_only=True)
        p = duckdb.connect(str(p_path), read_only=True)
        analysis = build_analysis(a, p, self.config, pcvt_path=p_path)
        a.close()
        p.close()
        package = root / "package"
        write_outputs(package, analysis, run_id="SYNTH-A04-20260717T000000000Z")
        result = validate_formal_result(
            package,
            config=self.config,
            a_raw_path=a_path,
            pcvt_raw_path=p_path,
            run_id="SYNTH-A04-20260717T000000000Z",
            synthetic_fixture=True,
            require_final_manifest=False,
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("accepted_year_missing:A1__P1_NATR14:2017", result["errors"])

    def test_text_date_adapter_is_canonical(self) -> None:
        p = duckdb.connect(str(self.p_path))
        p.execute(
            "UPDATE r0_t04_raw_metric_results SET trading_date=replace(trading_date,'-','')"
        )
        p.close()
        a = duckdb.connect(str(self.a_path), read_only=True)
        p = duckdb.connect(str(self.p_path), read_only=True)
        analysis = build_analysis(a, p, self.config, pcvt_path=self.p_path)
        self.assertEqual(len(analysis["pairwise_overall"]), 24)
        a.close()
        p.close()


if __name__ == "__main__":
    unittest.main()
