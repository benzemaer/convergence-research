"""Fail-closed materializer for the immutable R2A-T01 PCAVT score release."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import shutil
import uuid
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator, FormatChecker

from src.common.canonical_io import formal_source_binding
from src.r2a.r2a_t01_artifact_manifest import (
    FORMAL_EXECUTION_SURFACE,
    TABLE_ORDER,
    build_manifest,
    write_schema,
)
from src.r2a.r2a_t01_formal_input_adapter import (
    FORMAL_INPUT_ORDER,
    FormalInputAdapter,
)
from src.r2a.r2a_t01_input_manifest import load_bound_inputs, sha256_file
from src.r2a.score_engine import (
    A_COMPONENTS,
    COMPONENTS_BY_DIMENSION,
    DIMENSION_ORDER,
    ENGINE_VERSION,
    PERCENTILE_WINDOW,
    TIE_METHOD,
    compute_a_dimension_scores,
    compute_component_scores,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "configs/r2a/r2a_t01_pcavt_score_release.v1.json"
DEFAULT_POLICY_PATH = ROOT / "configs/r2a/r2a_t01_eod_availability_policy.v1.json"
PCVT_DIMENSIONS = ("P", "C", "V", "T")
PCVT_COMPONENTS = tuple(
    component
    for dimension in PCVT_DIMENSIONS
    for component in COMPONENTS_BY_DIMENSION[dimension]
)
EXPECTED_INPUTS = (
    "securities",
    "trading_sessions",
    "security_observation_spine",
    "pcvt_component_scores",
    "pcvt_dimension_scores",
    "a_raw_observations",
    "pcvt_validation_raw",
)
MATERIALIZATION_INPUTS = EXPECTED_INPUTS[:-1]


class ScoreReleaseError(RuntimeError):
    """Raised when a release cannot be materialized atomically."""


def materialize_score_release(
    *,
    authorized_input_manifest: str | Path,
    output_dir: str | Path,
    run_id: str,
    expected_score_release_id: str | None = None,
    worker_count: int = 1,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    availability_policy_path: str | Path = DEFAULT_POLICY_PATH,
    synthetic_only: bool = True,
    execution_commit: str | None = None,
) -> Path:
    """Build the seven-table package; the release ID is always content-derived."""

    if worker_count < 1:
        raise ScoreReleaseError("worker_count_must_be_positive")
    target = Path(output_dir).resolve()
    if target.exists():
        raise ScoreReleaseError("output_directory_already_exists")
    config = _load_json(config_path)
    policy = _load_json(availability_policy_path)
    _validate_json_contract(
        config, ROOT / "schemas/r2a/r2a_t01_pcavt_score_release_config.schema.json"
    )
    _validate_json_contract(
        policy, ROOT / "schemas/r2a/r2a_t01_eod_availability_policy.schema.json"
    )
    _validate_runtime_contract(config, policy)
    input_manifest_path = Path(authorized_input_manifest).resolve()
    input_manifest = _load_json(input_manifest_path)
    preflight_bindings: dict[str, dict[str, Any]] = {}
    if synthetic_only:
        if input_manifest.get("synthetic_only") is not True:
            raise ScoreReleaseError("synthetic_run_requires_synthetic_manifest")
        _reject_formal_output_path(target)
    else:
        if not (
            config.get("formal_run_allowed") is True
            and config.get("real_input_read_allowed") is True
            and input_manifest.get("synthetic_only") is False
        ):
            raise ScoreReleaseError("formal_run_not_authorized")
        if (
            not execution_commit
            or input_manifest.get("source_commit") != execution_commit
        ):
            raise ScoreReleaseError("formal_input_execution_commit_mismatch")
        _require_formal_output_path(target)
        preflight_bindings = {
            relative: formal_source_binding(
                ROOT / relative, execution_commit, root=ROOT
            )
            for relative in FORMAL_EXECUTION_SURFACE
        }

    release_id, preimage_hash = compute_score_release_id(
        config=config,
        availability_policy_path=availability_policy_path,
        input_manifest=input_manifest,
        availability_policy_sha256=(
            preflight_bindings[
                Path(availability_policy_path).resolve().relative_to(ROOT).as_posix()
            ]["committed_byte_sha256"]
            if preflight_bindings
            else None
        ),
    )
    if (
        expected_score_release_id is not None
        and expected_score_release_id != release_id
    ):
        raise ScoreReleaseError("expected_score_release_id_mismatch")

    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        staging_path = temporary / "staging.duckdb"
        if synthetic_only:
            input_summary = _stage_synthetic_inputs(input_manifest_path, staging_path)
            authorization_id = None
        else:
            adapter = FormalInputAdapter(input_manifest_path)
            input_summary = _stage_formal_inputs(adapter, staging_path)
            authorization_id = adapter.authorization_id
        _validate_staging(staging_path)
        _materialize_staged_release(
            staging_path=staging_path,
            database_path=temporary / "score_data.duckdb",
            shard_dir=temporary / "a_score_shards",
            score_release_id=release_id,
            worker_count=worker_count,
        )
        if not synthetic_only:
            _enforce_formal_cardinality(temporary / "score_data.duckdb")
        staging_path.unlink()
        shutil.rmtree(temporary / "a_score_shards", ignore_errors=True)
        write_schema(temporary / "schema.json")
        build_manifest(
            package_dir=temporary,
            run_id=run_id,
            score_release_id=release_id,
            score_release_preimage_sha256=preimage_hash,
            authorized_input_manifest=input_manifest_path,
            input_summary=input_summary,
            formal_authorization_id=authorization_id,
            config_path=config_path,
            availability_policy_path=availability_policy_path,
            worker_count=worker_count,
            synthetic_only=synthetic_only,
            execution_commit=execution_commit,
        )
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def compute_score_release_id(
    *,
    config: Mapping[str, Any],
    availability_policy_path: str | Path,
    input_manifest: Mapping[str, Any],
    availability_policy_sha256: str | None = None,
) -> tuple[str, str]:
    """Return the canonical release ID and its full canonical-preimage hash."""

    inputs = input_manifest.get("inputs")
    if not isinstance(inputs, Mapping) or tuple(inputs) != EXPECTED_INPUTS:
        if not isinstance(inputs, Mapping) or set(inputs) != set(EXPECTED_INPUTS):
            raise ScoreReleaseError("input_set_mismatch")
    ordered_hashes = [str(inputs[name]["sha256"]) for name in MATERIALIZATION_INPUTS]
    preimage = {
        "release_contract_id": config["release_contract_id"],
        "dimension_definition_version": config["dimension_definition_version"],
        "percentile_window_W": config["percentile_window"],
        "availability_policy_sha256": (
            availability_policy_sha256 or sha256_file(availability_policy_path)
        ),
        "ordered_materialization_input_sha256s": ordered_hashes,
    }
    canonical = json.dumps(
        preimage, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f"pcavt-score-w120-v1-{digest[:16]}", digest


def _stage_synthetic_inputs(
    manifest_path: Path, staging_path: Path
) -> dict[str, dict[str, Any]]:
    rows = load_bound_inputs(manifest_path)
    manifest = _load_json(manifest_path)
    with duckdb.connect(str(staging_path)) as connection:
        for name in EXPECTED_INPUTS:
            table = pa.Table.from_pylist(rows[name])
            registration = f"arrow_{name}"
            connection.register(registration, table)
            connection.execute(
                f'CREATE TABLE "stage_{name}" AS SELECT * FROM "{registration}"'
            )
            connection.unregister(registration)
        connection.execute("CHECKPOINT")
    return {
        name: {
            "sha256": manifest["inputs"][name]["sha256"],
            "byte_size": manifest["inputs"][name]["byte_size"],
            "input_role": (
                "validation_only"
                if name == "pcvt_validation_raw"
                else "materialization"
            ),
        }
        for name in EXPECTED_INPUTS
    }


def _stage_formal_inputs(
    adapter: FormalInputAdapter, staging_path: Path
) -> dict[str, dict[str, Any]]:
    """Native DuckDB staging path; deliberately independent of the JSON-array loader."""

    with duckdb.connect(str(staging_path)) as connection:
        relations = adapter.attach_and_validate(connection)
        for name in FORMAL_INPUT_ORDER:
            connection.execute(
                f'CREATE TABLE "stage_{name}" AS SELECT * FROM {relations[name]}'
            )
        connection.execute("CHECKPOINT")
    return adapter.depathized_summary()


def _validate_staging(staging_path: Path) -> None:
    with duckdb.connect(str(staging_path), read_only=True) as connection:
        required_tables = {f"stage_{name}" for name in EXPECTED_INPUTS}
        actual = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        if actual != required_tables:
            raise ScoreReleaseError("staging_table_set_mismatch")
        _validate_staging_columns(connection)
        if connection.execute(
            "SELECT count(*) FROM (SELECT session_sequence,count(*) n FROM "
            "stage_trading_sessions GROUP BY 1 HAVING n<>1)"
        ).fetchone()[0]:
            raise ScoreReleaseError("duplicate_session_sequence")
        if connection.execute(
            "SELECT count(*) FROM (SELECT trading_date,count(*) n FROM "
            "stage_trading_sessions GROUP BY 1 HAVING n<>1)"
        ).fetchone()[0]:
            raise ScoreReleaseError("duplicate_trading_date")
        sequence_check = connection.execute(
            "SELECT min(session_sequence),max(session_sequence),count(*) "
            "FROM stage_trading_sessions"
        ).fetchone()
        if sequence_check[0] != 0 or sequence_check[1] + 1 != sequence_check[2]:
            raise ScoreReleaseError("trading_session_sequence_gap")
        duplicate_spine = connection.execute(
            "SELECT count(*) FROM (SELECT security_id,trading_date,count(*) n FROM "
            "stage_security_observation_spine GROUP BY 1,2 HAVING n<>1)"
        ).fetchone()[0]
        if duplicate_spine:
            raise ScoreReleaseError("duplicate_spine_key")
        spine_gaps = connection.execute(
            "SELECT count(*) FROM (SELECT security_id,min(observation_sequence) lo,"
            "max(observation_sequence) hi,count(*) n,count(DISTINCT observation_sequence) d "
            "FROM stage_security_observation_spine GROUP BY 1 "
            "HAVING lo<>0 OR hi+1<>n OR d<>n)"
        ).fetchone()[0]
        if spine_gaps:
            raise ScoreReleaseError("spine_observation_sequence_gap")
        mismatched = connection.execute(
            "SELECT count(*) FROM stage_security_observation_spine s "
            "LEFT JOIN stage_trading_sessions t USING(trading_date) "
            "WHERE t.trading_date IS NULL OR s.observation_sequence<>t.session_sequence"
        ).fetchone()[0]
        if mismatched:
            raise ScoreReleaseError("spine_session_sequence_mismatch")
        invalid_status = connection.execute(
            "SELECT count(*) FROM stage_security_observation_spine WHERE "
            "expected_observation_status NOT IN ('present','missing','listing_pause')"
        ).fetchone()[0]
        if invalid_status:
            raise ScoreReleaseError("invalid_expected_observation_status")
        _validate_source_keys(connection)


def _validate_staging_columns(connection: duckdb.DuckDBPyConnection) -> None:
    required = {
        "securities": {
            "security_id",
            "universe_id",
            "first_expected_date",
            "last_expected_date",
            "expected_observation_count",
        },
        "trading_sessions": {
            "trading_date",
            "session_sequence",
            "expected_security_count",
            "present_security_count",
            "available_time",
        },
        "security_observation_spine": {
            "security_id",
            "trading_date",
            "observation_sequence",
            "expected_observation_status",
            "source_contract",
            "source_ref",
            "observation_available_time",
        },
        "pcvt_component_scores": {
            "security_id",
            "trading_date",
            "observation_sequence",
            "dimension_id",
            "component_id",
            "percentile_window_W",
            "raw_value",
            "percentile",
            "score",
            "eligible",
            "validity_status",
            "reason_codes",
            "reference_observation_count",
            "reference_window_start",
            "reference_window_end",
            "score_engine_version",
            "source_run_id",
        },
        "pcvt_dimension_scores": {
            "security_id",
            "trading_date",
            "observation_sequence",
            "dimension_id",
            "percentile_window_W",
            "score_dimension",
            "score_dimension_min",
            "eligible_dimension",
            "validity_status",
            "reason_codes",
            "score_engine_version",
        },
        "a_raw_observations": {
            "security_id",
            "trading_date",
            "observation_sequence",
            "component_id",
            "raw_value",
            "validity_status",
            "reason_codes",
            "source_run_id",
        },
        "pcvt_validation_raw": {
            "security_id",
            "trading_date",
            "observation_sequence",
            "dimension_id",
            "component_id",
            "raw_value",
            "validity_status",
            "reason_codes",
        },
    }
    for table, expected in required.items():
        columns = {
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("stage_{table}")'
            ).fetchall()
        }
        missing = sorted(expected - columns)
        if missing:
            raise ScoreReleaseError(
                f"staging_schema_missing:{table}:{','.join(missing)}"
            )


def _validate_source_keys(connection: duckdb.DuckDBPyConnection) -> None:
    specifications = (
        ("pcvt_component_scores", "component_id", PCVT_COMPONENTS, 8),
        ("pcvt_dimension_scores", "dimension_id", PCVT_DIMENSIONS, 4),
        ("a_raw_observations", "component_id", A_COMPONENTS, 2),
        ("pcvt_validation_raw", "component_id", PCVT_COMPONENTS, 8),
    )
    for table, item_column, allowed, expected_per_present in specifications:
        allowed_sql = ",".join(f"'{item}'" for item in allowed)
        duplicates = connection.execute(
            f"SELECT count(*) FROM (SELECT security_id,trading_date,{item_column},"
            f"count(*) n FROM stage_{table} GROUP BY 1,2,3 HAVING n<>1)"
        ).fetchone()[0]
        if duplicates:
            raise ScoreReleaseError(f"duplicate_source_key:{table}")
        invalid = connection.execute(
            f"SELECT count(*) FROM stage_{table} x LEFT JOIN "
            "stage_security_observation_spine s USING(security_id,trading_date) "
            f"WHERE s.security_id IS NULL OR x.{item_column} NOT IN ({allowed_sql})"
        ).fetchone()[0]
        if invalid:
            raise ScoreReleaseError(f"extra_or_invalid_source_key:{table}")
        present_missing = connection.execute(
            "SELECT count(*) FROM (SELECT s.security_id,s.trading_date,count(x."
            f"{item_column}) n FROM stage_security_observation_spine s LEFT JOIN "
            f"stage_{table} x USING(security_id,trading_date) WHERE "
            "s.expected_observation_status='present' GROUP BY 1,2 "
            f"HAVING n<>{expected_per_present})"
        ).fetchone()[0]
        if present_missing:
            raise ScoreReleaseError(f"present_source_row_missing:{table}")


def _materialize_staged_release(
    *,
    staging_path: Path,
    database_path: Path,
    shard_dir: Path,
    score_release_id: str,
    worker_count: int,
) -> None:
    shard_dir.mkdir(parents=True, exist_ok=False)
    _write_a_score_shards(
        staging_path=staging_path,
        shard_dir=shard_dir,
        score_release_id=score_release_id,
        worker_count=worker_count,
    )
    quoted_stage = str(staging_path).replace("'", "''")
    quoted_components = str(shard_dir / "component-*.parquet").replace("'", "''")
    quoted_dimensions = str(shard_dir / "dimension-*.parquet").replace("'", "''")
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(f"ATTACH '{quoted_stage}' AS staging (READ_ONLY)")
        _create_tables(connection)
        _insert_registries(connection, score_release_id)
        _insert_core_tables(connection, score_release_id)
        _insert_pcvt_scores(connection, score_release_id)
        connection.execute(
            f"INSERT INTO daily_component_scores SELECT * FROM read_parquet('{quoted_components}') "
            "ORDER BY security_id,trading_date,component_id"
        )
        connection.execute(
            f"INSERT INTO daily_dimension_scores SELECT * FROM read_parquet('{quoted_dimensions}') "
            "ORDER BY security_id,trading_date,dimension_id"
        )
        _assert_release_cardinality(connection)
        connection.execute("CHECKPOINT")


def _create_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE securities(
          score_release_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          universe_id VARCHAR NOT NULL,
          first_expected_date DATE NOT NULL,
          last_expected_date DATE NOT NULL,
          expected_observation_count BIGINT NOT NULL CHECK(expected_observation_count >= 0),
          PRIMARY KEY(score_release_id,security_id),
          CHECK(first_expected_date <= last_expected_date)
        );
        CREATE TABLE trading_sessions(
          score_release_id VARCHAR NOT NULL,
          trading_date DATE NOT NULL,
          session_sequence BIGINT NOT NULL CHECK(session_sequence >= 0),
          expected_security_count BIGINT NOT NULL CHECK(expected_security_count >= 0),
          present_security_count BIGINT NOT NULL CHECK(present_security_count >= 0),
          available_time TIMESTAMPTZ NOT NULL,
          PRIMARY KEY(score_release_id,trading_date),
          UNIQUE(score_release_id,session_sequence),
          CHECK(present_security_count <= expected_security_count)
        );
        CREATE TABLE security_observation_spine(
          score_release_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          trading_date DATE NOT NULL,
          observation_sequence BIGINT NOT NULL CHECK(observation_sequence >= 0),
          expected_observation_status VARCHAR NOT NULL CHECK(expected_observation_status IN ('present','missing','listing_pause')),
          source_contract VARCHAR NOT NULL,
          source_ref VARCHAR NOT NULL,
          observation_available_time TIMESTAMPTZ NOT NULL,
          PRIMARY KEY(score_release_id,security_id,trading_date),
          UNIQUE(score_release_id,security_id,observation_sequence),
          FOREIGN KEY(score_release_id,security_id) REFERENCES securities(score_release_id,security_id),
          FOREIGN KEY(score_release_id,trading_date) REFERENCES trading_sessions(score_release_id,trading_date)
        );
        CREATE TABLE dimension_definitions(
          score_release_id VARCHAR NOT NULL,
          dimension_id VARCHAR NOT NULL CHECK(dimension_id IN ('P','C','A','V','T')),
          canonical_order INTEGER NOT NULL CHECK(canonical_order BETWEEN 1 AND 5),
          dimension_name VARCHAR NOT NULL,
          component_count INTEGER NOT NULL CHECK(component_count = 2),
          aggregation_method VARCHAR NOT NULL CHECK(aggregation_method='equal_weight_mean_and_min'),
          score_direction VARCHAR NOT NULL CHECK(score_direction='higher_is_more_convergent'),
          percentile_window_W INTEGER NOT NULL CHECK(percentile_window_W = 120),
          definition_version VARCHAR NOT NULL,
          PRIMARY KEY(score_release_id,dimension_id),
          UNIQUE(score_release_id,canonical_order)
        );
        CREATE TABLE dimension_components(
          score_release_id VARCHAR NOT NULL,
          dimension_id VARCHAR NOT NULL,
          component_id VARCHAR NOT NULL,
          component_order INTEGER NOT NULL CHECK(component_order IN (1,2)),
          weight DOUBLE NOT NULL CHECK(weight = 0.5),
          raw_metric_name VARCHAR NOT NULL,
          raw_value_direction VARCHAR NOT NULL,
          score_formula VARCHAR NOT NULL,
          tie_method VARCHAR NOT NULL CHECK(tie_method='midrank'),
          current_value_in_reference_set BOOLEAN NOT NULL CHECK(current_value_in_reference_set=false),
          source_role VARCHAR NOT NULL CHECK(source_role IN ('accepted_r0_w120','recomputed_a_raw')),
          definition_version VARCHAR NOT NULL,
          PRIMARY KEY(score_release_id,dimension_id,component_id),
          UNIQUE(score_release_id,component_id),
          UNIQUE(score_release_id,dimension_id,component_order),
          FOREIGN KEY(score_release_id,dimension_id) REFERENCES dimension_definitions(score_release_id,dimension_id)
        );
        CREATE TABLE daily_component_scores(
          score_release_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          trading_date DATE NOT NULL,
          observation_sequence BIGINT NOT NULL CHECK(observation_sequence >= 0),
          dimension_id VARCHAR NOT NULL,
          component_id VARCHAR NOT NULL,
          percentile_window_W INTEGER NOT NULL CHECK(percentile_window_W = 120),
          raw_value DOUBLE,
          percentile DOUBLE,
          score DOUBLE,
          eligible BOOLEAN NOT NULL,
          validity_status VARCHAR NOT NULL CHECK(validity_status IN ('valid','unknown','diagnostic_required','blocked')),
          reason_codes VARCHAR[] NOT NULL CHECK(len(reason_codes)>=1),
          reference_observation_count INTEGER NOT NULL CHECK(reference_observation_count BETWEEN 0 AND 120),
          reference_window_start BIGINT,
          reference_window_end BIGINT,
          current_value_in_reference_set BOOLEAN NOT NULL CHECK(current_value_in_reference_set=false),
          tie_method VARCHAR NOT NULL CHECK(tie_method='midrank'),
          score_engine_version VARCHAR NOT NULL,
          source_role VARCHAR NOT NULL CHECK(source_role IN ('accepted_r0_w120','recomputed_a_raw')),
          source_run_id VARCHAR NOT NULL,
          available_time TIMESTAMPTZ NOT NULL,
          PRIMARY KEY(score_release_id,security_id,trading_date,dimension_id,component_id),
          FOREIGN KEY(score_release_id,security_id,trading_date) REFERENCES security_observation_spine(score_release_id,security_id,trading_date),
          FOREIGN KEY(score_release_id,dimension_id,component_id) REFERENCES dimension_components(score_release_id,dimension_id,component_id),
          CHECK((eligible AND validity_status='valid' AND percentile IS NOT NULL AND score IS NOT NULL AND percentile BETWEEN 0 AND 1 AND score BETWEEN 0 AND 1) OR (NOT eligible AND percentile IS NULL AND score IS NULL))
        );
        CREATE TABLE daily_dimension_scores(
          score_release_id VARCHAR NOT NULL,
          security_id VARCHAR NOT NULL,
          trading_date DATE NOT NULL,
          observation_sequence BIGINT NOT NULL CHECK(observation_sequence >= 0),
          dimension_id VARCHAR NOT NULL,
          percentile_window_W INTEGER NOT NULL CHECK(percentile_window_W = 120),
          score_dimension DOUBLE,
          score_dimension_min DOUBLE,
          eligible_dimension BOOLEAN NOT NULL,
          validity_status VARCHAR NOT NULL CHECK(validity_status IN ('valid','unknown','diagnostic_required','blocked')),
          reason_codes VARCHAR[] NOT NULL CHECK(len(reason_codes)>=1),
          component_count INTEGER NOT NULL CHECK(component_count=2),
          score_engine_version VARCHAR NOT NULL,
          source_role VARCHAR NOT NULL CHECK(source_role IN ('accepted_r0_w120','recomputed_a_raw')),
          available_time TIMESTAMPTZ NOT NULL,
          PRIMARY KEY(score_release_id,security_id,trading_date,dimension_id),
          FOREIGN KEY(score_release_id,security_id,trading_date) REFERENCES security_observation_spine(score_release_id,security_id,trading_date),
          FOREIGN KEY(score_release_id,dimension_id) REFERENCES dimension_definitions(score_release_id,dimension_id),
          CHECK((eligible_dimension AND validity_status='valid' AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL AND score_dimension BETWEEN 0 AND 1 AND score_dimension_min BETWEEN 0 AND 1) OR (NOT eligible_dimension AND score_dimension IS NULL AND score_dimension_min IS NULL))
        );
        """
    )


