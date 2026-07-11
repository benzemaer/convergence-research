# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r0_t15_layer_q_vector_materializer import (
    CONFIG_PATH,
    ROOT,
    TASK_ID,
    _csv_value,
    build_formal_registry,
)
from .r0_t15_local_duckdb_attestation import (
    OUTPUTS,
    build_r0_t15_local_duckdb_attestation,
)


def validate_r0_t15_layer_q_vector_materialization(
    *,
    run_dir: str | Path,
    require_author_package: bool = False,
    require_author_revision: bool = False,
    require_final_package: bool = False,
    verify_local_duckdb: bool = True,
) -> dict[str, Any]:
    if (
        sum(
            bool(value)
            for value in (
                require_author_package,
                require_author_revision,
                require_final_package,
            )
        )
        > 1
    ):
        raise ValueError("author package modes are mutually exclusive")
    run_dir = Path(run_dir)
    errors: list[str] = []
    required = [
        "r0_t15_request_binding.json",
        "r0_t15_candidate_registry.csv",
        "r0_t15_artifact_manifest.json",
        "r0_t15_authorized_handoff_manifest.json",
        "r0_t15_schema_validation.json",
        "r0_t15_upstream_reconciliation.csv",
        "r0_t15_anomaly_scan.json",
        "r0_t15_final_gate_validation_result.json",
        "r0_t15_execution_summary.json",
    ]
    if require_author_revision or require_final_package:
        required.extend(
            [
                "r0_t15_author_revision.json",
                "r0_t15_local_duckdb_attestation.json",
                "r0_t15_result_analysis.md",
                "r0_t15_evidence.md",
                "r0_t15_result_package.json",
            ]
        )
    if require_final_package:
        required.extend(
            [
                "r0_t15_external_review.json",
                "r0_t15_result_package.reviewed_rev1.json",
                "r0_t15_result_analysis.reviewed_rev1.md",
                "r0_t15_evidence.reviewed_rev1.md",
            ]
        )
    if verify_local_duckdb:
        required.extend(filename for filename, _table in OUTPUTS.values())
    for name in required:
        if not (run_dir / name).is_file():
            errors.append(f"missing_artifact:{name}")
    if errors:
        return _finish(
            run_dir,
            errors,
            require_author_package=require_author_package,
            require_author_revision=require_author_revision,
            require_final_package=require_final_package,
        )

    binding = _load_json(run_dir / "r0_t15_request_binding.json")
    manifest = _load_json(run_dir / "r0_t15_artifact_manifest.json")
    handoff = _load_json(run_dir / "r0_t15_authorized_handoff_manifest.json")
    schema = _load_json(run_dir / "r0_t15_schema_validation.json")
    anomaly = _load_json(run_dir / "r0_t15_anomaly_scan.json")
    execution_gate = _load_json(run_dir / "r0_t15_final_gate_validation_result.json")
    registry = _read_csv(run_dir / "r0_t15_candidate_registry.csv")
    reconciliation = _read_csv(run_dir / "r0_t15_upstream_reconciliation.csv")

    if (
        len(registry) != 10
        or sum(row["materialize"] == "true" for row in registry) != 8
        or sum(row["baseline_reuse"] == "true" for row in registry) != 2
    ):
        errors.append("registry_cardinality_invalid")
    if (
        binding.get("upstream_pr_number") != 87
        or binding.get("upstream_head_commit")
        != "2e2cc2931a4c3ff1ab427966bc78f79a0f69c151"
    ):
        errors.append("execution_upstream_pr_binding_invalid")
    if (
        binding.get("upstream_internal_continuation_gate_status") != "passed"
        or binding.get("repository_r0_materialization_gate_passed") is not False
    ):
        errors.append("execution_upstream_gate_boundary_invalid")
    if any(int(row["mismatch_count"]) != 0 for row in reconciliation):
        errors.append("baseline_reconciliation_mismatch")
    if (
        anomaly.get("status") != "passed"
        or anomaly.get("blocking_findings")
        or anomaly.get("unresolved_questions")
    ):
        errors.append("anomaly_scan_not_passed")
    if schema.get("status") != "passed" or schema.get("primary_key_status") != "passed":
        errors.append("schema_validation_not_passed")
    if not require_final_package and (
        execution_gate.get("status") != "pending_external_review"
        or execution_gate.get("formal_task_completed") is not False
    ):
        errors.append("source_execution_gate_boundary_invalid")

    _validate_registry_semantics(run_dir, manifest, registry, errors)
    _validate_handoff_lineage(run_dir, handoff, errors)

    if verify_local_duckdb and not require_author_revision:
        _validate_source_local_outputs(run_dir, errors)

    if require_author_package:
        _validate_legacy_author_package(run_dir, errors)
    if require_author_revision or require_final_package:
        _validate_author_revision(
            run_dir,
            manifest,
            handoff,
            errors,
            verify_local_duckdb=verify_local_duckdb,
            final_package=require_final_package,
        )
    return _finish(
        run_dir,
        errors,
        require_author_package=require_author_package,
        require_author_revision=require_author_revision,
        require_final_package=require_final_package,
    )


