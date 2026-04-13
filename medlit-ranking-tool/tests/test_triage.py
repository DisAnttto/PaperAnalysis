"""Unit tests for hybrid score-and-rank triage."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.models.paper import Paper
from app.models.search import SearchRequest, TargetProductProfile
from app.services.triage import (
    _REGULATORY_SOURCES,
    _ScoredPaper,
    _allocate_slots,
    _combine_and_select,
    _parse_scored_lines,
    detect_anchors,
    prescore_paper,
    prescore_regulatory,
    triage_papers,
    triage_papers_stream,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _faricimab_profile() -> TargetProductProfile:
    return TargetProductProfile(
        target_type="drug",
        product_name="faricimab",
        active_ingredient="faricimab",
        drug_class="anti_vegf",
        route="intravitreal",
        indications=["nAMD", "treatment-naive"],
    )


def _device_profile() -> TargetProductProfile:
    return TargetProductProfile(
        target_type="device",
        device_category="intraocular_lens",
        intended_use="cataract surgery",
        indications=["cataract"],
    )


def _paper(
    pmid: str,
    title: str,
    abstract: str = "",
    mesh: list[str] | None = None,
    source: str = "PubMed",
) -> Paper:
    return Paper(
        pmid=pmid if source == "PubMed" else None,
        identifier=pmid if source != "PubMed" else None,
        source=source,
        title=title,
        abstract=abstract or None,
        mesh_terms=mesh or [],
    )


def _reg_paper(identifier: str, title: str, abstract: str = "", source: str = "openFDA") -> Paper:
    return Paper(
        identifier=identifier,
        source=source,
        title=title,
        abstract=abstract or None,
    )


# ---------------------------------------------------------------------------
# prescore_paper (literature)
# ---------------------------------------------------------------------------

class TestPrescorePaper:
    def test_perfect_match_drug_in_title(self):
        tp = _faricimab_profile()
        p = _paper("1", "Faricimab for neovascular AMD", "A study of faricimab.")
        score = prescore_paper(p, "faricimab nAMD", tp)
        assert score >= 0.5, f"Expected >= 0.5 for drug-in-title, got {score}"

    def test_drug_in_abstract_only(self):
        tp = _faricimab_profile()
        p = _paper("2", "Treatment of nAMD with bispecific antibody",
                    "Faricimab was administered intravitreally.")
        score = prescore_paper(p, "faricimab nAMD", tp)
        assert 0.2 < score < 0.9

    def test_no_match_returns_low(self):
        tp = _faricimab_profile()
        p = _paper("3", "Glaucoma drainage devices",
                    "This study evaluates tube shunt outcomes.")
        score = prescore_paper(p, "faricimab nAMD", tp)
        assert score < 0.2

    def test_no_target_profile_uses_query_only(self):
        p = _paper("4", "Faricimab phase 3 trial results",
                    "Intravitreal faricimab showed improvements.")
        score = prescore_paper(p, "faricimab phase trial", None)
        assert score > 0.0

    def test_device_profile_with_category_in_title(self):
        tp = _device_profile()
        p = _paper("5", "Novel intraocular lens for cataract surgery",
                    "A new IOL design with hydrophobic acrylic.")
        score = prescore_paper(p, "intraocular lens cataract", tp)
        assert score >= 0.4

    def test_mesh_overlap_boosts_score(self):
        tp = _faricimab_profile()
        p = _paper(
            "6", "Anti-VEGF therapy results",
            "A clinical study.",
            mesh=["Vascular Endothelial Growth Factors", "faricimab", "Macular Degeneration"],
        )
        score = prescore_paper(p, "faricimab", tp)
        assert score > 0.0

    def test_score_bounded_zero_one(self):
        tp = _faricimab_profile()
        p = _paper("7", "Unrelated paper about diabetes", "No eye content.")
        score = prescore_paper(p, "nothing relevant", tp)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# prescore_regulatory (new)
# ---------------------------------------------------------------------------

class TestPrescoreRegulatory:
    def test_product_name_in_title_scores_high(self):
        tp = _faricimab_profile()
        p = _reg_paper("K123456", "Faricimab 510(k) clearance summary")
        score = prescore_regulatory(p, "faricimab nAMD", tp)
        assert score >= 0.4, f"Expected >= 0.4, got {score}"

    def test_unrelated_record_scores_low(self):
        tp = _faricimab_profile()
        p = _reg_paper("K999999", "Glucose monitor calibration device")
        score = prescore_regulatory(p, "faricimab nAMD", tp)
        assert score < 0.2

    def test_identifier_match_boosts_score(self):
        tp = _faricimab_profile()
        p = _reg_paper("K123456", "Ophthalmic device clearance")
        # Query mentions the exact K-number
        score = prescore_regulatory(p, "K123456 faricimab nAMD", tp)
        score_no_id = prescore_regulatory(p, "faricimab nAMD", tp)
        assert score > score_no_id

    def test_no_abstract_does_not_break_scoring(self):
        tp = _faricimab_profile()
        p = _reg_paper("K111111", "Faricimab drug label", abstract="")
        score = prescore_regulatory(p, "faricimab", tp)
        assert 0.0 <= score <= 1.0

    def test_score_bounded_zero_one(self):
        tp = _faricimab_profile()
        p = _reg_paper("FDA_LABEL:X", "Unrelated label", "Completely unrelated content.")
        score = prescore_regulatory(p, "nothing relevant", tp)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# detect_anchors
# ---------------------------------------------------------------------------

class TestDetectAnchors:
    def test_drug_name_in_title(self):
        tp = _faricimab_profile()
        papers = [
            _paper("100", "Faricimab for treatment-naive nAMD patients"),
            _paper("101", "Ranibizumab vs aflibercept in wet AMD"),
        ]
        anchors = detect_anchors(papers, tp)
        assert "100" in anchors
        assert "101" not in anchors

    def test_case_insensitive(self):
        tp = _faricimab_profile()
        papers = [_paper("200", "FARICIMAB Safety and Efficacy")]
        assert "200" in detect_anchors(papers, tp)

    def test_no_profile_returns_empty(self):
        papers = [_paper("300", "Some paper title")]
        assert detect_anchors(papers, None) == set()

    def test_product_name_also_anchors(self):
        tp = TargetProductProfile(
            target_type="drug",
            product_name="Vabysmo",
            active_ingredient="faricimab",
        )
        papers = [_paper("400", "Vabysmo real-world outcomes")]
        assert "400" in detect_anchors(papers, tp)

    def test_no_anchors_when_name_not_in_title(self):
        tp = _faricimab_profile()
        papers = [
            _paper("500", "Anti-VEGF treatment outcomes", "faricimab was used"),
        ]
        anchors = detect_anchors(papers, tp)
        assert len(anchors) == 0


# ---------------------------------------------------------------------------
# _parse_scored_lines
# ---------------------------------------------------------------------------

class TestParseScoredLines:
    def test_basic_tab_separated(self):
        raw = "12345678\t10\n23456789\t8\n34567890\t3"
        allowed = {"12345678", "23456789", "34567890"}
        scores = _parse_scored_lines(raw, allowed)
        assert scores["12345678"] == pytest.approx(1.0)
        assert scores["23456789"] == pytest.approx(0.8)
        assert scores["34567890"] == pytest.approx(0.3)

    def test_space_separated(self):
        raw = "12345678 9\n23456789 5"
        allowed = {"12345678", "23456789"}
        scores = _parse_scored_lines(raw, allowed)
        assert scores["12345678"] == pytest.approx(0.9)
        assert scores["23456789"] == pytest.approx(0.5)

    def test_code_fence_stripped(self):
        raw = "```\n12345678\t7\n23456789\t4\n```"
        allowed = {"12345678", "23456789"}
        scores = _parse_scored_lines(raw, allowed)
        assert len(scores) == 2

    def test_filters_unknown_pmids(self):
        raw = "12345678\t10\n99999999\t8"
        allowed = {"12345678"}
        scores = _parse_scored_lines(raw, allowed)
        assert "12345678" in scores
        assert "99999999" not in scores

    def test_score_clamped_to_one(self):
        raw = "12345678\t15"
        allowed = {"12345678"}
        scores = _parse_scored_lines(raw, allowed)
        assert scores["12345678"] == pytest.approx(1.0)

    def test_empty_string(self):
        assert _parse_scored_lines("", {"123"}) == {}

    def test_garbage_input(self):
        assert _parse_scored_lines("no pmids here\njust text", {"123"}) == {}

    def test_regulatory_ids_parsed(self):
        """K-numbers, FDA_LABEL, GUDID, DM prefixes are all valid UIDs."""
        raw = "K123456\t9\nFDA_LABEL:NDA201234\t7\nGUDID:00884412345670\t5\nDM:abc123\t3"
        allowed = {"K123456", "FDA_LABEL:NDA201234", "GUDID:00884412345670", "DM:abc123"}
        scores = _parse_scored_lines(raw, allowed)
        assert len(scores) == 4
        assert scores["K123456"] == pytest.approx(0.9)
        assert scores["FDA_LABEL:NDA201234"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# _allocate_slots
# ---------------------------------------------------------------------------

class TestAllocateSlots:
    def test_no_regulatory_all_lit(self):
        assert _allocate_slots(50, 0, 10) == (10, 0)

    def test_no_lit_all_reg(self):
        assert _allocate_slots(0, 50, 10) == (0, 10)

    def test_both_present_30pct_reg(self):
        lit, reg = _allocate_slots(100, 20, 10)
        assert lit + reg == 10
        assert reg >= 1
        assert lit >= 1

    def test_reg_capped_by_pool_size(self):
        # Only 2 regulatory records; reg_slots should not exceed 2
        lit, reg = _allocate_slots(100, 2, 10)
        assert reg <= 2
        assert lit + reg == 10

    def test_total_equals_top_n(self):
        for n_reg in [0, 1, 5, 20]:
            lit, reg = _allocate_slots(50, n_reg, 10)
            assert lit + reg == 10


# ---------------------------------------------------------------------------
# _combine_and_select — anchor overflow fix
# ---------------------------------------------------------------------------

class TestCombineAndSelect:
    def test_basic_ordering(self):
        items = [
            _ScoredPaper(uid="A", pre_score=0.8, llm_score=0.9),
            _ScoredPaper(uid="B", pre_score=0.3, llm_score=0.2),
            _ScoredPaper(uid="C", pre_score=0.5, llm_score=0.6),
        ]
        result = _combine_and_select(items, 2)
        assert result[0] == "A"
        assert len(result) == 2

    def test_anchor_floor_lifts_low_scoring_paper(self):
        items = [
            _ScoredPaper(uid="anchor", pre_score=0.1, llm_score=0.1, is_anchor=True),
            _ScoredPaper(uid="normal", pre_score=0.3, llm_score=0.3),
        ]
        result = _combine_and_select(items, 2)
        # Anchor gets floor of 0.5; normal gets 0.35*0.3 + 0.65*0.3 = 0.3
        assert result[0] == "anchor"

    def test_anchor_guarantee_survives_top_n(self):
        items = [
            _ScoredPaper(uid="top1", pre_score=0.9, llm_score=0.9),
            _ScoredPaper(uid="top2", pre_score=0.8, llm_score=0.8),
            _ScoredPaper(uid="anchor", pre_score=0.1, llm_score=0.05, is_anchor=True),
        ]
        result = _combine_and_select(items, 3)
        assert "anchor" in result

    def test_anchors_capped_at_top_n(self):
        """Regression: 5 anchors with top_n=3 must not consume all slots.

        Under the old uncapped code, all 5 anchors were added before the
        slot-fill loop, which meant non-anchor papers were never selected.
        The cap ensures at most top_n anchors are taken.
        """
        items = [
            _ScoredPaper(uid=f"anchor{i}", pre_score=0.5, is_anchor=True)
            for i in range(5)
        ]
        items.append(_ScoredPaper(uid="normal", pre_score=0.9))
        result = _combine_and_select(items, 3)
        assert len(result) == 3

    def test_no_llm_score_uses_prescore_only(self):
        items = [
            _ScoredPaper(uid="X", pre_score=0.7, llm_score=None),
            _ScoredPaper(uid="Y", pre_score=0.3, llm_score=None),
        ]
        result = _combine_and_select(items, 2)
        assert result == ["X", "Y"]

    def test_respects_top_n(self):
        items = [_ScoredPaper(uid=str(i), pre_score=i / 10) for i in range(10)]
        result = _combine_and_select(items, 3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# triage_papers (integration with mocked LLM) — split-track
# ---------------------------------------------------------------------------

class TestTriagePapers:
    def test_skips_llm_when_pool_not_larger_than_top_n(self):
        papers = [
            _paper("1", "A", "x"),
            _paper("2", "B", "y"),
        ]
        out = asyncio.run(triage_papers(papers, "q", None, 5))
        assert out == ["1", "2"]

    def test_returns_empty_for_no_papers(self):
        assert asyncio.run(triage_papers([], "q", None, 5)) == []

    def test_anchor_guarantee_with_mocked_llm(self):
        """Even when LLM gives anchor a score of 0, it survives."""
        tp = _faricimab_profile()
        papers = [
            _paper("39350227", "Intravitreal faricimab for treatment naive nAMD",
                    "Real-world study of faricimab in nAMD patients."),
            *[_paper(str(i), f"Unrelated paper {i}", "Not about faricimab.") for i in range(10, 20)],
        ]

        llm_output = "\n".join(
            f"{p.pmid}\t{8 - idx}" for idx, p in enumerate(papers) if p.pmid != "39350227"
        ) + "\n39350227\t0\n"

        async def _run():
            with patch(
                "app.services.triage._call_scoring_llm",
                new_callable=AsyncMock,
                return_value=llm_output,
            ):
                return await triage_papers(papers, "faricimab nAMD", tp, 5)

        result = asyncio.run(_run())
        assert "39350227" in result

    def test_fallback_on_llm_failure(self):
        papers = [_paper(str(i), f"T{i}", "abstract " * 20) for i in range(10000, 10006)]

        async def _run():
            with patch(
                "app.services.triage._call_scoring_llm",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API down"),
            ):
                return await triage_papers(papers, "query", None, 3)

        result = asyncio.run(_run())
        assert len(result) == 3

    def test_llm_scores_respected_in_ordering(self):
        papers = [_paper(str(i), f"Paper {i}", "some abstract text " * 10) for i in range(10000, 10006)]

        llm_output = "10002\t10\n10004\t9\n10000\t7\n10001\t5\n10003\t3\n10005\t1\n"

        async def _run():
            with patch(
                "app.services.triage._call_scoring_llm",
                new_callable=AsyncMock,
                return_value=llm_output,
            ):
                return await triage_papers(papers, "query", None, 3)

        result = asyncio.run(_run())
        assert result[0] == "10002"

    def test_regulatory_papers_appear_in_results(self):
        """openFDA / ClinicalTrials records must survive triage alongside PubMed."""
        tp = _faricimab_profile()
        lit_papers = [
            _paper(str(i), f"Faricimab clinical study {i}", "faricimab nAMD abstract")
            for i in range(10000, 10010)
        ]
        reg_papers = [
            _reg_paper("K123456", "Faricimab drug label", source="openFDA"),
            _reg_paper("NCT12345678", "Faricimab phase 3 trial", source="ClinicalTrials"),
        ]
        all_papers = lit_papers + reg_papers

        lit_llm = "\n".join(f"{p.pmid}\t7" for p in lit_papers)
        reg_llm = "K123456\t9\nNCT12345678\t8\n"

        async def _run():
            with patch(
                "app.services.triage._call_scoring_llm",
                new_callable=AsyncMock,
                side_effect=[lit_llm, reg_llm],
            ):
                return await triage_papers(all_papers, "faricimab nAMD", tp, 5)

        result = asyncio.run(_run())
        result_set = set(result)
        # At least one regulatory record must appear
        assert "K123456" in result_set or "NCT12345678" in result_set, (
            f"No regulatory records in result: {result}"
        )

    def test_split_tracks_pubmed_only(self):
        """When only PubMed papers are present, all slots go to the literature track."""
        papers = [_paper(str(i), f"Paper {i}", "abstract text") for i in range(20)]

        async def _run():
            with patch(
                "app.services.triage._call_scoring_llm",
                new_callable=AsyncMock,
                return_value="\n".join(f"{i}\t5" for i in range(20)),
            ):
                return await triage_papers(papers, "query", None, 5)

        result = asyncio.run(_run())
        assert len(result) == 5

    def test_split_tracks_regulatory_only(self):
        """When only regulatory papers are present, all slots go to the regulatory track."""
        papers = [
            _reg_paper(f"K{i:06d}", f"Device clearance {i}", source="openFDA")
            for i in range(20)
        ]

        async def _run():
            with patch(
                "app.services.triage._call_scoring_llm",
                new_callable=AsyncMock,
                return_value="\n".join(f"K{i:06d}\t5" for i in range(20)),
            ):
                return await triage_papers(papers, "query", None, 5)

        result = asyncio.run(_run())
        assert len(result) == 5


# ---------------------------------------------------------------------------
# triage_papers_stream
# ---------------------------------------------------------------------------

class TestTriagePapersStream:
    def test_small_pool_yields_all(self):
        papers = [_paper("1", "A"), _paper("2", "B")]

        async def _run():
            out = []
            async for pmid in triage_papers_stream(papers, "q", None, 5):
                out.append(pmid)
            return out

        assert asyncio.run(_run()) == ["1", "2"]

    def test_anchors_yielded_first(self):
        tp = _faricimab_profile()
        papers = [
            *[_paper(str(i), f"Unrelated paper {i}", "nothing") for i in range(10000, 10005)],
            _paper("39350227", "Faricimab for nAMD", "Real world data on faricimab"),
        ]

        async def fake_stream():
            for p in papers:
                uid = p.pmid or p.identifier
                if uid:
                    yield f"{uid}\t5\n"

        async def _run():
            out = []
            with patch(
                "app.services.triage._stream_scoring_llm",
                return_value=fake_stream(),
            ):
                async for pmid in triage_papers_stream(papers, "faricimab nAMD", tp, 3):
                    out.append(pmid)
            return out

        result = asyncio.run(_run())
        assert result[0] == "39350227"

    def test_stream_matches_batch_when_all_pool_papers_are_anchors(self) -> None:
        """Regression: many title-anchors used to make stream return only top_n
        arbitrary anchors and skip hybrid ranking (wrong PMIDs vs batch triage).
        """
        tp = _faricimab_profile()
        papers = [
            _paper(str(39350220 + i), f"faricimab cohort paper {i}", "nAMD abstract " * 15)
            for i in range(8)
        ]
        llm_lines = "\n".join(f"{p.pmid}\t5" for p in papers) + "\n"

        async def _batch() -> list[str]:
            with patch(
                "app.services.triage._call_scoring_llm",
                new_callable=AsyncMock,
                return_value=llm_lines,
            ):
                return await triage_papers(papers, "faricimab nAMD", tp, 3)

        async def fake_stream():
            yield llm_lines

        async def _stream() -> list[str]:
            with patch(
                "app.services.triage._stream_scoring_llm",
                return_value=fake_stream(),
            ):
                return [p async for p in triage_papers_stream(papers, "faricimab nAMD", tp, 3)]

        assert asyncio.run(_batch()) == asyncio.run(_stream())

    def test_regulatory_papers_in_stream_output(self):
        """Regulatory records must appear in streaming output."""
        tp = _faricimab_profile()
        lit_papers = [
            _paper(str(i), f"Faricimab study {i}", "faricimab nAMD")
            for i in range(10000, 10008)
        ]
        reg_papers = [
            _reg_paper("K123456", "Faricimab 510k", source="openFDA"),
        ]
        all_papers = lit_papers + reg_papers

        lit_llm = "\n".join(f"{p.pmid}\t6" for p in lit_papers)
        reg_llm = "K123456\t9\n"

        async def _run():
            out = []
            with patch(
                "app.services.triage._stream_scoring_llm",
                side_effect=[
                    _async_gen_lines(lit_llm),
                    _async_gen_lines(reg_llm),
                ],
            ):
                async for uid in triage_papers_stream(all_papers, "faricimab nAMD", tp, 5):
                    out.append(uid)
            return out

        result = asyncio.run(_run())
        assert "K123456" in result


async def _async_gen_lines(text: str):
    """Helper: async generator that yields the text as single chunk."""
    yield text


# ---------------------------------------------------------------------------
# SearchRequest validation (unchanged)
# ---------------------------------------------------------------------------

def test_search_request_pool_must_be_at_least_max_results():
    with pytest.raises(ValidationError):
        SearchRequest(query="x", pool_size=10, max_results=50)
