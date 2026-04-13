"""Product Similarity scoring (ranking_spec §2.2).

Compares the normalized ophthalmology product extracted from a paper
against the user-supplied target product profile.

Key design decisions:
- Scores are computed on *normalized* canonical values, never on raw strings.
- ``target_type`` on ``TargetProductProfile`` controls which sub-signals are
  active: only device signals fire for ``target_type="device"``, only drug
  signals for ``target_type="drug"``, both for ``target_type="both"``.
- Only sub-signals where both target and extracted values are non-null
  participate; absent signals are excluded and weights renormalized.
- Normalization never happens here; callers pass a precomputed
  ``NormalizedProduct``.
- String comparisons use a two-tier scheme: exact match = 1.0, one string
  contained within the other = 0.6, else 0.0.  This handles minor
  normalization variants (e.g. "iol" vs "intraocular_lens").
"""

from app.models.normalized import NormalizedDevice, NormalizedDrug, NormalizedMaterial, NormalizedProduct
from app.models.search import TargetProductProfile

# ---------------------------------------------------------------------------
# Default sub-signal weights (relative; only active signals renormalize to 1.0)
# ---------------------------------------------------------------------------

_DEFAULT_DEVICE_WEIGHTS: dict[str, float] = {
    "intended_use": 0.15,
    "device_category": 0.15,
    "material_subtype": 0.12,
    "indications": 0.12,
    "energy_source": 0.05,
    "anatomical_site": 0.08,
    "device_class": 0.03,
    "product_name": 0.10,
    "key_features": 0.05,
    "manufacturer": 0.05,
    "sterilization": 0.03,
    "material_features": 0.05,
}

_DEFAULT_DRUG_WEIGHTS: dict[str, float] = {
    "drug_ingredient": 0.30,
    "drug_class": 0.15,
    "drug_route": 0.10,
    "drug_formulation_features": 0.05,
    "drug_product_name": 0.05,
}

# Fallback for when target_type="both" and product has both device + drug
_BOTH_DEVICE_SHARE: float = 0.55
_BOTH_DRUG_SHARE: float = 0.45


# ---------------------------------------------------------------------------
# Pure comparison helpers (public for testing)
# ---------------------------------------------------------------------------

def _soft_string_match(a: str, b: str) -> float:
    """Two-tier string comparison.

    Returns 1.0 for an exact case-insensitive match, 0.6 when one string
    contains the other (handles normalization variants like "iol" vs
    "intraocular_lens"), and 0.0 otherwise.
    """
    al, bl = a.lower().strip(), b.lower().strip()
    if al == bl:
        return 1.0
    if al in bl or bl in al:
        return 0.6
    return 0.0


def score_material_similarity(
    mat: NormalizedMaterial,
    target_family: str | None,
    target_subtype: str | None,
) -> float:
    """Return material similarity ∈ [0, 1].

    - Exact subtype match → 1.0
    - Same family but different subtype → 0.5
    - Different family or unknown → 0.0
    """
    if mat.subtype and target_subtype:
        if mat.subtype == target_subtype:
            return 1.0
        if mat.family and target_family and mat.family == target_family:
            return 0.5
        return 0.0
    if mat.family and target_family:
        return 0.5 if mat.family == target_family else 0.0
    return 0.0


def score_drug_similarity(
    drug: NormalizedDrug,
    target_ingredient: str | None,
    target_class: str | None,
) -> tuple[float, float]:
    """Return (ingredient_score, class_score) each ∈ [0, 1].

    Uses soft string matching so minor normalization variants still score.
    """
    ingredient_score = 0.0
    if target_ingredient and drug.active_ingredient_normalized:
        ingredient_score = _soft_string_match(
            drug.active_ingredient_normalized, target_ingredient
        )

    class_score = 0.0
    if target_class and drug.drug_class_normalized:
        class_score = _soft_string_match(drug.drug_class_normalized, target_class)

    return ingredient_score, class_score


