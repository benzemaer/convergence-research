import csv
import inspect
import tempfile
import unittest
from pathlib import Path

import src.r2.r2_t01_candidate_convergence_shortlist_validator as validator_module
from src.r2.r2_t01_candidate_convergence_shortlist import build_run
from src.r2.r2_t01_candidate_convergence_shortlist_validator import validate_output

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json"


class R2T01Validator(unittest.TestCase):
    def _fixture(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        out = Path(temp.name) / "R2-T01-20260711T0102Z"
        build_run(CONFIG, out)
        self.assertEqual(validate_output(out, CONFIG)["status"], "passed")
        return out

    def _mutate(self, fn, expected_error: str):
        out = self._fixture()
        path = out / "r2_t01_shortlist_registry.csv"
        rows = _read(path)
        fn(rows)
        _write(path, rows)
        with self.assertRaises(RuntimeError) as ctx:
            validate_output(out, CONFIG)
        self.assertIn(expected_error, str(ctx.exception))

    def test_t30_cannot_be_primary(self):
        def mutate(rows):
            row = next(
                r
                for r in rows
                if r["r1_handoff_row_id"] == "q_W120_K3_P20_C20_T30_V20_S_PCT"
            )
            row["candidate_role"] = "primary"
            row["selection_eligible"] = "True"
            row["t03_geometry_role"] = "primary"

        self._mutate(
            mutate, "field_mismatch:q_W120_K3_P20_C20_T30_V20_S_PCT:candidate_role"
        )

    def test_v25_cannot_be_sensitivity(self):
        def mutate(rows):
            row = next(
                r
                for r in rows
                if r["r1_handoff_row_id"] == "q_W250_K3_P20_C20_T20_V25_S_PCVT"
            )
            row["candidate_role"] = "sensitivity"

        self._mutate(
            mutate, "field_mismatch:q_W250_K3_P20_C20_T20_V25_S_PCVT:candidate_role"
        )

    def test_shared_fallback_cannot_be_removed(self):
        def mutate(rows):
            row = next(r for r in rows if r["r1_handoff_row_id"] == "shared_S_PCT_W120")
            row["fallback_eligible"] = "False"

        self._mutate(mutate, "field_mismatch:shared_S_PCT_W120:fallback_eligible")

    def test_shared_row_cannot_be_duplicated(self):
        def mutate(rows):
            rows.append(dict(rows[0]))

        self._mutate(mutate, "shared_q_duplicate_or_duplicate_handoff_row")

    def test_window_track_cannot_be_swapped(self):
        def mutate(rows):
            row = next(
                r
                for r in rows
                if r["r1_handoff_row_id"] == "q_W120_K3_P20_C20_T25_V20_S_PCT"
            )
            row["window_track_id"] = "long_reference"

        self._mutate(
            mutate, "field_mismatch:q_W120_K3_P20_C20_T25_V20_S_PCT:window_track_id"
        )

    def test_validator_does_not_import_builder_decision_helpers(self):
        source = inspect.getsource(validator_module)
        forbidden = (
            "canonical_row",
            "audit_row",
            "reconcile_sources",
            "anomaly_scan",
        )
        for name in forbidden:
            self.assertNotIn(f"    {name},", source)
            self.assertNotIn(f"import {name}", source)

    def test_warning_codes_cannot_be_deleted(self):
        def mutate(rows):
            row = next(
                r
                for r in rows
                if r["r1_handoff_row_id"] == "q_W120_K3_P20_C20_T25_V20_S_PCT"
            )
            row["warning_codes"] = "[]"

        self._mutate(
            mutate, "field_mismatch:q_W120_K3_P20_C20_T25_V20_S_PCT:warning_codes"
        )

    def test_selection_path_flag_cannot_flip(self):
        def mutate(rows):
            row = next(
                r
                for r in rows
                if r["r1_handoff_row_id"] == "q_W250_K3_P20_C20_T25_V20_S_PCT"
            )
            row["selection_path_not_independently_confirmed"] = "False"

        self._mutate(
            mutate,
            "field_mismatch:q_W250_K3_P20_C20_T25_V20_S_PCT:"
            "selection_path_not_independently_confirmed",
        )

    def test_pairing_cannot_be_mutated(self):
        def mutate(rows):
            row = next(
                r for r in rows if r["r1_handoff_row_id"] == "shared_S_PCVT_W120"
            )
            row["paired_primary_route_id"] = "r2_s_pct_w120_qt25_primary"

        self._mutate(
            mutate, "field_mismatch:shared_S_PCVT_W120:paired_primary_route_id"
        )

    def test_state_and_q_values_cannot_be_mutated(self):
        def mutate(rows):
            row = next(r for r in rows if r["r1_handoff_row_id"] == "shared_S_PCT_W250")
            row["state_line"] = "S_PCVT"

        self._mutate(mutate, "field_mismatch:shared_S_PCT_W250:state_line")


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
