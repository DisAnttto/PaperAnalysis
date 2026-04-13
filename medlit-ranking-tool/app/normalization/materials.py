"""Ophthalmology material normalization registry.

Two alias tables are intentionally kept separate:

- ``MATERIAL_DIRECT_ALIASES``: direct material descriptions (confidence 0.95).
  The text explicitly names the material, so the match is high-confidence.

- ``MATERIAL_BRAND_HINTS``: IOL/device brand/trade names that *imply* a
  material but do not state it (confidence 0.60).  Only used as a fallback
  when no direct material description is found.

Lookup order:
  1. Exact match in MATERIAL_DIRECT_ALIASES (after case-folding).
  2. Substring scan in MATERIAL_DIRECT_ALIASES.
  3. If still no match: exact/substring scan in MATERIAL_BRAND_HINTS.
  4. In all cases: scan MATERIAL_FEATURE_KEYWORDS for feature tags.
"""

from __future__ import annotations

from app.normalization.registry import NormalizationMethod, NormResult

# ---------------------------------------------------------------------------
# (subtype, family) tuples used as dict values
# ---------------------------------------------------------------------------

# Direct material descriptions — high confidence (0.95)
# Keys are lowercase; matching is case-insensitive.
MATERIAL_DIRECT_ALIASES: dict[str, tuple[str, str]] = {
    # Acrylic family
    "hydrophobic acrylic": ("hydrophobic_acrylic", "acrylic"),
    "hydrophobic acrylate": ("hydrophobic_acrylic", "acrylic"),
    "hydrophobic acrylic iol": ("hydrophobic_acrylic", "acrylic"),
    "hydrophilic acrylic": ("hydrophilic_acrylic", "acrylic"),
    "hydrophilic acrylate": ("hydrophilic_acrylic", "acrylic"),
    "hydrophilic acrylic iol": ("hydrophilic_acrylic", "acrylic"),
    "acrylic": ("acrylic", "acrylic"),
    "acrylate": ("acrylic", "acrylic"),
    "acrylic iol": ("acrylic", "acrylic"),
    # Silicone family
    "silicone": ("silicone", "silicone"),
    "silicone iol": ("silicone", "silicone"),
    "silicone lens": ("silicone", "silicone"),
    # Collamer — only the material name itself is a direct alias
    "collamer": ("collamer", "collamer"),
    "icl material": ("collamer", "collamer"),
    # PMMA
    "pmma": ("pmma", "pmma"),
    "polymethylmethacrylate": ("pmma", "pmma"),
    "poly(methyl methacrylate)": ("pmma", "pmma"),
    "polymethyl methacrylate": ("pmma", "pmma"),
    "rigid lens": ("pmma", "pmma"),
    # Hydrogel
    "hydrogel": ("hydrogel", "hydrogel"),
    "poly-hema": ("hydrogel", "hydrogel"),
    "phema": ("hydrogel", "hydrogel"),
    "polyhydroxyethyl methacrylate": ("hydrogel", "hydrogel"),
    # Generic polymer when explicitly described as such
    "ophthalmic polymer": ("polymer_unknown", "polymer_unknown"),
    "foldable polymer": ("polymer_unknown", "polymer_unknown"),
    "copolymer iol": ("polymer_unknown", "polymer_unknown"),
}

# Brand / trade name hints — lower confidence (0.60).
# Brand names *suggest* material composition but do not state it explicitly.
MATERIAL_BRAND_HINTS: dict[str, tuple[str, str]] = {
    # Alcon IOLs → hydrophobic acrylic
    "acrysof": ("hydrophobic_acrylic", "acrylic"),
    "clareon": ("hydrophobic_acrylic", "acrylic"),
    "alcon acrysof": ("hydrophobic_acrylic", "acrylic"),
    # J&J / AMO IOLs → hydrophobic acrylic
    "tecnis": ("hydrophobic_acrylic", "acrylic"),
    "synergy": ("hydrophobic_acrylic", "acrylic"),
    "symfony": ("hydrophobic_acrylic", "acrylic"),
    # B+L IOLs → hydrophobic acrylic
    "envista": ("hydrophobic_acrylic", "acrylic"),
    "akreos": ("hydrophilic_acrylic", "acrylic"),
    # Carl Zeiss IOLs → hydrophilic acrylic
    "ct asphina": ("hydrophilic_acrylic", "acrylic"),
    "at torbi": ("hydrophilic_acrylic", "acrylic"),
    # Physiol IOLs → hydrophilic acrylic
    "finevision": ("hydrophilic_acrylic", "acrylic"),
    "precizon": ("hydrophilic_acrylic", "acrylic"),
    # STAAR ICL → collamer
    "staar icl": ("collamer", "collamer"),
    "evo icl": ("collamer", "collamer"),
    "visian": ("collamer", "collamer"),
    # Older / rigid IOLs → PMMA
    "pmma iol": ("pmma", "pmma"),
}

