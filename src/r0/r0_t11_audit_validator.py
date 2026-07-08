from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REPORT_FILES = (
    ROOT / "docs/reports/r0/R0_audit_report.md",
    ROOT / "docs/reports/r0/R0_r1_handoff.md",
    ROOT / "docs/reports/r0/R0_evidence_index.md",
    ROOT / "docs/reports/r0/R0_known_limitations.md",
)
FORMAL_EVIDENCE_FILES = (
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
)
R0_T11_EVIDENCE = (
    ROOT / "docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md"
)
README = ROOT / "docs/tasks/README.md"
ENGINEERING_STANDARD = ROOT / "docs/03_可复现研究工程标准.md"

REQUIRED_AUDIT_SNIPPETS = (
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
    "R_stage_formal_run_standard",
    "docs/03 §12",
    "R1_must_follow_formal_run_standard: true",
)
REQUIRED_HANDOFF_SNIPPETS = (
    "R1工程执行约束",
    "docs/03 §12",
    "evidence-bound",
)
REQUIRED_ENGINEERING_STANDARD_HEADINGS = (
    "## 12. R阶段正式运行、物化与交接 PR 规范",
    "### 12.1 适用范围",
    "### 12.2 两阶段推进",
    "### 12.3 Evidence 最小字段",
    "### 12.4 R阶段入口分层硬规则",
    "### 12.5 Resume、失败与监控",
    "### 12.6 并发与 DuckDB 写入",
    "### 12.7 Validator、README gate 与下游授权",
)
REQUIRED_ENGINEERING_STANDARD_KEYWORDS = (
    ("full 40-char SHA", "40 位完整"),
    ("row payload",),
    ("downstream_gate_allowed",),
    ("ProcessPoolExecutor",),
    ("spawn",),
    ("DuckDB",),
    ("read_parquet", "CTAS", "COPY"),
    ("DONE",),
    ("FAILED",),
    ("validator_status",),
    ("README",),
)
FORBIDDEN_AFFIRMATIVE_PATTERNS = (
    r"\bstrategy (?:is )?validated\b",
    r"\btrading signal (?:is )?ready\b",
    r"\btrade signal generated\b",
    r"\bbacktest (?:is )?(?:completed|passed)\b",
    r"\bfuture return (?:was |is )?analy[sz]ed\b",
    r"\brelease direction (?:is )?(?:known|determined)\b",
    r"\bportfolio (?:is )?ready\b",
    r"\boptimized parameter\b",
    r"\bparameter (?:is |was )?optimized\b",
    r"\bR1 (?:is )?completed\b",
    r"\bR[2-6][ -]T\d+ (?:is )?started\b",
)


class R0T11AuditValidationError(RuntimeError):
    pass