def _validate_registry_semantics(
    run_dir: Path,
    manifest: Mapping[str, Any],
    csv_rows: Sequence[Mapping[str, str]],
    errors: list[str],
) -> None:
    config = _load_json(CONFIG_PATH)
    request = _load_json(
        ROOT / config["upstream_binding"]["materialization_request_path"]
    )
    typed_rows = build_formal_registry(request, config)
    payload_hash = hashlib.sha256(
        json.dumps(
            typed_rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if manifest.get("registry_sha256") != payload_hash:
        errors.append("manifest_registry_payload_hash_mismatch")
    expected_rows = [
        {
            key: "" if value is None else str(_csv_value(value))
            for key, value in row.items()
        }
        for row in typed_rows
    ]
    if list(csv_rows) != expected_rows:
        errors.append("candidate_registry_request_semantic_mismatch")
    registry_path = run_dir / "r0_t15_candidate_registry.csv"
    if b"\r\n" in registry_path.read_bytes():
        errors.append("candidate_registry_not_lf_normalized")


def _validate_handoff_lineage(
    run_dir: Path, handoff: Mapping[str, Any], errors: list[str]
) -> None:
    manifest_path = run_dir / "r0_t15_artifact_manifest.json"
    registry_path = run_dir / "r0_t15_candidate_registry.csv"
    expected_manifest_path = _rel(manifest_path)
    expected_registry_path = _rel(registry_path)
    actual_manifest_sha = sha256_file(manifest_path)
    actual_registry_sha = sha256_file(registry_path)
    if handoff.get("artifact_manifest_path") != expected_manifest_path:
        errors.append("handoff_artifact_manifest_path_mismatch")
    if handoff.get("artifact_manifest_sha256") != actual_manifest_sha:
        errors.append("handoff_artifact_manifest_hash_mismatch")
    if handoff.get("candidate_registry_path") != expected_registry_path:
        errors.append("handoff_candidate_registry_path_mismatch")
    if handoff.get("candidate_registry_sha256") != actual_registry_sha:
        errors.append("handoff_candidate_registry_hash_mismatch")
    if (
        handoff.get("R1-T14-02_allowed_to_start") is not False
        or handoff.get("R1-T10_allowed_to_start") is not False
        or handoff.get("R2_allowed_to_start") is not False
        or handoff.get("repository_t14_02_gate_passed") is not False
        or handoff.get("formal_task_completed") is not False
    ):
        errors.append("handoff_repository_gate_boundary_invalid")


def _validate_legacy_author_package(run_dir: Path, errors: list[str]) -> None:
    package_path = run_dir / "r0_t15_result_package.author_draft_v1.json"
    if not package_path.is_file():
        errors.append("legacy_author_package_archive_missing")
        return
    package = _load_json(package_path)
    if (
        package.get("R0_q_vector_materialization_status") != "author_draft_complete"
        or package.get("formal_task_completed") is not False
    ):
        errors.append("legacy_author_package_status_invalid")


def _validate_author_revision(
    run_dir: Path,
    manifest: Mapping[str, Any],
    handoff: Mapping[str, Any],
    errors: list[str],
    *,
    verify_local_duckdb: bool,
    final_package: bool = False,
) -> None:
    package_path = run_dir / "r0_t15_result_package.json"
    package = _load_json(package_path)
    revision = _load_json(run_dir / "r0_t15_author_revision.json")
    attestation_path = run_dir / "r0_t15_local_duckdb_attestation.json"
    attestation = _load_json(attestation_path)

    expected_status = {
        "status": (
            "review_passed_final_gate_passed_pending_merge"
            if final_package
            else "author_revision_complete"
        ),
        "R0_q_vector_materialization_status": (
            "final_gate_passed_pending_merge"
            if final_package
            else "author_revision_complete_pending_rereview"
        ),
        "R0_q_vector_materialization_request_status": "approved",
        "independent_review_status": "passed" if final_package else "pending_rereview",
        "repository_final_gate_status": "passed" if final_package else "pending",
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "external_direct_duckdb_byte_review_performed": False,
        "formal_task_completed": False,
        "superseded": False,
    }
    for key, expected in expected_status.items():
        if package.get(key) != expected:
            errors.append(f"author_revision_package_field_mismatch:{key}")
    gate = package.get("gate_status", {})
    expected_gate = {
        "engineering_validator_status": "passed",
        "author_result_analysis_status": "passed",
        "anomaly_resolution_status": "passed",
        "author_revision_status": "completed",
        "goal_internal_continuation_gate_status": (
            "closed_pending_repository_merge"
            if final_package
            else "closed_pending_external_rereview"
        ),
        "goal_internal_continuation_allowed": False,
        "goal_internal_t14_02_authorized": False,
        "repository_t14_02_gate_passed": False,
    }
    if final_package:
        expected_gate.update(
            {
                "independent_review_status": "passed",
                "external_review_status": "passed",
                "repository_final_gate_status": "passed",
                "repository_merge_status": "pending",
            }
        )
    for key, expected in expected_gate.items():
        if gate.get(key) != expected:
            errors.append(f"author_revision_gate_field_mismatch:{key}")

    ref_prefixes = (
        "request_binding",
        "artifact_manifest",
        "candidate_registry",
        "handoff_manifest",
        "author_revision",
        "local_duckdb_attestation",
        "result_analysis",
        "run_copy_result_analysis",
        "formal_evidence",
        "run_copy_formal_evidence",
        "revision_config",
        "execution_config",
    )
    for prefix in ref_prefixes:
        _check_ref(package, prefix, errors, f"package_{prefix}")

    manifest_sha = sha256_file(run_dir / "r0_t15_artifact_manifest.json")
    registry_sha = sha256_file(run_dir / "r0_t15_candidate_registry.csv")
    handoff_sha = sha256_file(run_dir / "r0_t15_authorized_handoff_manifest.json")
    if package.get("artifact_manifest_sha256") != manifest_sha:
        errors.append("package_artifact_manifest_hash_mismatch")
    if package.get("candidate_registry_sha256") != registry_sha:
        errors.append("package_candidate_registry_hash_mismatch")
    if package.get("handoff_manifest_sha256") != handoff_sha:
        errors.append("package_handoff_manifest_hash_mismatch")
    if handoff.get("artifact_manifest_sha256") != package.get(
        "artifact_manifest_sha256"
    ):
        errors.append("package_handoff_artifact_manifest_hash_mismatch")
    if handoff.get("candidate_registry_sha256") != package.get(
        "candidate_registry_sha256"
    ):
        errors.append("package_handoff_candidate_registry_hash_mismatch")
    if handoff.get("author_revision_sha256") != package.get("author_revision_sha256"):
        errors.append("package_handoff_author_revision_hash_mismatch")
    if handoff.get("local_duckdb_attestation_sha256") != package.get(
        "local_duckdb_attestation_sha256"
    ):
        errors.append("package_handoff_attestation_hash_mismatch")

    _validate_upstream_final_binding(package, handoff, revision, errors)
    _validate_execution_binding(package, handoff, revision, errors)
    _validate_revision_record(
        run_dir,
        package,
        handoff,
        revision,
        errors,
        final_package=final_package,
    )
    _validate_revision_commit(package, errors)
    _validate_revision_config(package, handoff, revision, errors)
    _validate_archives(package, errors)
    _validate_committed_artifacts(package, errors)
    _validate_local_outputs(package, manifest, errors)
    _validate_attestation(
        run_dir,
        package,
        attestation,
        errors,
        verify_local_duckdb=verify_local_duckdb,
    )
    if final_package:
        _validate_external_review(run_dir, package, errors)
        _validate_final_documents(package, errors)
    else:
        _validate_revision_documents(package, errors)


def _validate_upstream_final_binding(
    package: Mapping[str, Any],
    handoff: Mapping[str, Any],
    revision: Mapping[str, Any],
    errors: list[str],
) -> None:
    bindings = [
        package.get("upstream_final_gate_binding", {}),
        handoff.get("upstream_final_gate_binding", {}),
        revision.get("upstream_final_gate_binding", {}),
    ]
    if not all(binding == bindings[0] for binding in bindings[1:]):
        errors.append("upstream_final_gate_binding_cross_file_mismatch")
        return
    binding = bindings[0]
    for prefix in (
        "result_package",
        "scientific_review",
        "final_gate_validation",
        "materialization_request",
    ):
        _check_ref(binding, prefix, errors, f"upstream_{prefix}")
    upstream_package = _load_json(ROOT / binding["result_package_path"])
    upstream_review = _load_json(ROOT / binding["scientific_review_path"])
    upstream_gate = _load_json(ROOT / binding["final_gate_validation_path"])
    if (
        upstream_package.get("status") != "completed"
        or upstream_package.get("formal_task_completed") is not True
        or upstream_package.get("downstream_gate_scope") != "R0-T15_only"
        or upstream_package.get("R1-T14-02_allowed_to_start") is not False
    ):
        errors.append("upstream_result_package_semantics_invalid")
    if (
        upstream_review.get("scientific_review_status") != "passed"
        or upstream_review.get("reviewer_identity") != "benzemaer"
        or str(upstream_review.get("review_comment_id")) != "4941866339"
    ):
        errors.append("upstream_scientific_review_semantics_invalid")
    if (
        upstream_gate.get("status") != "passed"
        or upstream_gate.get("formal_task_completed") is not True
        or upstream_gate.get("downstream_gate_scope") != "R0-T15_only"
    ):
        errors.append("upstream_final_gate_semantics_invalid")


def _validate_execution_binding(
    package: Mapping[str, Any],
    handoff: Mapping[str, Any],
    revision: Mapping[str, Any],
    errors: list[str],
) -> None:
    config_path = ROOT / str(package["revision_config_path"])
    config = _load_json(config_path)
    source = config["source_run"]
    archived_handoff = _load_json(ROOT / source["original_handoff_archive_path"])
    request_binding = _load_json(ROOT / source["request_binding_path"])
    expected = archived_handoff.get("upstream_binding")
    if expected != request_binding:
        errors.append("archived_handoff_request_binding_mismatch")
    if package.get("execution_upstream_binding") != expected:
        errors.append("package_execution_upstream_binding_mismatch")
    if handoff.get("execution_upstream_binding") != expected:
        errors.append("handoff_execution_upstream_binding_mismatch")
    if revision.get("execution_code_commit") != source.get("execution_code_commit"):
        errors.append("revision_execution_code_commit_mismatch")


def _validate_revision_record(
    run_dir: Path,
    package: Mapping[str, Any],
    handoff: Mapping[str, Any],
    revision: Mapping[str, Any],
    errors: list[str],
    *,
    final_package: bool = False,
) -> None:
    manifest_path = run_dir / "r0_t15_artifact_manifest.json"
    registry_path = run_dir / "r0_t15_candidate_registry.csv"
    archive_path = run_dir / "r0_t15_authorized_handoff_manifest.author_draft_v1.json"
    old_handoff = _load_json(archive_path)
    expected_manifest_sha = sha256_file(manifest_path)
    expected_registry_sha = sha256_file(registry_path)
    corrected = revision.get("corrected_handoff_targets", {})
    manifest_correction = corrected.get("artifact_manifest", {})
    registry_correction = corrected.get("candidate_registry", {})
    if revision.get("execution_artifacts_recomputed") is not False:
        errors.append("revision_execution_artifacts_recomputed_invalid")
    if revision.get("revision_code_commit") != package.get(
        "revision_code_commit"
    ) or handoff.get("revision_code_commit") != package.get("revision_code_commit"):
        errors.append("revision_code_commit_cross_file_mismatch")
    if revision.get("execution_upstream_binding_is_historical") is not True:
        errors.append("revision_execution_binding_history_flag_invalid")
    if revision.get("execution_recorded_upstream_result_package_sha256") != (
        old_handoff.get("upstream_binding", {}).get(
            "upstream_result_package_actual_sha256"
        )
    ):
        errors.append("revision_execution_runtime_hash_history_mismatch")
    if revision.get("line_ending_root_cause") != (
        "runtime_crlf_hashes_persisted_after_repository_lf_normalization"
    ):
        errors.append("revision_line_ending_root_cause_invalid")
    if revision.get("external_direct_duckdb_byte_review_performed") is not False:
        errors.append("revision_external_byte_review_boundary_invalid")
    if manifest_correction.get("canonical_lf_sha256") != expected_manifest_sha:
        errors.append("revision_manifest_corrected_hash_mismatch")
    if registry_correction.get("canonical_lf_sha256") != expected_registry_sha:
        errors.append("revision_registry_corrected_hash_mismatch")
    if manifest_correction.get("stale_sha256") != old_handoff.get(
        "artifact_manifest_sha256"
    ):
        errors.append("revision_manifest_stale_hash_mismatch")
    if registry_correction.get("stale_sha256") != old_handoff.get(
        "candidate_registry_sha256"
    ):
        errors.append("revision_registry_stale_hash_mismatch")
    crlf_manifest_sha = hashlib.sha256(
        manifest_path.read_bytes().replace(b"\n", b"\r\n")
    ).hexdigest()
    crlf_registry_sha = hashlib.sha256(
        registry_path.read_bytes().replace(b"\n", b"\r\n")
    ).hexdigest()
    if manifest_correction.get("stale_sha256") != crlf_manifest_sha:
        errors.append("revision_manifest_crlf_root_cause_not_reproduced")
    if registry_correction.get("stale_sha256") != crlf_registry_sha:
        errors.append("revision_registry_crlf_root_cause_not_reproduced")
    expected_history = [
        {
            "pr_number": 88,
            "comment_id": 4941872279,
            "outcome": "needs_revision",
            "blocking_findings": [
                "stale_handoff_artifact_manifest_hash",
                "stale_handoff_candidate_registry_hash",
            ],
        }
    ]
    if revision.get("review_history") != expected_history:
        errors.append("revision_review_history_invalid")
    expected_package_history = expected_history
    if final_package:
        expected_package_history = expected_history + [
            {
                "pr_number": 88,
                "comment_id": 4943245857,
                "outcome": "passed",
                "blocking_findings": [],
                "reviewed_pr_head_commit": ("3210c35a6a5a5679792bfd455969e78664fc5e13"),
            }
        ]
    if package.get("review_history") != expected_package_history:
        errors.append("package_review_history_invalid")
    if handoff.get("review_history") != expected_history:
        errors.append("handoff_review_history_invalid")
    if handoff.get("handoff_status") != (
        "author_revision_candidate_pending_external_rereview"
    ):
        errors.append("handoff_status_invalid")
    expected_handoff_governance = {
        "goal_internal_continuation_gate_status": ("closed_pending_external_rereview"),
        "goal_internal_continuation_allowed": False,
        "goal_internal_t14_02_authorized": False,
        "repository_t14_02_gate_passed": False,
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "independent_review_status": "pending_rereview",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
        "external_direct_duckdb_byte_review_performed": False,
    }
    for key, expected in expected_handoff_governance.items():
        if handoff.get(key) != expected:
            errors.append(f"handoff_revision_governance_field_mismatch:{key}")

    revision_refs = {
        "source_artifact_manifest": (
            _rel(manifest_path),
            expected_manifest_sha,
        ),
        "candidate_registry": (_rel(registry_path), expected_registry_sha),
        "revision_config": (
            package.get("revision_config_path"),
            package.get("revision_config_sha256"),
        ),
        "local_duckdb_attestation": (
            package.get("local_duckdb_attestation_path"),
            package.get("local_duckdb_attestation_sha256"),
        ),
    }
    for prefix, (expected_path, expected_sha) in revision_refs.items():
        if revision.get(f"{prefix}_path") != expected_path:
            errors.append(f"revision_reference_path_mismatch:{prefix}")
        if revision.get(f"{prefix}_sha256") != expected_sha:
            errors.append(f"revision_reference_hash_mismatch:{prefix}")
    for key, expected in {
        "author_revision_status": "completed_pending_rereview",
        "independent_review_status": "pending_rereview",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
    }.items():
        if revision.get(key) != expected:
            errors.append(f"revision_governance_field_mismatch:{key}")


def _validate_revision_commit(package: Mapping[str, Any], errors: list[str]) -> None:
    commit = package.get("revision_code_commit")
    if not isinstance(commit, str) or len(commit) != 40:
        errors.append("revision_code_commit_invalid")
        return
    import subprocess  # noqa: PLC0415

    exists = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT
    )
    if exists.returncode != 0 or ancestor.returncode != 0:
        errors.append("revision_code_commit_not_in_head_lineage")
    execution_commit = package.get("execution_code_commit")
    execution_exists = subprocess.run(
        ["git", "cat-file", "-e", f"{execution_commit}^{{commit}}"], cwd=ROOT
    )
    if execution_exists.returncode != 0:
        errors.append("execution_code_commit_object_missing")


def _validate_archives(package: Mapping[str, Any], errors: list[str]) -> None:
    supersedes = package.get("supersedes", {})
    for prefix in ("result_package", "handoff"):
        _check_ref(supersedes, prefix, errors, f"supersedes_{prefix}")
    if (
        supersedes.get("result_package_sha256")
        != "43aa859dc938f6a9796f68297107d978e9a3b1a36b1ea12fec8c10e5aee27f8b"
        or supersedes.get("handoff_sha256")
        != "fa589db97a19c8e4ba5baee272d5250c0a666e476532d316de2f1225feac879d"
    ):
        errors.append("supersession_archive_hash_invalid")


def _validate_revision_config(
    package: Mapping[str, Any],
    handoff: Mapping[str, Any],
    revision: Mapping[str, Any],
    errors: list[str],
) -> None:
    config_path = _resolve_repo_path(
        package.get("revision_config_path"), errors, "revision_config"
    )
    if config_path is None or not config_path.is_file():
        return
    config = _load_json(config_path)
    if (
        config.get("revision_id") != package.get("revision_id")
        or revision.get("revision_id") != package.get("revision_id")
        or handoff.get("revision_id") != package.get("revision_id")
    ):
        errors.append("revision_id_cross_file_mismatch")
    if config.get("upstream_final_gate_binding") != package.get(
        "upstream_final_gate_binding"
    ):
        errors.append("revision_config_upstream_final_gate_binding_mismatch")
    source = config.get("source_run", {})
    for prefix in (
        "execution_config",
        "execution_summary",
        "request_binding",
        "artifact_manifest",
        "candidate_registry",
    ):
        _check_ref(source, prefix, errors, f"revision_source_{prefix}")
    for prefix in (
        "original_handoff",
        "original_result_package",
        "original_analysis",
        "original_evidence",
    ):
        path_value = source.get(f"{prefix}_archive_path")
        hash_value = source.get(f"{prefix}_sha256")
        path = _resolve_repo_path(path_value, errors, f"revision_source_{prefix}")
        if path is None or not path.is_file():
            errors.append(f"revision_source_{prefix}_file_missing")
        elif sha256_file(path) != hash_value:
            errors.append(f"revision_source_{prefix}_hash_mismatch")


def _validate_committed_artifacts(
    package: Mapping[str, Any], errors: list[str]
) -> None:
    artifacts = package.get("committed_artifacts", [])
    paths = [item.get("path") for item in artifacts if isinstance(item, dict)]
    if len(paths) != len(set(paths)):
        errors.append("package_committed_artifact_missing_or_duplicate")
    required_paths = {
        package.get(f"{prefix}_path")
        for prefix in (
            "request_binding",
            "artifact_manifest",
            "candidate_registry",
            "handoff_manifest",
            "author_revision",
            "local_duckdb_attestation",
            "result_analysis",
            "run_copy_result_analysis",
            "formal_evidence",
            "run_copy_formal_evidence",
            "revision_config",
            "execution_config",
        )
    }
    supersedes = package.get("supersedes", {})
    required_paths.update(
        {supersedes.get("result_package_path"), supersedes.get("handoff_path")}
    )
    config_path = ROOT / str(package["revision_config_path"])
    if config_path.is_file():
        source = _load_json(config_path).get("source_run", {})
        required_paths.update(
            {
                source.get("original_analysis_archive_path"),
                source.get("original_evidence_archive_path"),
            }
        )
    required_paths.discard(None)
    if package.get("status") == "review_passed_final_gate_passed_pending_merge":
        required_paths.update(
            {
                package.get("external_review_record_path"),
                package.get("external_review_markdown_path"),
                package.get("reviewed_author_revision_package_path"),
                package.get("reviewed_result_analysis_path"),
                package.get("reviewed_formal_evidence_path"),
                package.get("readme_path"),
            }
        )
        required_paths.discard(None)
    if not required_paths.issubset(set(paths)):
        errors.append("package_committed_artifact_missing_or_duplicate")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("package_committed_artifact_invalid")
            continue
        path_value = artifact.get("path")
        path = _resolve_repo_path(path_value, errors, "committed_artifact")
        if path is None or not path.is_file():
            errors.append(f"package_artifact_missing:{path_value}")
        elif sha256_file(path) != artifact.get("sha256"):
            errors.append(f"package_artifact_hash_mismatch:{path_value}")


def _validate_local_outputs(
    package: Mapping[str, Any], manifest: Mapping[str, Any], errors: list[str]
) -> None:
    package_outputs = {
        item.get("table"): item
        for item in package.get("local_materialized_artifacts", [])
        if isinstance(item, dict)
    }
    manifest_outputs = manifest.get("outputs", {})
    if len(package_outputs) != len(manifest_outputs):
        errors.append("package_local_output_cardinality_mismatch")
    for record in manifest_outputs.values():
        package_record = package_outputs.get(record.get("table"))
        if package_record is None:
            errors.append(f"package_local_output_missing:{record.get('table')}")
            continue
        for key in ("path", "sha256", "row_count", "table"):
            if package_record.get(key) != record.get(key):
                errors.append(
                    f"package_local_output_field_mismatch:{record.get('table')}:{key}"
                )
        if package_record.get("committed_to_repo") is not False:
            errors.append(
                f"package_local_output_commit_boundary_invalid:{record.get('table')}"
            )


def _validate_attestation(
    run_dir: Path,
    package: Mapping[str, Any],
    attestation: Mapping[str, Any],
    errors: list[str],
    *,
    verify_local_duckdb: bool,
) -> None:
    expected_claim = (
        "implementation-side fresh reread of local DuckDB bytes; external review "
        "may inspect only committed manifests, code, reconciliation, and this attestation"
    )
    if (
        attestation.get("task_id") != TASK_ID
        or attestation.get("run_id") != package.get("run_id")
        or attestation.get("source_execution_code_commit")
        != package.get("execution_code_commit")
        or attestation.get("status") != "passed"
        or attestation.get("local_duckdb_byte_access") is not True
        or attestation.get("validation_scope") != "canonical_local_outputs"
        or attestation.get("delivery_status") != "local_only_not_committed_or_uploaded"
        or attestation.get("external_direct_duckdb_byte_review_performed") is not False
        or attestation.get("independent_byte_validation_status") != "not_performed"
        or attestation.get("claim_boundary") != expected_claim
        or attestation.get("validator_code_commit")
        != package.get("revision_code_commit")
    ):
        errors.append("local_duckdb_attestation_semantics_invalid")
    if verify_local_duckdb:
        try:
            fresh = build_r0_t15_local_duckdb_attestation(
                run_dir=run_dir,
                revision_code_commit=str(package.get("revision_code_commit")),
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"local_duckdb_reread_failed:{exc}")
            return
        for key in (
            "status",
            "outputs",
            "raw_parent_child_violation_counts",
            "confirmed_parent_child_violation_counts",
            "confirmation_interval_duration_mismatch_count",
            "checks",
            "failures",
        ):
            if fresh.get(key) != attestation.get(key):
                errors.append(f"local_duckdb_attestation_reread_mismatch:{key}")


def _validate_source_local_outputs(run_dir: Path, errors: list[str]) -> None:
    try:
        fresh = build_r0_t15_local_duckdb_attestation(run_dir=run_dir)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"source_local_duckdb_reread_failed:{exc}")
        return
    if fresh.get("status") != "passed":
        errors.append("source_local_duckdb_validation_failed")


