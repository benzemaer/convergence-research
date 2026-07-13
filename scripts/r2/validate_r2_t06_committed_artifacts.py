from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    manifest_path = output_dir / "r2_t06_output_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    for item in manifest.get("artifacts", []):
        path = Path(item["path"])
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            failures.append(f"missing:{item['path']}")
        elif _sha256(path) != item["sha256"]:
            failures.append(f"sha256:{item['path']}")
    result = {
        "task_id": "R2-T06",
        "run_id": output_dir.name,
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "validation_mode": "committed_artifact_bytes",
        "manifest_path": str(manifest_path),
    }
    (output_dir / "r2_t06_committed_artifact_validation.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
