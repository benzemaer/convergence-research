from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.r2a.r2a_t02_request_identity import (
    DynamicRequestError,
    build_canonical_request,
    canonical_spec_bytes,
    canonicalize_request_spec,
    ensure_no_request_id_collision,
    load_canonical_request,
    load_request_spec,
    request_hash_for_spec,
    request_id_for_hash,
    validate_canonical_request,
)

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts/r2a/build_r2a_t02_dynamic_request.py"
GOLDEN_HASH = "fda529f47faece8b7756159247e3c07c261721c4013270981929a4dfe5f9959d"
GOLDEN_ID = "pcavt-dynreq-v1-fda529f47faece8b"
GOLDEN_JSON = (
    '{"confirmation_k":3,"dynamic_protocol_version":"pcavt_dynamic_state_protocol.v1",'
    '"q_by_dimension":{"A":1500,"P":1000,"V":2500},'
    '"request_schema_version":"r2a_t02_dynamic_request_spec.v1",'
    '"score_release_id":"pcavt-score-w120-v1-c7e04f11a2cd09aa",'
    '"selected_dimensions":["P","A","V"]}'
)


def golden_spec() -> dict[str, object]:
    return {
        "request_schema_version": "r2a_t02_dynamic_request_spec.v1",
        "dynamic_protocol_version": "pcavt_dynamic_state_protocol.v1",
        "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
        "selected_dimensions": ["P", "A", "V"],
        "q_by_dimension": {"P": 1000, "A": 1500, "V": 2500},
        "confirmation_k": 3,
    }


def test_golden_identity_vector_is_byte_exact() -> None:
    assert canonical_spec_bytes(golden_spec()) == GOLDEN_JSON.encode("utf-8")
    assert request_hash_for_spec(golden_spec()) == GOLDEN_HASH
    assert request_id_for_hash(GOLDEN_HASH) == GOLDEN_ID
    envelope = build_canonical_request(golden_spec())
    assert envelope["request_hash"] == GOLDEN_HASH
    assert envelope["request_id"] == GOLDEN_ID


@pytest.mark.parametrize(
    "payload",
    [
        '{"confirmation_k":2,"confirmation_k":7}',
        '{"selected_dimensions":["P"],"selected_dimensions":["A"]}',
        '{"q_by_dimension":{"P":1000,"P":2500}}',
    ],
)
def test_request_loader_rejects_duplicate_keys_at_every_depth(
    tmp_path: Path, payload: str
) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(DynamicRequestError, match="duplicate_json_object_key"):
        load_request_spec(path)


def test_canonical_loader_rejects_duplicate_envelope_key(tmp_path: Path) -> None:
    envelope = build_canonical_request(golden_spec())
    payload = json.dumps(envelope, separators=(",", ":"))
    payload = payload.replace(
        f'"request_hash":"{GOLDEN_HASH}"',
        f'"request_hash":"{GOLDEN_HASH}","request_hash":"{GOLDEN_HASH}"',
    )
    path = tmp_path / "duplicate-envelope.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(DynamicRequestError, match="duplicate_json_object_key"):
        load_canonical_request(path)


def test_unique_key_request_and_canonical_envelope_load_normally(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(golden_spec()), encoding="utf-8")
    loaded_spec = load_request_spec(spec_path)
    assert loaded_spec == golden_spec()

    envelope = build_canonical_request(loaded_spec)
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
    assert load_canonical_request(envelope_path) == envelope


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_external_json_loader_rejects_non_finite_constants(
    tmp_path: Path, constant: str
) -> None:
    path = tmp_path / "non-finite.json"
    path.write_text(f'{{"confirmation_k":{constant}}}', encoding="utf-8")
    with pytest.raises(DynamicRequestError, match="non_finite_json_number"):
        load_request_spec(path)


def test_order_is_normalized_but_scientific_changes_change_identity() -> None:
    reordered = {
        "confirmation_k": 3,
        "q_by_dimension": {"V": 2500, "P": 1000, "A": 1500},
        "selected_dimensions": ["V", "A", "P"],
        "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
        "dynamic_protocol_version": "pcavt_dynamic_state_protocol.v1",
        "request_schema_version": "r2a_t02_dynamic_request_spec.v1",
    }
    assert request_hash_for_spec(reordered) == GOLDEN_HASH
    assert canonicalize_request_spec(reordered)["selected_dimensions"] == [
        "P",
        "A",
        "V",
    ]

    for field, value in (
        ("confirmation_k", 4),
        ("selected_dimensions", ["P", "A"]),
    ):
        changed = golden_spec()
        changed[field] = value
        if field == "selected_dimensions":
            changed["q_by_dimension"] = {"P": 1000, "A": 1500}
        assert request_hash_for_spec(changed) != GOLDEN_HASH
    changed_q = golden_spec()
    changed_q["q_by_dimension"] = {"P": 1500, "A": 1500, "V": 2500}
    assert request_hash_for_spec(changed_q) != GOLDEN_HASH


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("score_release_id", "latest"),
        ("score_release_id", "another-release"),
        ("dynamic_protocol_version", "pcavt_dynamic_state_protocol.v2"),
        ("request_schema_version", "r2a_t02_dynamic_request_spec.v2"),
    ],
)
def test_unknown_binding_or_version_is_rejected(field: str, value: object) -> None:
    spec = golden_spec()
    spec[field] = value
    with pytest.raises(DynamicRequestError, match="request_spec_schema_invalid"):
        canonicalize_request_spec(spec)


