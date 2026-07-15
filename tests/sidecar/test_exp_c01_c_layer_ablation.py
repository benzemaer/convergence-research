from __future__ import annotations

import unittest

from src.sidecar.exp_c01_c_layer_ablation import (
    BASELINE_VARIANT,
    C1_ID,
    C1_VARIANT,
    C2_ID,
    C2_VARIANT,
    InputContractError,
    build_observations,
    build_profiles,
    normalize_indicator_rows,
)


def score_row(
    security_id: str,
    trading_date: str,
    indicator_id: str,
    score: float | None,
    *,
    eligible: bool = True,
    status: str = "valid",
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "trading_date": trading_date,
        "percentile_window_W": 120,
        "indicator_id": indicator_id,
        "score": score,
        "eligible": eligible,
        "validity_status": status,
    }


def pair(
    trading_date: str,
    c1: float | None,
    c2: float | None,
    *,
    c1_eligible: bool = True,
    c2_eligible: bool = True,
    c1_status: str = "valid",
    c2_status: str = "valid",
) -> list[dict[str, object]]:
    return [
        score_row(
            "000001.SZ",
            trading_date,
            C1_ID,
            c1,
            eligible=c1_eligible,
            status=c1_status,
        ),
        score_row(
            "000001.SZ",
            trading_date,
            C2_ID,
            c2,
            eligible=c2_eligible,
            status=c2_status,
        ),
    ]


class ExpC01CoreTest(unittest.TestCase):
    def test_baseline_mean_and_min_weak_rule(self) -> None:
        observations = build_observations(pair("2024-01-01", 0.90, 0.70))
        item = observations[0]
        self.assertTrue(item.baseline_active)
        self.assertTrue(item.c1_active)
        self.assertFalse(item.c2_active)

        observations = build_observations(pair("2024-01-01", 0.79, 0.81))
        self.assertTrue(observations[0].baseline_active)
        self.assertFalse(observations[0].c1_active)
        self.assertTrue(observations[0].c2_active)

    def test_single_indicator_true_while_baseline_false(self) -> None:
        c1_candidate = build_observations(pair("2024-01-01", 0.90, 0.50))[0]
        self.assertTrue(c1_candidate.c1_active)
        self.assertFalse(c1_candidate.baseline_active)

        c2_candidate = build_observations(pair("2024-01-01", 0.50, 0.90))[0]
        self.assertTrue(c2_candidate.c2_active)
        self.assertFalse(c2_candidate.baseline_active)

    def test_valid_false_is_not_unknown(self) -> None:
        item = build_observations(pair("2024-01-01", 0.79, 0.79))[0]
        self.assertTrue(item.pair_common_valid)
        self.assertFalse(item.c1_active)
        self.assertFalse(item.c2_active)

    def test_unknown_blocked_and_null_break_segments(self) -> None:
        rows = []
        rows.extend(pair("2024-01-01", 0.90, 0.90))
        rows.extend(
            pair(
                "2024-01-02",
                None,
                0.90,
                c1_eligible=False,
                c1_status="unknown",
            )
        )
        rows.extend(
            pair(
                "2024-01-03",
                None,
                0.90,
                c1_eligible=False,
                c1_status="blocked",
            )
        )
        rows.extend(pair("2024-01-04", 0.90, 0.90))
        profiles = build_profiles(rows)
        profile = profiles["variant_profile"][0]
        self.assertEqual(profile["eligible_row_count"], 2)
        self.assertEqual(profile["active_true_count"], 2)
        self.assertEqual(profile["segment_count"], 2)
        self.assertEqual(profile["segment_duration_sum"], 2)

    def test_overlap_and_segment_conservation(self) -> None:
        rows = []
        rows.extend(pair("2024-01-01", 0.90, 0.70))
        rows.extend(pair("2024-01-02", 0.90, 0.50))
        rows.extend(pair("2024-01-03", 0.50, 0.90))
        profiles = build_profiles(rows)
        for row in profiles["variant_profile"]:
            self.assertEqual(
                row["active_true_count"] + row["active_false_count"],
                row["eligible_row_count"],
            )
            self.assertEqual(row["segment_duration_sum"], row["active_true_count"])
            self.assertEqual(
                row["transition_count"],
                row["true_to_false_transition_count"]
                + row["false_to_true_transition_count"],
            )
        for row in profiles["overlap_profile"]:
            self.assertEqual(
                row["n11"] + row["n10"] + row["n01"] + row["n00"],
                row["common_valid_rows"],
            )

    def test_only_w120_and_q_twenty_config_are_accepted(self) -> None:
        for window in (250, 500):
            row = score_row("000001.SZ", "2024-01-01", C1_ID, 0.8)
            row["percentile_window_W"] = window
            with self.subTest(window=window), self.assertRaises(InputContractError):
                normalize_indicator_rows([row])

    def test_baseline_reconciliation_matches_and_catches_mutation(self) -> None:
        rows = pair("2024-01-01", 0.90, 0.70)
        dimension = [
            {
                "security_id": "000001.SZ",
                "trading_date": "2024-01-01",
                "percentile_window_W": 120,
                "dimension": "C",
                "score_dimension": 0.80,
                "score_dimension_min": 0.70,
                "eligible_dimension": True,
                "validity_status": "valid",
            }
        ]
        state = [
            {
                "security_id": "000001.SZ",
                "trading_date": "2024-01-01",
                "percentile_window_W": 120,
                "dimension": "C",
                "q": 0.20,
                "weak_delta": 0.10,
                "dimension_active_weak": True,
                "validity_status": "valid",
            }
        ]
        profiles = build_profiles(
            rows,
            dimension_score_rows=dimension,
            dimension_state_rows=state,
        )
        self.assertEqual(profiles["baseline_reconciliation"]["mismatch_total"], 0)
        dimension[0]["score_dimension_min"] = 0.69
        mutated = build_profiles(
            rows,
            dimension_score_rows=dimension,
            dimension_state_rows=state,
        )
        self.assertGreater(
            mutated["baseline_reconciliation"]["score_min_mismatch"],
            0,
        )

    def test_invalid_status_and_invalid_score_are_rejected(self) -> None:
        row = score_row("000001.SZ", "2024-01-01", C1_ID, 0.8, status="not_valid")
        with self.assertRaises(InputContractError):
            normalize_indicator_rows([row])

        row = score_row("000001.SZ", "2024-01-01", C1_ID, 0.8, eligible=False)
        with self.assertRaises(InputContractError):
            normalize_indicator_rows([row])

    def test_expected_variant_ids_are_present(self) -> None:
        profiles = build_profiles(pair("2024-01-01", 0.85, 0.85))
        self.assertEqual(
            {row["variant_id"] for row in profiles["variant_profile"]},
            {BASELINE_VARIANT, C1_VARIANT, C2_VARIANT},
        )


if __name__ == "__main__":
    unittest.main()
