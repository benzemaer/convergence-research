from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t08_independent_validator import validate_run
from src.r2.r2_t08_r2_gate_r3_handoff import _version_rows

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads(
    (ROOT / "configs/r2/r2_t08_r2_gate_r3_handoff.v1.json").read_text(encoding="utf-8")
)


class T08ContractTests(unittest.TestCase):
    def test_two_frozen_versions_and_three_unselected_anchor_candidates(self) -> None:
        self.assertEqual(len(CONFIG["expected_frozen_versions"]), 2)
        self.assertEqual(
            [item["state_version_id"] for item in CONFIG["expected_frozen_versions"]],
            [
                "r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8",
                "r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8",
            ],
        )
        self.assertIsNone(CONFIG["release_anchor_obligation"]["selected_anchor"])
        self.assertEqual(len(CONFIG["release_anchor_obligation"]["candidates"]), 3)

    def test_zero_version_synthetic_is_not_fabricated(self) -> None:
        observed, mismatch = _version_rows(CONFIG, [])
        self.assertEqual(observed, {})
        self.assertGreater(mismatch, 0)

    def test_validator_does_not_import_generator(self) -> None:
        source = (ROOT / "src/r2/r2_t08_independent_validator.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("from src.r2.r2_t08_r2_gate_r3_handoff", source)


def _available_run() -> Path | None:
    candidates = sorted((ROOT / "data/generated/r2/r2_t08").glob("R2-T08-*"))
    return candidates[-1] if candidates else None


@unittest.skipUnless(
    _available_run() is not None, "formal T08 artifacts not present yet"
)
class T08MutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_run = _available_run()
        assert cls.source_run is not None

    def _mutated_run(self, filename: str, mutate) -> Path:
        temp_root = Path(tempfile.mkdtemp(prefix="r2_t08_mutation_"))
        self.addCleanup(shutil.rmtree, temp_root, ignore_errors=True)
        run = temp_root / self.source_run.name
        shutil.copytree(self.source_run, run)
        path = run / filename
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        return run

    def _assert_closed(self, filename: str, mutate) -> None:
        result = validate_run(self._mutated_run(filename, mutate), root=ROOT)
        self.assertEqual(result["status"], "failed")
        self.assertGreater(result["failure_count"], 0)

    def test_01_t07_final_manifest_binding_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_final_acceptance.json",
            lambda value: value["t07_final_freeze_manifest_ref"].update(
                {"committed_byte_sha256": "0" * 64}
            ),
        )

    def test_02_core_artifact_hash_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["state_version_registry_ref"].update(
                {"committed_byte_sha256": "1" * 64}
            ),
        )

    def test_03_t07_numeric_check_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_independent_validation.json",
            lambda value: value["checks"].update(
                {"t07_manifest_integrity_mismatch": 1}
            ),
        )

    def test_04_frozen_version_count_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_final_acceptance.json",
            lambda value: value.update({"frozen_version_count": 3}),
        )

    def test_05_version_id_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["frozen_versions"][0].update(
                {"state_version_id": "mutated_version"}
            ),
        )

    def test_06_w250_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["frozen_versions"][0].update({"W": 250}),
        )

    def test_07_shared_q_independent_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["strict_core_contract"].update(
                {"is_independent_state_version": True}
            ),
        )

    def test_08_canonical_hash_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["canonical_daily_state_ref"].update(
                {"stable_multiset_sha256": "2" * 64}
            ),
        )

    def test_09_event_zone_member_risk_set_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["qualified_event_risk_set_contract"].update(
                {"event_zone_member_is_not_a_substitute": False}
            ),
        )

    def test_10_strict_core_product_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["strict_core_contract"].update(
                {"is_independent_product": True}
            ),
        )

    def test_11_warning_deletion_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["warnings"].update({next(iter(value["warnings"])): []}),
        )

    def test_12_quality_break_release_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value["exit_quality_censor_contract"].update(
                {"quality_break_is_not_release": False}
            ),
        )

    def test_13_selected_anchor_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_release_anchor_obligation.json",
            lambda value: value.update({"selected_anchor": "finalized_zone"}),
        )

    def test_14_alternative_entrypoint_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_r3_handoff_manifest.json",
            lambda value: value.update({"alternative_entrypoints": ["other"]}),
        )

    def test_15_author_stage_gate_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_final_acceptance.json",
            lambda value: value.update({"R3_allowed_to_start": True}),
        )

    def test_16_committed_manifest_bytes_mutation(self) -> None:
        self._assert_closed(
            "r2_t08_output_manifest.json",
            lambda value: value["artifacts"][0].update({"sha256": "3" * 64}),
        )


if __name__ == "__main__":
    unittest.main()
