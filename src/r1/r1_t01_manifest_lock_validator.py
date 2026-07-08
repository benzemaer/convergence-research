from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]

TASK_DOC = ROOT / "docs/tasks/R1-T01_验证协议状态线假设与manifest锁定.md"
STAGE_DOC = ROOT / "docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md"
CONFIG = ROOT / "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json"
SCHEMA = ROOT / "schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json"
EVIDENCE = (
    ROOT / "docs/evidence/r1/R1-T01_validation_protocol_manifest_lock_evidence.md"
)
README = ROOT / "docs/tasks/README.md"
WRAPPER = ROOT / "scripts/r1/validate_r1_t01_manifest_lock.py"
R0_HANDOFF_EVIDENCE = (
    ROOT / "docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md"
)

REQUIRED_FILES = (TASK_DOC, STAGE_DOC, CONFIG, SCHEMA, EVIDENCE, README, WRAPPER)
R0_EVIDENCE_CHAIN = (
    ROOT / "docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md",
    ROOT
    / "docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md",
    ROOT / "docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md",
    ROOT
    / (
        "docs/evidence/r0/"
        "R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md"
    ),
    ROOT / "docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md",
    R0_HANDOFF_EVIDENCE,
)
STAGE_REQUIRED_SNIPPETS = (
    "S_PCT",
    "S_PCVT",
    "raw/confirmed 双主线",
    "r2_decision_basis = confirmed_state",
    "confirmed_state",
    "year = YEAR(trading_date)",
    "P_fixed_independent_CTV_circular_shift",
    "N_perm = 2000",
    "lag_set = [1, 3, 5, 10, 20]",
)
TASK_REQUIRED_SNIPPETS = (
    "reference baseline",
    "不是 optimized / best / selected parameter",
    "不是默认最优参数",
)
FORBIDDEN_AFFIRMATIVE_PATTERNS = (
    r"\bstrategy (?:is )?validated\b",
    r"\btrading signal (?:is )?ready\b",
    r"\btrade signal generated\b",
    r"\bbacktest (?:is )?(?:completed|passed)\b",
    r"\bfuture return (?:was |is )?analy[sz]ed\b",
    r"\bparameter (?:is |was )?optimized\b",
    r"\bparameter optimized\b",
    r"\bR1 completed\b",
    r"\bR2 started\b",
    r"策略已验证",
    r"交易信号已(?:生成|就绪)",
    r"回测(?:已)?(?:通过|完成)",
    r"未来收益(?:已)?分析",
    r"参数(?:已)?优化",
)
FORBIDDEN_FIELDS = {
    "future_return",
    "return",
    "backtest",
    "portfolio",
    "trade_signal",
    "trading_signal",
}
ROW_PAYLOAD_MARKERS = (
    '"rows": [',
    "`rows`:",
    "row_payload_json",
    "row_json",
    "read_parquet",
    "DuckDB table payload",
    ".csv content",
    ".jsonl content",
)
WRAPPER_FORBIDDEN = (
    "duckdb",
    "read_parquet",
    "read_json",
    "sha256(",
    "sha256_file",
    "W250_q20_K3",
    "P_fixed_independent_CTV_circular_shift",
    "N_perm",
)


class R1T01ManifestLockValidationError(RuntimeError):
    pass


