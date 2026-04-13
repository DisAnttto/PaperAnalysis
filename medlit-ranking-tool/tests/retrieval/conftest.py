"""Shared fixtures for retrieval tests."""

from __future__ import annotations

import pytest

from app.retrieval.enums import RelationLabel, SourceType, TierLevel
from app.retrieval.models import (
    EvidenceRecord,
    ExtractedTargetProfile,
    SeedRecord,
)


@pytest.fixture()
def sample_seed() -> SeedRecord:
    return SeedRecord(
        source_type=SourceType.pubmed_paper,
        source_name="PubMed",
        identifier="PMID:39350227",
        url="https://pubmed.ncbi.nlm.nih.gov/39350227/",
        title="Intravitreal faricimab for treatment naive patients with nAMD",
    )


@pytest.fixture()
def sample_profile() -> ExtractedTargetProfile:
    return ExtractedTargetProfile(
        product_type="drug",
        submission_mode="BLA",
        product_name="VABYSMO (faricimab-svoa)",
        active_ingredient="faricimab-svoa",
        route="intravitreal",
        indication=["nAMD", "DME"],
        key_metrics_or_endpoints=["BCVA", "OCT thickness", "dosing interval durability"],
    )


@pytest.fixture()
def sample_evidence() -> EvidenceRecord:
    return EvidenceRecord(
        identifier="BLA:761235 SumR",
        source_type=SourceType.fda_review,
        source_name="FDA",
        url="https://www.accessdata.fda.gov/drugsatfda_docs/nda/2022/761235Orig1s000SumR.pdf",
        title="FDA Summary Review for BLA 761235",
        product_name="VABYSMO (faricimab-svoa)",
        indication=["nAMD", "DME"],
        route="intravitreal",
        endpoints=["BCVA", "OCT thickness"],
    )
