from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Callable

from src.r2.r2_t05_canonical_materialization import (
    R2T05Blocked,
    _check_freeze_plan,
    _check_startup,
)


class R2T05StartupGateMutationTest(unittest.TestCase):
    VERSION_A = {
        "state_version_id": "r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8",
        "source_candidate_cell_id": "r2_s_pct_w120_qt25_primary__d2__g1",
        "state_line": "S_PCT",
        "window_track_id": "W120",
        "W": 120,
        "K": 3,
        "qP": 0.2,
        "qC": 0.2,
        "qT": 0.25,
        "qV": 0.2,
        "d": 2,
        "g": 1,
        "strict_core_enabled": True,
        "strict_core_source_candidate_cell_id": "r2_s_pct_w120_q20_shared__d2__g1",
    }
    VERSION_B = {
        "state_version_id": "r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8",
        "source_candidate_cell_id": "r2_s_pcvt_w120_qv30_primary__d2__g1",
        "state_line": "S_PCVT",
        "window_track_id": "W120",
        "W": 120,
        "K": 3,
        "qP": 0.2,
        "qC": 0.2,
        "qT": 0.2,
        "qV": 0.3,
        "d": 2,
        "g": 1,
        "strict_core_enabled": True,
        "strict_core_source_candidate_cell_id": "r2_s_pcvt_w120_q20_shared__d2__g1",
    }

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            + b"\n"
        )

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    def _fixture(
        self,
        mutate_artifacts: Callable[[dict, dict, dict], None] | None = None,
        mutate_binding: Callable[[dict[str, dict]], None] | None = None,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, str, dict]:
        temp = tempfile.TemporaryDirectory()
        repo = Path(temp.name)
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.name", "R2 T05 mutation test")
        self._git(repo, "config", "user.email", "r2-t05-mutation@example.invalid")
        decision_rel = "data/generated/r2/r2_t04/r2_t04_freeze_decision.json"
        plan_rel = "data/generated/r2/r2_t04/r2_t04_freeze_plan_manifest.json"
        phase_b_rel = "data/generated/r2/r2_t04/r2_t04_phase_b_independent_validation.json"
        handoff_rel = "data/generated/r2/r2_t04/r2_t04_repository_final_gate_handoff.json"
        validation_rel = "data/generated/r2/r2_t04/r2_t04_repository_final_gate_handoff_validation.json"
        versions = [dict(self.VERSION_A), dict(self.VERSION_B)]
        expected_versions = [dict(version) for version in versions]
        decision_units = [
            {
                "decision_unit": "S_PCT×W120",
                "automatic_recommendation": "shared-a",
                "primary_candidate_cell_id": versions[0]["source_candidate_cell_id"],
                "shared_candidate_cell_id": versions[0]["strict_core_source_candidate_cell_id"],
                "primary_disposition": "selected",
                "selected_d": 2,
                "selected_g": 1,
                "strict_core_enabled": True,
                "shared_disposition": "retain_as_strict_core_only",
                "pair_disposition": "selected",
            },
            {
                "decision_unit": "S_PCVT×W120",
                "automatic_recommendation": "shared-b",
                "primary_candidate_cell_id": versions[1]["source_candidate_cell_id"],
                "shared_candidate_cell_id": versions[1]["strict_core_source_candidate_cell_id"],
                "primary_disposition": "selected",
                "selected_d": 2,
                "selected_g": 1,
                "strict_core_enabled": True,
                "shared_disposition": "retain_as_strict_core_only",
                "pair_disposition": "selected",
            },
            {
                "decision_unit": "S_PCT×W250",
                "automatic_recommendation": "unused",
                "primary_candidate_cell_id": "r2_s_pct_w250_primary",
                "shared_candidate_cell_id": "r2_s_pct_w250_shared",
                "primary_disposition": "rejected",
                "selected_d": None,
                "selected_g": None,
                "strict_core_enabled": False,
                "shared_disposition": "rejected",
                "pair_disposition": "reject_pair",
            },
            {
                "decision_unit": "S_PCVT×W250",
                "automatic_recommendation": "unused",
                "primary_candidate_cell_id": "r2_s_pcvt_w250_primary",
                "shared_candidate_cell_id": "r2_s_pcvt_w250_shared",
                "primary_disposition": "rejected",
                "selected_d": None,
                "selected_g": None,
                "strict_core_enabled": False,
                "shared_disposition": "rejected",
                "pair_disposition": "reject_pair",
            },
        ]
        decision = {
            "task_id": "R2-T04",
            "freeze_decision_status": "passed",
            "selected_version_count": 2,
            "strict_core_only_count": 2,
            "rejected_decision_unit_count": 2,
            "decision_units": decision_units,
        }
        plan_versions = [dict(version) for version in versions]
        for version in plan_versions:
            version["planned_state_version_id"] = version.pop("state_version_id")
        plan = {
            "task_id": "R2-T04",
            "freeze_plan_status": "passed",
            "planned_state_version_count": 2,
            "planned_versions": plan_versions,
        }
        phase_b = {
            "task_id": "R2-T04",
            "phase": "B",
            "status": "passed",
            "selected_cell_count": 2,
            "strict_core_only_count": 2,
            "rejected_pair_count": 2,
        }
        if mutate_artifacts:
            mutate_artifacts(decision, plan, phase_b)
        self._write_json(repo / decision_rel, decision)
        self._write_json(repo / plan_rel, plan)
        self._write_json(repo / phase_b_rel, phase_b)
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "bound T04 artifacts")
        source_commit = self._git(repo, "rev-parse", "HEAD")
        bindings: dict[str, dict] = {}
        for rel in (decision_rel, plan_rel, phase_b_rel):
            payload = subprocess.run(
                ["git", "show", f"{source_commit}:{rel}"],
                cwd=repo,
                check=True,
                capture_output=True,
            ).stdout
            bindings[rel] = {
                "source_commit": source_commit,
                "git_blob_sha": self._git(repo, "rev-parse", f"{source_commit}:{rel}"),
                "committed_byte_sha256": hashlib.sha256(payload).hexdigest(),
            }
        if mutate_binding:
            mutate_binding(bindings)
        handoff = {
            "task_id": "R2-T04",
            "scientific_review_status": "passed",
            "repository_final_gate_status": "passed",
            "formal_task_completed": True,
            "R2-T05_allowed_to_start": True,
            "R3_allowed_to_start": False,
            "committed_inputs": bindings,
        }
        validation = {
            "task_id": "R2-T04",
            "status": "passed",
            "scientific_review_status": "passed",
            "repository_final_gate_status": "passed",
            "formal_task_completed": True,
            "R2-T05_allowed_to_start": True,
            "R3_allowed_to_start": False,
        }
        self._write_json(repo / handoff_rel, handoff)
        self._write_json(repo / validation_rel, validation)
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-q", "-m", "publish handoff")
        head = self._git(repo, "rev-parse", "HEAD")
        config = {
            "startup": {
                "handoff_path": handoff_rel,
                "handoff_validation_path": validation_rel,
                "required": {
                    "scientific_review_status": "passed",
                    "repository_final_gate_status": "passed",
                    "formal_task_completed": True,
                    "R2-T05_allowed_to_start": True,
                    "R3_allowed_to_start": False,
                },
                "required_committed_inputs": [decision_rel, plan_rel, phase_b_rel],
            },
            "inputs": {
                "t04_freeze_decision_path": decision_rel,
                "t04_freeze_plan_path": plan_rel,
                "t04_phase_b_independent_validation_path": phase_b_rel,
            },
            "selected_versions": expected_versions,
        }
        return temp, repo, head, config

    def _assert_startup_blocked(
        self,
        mutate_artifacts: Callable[[dict, dict, dict], None] | None = None,
        mutate_binding: Callable[[dict[str, dict]], None] | None = None,
    ) -> None:
        temp, repo, head, config = self._fixture(mutate_artifacts, mutate_binding)
        try:
            with self.assertRaises(R2T05Blocked):
                startup = _check_startup(repo, head, config)
                _check_freeze_plan(config, startup)
        finally:
            temp.cleanup()

    def test_freeze_decision_counts_fail_closed(self) -> None:
        for field in ("selected_version_count", "strict_core_only_count", "rejected_decision_unit_count"):
            with self.subTest(field=field):
                self._assert_startup_blocked(
                    mutate_artifacts=lambda decision, plan, phase_b, field=field: decision.__setitem__(field, 99)
                )

    def test_freeze_plan_cardinality_fails_closed(self) -> None:
        self._assert_startup_blocked(
            mutate_artifacts=lambda decision, plan, phase_b: plan.__setitem__("planned_state_version_count", 3)
        )

    def test_version_id_mutation_fails_closed(self) -> None:
        self._assert_startup_blocked(
            mutate_artifacts=lambda decision, plan, phase_b: plan["planned_versions"][0].__setitem__("planned_state_version_id", "tampered")
        )

    def test_candidate_cell_mutation_fails_closed(self) -> None:
        self._assert_startup_blocked(
            mutate_artifacts=lambda decision, plan, phase_b: plan["planned_versions"][0].__setitem__("source_candidate_cell_id", "tampered")
        )

    def test_strict_core_pair_mutation_fails_closed(self) -> None:
        self._assert_startup_blocked(
            mutate_artifacts=lambda decision, plan, phase_b: plan["planned_versions"][0].__setitem__("strict_core_source_candidate_cell_id", "tampered")
        )

    def test_committed_binding_mutation_fails_closed(self) -> None:
        self._assert_startup_blocked(
            mutate_binding=lambda bindings: bindings[next(iter(bindings))].__setitem__("git_blob_sha", "0" * 40)
        )


if __name__ == "__main__":
    unittest.main()
