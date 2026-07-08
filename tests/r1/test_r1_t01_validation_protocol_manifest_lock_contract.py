from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.validate_configs import CONFIGS
from src.r1.r1_t01_manifest_lock_validator import (
    R1T01ManifestLockValidationError,
    validate_r1_t01_manifest_lock,
)


class R1T01ValidationProtocolManifestLockContractTest(unittest.TestCase):
    def test_complete_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            result = validate_r1_t01_manifest_lock(root)
            self.assertEqual(result["validator_status"], "passed")

    def test_missing_r1_stage_doc_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            (
                root / "docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md"
            ).unlink()
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_missing_r1_config_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            (
                root / "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"
            ).unlink()
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_config_schema_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(root, lambda config: config.pop("locked_grid"))
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_missing_s_pct_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root,
                lambda config: config.__setitem__(
                    "state_lines",
                    [
                        line
                        for line in config["state_lines"]
                        if line["state_line"] != "S_PCT"
                    ],
                ),
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_missing_s_pcvt_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root,
                lambda config: config.__setitem__(
                    "state_lines",
                    [
                        line
                        for line in config["state_lines"]
                        if line["state_line"] != "S_PCVT"
                    ],
                ),
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_s_pcvt_only_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root,
                lambda config: config.__setitem__(
                    "state_lines",
                    [
                        line
                        for line in config["state_lines"]
                        if line["state_line"] == "S_PCVT"
                    ],
                ),
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_r2_decision_basis_must_be_confirmed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root, lambda config: config.__setitem__("r2_decision_basis", "raw")
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_baseline_optimization_claim_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root,
                lambda config: config["reference_config"].__setitem__(
                    "role", "optimized_best"
                ),
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_n_perm_must_be_2000(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(root, lambda config: config.__setitem__("N_perm", 999))
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_lag_set_must_be_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root, lambda config: config.__setitem__("lag_set", [1, 2, 3])
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_primary_null_model_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root,
                lambda config: config.__setitem__("primary_null_model", "bundle_shift"),
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_year_stability_required_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            _mutate_config(
                root,
                lambda config: config.__setitem__("year_stability_required", False),
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_forbidden_future_backtest_portfolio_trade_signal_blocks(self) -> None:
        for key in ("future_return", "backtest", "portfolio", "trade_signal"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_complete_fixture(root)
                _mutate_config(
                    root, lambda config, key=key: config.__setitem__(key, True)
                )
                with self.assertRaises(R1T01ManifestLockValidationError):
                    validate_r1_t01_manifest_lock(root)

    def test_readme_r1_t02_without_evidence_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            (
                root
                / (
                    "docs/evidence/r1/"
                    "R1-T01_validation_protocol_manifest_lock_evidence.md"
                )
            ).unlink()
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_thin_wrapper_with_data_logic_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_complete_fixture(root)
            (root / "scripts/r1/validate_r1_t01_manifest_lock.py").write_text(
                "import duckdb\n"
                "from src.r1.r1_t01_manifest_lock_validator_cli import main\n",
                encoding="utf-8",
            )
            with self.assertRaises(R1T01ManifestLockValidationError):
                validate_r1_t01_manifest_lock(root)

    def test_real_r1_config_passes_schema(self) -> None:
        schema = json.loads(
            Path(
                "schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json"
            ).read_text(encoding="utf-8")
        )
        config = json.loads(
            Path(
                "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)

    def test_validate_configs_includes_r1_config(self) -> None:
        expected = (
            Path("schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json"),
            Path("configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"),
        )
        normalized = tuple(
            (schema.relative_to(Path.cwd()), config.relative_to(Path.cwd()))
            for schema, config in CONFIGS
        )
        self.assertIn(expected, normalized)


def _write_complete_fixture(root: Path) -> None:
    for directory in (
        "configs/r1",
        "schemas/r1",
        "src/r1",
        "scripts/r1",
        "tests/r1",
        "docs/tasks",
        "docs/stages",
        "docs/evidence/r1",
        "docs/evidence/r0",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)
    _copy_repo_file(root, "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json")
    _copy_repo_file(
        root, "schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json"
    )
    _copy_repo_file(root, "docs/tasks/R1-T01_验证协议状态线假设与manifest锁定.md")
    _copy_repo_file(root, "docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md")
    _copy_repo_file(root, "scripts/r1/validate_r1_t01_manifest_lock.py")
    _write_readme(root)
    _write_r0_chain(root)
    _write_evidence(root)


def _copy_repo_file(root: Path, relative_path: str) -> None:
    source = Path(relative_path)
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _write_readme(root: Path) -> None:
    (root / "docs/tasks/README.md").write_text(
        "\n".join(
            (
                "current_stage: R1",
                "current_task: R1-T02 R0 产物接收、lineage 与无前视复检",
                "next_planned_task: R1-T03 27 组 W/q/K 全量轻量结构扫描",
                "`R1-T01` 验证协议、状态线假设与 manifest 锁定：completed via this PR",
            )
        ),
        encoding="utf-8",
    )


def _write_r0_chain(root: Path) -> None:
    names = (
        "R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md",
        "R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md",
        "R0-T10-03_r0_t06_nested_state_materialization_evidence.md",
        "R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md",
        "R0-T10-05_authorized_input_manifest_full_grid_evidence.md",
    )
    for name in names:
        (root / "docs/evidence/r0" / name).write_text(
            "`status`: completed\n", encoding="utf-8"
        )
    (
        root / "docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md"
    ).write_text(
        "\n".join(
            (
                "`task_id`: R0-T11",
                "`status`: completed",
                "`validator_status`: passed",
                "`R1_allowed_to_start`: true",
                "`R1_starting_task`: R1-T01",
            )
        ),
        encoding="utf-8",
    )


def _write_evidence(root: Path) -> None:
    fields = {
        "task_id": "R1-T01",
        "status": "completed",
        "run_id": "R1-T01-fixture",
        "code_commit": "fixture",
        "config_path": "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json",
        "config_sha256": _sha(
            root / "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"
        ),
        "schema_path": (
            "schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json"
        ),
        "schema_sha256": _sha(
            root / "schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json"
        ),
        "task_doc_path": "docs/tasks/R1-T01_验证协议状态线假设与manifest锁定.md",
        "task_doc_sha256": _sha(
            root / "docs/tasks/R1-T01_验证协议状态线假设与manifest锁定.md"
        ),
        "stage_doc_path": "docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md",
        "stage_doc_sha256": _sha(
            root / "docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md"
        ),
        "validator_command": "python -m src.r1.r1_t01_manifest_lock_validator_cli",
        "wrapper_validator_command": (
            "python scripts/r1/validate_r1_t01_manifest_lock.py"
        ),
        "validator_status": "passed",
        "state_lines_registered": "S_PCT,S_PCVT",
        "reference_config": "W250_q20_K3 reference_baseline",
        "all_27_configs_light_profile": "true",
        "raw_confirmed_mode": "dual_line",
        "r2_decision_basis": "confirmed_state",
        "primary_null_model": "P_fixed_independent_CTV_circular_shift",
        "N_perm": "2000",
        "lag_set": "[1,3,5,10,20]",
        "year_stability_required": "true",
        "future_labels_forbidden": "true",
        "decision_status_enum_registered": "true",
        "forbidden_input_check": "passed",
        "forbidden_output_check": "passed",
        "no_future_label_check": "passed",
        "no_backtest_check": "passed",
        "no_trading_signal_check": "passed",
        "no_parameter_optimization_claim_check": "passed",
        "manifest_contains_row_payload": "false",
        "summary_contains_row_payload": "false",
        "R1-T02_allowed_to_start": "true",
        "R2_allowed_to_start": "false",
    }
    (
        root / "docs/evidence/r1/R1-T01_validation_protocol_manifest_lock_evidence.md"
    ).write_text(
        "\n".join(f"`{key}`: {value}" for key, value in fields.items()),
        encoding="utf-8",
    )


def _mutate_config(root: Path, mutate: object) -> None:
    path = root / "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    mutate(config)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
