"""Tests for PubMed query construction."""

import asyncio
import os

import pytest

from app.models.search import TargetProductProfile
from app.services.pubmed import build_pubmed_query, search_pmids


def test_build_pubmed_query_adds_prospective_from_user_text() -> None:
    """User query containing 'prospective' ANDs a Title/Abstract booster (nAMD test pool)."""
    tp = TargetProductProfile(
        target_type="drug",
        active_ingredient="faricimab",
        indications=["nAMD"],
    )
    q = build_pubmed_query("faricimab nAMD prospective", tp)
    assert "prospective[Title/Abstract]" in q
    assert "faricimab[Title/Abstract]" in q


def test_build_pubmed_query_faricimab_profile() -> None:
    """Structured drug + indications produce field-tagged AND/OR query."""
    tp = TargetProductProfile(
        target_type="drug",
        product_name="faricimab",
        active_ingredient="faricimab",
        drug_class="anti_vegf",
        route="intravitreal",
        indications=["nAMD", "treatment-naive"],
    )
    q = build_pubmed_query(
        "faricimab neovascular age-related macular degeneration intravitreal",
        tp,
    )
    assert "faricimab[Title/Abstract]" in q
    assert " OR " in q
    assert "neovascular age-related macular degeneration" in q
    assert " AND " in q


def test_build_pubmed_query_fallback_no_target() -> None:
    assert build_pubmed_query("cataract intraocular lens", None) == (
        "cataract intraocular lens"
    )


def test_build_pubmed_query_keywords_and_uid() -> None:
    tp = TargetProductProfile(
        target_type="drug",
        active_ingredient="faricimab",
        indications=["DME"],
    )
    q = build_pubmed_query(
        "faricimab diabetic macular edema",
        tp,
        keywords=["REBA", "40943933"],
    )
    assert "faricimab[Title/Abstract]" in q
    assert "40943933[UID]" in q
    assert "REBA[Title/Abstract]" in q


def test_build_pubmed_query_device_category() -> None:
    tp = TargetProductProfile(
        target_type="device",
        device_category="intraocular_lens",
        indications=["cataract"],
    )
    q = build_pubmed_query("hydrophobic lens", tp)
    assert '"intraocular lens"[Title/Abstract]' in q
    assert "cataract[Title/Abstract]" in q


@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_PUBMED"),
    reason="Set RUN_LIVE_PUBMED=1 to hit NCBI ESearch",
)
def test_live_esearch_includes_pmid_39350227() -> None:
    """Golden paper from the faricimab nAMD demo should appear in the pool."""

    async def _run() -> None:
        tp = TargetProductProfile(
            target_type="drug",
            active_ingredient="faricimab",
            indications=["nAMD", "treatment-naive"],
        )
        term = build_pubmed_query(
            "faricimab neovascular age-related macular degeneration intravitreal",
            tp,
        )
        pmids = await search_pmids(term, max_results=100)
        assert "39350227" in pmids, (
            f"PMID 39350227 not in first {len(pmids)} results for {term!r}"
        )

    asyncio.run(_run())
