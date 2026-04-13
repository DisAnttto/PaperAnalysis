"""Tests for fuse_candidates in app/retrieval/fusion.py."""

from __future__ import annotations

from app.retrieval.enums import SourceType
from app.retrieval.fusion import _canonical, fuse_candidates
from app.retrieval.models import EvidenceRecord


def _rec(identifier: str, *, source_type=SourceType.pubmed_paper, **kwargs) -> EvidenceRecord:
    return EvidenceRecord(
        identifier=identifier,
        source_type=source_type,
        source_name="test",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Canonical identifier tests
# ---------------------------------------------------------------------------

def test_canonical_strips_prefix() -> None:
    assert _canonical("PMID:12345") == _canonical("pmid:12345")
    assert _canonical("PMID:12345") == "12345"


def test_canonical_strips_multiple_formats() -> None:
    assert _canonical("NCT:04709952") == _canonical("nct:04709952")


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------

def test_no_duplicates_unchanged() -> None:
    recs = [_rec("PMID:001"), _rec("PMID:002"), _rec("PMID:003")]
    result = fuse_candidates(recs)
    assert len(result) == 3


def test_exact_duplicates_merged() -> None:
    recs = [_rec("PMID:001"), _rec("PMID:001")]
    result = fuse_candidates(recs)
    assert len(result) == 1
    assert result[0].identifier == "PMID:001"


def test_case_insensitive_dedup() -> None:
    recs = [_rec("PMID:12345"), _rec("pmid:12345")]
    result = fuse_candidates(recs)
    assert len(result) == 1


def test_prefix_variant_dedup() -> None:
    """K211668 and 510K:K211668 share canonical '211668'... vary by prefix."""
    recs = [
        _rec("510K:K211668", source_type=SourceType.fda_510k),
        _rec("510K:K211668", source_type=SourceType.fda_510k, title="Duplicate device"),
    ]
    result = fuse_candidates(recs)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Field merging tests
# ---------------------------------------------------------------------------

def test_merge_prefers_non_none_title() -> None:
    recs = [
        _rec("PMID:001", title=None),
        _rec("PMID:001", title="Article Title"),
    ]
    result = fuse_candidates(recs)
    assert result[0].title == "Article Title"


def test_merge_union_indications() -> None:
    recs = [
        _rec("PMID:001", indication=["AMD"]),
        _rec("PMID:001", indication=["DME"]),
    ]
    result = fuse_candidates(recs)
    assert "AMD" in result[0].indication
    assert "DME" in result[0].indication


def test_merge_union_endpoints() -> None:
    recs = [
        _rec("PMID:001", endpoints=["BCVA"]),
        _rec("PMID:001", endpoints=["OCT"]),
    ]
    result = fuse_candidates(recs)
    assert "BCVA" in result[0].endpoints
    assert "OCT" in result[0].endpoints


def test_merge_raw_payload_keys() -> None:
    recs = [
        _rec("PMID:001", raw_payload={"a": 1}),
        _rec("PMID:001", raw_payload={"b": 2}),
    ]
    result = fuse_candidates(recs)
    assert result[0].raw_payload is not None
    assert "a" in result[0].raw_payload


def test_ordering_preserved() -> None:
    recs = [_rec("PMID:003"), _rec("PMID:001"), _rec("PMID:002")]
    result = fuse_candidates(recs)
    assert [r.identifier for r in result] == ["PMID:003", "PMID:001", "PMID:002"]
