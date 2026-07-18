"""Validate, canonicalize, and identify R2A-T02 dynamic request specifications.

This module deliberately contains no Score access or dynamic-state evaluator logic.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from src.common.canonical_io import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
SPEC_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t02_dynamic_request_spec.schema.json"
REQUEST_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t02_dynamic_request.schema.json"

REQUEST_SPEC_SCHEMA_VERSION = "r2a_t02_dynamic_request_spec.v1"
CANONICAL_REQUEST_SCHEMA_VERSION = "r2a_t02_dynamic_request.v1"
DYNAMIC_PROTOCOL_VERSION = "pcavt_dynamic_state_protocol.v1"
SCORE_RELEASE_ID = "pcavt-score-w120-v1-c7e04f11a2cd09aa"
DIMENSION_ORDER = ("P", "C", "A", "V", "T")
ALLOWED_Q_BP = frozenset({1000, 1500, 2000, 2500})
ALLOWED_CONFIRMATION_K = frozenset({2, 3, 4, 5, 6, 7})
REQUEST_ID_PREFIX = "pcavt-dynreq-v1-"


class DynamicRequestError(ValueError):
    """Fail-closed dynamic request validation error with a stable reason code."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


@lru_cache(maxsize=2)
def _load_schema(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DynamicRequestError("schema_not_object", path.name)
    Draft202012Validator.check_schema(value)
    return value


@lru_cache(maxsize=1)
def _spec_validator() -> Draft202012Validator:
    return Draft202012Validator(_load_schema(SPEC_SCHEMA_PATH))


@lru_cache(maxsize=1)
def _request_validator() -> Draft202012Validator:
    spec_schema = _load_schema(SPEC_SCHEMA_PATH)
    request_schema = _load_schema(REQUEST_SCHEMA_PATH)
    registry = Registry().with_resource(
        spec_schema["$id"], Resource.from_contents(spec_schema)
    )
    return Draft202012Validator(request_schema, registry=registry)


def _validate(validator: Draft202012Validator, value: object, code: str) -> None:
    try:
        validator.validate(value)
    except ValidationError as error:
        location = "/".join(str(item) for item in error.absolute_path) or "<root>"
        raise DynamicRequestError(code, f"{location}: {error.message}") from error


def canonicalize_request_spec(raw_spec: object) -> dict[str, Any]:
    """Validate a user spec and return its canonical scientific representation."""

    _validate(_spec_validator(), raw_spec, "request_spec_schema_invalid")
    if not isinstance(raw_spec, Mapping):  # pragma: no cover - schema establishes this
        raise DynamicRequestError("request_spec_not_object")

    selected = raw_spec["selected_dimensions"]
    q_by_dimension = raw_spec["q_by_dimension"]
    confirmation_k = raw_spec["confirmation_k"]
    if not isinstance(selected, list):  # pragma: no cover - schema establishes this
        raise DynamicRequestError("selected_dimensions_not_array")
    if len(selected) != len(set(selected)):
        raise DynamicRequestError("duplicate_selected_dimension")
    unknown = sorted(set(selected) - set(DIMENSION_ORDER))
    if unknown:
        raise DynamicRequestError("unknown_selected_dimension", ",".join(unknown))
    if not isinstance(q_by_dimension, Mapping):  # pragma: no cover
        raise DynamicRequestError("q_by_dimension_not_object")

    canonical_dimensions = [item for item in DIMENSION_ORDER if item in selected]
    selected_set = set(canonical_dimensions)
    q_key_set = set(q_by_dimension)
    if q_key_set != selected_set:
        missing = sorted(selected_set - q_key_set)
        extra = sorted(q_key_set - selected_set)
        raise DynamicRequestError(
            "q_key_set_mismatch", f"missing={missing};extra={extra}"
        )
    for dimension, q_bp in q_by_dimension.items():
        if type(q_bp) is not int:  # bool and JSON floats are intentionally rejected
            raise DynamicRequestError("q_value_not_json_integer", str(dimension))
        if q_bp not in ALLOWED_Q_BP:
            raise DynamicRequestError("q_value_out_of_domain", str(dimension))
    if type(confirmation_k) is not int:
        raise DynamicRequestError("confirmation_k_not_json_integer")
    if confirmation_k not in ALLOWED_CONFIRMATION_K:
        raise DynamicRequestError("confirmation_k_out_of_domain")

    return {
        "request_schema_version": REQUEST_SPEC_SCHEMA_VERSION,
        "dynamic_protocol_version": DYNAMIC_PROTOCOL_VERSION,
        "score_release_id": SCORE_RELEASE_ID,
        "selected_dimensions": canonical_dimensions,
        "q_by_dimension": {
            dimension: q_by_dimension[dimension] for dimension in canonical_dimensions
        },
        "confirmation_k": confirmation_k,
    }


def canonical_spec_bytes(spec: object) -> bytes:
    """Return the exact hash preimage after validation and normalization."""

    return canonical_json_bytes(canonicalize_request_spec(spec))


def request_hash_for_spec(spec: object) -> str:
    return hashlib.sha256(canonical_spec_bytes(spec)).hexdigest()


def request_id_for_hash(request_hash: str) -> str:
    if (
        len(request_hash) != 64
        or request_hash.lower() != request_hash
        or any(character not in "0123456789abcdef" for character in request_hash)
    ):
        raise DynamicRequestError("request_hash_format_invalid")
    return REQUEST_ID_PREFIX + request_hash[:16]


def build_canonical_request(raw_spec: object) -> dict[str, Any]:
    spec = canonicalize_request_spec(raw_spec)
    request_hash = hashlib.sha256(canonical_json_bytes(spec)).hexdigest()
    envelope = {
        "request_schema_version": CANONICAL_REQUEST_SCHEMA_VERSION,
        "request_id": request_id_for_hash(request_hash),
        "request_hash": request_hash,
        "spec": spec,
    }
    validate_canonical_request(envelope)
    return envelope


def validate_canonical_request(envelope: object) -> dict[str, Any]:
    """Schema-check an envelope and recompute its authoritative hash and ID."""

    _validate(_request_validator(), envelope, "canonical_request_schema_invalid")
    if not isinstance(envelope, Mapping):  # pragma: no cover
        raise DynamicRequestError("canonical_request_not_object")
    canonical_spec = canonicalize_request_spec(envelope["spec"])
    if envelope["spec"] != canonical_spec:
        raise DynamicRequestError("spec_not_canonical")
    expected_hash = hashlib.sha256(canonical_json_bytes(canonical_spec)).hexdigest()
    if envelope["request_hash"] != expected_hash:
        raise DynamicRequestError("request_hash_mismatch")
    expected_id = request_id_for_hash(expected_hash)
    if envelope["request_id"] != expected_id:
        raise DynamicRequestError("request_id_mismatch")
    return dict(envelope)


def ensure_no_request_id_collision(
    existing_request_id: str,
    existing_request_hash: str,
    candidate_request_id: str,
    candidate_request_hash: str,
) -> None:
    """Reject a hypothetical short-ID collision between two full identities."""

    if existing_request_id != request_id_for_hash(existing_request_hash):
        raise DynamicRequestError("existing_request_identity_invalid")
    if candidate_request_id != request_id_for_hash(candidate_request_hash):
        raise DynamicRequestError("candidate_request_identity_invalid")
    if (
        existing_request_id == candidate_request_id
        and existing_request_hash != candidate_request_hash
    ):
        raise DynamicRequestError("request_id_collision")


def strict_json_loads(payload: str) -> object:
    """Parse external JSON while rejecting duplicate keys at every object depth."""

    def reject_constant(value: str) -> None:
        raise DynamicRequestError("non_finite_json_number", value)

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for key, value in pairs:
            if key in parsed:
                raise DynamicRequestError("duplicate_json_object_key", key)
            parsed[key] = value
        return parsed

    try:
        return json.loads(
            payload,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as error:
        raise DynamicRequestError("request_json_invalid", str(error)) from error


def _load_external_json(path: str | Path) -> object:
    try:
        payload = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DynamicRequestError("request_json_read_failed", str(error)) from error
    return strict_json_loads(payload)


def load_request_spec(path: str | Path) -> object:
    return _load_external_json(path)


def load_canonical_request(path: str | Path) -> dict[str, Any]:
    """Strictly parse and fully validate a canonical request envelope."""

    return validate_canonical_request(_load_external_json(path))


def write_canonical_request(path: str | Path, envelope: object) -> Path:
    """Write a validated envelope atomically without replacing an existing output."""

    target = Path(path)
    if not target.parent.is_dir():
        raise DynamicRequestError("output_parent_missing", str(target.parent))
    if target.exists():
        raise DynamicRequestError("output_already_exists", str(target))
    validated = validate_canonical_request(envelope)
    payload = canonical_json_bytes(validated) + b"\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise DynamicRequestError("output_already_exists", str(target)) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
