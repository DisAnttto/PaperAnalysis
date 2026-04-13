"""Tests for evidence_strength_score in app/retrieval/scoring.py."""

from __future__ import annotations

import pytest

from app.retrieval.enums import SourceType
from app.retrieval.models import EvidenceRecord
from app.retrieval.scoring import evidence_strength_score


def _record(source_type: SourceType, **extra) -> EvidenceRecord:
    return EvidenceRecord(
        identifier=f"TEST:{source_type}",
        source_type=source_type,
        source_name="test",
        **extra,
    )


# ---------------------------------------------------------------------------
# Base scores
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source_type,min_score",
    [
        (SourceType.fda_ssed, 0.95),
        (SourceType.fda_review, 0.95),
        (SourceType.fda_label, 0.90),
        (SourceType.dailymed_label, 0.90),
        (SourceType.fda_510k, 0.85),
        (SourceType.fda_pma, 0.85),
        (SourceType.fda_denovo, 0.85),
        (SourceType.accessgudid_device, 0.60),
        (SourceType.maude_event, 0.50),
        (SourceType.fda_recall, 0.50),
    ],
)
def test_base_score(source_type: SourceType, min_score: float) -> None:
    rec = _record(source_type)
    score = evidence_strength_score(rec)
    assert score >= min_score, f"{source_type} expected >= {min_score}, got {score}"
    assert 0.0 <= score <= 1.0


def test_pubmed_rct_score() -> None:
    rec = _record(
        SourceType.pubmed_paper,
        raw_payload={"pub_type": ["Randomized Controlled Trial"]},
    )
    score = evidence_strength_score(rec)
    assert score >= 0.75


def test_pubmed_case_series_score() -> None:
    rec = _record(
        SourceType.pubmed_paper,
        title="Case series of retinal patients",
    )
    score = evidence_strength_score(rec)
    assert score <= 0.55


def test_pubmed_review_score() -> None:
    rec = _record(
        SourceType.pubmed_paper,
        title="Systematic review of AMD treatments",
    )
    score = evidence_strength_score(rec)
    assert score <= 0.60


def test_clinicaltrials_phase3_score() -> None:
    rec = _record(SourceType.clinicaltrials, raw_payload={"phase": "Phase 3"})
    score = evidence_strength_score(rec)
    assert score >= 0.80


def test_clinicaltrials_phase1_score() -> None:
    rec = _record(SourceType.clinicaltrials, raw_payload={"phase": "Phase 1"})
    score = evidence_strength_score(rec)
    assert score < 0.80


# ---------------------------------------------------------------------------
# Modifiers
# ---------------------------------------------------------------------------

def test_recency_bonus_applied() -> None:
    import datetime
    recent_year = str(datetime.date.today().year - 1)
    rec_old = _record(SourceType.pubmed_paper)
    rec_new = _record(
        SourceType.pubmed_paper,
        raw_payload={"publication_date": f"{recent_year}-01-01"},
    )
    assert evidence_strength_score(rec_new) >= evidence_strength_score(rec_old)


def test_sample_size_bonus_applied() -> None:
    rec_small = _record(SourceType.pubmed_paper, raw_payload={"enrollment": 10})
    rec_large = _record(SourceType.pubmed_paper, raw_payload={"enrollment": 200})
    assert evidence_strength_score(rec_large) >= evidence_strength_score(rec_small)


def test_score_capped_at_1() -> None:
    import datetime
    recent_year = str(datetime.date.today().year - 1)
    rec = _record(
        SourceType.fda_ssed,
        raw_payload={"publication_date": f"{recent_year}-01-01", "enrollment": 500},
    )
    assert evidence_strength_score(rec) <= 1.0
