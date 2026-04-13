"""Ophthalmology device category normalization registry."""

from __future__ import annotations

from app.normalization.registry import NormalizationMethod, NormResult

# Maps raw device mentions (lowercase) to canonical category strings.
DEVICE_CATEGORY_ALIASES: dict[str, str] = {
    # Intraocular lenses
    "intraocular lens": "intraocular_lens",
    "intraocular lenses": "intraocular_lens",
    "iol": "intraocular_lens",
    "iols": "intraocular_lens",
    "phakic iol": "intraocular_lens",
    "phakic intraocular lens": "intraocular_lens",
    "implantable collamer lens": "intraocular_lens",
    "icl": "intraocular_lens",
    "implantable contact lens": "intraocular_lens",
    "pseudophakic lens": "intraocular_lens",
    "multifocal iol": "intraocular_lens",
    "toric iol": "intraocular_lens",
    "edof iol": "intraocular_lens",
    "extended depth of focus iol": "intraocular_lens",
    "accommodating iol": "intraocular_lens",
    "monofocal iol": "intraocular_lens",
    # Contact lenses
    "contact lens": "contact_lens",
    "contact lenses": "contact_lens",
    "soft contact lens": "contact_lens",
    "rigid contact lens": "contact_lens",
    "scleral lens": "contact_lens",
    "orthokeratology lens": "contact_lens",
    "ortho-k lens": "contact_lens",
    "drug-delivering contact lens": "contact_lens",
    "therapeutic contact lens": "contact_lens",
    # Glaucoma devices
    "glaucoma drainage device": "glaucoma_device",
    "glaucoma implant": "glaucoma_device",
    "trabeculectomy": "glaucoma_device",
    "tube shunt": "glaucoma_device",
    "ahmed glaucoma valve": "glaucoma_device",
    "baerveldt implant": "glaucoma_device",
    "migs device": "glaucoma_device",
    "minimally invasive glaucoma surgery": "glaucoma_device",
    "istent": "glaucoma_device",
    "hydrus": "glaucoma_device",
    "canaloplasty": "glaucoma_device",
    "xen gel stent": "glaucoma_device",
    "preserflo": "glaucoma_device",
    "microshunt": "glaucoma_device",
    "kahook dual blade": "glaucoma_device",
    "trabectome": "glaucoma_device",
    "selective laser trabeculoplasty": "glaucoma_device",
    "slt": "glaucoma_device",
    # Retinal / vitreoretinal devices
    "retinal implant": "retinal_device",
    "epiretinal prosthesis": "retinal_device",
    "subretinal implant": "retinal_device",
    "argus": "retinal_device",
    "argus ii": "retinal_device",
    "retinal prosthesis": "retinal_device",
    "macular implant": "retinal_device",
    "vitreoretinal": "vitreoretinal_device",
    "vitrectomy instrument": "vitreoretinal_device",
    "scleral buckle": "vitreoretinal_device",
    "silicone oil": "vitreoretinal_device",
    "perfluorocarbon": "vitreoretinal_device",
    "gas tamponade": "vitreoretinal_device",
    # Corneal devices
    "corneal implant": "corneal_device",
    "corneal inlay": "corneal_device",
    "corneal ring": "corneal_device",
    "intacs": "corneal_device",
    "keratoconus ring": "corneal_device",
    "keratoprosthesis": "corneal_device",
    "keratoprostheses": "corneal_device",
    "boston kpro": "corneal_device",
    "osteo-odonto-keratoprosthesis": "corneal_device",
    "ookp": "corneal_device",
    "corneal graft": "corneal_device",
    "penetrating keratoplasty": "corneal_device",
    "deep anterior lamellar keratoplasty": "corneal_device",
    "endothelial keratoplasty": "corneal_device",
    "dsaek": "corneal_device",
    "dmek": "corneal_device",
    # Ophthalmic viscosurgical devices
    "opd": "ophthalmic_viscosurgical_device",
    "ovd": "ophthalmic_viscosurgical_device",
    "viscoelastic": "ophthalmic_viscosurgical_device",
    "viscosurgical device": "ophthalmic_viscosurgical_device",
    "ophthalmic viscosurgical device": "ophthalmic_viscosurgical_device",
    "sodium hyaluronate viscoelastic": "ophthalmic_viscosurgical_device",
    "hydroxypropyl methylcellulose ovd": "ophthalmic_viscosurgical_device",
    "provisc": "ophthalmic_viscosurgical_device",
    "healon": "ophthalmic_viscosurgical_device",
    "duovisc": "ophthalmic_viscosurgical_device",
    "discovisc": "ophthalmic_viscosurgical_device",
}

