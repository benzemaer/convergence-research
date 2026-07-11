import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.r2.r2_t01_author_package import build_author_package  # noqa: E402

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_author_package(Path(args.output)), ensure_ascii=False, sort_keys=True
        )
    )
