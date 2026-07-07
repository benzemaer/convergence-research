from __future__ import annotations

import re

FULL_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class FormalRunIdentityError(ValueError):
    pass


def validate_full_git_sha(value: str) -> str:
    candidate = str(value).strip()
    if not FULL_GIT_SHA_RE.fullmatch(candidate):
        raise FormalRunIdentityError("code_commit must be a full 40-character Git SHA")
    return candidate


def assert_full_git_sha(value: str) -> None:
    validate_full_git_sha(value)
