from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from src.r2a.r2a_t04_request_panel import (
    EXPECTED_LOGICAL_NAMES,
    R2AT04PanelError,
    build_request_panel,
    load_audit_config,
    stable_smoke_security_ids,
)

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_panel_has_four_unique_canonical_identities() -> None:
    panel = build_request_panel()
    assert (
        tuple(item["logical_request_name"] for item in panel) == EXPECTED_LOGICAL_NAMES
    )
    assert len(panel) == len({item["request_id"] for item in panel}) == 4
    assert len({item["request_hash"] for item in panel}) == 4
    assert [item["request_id"] for item in panel] == [
        "pcavt-dynreq-v1-d07aae4bbbd98f88",
        "pcavt-dynreq-v1-cf420e9c025374d1",
        "pcavt-dynreq-v1-21bd144aaed98d9e",
        "pcavt-dynreq-v1-b210f9e5211c46db",
    ]
    assert all(item["spec"]["selected_dimensions"] == ["C", "A"] for item in panel)
    assert all(item["spec"]["confirmation_k"] == 5 for item in panel)


def test_panel_duplicate_or_reorder_is_rejected() -> None:
    config = copy.deepcopy(load_audit_config())
    config["request_panel"][1] = copy.deepcopy(config["request_panel"][0])
    with pytest.raises(R2AT04PanelError):
        build_request_panel(config)


def test_smoke_security_selection_is_stable_hash_not_input_order() -> None:
    securities = [f"S{index:03d}" for index in range(20)]
    left = stable_smoke_security_ids("release", securities)
    right = stable_smoke_security_ids("release", list(reversed(securities)))
    assert left == right
    assert len(left) == 4


@pytest.mark.parametrize(
    "script",
    (
        "scripts/r2a/preflight_r2a_t04_real_data_audit.py",
        "scripts/r2a/run_r2a_t04_real_data_audit.py",
        "scripts/review/review_r2a_t04_real_data_audit.py",
    ),
)
def test_t04_direct_cli_entrypoints_resolve_repository_imports(script: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