def _insert_registries(
    connection: duckdb.DuckDBPyConnection, score_release_id: str
) -> None:
    dimension_names = {
        "P": "Price Compression",
        "C": "Reference-Price Convergence",
        "A": "Price-to-MA Attachment",
        "V": "Participation Contraction",
        "T": "Trend Neutrality",
    }
    for order, dimension in enumerate(DIMENSION_ORDER, start=1):
        connection.execute(
            "INSERT INTO dimension_definitions VALUES (?,?,?,?,2,'equal_weight_mean_and_min',"
            "'higher_is_more_convergent',120,'pcavt-dimension-definition.v1')",
            [score_release_id, dimension, order, dimension_names[dimension]],
        )
        for component_order, component in enumerate(
            COMPONENTS_BY_DIMENSION[dimension], start=1
        ):
            source_role = "recomputed_a_raw" if dimension == "A" else "accepted_r0_w120"
            connection.execute(
                "INSERT INTO dimension_components VALUES (?,?,?,?,0.5,?,"
                "'lower_raw_is_more_convergent','score=1-percentile','midrank',false,?,"
                "'pcavt-component-definition.v1')",
                [
                    score_release_id,
                    dimension,
                    component,
                    component_order,
                    component,
                    source_role,
                ],
            )


def _insert_core_tables(
    connection: duckdb.DuckDBPyConnection, score_release_id: str
) -> None:
    connection.execute(
        "INSERT INTO securities SELECT ?,security_id,universe_id,first_expected_date,"
        "last_expected_date,expected_observation_count FROM staging.main.stage_securities",
        [score_release_id],
    )
    connection.execute(
        "INSERT INTO trading_sessions SELECT ?,trading_date,session_sequence,"
        "expected_security_count,present_security_count,available_time "
        "FROM staging.main.stage_trading_sessions",
        [score_release_id],
    )
    connection.execute(
        "INSERT INTO security_observation_spine SELECT ?,security_id,trading_date,"
        "observation_sequence,expected_observation_status,source_contract,source_ref,"
        "observation_available_time FROM staging.main.stage_security_observation_spine",
        [score_release_id],
    )