def validate_r1_t01_manifest_lock(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    paths = _paths(root)
    _check_required_files(paths, errors)

    config: dict[str, Any] = {}
    if paths["config"].exists() and paths["schema"].exists():
        config = _check_config_schema(paths["config"], paths["schema"], errors)
        _check_config_semantics(config, errors)

    _check_stage_doc(paths["stage_doc"], errors)
    _check_task_doc(paths["task_doc"], errors)
    _check_forbidden_claims(
        (
            paths["task_doc"],
            paths["stage_doc"],
            paths["config"],
            paths["evidence"],
        ),
        errors,
    )
    _check_r0_evidence_chain(paths["r0_chain"], errors)
    _check_readme_gate(paths["readme"], paths["evidence"], errors)
    _check_evidence(paths["evidence"], paths, errors)
    _check_thin_wrapper(paths["wrapper"], errors)

    result = {
        "validator_status": "passed" if not errors else "failed",
        "required_files_check": "passed"
        if all(path.exists() for path in paths["required_files"])
        else "blocked",
        "config_schema_check": "passed"
        if not any("config_schema" in error for error in errors)
        else "blocked",
        "protocol_semantics_check": "passed"
        if not any("protocol_semantics" in error for error in errors)
        else "blocked",
        "stage_doc_check": "passed"
        if not any("stage_doc" in error for error in errors)
        else "blocked",
        "task_doc_check": "passed"
        if not any("task_doc" in error for error in errors)
        else "blocked",
        "forbidden_claim_check": "passed"
        if not any("forbidden_affirmative_claim" in error for error in errors)
        else "blocked",
        "r0_evidence_chain_check": "passed"
        if not any("R0_evidence" in error for error in errors)
        else "blocked",
        "readme_gate_check": "passed"
        if not any("README" in error for error in errors)
        else "blocked",
        "evidence_payload_check": "passed"
        if not any("row_payload" in error for error in errors)
        else "blocked",
        "thin_wrapper_check": "passed"
        if not any("thin_wrapper" in error for error in errors)
        else "blocked",
        "errors": errors,
    }
    if errors:
        raise R1T01ManifestLockValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _paths(root: Path) -> dict[str, Any]:
    return {
        "task_doc": root / TASK_DOC.relative_to(ROOT),
        "stage_doc": root / STAGE_DOC.relative_to(ROOT),
        "config": root / CONFIG.relative_to(ROOT),
        "schema": root / SCHEMA.relative_to(ROOT),
        "evidence": root / EVIDENCE.relative_to(ROOT),
        "readme": root / README.relative_to(ROOT),
        "wrapper": root / WRAPPER.relative_to(ROOT),
        "r0_chain": tuple(root / path.relative_to(ROOT) for path in R0_EVIDENCE_CHAIN),
        "required_files": tuple(
            root / path.relative_to(ROOT) for path in REQUIRED_FILES
        ),
        "root": root,
    }


def _check_required_files(paths: dict[str, Any], errors: list[str]) -> None:
    for path in paths["required_files"]:
        if not path.exists():
            errors.append(f"required_file_missing:{_display_path(path)}")


def _check_config_schema(
    config_path: Path, schema_path: Path, errors: list[str]
) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        config = json.loads(config_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(config)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"config_schema_invalid:{exc}")
        return {}
    return config


def _check_config_semantics(config: dict[str, Any], errors: list[str]) -> None:
    if not config:
        return
    state_lines = [item.get("state_line") for item in config.get("state_lines", [])]
    if "S_PCT" not in state_lines:
        errors.append("protocol_semantics_missing:S_PCT")
    if "S_PCVT" not in state_lines:
        errors.append("protocol_semantics_missing:S_PCVT")
    if state_lines == ["S_PCVT"]:
        errors.append("protocol_semantics_invalid:S_PCVT_only")
    if config.get("r2_decision_basis") != "confirmed_state":
        errors.append("protocol_semantics_invalid:r2_decision_basis")
    reference = config.get("reference_config", {})
    if reference.get("role") != "reference_baseline":
        errors.append("protocol_semantics_invalid:reference_not_baseline")
    baseline_claim_text = " ".join(
        str(reference.get(key, "")) for key in ("config_id", "role")
    ).lower()
    if any(
        token in baseline_claim_text
        for token in ("optimized", "best", "selected_by_return")
    ):
        errors.append("protocol_semantics_invalid:baseline_optimization_claim")
    grid = config.get("locked_grid", {})
    if grid.get("W") != [120, 250, 500]:
        errors.append("protocol_semantics_invalid:W_grid")
    if grid.get("q") != [0.1, 0.2, 0.3]:
        errors.append("protocol_semantics_invalid:q_grid")
    if grid.get("K") != [2, 3, 5] or 1 in grid.get("K", []):
        errors.append("protocol_semantics_invalid:K_grid")
    expected = {
        "N_perm": 2000,
        "primary_null_model": "P_fixed_independent_CTV_circular_shift",
        "lag_set": [1, 3, 5, 10, 20],
        "year_stability_required": True,
        "future_labels_forbidden": True,
    }
    for key, value in expected.items():
        if config.get(key) != value:
            errors.append(f"protocol_semantics_invalid:{key}")
    downstream = config.get("downstream_authorization", {})
    if downstream.get("downstream_R2_allowed_to_start") is not False:
        errors.append("protocol_semantics_invalid:R2_allowed")
    forbidden_keys = _find_forbidden_fields(config)
    allowed = {"forbidden_outputs"}
    unexpected = sorted(key for key in forbidden_keys if key not in allowed)
    if unexpected:
        errors.append("protocol_semantics_forbidden_field:" + ",".join(unexpected))


def _check_stage_doc(path: Path, errors: list[str]) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for snippet in STAGE_REQUIRED_SNIPPETS:
        if snippet not in text:
            errors.append(f"stage_doc_missing:{snippet}")


def _check_task_doc(path: Path, errors: list[str]) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for snippet in TASK_REQUIRED_SNIPPETS:
        if snippet not in text:
            errors.append(f"task_doc_missing:{snippet}")


def _check_forbidden_claims(paths: tuple[Path, ...], errors: list[str]) -> None:
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if _is_forbidden_example_line(line):
                continue
            for pattern in FORBIDDEN_AFFIRMATIVE_PATTERNS:
                if not re.search(pattern, line, flags=re.IGNORECASE):
                    continue
                errors.append(
                    f"forbidden_affirmative_claim:{_display_path(path)}:{pattern}"
                )


def _check_r0_evidence_chain(paths: tuple[Path, ...], errors: list[str]) -> None:
    for path in paths:
        if not path.exists():
            errors.append(f"R0_evidence_missing:{_display_path(path)}")
    if not paths[-1].exists():
        return
    fields = _parse_evidence(paths[-1])
    expected = {
        "task_id": "R0-T11",
        "status": "completed",
        "validator_status": "passed",
        "R1_allowed_to_start": "true",
        "R1_starting_task": "R1-T01",
    }
    for key, value in expected.items():
        if fields.get(key) != value:
            errors.append(f"R0_evidence_gate_mismatch:{key}")


def _check_readme_gate(
    readme_path: Path, evidence_path: Path, errors: list[str]
) -> None:
    if not readme_path.exists():
        errors.append("README_missing")
        return
    text = readme_path.read_text(encoding="utf-8")
    advanced = (
        "current_stage: R1" in text
        and "current_task: R1-T02 R0 产物接收、lineage 与无前视复检" in text
        and "next_planned_task: R1-T03 27 组 W/q/K 全量轻量结构扫描" in text
    )
    if advanced and not evidence_path.exists():
        errors.append("README_advanced_without_R1-T01_evidence")
    if advanced and evidence_path.exists():
        fields = _parse_evidence(evidence_path)
        if fields.get("validator_status") != "passed":
            errors.append("README_advanced_without_validator_status_passed")
        if fields.get("R1-T02_allowed_to_start") != "true":
            errors.append("README_advanced_without_R1-T02_allowed")
    if not advanced:
        errors.append("README_not_advanced_to_R1-T02")


def _check_evidence(path: Path, paths: dict[str, Any], errors: list[str]) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    _check_no_row_payload(text, errors)
    fields = _parse_evidence(path)
    required = {
        "task_id": "R1-T01",
        "status": "completed",
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
    for key, expected in required.items():
        if fields.get(key) != expected:
            errors.append(f"evidence_field_mismatch:{key}")
    path_fields = {
        "config": "config_path",
        "schema": "schema_path",
        "task_doc": "task_doc_path",
        "stage_doc": "stage_doc_path",
    }
    for path_key, field in path_fields.items():
        expected_path = _display_path(paths[path_key], paths["root"])
        if fields.get(field) != expected_path:
            errors.append(f"evidence_path_mismatch:{field}")
        hash_field = field.replace("_path", "_sha256")
        if paths[path_key].exists() and fields.get(hash_field) != sha256_file(
            paths[path_key]
        ):
            errors.append(f"evidence_hash_mismatch:{hash_field}")


def _check_thin_wrapper(path: Path, errors: list[str]) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "from src.r1.r1_t01_manifest_lock_validator_cli import main" not in text:
        errors.append("thin_wrapper_missing_cli_import")
    lower_text = text.lower()
    for marker in WRAPPER_FORBIDDEN:
        if marker.lower() in lower_text:
            errors.append(f"thin_wrapper_forbidden_marker:{marker}")


def _check_no_row_payload(text: str, errors: list[str]) -> None:
    for marker in ROW_PAYLOAD_MARKERS:
        if marker in text:
            errors.append(f"row_payload_marker_forbidden:{marker}")


def _is_forbidden_example_line(line: str) -> bool:
    markers = (
        "forbidden affirmative claims",
        "禁止",
        "若",
        "不得",
        "非目标",
        "no_",
    )
    return any(marker in line for marker in markers)


def _find_forbidden_fields(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_FIELDS:
                found.add(key)
            found.update(_find_forbidden_fields(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_forbidden_fields(item))
    return found


def _contains_token(value: Any, token: str) -> bool:
    if isinstance(value, dict):
        return any(
            _contains_token(key, token) or _contains_token(item, token)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_token(item, token) for item in value)
    return token.lower() in str(value).lower()


def _parse_evidence(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    if not path.exists():
        return fields
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("`") or "`:" not in line:
            continue
        key_end = line.find("`:")
        key = line[1:key_end].strip()
        value = line[key_end + 2 :].strip().replace("`", "")
        fields.setdefault(key, value.strip())
    return fields


def _display_path(path: Path, root: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
