from __future__ import annotations

from pathlib import Path


class R2T01FinalGatePending(RuntimeError):
    pass


def finalize_r2_t01_reviewed_package(
    *, output_dir: Path, review_record_path: Path
) -> None:
    raise R2T01FinalGatePending(
        "R2-T01 final gate requires an independent scientific review record and "
        "is intentionally not executed by the implementation actor."
    )
