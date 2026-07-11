from __future__ import annotations

import unittest
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE_SPEC = ROOT / "docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md"
TASK_01 = ROOT / "docs/tasks/R1-T14-01_层级q单变量响应诊断与候选提名.md"
TASK_02 = ROOT / "docs/tasks/R1-T14-02_层级q向量R0物化接收与正式结构复验.md"
README = ROOT / "docs/tasks/README.md"
R1_T09_RUN_DIR = ROOT / "data/generated/r1/r1_t09/R1-T09-20260710T1825Z"
R1_T09_RUN_TREE_SHA256 = (
    "6767614f868ceeaebcb282eecee582b6497e90ba8209c7dad0637081773b7937"
)

R1_T09_IMMUTABLE_HASHES = {
    "data/generated/r1/r1_t09/R1-T09-20260710T1825Z/r1_t09_experiment_summary.json": (
        "1802fb7a74f6642361fdf9d633b0658794896f49a5daf0ce0e03f50480cd0178"
    ),
    "data/generated/r1/r1_t09/R1-T09-20260710T1825Z/r1_t09_result_package.json": (
        "2f37610ba5c2d9b8dd95859cab3db888a1f748bffa5f30c2b87823b497371173"
    ),
    "data/generated/r1/r1_t09/R1-T09-20260710T1825Z/r1_t09_scientific_review.json": (
        "75d28376aa7f5b3dadd2b641430ebed432e3569754a56bdaca1675a250f2ef50"
    ),
    "docs/experiments/r1/R1-T09_年份稳定性与状态集中度检查_result_analysis.md": (
        "ca9c5ac88112bf3e6d6c734df6be404295e07c4254a61669d5337c73bc7cb7db"
    ),
    "docs/evidence/r1/R1-T09_年份稳定性与状态集中度检查_evidence.md": (
        "81bdf1f07e051f88f76731f0b2b10500b02bc04c4c8f966a41daf1fc974f7437"
    ),
    "docs/reviews/r1/R1-T09_年份稳定性与状态集中度检查_scientific_review.md": (
        "3beffd0eb1817cd2d067816fff38fa933e887f961fc8b38c71b1b17b5b4cf008"
    ),
}


