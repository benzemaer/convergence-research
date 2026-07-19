"""Frozen CA q-response request panel for the R2A-T04 real-data audit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.r2a.r2a_t02_request_identity import (
    build_canonical_request,
    ensure_no_request_id_collision,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs/r2a/r2a_t04_real_data_audit.v1.json"
EXPECTED_LOGICAL_NAMES = (
    "CA_q15_k5",
    "CA_q25_k5",
)


class R2AT04PanelError(ValueError):
    """Fail-closed request-panel error with a stable reason code."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")
        self.reason_code = reason_code


def load_audit_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise R2AT04PanelError("audit_config_not_object")
    return value


def build_request_panel(
    config: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Build and validate the exact two-request canonical panel."""

    resolved = dict(config) if config is not None else load_audit_config()
    if resolved.get("panel_id") != "r2a_t04_ca_q15_q25_k5_panel.v1":
        raise R2AT04PanelError("panel_id_mismatch")
    raw_panel = resolved.get("request_panel")
    if not isinstance(raw_panel, list) or len(raw_panel) != 2:
        raise R2AT04PanelError("logical_request_count_mismatch")
    names = tuple(item.get("logical_request_name") for item in raw_panel)
    if names != EXPECTED_LOGICAL_NAMES:
        raise R2AT04PanelError("logical_request_order_mismatch")
    if len(set(names)) != 2:
        raise R2AT04PanelError("duplicate_logical_request_name")
    built: list[dict[str, Any]] = []
    for item in raw_panel:
        if not isinstance(item, Mapping) or set(item) != {
            "logical_request_name",
            "selected_dimensions",
            "q_by_dimension",
            "confirmation_k",
        }:
            raise R2AT04PanelError("request_panel_entry_invalid")
        envelope = build_canonical_request(
            {
                "request_schema_version": "r2a_t02_dynamic_request_spec.v1",
                "dynamic_protocol_version": "pcavt_dynamic_state_protocol.v1",
                "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
                "selected_dimensions": item["selected_dimensions"],
                "q_by_dimension": item["q_by_dimension"],
                "confirmation_k": item["confirmation_k"],
            }
        )
        built.append({"logical_request_name": item["logical_request_name"], **envelope})
    request_ids = [str(item["request_id"]) for item in built]
    request_hashes = [str(item["request_hash"]) for item in built]
    if len(set(request_ids)) != 2 or len(set(request_hashes)) != 2:
        raise R2AT04PanelError("canonical_request_identity_not_unique")
    for index, existing in enumerate(built):
        for candidate in built[index + 1 :]:
            ensure_no_request_id_collision(
                str(existing["request_id"]),
                str(existing["request_hash"]),
                str(candidate["request_id"]),
                str(candidate["request_hash"]),
            )
    return tuple(built)


def request_by_name(
    logical_name: str, panel: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    resolved = build_request_panel() if panel is None else panel
    matches = [
        item for item in resolved if item["logical_request_name"] == logical_name
    ]
    if len(matches) != 1:
        raise R2AT04PanelError("logical_request_resolution_failed", logical_name)
    return dict(matches[0])


def canonical_envelope(panel_item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: panel_item[key]
        for key in ("request_schema_version", "request_id", "request_hash", "spec")
    }


def stable_smoke_security_ids(
    score_release_id: str, security_ids: Sequence[str], *, count: int = 4
) -> tuple[str, ...]:
    """Select the frozen smoke scope without inspecting market outcomes."""

    unique = sorted(set(security_ids))
    if len(unique) != len(security_ids):
        raise R2AT04PanelError("duplicate_security_id")
    if len(unique) < count:
        raise R2AT04PanelError("insufficient_security_count")
    ranked = sorted(
        unique,
        key=lambda security_id: (
            hashlib.sha256(f"{score_release_id}:{security_id}".encode()).hexdigest(),
            security_id,
        ),
    )
    return tuple(ranked[:count])
