"""Independent R2-T05 validator.

This module deliberately does not import the production materializer.  It
reconstructs source joins, event identities and risk formulas with its own SQL
and a small independent identity serializer.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


class R2T05IndependentValidationError(RuntimeError):
    pass


ROOT = Path(__file__).resolve().parents[2]
COMPACT_AUDIT_STATUS_FILES = (
    "r2_t05_source_readiness.json",
    "r2_t05_selected_cell_reconciliation.csv",
    "r2_t05_daily_reconciliation.csv",
    "r2_t05_event_reconciliation.csv",
    "r2_t05_membership_reconciliation.csv",
    "r2_t05_strict_core_reconciliation.csv",
    "r2_t05_availability_time_audit.csv",
    "r2_t05_risk_set_audit.csv",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _git_json(repo: Path, rel: str) -> dict[str, Any]:
    import subprocess

    payload = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=repo, check=True, capture_output=True
    ).stdout
    return json.loads(payload.decode("utf-8"))


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _check(
    assertions: list[dict[str, Any]],
    failures: list[str],
    name: str,
    actual: Any,
    expected: Any = 0,
) -> None:
    passed = actual == expected
    assertions.append(
        {
            "assertion": name,
            "status": "passed" if passed else "failed",
            "actual": actual,
            "expected": expected,
        }
    )
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
    _check(
        assertions,
        failures,
        "startup_bound_input_cardinality",
        len(by_path),
        len(required),
    )
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
            _check(
                assertions,
                failures,
                f"startup_git_blob_sha:{rel}",
                blob_sha,
                binding.get("git_blob_sha"),
            )
            _check(
                assertions,
                failures,
                f"startup_committed_byte_sha256:{rel}",
                hashlib.sha256(payload).hexdigest(),
                binding.get("committed_byte_sha256"),
            )
            documents[rel] = json.loads(payload.decode("utf-8"))
        except (
            KeyError,
            subprocess.CalledProcessError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            failures.append(f"startup_bound_input_invalid:{rel}")
    decision = documents.get(config["inputs"]["t04_freeze_decision_path"])
    plan = documents.get(config["inputs"]["t04_freeze_plan_path"])
    phase_b = documents.get(config["inputs"]["t04_phase_b_independent_validation_path"])
    if decision is not None:
        _check(
            assertions,
            failures,
            "startup_freeze_decision_status",
            decision.get("freeze_decision_status"),
            "passed",
        )
        _check(
            assertions,
            failures,
            "startup_freeze_decision_selected_count",
            decision.get("selected_version_count"),
            2,
        )
        _check(
            assertions,
            failures,
            "startup_freeze_decision_strict_core_count",
            decision.get("strict_core_only_count"),
            2,
        )
        _check(
            assertions,
            failures,
            "startup_freeze_decision_rejected_count",
            decision.get("rejected_decision_unit_count"),
            2,
        )
    if plan is not None:
        _check(
            assertions,
            failures,
            "startup_freeze_plan_status",
            plan.get("freeze_plan_status"),
            "passed",
        )
        _check(
            assertions,
            failures,
            "startup_freeze_plan_cardinality",
            plan.get("planned_state_version_count"),
            2,
        )
        normalized_versions = []
        for version in plan.get("planned_versions", []):
            normalized = dict(version)
            if "planned_state_version_id" in normalized:
                normalized["state_version_id"] = normalized.pop(
                    "planned_state_version_id"
                )
            normalized_versions.append(normalized)
        _check(
            assertions,
            failures,
            "startup_freeze_plan_exact_versions",
            normalized_versions,
            config["selected_versions"],
        )
    if phase_b is not None:
        _check(
            assertions,
            failures,
            "startup_phase_b_status",
            phase_b.get("status"),
            "passed",
        )
        _check(
            assertions,
            failures,
            "startup_phase_b_selected_count",
            phase_b.get("selected_cell_count"),
            2,
        )
        _check(
            assertions,
            failures,
            "startup_phase_b_strict_core_count",
            phase_b.get("strict_core_only_count"),
            2,
        )
        _check(
            assertions,
            failures,
            "startup_phase_b_rejected_pair_count",
            phase_b.get("rejected_pair_count"),
            2,
        )


def _independent_event_id(
    contract_version: str,
    state_version_id: str,
    security_id: str,
    cell_id: str,
    component_id: str,
    start_date: Any,
    qualification_time: Any,
) -> str:
    payload = {
        "contract_version": contract_version,
        "state_version_id": state_version_id,
        "security_id": security_id,
        "first_qualified_component_identity": {
            "source_candidate_cell_id": cell_id,
            "first_component_id": component_id,
            "first_component_start_date": start_date.isoformat()
            if hasattr(start_date, "isoformat")
            else str(start_date),
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
        package["independent_validation_path"] = validation_path.relative_to(
            ROOT
        ).as_posix()
        package_path.write_bytes(_canonical_json(package) + b"\n")
    manifest_path = run_dir / "r2_t05_output_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("artifacts", [])
        rel = validation_path.relative_to(ROOT).as_posix()
        replacement = {
            "path": rel,
            "sha256": _sha256_file(validation_path),
            "size_bytes": validation_path.stat().st_size,
        }
        entries = [row for row in entries if row.get("path") != rel]
        entries.append(replacement)
        manifest["artifacts"] = sorted(entries, key=lambda row: row["path"])
        manifest["artifact_count"] = len(manifest["artifacts"])
        manifest_path.write_bytes(_canonical_json(manifest) + b"\n")


def _validate_compact_audit_statuses(
    run_dir: Path, assertions: list[dict[str, Any]], failures: list[str]
) -> None:
    for name in COMPACT_AUDIT_STATUS_FILES:
        path = run_dir / name
        if not path.is_file():
            _check(assertions, failures, f"compact_audit_file:{name}", 0, 1)
            continue
        if path.suffix == ".json":
            document = json.loads(path.read_text(encoding="utf-8"))
            _check(
                assertions,
                failures,
                f"compact_audit_status:{name}",
                document.get("status"),
                "passed",
            )
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        failed_rows = sum(row.get("status") != "passed" for row in rows)
        _check(assertions, failures, f"compact_audit_status:{name}", failed_rows, 0)


def _ensure_independent_daily_component_map(con: duckdb.DuckDBPyConnection) -> None:
    """Build a validator-only component/transition map from source lineage.

    The production materializer has a separate temporary map.  This map is
    deliberately rebuilt from source event, bridge and reentry facts under a
    different name so the daily check cannot pass merely by repeating the
    production latest-membership query.
    """
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE iv_daily_component_map AS
        SELECT DISTINCT l.state_version_id,l.canonical_event_id,
               l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,
               e.first_component_id component_id
        FROM r2_t05_event_id_lineage l
        JOIN src.event_zone e
          ON e.candidate_cell_id=l.source_candidate_cell_id
         AND e.security_id=l.security_id
         AND e.scan_event_id=l.source_scan_event_id
        UNION
        SELECT DISTINCT l.state_version_id,l.canonical_event_id,
               l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,
               b.left_component_id
        FROM r2_t05_event_id_lineage l
        JOIN src.event_zone_bridge_segment b
          ON b.candidate_cell_id=l.source_candidate_cell_id
         AND b.security_id=l.security_id
         AND b.scan_event_id=l.source_scan_event_id
         AND b.merge_accepted
        UNION
        SELECT DISTINCT l.state_version_id,l.canonical_event_id,
               l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,
               b.right_component_id
        FROM r2_t05_event_id_lineage l
        JOIN src.event_zone_bridge_segment b
          ON b.candidate_cell_id=l.source_candidate_cell_id
         AND b.security_id=l.security_id
         AND b.scan_event_id=l.source_scan_event_id
         AND b.merge_accepted
        UNION
        SELECT DISTINCT l.state_version_id,l.canonical_event_id,
               l.source_candidate_cell_id,l.source_scan_event_id,l.security_id,
               r.source_component_id
        FROM r2_t05_event_id_lineage l
        JOIN src.reentry_attempt r
          ON r.candidate_cell_id=l.source_candidate_cell_id
         AND r.security_id=l.security_id
         AND r.scan_event_id=l.source_scan_event_id
        """
    )