# Feature keywords — always scanned regardless of family match.
# Keys are lowercase substrings; values are canonical feature tag strings.
MATERIAL_FEATURE_KEYWORDS: dict[str, str] = {
    "uv filter": "uv_filter",
    "uv-filter": "uv_filter",
    "uv blocking": "uv_filter",
    "blue light filter": "blue_light_filter",
    "blue-light filter": "blue_light_filter",
    "blue filter": "blue_light_filter",
    "heparin": "heparin_surface",
    "heparin surface": "heparin_surface",
    "drug eluting": "drug_eluting",
    "drug-eluting": "drug_eluting",
    "sustained release": "drug_eluting",
    "preservative free": "preservative_free",
    "preservative-free": "preservative_free",
    "pfree": "preservative_free",
    "biodegradable": "biodegradable",
    "bioresorbable": "biodegradable",
    "foldable": "foldable",
    "foldable iol": "foldable",
    "aspheric": "aspheric",
    "aberration free": "aspheric",
    "toric": "toric",
    "toric iol": "toric",
    "multifocal": "multifocal",
    "diffractive multifocal": "multifocal",
    "trifocal": "multifocal",
    "monofocal": "monofocal",
    "single focus": "monofocal",
    "edof": "edof",
    "extended depth of focus": "edof",
    "extended range of vision": "edof",
}

_DIRECT_CONFIDENCE: float = 0.95
_BRAND_CONFIDENCE: float = 0.60
_UNKNOWN_CONFIDENCE: float = 0.0


def _scan_aliases(
    text: str,
    table: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    """Case-insensitive exact then substring scan against an alias table.

    Longer keys are tried first to prevent short substrings (e.g. "acrylate")
    from matching before longer, more specific ones (e.g. "polymethylmethacrylate").
    """
    folded = text.lower()
    if folded in table:
        return table[folded]
    for key in sorted(table, key=len, reverse=True):
        if key in folded:
            return table[key]
    return None


def _detect_features(text: str) -> list[str]:
    folded = text.lower()
    seen: set[str] = set()
    features: list[str] = []
    for key, tag in MATERIAL_FEATURE_KEYWORDS.items():
        if key in folded and tag not in seen:
            features.append(tag)
            seen.add(tag)
    return features


def normalize_material(raw: str) -> "NormalizedMaterialResult":
    """Normalize a raw material string into canonical family/subtype/features.

    Returns a plain namespace object (not a Pydantic model — avoids circular
    import with ``app.models.normalized``).  The caller (``normalized.py``)
    converts this into the full ``NormalizedMaterial`` Pydantic model.
    """
    features = _detect_features(raw)

    match = _scan_aliases(raw, MATERIAL_DIRECT_ALIASES)
    if match:
        subtype, family = match
        return NormalizedMaterialResult(
            raw=raw,
            family=family,
            subtype=subtype,
            features=features,
            confidence=_DIRECT_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )

    match = _scan_aliases(raw, MATERIAL_BRAND_HINTS)
    if match:
        subtype, family = match
        return NormalizedMaterialResult(
            raw=raw,
            family=family,
            subtype=subtype,
            features=features,
            confidence=_BRAND_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )

    return NormalizedMaterialResult(
        raw=raw,
        family=None,
        subtype=None,
        features=features,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )


class NormalizedMaterialResult:
    """Plain dataclass-like result returned by normalize_material().

    Kept in this module to avoid circular imports with app.models.normalized.
    """

    __slots__ = ("raw", "family", "subtype", "features", "confidence", "method")

    def __init__(
        self,
        raw: str,
        family: str | None,
        subtype: str | None,
        features: list[str],
        confidence: float,
        method: NormalizationMethod,
    ) -> None:
        self.raw = raw
        self.family = family
        self.subtype = subtype
        self.features = features
        self.confidence = confidence
        self.method = method