_MATCH_CONFIDENCE: float = 0.95
_UNKNOWN_CONFIDENCE: float = 0.0


def normalize_device_category(raw: str) -> NormResult:
    """Normalize a raw device category string to a canonical value."""
    folded = raw.lower().strip()
    if folded in DEVICE_CATEGORY_ALIASES:
        return NormResult(
            raw=raw,
            canonical=DEVICE_CATEGORY_ALIASES[folded],
            confidence=_MATCH_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )
    for key, val in DEVICE_CATEGORY_ALIASES.items():
        if key in folded:
            return NormResult(
                raw=raw,
                canonical=val,
                confidence=_MATCH_CONFIDENCE,
                method=NormalizationMethod.DICTIONARY,
            )
    return NormResult(
        raw=raw,
        canonical=None,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )


# ---------------------------------------------------------------------------
# Intended use, energy source, sterilization — dictionary normalizers
# ---------------------------------------------------------------------------

INTENDED_USE_ALIASES: dict[str, str] = {
    "cataract surgery": "cataract_surgery",
    "phacoemulsification": "cataract_surgery",
    "refractive surgery": "refractive_surgery",
    "lasik": "refractive_surgery",
    "prk": "refractive_surgery",
    "percutaneous coronary intervention": "percutaneous_coronary_intervention",
    "minimally invasive glaucoma surgery": "migs",
    "migs": "migs",
    "glaucoma surgery": "glaucoma_surgery",
    "trabeculectomy": "glaucoma_surgery",
    "intravitreal injection": "intravitreal_injection",
    "vitrectomy": "vitrectomy",
    "corneal transplant": "corneal_transplant",
    "keratoplasty": "corneal_transplant",
}

ENERGY_SOURCE_ALIASES: dict[str, str] = {
    "electrical": "electrical",
    "electromagnetic": "electromagnetic",
    "mechanical": "mechanical",
    "chemical": "chemical",
    "thermal": "thermal",
    "laser": "optical",
    "optical": "optical",
    "ultrasound": "acoustic",
    "acoustic": "acoustic",
    "phaco": "acoustic",
    "none": "none",
    "passive": "none",
}

STERILIZATION_ALIASES: dict[str, str] = {
    "ethylene oxide": "eto",
    "eto": "eto",
    "eo": "eto",
    "gamma": "gamma",
    "gamma irradiation": "gamma",
    "e-beam": "ebeam",
    "electron beam": "ebeam",
    "steam": "steam",
    "autoclave": "steam",
    "plasma": "plasma",
    "hydrogen peroxide": "plasma",
    "sterile": "unknown_sterile",
}


def normalize_intended_use(raw: str) -> NormResult:
    """Normalize a raw intended use string to a canonical value."""
    folded = raw.lower().strip()
    if folded in INTENDED_USE_ALIASES:
        return NormResult(
            raw=raw,
            canonical=INTENDED_USE_ALIASES[folded],
            confidence=_MATCH_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )
    for key, val in INTENDED_USE_ALIASES.items():
        if key in folded:
            return NormResult(
                raw=raw,
                canonical=val,
                confidence=_MATCH_CONFIDENCE,
                method=NormalizationMethod.DICTIONARY,
            )
    return NormResult(
        raw=raw,
        canonical=None,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )


def normalize_energy_source(raw: str) -> NormResult:
    """Normalize a raw energy source string to a canonical value."""
    folded = raw.lower().strip()
    if folded in ENERGY_SOURCE_ALIASES:
        return NormResult(
            raw=raw,
            canonical=ENERGY_SOURCE_ALIASES[folded],
            confidence=_MATCH_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )
    for key, val in ENERGY_SOURCE_ALIASES.items():
        if key in folded:
            return NormResult(
                raw=raw,
                canonical=val,
                confidence=_MATCH_CONFIDENCE,
                method=NormalizationMethod.DICTIONARY,
            )
    return NormResult(
        raw=raw,
        canonical=None,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )


def normalize_sterilization(raw: str) -> NormResult:
    """Normalize a raw sterilization method string to a canonical value."""
    folded = raw.lower().strip()
    if folded in STERILIZATION_ALIASES:
        return NormResult(
            raw=raw,
            canonical=STERILIZATION_ALIASES[folded],
            confidence=_MATCH_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )
    for key, val in STERILIZATION_ALIASES.items():
        if key in folded:
            return NormResult(
                raw=raw,
                canonical=val,
                confidence=_MATCH_CONFIDENCE,
                method=NormalizationMethod.DICTIONARY,
            )
    return NormResult(
        raw=raw,
        canonical=None,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )
