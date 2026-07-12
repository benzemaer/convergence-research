from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/r2/r2_t02_premerge_full_evidence.schema.json"
PROFILE_CONFIG = ROOT / "configs/ci/unittest_profiles.v1.json"
FORMAL_SURFACE = [
    "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v1.json",
    "src/r2/r2_t02_protocol_freeze.py",
    "src/r2/r2_t02_independent_validator.py",
    "src/r2/r2_t02_premerge_full_evidence.py",
    "schemas/r2/r2_t02_premerge_full_evidence.schema.json",
]


def build_evidence(
    profile_result_path: Path,
    output_path: Path,
    *,
    reviewed_head_sha: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    profile_result = _load_json(profile_result_path)
    profiles = _load_json(root / "configs/ci/unittest_profiles.v1.json")["profiles"]
    heavy_files = sorted(profiles["r0-heavy-premerge"].get("files", []))
    payload = {
        "task_id": "R2-T02",
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "pull_request_number": _int_env("PR_NUMBER"),
        "workflow_name": os.environ.get("GITHUB_WORKFLOW", ""),
        "workflow_event": os.environ.get("GITHUB_EVENT_NAME", ""),
        "workflow_run_id": _int_env("GITHUB_RUN_ID"),
        "workflow_attempt": _int_env("GITHUB_RUN_ATTEMPT"),
        "workflow_conclusion": "success"
        if profile_result["status"] == "passed"
        else "failed",
        "tested_head_sha": _git_sha(root),
        "reviewed_head_sha": reviewed_head_sha,
        "profile": profile_result["profile"],
        "status": profile_result["status"],
        "test_count": profile_result["test_count"],
        "unique_test_count": profile_result["unique_test_count"],
        "test_collection_sha256": profile_result["test_collection_sha256"],
        "failure_count": profile_result["failure_count"],
        "error_count": profile_result["error_count"],
        "skipped_count": profile_result["skipped_count"],
        "elapsed_seconds": profile_result["elapsed_seconds"],
        "heavy_profile": "r0-heavy-premerge",
        "heavy_test_file_set": heavy_files,
        "heavy_test_count": len(heavy_files),
        "completed_at_utc": profile_result["completed_at_utc"],
        "formal_surface_sha256": _formal_surface_sha256(root),
    }
    _validate(payload, root)
    if payload["tested_head_sha"] != payload["reviewed_head_sha"]:
        raise ValueError("tested_head_sha_must_equal_reviewed_head_sha")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def validate_final_gate(
    evidence_path: Path, *, reviewed_head_sha: str, root: Path = ROOT
) -> None:
    payload = _load_json(evidence_path)
    _validate(payload, root)
    errors = []
    if payload["tested_head_sha"] != reviewed_head_sha:
        errors.append("reviewed_head_mismatch")
    if payload["tested_head_sha"] != payload["reviewed_head_sha"]:
        errors.append("tested_reviewed_head_mismatch")
    if payload["status"] != "passed":
        errors.append("full_profile_not_passed")
    if payload["failure_count"] != 0 or payload["error_count"] != 0:
        errors.append("full_profile_failures_or_errors")
    if errors:
        raise ValueError(",".join(errors))


def _validate(payload: dict[str, Any], root: Path) -> None:
    schema = _load_json(root / "schemas/r2/r2_t02_premerge_full_evidence.schema.json")
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=str)
    if errors:
        raise ValueError(
            "; ".join(f"{error.json_path}:{error.message}" for error in errors)
        )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _int_env(name: str) -> int:
    value = os.environ.get(name, "0")
    return int(value) if value else 0


def _git_sha(root: Path) -> str:
    import subprocess

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _formal_surface_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for rel in sorted(FORMAL_SURFACE):
        path = root / rel
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or validate R2-T02 premerge evidence."
    )
    parser.add_argument("--profile-result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviewed-head-sha", required=True)
    parser.add_argument("--final-gate-validate", type=Path)
    args = parser.parse_args(argv)
    if args.final_gate_validate:
        validate_final_gate(
            args.final_gate_validate, reviewed_head_sha=args.reviewed_head_sha
        )
        return 0
    if not args.profile_result or not args.output:
        parser.error(
            "--profile-result and --output are required unless "
            "--final-gate-validate is used"
        )
    build_evidence(
        args.profile_result, args.output, reviewed_head_sha=args.reviewed_head_sha
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
