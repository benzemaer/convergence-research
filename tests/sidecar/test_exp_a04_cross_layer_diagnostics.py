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
    root: Path,
    *,
    securities: int = 800,
    years: tuple[int, ...] = tuple(range(2016, 2027)),
    days_per_year: int = 1,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    a_path = root / "a.duckdb"
    p_path = root / "p.duckdb"
    a = duckdb.connect(str(a_path))
    p = duckdb.connect(str(p_path))
    year_values = ",".join(f"({year})" for year in years)
    a_indicator_values = ",".join(
        f"('{indicator}', {offset}.0)" for offset, indicator in enumerate(A_IDS)
    )
    pcvt_indicator_values = ",".join(
        f"('{indicator}', {offset}.0)" for offset, indicator in enumerate(PCVT_IDS)
    )
    a.execute(
        f"""
        CREATE TABLE exp_a01_raw_metrics AS
        WITH calendar_years(calendar_year) AS (VALUES {year_values}),
        a_indicators(indicator_id, value_offset) AS (VALUES {a_indicator_values})
        SELECT 'S' || security_index::VARCHAR AS security_id,
               printf('%04d-01-%02d', calendar_year, day_of_year) AS trading_date,
               ((calendar_year - 2016) * {days_per_year} + day_of_year)::BIGINT
                   AS observation_sequence,
               indicator_id,
               (((calendar_year - 2016) * {days_per_year} + day_of_year) / 100.0)
                   + value_offset AS raw_value,
               'valid' AS validity_status
        FROM range(0, {securities}) AS securities(security_index)
        CROSS JOIN calendar_years
        CROSS JOIN range(1, {days_per_year + 1}) AS days(day_of_year)
        CROSS JOIN a_indicators
        """
    )
    p.execute(
        f"""
        CREATE TABLE r0_t04_raw_metric_results AS
        WITH calendar_years(calendar_year) AS (VALUES {year_values}),
        pcvt_indicators(indicator_id, value_offset) AS
            (VALUES {pcvt_indicator_values})
        SELECT 'S' || security_index::VARCHAR AS security_id,
               printf('%04d-01-%02d', calendar_year, day_of_year) AS trading_date,
               indicator_id,
               (((calendar_year - 2016) * {days_per_year} + day_of_year) / 100.0)
                   + value_offset AS raw_value,
               'valid' AS validity_status
        FROM range(0, {securities}) AS securities(security_index)
        CROSS JOIN calendar_years
        CROSS JOIN range(1, {days_per_year + 1}) AS days(day_of_year)
        CROSS JOIN pcvt_indicators
        """
    )
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
        self.a_path, self.p_path = make_inputs(self.root, years=(2016,))

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
        a_path, p_path = make_inputs(
            self.root / "full_pair", years=tuple(range(2016, 2027))
        )
        a = duckdb.connect(str(a_path), read_only=True)
        p = duckdb.connect(str(p_path), read_only=True)
        p.execute(
            "ATTACH ? AS probe (READ_ONLY)", [str(self.p_path)]
        ) if False else None
        analysis = build_analysis(a, p, self.config, pcvt_path=p_path)
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
            [11, 24, 24, 264, 19200, 72, 12, 3],
        )
        self.assertEqual(
            len({row["security_id"] for row in analysis["pairwise_security"]}),
            800,
        )
        self.assertTrue(
            all(
                sum(row["pair_id"] == pair_id for row in analysis["pairwise_security"])
                == 800
                for pair_id in {row["pair_id"] for row in analysis["pairwise_security"]}
            )
        )
        self.assertTrue(
            all(
                sum(row["pair_id"] == pair_id for row in analysis["pairwise_year"])
                == 11
                for pair_id in {row["pair_id"] for row in analysis["pairwise_year"]}
            )
        )
        self.assertTrue(
            all(row["common_count"] > 0 for row in analysis["pairwise_year"])
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
        a_path, p_path = make_inputs(
            self.root / "full_tail", years=tuple(range(2016, 2027))
        )
        p = duckdb.connect(str(p_path))
        p.execute(
            "UPDATE r0_t04_raw_metric_results SET raw_value=1.0 WHERE indicator_id='P1_NATR14'"
        )
        p.close()
        a = duckdb.connect(str(a_path), read_only=True)
        p = duckdb.connect(str(p_path), read_only=True)
        analysis = build_analysis(a, p, self.config, pcvt_path=p_path)
        tail = next(
            row
            for row in analysis["tail_overlap"]
            if row["pair_id"] == "A1__P1_NATR14" and row["tail_fraction"] == 0.05
        )
        self.assertEqual(tail["pcvt_selected_count"], 8800)
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

    def test_security_registry_mismatch_fails_closed(self) -> None:
        p = duckdb.connect(str(self.p_path))
        p.execute("DELETE FROM r0_t04_raw_metric_results WHERE security_id='S799'")
        p.close()
        a = duckdb.connect(str(self.a_path), read_only=True)
        p = duckdb.connect(str(self.p_path), read_only=True)
        with self.assertRaisesRegex(
            LineageError,
            "(pcvt_security_registry_count_mismatch|cross_raw_security_registry_mismatch)",
        ):
            build_analysis(a, p, self.config, pcvt_path=self.p_path)
        a.close()
        p.close()

    def test_missing_pair_year_is_blocking_and_year_grid_is_preserved(self) -> None:
        a_path, p_path = make_inputs(
            self.root / "full_missing_year", years=tuple(range(2016, 2027))
        )
        p = duckdb.connect(str(p_path))
        p.execute(
            "DELETE FROM r0_t04_raw_metric_results WHERE indicator_id='P1_NATR14' AND trading_date LIKE '2017-%'"
        )
        p.close()
        a = duckdb.connect(str(a_path), read_only=True)
        p = duckdb.connect(str(p_path), read_only=True)
        analysis = build_analysis(a, p, self.config, pcvt_path=p_path)
        missing = next(
            row
            for row in analysis["pairwise_year"]
            if row["pair_id"] == "A1__P1_NATR14" and row["calendar_year"] == 2017
        )
        self.assertEqual(missing["common_count"], 0)
        self.assertEqual(len(analysis["pairwise_year"]), 264)
        anomaly = build_anomaly_scan(analysis, self.config, synthetic_fixture=False)
        self.assertEqual(anomaly["status"], "failed")
        self.assertIn(
            "accepted_year_missing:A1__P1_NATR14:2017",
            anomaly["blocking_anomalies"],
        )
        a.close()
        p.close()


if __name__ == "__main__":
    unittest.main()
