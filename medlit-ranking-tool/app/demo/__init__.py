"""Demo/QA fixtures for the MedLit Ranking Tool.

All public functions return pre-built objects; no LLM or PubMed calls are made.
Normalization is computed once at module load via normalize_extraction().
"""

from app.demo.fixtures import (
    get_demo_extraction,
    get_demo_normalized,
    get_demo_paper,
    get_demo_papers,
)

__all__ = [
    "get_demo_papers",
    "get_demo_paper",
    "get_demo_extraction",
    "get_demo_normalized",
]
