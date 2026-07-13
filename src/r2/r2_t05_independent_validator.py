"""Independent R2-T05 validator.

This module deliberately does not import the production materializer.  It
reconstructs source joins, event identities and risk formulas with its own SQL
and a small independent identity serializer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


class R2T05IndependentValidationError(RuntimeError):
    pass


ROOT = Path(__file__).resolve().parents[2]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _git_json(repo: Path, rel: str) -> dict[str, Any]:
    import subprocess

    payload = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=repo, check=True, capture_output=True).stdout
    return json.loads(payload.decode("utf-8"))


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _check(assertions: list[dict[str, Any]], failures: list[str], name: str, actual: Any, expected: Any = 0) -> None:
    passed = actual == expected
    assertions.append({"assertion": name, "status": "passed" if passed else "failed", "actual": actual, "expected": expected})
    if not passed:
        failures.append(name)


def _validate_startup_contract(
    config: dict[str, Any],
    input_binding: dict[str, Any],
    repo: Path,
    assertions: list[dict[str, Any]],
    failures: list[str],
) -> None:
    """Independently verify T04 handoff-bound blobs used by the T05 startup gate."""
    import subprocess

    startup = input_binding.get("startup", {})
    for key, expected in config["startup"]["required"].items():
        _check(assertions, failures, f"startup_{key}", startup.get(key), expected)
    _check(assertions, failures, "startup_status", startup.get("status"), "passed")
    required = config["startup"]["required_committed_inputs"]
    rows = startup.get("committed_inputs", [])
    by_path = {row.get("path"): row for row in rows if isinstance(row, dict)}
    _check(assertions, failures, "startup_bound_input_cardinality", len(by_path), len(required))
    documents: dict[str, dict[str, Any]] = {}
    for rel in required:
        binding = by_path.get(rel)
        if not binding:
            failures.append(f"startup_bound_input_missing:{rel}")
            continue
        try:
            payload = subprocess.run(
                ["git", "show", f"{binding['source_commit']}:{rel}"],
                cwd=repo,
                check=True,
                capture_output=True,
            ).stdout
            blob_sha = subprocess.run(
                ["git", "rev-parse", f"{binding['source_commit']}:{rel}"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            _check(assertions, failures, f"startup_git_blob_sha:{rel}", blob_sha, binding.get("git_blob_sha"))
            _check(assertions, failures, f"startup_committed_byte_sha256:{rel}", hashlib.sha256(payload).hexdigest(), binding.get("committed_byte_sha256"))
            documents[rel] = json.loads(payload.decode("utf-8"))
        except (KeyError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError):
            failures.append(f"startup_bound_input_invalid:{rel}")
    decision = documents.get(config["inputs"]["t04_freeze_decision_path"])
    plan = documents.get(config["inputs"]["t04_freeze_plan_path"])
    phase_b = documents.get(config["inputs"]["t04_phase_b_independent_validation_path"])
    if decision is not None:
        _check(assertions, failures, "startup_freeze_decision_status", decision.get("freeze_decision_status"), "passed")
        _check(assertions, failures, "startup_freeze_decision_selected_count", decision.get("selected_version_count"), 2)
        _check(assertions, failures, "startup_freeze_decision_strict_core_count", decision.get("strict_core_only_count"), 2)
        _check(assertions, failures, "startup_freeze_decision_rejected_count", decision.get("rejected_decision_unit_count"), 2)
    if plan is not None:
        _check(assertions, failures, "startup_freeze_plan_status", plan.get("freeze_plan_status"), "passed")
        _check(assertions, failures, "startup_freeze_plan_cardinality", plan.get("planned_state_version_count"), 2)
        normalized_versions = []
        for version in plan.get("planned_versions", []):
            normalized = dict(version)
            if "planned_state_version_id" in normalized:
                normalized["state_version_id"] = normalized.pop("planned_state_version_id")
            normalized_versions.append(normalized)
        _check(assertions, failures, "startup_freeze_plan_exact_versions", normalized_versions, config["selected_versions"])
    if phase_b is not None:
        _check(assertions, failures, "startup_phase_b_status", phase_b.get("status"), "passed")
        _check(assertions, failures, "startup_phase_b_selected_count", phase_b.get("selected_cell_count"), 2)
        _check(assertions, failures, "startup_phase_b_strict_core_count", phase_b.get("strict_core_only_count"), 2)
        _check(assertions, failures, "startup_phase_b_rejected_pair_count", phase_b.get("rejected_pair_count"), 2)


def _independent_event_id(contract_version: str, state_version_id: str, security_id: str, cell_id: str, component_id: str, start_date: Any, qualification_time: Any) -> str:
    payload = {
        "contract_version": contract_version,
        "state_version_id": state_version_id,
        "security_id": security_id,
        "first_qualified_component_identity": {
            "source_candidate_cell_id": cell_id,
            "first_component_id": component_id,
            "first_component_start_date": start_date.isoformat() if hasattr(start_date, "isoformat") else str(start_date),
            "first_qualification_time": str(qualification_time),
        },
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _refresh_package(run_dir: Path, validation: dict[str, Any]) -> None:
    validation_path = run_dir / "r2_t05_independent_validation.json"
    validation_path.write_bytes(_canonical_json(validation) + b"\n")
    package_path = run_dir / "r2_t05_result_package.json"
    if package_path.is_file():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["independent_validation_status"] = validation["status"]
        package["independent_validation_path"] = validation_path.relative_to(ROOT).as_posix()
        package_path.write_bytes(_canonical_json(package) + b"\n")
    manifest_path = run_dir / "r2_t05_output_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("artifacts", [])
        rel = validation_path.relative_to(ROOT).as_posix()
        replacement = {"path": rel, "sha256": _sha256_file(validation_path), "size_bytes": validation_path.stat().st_size}
        entries = [row for row in entries if row.get("path") != rel]
        entries.append(replacement)
        manifest["artifacts"] = sorted(entries, key=lambda row: row["path"])
        manifest["artifact_count"] = len(manifest["artifacts"])
        manifest_path.write_bytes(_canonical_json(manifest) + b"\n")


def validate_formal_output(run_dir: Path, repo: Path = ROOT) -> dict[str, Any]:
    config = _git_json(repo, "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json")
    input_binding = json.loads((run_dir / "r2_t05_input_binding.json").read_text(encoding="utf-8"))
    source_rel = input_binding["t03_database"]["path"]
    source_db = repo / Path(source_rel)
    t03_package = _git_json(repo, config["inputs"]["t03_result_package_path"])
    failures: list[str] = []
    assertions: list[dict[str, Any]] = []
    _validate_startup_contract(config, input_binding, repo, assertions, failures)
    expected_sha = t03_package.get("database_sha256")
    actual_sha = _sha256_file(source_db) if source_db.is_file() else None
    _check(assertions, failures, "source_db_sha256", actual_sha, expected_sha)
    output_db = run_dir / config["output"]["database_name"]
    if not output_db.is_file():
        failures.append("canonical_database_missing")
        validation = {"task_id": "R2-T05", "run_id": run_dir.name, "status": "failed", "failure_count": len(failures), "failures": failures, "assertions": assertions, "validation_mode": "independent_sql_and_lineage_recalculation"}
        _refresh_package(run_dir, validation)
        return validation
    con = duckdb.connect(str(output_db), read_only=False)
    con.execute(f"ATTACH '{_sql_path(source_db)}' AS src (READ_ONLY)")
    source_tables = {row[0] for row in con.execute("SHOW TABLES FROM src").fetchall()}
    output_tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    required_output = {"r2_canonical_daily_state", "r2_canonical_event_zone", "r2_canonical_event_membership", "r2_t05_event_id_lineage"}
    _check(assertions, failures, "required_output_tables", len(required_output - output_tables), 0)
    selected = config["selected_versions"]
    expected_daily = con.execute("SELECT count(*) FROM src.base_expected_security_date").fetchone()[0]
    _check(assertions, failures, "authoritative_daily_key_count_positive", expected_daily > 0, True)
    _check(assertions, failures, "daily_version_count", con.execute("SELECT count(distinct state_version_id) FROM r2_canonical_daily_state").fetchone()[0], 2)
    _check(assertions, failures, "event_version_count", con.execute("SELECT count(distinct state_version_id) FROM r2_canonical_event_zone").fetchone()[0], 2)
    _check(assertions, failures, "W250_exclusion", con.execute("SELECT count(*) FROM r2_canonical_daily_state WHERE state_version_id LIKE '%W250%' OR state_version_id LIKE '%W250%'").fetchone()[0], 0)
    _check(assertions, failures, "shared_event_exclusion", con.execute("SELECT count(*) FROM r2_t05_event_id_lineage WHERE source_candidate_cell_id LIKE '%shared%'").fetchone()[0], 0)
    _check(assertions, failures, "daily_duplicate_primary_key", con.execute("SELECT count(*)-count(distinct (state_version_id,security_id,trade_date)) FROM r2_canonical_daily_state").fetchone()[0], 0)
    _check(assertions, failures, "event_duplicate_primary_key", con.execute("SELECT count(*)-count(distinct (state_version_id,event_id)) FROM r2_canonical_event_zone").fetchone()[0], 0)
    _check(assertions, failures, "membership_duplicate_primary_key", con.execute("SELECT count(*)-count(distinct (state_version_id,event_id,security_id,trade_date)) FROM r2_canonical_event_membership").fetchone()[0], 0)
    for version in selected:
        cell = version["source_candidate_cell_id"]
        strict_cell = version["strict_core_source_candidate_cell_id"]
        primary_route = con.execute("SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?", [cell]).fetchone()
        strict_route = con.execute("SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?", [strict_cell]).fetchone()
        if not primary_route or not strict_route:
            failures.append(f"route_missing:{cell}")
            continue
        state = version["state_version_id"]
        _check(assertions, failures, f"daily_row_count:{state}", con.execute("SELECT count(*) FROM r2_canonical_daily_state WHERE state_version_id=?", [state]).fetchone()[0], expected_daily)
        missing = con.execute("""
          SELECT count(*) FROM src.base_expected_security_date b
          LEFT JOIN r2_canonical_daily_state d ON d.state_version_id=? AND d.security_id=b.security_id AND d.trade_date=b.trade_date
          WHERE d.security_id IS NULL
        """, [state]).fetchone()[0]
        extra = con.execute("""
          SELECT count(*) FROM r2_canonical_daily_state d
          LEFT JOIN src.base_expected_security_date b ON b.security_id=d.security_id AND b.trade_date=d.trade_date
          WHERE d.state_version_id=? AND b.security_id IS NULL
        """, [state]).fetchone()[0]
        _check(assertions, failures, f"daily_key_surface_missing:{state}", missing, 0)
        _check(assertions, failures, f"daily_key_surface_extra:{state}", extra, 0)
        daily_mismatch = con.execute("""
          SELECT count(*) FROM r2_canonical_daily_state d JOIN src.route_daily r
            ON r.route_id=? AND r.security_id=d.security_id AND r.trade_date=d.trade_date
          WHERE d.state_version_id=? AND (d.raw_state IS DISTINCT FROM r.raw_state OR d.confirmed_state IS DISTINCT FROM r.confirmed_state
             OR d.confirmation_time IS DISTINCT FROM r.confirmation_time OR d.eligible_state IS DISTINCT FROM r.eligible
             OR d.quality_state IS DISTINCT FROM r.quality_state OR d.state_risk_set_eligible IS DISTINCT FROM r.state_risk_set_eligible)
        """, [primary_route[0], state]).fetchone()[0]
        _check(assertions, failures, f"daily_source_fact_reconciliation:{state}", daily_mismatch, 0)
        strict_mismatch = con.execute("""
          SELECT count(*) FROM r2_canonical_daily_state d JOIN src.route_daily s
            ON s.route_id=? AND s.security_id=d.security_id AND s.trade_date=d.trade_date
          WHERE d.state_version_id=? AND d.strict_core_member IS DISTINCT FROM s.confirmed_state
        """, [strict_route[0], state]).fetchone()[0]
        _check(assertions, failures, f"strict_core_exact_key_recalculation:{state}", strict_mismatch, 0)
        _check(assertions, failures, f"strict_core_subset:{state}", con.execute("SELECT count(*) FROM r2_canonical_daily_state WHERE state_version_id=? AND strict_core_member AND NOT confirmed_state", [state]).fetchone()[0], 0)
        source_events = con.execute("SELECT count(*) FROM src.event_zone WHERE candidate_cell_id=?", [cell]).fetchone()[0]
        canonical_events = con.execute("SELECT count(*) FROM r2_canonical_event_zone WHERE state_version_id=?", [state]).fetchone()[0]
        _check(assertions, failures, f"event_count_reconciliation:{state}", canonical_events, source_events)
        source_membership = con.execute("SELECT count(*) FROM src.event_zone_membership_daily WHERE candidate_cell_id=?", [cell]).fetchone()[0]
        lineage_membership = con.execute("""
          SELECT count(*) FROM src.event_zone_membership_daily m JOIN r2_t05_event_id_lineage l
            ON l.source_candidate_cell_id=m.candidate_cell_id AND l.source_scan_event_id=m.scan_event_id AND l.security_id=m.security_id
          WHERE l.state_version_id=?
        """, [state]).fetchone()[0]
        _check(assertions, failures, f"membership_source_join_count:{state}", lineage_membership, source_membership)
    # Independently recompute every canonical event id from first-component facts.
    event_rows = con.execute("""
      SELECT l.state_version_id,l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,l.first_component_id,l.canonical_event_id,
             q.start_date,q.event_qualification_time
      FROM r2_t05_event_id_lineage l JOIN src.qualified_component q
        ON q.candidate_cell_id=l.source_candidate_cell_id AND q.security_id=l.security_id AND q.component_id=l.first_component_id
      ORDER BY l.state_version_id,l.security_id,l.source_scan_event_id
    """).fetchall()
    id_mismatch = 0
    for row in event_rows:
        if _independent_event_id(config["contract_version"], row[0], row[3], row[1], row[4], row[6], row[7]) != row[5]:
            id_mismatch += 1
    _check(assertions, failures, "event_id_independent_recalculation", id_mismatch, 0)
    _check(assertions, failures, "event_id_source_scan_one_to_one", len(event_rows), con.execute("SELECT count(distinct (state_version_id,source_scan_event_id)) FROM r2_t05_event_id_lineage").fetchone()[0])
    _check(assertions, failures, "event_id_cross_state_security_collision", con.execute("SELECT count(*)-count(distinct (state_version_id,canonical_event_id)) FROM r2_t05_event_id_lineage").fetchone()[0], 0)
    # Independent source-to-canonical membership comparison. The component join is rebuilt here.
    con.execute("""
      CREATE TEMP TABLE iv_component_map AS
      SELECT DISTINCT l.state_version_id,l.canonical_event_id,l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,e.first_component_id component_id
      FROM r2_t05_event_id_lineage l JOIN src.event_zone e ON e.candidate_cell_id=l.source_candidate_cell_id AND e.security_id=l.security_id AND e.scan_event_id=l.source_scan_event_id
      UNION SELECT DISTINCT l.state_version_id,l.canonical_event_id,l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,b.left_component_id
      FROM r2_t05_event_id_lineage l JOIN src.event_zone_bridge_segment b ON b.candidate_cell_id=l.source_candidate_cell_id AND b.security_id=l.security_id AND b.scan_event_id=l.source_scan_event_id AND b.merge_accepted
      UNION SELECT DISTINCT l.state_version_id,l.canonical_event_id,l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,b.right_component_id
      FROM r2_t05_event_id_lineage l JOIN src.event_zone_bridge_segment b ON b.candidate_cell_id=l.source_candidate_cell_id AND b.security_id=l.security_id AND b.scan_event_id=l.source_scan_event_id AND b.merge_accepted
      UNION SELECT DISTINCT l.state_version_id,l.canonical_event_id,l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,r.source_component_id
      FROM r2_t05_event_id_lineage l JOIN src.reentry_attempt r ON r.candidate_cell_id=l.source_candidate_cell_id AND r.security_id=l.security_id AND r.scan_event_id=l.source_scan_event_id
    """)
    member_mismatch = con.execute("""
      SELECT count(*) FROM src.event_zone_membership_daily m
      JOIN r2_t05_event_id_lineage l ON l.source_candidate_cell_id=m.candidate_cell_id AND l.source_scan_event_id=m.scan_event_id AND l.security_id=m.security_id
      JOIN r2_canonical_event_membership c ON c.state_version_id=l.state_version_id AND c.event_id=l.canonical_event_id AND c.security_id=m.security_id AND c.trade_date=m.trade_date
      WHERE c.component_member IS DISTINCT FROM EXISTS (SELECT 1 FROM iv_component_map im JOIN src.qualified_component q ON q.candidate_cell_id=im.source_candidate_cell_id AND q.security_id=im.security_id AND q.component_id=im.component_id WHERE im.canonical_event_id=l.canonical_event_id AND m.trade_date BETWEEN q.start_date AND q.end_date)
         OR c.retrospective_component_member IS DISTINCT FROM m.retrospective_component_member
         OR c.is_prequalification_confirmed_day IS DISTINCT FROM m.prequalification_member
         OR c.is_unqualified_reentry_day IS DISTINCT FROM m.unqualified_reentry_member
         OR c.is_bridged_gap IS DISTINCT FROM m.is_raw_false_bridge
         OR c.event_zone_member IS DISTINCT FROM m.event_zone_member
         OR c.component_qualified_as_of IS DISTINCT FROM m.component_qualified_as_of
         OR c.event_status_as_of IS DISTINCT FROM m.zone_status_as_of
         OR c.zone_revision IS DISTINCT FROM m.zone_revision_as_of
         OR c.membership_available_time IS DISTINCT FROM m.membership_available_time
         OR c.state_risk_set_eligible IS DISTINCT FROM (m.eligible AND m.quality_state='valid' AND m.confirmed_state)
         OR c.qualified_event_risk_set_eligible IS DISTINCT FROM (m.eligible AND m.quality_state='valid' AND m.confirmed_state AND m.event_zone_member AND m.component_qualified_as_of AND NOT m.is_raw_false_bridge AND NOT m.prequalification_member)
    """).fetchone()[0]
    _check(assertions, failures, "membership_row_level_reconciliation", member_mismatch, 0)
    _check(assertions, failures, "membership_availability_not_before_source_row", con.execute("""
      SELECT count(*) FROM r2_canonical_event_membership c JOIN r2_t05_event_id_lineage l
        ON l.state_version_id=c.state_version_id AND l.canonical_event_id=c.event_id
      JOIN src.cell_registry cr ON cr.candidate_cell_id=l.source_candidate_cell_id
      JOIN src.route_daily r ON r.route_id=cr.route_id AND r.security_id=c.security_id AND r.trade_date=c.trade_date
      WHERE c.membership_available_time<r.available_time
    """).fetchone()[0], 0)
    _check(assertions, failures, "risk_formula_recalculation", con.execute("""
      SELECT count(*) FROM r2_canonical_event_membership c
      JOIN r2_t05_event_id_lineage l
        ON l.state_version_id=c.state_version_id AND l.canonical_event_id=c.event_id
      JOIN src.cell_registry cr ON cr.candidate_cell_id=l.source_candidate_cell_id
      JOIN src.route_daily r ON r.route_id=cr.route_id AND r.security_id=c.security_id AND r.trade_date=c.trade_date
      WHERE c.state_risk_set_eligible IS DISTINCT FROM (r.eligible AND r.quality_state='valid' AND r.confirmed_state)
    """).fetchone()[0], 0)
    _check(assertions, failures, "bridge_and_prequalification_risk_exclusion", con.execute("SELECT count(*) FROM r2_canonical_event_membership WHERE (is_bridged_gap OR is_prequalification_confirmed_day OR is_unqualified_reentry_day) AND qualified_event_risk_set_eligible").fetchone()[0], 0)
    _check(assertions, failures, "bridge_confirmed_truth", con.execute("SELECT count(*) FROM r2_canonical_event_membership WHERE is_bridged_gap AND confirmed_state").fetchone()[0], 0)
    _check(assertions, failures, "event_revision_monotonic", con.execute("""
      SELECT count(*) FROM (SELECT zone_revision,lag(zone_revision) OVER(PARTITION BY state_version_id,event_id ORDER BY membership_available_time,trade_date) prior_revision FROM r2_canonical_event_membership) x WHERE prior_revision IS NOT NULL AND zone_revision<prior_revision
    """).fetchone()[0], 0)
    _check(assertions, failures, "quality_break_not_natural_exit", con.execute("SELECT count(*) FROM r2_canonical_event_zone WHERE zone_status='FINALIZED_WITH_QUALITY_BREAK' AND exit_reason NOT IN ('quality_break')").fetchone()[0], 0)
    _check(assertions, failures, "right_censor_no_finalization", con.execute("SELECT count(*) FROM r2_canonical_event_zone WHERE right_censored AND zone_finalization_time IS NOT NULL").fetchone()[0], 0)
    # Schema/field scan and manifest binding checks.
    forbidden = []
    for table in output_tables:
        for column in con.execute(f'DESCRIBE "{table}"').fetchall():
            name = column[0].lower()
            if any(token in name for token in {"future_return", "future_direction", "release_label", "precision", "recall", "backtest", "winner", "trading_efficacy"}):
                forbidden.append(f"{table}.{column[0]}")
    _check(assertions, failures, "forbidden_field_scan", len(forbidden), 0)
    manifest = json.loads((run_dir / "r2_t05_output_manifest.json").read_text(encoding="utf-8"))
    manifest_failures = 0
    for artifact in manifest.get("artifacts", []):
        path = repo / Path(artifact["path"])
        if path.suffix == ".duckdb":
            continue
        if not path.is_file() or _sha256_file(path) != artifact.get("sha256"):
            manifest_failures += 1
    _check(assertions, failures, "output_manifest_hashes", manifest_failures, 0)
    fingerprints = json.loads((run_dir / "r2_t05_table_fingerprint.json").read_text(encoding="utf-8"))
    fingerprint_failures = 0
    for table, profile in fingerprints.get("tables", {}).items():
        if table not in output_tables or con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] != profile.get("row_count"):
            fingerprint_failures += 1
    _check(assertions, failures, "output_table_fingerprint_row_counts", fingerprint_failures, 0)
    con.close()
    validation = {"task_id": "R2-T05", "run_id": run_dir.name, "status": "passed" if not failures else "failed", "failure_count": len(failures), "failures": failures, "assertions": assertions, "validation_mode": "independent_sql_and_lineage_recalculation", "source_database_sha256": actual_sha, "source_database_path": source_rel, "output_database_sha256": _sha256_file(output_db), "selected_version_count": 2, "canonical_event_id_algorithm": "independent_sha256_recalculation"}
    _refresh_package(run_dir, validation)
    return validation


__all__ = ["R2T05IndependentValidationError", "validate_formal_output"]


def validate_committed_artifacts(run_dir: Path, repo: Path = ROOT, commit: str | None = None) -> dict[str, Any]:
    """Validate committed compact artifact bytes and local row-level DB binding."""
    import subprocess

    commit = commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    manifest_path = run_dir / "r2_t05_output_manifest.json"
    failures: list[str] = []
    if not manifest_path.is_file():
        failures.append("output_manifest_missing")
        result = {"task_id": "R2-T05", "run_id": run_dir.name, "status": "failed", "failure_count": len(failures), "failures": failures, "validation_mode": "committed_artifact_bytes"}
        (run_dir / "r2_t05_committed_artifact_validation.json").write_bytes(_canonical_json(result) + b"\n")
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validation_name = "r2_t05_committed_artifact_validation.json"
    for artifact in manifest.get("artifacts", []):
        rel = artifact.get("path", "")
        path = repo / Path(rel)
        if path.name == validation_name or path.suffix == ".duckdb":
            continue
        if not path.is_file():
            failures.append(f"artifact_missing:{rel}")
            continue
        payload = path.read_bytes()
        if b"\r" in payload or payload.startswith(b"\xef\xbb\xbf") or not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
            failures.append(f"artifact_noncanonical_text:{rel}")
        if _sha256_file(path) != artifact.get("sha256"):
            failures.append(f"artifact_hash_mismatch:{rel}")
    for binding in json.loads((run_dir / "r2_t05_input_binding.json").read_text(encoding="utf-8")).get("source_bindings", []):
        rel = binding["path"]
        try:
            blob = subprocess.run(["git", "show", f"{binding['source_commit']}:{rel}"], cwd=repo, check=True, capture_output=True).stdout
            if hashlib.sha1(blob).hexdigest() != binding.get("git_blob_sha"):
                failures.append(f"input_blob_mismatch:{rel}")
            if hashlib.sha256(blob).hexdigest() != binding.get("committed_byte_sha256"):
                failures.append(f"input_byte_hash_mismatch:{rel}")
        except subprocess.CalledProcessError:
            failures.append(f"input_blob_missing:{rel}")
    db_path = run_dir / json.loads((run_dir / "r2_t05_output_manifest.json").read_text(encoding="utf-8")).get("database_path", "").split("/")[-1]
    # The manifest path is repository-relative; resolve it directly when present.
    database_rel = manifest.get("database_path")
    database = repo / Path(database_rel) if database_rel else db_path
    if not database.is_file():
        failures.append("canonical_database_missing")
    elif manifest.get("database_sha256") and _sha256_file(database) != manifest.get("database_sha256"):
        failures.append("canonical_database_hash_mismatch")
    result = {"task_id": "R2-T05", "run_id": run_dir.name, "status": "passed" if not failures else "failed", "failure_count": len(failures), "failures": failures, "validation_mode": "committed_artifact_bytes", "validated_commit": commit, "manifest_path": manifest_path.relative_to(repo).as_posix()}
    (run_dir / validation_name).write_bytes(_canonical_json(result) + b"\n")
    return result


__all__ += ["validate_committed_artifacts"]
