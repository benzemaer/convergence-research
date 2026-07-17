# ruff: noqa: E501

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.sidecar.exp_a04_cross_layer_diagnostics_validator import (
    validate_authoritative_pcvt_registry,
    validate_authorized_manifest,
    validate_handoffs,
)

ROOT = Path(__file__).resolve().parents[2]


def synthetic_manifest(root: Path, *, extra: bool = False) -> Path:
    ids = [
        "exp_a03_accepted_result_handoff",
        "exp_a03_manifest",
        "exp_a03_validator_result",
        "exp_a03_anomaly_scan",
        "exp_a03_candidate_disposition",
        "exp_a01_raw_metrics",
        "exp_a04_pcvt_raw_accepted_handoff",
        "pcvt_raw_metrics",
        "pcvt_raw_acceptance_evidence",
        "pcvt_raw_validator_or_manifest_evidence",
    ]
    artifacts = {
        artifact_id: {
            "artifact_id": artifact_id,
            "artifact_kind": "handoff_json",
            "filename": artifact_id + ".json",
            "path": artifact_id + ".json",
            "path_policy": "synthetic_fixture",
            "sha256": "0" * 64,
        }
        for artifact_id in ids
    }
    if extra:
        artifacts["extra"] = copy.deepcopy(artifacts[ids[0]])
        artifacts["extra"]["artifact_id"] = "extra"
    payload = {
        "$schema": "../../schemas/sidecar/exp_a04_authorized_input_manifest.schema.json",
        "manifest_type": "exp_a04_synthetic_input_manifest",
        "manifest_version": "1.0.0",
        "task_id": "EXP-A04",
        "authorized_for_task": "EXP-A04",
        "formal_data_version": False,
        "authorization": {
            "status": "synthetic_fixture_only",
            "formal_run_allowed": False,
            "authorized_for_task": "EXP-A04",
            "authorization_scope": "EXP-A04 cross-layer diagnostics only",
            "evidence": "temporary test",
        },
        "input_artifacts": artifacts,
        "cross_artifact_bindings": {
            "a03_run_id": "EXP-A03-20260717T134059037Z",
            "a03_reviewed_implementation_sha": "dc4984138f440e28fb87fd0ee6366dd9280b9488",
            "a03_result_commit": "66a96f8fe7cf6cc1b3f2ccd98d6f89a5f1115094",
            "a03_quality_run_id": "29585252831",
            "a03_disposition_sha256": "0" * 64,
            "a03_candidate_set": ["A1", "A2", "A2b"],
            "a01_raw_sha256": "0" * 64,
            "a01_raw_row_count": 5253198,
            "a01_expected_key_count": 1751066,
            "a01_security_count": 800,
            "a01_date_min": "2016-01-04",
            "a01_date_max": "2026-06-30",
            "pcvt_source_task_id": "R0-T10-01",
            "pcvt_accepted_run_id": "R0-T10-01-20260708T1715Z",
            "pcvt_raw_sha256": "89ff2979f8e151c1611c0c61b1b547783f76a4ad94953c9252b0ecef98ed56a0",
            "pcvt_raw_row_count": 13846152,
            "pcvt_expected_key_count": 1730769,
            "pcvt_security_count": 800,
            "pcvt_date_min": "2016-01-04",
            "pcvt_date_max": "2026-06-30",
            "pcvt_table": "r0_t04_raw_metric_results",
            "pcvt_indicator_ids": [
                "P1_NATR14",
                "P2_LogRange20",
                "C1_LogMASpread_5_60",
                "C2_AdjVWAPSpread_5_60",
                "T1_ER20",
                "T2_AbsTrendT20",
                "V1_TurnoverShrink20_60",
                "V2_LogAmount20_base",
            ],
            "pcvt_layer_mapping": {
                "P1_NATR14": "P",
                "P2_LogRange20": "P",
                "C1_LogMASpread_5_60": "C",
                "C2_AdjVWAPSpread_5_60": "C",
                "T1_ER20": "T",
                "T2_AbsTrendT20": "T",
                "V1_TurnoverShrink20_60": "V",
                "V2_LogAmount20_base": "V",
            },
            "a04_reviewed_implementation_sha": "0" * 40,
        },
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
    return path


class ExpA04LineageTests(unittest.TestCase):
    def test_committed_handoffs_and_evidence_are_accepted(self) -> None:
        config = json.loads(
            (
                ROOT / "configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(validate_handoffs(ROOT, config), [])

    def test_pcvt_registry_is_rebuilt_from_authoritative_r0_contracts(self) -> None:
        config = json.loads(
            (
                ROOT / "configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(validate_authoritative_pcvt_registry(ROOT, config), [])
        mutated = copy.deepcopy(config)
        mutated["pcvt_indicator_registry"][0]["raw_metric_name"] = "wrong"
        self.assertIn(
            "authoritative_pcvt_registry_mismatch",
            validate_authoritative_pcvt_registry(ROOT, mutated),
        )

    def test_mutated_a03_handoff_fails_without_opening_raw(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            payload = json.loads(
                (
                    ROOT
                    / "data/generated/sidecar/exp_a03/exp_a03_accepted_result_handoff.json"
                ).read_text(encoding="utf-8")
            )
            payload["accepted_candidate_set_for_A04"] = ["A1"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            config = json.loads(
                (
                    ROOT / "configs/sidecar/exp_a04_cross_layer_diagnostics.v1.json"
                ).read_text(encoding="utf-8")
            )
            errors = validate_handoffs(ROOT, config, a03_path=path)
            self.assertTrue(errors)

    def test_manifest_is_exactly_ten_and_extra_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = synthetic_manifest(Path(td), extra=True)
            errors = validate_authorized_manifest(ROOT, path)
            self.assertIn("authorized_manifest_exact_ten_artifacts_mismatch", errors)

    def test_manifest_without_extra_artifact_passes_schema_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = synthetic_manifest(Path(td))
            self.assertEqual(validate_authorized_manifest(ROOT, path), [])


if __name__ == "__main__":
    unittest.main()
