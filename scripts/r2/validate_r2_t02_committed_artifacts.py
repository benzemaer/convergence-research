import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.canonical_io import repo_rel, sha256_bytes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate committed R2-T02 artifact bytes against result package."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", default="HEAD")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    package = json.loads(
        (output_dir / "r2_t02_result_package.json").read_text(encoding="utf-8")
    )
    errors = []
    for name, expected_hash in sorted(package["artifact_hashes"].items()):
        rel = f"{repo_rel(output_dir, ROOT)}/{name}"
        try:
            committed_bytes = subprocess.check_output(
                ["git", "show", f"{args.commit}:{rel}"],
                cwd=ROOT,
            )
        except subprocess.CalledProcessError:
            errors.append(f"missing_committed_artifact:{name}")
            continue
        actual_hash = sha256_bytes(committed_bytes)
        if actual_hash != expected_hash:
            errors.append(f"committed_hash_mismatch:{name}")
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "commit": args.commit,
                "artifact_count": len(package["artifact_hashes"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