def _insert_pcvt_scores(
    connection: duckdb.DuckDBPyConnection, score_release_id: str
) -> None:
    connection.execute(
        """
        INSERT INTO daily_component_scores
        SELECT ?,s.security_id,s.trading_date,s.observation_sequence,r.dimension_id,
          r.component_id,120,
          CASE WHEN s.expected_observation_status='present' THEN x.raw_value ELSE NULL END,
          CASE WHEN s.expected_observation_status='present' THEN x.percentile ELSE NULL END,
          CASE WHEN s.expected_observation_status='present' THEN x.score ELSE NULL END,
          CASE WHEN s.expected_observation_status='present' THEN x.eligible ELSE false END,
          CASE WHEN s.expected_observation_status='present' THEN x.validity_status ELSE 'blocked' END,
          CASE WHEN s.expected_observation_status='missing' THEN ['market_observation_missing']
               WHEN s.expected_observation_status='listing_pause' THEN ['security_listing_pause']
               ELSE x.reason_codes END,
          CASE WHEN s.expected_observation_status='present' THEN x.reference_observation_count ELSE 0 END,
          CASE WHEN s.expected_observation_status='present' THEN x.reference_window_start ELSE NULL END,
          CASE WHEN s.expected_observation_status='present' THEN x.reference_window_end ELSE NULL END,
          false,'midrank',
          CASE WHEN s.expected_observation_status='present' THEN x.score_engine_version ELSE 'accepted_r0_t05_score_engine.v1' END,
          'accepted_r0_w120',
          CASE WHEN s.expected_observation_status='present' THEN x.source_run_id ELSE 'expected_empty' END,
          s.observation_available_time
        FROM security_observation_spine s
        CROSS JOIN dimension_components r
        LEFT JOIN staging.main.stage_pcvt_component_scores x
          ON x.security_id=s.security_id AND x.trading_date=s.trading_date
         AND x.dimension_id=r.dimension_id AND x.component_id=r.component_id
        WHERE s.score_release_id=? AND r.score_release_id=? AND r.dimension_id<>'A'
        """,
        [score_release_id, score_release_id, score_release_id],
    )
    connection.execute(
        """
        INSERT INTO daily_dimension_scores
        SELECT ?,s.security_id,s.trading_date,s.observation_sequence,r.dimension_id,120,
          CASE WHEN s.expected_observation_status='present' THEN x.score_dimension ELSE NULL END,
          CASE WHEN s.expected_observation_status='present' THEN x.score_dimension_min ELSE NULL END,
          CASE WHEN s.expected_observation_status='present' THEN x.eligible_dimension ELSE false END,
          CASE WHEN s.expected_observation_status='present' THEN x.validity_status ELSE 'blocked' END,
          CASE WHEN s.expected_observation_status='missing' THEN ['market_observation_missing','component_score_missing']
               WHEN s.expected_observation_status='listing_pause' THEN ['security_listing_pause','component_score_missing']
               ELSE x.reason_codes END,
          2,CASE WHEN s.expected_observation_status='present' THEN x.score_engine_version ELSE 'accepted_r0_t05_score_engine.v1' END,
          'accepted_r0_w120',s.observation_available_time
        FROM security_observation_spine s
        CROSS JOIN dimension_definitions r
        LEFT JOIN staging.main.stage_pcvt_dimension_scores x
          ON x.security_id=s.security_id AND x.trading_date=s.trading_date
         AND x.dimension_id=r.dimension_id
        WHERE s.score_release_id=? AND r.score_release_id=? AND r.dimension_id<>'A'
        """,
        [score_release_id, score_release_id, score_release_id],
    )


