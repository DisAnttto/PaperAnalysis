"""Shared fixtures for ranking tests.

Ophthalmology-focused after the normalization layer refactor.
Legacy coronary-stent fixtures are kept for backward compat with other tests
that haven't been updated yet; new ophthalmic fixtures are added below.
"""

from datetime import date

import pytest


@pytest.fixture(autouse=True)
def _mock_llm_relevance_for_composite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real LLM calls in composite tests — use deterministic relevance fallback."""

    async def _no_llm(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.ranking.composite.llm_relevance_raw", _no_llm)

from app.models.extraction import (
    DeviceExtraction,
    DrugExtraction,
    EvidenceDomainType,
    EvidenceInt,
    EvidenceStr,
    EvidenceStrList,
    EvidenceStudyType,
    ExtractionResult,
    ExtractedMetric,
    PaperSynopsis,
    StudyExtraction,
    TopicalRelevance,
)
from app.models.normalized import (
    NormalizedDevice,
    NormalizedDrug,
    NormalizedMaterial,
    NormalizedProduct,
)
from app.models.paper import Paper
from app.models.search import (
    SearchRequest,
    TargetMetric,
    TargetProductProfile,
)
from app.normalization import normalize_extraction
from app.normalization.registry import NormalizationMethod


def _ev(val: str, section: str = "abstract") -> EvidenceStr:
    return EvidenceStr(
        value=val, evidence_snippet=val, evidence_section=section,
    )


def _ev_int(val: int, section: str = "abstract") -> EvidenceInt:
    return EvidenceInt(
        value=val, evidence_snippet=str(val), evidence_section=section,
    )


def _ev_list(vals: list[str], section: str = "abstract") -> EvidenceStrList:
    return EvidenceStrList(
        value=vals, evidence_snippet=", ".join(vals), evidence_section=section,
    )


def _make_study(
    study_type: str = "rct",
    domain: str = "human_clinical",
    n: int | None = 200,
) -> StudyExtraction:
    return StudyExtraction(
        study_type=EvidenceStudyType(
            value=study_type,
            evidence_snippet=study_type,
            evidence_section="abstract",
        ),
        evidence_domain=EvidenceDomainType(
            value=domain,
            evidence_snippet=domain,
            evidence_section="abstract",
        ),
        sample_size=_ev_int(n) if n is not None else None,
    )


def _make_synopsis(text: str = "A study.") -> PaperSynopsis:
    return PaperSynopsis(
        value=text,
        supporting_evidence_snippets=[text],
    )


# ---------------------------------------------------------------------------
# Legacy coronary-stent fixtures (unchanged)
# ---------------------------------------------------------------------------

@pytest.fixture()
def paper() -> Paper:
    return Paper(
        pmid="12345678",
        doi="10.1000/test",
        title="Drug-eluting coronary stent outcomes in a randomized trial",
        abstract=(
            "A randomized controlled trial of 500 patients compared "
            "drug-eluting stents with bare-metal stents for coronary "
            "artery disease. The MACE rate was 4.2%."
        ),
        authors=["Smith J", "Doe A"],
        journal="J Cardiol",
        published_date=date(2024, 6, 15),
        mesh_terms=["Coronary Stents", "Drug-Eluting Stents"],
        keywords=["stent", "coronary"],
    )


@pytest.fixture()
def extraction() -> ExtractionResult:
    return ExtractionResult(
        paper_synopsis=_make_synopsis("RCT comparing DES vs BMS outcomes."),
        topical_relevance=TopicalRelevance(
            label="high",
            evidence_snippet="drug-eluting coronary stent",
            evidence_section="title",
        ),
        device=DeviceExtraction(
            product_name=_ev("Xience V"),
            device_category=_ev("coronary stent"),
            manufacturer=_ev("Abbott"),
            intended_use=_ev("percutaneous coronary intervention"),
            indications=_ev_list(["coronary artery disease"]),
            anatomical_site=_ev("left anterior descending artery"),
            material=_ev("cobalt-chromium"),
            key_features=_ev_list(["drug-eluting", "bioresorbable polymer"]),
        ),
        study=StudyExtraction(
            study_type=EvidenceStudyType(
                value="rct",
                evidence_snippet="randomized controlled trial",
                evidence_section="abstract",
            ),
            evidence_domain=EvidenceDomainType(
                value="human_clinical",
                evidence_snippet="500 patients",
                evidence_section="abstract",
            ),
            sample_size=_ev_int(500),
        ),
        metrics=[
            ExtractedMetric(
                metric_name_normalized="mace_rate",
                metric_name_raw="MACE rate",
                metric_category="safety",
                value_type="percentage",
                numeric_value=4.2,
                unit="%",
                evidence_snippet="MACE rate was 4.2%",
                evidence_section="abstract",
            ),
            ExtractedMetric(
                metric_name_normalized="tlr_rate",
                metric_name_raw="TLR rate",
                metric_category="efficacy",
                value_type="percentage",
                numeric_value=2.1,
                unit="%",
                evidence_snippet="TLR rate was 2.1%",
                evidence_section="abstract",
            ),
        ],
    )


@pytest.fixture()
def normalized(extraction: ExtractionResult) -> NormalizedProduct:
    return normalize_extraction(extraction)


@pytest.fixture()
def target_product() -> TargetProductProfile:
    return TargetProductProfile(
        product_name="Xience V",
        device_category="coronary stent",
        manufacturer="Abbott",
        indications=["coronary artery disease"],
        anatomical_site="left anterior descending artery",
        key_features=["drug-eluting"],
    )


@pytest.fixture()
def target_metrics() -> list[TargetMetric]:
    return [
        TargetMetric(
            metric_name_normalized="mace_rate",
            direction="lower_better",
            threshold=10.0,
            normalisation_range=10.0,
        ),
        TargetMetric(
            metric_name_normalized="tlr_rate",
            direction="lower_better",
            threshold=5.0,
            normalisation_range=5.0,
        ),
    ]


@pytest.fixture()
def full_request(
    target_product: TargetProductProfile,
    target_metrics: list[TargetMetric],
) -> SearchRequest:
    return SearchRequest(
        query="drug-eluting coronary stent outcomes",
        mesh_terms=["Coronary Stents"],
        keywords=["stent", "drug-eluting"],
        target_product=target_product,
        target_metrics=target_metrics,
    )


@pytest.fixture()
def minimal_request() -> SearchRequest:
    """Request with no target product and no target metrics."""
    return SearchRequest(query="coronary stent")


# ---------------------------------------------------------------------------
# Ophthalmology IOL fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def iol_paper() -> Paper:
    return Paper(
        pmid="99001122",
        title="Hydrophobic acrylic IOL outcomes after cataract surgery",
        abstract=(
            "Prospective cohort of 250 patients receiving hydrophobic "
            "acrylic intraocular lens (IOL) for cataract. UDVA 0.1 logMAR."
        ),
        published_date=date(2023, 3, 1),
        mesh_terms=["Lenses, Intraocular", "Cataract Extraction"],
    )


@pytest.fixture()
def iol_extraction() -> ExtractionResult:
    return ExtractionResult(
        paper_synopsis=_make_synopsis("Cohort study of hydrophobic acrylic IOL."),
        topical_relevance=TopicalRelevance(
            label="high",
            evidence_snippet="hydrophobic acrylic IOL cataract",
            evidence_section="title",
        ),
        device=DeviceExtraction(
            product_name=_ev("AcrySof IQ"),
            device_category=_ev("intraocular lens"),
            manufacturer=_ev("Alcon"),
            intended_use=_ev("cataract surgery"),
            indications=_ev_list(["cataract"]),
            anatomical_site=_ev("lens capsule"),
            material=_ev("hydrophobic acrylic"),
            key_features=_ev_list(["aspheric", "uv filter"]),
        ),
        study=_make_study("prospective_cohort", "human_clinical", 250),
    )


@pytest.fixture()
def iol_normalized(iol_extraction: ExtractionResult) -> NormalizedProduct:
    return normalize_extraction(iol_extraction)


@pytest.fixture()
def iol_target() -> TargetProductProfile:
    return TargetProductProfile(
        target_type="device",
        device_category="intraocular_lens",
        intended_use="cataract_surgery",
        indications=["cataract"],
        anatomical_site="lens_capsule",
        material_family="acrylic",
        material_subtype="hydrophobic_acrylic",
        material_features=["aspheric", "uv_filter"],
    )


# ---------------------------------------------------------------------------
# Anti-VEGF drug fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def avegf_paper() -> Paper:
    return Paper(
        pmid="88776655",
        title="Ranibizumab vs aflibercept for wet AMD: 12-month outcomes",
        abstract=(
            "RCT of 300 patients with neovascular AMD comparing intravitreal "
            "ranibizumab (Lucentis) and aflibercept (Eylea). BCVA gain 7.1 letters."
        ),
        published_date=date(2022, 9, 10),
        mesh_terms=["Ranibizumab", "Age-Related Macular Degeneration"],
    )


@pytest.fixture()
def avegf_extraction() -> ExtractionResult:
    return ExtractionResult(
        paper_synopsis=_make_synopsis("RCT comparing anti-VEGF drugs for wet AMD."),
        topical_relevance=TopicalRelevance(
            label="high",
            evidence_snippet="ranibizumab vs aflibercept wet AMD",
            evidence_section="title",
        ),
        drug=DrugExtraction(
            product_name=_ev("Lucentis"),
            active_ingredient=_ev("ranibizumab"),
            drug_class=_ev("anti-VEGF"),
            route=_ev("intravitreal"),
            indications=_ev_list(["neovascular AMD", "wet AMD"]),
        ),
        study=_make_study("rct", "human_clinical", 300),
    )


@pytest.fixture()
def avegf_normalized(avegf_extraction: ExtractionResult) -> NormalizedProduct:
    return normalize_extraction(avegf_extraction)


@pytest.fixture()
def avegf_target() -> TargetProductProfile:
    return TargetProductProfile(
        target_type="drug",
        active_ingredient="ranibizumab",
        drug_class="anti_vegf",
        route="intravitreal",
        indications=["macular_degeneration"],
    )