def _validate_revision_documents(package: Mapping[str, Any], errors: list[str]) -> None:
    analysis_path = ROOT / str(package["result_analysis_path"])
    evidence_path = ROOT / str(package["formal_evidence_path"])
    markers = (
        "independent_review_status=pending_rereview",
        "external_direct_duckdb_byte_review_performed=false",
        "R1-T14-02_allowed_to_start=false",
        "formal_task_completed=false",
        "selection_path_not_independently_confirmed=true",
    )
    for label, path in (("analysis", analysis_path), ("evidence", evidence_path)):
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        for marker in markers:
            if marker not in text:
                errors.append(f"revision_{label}_marker_missing:{marker}")
    if package.get("result_analysis_sha256") != package.get(
        "run_copy_result_analysis_sha256"
    ):
        errors.append("revision_analysis_run_copy_hash_mismatch")
    if package.get("formal_evidence_sha256") != package.get(
        "run_copy_formal_evidence_sha256"
    ):
        errors.append("revision_evidence_run_copy_hash_mismatch")


def _validate_external_review(
    run_dir: Path, package: Mapping[str, Any], errors: list[str]
) -> None:
    review_path = run_dir / "r0_t15_external_review.json"
    reviewed_package_path = run_dir / "r0_t15_result_package.reviewed_rev1.json"
    reviewed_analysis_path = run_dir / "r0_t15_result_analysis.reviewed_rev1.md"
    reviewed_evidence_path = run_dir / "r0_t15_evidence.reviewed_rev1.md"
    review = _load_json(review_path)
    expected = {
        "task_id": "R0-T15",
        "revision_id": "R0-T15-REV1",
        "external_review_status": "passed",
        "independent_review_status": "passed",
        "reviewer_identity": "benzemaer",
        "reviewer_role": "independent_materialization_reviewer",
        "implementation_actor": "codex",
        "independence_attestation": True,
        "review_comment_id": 4943245857,
        "review_source": (
            "https://github.com/benzemaer/convergence-research/"
            "pull/88#issuecomment-4943245857"
        ),
        "reviewed_pr_head_commit": ("3210c35a6a5a5679792bfd455969e78664fc5e13"),
        "reviewed_result_package_sha256": (
            "078cb456c21ef995bcb8e052191ef948d5ea5129e82f7549eef5ed4b3ab917b0"
        ),
        "reviewed_handoff_sha256": (
            "438d2f09ee7a853547a037521ba4ca133bd18bf1fa5dfef91f97db5f670393c3"
        ),
        "reviewed_artifact_manifest_sha256": (
            "664b6d4558978806db80912aa5e544e0c81824b188a5ea71fece8e20507a8c51"
        ),
        "reviewed_candidate_registry_sha256": (
            "02fdaf1b94780ef42115a9109ae9f1fd6b90a6e019925a5067ad1bac96d4944f"
        ),
        "external_direct_duckdb_byte_review_performed": False,
        "independent_byte_validation_status": "not_performed",
        "blocking_findings": [],
        "downstream_gate_recommendation": True,
        "downstream_gate_scope": "R0-T15_repository_final_gate_only",
    }
    for key, value in expected.items():
        if review.get(key) != value:
            errors.append(f"external_review_field_mismatch:{key}")
    if review.get("reviewer_identity") == review.get("implementation_actor"):
        errors.append("external_review_not_independent")
    if review.get("closed_prior_blockers") != [
        "stale_handoff_artifact_manifest_hash",
        "stale_handoff_candidate_registry_hash",
    ]:
        errors.append("external_review_closed_blockers_invalid")
    reviewed_refs = {
        "reviewed_handoff": run_dir / "r0_t15_authorized_handoff_manifest.json",
        "reviewed_artifact_manifest": run_dir / "r0_t15_artifact_manifest.json",
        "reviewed_candidate_registry": run_dir / "r0_t15_candidate_registry.csv",
        "reviewed_author_revision": run_dir / "r0_t15_author_revision.json",
        "reviewed_local_duckdb_attestation": (
            run_dir / "r0_t15_local_duckdb_attestation.json"
        ),
        "reviewed_author_revision_validation": (
            run_dir / "r0_t15_author_revision_package_validation_result.json"
        ),
    }
    for prefix, path in reviewed_refs.items():
        if review.get(f"{prefix}_path") != _rel(path):
            errors.append(f"external_review_reference_path_mismatch:{prefix}")
        if not path.is_file():
            errors.append(f"external_review_reference_missing:{prefix}")
        elif review.get(f"{prefix}_sha256") != sha256_file(path):
            errors.append(f"external_review_reference_hash_mismatch:{prefix}")
    for path, expected_sha, label in (
        (
            reviewed_package_path,
            expected["reviewed_result_package_sha256"],
            "reviewed_package",
        ),
        (
            reviewed_analysis_path,
            "13d6bcd192ef05ecd227278f9e51452ddcedd91469c05badfd983af8ee8aef1f",
            "reviewed_analysis",
        ),
        (
            reviewed_evidence_path,
            "3b6848a197c4a7e36909f1badebdeeea87fdfba9fe84c3aa4026363532801c84",
            "reviewed_evidence",
        ),
    ):
        if not path.is_file():
            errors.append(f"external_review_{label}_missing")
        elif sha256_file(path) != expected_sha:
            errors.append(f"external_review_{label}_hash_mismatch")
    if review.get("reviewed_result_analysis_sha256") != sha256_file(
        reviewed_analysis_path
    ):
        errors.append("external_review_reviewed_analysis_hash_mismatch")
    revision_validation_path = reviewed_refs["reviewed_author_revision_validation"]
    if revision_validation_path.is_file():
        revision_validation = _load_json(revision_validation_path)
        if revision_validation.get("status") != "passed":
            errors.append("external_review_author_revision_validation_not_passed")
        if revision_validation.get("result_package_sha256") != sha256_file(
            reviewed_package_path
        ):
            errors.append(
                "external_review_author_revision_validation_package_hash_mismatch"
            )
    refs = {
        "external_review_record": review_path,
        "reviewed_author_revision_package": reviewed_package_path,
        "reviewed_result_analysis": reviewed_analysis_path,
        "reviewed_formal_evidence": reviewed_evidence_path,
    }
    for prefix, path in refs.items():
        if package.get(f"{prefix}_path") != _rel(path):
            errors.append(f"final_package_reference_path_mismatch:{prefix}")
        if package.get(f"{prefix}_sha256") != sha256_file(path):
            errors.append(f"final_package_reference_hash_mismatch:{prefix}")
    markdown_path = _resolve_repo_path(
        package.get("external_review_markdown_path"),
        errors,
        "external_review_markdown",
    )
    if markdown_path is None or not markdown_path.is_file():
        errors.append("external_review_markdown_missing")
    elif sha256_file(markdown_path) != package.get("external_review_markdown_sha256"):
        errors.append("external_review_markdown_hash_mismatch")


