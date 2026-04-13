"""Candidate fusion: deduplicate and merge evidence records by identifier."""

from __future__ import annotations

import re
from typing import Any

from app.retrieval.models import EvidenceRecord


_STRIP_PREFIX_RE = re.compile(r"^[A-Z0-9_]+:", re.IGNORECASE)
_NORMALIZE_RE = re.compile(r"[^a-z0-9]")


def _canonical(identifier: str) -> str:
    """Strip common prefixes and normalise to lowercase alphanumerics."""
    s = _STRIP_PREFIX_RE.sub("", identifier)
    return _NORMALIZE_RE.sub("", s.lower())


def _merge_two(primary: EvidenceRecord, secondary: EvidenceRecord) -> EvidenceRecord:
    """Merge *secondary* into *primary*, preferring non-None primary fields."""
    merged_indication = list({i for i in primary.indication + secondary.indication})
    merged_endpoints = list({e for e in primary.endpoints + secondary.endpoints})

    # Merge raw_payloads: store both under list if different
    raw: dict[str, Any] = {}
    if primary.raw_payload:
        raw.update(primary.raw_payload)
    if secondary.raw_payload:
        for k, v in secondary.raw_payload.items():
            if k not in raw:
                raw[k] = v

    return EvidenceRecord(
        identifier=primary.identifier,
        source_type=primary.source_type,
        source_name=primary.source_name,
        url=primary.url or secondary.url,
        title=primary.title or secondary.title,
        product_name=primary.product_name or secondary.product_name,
        manufacturer=primary.manufacturer or secondary.manufacturer,
        indication=merged_indication,
        route=primary.route or secondary.route,
        endpoints=merged_endpoints,
        raw_payload=raw or None,
    )


def fuse_candidates(candidates: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Deduplicate candidates by canonical identifier, merging fields.

    Records sharing a canonical identifier (e.g. ``PMID:12345`` and
    ``pmid:12345``) are merged: non-None primary values are preferred, lists
    are unioned, and raw_payload keys are merged.
    """
    groups: dict[str, list[EvidenceRecord]] = {}
    order: list[str] = []

    for rec in candidates:
        key = _canonical(rec.identifier)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(rec)

    fused: list[EvidenceRecord] = []
    for key in order:
        group = groups[key]
        merged = group[0]
        for other in group[1:]:
            merged = _merge_two(merged, other)
        fused.append(merged)

    return fused