def _independent_daily_asof_mismatch(
    con: duckdb.DuckDBPyConnection, state_version_id: str, primary_route_id: str
) -> int:
    _ensure_independent_daily_component_map(con)
    return con.execute(
        """
        WITH daily AS (
          SELECT d.state_version_id,d.security_id,d.trade_date,d.state_risk_set_eligible,
                 r.available_time,cr.candidate_cell_id
          FROM r2_canonical_daily_state d
          JOIN src.route_daily r
            ON r.route_id=? AND r.security_id=d.security_id AND r.trade_date=d.trade_date
          JOIN src.cell_registry cr ON cr.route_id=r.route_id
          WHERE d.state_version_id=?
        ), current_row AS (
          SELECT d.*,m.scan_event_id current_scan_event_id,
                 m.zone_status_as_of current_status,
                 m.event_zone_member current_event_zone_member,
                 m.is_raw_false_bridge current_is_raw_false_bridge,
                 m.prequalification_member current_prequalification_member,
                 m.unqualified_reentry_member current_unqualified_reentry_member,
                 l.canonical_event_id current_event_id
          FROM daily d
          LEFT JOIN LATERAL (
            SELECT m.scan_event_id,m.zone_status_as_of,m.event_zone_member,
                   m.is_raw_false_bridge,m.prequalification_member,
                   m.unqualified_reentry_member
            FROM src.event_zone_membership_daily m
            WHERE m.candidate_cell_id=d.candidate_cell_id
              AND m.security_id=d.security_id
              AND m.trade_date=d.trade_date
              AND m.available_time<=d.available_time
            ORDER BY m.available_time DESC,m.evaluation_time DESC,m.scan_event_id DESC
            LIMIT 1
          ) m ON true
          LEFT JOIN r2_t05_event_id_lineage l
            ON l.state_version_id=d.state_version_id
           AND l.source_candidate_cell_id=d.candidate_cell_id
           AND l.source_scan_event_id=m.scan_event_id
           AND l.security_id=d.security_id
        ), history_row AS (
          SELECT d.state_version_id,d.security_id,d.trade_date,
                 h.canonical_event_id history_event_id,h.event_status history_status
          FROM current_row d
          LEFT JOIN LATERAL (
            SELECT x.canonical_event_id,x.event_status,x.available_time,
                   x.source_trade_date,x.source_scan_event_id
            FROM (
              SELECT l.canonical_event_id,m.zone_status_as_of event_status,
                     m.available_time,m.trade_date source_trade_date,m.scan_event_id source_scan_event_id
              FROM src.event_zone_membership_daily m
              JOIN r2_t05_event_id_lineage l
                ON l.state_version_id=d.state_version_id
               AND l.source_candidate_cell_id=m.candidate_cell_id
               AND l.source_scan_event_id=m.scan_event_id
               AND l.security_id=m.security_id
              WHERE m.candidate_cell_id=d.candidate_cell_id
                AND m.security_id=d.security_id
                AND m.trade_date<=d.trade_date
                AND m.available_time<=d.available_time
              UNION ALL
              SELECT l.canonical_event_id,e.status,e.zone_finalization_time,
                     CAST(e.zone_finalization_time AS DATE),e.scan_event_id
              FROM src.event_zone e
              JOIN r2_t05_event_id_lineage l
                ON l.state_version_id=d.state_version_id
               AND l.source_candidate_cell_id=e.candidate_cell_id
               AND l.source_scan_event_id=e.scan_event_id
               AND l.security_id=e.security_id
              WHERE e.candidate_cell_id=d.candidate_cell_id
                AND e.security_id=d.security_id
                AND e.zone_finalization_time IS NOT NULL
                AND CAST(e.zone_finalization_time AS DATE)<=d.trade_date
                AND e.zone_finalization_time<=d.available_time
            ) x
            ORDER BY x.available_time DESC,x.source_trade_date DESC,x.source_scan_event_id DESC
            LIMIT 1
          ) h ON true
        ), expected AS (
          SELECT c.state_version_id,c.security_id,c.trade_date,
                 CASE WHEN c.current_scan_event_id IS NOT NULL THEN EXISTS (
                   SELECT 1
                   FROM iv_daily_component_map cm
                   JOIN src.qualified_component q
                     ON q.candidate_cell_id=cm.source_candidate_cell_id
                    AND q.security_id=cm.security_id
                    AND q.component_id=cm.component_id
                   WHERE cm.state_version_id=c.state_version_id
                     AND cm.canonical_event_id=c.current_event_id
                     AND cm.security_id=c.security_id
                     AND q.qualified
                     AND c.trade_date BETWEEN q.start_date AND q.end_date
                     AND q.event_qualification_time<=c.available_time
                 ) ELSE false END component_qualified_as_of,
                 coalesce(c.current_status,h.history_status,'NO_EVENT') event_status_as_of,
                 CASE
                   WHEN c.current_scan_event_id IS NOT NULL
                    AND c.current_status IN ('COMPONENT_FORMING','QUALIFIED_ACTIVE','GAP_PENDING','REENTRY_PENDING_QUALIFICATION')
                   THEN c.current_event_id
                   WHEN c.current_scan_event_id IS NULL
                    AND h.history_status IN ('COMPONENT_FORMING','QUALIFIED_ACTIVE','GAP_PENDING','REENTRY_PENDING_QUALIFICATION')
                   THEN h.history_event_id
                   ELSE NULL
                 END active_event_id_as_of,
                 c.state_risk_set_eligible
                   AND c.current_scan_event_id IS NOT NULL
                   AND coalesce(c.current_event_zone_member,false)
                   AND EXISTS (
                     SELECT 1
                     FROM iv_daily_component_map cm
                     JOIN src.qualified_component q
                       ON q.candidate_cell_id=cm.source_candidate_cell_id
                      AND q.security_id=cm.security_id
                      AND q.component_id=cm.component_id
                     WHERE cm.state_version_id=c.state_version_id
                       AND cm.canonical_event_id=c.current_event_id
                       AND cm.security_id=c.security_id
                       AND q.qualified
                       AND c.trade_date BETWEEN q.start_date AND q.end_date
                       AND q.event_qualification_time<=c.available_time
                   )
                   AND NOT coalesce(c.current_is_raw_false_bridge,false)
                   AND NOT coalesce(c.current_prequalification_member,false)
                   AND NOT coalesce(c.current_unqualified_reentry_member,false)
                   qualified_event_risk_set_eligible
          FROM current_row c
          LEFT JOIN history_row h USING(state_version_id,security_id,trade_date)
        )
        SELECT count(*) FROM r2_canonical_daily_state d
        JOIN expected e USING(state_version_id,security_id,trade_date)
        WHERE d.component_qualified_as_of IS DISTINCT FROM e.component_qualified_as_of
           OR d.event_status_as_of IS DISTINCT FROM e.event_status_as_of
           OR d.active_event_id_as_of IS DISTINCT FROM e.active_event_id_as_of
           OR d.qualified_event_risk_set_eligible IS DISTINCT FROM e.qualified_event_risk_set_eligible
        """,
        [primary_route_id, state_version_id],
    ).fetchone()[0]


