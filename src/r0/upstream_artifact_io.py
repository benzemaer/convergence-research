from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SMALL_JSON_MAX_BYTES = 16 * 1024 * 1024


class R0UpstreamArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class JsonlGzWriteSummary:
    path: Path
    row_count: int
    content_sha256: str
    file_sha256: str
    field_names: tuple[str, ...]
    date_min: str | None
    date_max: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "row_count": self.row_count,
            "content_sha256": self.content_sha256,
            "file_sha256": self.file_sha256,
            "field_names": list(self.field_names),
            "date_min": self.date_min,
            "date_max": self.date_max,
        }


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_object(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def read_small_json(path: str | Path, *, max_bytes: int = SMALL_JSON_MAX_BYTES) -> Any:
    source = Path(path)
    if source.stat().st_size > max_bytes:
        raise R0UpstreamArtifactError(
            f"JSON manifest exceeds small-file boundary: {source}"
        )
    with source.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    partial.replace(target)


def write_jsonl_gz_atomic(
    path: str | Path, rows: Iterable[Mapping[str, Any]]
) -> JsonlGzWriteSummary:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    content_digest = hashlib.sha256()
    row_count = 0
    field_names: set[str] = set()
    date_min: str | None = None
    date_max: str | None = None
    with gzip.open(partial, "wt", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            row_dict = dict(row)
            line = canonical_json(row_dict) + "\n"
            content_digest.update(line.encode("utf-8"))
            handle.write(line)
            row_count += 1
            field_names.update(str(key) for key in row_dict)
            trading_date = row_dict.get("trading_date")
            if trading_date is not None:
                value = str(trading_date)
                date_min = value if date_min is None else min(date_min, value)
                date_max = value if date_max is None else max(date_max, value)
    partial.replace(target)
    return JsonlGzWriteSummary(
        path=target,
        row_count=row_count,
        content_sha256=content_digest.hexdigest(),
        file_sha256=sha256_file(target),
        field_names=tuple(sorted(field_names)),
        date_min=date_min,
        date_max=date_max,
    )


def iter_jsonl_gz(path: str | Path) -> Iterable[dict[str, Any]]:
    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise R0UpstreamArtifactError(f"expected JSON object row: {path}")
                yield payload


def validate_manifest_shape(
    manifest: Mapping[str, Any],
    *,
    required_fields: Sequence[str],
    row_payload_forbidden_keys: Sequence[str] = ("rows", "raw_metric_results"),
) -> None:
    missing = [field for field in required_fields if field not in manifest]
    if missing:
        raise R0UpstreamArtifactError(f"manifest missing fields: {missing}")
    for key in row_payload_forbidden_keys:
        value = manifest.get(key)
        if isinstance(value, list):
            raise R0UpstreamArtifactError(
                f"manifest must not embed row payload array: {key}"
            )


def duckdb_table_summary(path: str | Path, table_name: str) -> dict[str, Any]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        row_count = int(
            conn.execute(f"SELECT count(*) FROM {quote_ident(table_name)}").fetchone()[
                0
            ]
        )
        schema_rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    finally:
        conn.close()
    return {
        "table_name": table_name,
        "row_count": row_count,
        "schema": [
            {"column_name": str(row[1]), "data_type": str(row[2])}
            for row in schema_rows
        ],
    }


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
