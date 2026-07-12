import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2.r2_t02_committed_artifact_validator import (  # noqa: E402
    validate_committed_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate committed R2-T02 artifacts.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--write-sidecar", action="store_true")
    parser.add_argument("--update-package", action="store_true")
    args = parser.parse_args()
    result = validate_committed_artifacts(
        args.output_dir,
        commit=args.commit,
        write_sidecar=args.write_sidecar,
        update_package=args.update_package,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