def validate_formal_output(run_dir: Path, repo: Path = ROOT) -> dict[str, Any]:
    config = _git_json(
        repo, "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json"
    )
    input_binding = json.loads(
        (run_dir / "r2_t05_input_binding.json").read_text(encoding="utf-8")
    )
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
        validation = {
            "task_id": "R2-T05",
            "run_id": run_dir.name,
            "status": "failed",
            "failure_count": len(failures),
            "failures": failures,
            "assertions": assertions,
            "validation_mode": "independent_sql_and_lineage_recalculation",
        }
        _refresh_package(run_dir, validation)
        return validation
    con = duckdb.connect(str(output_db), read_only=False)
    con.execute(f"ATTACH '{_sql_path(source_db)}' AS src (READ_ONLY)")
    output_tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    required_output = {
        "r2_canonical_daily_state",
        "r2_canonical_event_zone",
        "r2_canonical_event_membership",
        "r2_t05_event_id_lineage",
    }
    _check(
        assertions,
        failures,
        "required_output_tables",
        len(required_output - output_tables),
        0,
    )
    daily_columns = (
        {row[0] for row in con.execute("DESCRIBE r2_canonical_daily_state").fetchall()}
        if "r2_canonical_daily_state" in output_tables
        else set()
    )
    _check(
        assertions,
        failures,
        "daily_required_qualified_event_risk_field",
        "qualified_event_risk_set_eligible" in daily_columns,
        True,
    )
    selected = config["selected_versions"]
    expected_daily = con.execute(
        "SELECT count(*) FROM src.base_expected_security_date"
    ).fetchone()[0]
    _check(
        assertions,
        failures,
        "authoritative_daily_key_count_positive",
        expected_daily > 0,
        True,
    )
    _check(
        assertions,
        failures,
        "daily_version_count",
        con.execute(
            "SELECT count(distinct state_version_id) FROM r2_canonical_daily_state"
        ).fetchone()[0],
        2,
    )
    _check(
        assertions,
        failures,
        "event_version_count",
        con.execute(
            "SELECT count(distinct state_version_id) FROM r2_canonical_event_zone"
        ).fetchone()[0],
        2,
    )
    _check(
        assertions,
        failures,
        "W250_exclusion",
        con.execute(
            "SELECT count(*) FROM r2_canonical_daily_state WHERE state_version_id LIKE '%W250%' OR state_version_id LIKE '%W250%'"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "shared_event_exclusion",
        con.execute(
            "SELECT count(*) FROM r2_t05_event_id_lineage WHERE source_candidate_cell_id LIKE '%shared%'"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "daily_duplicate_primary_key",
        con.execute(
            "SELECT count(*)-count(distinct (state_version_id,security_id,trade_date)) FROM r2_canonical_daily_state"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "event_duplicate_primary_key",
        con.execute(
            "SELECT count(*)-count(distinct (state_version_id,event_id)) FROM r2_canonical_event_zone"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "membership_duplicate_primary_key",
        con.execute(
            "SELECT count(*)-count(distinct (state_version_id,event_id,security_id,trade_date)) FROM r2_canonical_event_membership"
        ).fetchone()[0],
        0,
    )
    for version in selected:
        cell = version["source_candidate_cell_id"]
        strict_cell = version["strict_core_source_candidate_cell_id"]
        primary_route = con.execute(
            "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?", [cell]
        ).fetchone()
        strict_route = con.execute(
            "SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=?",
            [strict_cell],
        ).fetchone()
        if not primary_route or not strict_route:
            failures.append(f"route_missing:{cell}")
            continue
        state = version["state_version_id"]
        _check(
            assertions,
            failures,
            f"daily_row_count:{state}",
            con.execute(
                "SELECT count(*) FROM r2_canonical_daily_state WHERE state_version_id=?",
                [state],
            ).fetchone()[0],
            expected_daily,
        )
        missing = con.execute(
            """
          SELECT count(*) FROM src.base_expected_security_date b
          LEFT JOIN r2_canonical_daily_state d ON d.state_version_id=? AND d.security_id=b.security_id AND d.trade_date=b.trade_date
          WHERE d.security_id IS NULL
        """,
            [state],
        ).fetchone()[0]
        extra = con.execute(
            """
          SELECT count(*) FROM r2_canonical_daily_state d
          LEFT JOIN src.base_expected_security_date b ON b.security_id=d.security_id AND b.trade_date=d.trade_date
          WHERE d.state_version_id=? AND b.security_id IS NULL
        """,
            [state],
        ).fetchone()[0]
        _check(assertions, failures, f"daily_key_surface_missing:{state}", missing, 0)
        _check(assertions, failures, f"daily_key_surface_extra:{state}", extra, 0)
        daily_mismatch = con.execute(
            """
          SELECT count(*) FROM r2_canonical_daily_state d JOIN src.route_daily r
            ON r.route_id=? AND r.security_id=d.security_id AND r.trade_date=d.trade_date
          WHERE d.state_version_id=? AND (d.raw_state IS DISTINCT FROM r.raw_state OR d.confirmed_state IS DISTINCT FROM r.confirmed_state
             OR d.confirmation_time IS DISTINCT FROM r.confirmation_time OR d.eligible_state IS DISTINCT FROM r.eligible
             OR d.quality_state IS DISTINCT FROM r.quality_state OR d.state_risk_set_eligible IS DISTINCT FROM r.state_risk_set_eligible)
        """,
            [primary_route[0], state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"daily_source_fact_reconciliation:{state}",
            daily_mismatch,
            0,
        )
        daily_asof_mismatch = _independent_daily_asof_mismatch(
            con, state, primary_route[0]
        )
        _check(
            assertions,
            failures,
            f"daily_asof_independent_recalculation:{state}",
            daily_asof_mismatch,
            0,
        )
        qualified_key_mismatch = con.execute(
            """
            WITH daily_keys AS (
              SELECT security_id,trade_date
              FROM r2_canonical_daily_state
              WHERE state_version_id=? AND qualified_event_risk_set_eligible
            ), membership_keys AS (
              SELECT security_id,trade_date
              FROM r2_canonical_event_membership
              WHERE state_version_id=? AND qualified_event_risk_set_eligible
            )
            SELECT (SELECT count(*) FROM (SELECT * FROM daily_keys EXCEPT SELECT * FROM membership_keys))
                 + (SELECT count(*) FROM (SELECT * FROM membership_keys EXCEPT SELECT * FROM daily_keys))
            """,
            [state, state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"daily_qualified_event_risk_exact_keys:{state}",
            qualified_key_mismatch,
            0,
        )
        component_key_mismatch = con.execute(
            """
            WITH daily_keys AS (
              SELECT security_id,trade_date
              FROM r2_canonical_daily_state
              WHERE state_version_id=? AND component_qualified_as_of
            ), membership_keys AS (
              SELECT security_id,trade_date
              FROM r2_canonical_event_membership
              WHERE state_version_id=? AND component_qualified_as_of
            )
            SELECT (SELECT count(*) FROM (SELECT * FROM daily_keys EXCEPT SELECT * FROM membership_keys))
                 + (SELECT count(*) FROM (SELECT * FROM membership_keys EXCEPT SELECT * FROM daily_keys))
            """,
            [state, state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"daily_component_qualification_exact_keys:{state}",
            component_key_mismatch,
            0,
        )
        transition_mismatch = con.execute(
            """
            SELECT count(*)
            FROM r2_canonical_daily_state d
            JOIN src.route_daily r
              ON r.route_id=(SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=d.candidate_config_id)
             AND r.security_id=d.security_id
             AND r.trade_date=d.trade_date
            JOIN src.event_zone_membership_daily sm
              ON sm.candidate_cell_id=d.candidate_config_id
             AND sm.security_id=d.security_id
             AND sm.trade_date=d.trade_date
             AND sm.available_time<=r.available_time
            JOIN r2_t05_event_id_lineage l
              ON l.state_version_id=d.state_version_id
             AND l.source_candidate_cell_id=sm.candidate_cell_id
             AND l.source_scan_event_id=sm.scan_event_id
             AND l.security_id=sm.security_id
            JOIN iv_daily_component_map cm
              ON cm.state_version_id=l.state_version_id
             AND cm.canonical_event_id=l.canonical_event_id
             AND cm.security_id=d.security_id
            JOIN src.qualified_component q
              ON q.candidate_cell_id=cm.source_candidate_cell_id
             AND q.security_id=cm.security_id
             AND q.component_id=cm.component_id
            WHERE d.state_version_id=? AND q.qualified
              AND d.trade_date BETWEEN q.start_date AND q.end_date
              AND d.component_qualified_as_of IS DISTINCT FROM
                  (q.event_qualification_time<=r.available_time)
            """,
            [state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"daily_component_qualification_transition_lineage:{state}",
            transition_mismatch,
            0,
        )
        unqualified_reentry_mismatch = con.execute(
            """
            SELECT count(*)
            FROM r2_canonical_daily_state d
            JOIN src.reentry_attempt r
              ON r.candidate_cell_id=d.candidate_config_id
             AND r.security_id=d.security_id
             AND d.trade_date BETWEEN r.start_date AND r.end_date
             AND r.outcome='unqualified_reentry'
            WHERE d.state_version_id=?
              AND (d.component_qualified_as_of OR d.qualified_event_risk_set_eligible)
            """,
            [state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"daily_unqualified_reentry_all_false:{state}",
            unqualified_reentry_mismatch,
            0,
        )
        accepted_reentry_first_day = con.execute(
            """
            SELECT count(*)
            FROM r2_canonical_daily_state d
            JOIN src.event_zone_bridge_segment b
              ON b.candidate_cell_id=d.candidate_config_id
             AND b.security_id=d.security_id
             AND b.merge_accepted
            JOIN r2_t05_event_id_lineage l
              ON l.state_version_id=d.state_version_id
             AND l.source_candidate_cell_id=b.candidate_cell_id
             AND l.source_scan_event_id=b.scan_event_id
             AND l.security_id=b.security_id
            JOIN src.qualified_component q
              ON q.candidate_cell_id=b.candidate_cell_id
             AND q.security_id=b.security_id
             AND q.component_id=b.right_component_id
             AND q.qualified
            WHERE d.state_version_id=?
              AND d.trade_date=q.start_date
              AND d.component_qualified_as_of
            """,
            [state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"daily_accepted_reentry_first_day_false:{state}",
            accepted_reentry_first_day,
            0,
        )
        accepted_reentry_qualification_day = con.execute(
            """
            SELECT count(*)
            FROM r2_canonical_daily_state d
            JOIN src.event_zone_bridge_segment b
              ON b.candidate_cell_id=d.candidate_config_id
             AND b.security_id=d.security_id
             AND b.merge_accepted
            JOIN r2_t05_event_id_lineage l
              ON l.state_version_id=d.state_version_id
             AND l.source_candidate_cell_id=b.candidate_cell_id
             AND l.source_scan_event_id=b.scan_event_id
             AND l.security_id=b.security_id
            JOIN src.qualified_component q
              ON q.candidate_cell_id=b.candidate_cell_id
             AND q.security_id=b.security_id
             AND q.component_id=b.right_component_id
             AND q.qualified
            JOIN src.route_daily r
              ON r.route_id=(SELECT route_id FROM src.cell_registry WHERE candidate_cell_id=d.candidate_config_id)
             AND r.security_id=d.security_id
             AND r.trade_date=d.trade_date
            WHERE d.state_version_id=?
              AND q.event_qualification_time<=r.available_time
              AND NOT d.component_qualified_as_of
            """,
            [state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"daily_accepted_reentry_qualification_day_true:{state}",
            accepted_reentry_qualification_day,
            0,
        )
        strict_mismatch = con.execute(
            """
          SELECT count(*) FROM r2_canonical_daily_state d JOIN src.route_daily s
            ON s.route_id=? AND s.security_id=d.security_id AND s.trade_date=d.trade_date
          WHERE d.state_version_id=? AND d.strict_core_member IS DISTINCT FROM s.confirmed_state
        """,
            [strict_route[0], state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"strict_core_exact_key_recalculation:{state}",
            strict_mismatch,
            0,
        )
        _check(
            assertions,
            failures,
            f"strict_core_subset:{state}",
            con.execute(
                "SELECT count(*) FROM r2_canonical_daily_state WHERE state_version_id=? AND strict_core_member AND NOT confirmed_state",
                [state],
            ).fetchone()[0],
            0,
        )
        source_events = con.execute(
            "SELECT count(*) FROM src.event_zone WHERE candidate_cell_id=?", [cell]
        ).fetchone()[0]
        canonical_events = con.execute(
            "SELECT count(*) FROM r2_canonical_event_zone WHERE state_version_id=?",
            [state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"event_count_reconciliation:{state}",
            canonical_events,
            source_events,
        )
        source_membership = con.execute(
            "SELECT count(*) FROM src.event_zone_membership_daily WHERE candidate_cell_id=?",
            [cell],
        ).fetchone()[0]
        lineage_membership = con.execute(
            """
          SELECT count(*) FROM src.event_zone_membership_daily m JOIN r2_t05_event_id_lineage l
            ON l.source_candidate_cell_id=m.candidate_cell_id AND l.source_scan_event_id=m.scan_event_id AND l.security_id=m.security_id
          WHERE l.state_version_id=?
        """,
            [state],
        ).fetchone()[0]
        _check(
            assertions,
            failures,
            f"membership_source_join_count:{state}",
            lineage_membership,
            source_membership,
        )
    _check(
        assertions,
        failures,
        "daily_qualified_event_risk_implies_state_risk",
        con.execute(
            "SELECT count(*) FROM r2_canonical_daily_state WHERE qualified_event_risk_set_eligible AND (NOT state_risk_set_eligible OR NOT confirmed_state)"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "daily_qualified_event_risk_no_active_event",
        con.execute(
            "SELECT count(*) FROM r2_canonical_daily_state WHERE qualified_event_risk_set_eligible AND active_event_id_as_of IS NULL"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "daily_active_event_same_state_security_fk",
        con.execute("""
      SELECT count(*) FROM r2_canonical_daily_state d
      LEFT JOIN r2_canonical_event_zone e
        ON e.state_version_id=d.state_version_id AND e.security_id=d.security_id AND e.event_id=d.active_event_id_as_of
      WHERE d.active_event_id_as_of IS NOT NULL AND e.event_id IS NULL
    """).fetchone()[0],
        0,
    )
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
        if (
            _independent_event_id(
                config["contract_version"],
                row[0],
                row[3],
                row[1],
                row[4],
                row[6],
                row[7],
            )
            != row[5]
        ):
            id_mismatch += 1
    _check(assertions, failures, "event_id_independent_recalculation", id_mismatch, 0)
    _check(
        assertions,
        failures,
        "event_id_source_scan_one_to_one",
        len(event_rows),
        con.execute(
            "SELECT count(distinct (state_version_id,source_scan_event_id)) FROM r2_t05_event_id_lineage"
        ).fetchone()[0],
    )
    _check(
        assertions,
        failures,
        "event_id_cross_state_security_collision",
        con.execute(
            "SELECT count(*)-count(distinct (state_version_id,canonical_event_id)) FROM r2_t05_event_id_lineage"
        ).fetchone()[0],
        0,
    )
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
    _check(
        assertions, failures, "membership_row_level_reconciliation", member_mismatch, 0
    )
    _check(
        assertions,
        failures,
        "membership_availability_not_before_source_row",
        con.execute("""
      SELECT count(*) FROM r2_canonical_event_membership c JOIN r2_t05_event_id_lineage l
        ON l.state_version_id=c.state_version_id AND l.canonical_event_id=c.event_id
      JOIN src.cell_registry cr ON cr.candidate_cell_id=l.source_candidate_cell_id
      JOIN src.route_daily r ON r.route_id=cr.route_id AND r.security_id=c.security_id AND r.trade_date=c.trade_date
      WHERE c.membership_available_time<r.available_time
    """).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "risk_formula_recalculation",
        con.execute("""
      SELECT count(*) FROM r2_canonical_event_membership c
      JOIN r2_t05_event_id_lineage l
        ON l.state_version_id=c.state_version_id AND l.canonical_event_id=c.event_id
      JOIN src.cell_registry cr ON cr.candidate_cell_id=l.source_candidate_cell_id
      JOIN src.route_daily r ON r.route_id=cr.route_id AND r.security_id=c.security_id AND r.trade_date=c.trade_date
      WHERE c.state_risk_set_eligible IS DISTINCT FROM (r.eligible AND r.quality_state='valid' AND r.confirmed_state)
    """).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "bridge_and_prequalification_risk_exclusion",
        con.execute(
            "SELECT count(*) FROM r2_canonical_event_membership WHERE (is_bridged_gap OR is_prequalification_confirmed_day OR is_unqualified_reentry_day) AND qualified_event_risk_set_eligible"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "bridge_confirmed_truth",
        con.execute(
            "SELECT count(*) FROM r2_canonical_event_membership WHERE is_bridged_gap AND confirmed_state"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "event_revision_monotonic",
        con.execute("""
      SELECT count(*) FROM (SELECT zone_revision,lag(zone_revision) OVER(PARTITION BY state_version_id,event_id ORDER BY membership_available_time,trade_date) prior_revision FROM r2_canonical_event_membership WHERE event_zone_member) x WHERE prior_revision IS NOT NULL AND zone_revision<prior_revision
    """).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "quality_break_not_natural_exit",
        con.execute(
            "SELECT count(*) FROM r2_canonical_event_zone WHERE zone_status='FINALIZED_WITH_QUALITY_BREAK' AND exit_reason NOT IN ('quality_break')"
        ).fetchone()[0],
        0,
    )
    _check(
        assertions,
        failures,
        "right_censor_no_finalization",
        con.execute(
            "SELECT count(*) FROM r2_canonical_event_zone WHERE right_censored AND zone_finalization_time IS NOT NULL"
        ).fetchone()[0],
        0,
    )
    # Schema/field scan and manifest binding checks.
    forbidden = []
    for table in output_tables:
        for column in con.execute(f'DESCRIBE "{table}"').fetchall():
            name = column[0].lower()
            if any(
                token in name
                for token in {
                    "future_return",
                    "future_direction",
                    "release_label",
                    "precision",
                    "recall",
                    "backtest",
                    "winner",
                    "trading_efficacy",
                }
            ):
                forbidden.append(f"{table}.{column[0]}")
    _check(assertions, failures, "forbidden_field_scan", len(forbidden), 0)
    manifest = json.loads(
        (run_dir / "r2_t05_output_manifest.json").read_text(encoding="utf-8")
    )
    manifest_failures = 0
    for artifact in manifest.get("artifacts", []):
        path = repo / Path(artifact["path"])
        if path.suffix == ".duckdb":
            continue
        if not path.is_file() or _sha256_file(path) != artifact.get("sha256"):
            manifest_failures += 1
    _check(assertions, failures, "output_manifest_hashes", manifest_failures, 0)
    fingerprints = json.loads(
        (run_dir / "r2_t05_table_fingerprint.json").read_text(encoding="utf-8")
    )
    fingerprint_failures = 0
    for table, profile in fingerprints.get("tables", {}).items():
        if table not in output_tables or con.execute(
            f'SELECT count(*) FROM "{table}"'
        ).fetchone()[0] != profile.get("row_count"):
            fingerprint_failures += 1
    _check(
        assertions,
        failures,
        "output_table_fingerprint_row_counts",
        fingerprint_failures,
        0,
    )
    _validate_compact_audit_statuses(run_dir, assertions, failures)
    package_path = run_dir / "r2_t05_result_package.json"
    if package_path.is_file():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        _check(
            assertions,
            failures,
            "package_anomaly_scan_status",
            package.get("anomaly_scan_status"),
            "passed",
        )
    con.close()
    validation = {
        "task_id": "R2-T05",
        "run_id": run_dir.name,
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "assertions": assertions,
        "validation_mode": "independent_sql_and_lineage_recalculation",
        "source_database_sha256": actual_sha,
        "source_database_path": source_rel,
        "output_database_sha256": _sha256_file(output_db),
        "selected_version_count": 2,
        "canonical_event_id_algorithm": "independent_sha256_recalculation",
    }
    _refresh_package(run_dir, validation)
    return validation


__all__ = ["R2T05IndependentValidationError", "validate_formal_output"]


def validate_committed_artifacts(
    run_dir: Path, repo: Path = ROOT, commit: str | None = None
) -> dict[str, Any]:
    """Validate committed compact artifact bytes and local row-level DB binding."""
    import subprocess

    commit = (
        commit
        or subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    manifest_path = run_dir / "r2_t05_output_manifest.json"
    failures: list[str] = []
    if not manifest_path.is_file():
        failures.append("output_manifest_missing")
        result = {
            "task_id": "R2-T05",
            "run_id": run_dir.name,
            "status": "failed",
            "failure_count": len(failures),
            "failures": failures,
            "validation_mode": "committed_artifact_bytes",
        }
        (run_dir / "r2_t05_committed_artifact_validation.json").write_bytes(
            _canonical_json(result) + b"\n"
        )
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
        if (
            b"\r" in payload
            or payload.startswith(b"\xef\xbb\xbf")
            or not payload.endswith(b"\n")
            or payload.endswith(b"\n\n")
        ):
            failures.append(f"artifact_noncanonical_text:{rel}")
        if _sha256_file(path) != artifact.get("sha256"):
            failures.append(f"artifact_hash_mismatch:{rel}")
    for binding in json.loads(
        (run_dir / "r2_t05_input_binding.json").read_text(encoding="utf-8")
    ).get("source_bindings", []):
        rel = binding["path"]
        try:
            blob = subprocess.run(
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
            if blob_sha != binding.get("git_blob_sha"):
                failures.append(f"input_blob_mismatch:{rel}")
            if hashlib.sha256(blob).hexdigest() != binding.get("committed_byte_sha256"):
                failures.append(f"input_byte_hash_mismatch:{rel}")
        except subprocess.CalledProcessError:
            failures.append(f"input_blob_missing:{rel}")
    db_path = (
        run_dir
        / json.loads(
            (run_dir / "r2_t05_output_manifest.json").read_text(encoding="utf-8")
        )
        .get("database_path", "")
        .split("/")[-1]
    )
    # The manifest path is repository-relative; resolve it directly when present.
    database_rel = manifest.get("database_path")
    database = repo / Path(database_rel) if database_rel else db_path
    if not database.is_file():
        failures.append("canonical_database_missing")
    elif manifest.get("database_sha256") and _sha256_file(database) != manifest.get(
        "database_sha256"
    ):
        failures.append("canonical_database_hash_mismatch")
    result = {
        "task_id": "R2-T05",
        "run_id": run_dir.name,
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "validation_mode": "committed_artifact_bytes",
        "validated_commit": commit,
        "manifest_path": manifest_path.relative_to(repo).as_posix(),
    }
    (run_dir / validation_name).write_bytes(_canonical_json(result) + b"\n")
    return result


__all__ += ["validate_committed_artifacts"]