def _write_a_score_shards(
    *,
    staging_path: Path,
    shard_dir: Path,
    score_release_id: str,
    worker_count: int,
) -> None:
    with duckdb.connect(str(staging_path), read_only=True) as connection:
        securities = [
            str(row[0])
            for row in connection.execute(
                "SELECT security_id FROM stage_securities ORDER BY security_id"
            ).fetchall()
        ]
    arguments = [
        (str(staging_path), str(shard_dir), index, security_id, score_release_id)
        for index, security_id in enumerate(securities)
    ]
    if worker_count == 1:
        results = [_score_security_shard(argument) for argument in arguments]
    else:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=worker_count, mp_context=context
        ) as executor:
            results = list(executor.map(_score_security_shard, arguments))
    if sum(item["component_rows"] for item in results) == 0:
        raise ScoreReleaseError("empty_a_component_shards")


def _score_security_shard(
    argument: tuple[str, str, int, str, str],
) -> dict[str, Any]:
    staging_path, shard_dir, index, security_id, score_release_id = argument
    with duckdb.connect(staging_path, read_only=True) as connection:
        rows = connection.execute(
            """
            WITH a_components(component_id) AS (
              VALUES ('A1_LogBodyCenterToMACloudCenter_5_60'),
                     ('A2_BodyCenterOutsideMACloudRate20_5_60')
            )
            SELECT s.trading_date,s.observation_sequence,s.expected_observation_status,
                   s.observation_available_time,c.component_id,a.raw_value,
                   a.validity_status,a.reason_codes,a.source_run_id
            FROM stage_security_observation_spine s
            CROSS JOIN a_components c
            LEFT JOIN stage_a_raw_observations a
              ON a.security_id=s.security_id AND a.trading_date=s.trading_date
             AND a.component_id=c.component_id
            WHERE s.security_id=? ORDER BY s.observation_sequence,c.component_id
            """,
            [security_id],
        ).fetchall()
    raw_rows: list[dict[str, Any]] = []
    metadata: dict[tuple[str, str], tuple[Any, str]] = {}
    for row in rows:
        trading_date = str(row[0])
        sequence = int(row[1])
        observation_status = str(row[2])
        component_id = str(row[4])
        if observation_status == "missing":
            raw_value, validity, reasons = (
                None,
                "blocked",
                ["market_observation_missing"],
            )
        elif observation_status == "listing_pause":
            raw_value, validity, reasons = None, "blocked", ["security_listing_pause"]
        else:
            if row[6] is None:
                raise ScoreReleaseError("present_a_raw_source_missing")
            raw_value, validity = row[5], str(row[6])
            reasons = list(row[7] or [validity])
        source_run_id = str(row[8] or "r2a_t01_a_raw_source")
        raw_rows.append(
            {
                "security_id": security_id,
                "trading_date": trading_date,
                "observation_sequence": sequence,
                "indicator_id": component_id,
                "raw_value": raw_value,
                "validity_status": validity,
                "reason_codes": reasons,
            }
        )
        metadata[(trading_date, component_id)] = (row[3], source_run_id)
    component_scores = compute_component_scores(raw_rows, worker_count=1)
    dimension_scores = compute_a_dimension_scores(component_scores)
    component_payload = []
    for item in component_scores:
        available_time, source_run_id = metadata[(item.trading_date, item.indicator_id)]
        component_payload.append(
            {
                "score_release_id": score_release_id,
                "security_id": item.security_id,
                "trading_date": item.trading_date,
                "observation_sequence": item.observation_sequence,
                "dimension_id": "A",
                "component_id": item.indicator_id,
                "percentile_window_W": item.percentile_window,
                "raw_value": item.raw_value,
                "percentile": item.percentile,
                "score": item.score,
                "eligible": item.eligible,
                "validity_status": item.validity_status,
                "reason_codes": list(item.reason_codes),
                "reference_observation_count": item.reference_observation_count,
                "reference_window_start": item.reference_sequence_start,
                "reference_window_end": item.reference_sequence_end,
                "current_value_in_reference_set": False,
                "tie_method": TIE_METHOD,
                "score_engine_version": ENGINE_VERSION,
                "source_role": "recomputed_a_raw",
                "source_run_id": source_run_id,
                "available_time": available_time,
            }
        )
    dimension_payload = []
    for item in dimension_scores:
        available_time = metadata[(item.trading_date, A_COMPONENTS[0])][0]
        dimension_payload.append(
            {
                "score_release_id": score_release_id,
                "security_id": item.security_id,
                "trading_date": item.trading_date,
                "observation_sequence": item.observation_sequence,
                "dimension_id": "A",
                "percentile_window_W": item.percentile_window,
                "score_dimension": item.score_dimension,
                "score_dimension_min": item.score_dimension_min,
                "eligible_dimension": item.eligible_dimension,
                "validity_status": item.validity_status,
                "reason_codes": list(item.reason_codes),
                "component_count": 2,
                "score_engine_version": ENGINE_VERSION,
                "source_role": "recomputed_a_raw",
                "available_time": available_time,
            }
        )
    component_path = Path(shard_dir) / f"component-{index:04d}.parquet"
    dimension_path = Path(shard_dir) / f"dimension-{index:04d}.parquet"
    pq.write_table(
        pa.Table.from_pylist(component_payload), component_path, compression="zstd"
    )
    pq.write_table(
        pa.Table.from_pylist(dimension_payload), dimension_path, compression="zstd"
    )
    return {
        "security_id": security_id,
        "component_rows": len(component_payload),
        "dimension_rows": len(dimension_payload),
        "component_shard": component_path.name,
        "dimension_shard": dimension_path.name,
    }


