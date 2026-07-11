import tempfile
import unittest
from collections import Counter
from pathlib import Path

from src.r2.r2_t01_candidate_convergence_shortlist import build_run

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json"


class R2T01Builder(unittest.TestCase):
    def test_builds_canonical_12_row_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "R2-T01-20260711T0100Z"
            summary = build_run(CONFIG, out)
            rows = list(_csv(out / "r2_t01_shortlist_registry.csv"))
            primary = list(_csv(out / "r2_t01_primary_shortlist.csv"))
        self.assertEqual(summary["canonical_registry_row_count"], 12)
        self.assertEqual(
            Counter(r["candidate_role"] for r in rows),
            {
                "primary": 4,
                "strict_core_reference": 4,
                "sensitivity": 2,
                "excluded": 2,
            },
        )
        self.assertEqual(len(primary), 4)
        self.assertEqual(
            sorted(r["route_id"] for r in primary),
            [
                "r2_s_pct_w120_qt25_primary",
                "r2_s_pct_w250_qt25_primary",
                "r2_s_pcvt_w120_qv30_primary",
                "r2_s_pcvt_w250_qv30_primary",
            ],
        )

    def test_shared_rows_are_not_duplicated_as_fallback_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "R2-T01-20260711T0101Z"
            build_run(CONFIG, out)
            rows = list(_csv(out / "r2_t01_shortlist_registry.csv"))
        shared = [r for r in rows if r["candidate_role"] == "strict_core_reference"]
        self.assertEqual(len(rows), 12)
        self.assertEqual(len(shared), 4)
        self.assertTrue(all(r["fallback_eligible"] == "True" for r in shared))
        self.assertTrue(
            all(r["independent_product_eligible"] == "False" for r in shared)
        )


def _csv(path: Path):
    import csv

    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


if __name__ == "__main__":
    unittest.main()
