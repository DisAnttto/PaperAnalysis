"""Offline validation of tests/collection/cases.json (no PubMed / LLM)."""

from tests.collection import load_collection


def test_collection_version():
    coll = load_collection()
    assert coll.version == 1


def test_collection_has_faricimab_case():
    coll = load_collection()
    ids = {c.id for c in coll.cases}
    assert "faricimab_namd_39350227" in ids


def test_collection_has_gold_cases():
    coll = load_collection()
    ids = {c.id for c in coll.cases}
    assert len(coll.cases) >= 11
    expected = {
        "faricimab_dme_40943933",
        "aflibercept_dme_te_32783421",
        "aflibercept_dme_te_33559843",
        "ozurdex_dme_25574787",
        "brolucizumab_namd_38063874",
        "panoptix_iol_37641668",
        "clareon_panoptix_39465378",
        "ahmed_valve_32184556",
        "xen_stent_31197608",
        "iol_pod1_iop_safety",
    }
    assert expected <= ids


def test_every_case_validates():
    coll = load_collection()
    assert len(coll.cases) >= 1
    for c in coll.cases:
        assert c.id
        assert c.request.query


def test_iop_safety_case_structure():
    """Offline check: IOP case has the expected shape including thematic expectations."""
    coll = load_collection()
    iop = next((c for c in coll.cases if c.id == "iol_pod1_iop_safety"), None)
    assert iop is not None, "iol_pod1_iop_safety case missing from cases.json"

    # PMID anchors for the three key evidence buckets
    assert set(iop.expectations.golden_pmids) == {"11159474", "8784635", "35187424"}

    # Composite floor: ~25% below run-02 actuals to allow LLM variance
    for pmid in iop.expectations.golden_pmids:
        assert pmid in iop.expectations.min_composite_by_pmid
        assert iop.expectations.min_composite_by_pmid[pmid] >= 0.40
        assert pmid in iop.expectations.max_rank_by_pmid
        # Must appear in literature section (ranks 1-14), not below regulatory filler
        assert iop.expectations.max_rank_by_pmid[pmid] <= 14

    # M dimension must be active
    assert iop.expectations.min_m_nonzero_count is not None
    assert iop.expectations.min_m_nonzero_count >= 10

    # Glaucoma-procedure papers must not dominate top 10
    assert iop.expectations.max_glaucoma_procedure_in_top_n is not None
    max_count, top_n = iop.expectations.max_glaucoma_procedure_in_top_n
    assert top_n == 10
    assert max_count <= 3

    # Target must be a device (IOL), not a drug
    assert iop.request.target_product is not None
    assert iop.request.target_product.target_type == "device"
    assert iop.request.target_product.device_category == "intraocular_lens"

    # M dimension powered by metrics_of_interest
    assert iop.request.metrics_of_interest
    assert any("IOP" in m for m in iop.request.metrics_of_interest)
