from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.r0.r0_t11_audit_validator import (
    R0T11AuditValidationError,
    validate_r0_t11_audit,
)


class R0T11AuditValidatorTest(unittest.TestCase):
    def test_complete_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            result = validate_r0_t11_audit(root)
            self.assertEqual(result["validator_status"], "passed")

    def test_missing_report_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            (root / "docs/reports/r0/R0_known_limitations.md").unlink()
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_missing_formal_evidence_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            (
                root
                / (
                    "docs/evidence/r0/"
                    "R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md"
                )
            ).unlink()
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_r0_t10_05_gate_missing_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            evidence = root / (
                "docs/evidence/r0/"
                "R0-T10-05_authorized_input_manifest_full_grid_evidence.md"
            )
            evidence.write_text(
                evidence.read_text(encoding="utf-8").replace(
                    "`R0-T11_allowed_to_start`: true",
                    "`R0-T11_allowed_to_start`: false",
                ),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_audit_report_missing_zero_interval_explanation_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            audit = root / "docs/reports/r0/R0_audit_report.md"
            audit.write_text(
                audit.read_text(encoding="utf-8").replace(
                    "no_confirmed_segments_in_r0_t07_input", "missing_reason"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_audit_report_missing_r1_allowed_gate_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            audit = root / "docs/reports/r0/R0_audit_report.md"
            audit.write_text(
                audit.read_text(encoding="utf-8").replace(
                    "R1_allowed_to_start: true", "R1_allowed_to_start: false"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_missing_two_stage_section_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            standard = root / "docs/03_可复现研究工程标准.md"
            standard.write_text(
                standard.read_text(encoding="utf-8").replace(
                    "### 12.2 两阶段推进", "### 12.2 missing"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_missing_evidence_minimum_section_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            standard = root / "docs/03_可复现研究工程标准.md"
            standard.write_text(
                standard.read_text(encoding="utf-8").replace(
                    "### 12.3 Evidence 最小字段", "### 12.3 missing"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_missing_r_stage_layering_section_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            standard = root / "docs/03_可复现研究工程标准.md"
            standard.write_text(
                standard.read_text(encoding="utf-8").replace(
                    "### 12.4 R阶段入口分层硬规则", "### 12.4 missing"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_missing_resume_done_failed_rules_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            standard = root / "docs/03_可复现研究工程标准.md"
            standard.write_text(
                standard.read_text(encoding="utf-8")
                .replace("DONE", "done_marker")
                .replace("FAILED", "failed_marker"),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_missing_duckdb_spawn_row_payload_rules_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            standard = root / "docs/03_可复现研究工程标准.md"
            standard.write_text(
                standard.read_text(encoding="utf-8")
                .replace("DuckDB", "database")
                .replace("spawn", "process_context")
                .replace("row payload", "row body"),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_audit_report_must_reference_engineering_standard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            audit = root / "docs/reports/r0/R0_audit_report.md"
            audit.write_text(
                audit.read_text(encoding="utf-8").replace("docs/03 §12", "docs/03"),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_handoff_must_reference_engineering_standard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            handoff = root / "docs/reports/r0/R0_r1_handoff.md"
            handoff.write_text(
                handoff.read_text(encoding="utf-8").replace("docs/03 §12", "docs/03"),
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_forbidden_affirmative_claim_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            report = root / "docs/reports/r0/R0_r1_handoff.md"
            report.write_text(
                report.read_text(encoding="utf-8") + "\nThis says backtest passed.\n",
                encoding="utf-8",
            )
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_readme_advanced_only_when_validator_evidence_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            (
                root / "docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md"
            ).unlink()
            with self.assertRaises(R0T11AuditValidationError):
                validate_r0_t11_audit(root)

    def test_thin_wrapper_remains_thin(self) -> None:
        wrapper = Path("scripts/r0/validate_r0_t11_audit.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from src.r0.r0_t11_audit_validator_cli import main", wrapper)
        forbidden = ("duckdb", "read_parquet", "read_json", "sha256_file")
        for marker in forbidden:
            self.assertNotIn(marker, wrapper)

    def test_real_engineering_standard_section_exists(self) -> None:
        text = Path("docs/03_可复现研究工程标准.md").read_text(encoding="utf-8")
        for heading in (
            "## 12. R阶段正式运行、物化与交接 PR 规范",
            "### 12.1 适用范围",
            "### 12.2 两阶段推进",
            "### 12.3 Evidence 最小字段",
            "### 12.4 R阶段入口分层硬规则",
            "### 12.5 Resume、失败与监控",
            "### 12.6 并发与 DuckDB 写入",
            "### 12.7 Validator、README gate 与下游授权",
        ):
            self.assertIn(heading, text)


def _write_complete_fixture(root: Path) -> None:
    for directory in (
        root / "docs/reports/r0",
        root / "docs/evidence/r0",
        root / "docs/tasks",
        root / "docs",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (root / "docs/03_可复现研究工程标准.md").write_text(
        _engineering_standard_fixture(), encoding="utf-8"
    )
    for name, gate in (
        ("R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md", ""),
        ("R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md", ""),
        ("R0-T10-03_r0_t06_nested_state_materialization_evidence.md", ""),
        ("R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md", ""),
    ):
        (root / "docs/evidence/r0" / name).write_text(
            f"`status`: completed\n{gate}\n", encoding="utf-8"
        )
    (
        root
        / "docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md"
    ).write_text(
        "\n".join(
            (
                "`status`: completed",
                "`validator_status`: passed",
                "`source_evidence_check`: passed",
                "`input_artifact_hash_check`: passed",
                "`synthetic_input_check`: passed",
                "`raw_external_source_check`: passed",
                "`full_code_commit_check`: passed",
                "`R0-T11_allowed_to_start`: true",
            )
        ),
        encoding="utf-8",
    )
    audit_text = "\n".join(
        (
            "R0_status: completed",
            "R1_allowed_to_start: true",
            "R1_starting_task: R1-T01",
            "no_confirmed_segments_in_r0_t07_input",
            "confirmed_interval_row_count_total: 0",
            "daily_confirmed_true_count_total: 0",
            "selected_config_count: 27",
            "failed_config_count: 0",
            "R0_W250_Q20_K3_WEAK_D010",
            "W=120/250/500",
            "q=0.10/0.20/0.30",
            "K=2/3/5",
            "weak_delta=0.10",
            "R_stage_formal_run_standard: docs/03 §12",
            "R1_must_follow_formal_run_standard: true",
        )
    )
    (root / "docs/reports/r0/R0_audit_report.md").write_text(
        audit_text, encoding="utf-8"
    )
    (root / "docs/reports/r0/R0_r1_handoff.md").write_text(
        "## R1工程执行约束\n"
        "R1 must follow docs/03 §12 with two-stage and evidence-bound gates.\n",
        encoding="utf-8",
    )
    for name in ("R0_evidence_index.md", "R0_known_limitations.md"):
        (root / "docs/reports/r0" / name).write_text(
            "allowed scope\n", encoding="utf-8"
        )
    (
        root / "docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md"
    ).write_text(
        "\n".join(
            (
                "`task_id`: R0-T11",
                "`status`: completed",
                "`validator_status`: passed",
                "`R0_status`: completed",
                "`R1_allowed_to_start`: true",
                "`R1_starting_task`: R1-T01",
                "`zero_interval_acknowledged`: true",
                "`no_future_label_check`: passed",
                "`no_backtest_check`: passed",
                "`no_trading_signal_check`: passed",
                "`no_parameter_optimization_claim_check`: passed",
                "`README_updated_to_R1`: true",
                "`downstream_gate_allowed`: true",
                "`r_stage_formal_run_standard_updated`: true",
                "`engineering_standard_path`: `docs/03_可复现研究工程标准.md`",
                "`engineering_standard_sha256`: `" + "b" * 64 + "`",
                "`r_stage_formal_run_standard_check`: passed",
                "`r1_formal_run_standard_gate`: passed",
                "`audit_report_sha256`: `" + "a" * 64 + "`",
            )
        ),
        encoding="utf-8",
    )
    (root / "docs/tasks/README.md").write_text(
        "\n".join(
            (
                "current_stage: R1",
                "current_task: R1-T01 状态存在性与频率轮廓",
                "next_planned_task: R1-T02 结构关系与协同约束检验",
                "`R0-T11` R0 审计报告与 R1 交接：completed via PR #74",
            )
        ),
        encoding="utf-8",
    )


def _engineering_standard_fixture() -> str:
    return "\n".join(
        (
            "## 12. R阶段正式运行、物化与交接 PR 规范",
            "### 12.1 适用范围",
            "formal evidence chain and README gate",
            "### 12.2 两阶段推进",
            "two-stage downstream_gate_allowed validator_status",
            "### 12.3 Evidence 最小字段",
            "full 40-char SHA row payload",
            "### 12.4 R阶段入口分层硬规则",
            "src/rN scripts/rN",
            "### 12.5 Resume、失败与监控",
            "DONE FAILED retry",
            "### 12.6 并发与 DuckDB 写入",
            "ProcessPoolExecutor spawn DuckDB read_parquet",
            "### 12.7 Validator、README gate 与下游授权",
            "README validator_status",
        )
    )


if __name__ == "__main__":
    unittest.main()
