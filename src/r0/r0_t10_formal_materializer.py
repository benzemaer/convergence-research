from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.main_grid_materialization_runner import run_main_grid_materialization
from src.r0.r0_t09_input_manifest_builder import (
    BuildResult,
    R0T09InputManifestBuilderError,
    build_r0_t09_input_manifest,
)

R0_T10_FORMAL_MATERIALIZER_VERSION = "r0_t10_formal_materializer.v1"
MAX_WORKERS_DEFAULT = 2
MAX_WORKERS_UPPER_BOUND = 2
BASELINE_CANDIDATE_CONFIG_ID = "R0_W250_Q20_K3_WEAK_D010"
SUMMARY_FILENAME = "r0_t10_execution_summary.json"
UPSTREAM_SUMMARY_FILENAME = "upstream_generation_summary.json"
REQUIRED_UPSTREAM_KEYS = {
    "r0_t04": ("raw_metric_results",),
    "r0_t05": ("indicator_score_results", "dimension_score_results"),
    "r0_t06": ("nested_daily_state_results",),
    "r0_t07": ("daily_confirmation_results", "confirmed_interval_results"),
}
FORBIDDEN_FORMAL_PATH_PARTS = ("tests", "fixtures")
FORBIDDEN_FORMAL_PATH_TOKENS = (
    "synthetic",
    "smoke",
    "fixture",
    "contract_grid",
    "_contract_grid_payload",
)