def score_feature_overlap(
    extracted_features: list[str],
    target_features: list[str],
) -> float:
    """Jaccard similarity over two feature tag sets ∈ [0, 1]."""
    a = {f.lower() for f in extracted_features}
    b = {f.lower() for f in target_features}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def score_indication_similarity(
    extracted: list[str],
    target: list[str],
) -> float:
    """Jaccard similarity over canonical indication sets ∈ [0, 1]."""
    a = {s.lower() for s in extracted}
    b = {s.lower() for s in target}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _normalised_levenshtein(a: str, b: str) -> float:
    a_lower, b_lower = a.lower(), b.lower()
    if a_lower == b_lower:
        return 1.0
    la, lb = len(a_lower), len(b_lower)
    if la == 0 or lb == 0:
        return 0.0
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a_lower[i - 1] == b_lower[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return 1.0 - prev[lb] / max(la, lb)


# ---------------------------------------------------------------------------
# Device sub-signals
# ---------------------------------------------------------------------------

def _score_device_signals(
    device: NormalizedDevice,
    target: TargetProductProfile,
    weights: dict[str, float],
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute device sub-signal scores and active weights.

    Returns (signals, active_weights).
    """
    signals: dict[str, float] = {}
    active: dict[str, float] = {}

    if target.intended_use and device.intended_use_normalized:
        signals["intended_use"] = _soft_string_match(
            device.intended_use_normalized, target.intended_use
        )
        active["intended_use"] = weights["intended_use"]

    if target.device_category and device.device_category_normalized:
        signals["device_category"] = _soft_string_match(
            device.device_category_normalized, target.device_category
        )
        active["device_category"] = weights["device_category"]

    t_subtype = target.material_subtype
    t_family = target.material_family
    if (t_subtype or t_family) and device.material:
        signals["material_subtype"] = score_material_similarity(
            device.material, t_family, t_subtype
        )
        active["material_subtype"] = weights["material_subtype"]

    if target.material_features and device.material and device.material.features:
        signals["material_features"] = score_feature_overlap(
            device.material.features, target.material_features
        )
        active["material_features"] = weights["material_features"]

    t_inds = target.indications
    if t_inds and device.indications_normalized:
        signals["indications"] = score_indication_similarity(
            device.indications_normalized, t_inds
        )
        active["indications"] = weights["indications"]

    if target.anatomical_site and device.anatomical_site_normalized:
        signals["anatomical_site"] = _soft_string_match(
            device.anatomical_site_normalized, target.anatomical_site
        )
        active["anatomical_site"] = weights["anatomical_site"]

    if target.energy_source and device.energy_source_normalized:
        signals["energy_source"] = _soft_string_match(
            device.energy_source_normalized, target.energy_source
        )
        active["energy_source"] = weights["energy_source"]

    if target.product_name and device.product_name_raw:
        signals["product_name"] = _normalised_levenshtein(
            target.product_name, device.product_name_raw
        )
        active["product_name"] = weights["product_name"]

    if target.key_features and device.key_features_normalized:
        signals["key_features"] = score_feature_overlap(
            device.key_features_normalized, target.key_features
        )
        active["key_features"] = weights["key_features"]

    if target.manufacturer and device.manufacturer_raw:
        signals["manufacturer"] = _soft_string_match(
            device.manufacturer_raw, target.manufacturer
        )
        active["manufacturer"] = weights["manufacturer"]

    if target.device_class and device.device_class:
        signals["device_class"] = (
            1.0 if device.device_class == target.device_class else 0.0
        )
        active["device_class"] = weights["device_class"]

    if target.sterilization_method and device.sterilization_normalized:
        signals["sterilization"] = _soft_string_match(
            device.sterilization_normalized, target.sterilization_method
        )
        active["sterilization"] = weights["sterilization"]

    return signals, active


# ---------------------------------------------------------------------------
# Drug sub-signals
# ---------------------------------------------------------------------------

def _score_drug_signals(
    drug: NormalizedDrug,
    target: TargetProductProfile,
    weights: dict[str, float],
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute drug sub-signal scores and active weights.

    Note: drug_indications is intentionally omitted because the NormalizedDrug
    model does not carry indications — including it with a hardcoded 0 would
    drag down every drug P score unfairly.  Indication overlap is scored via
    the device path when extraction produces a device component.
    """
    signals: dict[str, float] = {}
    active: dict[str, float] = {}

    if target.active_ingredient and drug.active_ingredient_normalized is not None:
        ing_score, _ = score_drug_similarity(drug, target.active_ingredient, None)
        signals["drug_ingredient"] = ing_score
        active["drug_ingredient"] = weights["drug_ingredient"]

    if target.drug_class and drug.drug_class_normalized is not None:
        _, cls_score = score_drug_similarity(drug, None, target.drug_class)
        signals["drug_class"] = cls_score
        active["drug_class"] = weights["drug_class"]

    if target.route and drug.route_normalized is not None:
        signals["drug_route"] = _soft_string_match(
            drug.route_normalized, target.route
        )
        active["drug_route"] = weights["drug_route"]

    if target.material_features and drug.formulation_features_normalized:
        signals["drug_formulation_features"] = score_feature_overlap(
            drug.formulation_features_normalized, target.material_features
        )
        active["drug_formulation_features"] = weights["drug_formulation_features"]

    if target.product_name and drug.product_name_raw:
        signals["drug_product_name"] = _normalised_levenshtein(
            target.product_name, drug.product_name_raw
        )
        active["drug_product_name"] = weights["drug_product_name"]

    return signals, active


# ---------------------------------------------------------------------------
# Top-level scorer
# ---------------------------------------------------------------------------

def score_product_similarity(
    normalized: NormalizedProduct,
    target: TargetProductProfile,
    *,
    device_sub_weights: dict[str, float] | None = None,
    drug_sub_weights: dict[str, float] | None = None,
) -> tuple[float, dict]:
    """Compute the product similarity score P ∈ [0, 1].

    Returns (score, breakdown) where breakdown includes each sub-signal value,
    effective weights used, and the product_type activated.

    Only sub-signals relevant to ``target.target_type`` are considered.
    Sub-signals missing normalized values from either side are excluded and
    their weights redistributed.
    """
    dev_w = {**_DEFAULT_DEVICE_WEIGHTS, **(device_sub_weights or {})}
    drug_w = {**_DEFAULT_DRUG_WEIGHTS, **(drug_sub_weights or {})}

    target_type = target.target_type
    all_signals: dict[str, float] = {}
    all_active: dict[str, float] = {}

    if target_type in ("device", "both") and normalized.device is not None:
        dev_signals, dev_active = _score_device_signals(
            normalized.device, target, dev_w
        )
        if target_type == "both":
            dev_active = {k: v * _BOTH_DEVICE_SHARE for k, v in dev_active.items()}
        all_signals.update(dev_signals)
        all_active.update(dev_active)

    if target_type in ("drug", "both") and normalized.drug is not None:
        drug_signals, drug_active = _score_drug_signals(
            normalized.drug, target, drug_w
        )
        if target_type == "both":
            drug_active = {k: v * _BOTH_DRUG_SHARE for k, v in drug_active.items()}
        all_signals.update(drug_signals)
        all_active.update(drug_active)

    total_weight = sum(all_active.values())
    if total_weight == 0:
        return 0.0, {
            "signals": all_signals,
            "weights": {},
            "product_type_activated": target_type,
            "note": "no overlapping non-null fields between target and normalized extraction",
        }

    normalised_weights = {k: v / total_weight for k, v in all_active.items()}
    score = sum(all_signals[k] * normalised_weights[k] for k in all_signals)
    score = max(0.0, min(1.0, score))

    return score, {
        "signals": all_signals,
        "weights": normalised_weights,
        "product_type_activated": target_type,
    }
