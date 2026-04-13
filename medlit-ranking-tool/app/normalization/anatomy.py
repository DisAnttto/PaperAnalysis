"""Ophthalmology anatomical site and indication normalization registry."""

from __future__ import annotations

from app.normalization.registry import NormalizationMethod, NormListResult, NormResult

# ---------------------------------------------------------------------------
# Anatomical site aliases → canonical site
# ---------------------------------------------------------------------------

ANATOMY_ALIASES: dict[str, str] = {
    # Anterior segment
    "anterior segment": "anterior_segment",
    "anterior chamber": "anterior_segment",
    "ac": "anterior_segment",
    # Posterior segment
    "posterior segment": "posterior_segment",
    "posterior chamber": "posterior_segment",
    "vitreous cavity": "vitreous",
    "vitreous": "vitreous",
    "vitreous body": "vitreous",
    # Cornea
    "cornea": "cornea",
    "corneal": "cornea",
    "corneal surface": "cornea",
    "corneal stroma": "cornea",
    "corneal endothelium": "cornea",
    "corneal epithelium": "cornea",
    # Retina
    "retina": "retina",
    "retinal": "retina",
    "neural retina": "retina",
    "peripheral retina": "retina",
    # Macula / fovea
    "macula": "macula",
    "macular": "macula",
    "fovea": "macula",
    "foveal": "macula",
    "subfoveal": "macula",
    # Lens
    "lens": "lens_capsule",
    "crystalline lens": "lens_capsule",
    "lens capsule": "lens_capsule",
    "posterior capsule": "lens_capsule",
    "anterior capsule": "lens_capsule",
    "capsular bag": "lens_capsule",
    # Trabecular meshwork / angle
    "trabecular meshwork": "trabecular_meshwork",
    "trabeculum": "trabecular_meshwork",
    "iridocorneal angle": "trabecular_meshwork",
    "schlemm's canal": "trabecular_meshwork",
    "drainage angle": "trabecular_meshwork",
    # Conjunctiva / ocular surface
    "conjunctiva": "conjunctiva",
    "conjunctival": "conjunctiva",
    "ocular surface": "ocular_surface",
    "limbus": "ocular_surface",
    "limbal": "ocular_surface",
    # Optic nerve
    "optic nerve": "optic_nerve",
    "optic disc": "optic_nerve",
    "optic nerve head": "optic_nerve",
    "peripapillary": "optic_nerve",
    # Iris / ciliary body
    "iris": "iris",
    "ciliary body": "iris",
    "ciliary": "iris",
    "uvea": "iris",
    "uveal": "iris",
    # Sclera
    "sclera": "sclera",
    "scleral": "sclera",
    # Choroid
    "choroid": "choroid",
    "choroidal": "choroid",
    "subretinal": "choroid",
    # Eyelid
    "eyelid": "eyelid",
    "lid": "eyelid",
    "meibomian gland": "eyelid",
}

# ---------------------------------------------------------------------------
# Indication / condition aliases → canonical indication
# ---------------------------------------------------------------------------