class R0T10FormalMaterializationError(RuntimeError):
    def __init__(self, message: str, summary: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.summary = dict(summary or {})


@dataclass(frozen=True)
class R0T10Result:
    output_dir: Path
    summary_path: Path
    summary: dict[str, Any]


def run_r0_t10_formal_materialization(
    *,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    data_root: str | Path = "data",
    r0_t04_input: str | Path | None = None,
    r0_t05_input: str | Path | None = None,
    r0_t06_input: str | Path | None = None,
    r0_t07_input: str | Path | None = None,
    max_workers: int = MAX_WORKERS_DEFAULT,
    dry_run_r0_t09: bool = False,
    baseline_r0_t09: bool = False,
    full_grid_r0_t09: bool = False,
    resume: bool = True,
) -> R0T10Result:
    if max_workers < 1 or max_workers > MAX_WORKERS_UPPER_BOUND:
        raise R0T10FormalMaterializationError("max_workers must be between 1 and 2")

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    created_at = _utc_now()
    upstream_paths = {
        "r0_t04": Path(r0_t04_input) if r0_t04_input is not None else None,
        "r0_t05": Path(r0_t05_input) if r0_t05_input is not None else None,
        "r0_t06": Path(r0_t06_input) if r0_t06_input is not None else None,
        "r0_t07": Path(r0_t07_input) if r0_t07_input is not None else None,
    }

    if full_grid_r0_t09:
        summary = _base_summary(
            root=root,
            run_id=run_id,
            code_commit=code_commit,
            created_at=created_at,
            data_root=Path(data_root),
            upstream_paths=upstream_paths,
        )
        summary.update(
            {
                "status": "blocked",
                "reason_codes": ["full_grid_requires_second_submission"],
                "full_grid_status": "deferred_pending_review",
                "authorized_input_manifest_written": False,
            }
        )
        return _write_result(root, summary)

    readiness = evaluate_formal_upstream_readiness(
        data_root=data_root,
        upstream_paths=upstream_paths,
    )
    if readiness["validity_status"] == "blocked":
        summary = _base_summary(
            root=root,
            run_id=run_id,
            code_commit=code_commit,
            created_at=created_at,
            data_root=Path(data_root),
            upstream_paths=upstream_paths,
        )
        summary.update(
            {
                "status": "blocked",
                "reason_codes": readiness["reason_codes"],
                "readiness": readiness,
                "authorized_input_manifest_written": False,
                "full_grid_status": "not_started",
            }
        )
        _write_upstream_summary(root, summary)
        return _write_result(root, summary)

    manifest_result = _build_r0_t09_manifest(
        root=root,
        run_id=run_id,
        code_commit=code_commit,
        upstream_paths=upstream_paths,
    )
    dry_run_result: dict[str, Any] | None = None
    baseline_result: dict[str, Any] | None = None
    r0_t09_output_dir = root / "r0_t09_full_grid"

    if dry_run_r0_t09:
        dry_run_result = run_main_grid_materialization(
            input_manifest=manifest_result.manifest_path,
            output_dir=r0_t09_output_dir,
            max_workers=max_workers,
            dry_run=True,
            run_id=run_id,
            code_commit=code_commit,
        )
    if baseline_r0_t09:
        baseline_result = run_main_grid_materialization(
            input_manifest=manifest_result.manifest_path,
            output_dir=r0_t09_output_dir,
            max_workers=1,
            resume=resume,
            only_config=BASELINE_CANDIDATE_CONFIG_ID,
            run_id=run_id,
            code_commit=code_commit,
        )

    status = "pre_full_grid_completed"
    reason_codes = ["valid_no_blocker"]
    if baseline_result is not None and baseline_result.get("status") != "completed":
        status = "blocked"
        reason_codes = ["baseline_materialization_failed"]

    summary = _base_summary(
        root=root,
        run_id=run_id,
        code_commit=code_commit,
        created_at=created_at,
        data_root=Path(data_root),
        upstream_paths=upstream_paths,
    )
    summary.update(
        {
            "status": status,
            "reason_codes": reason_codes,
            "readiness": readiness,
            "upstream_artifacts": _portable_upstream_paths(upstream_paths),
            "upstream_artifacts_generated_by_r0_t10": False,
            "authorized_input_manifest_written": True,
            "authorized_input_manifest_path": _portable_path(
                manifest_result.manifest_path
            ),
            "r0_t09_input_generation_summary_path": _portable_path(
                manifest_result.summary_path
            ),
            "r0_t09_output_dir": _portable_path(r0_t09_output_dir),
            "r0_t09_output_manifest_path": _portable_path(
                r0_t09_output_dir / "manifest.json"
            )
            if baseline_result is not None
            else None,
            "dry_run_result": dry_run_result,
            "baseline_result": baseline_result,
            "full_grid_status": "deferred_pending_review",
            "full_grid_result": None,
            "audit_report_generated": False,
            "r1_handoff_generated": False,
        }
    )
    _write_upstream_summary(root, summary)
    return _write_result(root, summary)


def evaluate_formal_upstream_readiness(
    *,
    data_root: str | Path = "data",
    upstream_paths: Mapping[str, Path | None] | None = None,
) -> dict[str, Any]:
    upstream_paths = dict(upstream_paths or {})
    missing_inputs = [
        name for name in REQUIRED_UPSTREAM_KEYS if upstream_paths.get(name) is None
    ]
    reason_codes: list[str] = []
    if missing_inputs:
        reason_codes.append("formal_upstream_inputs_missing")

    path_checks = {
        name: _check_formal_upstream_path(path, REQUIRED_UPSTREAM_KEYS[name])
        for name, path in upstream_paths.items()
        if path is not None and name in REQUIRED_UPSTREAM_KEYS
    }
    for check in path_checks.values():
        reason_codes.extend(
            reason for reason in check["reason_codes"] if reason != "valid_no_blocker"
        )

    report_flags = discover_existing_r0_source_flags(data_root)
    if not upstream_paths and report_flags["blocking_flags"]:
        reason_codes.extend(report_flags["blocking_flags"])

    reason_codes = sorted(set(reason_codes))
    return {
        "validity_status": "blocked" if reason_codes else "valid",
        "reason_codes": reason_codes or ["valid_no_blocker"],
        "missing_upstream_inputs": missing_inputs,
        "path_checks": path_checks,
        "discovered_source_flags": report_flags,
    }


def discover_existing_r0_source_flags(data_root: str | Path) -> dict[str, Any]:
    root = Path(data_root)
    blocking: set[str] = set()
    inspected: list[str] = []
    if not root.exists():
        return {
            "data_root": _portable_path(root),
            "inspected_report_count": 0,
            "inspected_reports": [],
            "blocking_flags": ["formal_data_root_missing"],
        }

    for path in root.glob("generated/**/*.json"):
        if path.stat().st_size > 5_000_000:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        flags = _collect_gate_flags(payload)
        if not flags:
            continue
        inspected.append(_portable_path(path))
        if flags.get("formal_use_authorized") is False:
            blocking.add("formal_use_authorized_false")
        if flags.get("pcvt_values_generated") is False:
            blocking.add("pcvt_values_not_generated")
        if flags.get("r0_state_generated") is False:
            blocking.add("r0_state_not_generated")
    return {
        "data_root": _portable_path(root),
        "inspected_report_count": len(inspected),
        "inspected_reports": inspected[:50],
        "blocking_flags": sorted(blocking),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the R0-T10 formal materialization pre-full-grid gate."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--r0-t04-input", type=Path)
    parser.add_argument("--r0-t05-input", type=Path)
    parser.add_argument("--r0-t06-input", type=Path)
    parser.add_argument("--r0-t07-input", type=Path)
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS_DEFAULT)
    parser.add_argument("--dry-run-r0-t09", action="store_true")
    parser.add_argument("--baseline-r0-t09", action="store_true")
    parser.add_argument(
        "--full-grid-r0-t09",
        action="store_true",
        help="Blocked in this pre-full-grid submission; reserved for the second pass.",
    )
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_r0_t10_formal_materialization(
            output_dir=args.output_dir,
            run_id=args.run_id,
            code_commit=args.code_commit,
            data_root=args.data_root,
            r0_t04_input=args.r0_t04_input,
            r0_t05_input=args.r0_t05_input,
            r0_t06_input=args.r0_t06_input,
            r0_t07_input=args.r0_t07_input,
            max_workers=args.max_workers,
            dry_run_r0_t09=args.dry_run_r0_t09,
            baseline_r0_t09=args.baseline_r0_t09,
            full_grid_r0_t09=args.full_grid_r0_t09,
            resume=not args.no_resume,
        )
    except (R0T10FormalMaterializationError, R0T09InputManifestBuilderError) as exc:
        summary = getattr(exc, "summary", None)
        if summary:
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
        else:
            print(json.dumps({"status": "blocked", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result.summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.summary["status"] != "blocked" else 2


def _build_r0_t09_manifest(
    *,
    root: Path,
    run_id: str,
    code_commit: str,
    upstream_paths: Mapping[str, Path | None],
) -> BuildResult:
    return build_r0_t09_input_manifest(
        output_dir=root / "r0_t09_inputs",
        run_id=run_id,
        code_commit=code_commit,
        r0_t04_input=upstream_paths["r0_t04"],
        r0_t05_input=upstream_paths["r0_t05"],
        r0_t06_input=upstream_paths["r0_t06"],
        r0_t07_input=upstream_paths["r0_t07"],
    )


def _check_formal_upstream_path(
    path: Path, required_keys: Sequence[str]
) -> dict[str, Any]:
    reason_codes: list[str] = []
    normalized_parts = tuple(part.lower() for part in path.parts)
    name_lower = path.name.lower()
    if _contains_forbidden_path_part(normalized_parts):
        reason_codes.append("formal_input_fixture_path_forbidden")
    if any(token in name_lower for token in FORBIDDEN_FORMAL_PATH_TOKENS):
        reason_codes.append("formal_input_synthetic_path_forbidden")
    if not path.is_file():
        reason_codes.append("formal_upstream_input_file_missing")
        return {
            "path": _portable_path(path),
            "required_keys": list(required_keys),
            "reason_codes": reason_codes,
            "row_counts": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        reason_codes.append("formal_upstream_input_json_invalid")
        return {
            "path": _portable_path(path),
            "required_keys": list(required_keys),
            "reason_codes": reason_codes,
            "row_counts": {},
        }
    if not isinstance(payload, Mapping):
        reason_codes.append("formal_upstream_input_shape_invalid")
        return {
            "path": _portable_path(path),
            "required_keys": list(required_keys),
            "reason_codes": reason_codes,
            "row_counts": {},
        }
    row_counts: dict[str, int] = {}
    for key in required_keys:
        value = payload.get(key)
        if not isinstance(value, list):
            reason_codes.append(f"{key}_missing")
            continue
        row_counts[key] = len(value)
        if not value and key != "confirmed_interval_results":
            reason_codes.append(f"{key}_empty")
    if _collect_gate_flags(payload).get("synthetic_smoke_fixture") is True:
        reason_codes.append("formal_input_synthetic_payload_forbidden")
    return {
        "path": _portable_path(path),
        "required_keys": list(required_keys),
        "reason_codes": sorted(set(reason_codes)) or ["valid_no_blocker"],
        "row_counts": row_counts,
    }


def _contains_forbidden_path_part(parts: Sequence[str]) -> bool:
    for index in range(len(parts) - len(FORBIDDEN_FORMAL_PATH_PARTS) + 1):
        if parts[index : index + len(FORBIDDEN_FORMAL_PATH_PARTS)] == tuple(
            FORBIDDEN_FORMAL_PATH_PARTS
        ):
            return True
    return False


def _collect_gate_flags(payload: Any) -> dict[str, Any]:
    flags: dict[str, Any] = {}
    keys = {
        "formal_use_authorized",
        "pcvt_values_generated",
        "r0_state_generated",
        "synthetic_smoke_fixture",
    }
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key in keys and key not in flags:
                flags[key] = value
            flags.update(
                {k: v for k, v in _collect_gate_flags(value).items() if k not in flags}
            )
    elif isinstance(payload, list):
        for item in payload:
            flags.update(
                {k: v for k, v in _collect_gate_flags(item).items() if k not in flags}
            )
    return flags


def _base_summary(
    *,
    root: Path,
    run_id: str,
    code_commit: str,
    created_at: str,
    data_root: Path,
    upstream_paths: Mapping[str, Path | None],
) -> dict[str, Any]:
    return {
        "task_id": "R0-T10",
        "engine_version": R0_T10_FORMAL_MATERIALIZER_VERSION,
        "run_id": run_id,
        "code_commit": code_commit,
        "created_at": created_at,
        "output_dir": _portable_path(root),
        "data_root": _portable_path(data_root),
        "requested_upstream_inputs": _portable_upstream_paths(upstream_paths),
        "authorized_input_manifest_path": None,
        "r0_t09_input_generation_summary_path": None,
        "r0_t09_output_dir": None,
        "r0_t09_output_manifest_path": None,
        "dry_run_result": None,
        "baseline_result": None,
        "full_grid_result": None,
        "audit_report_generated": False,
        "r1_handoff_generated": False,
    }


def _write_upstream_summary(root: Path, summary: Mapping[str, Any]) -> None:
    upstream = root / "upstream"
    upstream.mkdir(parents=True, exist_ok=True)
    _write_json(upstream / UPSTREAM_SUMMARY_FILENAME, dict(summary))


def _write_result(root: Path, summary: dict[str, Any]) -> R0T10Result:
    summary_path = root / SUMMARY_FILENAME
    _write_json(summary_path, summary)
    return R0T10Result(output_dir=root, summary_path=summary_path, summary=summary)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _portable_upstream_paths(
    upstream_paths: Mapping[str, Path | None],
) -> dict[str, str | None]:
    return {
        key: _portable_path(path) if path is not None else None
        for key, path in upstream_paths.items()
    }


def _portable_path(path: Path) -> str:
    return path.as_posix()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
