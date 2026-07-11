import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.r1.r1_t10_r1_gate_r2_decision_matrix_validator_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