def _assert_release_cardinality(connection: duckdb.DuckDBPyConnection) -> None:
    spine = int(
        connection.execute(
            "SELECT count(*) FROM security_observation_spine"
        ).fetchone()[0]
    )
    components = int(
        connection.execute("SELECT count(*) FROM daily_component_scores").fetchone()[0]
    )
    dimensions = int(
        connection.execute("SELECT count(*) FROM daily_dimension_scores").fetchone()[0]
    )
    if components != spine * 10 or dimensions != spine * 5:
        raise ScoreReleaseError("release_cardinality_mismatch")
    release_counts = {
        table: connection.execute(
            f'SELECT count(DISTINCT score_release_id) FROM "{table}"'
        ).fetchone()[0]
        for table in TABLE_ORDER
    }
    if set(release_counts.values()) != {1}:
        raise ScoreReleaseError("score_release_id_not_total")


def _enforce_formal_cardinality(database_path: Path) -> None:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        security_count = connection.execute(
            "SELECT count(*) FROM securities"
        ).fetchone()[0]
        years = connection.execute(
            "SELECT min(year(trading_date)),max(year(trading_date)) FROM trading_sessions"
        ).fetchone()
    if security_count != 800:
        raise ScoreReleaseError("formal_security_count_must_equal_800")
    if years != (2016, 2026):
        raise ScoreReleaseError("formal_calendar_year_domain_must_be_2016_2026")


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ScoreReleaseError("contract_json_must_be_object")
    return payload


def _validate_json_contract(payload: Mapping[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


def _validate_runtime_contract(
    config: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    if config.get("percentile_window") != PERCENTILE_WINDOW:
        raise ScoreReleaseError("config_window_mismatch")
    if config.get("dimension_order") != list(DIMENSION_ORDER):
        raise ScoreReleaseError("dimension_order_mismatch")
    if policy.get("policy_id") != "r2a_t01_eod_close_1500_asia_shanghai.v1":
        raise ScoreReleaseError("availability_policy_mismatch")


def _reject_formal_output_path(path: Path) -> None:
    root = (ROOT / "data/generated/r2a/r2a_t01").resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return
    raise ScoreReleaseError("formal_output_path_not_authorized")


def _require_formal_output_path(path: Path) -> None:
    root = (ROOT / "data/generated/r2a/r2a_t01").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ScoreReleaseError("formal_output_must_use_canonical_root") from exc
