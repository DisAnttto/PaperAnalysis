"""Seeded ophthalmology paper fixtures for demo/QA mode.

Six papers covering the main ophthalmology product categories:
  1. Hydrophobic acrylic IOL for cataract (prospective cohort, n=250)
  2. Intravitreal faricimab for treatment-naïve nAMD (prospective cohort, PMID 39350227)
  3. Glaucoma drainage device iStent (retrospective cohort, n=150)
  4. Silicone IOL for cataract (case series, n=80)
  5. Dexamethasone intravitreal implant for DME (RCT, n=200)
  6. Drug-eluting contact lens for dry eye (bench/in-vitro, n=30)

Extraction payloads validate against all existing Pydantic models.
NormalizedProduct is computed once at module load.
"""

from datetime import date

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
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper
from app.normalization import normalize_extraction


def _ev(val: str, section: str = "abstract") -> EvidenceStr:
    return EvidenceStr(value=val, evidence_snippet=val, evidence_section=section)


def _ev_int(val: int, section: str = "abstract") -> EvidenceInt:
    return EvidenceInt(value=val, evidence_snippet=str(val), evidence_section=section)


def _ev_list(vals: list[str], section: str = "abstract") -> EvidenceStrList:
    return EvidenceStrList(
        value=vals, evidence_snippet=", ".join(vals), evidence_section=section
    )


def _study(
    study_type: str,
    domain: str,
    n: int | None = None,
) -> StudyExtraction:
    return StudyExtraction(
        study_type=EvidenceStudyType(
            value=study_type,
            evidence_snippet=f"This was a {study_type.replace('_', ' ')} study.",
            evidence_section="abstract",
        ),
        evidence_domain=EvidenceDomainType(
            value=domain,
            evidence_snippet=f"Evidence domain: {domain}.",
            evidence_section="abstract",
        ),
        sample_size=_ev_int(n) if n is not None else None,
    )


def _synopsis(text: str) -> PaperSynopsis:
    return PaperSynopsis(value=text, supporting_evidence_snippets=[text])


def _topical(label: str, snippet: str) -> TopicalRelevance:
    return TopicalRelevance(
        label=label, evidence_snippet=snippet, evidence_section="title"
    )


# ---------------------------------------------------------------------------
# Fixture 1 — Hydrophobic acrylic IOL for cataract
# ---------------------------------------------------------------------------

_P1 = Paper(
    pmid="DEMO001",
    doi="10.1000/demo.001",
    title=(
        "Visual outcomes after implantation of a hydrophobic acrylic intraocular lens "
        "in cataract surgery: a prospective cohort study"
    ),
    abstract=(
        "Purpose: To evaluate visual outcomes following implantation of the AcrySof IQ "
        "hydrophobic acrylic intraocular lens (IOL) in patients undergoing phacoemulsification "
        "for age-related cataract. Methods: A prospective cohort of 250 eyes was enrolled. "
        "The IOL features an aspheric optic with UV filter. Results: Mean uncorrected distance "
        "visual acuity (UDVA) improved to 0.08 logMAR at 3 months. Posterior capsule opacification "
        "(PCO) rate was 6.4% at 12 months. No significant complications were observed. "
        "Conclusion: The hydrophobic acrylic IOL provided excellent visual outcomes with a low PCO rate."
    ),
    authors=["Chen W", "Patel R", "Yamamoto K"],
    journal="Journal of Cataract and Refractive Surgery",
    published_date=date(2023, 5, 15),
    mesh_terms=["Lenses, Intraocular", "Cataract Extraction", "Phacoemulsification"],
    keywords=["intraocular lens", "hydrophobic acrylic", "cataract", "visual acuity"],
)