@pytest.mark.parametrize("q_value", ["1000", 1000.0, True, None, 999, 0, -1000])
def test_q_requires_allowed_json_integer(q_value: object) -> None:
    spec = golden_spec()
    spec["q_by_dimension"] = {"P": q_value, "A": 1500, "V": 2500}
    with pytest.raises(DynamicRequestError):
        canonicalize_request_spec(spec)


@pytest.mark.parametrize("confirmation_k", [1, 8, 0, -1, 3.5, "5", None, True, False])
def test_k_domain_is_strict(confirmation_k: object) -> None:
    spec = golden_spec()
    spec["confirmation_k"] = confirmation_k
    with pytest.raises(DynamicRequestError):
        canonicalize_request_spec(spec)


def test_q_key_set_duplicate_unknown_empty_and_extra_fields_are_rejected() -> None:
    mutations = []
    missing_q = golden_spec()
    missing_q["q_by_dimension"] = {"P": 1000, "A": 1500}
    mutations.append(missing_q)
    extra_q = golden_spec()
    extra_q["q_by_dimension"] = {"P": 1000, "A": 1500, "V": 2500, "T": 1000}
    mutations.append(extra_q)
    duplicate = golden_spec()
    duplicate["selected_dimensions"] = ["P", "A", "P"]
    duplicate["q_by_dimension"] = {"P": 1000, "A": 1500}
    mutations.append(duplicate)
    unknown = golden_spec()
    unknown["selected_dimensions"] = ["P", "X"]
    unknown["q_by_dimension"] = {"P": 1000, "X": 1500}
    mutations.append(unknown)
    empty = golden_spec()
    empty["selected_dimensions"] = []
    empty["q_by_dimension"] = {}
    mutations.append(empty)
    extra_field = golden_spec()
    extra_field["worker_count"] = 16
    mutations.append(extra_field)
    for mutation in mutations:
        with pytest.raises(DynamicRequestError):
            canonicalize_request_spec(mutation)


def test_envelope_hash_and_id_are_recomputed_not_regex_only() -> None:
    envelope = build_canonical_request(golden_spec())
    validate_canonical_request(envelope)
    tampered_hash = copy.deepcopy(envelope)
    tampered_hash["request_hash"] = "0" * 64
    with pytest.raises(DynamicRequestError, match="request_hash_mismatch"):
        validate_canonical_request(tampered_hash)
    tampered_id = copy.deepcopy(envelope)
    tampered_id["request_id"] = "pcavt-dynreq-v1-0000000000000000"
    with pytest.raises(DynamicRequestError, match="request_id_mismatch"):
        validate_canonical_request(tampered_id)
    noncanonical = copy.deepcopy(envelope)
    noncanonical["spec"]["selected_dimensions"] = ["V", "A", "P"]
    with pytest.raises(DynamicRequestError, match="spec_not_canonical"):
        validate_canonical_request(noncanonical)


def test_hypothetical_short_id_collision_fails_closed() -> None:
    first_hash = "0123456789abcdef" + "0" * 48
    second_hash = "0123456789abcdef" + "1" * 48
    request_id = "pcavt-dynreq-v1-0123456789abcdef"
    with pytest.raises(DynamicRequestError, match="request_id_collision"):
        ensure_no_request_id_collision(request_id, first_hash, request_id, second_hash)


def test_cli_writes_canonical_utf8_lf_once_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    spec_path = tmp_path / "spec.json"
    output_path = tmp_path / "request.json"
    spec_path.write_text(json.dumps(golden_spec()), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--spec",
            str(spec_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert f"request_id={GOLDEN_ID}" in completed.stdout
    assert f"request_hash={GOLDEN_HASH}" in completed.stdout
    payload = output_path.read_bytes()
    assert not payload.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in payload
    assert payload.endswith(b"\n") and not payload.endswith(b"\n\n")
    validate_canonical_request(json.loads(payload))

    refused = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--spec",
            str(spec_path),
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    assert "output_already_exists" in refused.stderr


def test_cli_requires_existing_output_parent(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(golden_spec()), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--spec",
            str(spec_path),
            "--output",
            str(tmp_path / "missing/request.json"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "output_parent_missing" in completed.stderr