def validate_r0_t11_audit(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    report_paths = tuple(root / path.relative_to(ROOT) for path in REPORT_FILES)
    evidence_paths = tuple(
        root / path.relative_to(ROOT) for path in FORMAL_EVIDENCE_FILES
    )
    audit_evidence_path = root / R0_T11_EVIDENCE.relative_to(ROOT)
    readme_path = root / README.relative_to(ROOT)
    engineering_standard_path = root / ENGINEERING_STANDARD.relative_to(ROOT)

    _check_required_files(report_paths, "report", errors)
    _check_required_files(evidence_paths, "formal_evidence", errors)
    engineering_standard_sha256 = _check_engineering_standard(
        engineering_standard_path, errors
    )
    evidence = {
        path.name: _parse_evidence(path) for path in evidence_paths if path.exists()
    }
    _check_formal_evidence_gates(evidence, errors)

    if report_paths[0].exists():
        audit_text = report_paths[0].read_text(encoding="utf-8")
        for snippet in REQUIRED_AUDIT_SNIPPETS:
            if snippet not in audit_text:
                errors.append(f"audit_report_missing:{snippet}")
    if report_paths[1].exists():
        handoff_text = report_paths[1].read_text(encoding="utf-8")
        for snippet in REQUIRED_HANDOFF_SNIPPETS:
            if snippet not in handoff_text:
                errors.append(f"handoff_missing:{snippet}")
        if "two-stage" not in handoff_text and "两阶段" not in handoff_text:
            errors.append("handoff_missing:two-stage_or_两阶段")
    _check_forbidden_claims(report_paths, errors)
    _check_readme_gate(readme_path, audit_evidence_path, errors)
    if audit_evidence_path.exists():
        _check_t11_evidence(audit_evidence_path, errors)

    result = {
        "validator_status": "passed" if not errors else "failed",
        "required_report_files_check": "passed"
        if all(path.exists() for path in report_paths)
        else "blocked",
        "required_formal_evidence_check": "passed"
        if all(path.exists() for path in evidence_paths)
        else "blocked",
        "formal_evidence_gate_check": "passed"
        if not any(
            "formal_evidence" in error or "R0-T10-05" in error for error in errors
        )
        else "blocked",
        "audit_report_content_check": "passed"
        if not any("audit_report_missing" in error for error in errors)
        else "blocked",
        "handoff_content_check": "passed"
        if not any("handoff_missing" in error for error in errors)
        else "blocked",
        "r_stage_formal_run_standard_check": "passed"
        if not any("engineering_standard" in error for error in errors)
        else "blocked",
        "engineering_standard_sha256": engineering_standard_sha256,
        "forbidden_claim_check": "passed"
        if not any("forbidden_affirmative_claim" in error for error in errors)
        else "blocked",
        "readme_gate_check": "passed"
        if not any("README" in error for error in errors)
        else "blocked",
        "errors": errors,
    }
    if errors:
        raise R0T11AuditValidationError(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
    return result


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_required_files(
    paths: tuple[Path, ...], label: str, errors: list[str]
) -> None:
    for path in paths:
        if not path.exists():
            errors.append(f"{label}_missing:{_display_path(path)}")


def _check_formal_evidence_gates(
    evidence: dict[str, dict[str, str]], errors: list[str]
) -> None:
    for name, fields in evidence.items():
        if fields.get("status") != "completed":
            errors.append(f"formal_evidence_not_completed:{name}")
    t10_05 = evidence.get(
        "R0-T10-05_authorized_input_manifest_full_grid_evidence.md", {}
    )
    required = {
        "validator_status": "passed",
        "source_evidence_check": "passed",
        "input_artifact_hash_check": "passed",
        "synthetic_input_check": "passed",
        "raw_external_source_check": "passed",
        "full_code_commit_check": "passed",
        "R0-T11_allowed_to_start": "true",
    }
    for key, expected in required.items():
        if t10_05.get(key) != expected:
            errors.append(f"R0-T10-05_gate_missing:{key}")


def _check_engineering_standard(path: Path, errors: list[str]) -> str | None:
    if not path.exists():
        errors.append(f"engineering_standard_missing:{_display_path(path)}")
        return None
    text = path.read_text(encoding="utf-8")
    for heading in REQUIRED_ENGINEERING_STANDARD_HEADINGS:
        if heading not in text:
            errors.append(f"engineering_standard_heading_missing:{heading}")
    for alternatives in REQUIRED_ENGINEERING_STANDARD_KEYWORDS:
        if not any(keyword in text for keyword in alternatives):
            errors.append(
                "engineering_standard_keyword_missing:" + "|".join(alternatives)
            )
    return sha256_file(path)


def _check_forbidden_claims(paths: tuple[Path, ...], errors: list[str]) -> None:
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_AFFIRMATIVE_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                errors.append(
                    f"forbidden_affirmative_claim:{_display_path(path)}:{pattern}"
                )


def _check_readme_gate(
    readme_path: Path, audit_evidence_path: Path, errors: list[str]
) -> None:
    if not readme_path.exists():
        errors.append("README_missing")
        return
    text = readme_path.read_text(encoding="utf-8")
    advanced = (
        "current_stage: R1" in text
        and "R0-T11` R0 审计报告与 R1 交接：completed via PR #74" in text
    )
    if advanced and not audit_evidence_path.exists():
        errors.append("README_advanced_without_R0-T11_evidence")
    if not advanced:
        errors.append("README_not_advanced_to_R1")


def _check_t11_evidence(path: Path, errors: list[str]) -> None:
    fields = _parse_evidence(path)
    required = {
        "task_id": "R0-T11",
        "status": "completed",
        "validator_status": "passed",
        "R0_status": "completed",
        "R1_allowed_to_start": "true",
        "R1_starting_task": "R1-T01",
        "zero_interval_acknowledged": "true",
        "no_future_label_check": "passed",
        "no_backtest_check": "passed",
        "no_trading_signal_check": "passed",
        "no_parameter_optimization_claim_check": "passed",
        "README_updated_to_R1": "true",
        "downstream_gate_allowed": "true",
        "r_stage_formal_run_standard_updated": "true",
        "r_stage_formal_run_standard_check": "passed",
        "r1_formal_run_standard_gate": "passed",
    }
    for key, expected in required.items():
        if fields.get(key) != expected:
            errors.append(f"R0-T11_evidence_field_mismatch:{key}")
    for key, value in fields.items():
        if "sha256" in key or key.endswith("_hash"):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                errors.append(f"R0-T11_evidence_hash_invalid:{key}")
    if fields.get("engineering_standard_path") != "docs/03_可复现研究工程标准.md":
        errors.append("R0-T11_evidence_field_mismatch:engineering_standard_path")
    _check_no_row_payload(path.read_text(encoding="utf-8"), errors)


def _check_no_row_payload(text: str, errors: list[str]) -> None:
    forbidden = ('"rows": [', "`rows`:", "row_payload_json", "row_json")
    for marker in forbidden:
        if marker in text:
            errors.append(f"row_payload_marker_forbidden:{marker}")


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


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
