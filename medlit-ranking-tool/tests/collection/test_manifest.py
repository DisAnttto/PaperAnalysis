"""Offline validation of tests/collection/cases.json (no PubMed / LLM)."""

from tests.collection import load_collection


def test_collection_version():
    coll = load_collection()
    assert coll.version == 1


def test_collection_has_faricimab_case():
    coll = load_collection()
    ids = {c.id for c in coll.cases}
    assert "faricimab_namd_39350227" in ids


def test_collection_has_nine_paper_gold_cases():
    coll = load_collection()
    ids = {c.id for c in coll.cases}
    assert len(coll.cases) >= 10
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
    }
    assert expected <= ids


def test_every_case_validates():
    coll = load_collection()
    assert len(coll.cases) >= 1
    for c in coll.cases:
        assert c.id
        assert c.request.query