def _validate_final_documents(package: Mapping[str, Any], errors: list[str]) -> None:
    markers = (
        "independent_review_status=passed",
        "repository_final_gate_status=passed",
        "external_direct_duckdb_byte_review_performed=false",
        "R1-T14-02_allowed_to_start=false",
        "R1-T10_allowed_to_start=false",
        "R2_allowed_to_start=false",
        "formal_task_completed=false",
        "selection_path_not_independently_confirmed=true",
    )
    for label, prefix in (
        ("analysis", "result_analysis"),
        ("evidence", "formal_evidence"),
    ):
        path = _resolve_repo_path(package.get(f"{prefix}_path"), errors, label)
        text = path.read_text(encoding="utf-8") if path and path.is_file() else ""
        for marker in markers:
            if marker not in text:
                errors.append(f"final_{label}_marker_missing:{marker}")
    if package.get("result_analysis_sha256") != package.get(
        "run_copy_result_analysis_sha256"
    ):
        errors.append("final_analysis_run_copy_hash_mismatch")
    if package.get("formal_evidence_sha256") != package.get(
        "run_copy_formal_evidence_sha256"
    ):
        errors.append("final_evidence_run_copy_hash_mismatch")
    readme_path = _resolve_repo_path(package.get("readme_path"), errors, "readme")
    if readme_path is None or not readme_path.is_file():
        errors.append("final_readme_missing")
        return
    if sha256_file(readme_path) != package.get("readme_sha256"):
        errors.append("final_readme_hash_mismatch")
    readme = readme_path.read_text(encoding="utf-8")
    for marker in (
        "R0_q_vector_materialization_status: final_gate_passed_pending_merge",
        "R1-T14-02_allowed_to_start: false",
        "R1-T10_allowed_to_start: false",
        "R2_allowed_to_start: false",
    ):
        if marker not in readme:
            errors.append(f"final_readme_marker_missing:{marker}")


