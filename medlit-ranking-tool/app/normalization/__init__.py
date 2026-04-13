"""Ophthalmology normalization pipeline.

Public API:
    ``normalize_extraction(extracted)`` — single entry point that converts a
    raw ``ExtractionResult`` into a ``NormalizedProduct``.  Call this **once**
    after extraction; pass the result directly to the scorer.
"""

from app.normalization.registry import NormalizationMethod
from app.normalization.anatomy import normalize_anatomical_site, normalize_indications
from app.normalization.devices import (
    normalize_device_category,
    normalize_energy_source,
    normalize_intended_use,
    normalize_sterilization,
)
from app.normalization.drugs import normalize_drug
from app.normalization.materials import normalize_material

__all__ = ["normalize_extraction"]


def _normalize_device(extracted_device):  # -> NormalizedDevice
    from app.models.extraction import DeviceClass, DeviceExtraction
    from app.models.normalized import NormalizedDevice, NormalizedMaterial

    d: DeviceExtraction = extracted_device

    category_raw = d.device_category.value if d.device_category else None
    cat_result = normalize_device_category(category_raw) if category_raw else None

    site_raw = d.anatomical_site.value if d.anatomical_site else None
    site_result = normalize_anatomical_site(site_raw) if site_raw else None

    indications_raw_list = (
        d.indications.value if d.indications else []
    )
    ind_result = (
        normalize_indications(indications_raw_list) if indications_raw_list else None
    )

    material_raw = d.material.value if d.material else None
    norm_mat: NormalizedMaterial | None = None
    if material_raw:
        mr = normalize_material(material_raw)
        norm_mat = NormalizedMaterial(
            raw=mr.raw,
            family=mr.family,
            subtype=mr.subtype,
            features=mr.features,
            confidence=mr.confidence,
            method=mr.method,
        )

    key_features_raw = d.key_features.value if d.key_features else []
    key_features_norm = [f.lower().replace(" ", "_") for f in key_features_raw]

    intended_use_raw = d.intended_use.value if d.intended_use else None
    intended_use_norm_result = (
        normalize_intended_use(intended_use_raw) if intended_use_raw else None
    )

    device_class_val = None
    if d.device_class is not None and d.device_class != DeviceClass.UNKNOWN:
        device_class_val = d.device_class.value

    energy_raw = d.energy_source.value if d.energy_source else None
    energy_norm = normalize_energy_source(energy_raw) if energy_raw else None

    steril_raw = (
        d.sterilization_method.value if d.sterilization_method else None
    )
    steril_norm = normalize_sterilization(steril_raw) if steril_raw else None

    device_confidence = (
        (cat_result.confidence if cat_result and cat_result.canonical else 0.0)
    )

    return NormalizedDevice(
        product_name_raw=d.product_name.value if d.product_name else None,
        device_category_raw=category_raw,
        device_category_normalized=cat_result.canonical if cat_result else None,
        manufacturer_raw=d.manufacturer.value if d.manufacturer else None,
        intended_use_raw=intended_use_raw,
        intended_use_normalized=(
            intended_use_norm_result.canonical if intended_use_norm_result else None
        ),
        indications_raw=indications_raw_list,
        indications_normalized=ind_result.canonical if ind_result else [],
        anatomical_site_raw=site_raw,
        anatomical_site_normalized=site_result.canonical if site_result else None,
        material=norm_mat,
        key_features_raw=key_features_raw,
        key_features_normalized=key_features_norm,
        device_class=device_class_val,
        energy_source_normalized=energy_norm.canonical if energy_norm else None,
        sterilization_normalized=steril_norm.canonical if steril_norm else None,
        confidence=device_confidence,
        method=NormalizationMethod.DICTIONARY,
    )


def _normalize_drug(extracted_drug):  # -> NormalizedDrug
    from app.models.extraction import DrugExtraction
    from app.models.normalized import NormalizedDrug

    dr: DrugExtraction = extracted_drug

    ingredient_raw = dr.active_ingredient.value if dr.active_ingredient else None
    product_name_raw = dr.product_name.value if dr.product_name else None
    route_raw = dr.route.value if dr.route else None
    formulation_raw = dr.formulation_features.value if dr.formulation_features else []

    lookup_text = ingredient_raw or product_name_raw or ""
    context = (dr.drug_class.value if dr.drug_class else "") + " " + (route_raw or "")

    norm = normalize_drug(lookup_text, context.strip() or None)

    route_normalized = norm.route_normalized
    if not route_normalized and route_raw:
        from app.normalization.drugs import ROUTE_KEYWORDS
        for key, val in ROUTE_KEYWORDS.items():
            if key in route_raw.lower():
                route_normalized = val
                break

    formulation_features_norm = list(norm.formulation_features_normalized)
    if formulation_raw:
        from app.normalization.drugs import FORMULATION_FEATURE_KEYWORDS
        for feat in formulation_raw:
            for key, tag in FORMULATION_FEATURE_KEYWORDS.items():
                if key in feat.lower() and tag not in formulation_features_norm:
                    formulation_features_norm.append(tag)

    return NormalizedDrug(
        product_name_raw=product_name_raw,
        active_ingredient_raw=ingredient_raw,
        active_ingredient_normalized=norm.active_ingredient_normalized,
        drug_class_normalized=norm.drug_class_normalized,
        route_normalized=route_normalized,
        formulation_features_normalized=formulation_features_norm,
        confidence=norm.confidence,
        method=norm.method,
    )


def normalize_extraction(extracted):  # ExtractionResult -> NormalizedProduct
    """Normalize a raw ExtractionResult into a NormalizedProduct.

    This is the single entry point for normalization.  Call it once per paper
    after extraction completes.  Pass the returned NormalizedProduct to
    ``score_product_similarity`` — do not call normalization inside the scorer.
    """
    from app.models.normalized import NormalizedProduct

    norm_device = None
    norm_drug = None

    if extracted.device is not None:
        norm_device = _normalize_device(extracted.device)

    if extracted.drug is not None:
        norm_drug = _normalize_drug(extracted.drug)

    if norm_device is not None and norm_drug is not None:
        product_type = "both"
    elif norm_device is not None:
        product_type = "device"
    elif norm_drug is not None:
        product_type = "drug"
    else:
        product_type = "unknown"

    return NormalizedProduct(
        device=norm_device,
        drug=norm_drug,
        product_type=product_type,
    )
