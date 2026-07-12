import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2.r2_t02_repository_final_gate_handoff import (  # noqa: E402
    RUN_DIR,
    create_handoff,
    validate_handoff,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or validate the R2-T02 post-merge final-gate handoff."
    )
    parser.add_argument("--source-commit")
    parser.add_argument("--handoff-commit")
    parser.add_argument(
        "--handoff-path",
        default=str(RUN_DIR / "r2_t02_repository_final_gate_handoff.json"),
    )
    parser.add_argument("--output")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.create:
        if not args.source_commit:
            parser.error("--source-commit is required with --create")
        create_handoff(
            Path(args.handoff_path),
            source_commit=args.source_commit,
            verify_remote=not args.offline,
        )
        return 0
    if not args.handoff_commit:
        parser.error("--handoff-commit is required for validation")
    validate_handoff(
        Path(args.handoff_path),
        handoff_commit=args.handoff_commit,
        output_path=Path(args.output) if args.output else None,
        verify_remote=not args.offline,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