def _check_ref(
    payload: Mapping[str, Any], prefix: str, errors: list[str], label: str
) -> None:
    path_value = payload.get(f"{prefix}_path")
    hash_value = payload.get(f"{prefix}_sha256")
    if not path_value or not hash_value:
        errors.append(f"{label}_reference_missing")
        return
    path = _resolve_repo_path(path_value, errors, label)
    if path is None or not path.is_file():
        errors.append(f"{label}_file_missing")
    elif sha256_file(path) != hash_value:
        errors.append(f"{label}_hash_mismatch")


def _resolve_repo_path(path_value: Any, errors: list[str], label: str) -> Path | None:
    if not isinstance(path_value, str):
        errors.append(f"{label}_path_invalid")
        return None
    path = (ROOT / path_value).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        errors.append(f"{label}_path_outside_repository")
        return None
    return path


def _finish(
    run_dir: Path,
    errors: list[str],
    *,
    require_author_package: bool,
    require_author_revision: bool,
    require_final_package: bool,
) -> dict[str, Any]:
    mode = (
        "final_package"
        if require_final_package
        else "author_revision"
        if require_author_revision
        else "author_package"
        if require_author_package
        else "engineering"
    )
    result = {
        "task_id": TASK_ID,
        "validation_mode": mode,
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "independent_review_status": (
            "passed"
            if require_final_package
            else "pending_rereview"
            if require_author_revision
            else "not_started"
        ),
        "repository_final_gate_status": (
            "passed" if require_final_package and not errors else "pending"
        ),
        "repository_merge_status": "pending",
        "goal_internal_continuation_allowed": False,
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "formal_task_completed": False,
    }
    if require_author_revision or require_final_package:
        package_path = run_dir / "r0_t15_result_package.json"
        result["result_package_path"] = _rel(package_path)
        result["result_package_sha256"] = (
            sha256_file(package_path) if package_path.is_file() else None
        )
    filename = {
        "engineering": "r0_t15_engineering_validation_result.json",
        "author_package": "r0_t15_author_draft_package_validation_result.json",
        "author_revision": "r0_t15_author_revision_package_validation_result.json",
        "final_package": "r0_t15_final_gate_validation_result.json",
    }[mode]
    write_json_atomic(run_dir / filename, result)
    return result


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
