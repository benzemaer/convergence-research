"""Controlled future-formal entry boundary for R2A-T06.

The implementation candidate intentionally contains no authorization artifact.
Every invocation therefore fails closed before reading any real Score input.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.r2a.r2a_t06_consecutive_failure_exit import T06Error, load_t06_config

FORMAL_REQUIRED_FILES = (
    "request_identity.json",
    "input_manifest.json",
    "run_summary.json",
    "validation_receipt.json",
    "result_analysis.md",
    "false_run_length_profile.csv",
    "recovery_hazard_profile.csv",
    "candidate_exit_summary.csv",
    "recognition_lag_profile.csv",
    "post_recognition_reentry.csv",
    "episode_fragmentation_profile.csv",
    "exit_type_margin_profile.csv",
    "cross_q_nesting_validation.csv",
    "year_profile.csv",
    "security_profile.csv",
    "deterministic_episode_samples.csv",
    "t06_detail.duckdb",
)


def assert_formal_execution_authorized(
    authorization: Mapping[str, Any] | None,
    *,
    config: Mapping[str, Any] | None = None,
) -> None:
    """Fail before input discovery unless a future owner authorization is valid."""

    loaded = dict(config or load_t06_config())
    if loaded.get("formal_run_allowed") is not True:
        raise T06Error("formal_run_not_authorized_implementation_stage")
    if not authorization or authorization.get("owner_authorized") is not True:
        raise T06Error("owner_formal_authorization_missing")
    if authorization.get("reviewed_implementation_sha") != authorization.get(
        "execution_parent_sha"
    ):
        raise T06Error("formal_authorization_sha_binding_mismatch")


def run_formal(
    authorization: Mapping[str, Any] | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> None:
    """Reserved future entry; current implementation always stops at the gate."""

    assert_formal_execution_authorized(authorization, config=config)
    raise T06Error("formal_execution_not_implemented_until_owner_approval")