class R1T14RouteContractTest(unittest.TestCase):
    def test_task_documents_exist_with_expected_identity(self) -> None:
        expected = {
            TASK_01: (
                "# R1-T14-01 层级 q 单变量响应诊断与候选提名",
                "`task_id`: R1-T14-01",
            ),
            TASK_02: (
                "# R1-T14-02 层级 q-vector R0 物化接收与正式结构复验",
                "`task_id`: R1-T14-02",
            ),
        }
        for path, markers in expected.items():
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, text)

    def test_stage_spec_freezes_the_branching_route(self) -> None:
        text = STAGE_SPEC.read_text(encoding="utf-8")
        self.assertIn(
            "R1-T09 → R1-T14-01 → R0 handoff → R1-T14-02 → R1-T10 → R2",
            text,
        )
        self.assertIn("no_q_decoupling_candidate", text)
        self.assertIn("T14-01 不产生 `freeze_candidate`", text)
        self.assertIn("不能直接放行 T14-02", text)
        for marker in (
            "initial_after_R1-T09",
            "no_q_decoupling_candidate:",
            "q_vector_materialization_request:",
            "R0_q_vector_materialization_final_gate:",
            "R0_q_vector_materialization_task_id: "
            "<bound concrete R0 task_id before final gate>",
        ):
            self.assertIn(marker, text)

    def test_t14_01_diagnostic_derivation_boundary_is_explicit(self) -> None:
        text = TASK_01.read_text(encoding="utf-8")
        stage = STAGE_SPEC.read_text(encoding="utf-8")
        for document in (text, stage):
            self.assertIn("diagnostic-only / non-authoritative", document)
            self.assertIn("r1_t14_01_diagnostic_only", document)
            self.assertIn("不得替代 R0 formal materialization", document)
            self.assertIn("重新计算 strict-past percentile score", document)
        self.assertIn("不得直接作为 R1-T14-02 或 R1-T10 输入", text)
        self.assertIn(
            "不得对未正式物化的 q 水平执行正式 R1-T08 global/nested null",
            text,
        )
        self.assertIn(
            "不产生正式 R1-T08 global/nested null gate evidence",
            text,
        )

    def test_t14_02_requires_r0_formal_materialization(self) -> None:
        task_01 = TASK_01.read_text(encoding="utf-8")
        text = TASK_02.read_text(encoding="utf-8")
        self.assertIn("T14-01 不得直接授权 T14-02", task_01)
        self.assertIn("R0_q_vector_materialization_status: completed", text)
        self.assertIn("R0_q_vector_materialization_task_id", text)
        self.assertIn("blocked_return_to_R0", text)
        self.assertIn("没有 R1-T14-01 `q_vector_materialization_request`", text)
        self.assertIn(
            "T14-01 的 `r1_t14_01_diagnostic_only` artifacts "
            "不得作为本 task 的 formal input",
            text,
        )

    def test_t14_02_is_same_sample_revalidation_with_selection_limitation(self) -> None:
        text = TASK_02.read_text(encoding="utf-8")
        stage = STAGE_SPEC.read_text(encoding="utf-8")
        for document in (text, stage):
            self.assertIn("same-sample formal", document)
            self.assertIn("不是独立 confirmatory test", document)
            self.assertIn("selection_path_not_independently_confirmed=true", document)
            self.assertIn("校正 T14-01", document)
        self.assertIn("只控制 T14-02 formal run 的冻结 family", text)
        self.assertIn("不得描述为独立 confirmation sample", text)

    def test_both_tasks_forbid_future_labels_and_direct_freeze(self) -> None:
        for path in (TASK_01, TASK_02):
            text = path.read_text(encoding="utf-8")
            self.assertIn("未来标签", text, path)
            self.assertRegex(text, r"不得.*冻结|不.*冻结")
            self.assertIn("R2", text)

    def test_both_tasks_require_artifact_analysis_and_anomaly_stop(self) -> None:
        for path in (TASK_01, TASK_02):
            text = path.read_text(encoding="utf-8")
            self.assertIn("读取实际结果 artifacts", text, path)
            self.assertIn("result analysis", text, path)
            self.assertIn("异常扫描", text, path)
            self.assertIn("必须停止下游推进", text, path)

    def test_readme_keeps_downstream_gates_closed(self) -> None:
        text = README.read_text(encoding="utf-8")
        current = text.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
        self.assertIn("current_stage: R0", current)
        self.assertIn("current_task: R0-T15 正式 q-vector 物化", current)
        self.assertIn(
            "next_planned_task: R1-T14-02 层级 q-vector R0 物化接收与正式结构复验",
            current,
        )
        self.assertIn(
            "R1-T14-01_decision_status: q_vector_materialization_request", current
        )
        self.assertIn("R1-T14-02_status: blocked_pending_R0", current)
        self.assertIn("R0_q_vector_materialization_request_status: approved", current)
        self.assertIn("R0_q_vector_materialization_task_id: R0-T15", current)
        self.assertIn("R0_q_vector_materialization_allowed_to_start: true", current)
        self.assertIn("R0_q_vector_materialization_status: authorized", current)
        self.assertIn("R1-T14-01_allowed_to_start: true", current)
        for task in ("R1-T14-02", "R1-T10", "R1-T11", "R1-T12", "R1-T13"):
            self.assertIn(f"{task}_allowed_to_start: false", current)
        self.assertIn("R2_allowed_to_start: false", current)
        for task in ("R1-T11", "R1-T12", "R1-T13"):
            self.assertRegex(text, rf"`{task}`.*optional / triggered")

    def test_readme_records_all_t14_branch_state_transitions(self) -> None:
        text = README.read_text(encoding="utf-8")
        for marker in (
            "若 T14-01 final gate 选择 `no_q_decoupling_candidate`",
            "R1-T14-01_decision_status: no_q_decoupling_candidate",
            "R1-T14-02_status: not_triggered",
            "若 T14-01 final gate 选择 `q_vector_materialization_request`",
            "R0_q_vector_materialization_request_status: approved",
            "R0_q_vector_materialization_task_id: "
            "<bound concrete R0 task_id before final gate>",
            "R1-T14-02_status: blocked_pending_R0",
            "R0 q-vector materialization final gate 通过后",
            "R0_q_vector_materialization_request_status: fulfilled",
            "R1-T14-02_status: authorized",
        ):
            self.assertIn(marker, text)

    def test_only_t14_01_implementation_exists_before_stacked_downstream(self) -> None:
        required_patterns = (
            "src/r1/r1_t14_01*",
            "scripts/r1/*r1_t14_01*",
            "configs/r1/r1_t14_01*",
            "schemas/r1/r1_t14_01*",
        )
        for pattern in required_patterns:
            self.assertTrue(list(ROOT.glob(pattern)), pattern)
        forbidden_patterns = (
            "src/r1/r1_t14_02*",
            "scripts/r1/*r1_t14_02*",
            "configs/r1/r1_t14_02*",
            "schemas/r1/r1_t14_02*",
            "src/r0/r0_t15*",
            "scripts/r0/*r0_t15*",
        )
        for pattern in forbidden_patterns:
            self.assertEqual(list(ROOT.glob(pattern)), [], pattern)

    def test_r1_t09_final_artifacts_and_reviews_are_immutable(self) -> None:
        tree_hash = sha256()
        for path in sorted(
            item for item in R1_T09_RUN_DIR.rglob("*") if item.is_file()
        ):
            relative_path = path.relative_to(R1_T09_RUN_DIR).as_posix()
            tree_hash.update(relative_path.encode("utf-8"))
            tree_hash.update(b"\0")
            tree_hash.update(path.read_bytes())
            tree_hash.update(b"\0")
        self.assertEqual(tree_hash.hexdigest(), R1_T09_RUN_TREE_SHA256)

        for relative_path, expected_hash in R1_T09_IMMUTABLE_HASHES.items():
            path = ROOT / relative_path
            self.assertTrue(path.is_file(), path)
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected_hash, path)


if __name__ == "__main__":
    unittest.main()
