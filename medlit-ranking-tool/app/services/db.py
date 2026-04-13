"""Lightweight SQLite persistence for papers, extractions, and normalizations.

Uses SQLAlchemy Core (not ORM) for simplicity.  All Pydantic objects are
serialized to JSON text columns.  This avoids mapping every nested field
to relational columns — good enough for MVP.

Tables are auto-created on first access via `ensure_tables()`.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from loguru import logger

from app.core.config import settings
from app.models.extraction import ExtractionResult
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper

metadata = sa.MetaData()

papers_table = sa.Table(
    "papers",
    metadata,
    sa.Column("pmid", sa.String, primary_key=True),
    sa.Column("data_json", sa.Text, nullable=False),
)

extractions_table = sa.Table(
    "extractions",
    metadata,
    sa.Column("pmid", sa.String, primary_key=True),
    sa.Column("data_json", sa.Text, nullable=False),
)

normalizations_table = sa.Table(
    "normalizations",
    metadata,
    sa.Column("pmid", sa.String, primary_key=True),
    sa.Column("data_json", sa.Text, nullable=False),
)

evidence_records_table = sa.Table(
    "evidence_records",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("identifier", sa.Text, nullable=False, unique=True),
    sa.Column("source_type", sa.Text, nullable=False),
    sa.Column("data_json", sa.Text, nullable=False),
    sa.Column("fetched_at", sa.DateTime, nullable=False),
)

correlation_cache_table = sa.Table(
    "correlation_cache",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("seed_id", sa.Text, nullable=False),
    sa.Column("candidate_id", sa.Text, nullable=False),
    sa.Column("scores_json", sa.Text, nullable=False),
    sa.Column("computed_at", sa.DateTime, nullable=False),
    sa.UniqueConstraint("seed_id", "candidate_id", name="uq_seed_candidate"),
)

_engine: sa.Engine | None = None


def _get_engine() -> sa.Engine:
    global _engine
    if _engine is None:
        db_url = settings.DATABASE_URL
        # Ensure parent directory exists for file-based DBs
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            if db_path.startswith("./"):
                db_path = db_path[2:]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _engine = sa.create_engine(db_url, echo=False)
    return _engine


def ensure_tables() -> None:
    """Create tables if they don't exist."""
    engine = _get_engine()
    metadata.create_all(engine)
    logger.debug("DB tables ensured at {}", settings.DATABASE_URL)


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------

def save_paper(paper: Paper) -> None:
    key = paper.uid
    if not key:
        return
    ensure_tables()
    engine = _get_engine()
    data = paper.model_dump_json()
    with engine.begin() as conn:
        existing = conn.execute(
            sa.select(papers_table.c.pmid).where(papers_table.c.pmid == key)
        ).first()
        if existing:
            conn.execute(
                papers_table.update()
                .where(papers_table.c.pmid == key)
                .values(data_json=data)
            )
        else:
            conn.execute(papers_table.insert().values(pmid=key, data_json=data))


def load_paper(pmid: str) -> Paper | None:
    ensure_tables()
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(papers_table.c.data_json).where(papers_table.c.pmid == pmid)
        ).first()
    if row is None:
        return None
    return Paper.model_validate_json(row[0])


def save_papers(papers: list[Paper]) -> None:
    for p in papers:
        save_paper(p)


# ---------------------------------------------------------------------------
# Extractions
# ---------------------------------------------------------------------------

def save_extraction(pmid: str, extraction: ExtractionResult) -> None:
    ensure_tables()
    engine = _get_engine()
    data = extraction.model_dump_json()
    with engine.begin() as conn:
        existing = conn.execute(
            sa.select(extractions_table.c.pmid).where(extractions_table.c.pmid == pmid)
        ).first()
        if existing:
            conn.execute(
                extractions_table.update()
                .where(extractions_table.c.pmid == pmid)
                .values(data_json=data)
            )
        else:
            conn.execute(extractions_table.insert().values(pmid=pmid, data_json=data))


def load_extraction(pmid: str) -> ExtractionResult | None:
    ensure_tables()
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(extractions_table.c.data_json).where(extractions_table.c.pmid == pmid)
        ).first()
    if row is None:
        return None
    return ExtractionResult.model_validate_json(row[0])


