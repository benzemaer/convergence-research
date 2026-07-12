# ruff: noqa: E402
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.r2.r2_t02_protocol_freeze import validate_output


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate R2-T02 protocol package.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT
        / "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v5.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    validate_output(args.output_dir, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
