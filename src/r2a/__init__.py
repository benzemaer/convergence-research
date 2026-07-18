"""R2A canonical PCAVT score-release implementation."""

from src.r2a.score_engine import (
    A_COMPONENTS,
    COMPONENTS_BY_DIMENSION,
    DIMENSION_ORDER,
    PERCENTILE_WINDOW,
    compute_a_dimension_scores,
    compute_component_scores,
)

__all__ = [
    "A_COMPONENTS",
    "COMPONENTS_BY_DIMENSION",
    "DIMENSION_ORDER",
    "PERCENTILE_WINDOW",
    "compute_a_dimension_scores",
    "compute_component_scores",
]