_E1 = ExtractionResult(
    paper_synopsis=_synopsis(
        "Prospective cohort of 250 eyes with AcrySof IQ hydrophobic acrylic IOL showing "
        "UDVA 0.08 logMAR and 6.4% PCO at 12 months."
    ),
    topical_relevance=_topical(
        "high",
        "hydrophobic acrylic intraocular lens cataract surgery",
    ),
    device=DeviceExtraction(
        product_name=_ev("AcrySof IQ", "title"),
        device_category=_ev("intraocular lens", "abstract"),
        manufacturer=_ev("Alcon", "abstract"),
        intended_use=_ev("cataract surgery", "abstract"),
        indications=_ev_list(["cataract", "age-related cataract"]),
        anatomical_site=_ev("lens capsule", "abstract"),
        material=_ev("hydrophobic acrylic", "abstract"),
        key_features=_ev_list(["aspheric", "uv filter", "foldable"]),
    ),
    study=_study("prospective_cohort", "human_clinical", 250),
    metrics=[
        ExtractedMetric(
            metric_name_normalized="udva_logmar",
            metric_name_raw="UDVA",
            metric_category="efficacy",
            value_type="numeric",
            numeric_value=0.08,
            unit="logMAR",
            timepoint="3 months",
            evidence_snippet="Mean uncorrected distance visual acuity (UDVA) improved to 0.08 logMAR at 3 months.",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="pco_rate",
            metric_name_raw="PCO rate",
            metric_category="safety",
            value_type="percentage",
            numeric_value=6.4,
            unit="%",
            timepoint="12 months",
            evidence_snippet="Posterior capsule opacification (PCO) rate was 6.4% at 12 months.",
            evidence_section="abstract",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Fixture 2 — Faricimab for treatment-naïve nAMD (PMID 39350227, real metadata)
# ---------------------------------------------------------------------------

_P2 = Paper(
    pmid="39350227",
    doi="10.1186/s40942-024-00586-w",
    title=(
        "Intravitreal faricimab for treatment naïve patients with neovascular "
        "age-related macular degeneration: a real-world prospective study."
    ),
    abstract=(
        "Intravitreal faricimab, a bispecific antibody targeting angiopoietin-2 and VEGF-A, "
        "for neovascular age-related macular degeneration (nAMD). "
        "Single-centre, prospective cohort study of 21 eyes from 19 treatment-naïve nAMD "
        "patients treated with intravitreal faricimab. Patients underwent a loading dose of "
        "4 monthly faricimab injections followed by a treat-and-extend regimen. "
        "Primary outcomes included best-corrected visual acuity (BCVA) and spectral-domain "
        "optical coherence tomography (SD-OCT) structural parameters. "
        "After loading, 93.3% of eyes achieved a dry macular SD-OCT scan within a median time "
        "of 8 weeks. At the first extension, 53% of eyes remained dry, while 47% showed fluid "
        "recurrence. Median BCVA, central subfield thickness (CST), and macular volume at "
        "final follow-up improved significantly from baseline (p < 0.01). "
        "The intended interval between injections was ≥ 12 weeks in 42.86% of eyes."
    ),
    authors=["Grimaldi G", "Cancian G", "Paris A", "Clerici M", "Volpe G", "Menghini M"],
    journal="International journal of retina and vitreous",
    published_date=date(2024, 9, 30),
    mesh_terms=[
        "Age-related macular degeneration",
        "Anti-angiopoietin 2",
        "Anti-vascular endothelial growth factor",
        "Faricimab",
        "Treat-and-extend",
    ],
    keywords=[
        "faricimab",
        "nAMD",
        "anti-VEGF",
        "intravitreal",
        "treat-and-extend",
        "treatment-naive",
    ],
)

_E2 = ExtractionResult(
    paper_synopsis=_synopsis(
        "Prospective real-world cohort: intravitreal faricimab in treatment-naïve nAMD; "
        "4 monthly loading injections then treat-and-extend; BCVA and CST improved."
    ),
    topical_relevance=_topical(
        "high",
        "intravitreal faricimab neovascular age-related macular degeneration treatment naïve",
    ),
    drug=DrugExtraction(
        product_name=_ev("Vabysmo", "abstract"),
        active_ingredient=_ev("faricimab", "abstract"),
        drug_class=_ev("anti-VEGF bispecific", "abstract"),
        route=_ev("intravitreal", "abstract"),
        indications=_ev_list(["nAMD", "treatment-naïve neovascular AMD"]),
        formulation_features=_ev_list(["6.0 mg dose"]),
    ),
    study=_study("prospective_cohort", "human_clinical", 21),
    metrics=[
        ExtractedMetric(
            metric_name_normalized="bcva_change",
            metric_name_raw="BCVA change from baseline (median improved)",
            metric_category="efficacy",
            value_type="numeric",
            numeric_value=0.0,
            unit="logMAR change",
            timepoint="final follow-up",
            evidence_snippet=(
                "Median BCVA, CST, and MV at the final follow-up were significantly improved "
                "from baseline (p < 0.01)."
            ),
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="central_retinal_thickness",
            metric_name_raw="central retinal thickness (CST reduction)",
            metric_category="efficacy",
            value_type="numeric",
            numeric_value=1.0,
            unit="µm vs baseline",
            timepoint="final follow-up",
            evidence_snippet="significant reductions in ... central subfield thickness (CST)",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="retinal_fluid_resolution",
            metric_name_raw="retinal fluid resolution (fluid recurrence rate)",
            metric_category="efficacy",
            value_type="percentage",
            numeric_value=47.0,
            unit="%",
            timepoint="first extension",
            evidence_snippet="47% showed fluid recurrence at the first extension.",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="complete_dryness_rate",
            metric_name_raw="complete dryness rate (dry macular SD-OCT)",
            metric_category="efficacy",
            value_type="percentage",
            numeric_value=93.3,
            unit="%",
            timepoint="after loading",
            evidence_snippet="93.3% of eyes achieved a dry macular SD-OCT scan within 8 weeks.",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="treatment_interval",
            metric_name_raw="treatment interval (intended ≥12 weeks)",
            metric_category="efficacy",
            value_type="percentage",
            numeric_value=42.86,
            unit="% of eyes",
            timepoint="last follow-up",
            evidence_snippet="The intended interval between injections was ≥ 12 weeks in 42.86%.",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="injection_frequency",
            metric_name_raw="injection frequency (4 monthly loading regimen)",
            metric_category="efficacy",
            value_type="numeric",
            numeric_value=4.0,
            unit="injections loading",
            timepoint="loading phase",
            evidence_snippet="loading dose (LD) of 4 monthly faricimab injections",
            evidence_section="abstract",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Fixture 3 — Glaucoma drainage device (iStent)
# ---------------------------------------------------------------------------

_P3 = Paper(
    pmid="DEMO003",
    doi="10.1000/demo.003",
    title=(
        "iStent trabecular micro-bypass stent combined with phacoemulsification "
        "for open-angle glaucoma: 24-month retrospective outcomes"
    ),
    abstract=(
        "Purpose: To evaluate the IOP-lowering efficacy of iStent combined with cataract surgery. "
        "Methods: 150 eyes with mild-to-moderate primary open-angle glaucoma (POAG) underwent "
        "combined phacoemulsification and iStent implantation. "
        "Results: Mean IOP decreased from 21.3 mmHg to 15.8 mmHg at 24 months (p<0.001). "
        "Glaucoma medication use reduced from 1.8 to 0.9 drops per day. "
        "No device-related serious adverse events were observed. "
        "Conclusion: iStent combined with cataract surgery effectively reduced IOP and medication burden."
    ),
    authors=["Garcia M", "Lee H", "Thompson S"],
    journal="American Journal of Ophthalmology",
    published_date=date(2021, 11, 20),
    mesh_terms=["Glaucoma, Open-Angle", "Stents", "Intraocular Pressure"],
    keywords=["iStent", "MIGS", "glaucoma", "trabecular meshwork", "IOP"],
)

_E3 = ExtractionResult(
    paper_synopsis=_synopsis(
        "Retrospective cohort of 150 eyes with POAG receiving iStent + phaco; "
        "IOP reduced from 21.3 to 15.8 mmHg at 24 months."
    ),
    topical_relevance=_topical(
        "high",
        "iStent trabecular micro-bypass stent open-angle glaucoma",
    ),
    device=DeviceExtraction(
        product_name=_ev("iStent", "title"),
        device_category=_ev("MIGS device", "abstract"),
        manufacturer=_ev("Glaukos", "abstract"),
        intended_use=_ev("minimally invasive glaucoma surgery", "abstract"),
        indications=_ev_list(["primary open-angle glaucoma", "POAG", "glaucoma"]),
        anatomical_site=_ev("trabecular meshwork", "abstract"),
    ),
    study=_study("retrospective_cohort", "human_clinical", 150),
    metrics=[
        ExtractedMetric(
            metric_name_normalized="iop_mmhg",
            metric_name_raw="IOP",
            metric_category="efficacy",
            value_type="numeric",
            numeric_value=15.8,
            unit="mmHg",
            timepoint="24 months",
            evidence_snippet="Mean IOP decreased from 21.3 mmHg to 15.8 mmHg at 24 months.",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="medication_drops_per_day",
            metric_name_raw="glaucoma medication use",
            metric_category="efficacy",
            value_type="numeric",
            numeric_value=0.9,
            unit="drops/day",
            timepoint="24 months",
            evidence_snippet="Glaucoma medication use reduced from 1.8 to 0.9 drops per day.",
            evidence_section="abstract",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Fixture 4 — Silicone IOL for cataract
# ---------------------------------------------------------------------------

_P4 = Paper(
    pmid="DEMO004",
    doi="10.1000/demo.004",
    title=(
        "Comparison of silicone and hydrophobic acrylic intraocular lenses "
        "for posterior capsule opacification: a case series"
    ),
    abstract=(
        "Objective: To compare PCO rates between silicone and hydrophobic acrylic IOLs. "
        "Methods: 80 eyes received silicone IOL implantation during cataract surgery. "
        "PCO was graded with retroillumination photography. "
        "Results: PCO rate at 24 months was 18.5% for silicone IOLs, significantly higher "
        "than the 6.4% observed in a historical cohort of acrylic IOLs (p=0.002). "
        "UDVA outcomes were comparable between groups at 0.10 logMAR. "
        "Conclusion: Hydrophobic acrylic IOLs showed superior PCO resistance compared to silicone."
    ),
    authors=["Brown T", "Nakamura Y"],
    journal="Eye",
    published_date=date(2020, 3, 10),
    mesh_terms=["Lenses, Intraocular", "Posterior Capsule Opacification", "Silicones"],
    keywords=["silicone IOL", "PCO", "cataract", "lens comparison"],
)

_E4 = ExtractionResult(
    paper_synopsis=_synopsis(
        "Case series of 80 eyes with silicone IOL; PCO rate 18.5% at 24 months, "
        "higher than acrylic historical controls."
    ),
    topical_relevance=_topical(
        "medium",
        "silicone intraocular lens posterior capsule opacification",
    ),
    device=DeviceExtraction(
        product_name=_ev("silicone IOL", "abstract"),
        device_category=_ev("intraocular lens", "abstract"),
        intended_use=_ev("cataract surgery", "abstract"),
        indications=_ev_list(["cataract"]),
        anatomical_site=_ev("lens capsule", "abstract"),
        material=_ev("silicone", "abstract"),
        key_features=_ev_list(["foldable"]),
    ),
    study=_study("case_series", "human_clinical", 80),
    metrics=[
        ExtractedMetric(
            metric_name_normalized="pco_rate",
            metric_name_raw="PCO rate",
            metric_category="safety",
            value_type="percentage",
            numeric_value=18.5,
            unit="%",
            timepoint="24 months",
            evidence_snippet="PCO rate at 24 months was 18.5% for silicone IOLs.",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="udva_logmar",
            metric_name_raw="UDVA",
            metric_category="efficacy",
            value_type="numeric",
            numeric_value=0.10,
            unit="logMAR",
            timepoint="24 months",
            evidence_snippet="UDVA outcomes were comparable between groups at 0.10 logMAR.",
            evidence_section="abstract",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Fixture 5 — Dexamethasone intravitreal implant for DME
# ---------------------------------------------------------------------------

_P5 = Paper(
    pmid="DEMO005",
    doi="10.1000/demo.005",
    title=(
        "Dexamethasone intravitreal implant (Ozurdex) for diabetic macular edema: "
        "results from a randomized controlled trial"
    ),
    abstract=(
        "Purpose: To evaluate the efficacy and safety of the dexamethasone 0.7 mg "
        "intravitreal implant (Ozurdex) for diabetic macular edema (DME). "
        "Methods: 200 patients with persistent DME were randomized to Ozurdex or sham injection. "
        "Results: Proportion of patients gaining ≥15 letters BCVA at 3 months was 22.2% "
        "with Ozurdex versus 12.0% with sham (p=0.007). Mean central subfield thickness "
        "decreased by 127 µm. Intraocular pressure increase >10 mmHg occurred in 15.4% of "
        "Ozurdex-treated eyes. "
        "Conclusion: Ozurdex provided significant improvement in DME with manageable IOP side effects."
    ),
    authors=["Kumar A", "Martinez E", "Park J"],
    journal="JAMA Ophthalmology",
    published_date=date(2023, 1, 15),
    mesh_terms=["Dexamethasone", "Macular Edema", "Diabetic Retinopathy"],
    keywords=["dexamethasone", "Ozurdex", "DME", "intravitreal implant", "corticosteroid"],
)

_E5 = ExtractionResult(
    paper_synopsis=_synopsis(
        "RCT of 200 patients with DME comparing dexamethasone implant (Ozurdex) vs sham; "
        "22.2% gained ≥15 BCVA letters at 3 months."
    ),
    topical_relevance=_topical(
        "high",
        "dexamethasone intravitreal implant diabetic macular edema",
    ),
    drug=DrugExtraction(
        product_name=_ev("Ozurdex", "title"),
        active_ingredient=_ev("dexamethasone", "abstract"),
        drug_class=_ev("corticosteroid", "abstract"),
        route=_ev("intravitreal", "abstract"),
        indications=_ev_list(["diabetic macular edema", "DME"]),
        formulation_features=_ev_list(["sustained release implant", "0.7 mg"]),
    ),
    study=_study("rct", "human_clinical", 200),
    metrics=[
        ExtractedMetric(
            metric_name_normalized="bcva_15_letters_gain_proportion",
            metric_name_raw="proportion gaining ≥15 letters",
            metric_category="efficacy",
            value_type="percentage",
            numeric_value=22.2,
            unit="%",
            timepoint="3 months",
            evidence_snippet=(
                "Proportion of patients gaining ≥15 letters BCVA at 3 months was 22.2% with Ozurdex."
            ),
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="iop_increase_rate",
            metric_name_raw="IOP increase >10 mmHg",
            metric_category="adverse_event",
            value_type="percentage",
            numeric_value=15.4,
            unit="%",
            evidence_snippet="Intraocular pressure increase >10 mmHg occurred in 15.4% of Ozurdex-treated eyes.",
            evidence_section="abstract",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Fixture 6 — Drug-eluting contact lens for dry eye disease
# ---------------------------------------------------------------------------

_P6 = Paper(
    pmid="DEMO006",
    doi="10.1000/demo.006",
    title=(
        "Cyclosporine-eluting contact lens for dry eye disease: "
        "in vitro drug release and biocompatibility evaluation"
    ),
    abstract=(
        "Purpose: To develop and characterize a cyclosporine-eluting silicone hydrogel contact lens "
        "for treatment of dry eye disease (DED). "
        "Methods: 30 lens samples were prepared with 0.05% cyclosporine encapsulated in a "
        "hydrogel matrix. In vitro drug release was evaluated over 30 days. "
        "Biocompatibility was assessed using human corneal epithelial cell culture. "
        "Results: Sustained cyclosporine release of 1.2 µg/day was achieved over 28 days. "
        "Cell viability remained above 90% throughout. Contact angle was 52° indicating "
        "good wettability. "
        "Conclusion: Cyclosporine-eluting contact lenses show promise as drug delivery platforms for DED."
    ),
    authors=["Liu X", "Sharma N", "O'Brien C"],
    journal="Biomaterials",
    published_date=date(2024, 2, 28),
    mesh_terms=["Contact Lenses", "Cyclosporine", "Dry Eye Syndromes", "Drug Delivery Systems"],
    keywords=["drug-eluting contact lens", "cyclosporine", "dry eye", "sustained release"],
)

_E6 = ExtractionResult(
    paper_synopsis=_synopsis(
        "In vitro study of cyclosporine-eluting silicone hydrogel contact lens; "
        "1.2 µg/day release over 28 days with good biocompatibility."
    ),
    topical_relevance=_topical(
        "medium",
        "cyclosporine-eluting contact lens dry eye disease",
    ),
    device=DeviceExtraction(
        product_name=_ev("cyclosporine-eluting contact lens", "title"),
        device_category=_ev("contact lens", "abstract"),
        intended_use=_ev("dry eye disease treatment", "abstract"),
        indications=_ev_list(["dry eye disease", "DED"]),
        anatomical_site=_ev("cornea", "abstract"),
        material=_ev("silicone hydrogel", "abstract"),
        key_features=_ev_list(["drug-eluting", "sustained release", "preservative-free"]),
    ),
    drug=DrugExtraction(
        active_ingredient=_ev("cyclosporine", "abstract"),
        drug_class=_ev("immunomodulator", "abstract"),
        route=_ev("topical", "abstract"),
        indications=_ev_list(["dry eye disease"]),
        formulation_features=_ev_list(["0.05%", "sustained release"]),
    ),
    study=_study("in_vitro_study", "in_vitro", 30),
    metrics=[
        ExtractedMetric(
            metric_name_normalized="drug_release_rate",
            metric_name_raw="cyclosporine release",
            metric_category="performance",
            value_type="numeric",
            numeric_value=1.2,
            unit="µg/day",
            timepoint="28 days",
            evidence_snippet="Sustained cyclosporine release of 1.2 µg/day was achieved over 28 days.",
            evidence_section="abstract",
        ),
        ExtractedMetric(
            metric_name_normalized="cell_viability",
            metric_name_raw="cell viability",
            metric_category="biocompatibility",
            value_type="percentage",
            numeric_value=90.0,
            unit="%",
            evidence_snippet="Cell viability remained above 90% throughout.",
            evidence_section="abstract",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Registry — build normalized products at module load
# ---------------------------------------------------------------------------

_PAPERS: dict[str, Paper] = {
    p.pmid: p for p in [_P1, _P2, _P3, _P4, _P5, _P6] if p.pmid
}

_EXTRACTIONS: dict[str, ExtractionResult] = {
    "DEMO001": _E1,
    "39350227": _E2,
    "DEMO003": _E3,
    "DEMO004": _E4,
    "DEMO005": _E5,
    "DEMO006": _E6,
}

_NORMALIZED: dict[str, NormalizedProduct] = {
    pmid: normalize_extraction(ext) for pmid, ext in _EXTRACTIONS.items()
}


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------

def get_demo_papers() -> list[Paper]:
    return list(_PAPERS.values())


def get_demo_paper(pmid: str) -> Paper | None:
    return _PAPERS.get(pmid)


def get_demo_extraction(pmid: str) -> ExtractionResult | None:
    return _EXTRACTIONS.get(pmid)


def get_demo_normalized(pmid: str) -> NormalizedProduct | None:
    return _NORMALIZED.get(pmid)


def get_all_demo_triples() -> list[tuple[Paper, ExtractionResult, NormalizedProduct]]:
    """Return all (paper, extraction, normalized) tuples for ranking."""
    return [
        (_PAPERS[pmid], _EXTRACTIONS[pmid], _NORMALIZED[pmid])
        for pmid in _PAPERS
    ]
