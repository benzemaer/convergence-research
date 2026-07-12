from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import ROOT, repo_rel, sha256_bytes


def validate_committed_artifacts(
    output_dir: Path, *, commit: str = "HEAD", root: Path = ROOT
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    package = json.loads(
        (output_dir / "r2_t02_result_package.json").read_text(encoding="utf-8")
    )
    errors = []
    for name, expected_hash in sorted(package["artifact_hashes"].items()):
        rel = f"{repo_rel(output_dir, root)}/{name}"
        try:
            committed_bytes = subprocess.check_output(
                ["git", "show", f"{commit}:{rel}"],
                cwd=root,
            )
        except subprocess.CalledProcessError:
            errors.append(f"missing_committed_artifact:{name}")
            continue
        actual_hash = sha256_bytes(committed_bytes)
        if actual_hash != expected_hash:
            errors.append(f"committed_hash_mismatch:{name}")
    return {
        "status": "passed" if not errors else "failed",
        "commit": commit,
        "artifact_count": len(package["artifact_hashes"]),
        "errors": errors,
    }
