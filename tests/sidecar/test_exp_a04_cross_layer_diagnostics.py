# ruff: noqa: E501

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.sidecar.exp_a04_cross_layer_diagnostics import (
    A_IDS,
    LineageError,
    build_analysis,
    build_anomaly_scan,
    build_result_analysis,
    pair_registry,
    pcvt_registry,
)

PCVT_IDS = [
    "P1_NATR14",
    "P2_LogRange20",
    "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60",
    "T1_ER20",
    "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60",
    "V2_LogAmount20_base",
]


def make_inputs(
    root: Path, *, securities: int = 3, days_per_year: int = 12
) -> tuple[Path, Path]:
    a_path = root / "a.duckdb"
    p_path = root / "p.duckdb"
    a = duckdb.connect(str(a_path))
    p = duckdb.connect(str(p_path))
    a.execute(
        "CREATE TABLE exp_a01_raw_metrics(security_id VARCHAR,trading_date VARCHAR,observation_sequence BIGINT,indicator_id VARCHAR,raw_value DOUBLE,validity_status VARCHAR)"
    )
    p.execute(
        "CREATE TABLE r0_t04_raw_metric_results(security_id VARCHAR,trading_date VARCHAR,indicator_id VARCHAR,raw_value DOUBLE,validity_status VARCHAR)"
    )
    a_rows: list[tuple[object, ...]] = []
    p_rows: list[tuple[object, ...]] = []
    for security in range(securities):
        for year in range(2016, 2027):
            for day in range(1, days_per_year + 1):
                date_text = f"{year:04d}-01-{day:02d}"
                index = (year - 2016) * days_per_year + day
                a_rows.extend(
                    (
                        f"S{security}",
                        date_text,
                        index,
                        indicator,
                        index / 100 + offset,
                        "valid",
                    )
                    for offset, indicator in enumerate(A_IDS)
                )
                p_rows.extend(
                    (
                        f"S{security}",
                        date_text,
                        indicator,
                        index / 100 + offset,
                        "valid",
                    )
                    for offset, indicator in enumerate(PCVT_IDS)
                )
    a.executemany("INSERT INTO exp_a01_raw_metrics VALUES (?,?,?,?,?,?)", a_rows)
    p.executemany("INSERT INTO r0_t04_raw_metric_results VALUES (?,?,?,?,?)", p_rows)
    a.close()
    p.close()
    return a_path, p_path


class ExpA04CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.config = json.loads(
            Path("configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.a_path, self.p_path = make_inputs(self.root)

    def tearDown(self) -> None:
        for path in self.root.glob(
            "*.duckdb"
        ):  # close handles are owned by the test body
            try:
                path.unlink()
            except PermissionError:
                pass

    def test_registry_and_pair_registry_are_frozen(self) -> None:
        registry = pcvt_registry(self.config)
        self.assertEqual(len(registry), 8)
        self.assertEqual({row["layer"] for row in registry}, {"P", "C", "T", "V"})
        self.assertEqual(
            [row["indicator_id"] for row in registry][-1], "V2_LogAmount20_base"
        )
        pairs = pair_registry(self.config)
        self.assertEqual(len(pairs), 24)
        self.assertEqual(len({row["pair_id"] for row in pairs}), 24)
        self.assertTrue(
            all(
                row["a_direction"]
                == row["pcvt_direction"]
                == "lower_raw_is_more_convergent"
                for row in pairs
            )
        )

    def test_pair_specific_universe_and_output_contract(self) -> None:
        a = duckdb.connect(str(self.a_path), read_only=True)
        p = duckdb.connect(str(self.p_path), read_only=True)
        p.execute(
            "ATTACH ? AS probe (READ_ONLY)", [str(self.p_path)]
        ) if False else None
        analysis = build_analysis(a, p, self.config, pcvt_path=self.p_path)
        self.assertEqual(
            [
                len(analysis[key])
                for key in (
                    "indicator_registry",
                    "pairwise_coverage",
                    "pairwise_overall",
                    "pairwise_year",
                    "pairwise_security",
                    "tail_overlap",
                    "layer_summary",
                    "candidate_summary",
                )
            ],
            [11, 24, 24, 264, 72, 72, 12, 3],
        )
        self.assertTrue(
            all(row["common_count"] > 0 for row in analysis["pairwise_overall"])
        )
        self.assertTrue(
            all(row["one_to_one_key_proven"] for row in analysis["pairwise_coverage"])
        )
        a.close()
        p.close()

    def test_canonical_duplicate_is_fail_closed(self) -> None:
        p = duckdb.connect(str(self.p_path))
        p.execute(
            "INSERT INTO r0_t04_raw_metric_results VALUES ('S0','2016-01-01','P1_NATR14',9.0,'valid')"
        )
        p.close()
        a = duckdb.connect(str(self.a_path), read_only=True)
        p = duckdb.connect(str(self.p_path), read_only=True)
        with self.assertRaises(LineageError):
            build_analysis(a, p, self.config, pcvt_path=self.p_path)
        a.close()
        p.close()

    def test_tied_tail_includes_all_threshold_ties_and_anomaly_is_investigation(
        self,
    ) -> None:
        p = duckdb.connect(str(self.p_path))
        p.execute(
            "UPDATE r0_t04_raw_metric_results SET raw_value=1.0 WHERE indicator_id='P1_NATR14'"
        )
        p.close()
        a = duckdb.connect(str(self.a_path), read_only=True)
        p = duckdb.connect(str(self.p_path), read_only=True)
        analysis = build_analysis(a, p, self.config, pcvt_path=self.p_path)
        tail = next(
            row
            for row in analysis["tail_overlap"]
            if row["pair_id"] == "A1__P1_NATR14" and row["tail_fraction"] == 0.05
        )
        self.assertEqual(tail["pcvt_selected_count"], 396)
        self.assertEqual(tail["intersection_count"], tail["a_selected_count"])
        anomaly = build_anomaly_scan(analysis, self.config, synthetic_fixture=True)
        self.assertEqual(anomaly["status"], "passed_with_investigation_items")
        self.assertIn(
            "synthetic_fixture_requires_investigation", anomaly["investigation_items"]
        )
        self.assertTrue(
            build_result_analysis(
                "SYNTH-A04-20260717T000000000Z",
                "",
                anomaly["status"],
                synthetic_fixture=True,
            )
            .rstrip()
            .endswith("needs_investigation_before_user_review")
        )
        a.close()
        p.close()


if __name__ == "__main__":
    unittest.main()