# ---------------------------------------------------------------------------
# Normalizations
# ---------------------------------------------------------------------------

def save_normalization(pmid: str, normalized: NormalizedProduct) -> None:
    ensure_tables()
    engine = _get_engine()
    data = normalized.model_dump_json()
    with engine.begin() as conn:
        existing = conn.execute(
            sa.select(normalizations_table.c.pmid).where(normalizations_table.c.pmid == pmid)
        ).first()
        if existing:
            conn.execute(
                normalizations_table.update()
                .where(normalizations_table.c.pmid == pmid)
                .values(data_json=data)
            )
        else:
            conn.execute(normalizations_table.insert().values(pmid=pmid, data_json=data))


def load_normalization(pmid: str) -> NormalizedProduct | None:
    ensure_tables()
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(normalizations_table.c.data_json).where(normalizations_table.c.pmid == pmid)
        ).first()
    if row is None:
        return None
    return NormalizedProduct.model_validate_json(row[0])


# ---------------------------------------------------------------------------
# Evidence records (correlated-evidence retrieval cache)
# ---------------------------------------------------------------------------

def save_evidence_record(record: Any) -> None:
    """Persist an EvidenceRecord to the DB (upsert by identifier)."""
    ensure_tables()
    engine = _get_engine()
    data = record.model_dump_json() if hasattr(record, "model_dump_json") else json.dumps(record)
    now = datetime.now(tz=timezone.utc)
    with engine.begin() as conn:
        existing = conn.execute(
            sa.select(evidence_records_table.c.id).where(
                evidence_records_table.c.identifier == record.identifier
            )
        ).first()
        if existing:
            conn.execute(
                evidence_records_table.update()
                .where(evidence_records_table.c.identifier == record.identifier)
                .values(data_json=data, fetched_at=now)
            )
        else:
            conn.execute(
                evidence_records_table.insert().values(
                    identifier=record.identifier,
                    source_type=str(record.source_type),
                    data_json=data,
                    fetched_at=now,
                )
            )


def load_evidence_record(identifier: str) -> Any | None:
    """Load an EvidenceRecord from DB by identifier, or None if absent."""
    from app.retrieval.models import EvidenceRecord  # local import to avoid cycles

    ensure_tables()
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(evidence_records_table.c.data_json).where(
                evidence_records_table.c.identifier == identifier
            )
        ).first()
    if row is None:
        return None
    return EvidenceRecord.model_validate_json(row[0])


# ---------------------------------------------------------------------------
# Correlation cache
# ---------------------------------------------------------------------------

def save_correlation(seed_id: str, cand_id: str, scores: dict[str, Any]) -> None:
    """Persist correlation scores for a seed/candidate pair (upsert)."""
    ensure_tables()
    engine = _get_engine()
    scores_json = json.dumps(scores)
    now = datetime.now(tz=timezone.utc)
    with engine.begin() as conn:
        existing = conn.execute(
            sa.select(correlation_cache_table.c.id).where(
                (correlation_cache_table.c.seed_id == seed_id)
                & (correlation_cache_table.c.candidate_id == cand_id)
            )
        ).first()
        if existing:
            conn.execute(
                correlation_cache_table.update()
                .where(
                    (correlation_cache_table.c.seed_id == seed_id)
                    & (correlation_cache_table.c.candidate_id == cand_id)
                )
                .values(scores_json=scores_json, computed_at=now)
            )
        else:
            conn.execute(
                correlation_cache_table.insert().values(
                    seed_id=seed_id,
                    candidate_id=cand_id,
                    scores_json=scores_json,
                    computed_at=now,
                )
            )


def load_correlation(seed_id: str, cand_id: str) -> dict[str, Any] | None:
    """Load cached correlation scores for a seed/candidate pair, or None."""
    ensure_tables()
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            sa.select(correlation_cache_table.c.scores_json).where(
                (correlation_cache_table.c.seed_id == seed_id)
                & (correlation_cache_table.c.candidate_id == cand_id)
            )
        ).first()
    if row is None:
        return None
    return json.loads(row[0])
