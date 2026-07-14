"""Independent analysis and final-manifest construction for R3-T01 results.

The analyzer is deliberately downstream of the runner and validator.  It reads
artifact bytes from disk and never calls the production construction module or
reuses the validator's in-memory replay objects.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import (
    TextContractError,
    formal_source_binding,
    read_csv,
    sha256_bytes,
    write_json,
    write_markdown,
)

ROOT = Path(__file__).resolve().parents[2]


class ResultAnalysisError(ValueError):
    """A fail-closed result-analysis or manifest error."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        detail = f":{message}" if message else ""
        super().__init__(f"{code}{detail}")


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultAnalysisError(
            "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", str(path)
        ) from exc


def _sha(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ResultAnalysisError(
            "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", str(path)
        ) from exc


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ResultAnalysisError("FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", str(path))


def _artifact_row_count(path: Path, kind: str, value: Any | None = None) -> int | None:
    if kind == "csv":
        return len(read_csv(path))
    if kind != "json" or value is None:
        return None
    if isinstance(value, dict) and isinstance(value.get("cases"), list):
        return len(value["cases"])
    if isinstance(value, list):
        return len(value)
    return None


def _schema_binding(name: str, root: Path) -> tuple[str, str] | None:
    mapping = {
        "r3_t01_protocol_registry.json": (
            "schemas/r3/r3_t01_protocol_registry.schema.json"
        ),
        "r3_t01_t0_transition_contract.json": (
            "schemas/r3/r3_t01_exit_attempt_contract.schema.json"
        ),
        "r3_t01_landmark_horizon_contract.json": (
            "schemas/r3/r3_t01_landmark_horizon_contract.schema.json"
        ),
        "r3_t01_sample_split_contract.json": (
            "schemas/r3/r3_t01_sample_split_contract.schema.json"
        ),
    }
    relative = mapping.get(name)
    if relative is None:
        return None
    path = root / relative
    _require_file(path)
    return relative, _sha(path)


def _public_forbidden_fields(config: dict[str, Any]) -> tuple[str, ...]:
    del config
    return (
        "component_qualification_" + "available_time",
        "g_used_as_of_exit",
        "daily.available_time",
        "evaluation_time",
        "raw_false_gap_ordinal_as_of",
        "raw_false_gap_count_as_of",
    )


def _scan_pathologies(
    config: dict[str, Any],
    production: dict[str, Any],
    independent: dict[str, Any],
    mutations: list[dict[str, str]],
    upstream: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cases = production.get("cases", [])
    attempts = [
        attempt for case in cases for attempt in case.get("actual_attempts", [])
    ]
    if cases and not attempts:
        findings.append({"code": "ALL_CASES_ZERO_ATTEMPTS", "message": "all cases"})
    ordinals = [attempt.get("exit_attempt_ordinal") for attempt in attempts]
    if ordinals and all(value == 1 for value in ordinals):
        findings.append(
            {"code": "ALL_ATTEMPT_ORDINALS_ONE", "message": "attempt ordinals"}
        )
    divergences = [
        attempt
        for attempt in attempts
        if attempt.get("component_count_as_of_exit")
        != attempt.get("source_component_ordinal")
    ]
    if attempts and not divergences:
        findings.append(
            {"code": "COMPONENT_COUNT_ORDINALS_IDENTICAL", "message": "all attempts"}
        )
    landmark_dates: list[str] = []
    horizon_dates: dict[str, list[str]] = {
        key: [] for key in ("H5", "H10", "H20", "H30")
    }
    for case in cases:
        for landmark in case.get("landmarks", {}).values():
            for key in ("T1", "T2"):
                if landmark.get(key, {}).get("available"):
                    date = landmark[key].get("trade_date")
                    if date is not None:
                        landmark_dates.append(str(date))
            for key in horizon_dates:
                if landmark.get(key, {}).get("available"):
                    date = landmark[key].get("trade_date")
                    if date is not None:
                        horizon_dates[key].append(str(date))
            if (
                landmark.get("state_version_id") is None
                or landmark.get("security_id") is None
            ):
                findings.append(
                    {"code": "LANDMARK_GROUP_BINDING_MISSING", "message": "landmark"}
                )
    if landmark_dates and len(set(landmark_dates)) == 1:
        findings.append(
            {"code": "ALL_LANDMARKS_SAME_DATE", "message": landmark_dates[0]}
        )
    if all(horizon_dates[key] for key in horizon_dates):
        if len({tuple(horizon_dates[key]) for key in horizon_dates}) == 1:
            findings.append({"code": "HORIZONS_IDENTICAL", "message": "H5/H10/H20/H30"})
    for case in cases:
        attempts_by_id = {
            str(attempt.get("exit_attempt_id")): attempt
            for attempt in case.get("actual_attempts", [])
        }
        for attempt_id, landmark in case.get("landmarks", {}).items():
            attempt = attempts_by_id.get(str(attempt_id), {})
            if landmark.get("state_version_id") != attempt.get(
                "state_version_id"
            ) or landmark.get("security_id") != attempt.get("security_id"):
                findings.append(
                    {
                        "code": "LANDMARK_CROSS_GROUP_CONTAMINATION",
                        "message": str(attempt_id),
                    }
                )
            if any(
                landmark.get(key) is not None
                and landmark.get(key, {}).get("available")
                and landmark.get(key, {}).get("trade_date") <= landmark.get("t0_date")
                for key in ("T1", "T2", "H5", "H10", "H20", "H30")
            ):
                findings.append(
                    {"code": "LANDMARK_NOT_AFTER_T0", "message": str(attempt_id)}
                )
    if independent.get("cases") != cases:
        findings.append(
            {"code": "PRODUCTION_INDEPENDENT_REPLAY_MISMATCH", "message": "cases"}
        )
    if not mutations:
        findings.append(
            {"code": "MUTATION_NOT_EXECUTED", "message": "mutation file empty"}
        )
    elif len({row.get("actual_error_codes") for row in mutations}) == 1:
        findings.append(
            {
                "code": "MUTATION_GENERIC_ERROR_COLLAPSE",
                "message": "all mutation results",
            }
        )
    if upstream.get("reviewed_implementation_sha") != upstream.get(
        "formal_execution_sha"
    ):
        findings.append(
            {
                "code": "IMPLEMENTATION_SHA_BINDING_MISMATCH",
                "message": "upstream binding",
            }
        )
    expected_upstream = {
        (item.get("path"), item.get("committed_byte_sha256"))
        for item in config.get("upstream_binding", {}).get("required_artifacts", [])
    }
    actual_upstream = {
        (item.get("path"), item.get("committed_byte_sha256", item.get("sha256")))
        for item in upstream.get("required_artifacts", [])
    }
    if expected_upstream != actual_upstream:
        findings.append(
            {
                "code": "UPSTREAM_BINDING_CONFIG_MISMATCH",
                "message": "required artifacts",
            }
        )
    serialized_config = json.dumps(config, ensure_ascii=False, sort_keys=True)
    for forbidden in _public_forbidden_fields(config):
        if forbidden in serialized_config:
            findings.append(
                {"code": "NON_PUBLIC_CANONICAL_FIELD_REFERENCE", "message": forbidden}
            )
    return findings


def _metrics(
    config: dict[str, Any],
    production: dict[str, Any],
    independent: dict[str, Any],
    mutations: list[dict[str, str]],
    anomalies: dict[str, Any],
) -> dict[str, Any]:
    cases = production.get("cases", [])
    attempts = [
        attempt for case in cases for attempt in case.get("actual_attempts", [])
    ]
    ids = [attempt.get("exit_attempt_id") for attempt in attempts]
    ordinals_by_event: dict[tuple[str, str], list[int]] = {}
    for attempt in attempts:
        key = (str(attempt.get("state_version_id")), str(attempt.get("event_id")))
        ordinals_by_event.setdefault(key, []).append(
            int(attempt.get("exit_attempt_ordinal", -1))
        )
    ordinal_conservation = all(
        sorted(values) == list(range(1, len(values) + 1))
        for values in ordinals_by_event.values()
    )
    landmark_counts = {
        key: sum(
            bool(landmark.get(key, {}).get("available"))
            for case in cases
            for landmark in case.get("landmarks", {}).values()
        )
        for key in ("T1", "T2", "H5", "H10", "H20", "H30")
    }
    mutation_passed = sum(row.get("status") == "passed" for row in mutations)
    return {
        "contract_artifact_count": len(
            config.get("output_contract", {}).get("formal_artifacts", [])
        ),
        "synthetic_case_count": len(cases),
        "attempt_count": len(attempts),
        "attempt_count_by_case": {
            case.get("case_id"): len(case.get("actual_attempts", [])) for case in cases
        },
        "zero_attempt_negative_case_count": sum(
            not case.get("actual_attempts") for case in cases
        ),
        "multi_attempt_case_count": sum(
            len(case.get("actual_attempts", [])) > 1 for case in cases
        ),
        "unqualified_reentry_case_count": sum(
            any(
                attempt.get("unqualified_reentry")
                for attempt in case.get("actual_attempts", [])
            )
            for case in cases
        ),
        "id_uniqueness": len(ids) == len(set(ids)),
        "ordinal_conservation": ordinal_conservation,
        "component_count_ordinal_divergence_count": sum(
            attempt.get("component_count_as_of_exit")
            != attempt.get("source_component_ordinal")
            for attempt in attempts
        ),
        "landmark_availability_counts": landmark_counts,
        "mutation_passed_count": mutation_passed,
        "mutation_count": len(mutations),
        "anomaly_count": int(anomalies.get("anomaly_count", 0)),
        "schema_count": len(config.get("schema_registry", [])),
        "production_independent_mismatch_count": int(
            production.get("cases") != independent.get("cases")
        ),
        "real_database_opened": False,
    }


def _manifest_artifacts(
    run_dir: Path, config: dict[str, Any], root: Path
) -> list[dict[str, Any]]:
    declarations = {
        item["filename"]: item for item in config["output_contract"]["formal_artifacts"]
    }
    artifacts: list[dict[str, Any]] = []
    for name in sorted(declarations):
        if name == "r3_t01_manifest.json":
            continue
        path = run_dir / name
        _require_file(path)
        kind = declarations[name]["kind"]
        value = _load_json(path) if kind == "json" else None
        item: dict[str, Any] = {
            "path": name,
            "artifact_owner": declarations[name]["artifact_owner"],
            "artifact_sha256": _sha(path),
            "size_bytes": path.stat().st_size,
            "kind": kind,
            "row_count": _artifact_row_count(path, kind, value),
        }
        schema = _schema_binding(name, root)
        if schema is not None:
            item["schema_path"], item["schema_sha256"] = schema
        artifacts.append(item)
    return artifacts


def _git_blob_sha(root: Path, source_commit: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{source_commit}:{path}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return sha256_bytes(result.stdout) if result.returncode == 0 else None


def _source_binding(path: Path, source_commit: str, root: Path) -> dict[str, Any]:
    """Bind formal inputs to committed Git bytes; retain a non-formal test fallback."""

    relative = _relative(path, root)
    is_commit = len(source_commit) == 40 and all(
        character in "0123456789abcdef" for character in source_commit.lower()
    )
    if not is_commit:
        return {
            "path": relative,
            "sha256": _sha(path),
            "size_bytes": path.stat().st_size,
            "lineage_status": "non_formal_local_snapshot",
        }
    try:
        binding = formal_source_binding(path, source_commit, root=root)
    except (OSError, TextContractError, subprocess.CalledProcessError) as exc:
        raise ResultAnalysisError("FORMAL_SOURCE_BINDING_INVALID", str(exc)) from exc
    return {
        "path": binding["path"],
        "sha256": binding["committed_byte_sha256"],
        "size_bytes": path.stat().st_size,
        "source_commit": binding["source_commit"],
        "git_blob_sha": binding["git_blob_sha"],
        "committed_byte_sha256": binding["committed_byte_sha256"],
        "normalized_text_sha256": binding["normalized_text_sha256"],
        "encoding": binding["encoding"],
        "line_ending": binding["line_ending"],
        "bom": binding["bom"],
        "terminal_lf_count": binding["terminal_lf_count"],
    }


def analyze_run_dir(
    run_dir: Path,
    config_path: Path,
    fixture_path: Path,
    *,
    reviewed_implementation_sha: str,
    formal_execution_sha: str,
    root: Path = ROOT,
) -> Path:
    """Reread actual validated artifacts, write analysis, then write manifest last."""

    run_dir = run_dir if run_dir.is_absolute() else root / run_dir
    config_path = config_path if config_path.is_absolute() else root / config_path
    fixture_path = fixture_path if fixture_path.is_absolute() else root / fixture_path
    manifest_path = run_dir / "r3_t01_manifest.json"
    if manifest_path.exists():
        raise ResultAnalysisError("MANIFEST_ALREADY_EXISTS", manifest_path.name)
    analysis_path = run_dir / "r3_t01_result_analysis.md"
    if analysis_path.exists():
        raise ResultAnalysisError("RESULT_ANALYSIS_ALREADY_EXISTS", analysis_path.name)
    config = _load_json(config_path)
    _load_json(fixture_path)
    validator = _load_json(run_dir / "r3_t01_validator_result.json")
    if validator.get("status") != "passed":
        raise ResultAnalysisError("VALIDATOR_NOT_PASSED")
    production = _load_json(run_dir / "r3_t01_production_synthetic_results.json")
    independent = _load_json(run_dir / "r3_t01_independent_replay_results.json")
    mutations = read_csv(run_dir / "r3_t01_mutation_results.csv")
    anomalies = _load_json(run_dir / "r3_t01_anomaly_scan.json")
    upstream = _load_json(run_dir / "r3_t01_upstream_binding.json")
    if upstream.get("reviewed_implementation_sha") != reviewed_implementation_sha:
        raise ResultAnalysisError("IMPLEMENTATION_SHA_BINDING_MISMATCH", "reviewed")
    if upstream.get("formal_execution_sha") != formal_execution_sha:
        raise ResultAnalysisError("IMPLEMENTATION_SHA_BINDING_MISMATCH", "formal")
    if anomalies.get("status") != "complete":
        raise ResultAnalysisError("PENDING_FORMAL_ARTIFACT", "anomaly_scan")
    if not isinstance(independent.get("cases"), list):
        raise ResultAnalysisError(
            "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", "independent"
        )
    findings = _scan_pathologies(config, production, independent, mutations, upstream)
    metrics = _metrics(config, production, independent, mutations, anomalies)
    artifact_declarations = config["output_contract"]["formal_artifacts"]
    landmark_summary = json.dumps(
        metrics["landmark_availability_counts"],
        ensure_ascii=False,
        sort_keys=True,
    )
    markdown = "\n".join(
        [
            "# R3-T01 result analysis",
            "",
            "## Actual run and scope",
            "",
            (
                f"The analyzer reread {len(artifact_declarations)} declared artifacts "
                f"from `{run_dir.name}` after the independent validator passed. "
                "It did not open the canonical database; the run is synthetic-only."
            ),
            (
                f"Implementation SHA: `{reviewed_implementation_sha}`. "
                f"Formal execution SHA: `{formal_execution_sha}`."
            ),
            "",
            "## Contract and independent replay",
            "",
            (
                f"The run contains {metrics['synthetic_case_count']} synthetic cases "
                f"and {metrics['attempt_count']} natural exit attempts. "
                f"ID uniqueness={metrics['id_uniqueness']}; "
                f"ordinal conservation={metrics['ordinal_conservation']}; "
                "production/independent case equality="
                f"{production.get('cases') == independent.get('cases')}."
            ),
            (
                f"Landmark availability: {landmark_summary}. "
                f"Mutation results passed: {metrics['mutation_passed_count']}/"
                f"{metrics['mutation_count']}."
            ),
            "",
            "## Anomaly scan",
            "",
            (
                f"The validator anomaly artifact reports {metrics['anomaly_count']} "
                f"findings. The analyzer added {len(findings)} independent "
                "pathology findings."
            ),
            *(f"- `{item['code']}`: {item['message']}" for item in findings),
            "" if findings else "- No additional analyzer pathology was detected.",
            "",
            "## Supported conclusions",
            "",
            (
                "The artifacts support only that the declared R3-T01 protocol, "
                "synthetic replay, independent replay, artifact ownership, mutation "
                "checks, and deterministic rebuild checks were executed and reconciled "
                "for this run."
            ),
            "",
            "## Not supported",
            "",
            (
                "This analysis does not support future-return, boundary, path-label, "
                "model-performance, or trading-advantage claims. It also does not "
                "replace scientific review of the implementation or downstream "
                "sample-outcome validation."
            ),
            "",
            "## R3-T02 recommendation",
            "",
            (
                "R3-T02 is not authorized by this artifact. Any analyzer finding "
                "requires resolution before downstream progression; the repository "
                "gate remains authoritative."
            ),
        ]
    )
    write_markdown(analysis_path, markdown)
    artifacts = _manifest_artifacts(run_dir, config, root)
    config_binding = _source_binding(config_path, formal_execution_sha, root)
    fixture_binding = _source_binding(fixture_path, formal_execution_sha, root)
    manifest = {
        "task_id": config["task_id"],
        "run_id": run_dir.name,
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "formal_execution_sha": formal_execution_sha,
        "config": config_binding,
        "fixture": fixture_binding,
        "upstream_bindings": [
            *[
                {
                    "path": item["path"],
                    "sha256": item["committed_byte_sha256"],
                    "source_commit": item["source_commit"],
                }
                for item in config["upstream_binding"]["required_artifacts"]
            ],
            {
                "path": config["upstream_binding"]["committed_artifact_validation"][
                    "path"
                ],
                "sha256": _git_blob_sha(
                    root,
                    config["upstream_binding"]["committed_artifact_validation"][
                        "source_commit"
                    ],
                    config["upstream_binding"]["committed_artifact_validation"]["path"],
                ),
                "source_commit": config["upstream_binding"][
                    "committed_artifact_validation"
                ]["source_commit"],
            },
        ],
        "artifacts": artifacts,
        "validator_status": validator.get("status"),
        "anomaly_status": anomalies.get("status"),
        "result_analysis_status": "needs_revision" if findings else "passed",
        "real_database_opened": False,
        "formal_run_status": "completed",
        "manifest_self_hash_excluded": True,
    }
    write_json(manifest_path, manifest)
    return analysis_path