INDICATION_ALIASES: dict[str, str] = {
    # Cataract
    "cataract": "cataract",
    "cataracts": "cataract",
    "cataract surgery": "cataract",
    "phacoemulsification": "cataract",
    "phaco": "cataract",
    "lens extraction": "cataract",
    "pseudophakia": "cataract",
    # Glaucoma
    "glaucoma": "glaucoma",
    "open angle glaucoma": "glaucoma",
    "oag": "glaucoma",
    "primary open-angle glaucoma": "glaucoma",
    "poag": "glaucoma",
    "angle closure glaucoma": "glaucoma",
    "acg": "glaucoma",
    "normal tension glaucoma": "glaucoma",
    "refractory glaucoma": "glaucoma",
    "medically refractory glaucoma": "glaucoma",
    "ocular hypertension": "ocular_hypertension",
    "oht": "ocular_hypertension",
    "elevated iop": "ocular_hypertension",
    "intraocular pressure": "ocular_hypertension",
    # Dry eye / ocular surface
    "dry eye": "dry_eye",
    "dry eye disease": "dry_eye",
    "ded": "dry_eye",
    "keratoconjunctivitis sicca": "dry_eye",
    "kcs": "dry_eye",
    "meibomian gland dysfunction": "dry_eye",
    "mgd": "dry_eye",
    "ocular surface disease": "dry_eye",
    # Macular degeneration
    "macular degeneration": "macular_degeneration",
    "age-related macular degeneration": "macular_degeneration",
    "armd": "macular_degeneration",
    "amd": "macular_degeneration",
    "neovascular amd": "macular_degeneration",
    "wet amd": "macular_degeneration",
    "dry amd": "macular_degeneration",
    "geographic atrophy": "macular_degeneration",
    "choroidal neovascularization": "macular_degeneration",
    "cnv": "macular_degeneration",
    # Diabetic macular edema
    "diabetic macular edema": "diabetic_macular_edema",
    "dme": "diabetic_macular_edema",
    "clinically significant macular edema": "diabetic_macular_edema",
    "csme": "diabetic_macular_edema",
    # Diabetic retinopathy
    "diabetic retinopathy": "diabetic_retinopathy",
    "dr": "diabetic_retinopathy",
    "proliferative diabetic retinopathy": "diabetic_retinopathy",
    "pdr": "diabetic_retinopathy",
    "nonproliferative diabetic retinopathy": "diabetic_retinopathy",
    "npdr": "diabetic_retinopathy",
    # Retinal detachment / tears
    "retinal detachment": "retinal_detachment",
    "rd": "retinal_detachment",
    "rhegmatogenous retinal detachment": "retinal_detachment",
    "retinal tear": "retinal_detachment",
    "tractional retinal detachment": "retinal_detachment",
    # Uveitis
    "uveitis": "uveitis",
    "anterior uveitis": "uveitis",
    "posterior uveitis": "uveitis",
    "panuveitis": "uveitis",
    "iritis": "uveitis",
    "iridocyclitis": "uveitis",
    "endophthalmitis": "uveitis",
    # Keratoconus
    "keratoconus": "keratoconus",
    "ectasia": "keratoconus",
    "corneal ectasia": "keratoconus",
    # Presbyopia / refractive
    "presbyopia": "presbyopia",
    "near vision loss": "presbyopia",
    "myopia": "myopia",
    "myopic": "myopia",
    "nearsightedness": "myopia",
    "hyperopia": "hyperopia",
    "farsightedness": "hyperopia",
    "astigmatism": "astigmatism",
    "refractive error": "refractive_error",
    # Macular / retinal other
    "epiretinal membrane": "epiretinal_membrane",
    "erm": "epiretinal_membrane",
    "macular hole": "macular_hole",
    "macular pucker": "epiretinal_membrane",
    "vitreomacular traction": "vitreomacular_traction",
    "vmt": "vitreomacular_traction",
    "retinal vein occlusion": "retinal_vein_occlusion",
    "rvo": "retinal_vein_occlusion",
    "branch retinal vein occlusion": "retinal_vein_occlusion",
    "brvo": "retinal_vein_occlusion",
    "central retinal vein occlusion": "retinal_vein_occlusion",
    "crvo": "retinal_vein_occlusion",
    # Other
    "pterygium": "pterygium",
    "blepharitis": "blepharitis",
    "chalazion": "chalazion",
}

_MATCH_CONFIDENCE: float = 0.95
_UNKNOWN_CONFIDENCE: float = 0.0


def _lookup(raw: str, table: dict[str, str]) -> str | None:
    """Case-insensitive exact then longest-key-first substring scan."""
    folded = raw.lower().strip()
    if folded in table:
        return table[folded]
    for key in sorted(table, key=len, reverse=True):
        if key in folded:
            return table[key]
    return None


def normalize_anatomical_site(raw: str) -> NormResult:
    """Normalize a raw anatomical site string."""
    canonical = _lookup(raw, ANATOMY_ALIASES)
    if canonical:
        return NormResult(
            raw=raw,
            canonical=canonical,
            confidence=_MATCH_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )
    return NormResult(
        raw=raw,
        canonical=None,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )


def normalize_indication(raw: str) -> NormResult:
    """Normalize a single raw indication string."""
    canonical = _lookup(raw, INDICATION_ALIASES)
    if canonical:
        return NormResult(
            raw=raw,
            canonical=canonical,
            confidence=_MATCH_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )
    return NormResult(
        raw=raw,
        canonical=None,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )


def normalize_indications(raw_list: list[str]) -> NormListResult:
    """Normalize a list of raw indication strings."""
    canonical: list[str] = []
    total_conf: float = 0.0
    for raw in raw_list:
        result = normalize_indication(raw)
        if result.canonical is not None:
            canonical.append(result.canonical)
            total_conf += result.confidence
        else:
            total_conf += 0.0

    n = len(raw_list)
    avg_conf = (total_conf / n) if n > 0 else 0.0
    method = NormalizationMethod.DICTIONARY if canonical else NormalizationMethod.UNKNOWN

    return NormListResult(
        raw=raw_list,
        canonical=canonical,
        confidence=avg_conf,
        method=method,
    )
