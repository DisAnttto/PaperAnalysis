"""Human-readable one-line labels for normalized product rows in the UI.

``format_product_table_label`` must reflect *everything* the scorer can match on,
not only product name / ingredient.  A paper can score highly on route or class
while the LLM omits a clean ingredient string — the table label must still
show route, class, etc. so users understand the P score.
"""

from app.models.normalized import NormalizedDevice, NormalizedDrug, NormalizedProduct


def _dedupe_preserve(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        k = p.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(p.strip())
    return out


def _device_chunk(device: NormalizedDevice) -> str | None:
    bits: list[str] = []
    if device.product_name_raw:
        bits.append(device.product_name_raw.strip())
    if device.device_category_normalized:
        bits.append(device.device_category_normalized)
    elif device.device_category_raw:
        bits.append(device.device_category_raw.strip())
    if device.manufacturer_raw:
        bits.append(device.manufacturer_raw.strip())
    if device.material and device.material.subtype:
        bits.append(device.material.subtype)
    if device.anatomical_site_normalized:
        bits.append(device.anatomical_site_normalized)
    bits = _dedupe_preserve(bits)
    return " · ".join(bits) if bits else None


def _drug_chunk(drug: NormalizedDrug) -> str | None:
    bits: list[str] = []
    ing = drug.active_ingredient_normalized or (drug.active_ingredient_raw or "").strip()
    if ing:
        bits.append(ing)
    if drug.product_name_raw:
        pn = drug.product_name_raw.strip()
        if not ing or pn.lower() not in ing.lower():
            bits.append(pn)
    if drug.drug_class_normalized:
        bits.append(drug.drug_class_normalized)
    if drug.route_normalized:
        bits.append(drug.route_normalized)
    if drug.formulation_features_normalized:
        bits.extend(drug.formulation_features_normalized[:3])
    bits = _dedupe_preserve(bits)
    return " · ".join(bits) if bits else None


def format_product_table_label(normalized: NormalizedProduct) -> str | None:
    """Single-line description of extracted product(s) for results-table cells."""
    if normalized.product_type == "unknown":
        return None

    chunks: list[str] = []
    if normalized.device:
        c = _device_chunk(normalized.device)
        if c:
            chunks.append(c)
    if normalized.drug:
        c = _drug_chunk(normalized.drug)
        if c:
            chunks.append(c)

    if not chunks:
        return None
    return " · ".join(chunks)
