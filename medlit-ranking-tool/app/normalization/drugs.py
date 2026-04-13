"""Ophthalmology drug normalization registry.

Maps raw extracted drug names (generic names, brand names, abbreviations)
to canonical active ingredient, drug class, and route values.

All normalization is dictionary/rule-based and deterministic.
"""

from __future__ import annotations

from app.normalization.registry import NormalizationMethod, NormResult

# ---------------------------------------------------------------------------
# (active_ingredient, drug_class) tuples
# ---------------------------------------------------------------------------

DRUG_INGREDIENT_ALIASES: dict[str, tuple[str, str]] = {
    # --- Anti-VEGF ---
    "ranibizumab": ("ranibizumab", "anti_vegf"),
    "lucentis": ("ranibizumab", "anti_vegf"),
    "aflibercept": ("aflibercept", "anti_vegf"),
    "eylea": ("aflibercept", "anti_vegf"),
    "zaltrap": ("aflibercept", "anti_vegf"),
    "bevacizumab": ("bevacizumab", "anti_vegf"),
    "avastin": ("bevacizumab", "anti_vegf"),
    "brolucizumab": ("brolucizumab", "anti_vegf"),
    "beovu": ("brolucizumab", "anti_vegf"),
    "faricimab": ("faricimab", "anti_vegf"),
    "vabysmo": ("faricimab", "anti_vegf"),
    "pegaptanib": ("pegaptanib", "anti_vegf"),
    "macugen": ("pegaptanib", "anti_vegf"),
    # --- Corticosteroids ---
    "dexamethasone": ("dexamethasone", "corticosteroid"),
    "ozurdex": ("dexamethasone", "corticosteroid"),
    "prednisolone": ("prednisolone", "corticosteroid"),
    "pred forte": ("prednisolone", "corticosteroid"),
    "loteprednol": ("loteprednol", "corticosteroid"),
    "lotemax": ("loteprednol", "corticosteroid"),
    "triamcinolone": ("triamcinolone", "corticosteroid"),
    "kenalog": ("triamcinolone", "corticosteroid"),
    "triesence": ("triamcinolone", "corticosteroid"),
    "fluocinolone": ("fluocinolone", "corticosteroid"),
    "iluvien": ("fluocinolone", "corticosteroid"),
    "retisert": ("fluocinolone", "corticosteroid"),
    # --- Antibiotics ---
    "moxifloxacin": ("moxifloxacin", "antibiotic"),
    "vigamox": ("moxifloxacin", "antibiotic"),
    "moxeza": ("moxifloxacin", "antibiotic"),
    "gatifloxacin": ("gatifloxacin", "antibiotic"),
    "zymaxid": ("gatifloxacin", "antibiotic"),
    "ofloxacin": ("ofloxacin", "antibiotic"),
    "ocuflox": ("ofloxacin", "antibiotic"),
    "tobramycin": ("tobramycin", "antibiotic"),
    "tobrex": ("tobramycin", "antibiotic"),
    "ciprofloxacin": ("ciprofloxacin", "antibiotic"),
    "ciloxan": ("ciprofloxacin", "antibiotic"),
    "azithromycin": ("azithromycin", "antibiotic"),
    # --- NSAIDs ---
    "ketorolac": ("ketorolac", "nsaid"),
    "acular": ("ketorolac", "nsaid"),
    "bromfenac": ("bromfenac", "nsaid"),
    "bronchek": ("bromfenac", "nsaid"),
    "nepafenac": ("nepafenac", "nsaid"),
    "ilevro": ("nepafenac", "nsaid"),
    "nevanac": ("nepafenac", "nsaid"),
    # --- Anti-inflammatory / immunomodulator ---
    "cyclosporine": ("cyclosporine", "immunomodulator"),
    "cyclosporin": ("cyclosporine", "immunomodulator"),
    "restasis": ("cyclosporine", "immunomodulator"),
    "cequa": ("cyclosporine", "immunomodulator"),
    "lifitegrast": ("lifitegrast", "immunomodulator"),
    "xiidra": ("lifitegrast", "immunomodulator"),
    # --- Prostaglandin analogues (glaucoma) ---
    "latanoprost": ("latanoprost", "prostaglandin_analog"),
    "xalatan": ("latanoprost", "prostaglandin_analog"),
    "bimatoprost": ("bimatoprost", "prostaglandin_analog"),
    "lumigan": ("bimatoprost", "prostaglandin_analog"),
    "latisse": ("bimatoprost", "prostaglandin_analog"),
    "travoprost": ("travoprost", "prostaglandin_analog"),
    "travatan": ("travoprost", "prostaglandin_analog"),
    "tafluprost": ("tafluprost", "prostaglandin_analog"),
    "zioptan": ("tafluprost", "prostaglandin_analog"),
    "netarsudil": ("netarsudil", "rho_kinase_inhibitor"),
    "rhopressa": ("netarsudil", "rho_kinase_inhibitor"),
    # --- Beta-blockers (glaucoma) ---
    "timolol": ("timolol", "beta_blocker"),
    "timoptic": ("timolol", "beta_blocker"),
    "betaxolol": ("betaxolol", "beta_blocker"),
    "betoptic": ("betaxolol", "beta_blocker"),
    "levobunolol": ("levobunolol", "beta_blocker"),
    # --- Carbonic anhydrase inhibitors (glaucoma) ---
    "dorzolamide": ("dorzolamide", "carbonic_anhydrase_inhibitor"),
    "trusopt": ("dorzolamide", "carbonic_anhydrase_inhibitor"),
    "brinzolamide": ("brinzolamide", "carbonic_anhydrase_inhibitor"),
    "azopt": ("brinzolamide", "carbonic_anhydrase_inhibitor"),
    # --- Alpha agonists (glaucoma) ---
    "brimonidine": ("brimonidine", "alpha_agonist"),
    "alphagan": ("brimonidine", "alpha_agonist"),
    "apraclonidine": ("apraclonidine", "alpha_agonist"),
    "iopidine": ("apraclonidine", "alpha_agonist"),
    # --- Mydriatics / cycloplegics ---
    "atropine": ("atropine", "mydriatic_cycloplegic"),
    "tropicamide": ("tropicamide", "mydriatic_cycloplegic"),
    "mydriacyl": ("tropicamide", "mydriatic_cycloplegic"),
    "phenylephrine": ("phenylephrine", "mydriatic_cycloplegic"),
    "cyclopentolate": ("cyclopentolate", "mydriatic_cycloplegic"),
    "cyclogyl": ("cyclopentolate", "mydriatic_cycloplegic"),
    "homatropine": ("homatropine", "mydriatic_cycloplegic"),
    # --- Antifungal ---
    "natamycin": ("natamycin", "antifungal"),
    "natacyn": ("natamycin", "antifungal"),
    "voriconazole": ("voriconazole", "antifungal"),
    # --- Antiviral ---
    "ganciclovir": ("ganciclovir", "antiviral"),
    "zirgan": ("ganciclovir", "antiviral"),
    "trifluridine": ("trifluridine", "antiviral"),
    "viroptic": ("trifluridine", "antiviral"),
    # --- Artificial tears / lubricants ---
    "sodium hyaluronate": ("sodium_hyaluronate", "lubricant"),
    "hyaluronic acid": ("sodium_hyaluronate", "lubricant"),
    "carboxymethylcellulose": ("carboxymethylcellulose", "lubricant"),
    "refresh": ("carboxymethylcellulose", "lubricant"),
    "hydroxypropyl methylcellulose": ("hydroxypropyl_methylcellulose", "lubricant"),
    "hpmc": ("hydroxypropyl_methylcellulose", "lubricant"),
}

# Route keyword hints — substring match in raw text / context.
ROUTE_KEYWORDS: dict[str, str] = {
    "intravitreal": "intravitreal",
    "ivt": "intravitreal",
    "intravitreal injection": "intravitreal",
    "intraocular": "intraocular",
    "subconjunctival": "subconjunctival",
    "topical": "topical",
    "eye drop": "topical",
    "ophthalmic drop": "topical",
    "ophthalmic solution": "topical",
    "ophthalmic ointment": "topical",
    "ophthalmic gel": "topical",
    "ointment": "topical",
    "periocular": "periocular",
    "peribulbar": "periocular",
    "retrobulbar": "periocular",
    "oral": "oral",
    "systemic": "oral",
    "sustained release implant": "implant",
    "implant": "implant",
    "intracameral": "intracameral",
}

# Formulation feature hints — substring match.
FORMULATION_FEATURE_KEYWORDS: dict[str, str] = {
    "preservative free": "preservative_free",
    "preservative-free": "preservative_free",
    "unit dose": "preservative_free",
    "pfree": "preservative_free",
    "extended release": "extended_release",
    "sustained release": "extended_release",
    "depot": "extended_release",
    "implant": "implant_formulation",
    "emulsion": "emulsion",
    "gel": "gel",
    "ointment": "ointment",
    "nanodroplet": "nanodroplet",
    "nanoparticle": "nanoparticle",
    "liposomal": "liposomal",
}

_MATCH_CONFIDENCE: float = 0.95
_UNKNOWN_CONFIDENCE: float = 0.0


def _scan(text: str, table: dict[str, str]) -> str | None:
    folded = text.lower()
    if folded in table:
        return table[folded]
    for key, val in table.items():
        if key in folded:
            return val
    return None


def normalize_drug(
    raw_name: str,
    raw_context: str | None = None,
) -> "NormalizedDrugResult":
    """Normalize a raw drug name into canonical ingredient / class / route.

    ``raw_context`` may be the full sentence or abstract excerpt where the drug
    was mentioned, used only for route / formulation detection.
    """
    combined = (raw_name + " " + (raw_context or "")).strip()

    ingredient_match = _scan(raw_name, {k: v[0] for k, v in DRUG_INGREDIENT_ALIASES.items()})
    class_match = _scan(raw_name, {k: v[1] for k, v in DRUG_INGREDIENT_ALIASES.items()})

    route = _scan(combined, ROUTE_KEYWORDS)
    formulation_features: list[str] = []
    seen_ff: set[str] = set()
    for key, tag in FORMULATION_FEATURE_KEYWORDS.items():
        if key in combined.lower() and tag not in seen_ff:
            formulation_features.append(tag)
            seen_ff.add(tag)

    if ingredient_match:
        return NormalizedDrugResult(
            raw_name=raw_name,
            active_ingredient_normalized=ingredient_match,
            drug_class_normalized=class_match,
            route_normalized=route,
            formulation_features_normalized=formulation_features,
            confidence=_MATCH_CONFIDENCE,
            method=NormalizationMethod.DICTIONARY,
        )

    return NormalizedDrugResult(
        raw_name=raw_name,
        active_ingredient_normalized=None,
        drug_class_normalized=None,
        route_normalized=route,
        formulation_features_normalized=formulation_features,
        confidence=_UNKNOWN_CONFIDENCE,
        method=NormalizationMethod.UNKNOWN,
    )


class NormalizedDrugResult:
    """Plain result returned by normalize_drug(); avoids circular imports."""

    __slots__ = (
        "raw_name",
        "active_ingredient_normalized",
        "drug_class_normalized",
        "route_normalized",
        "formulation_features_normalized",
        "confidence",
        "method",
    )

    def __init__(
        self,
        raw_name: str,
        active_ingredient_normalized: str | None,
        drug_class_normalized: str | None,
        route_normalized: str | None,
        formulation_features_normalized: list[str],
        confidence: float,
        method: NormalizationMethod,
    ) -> None:
        self.raw_name = raw_name
        self.active_ingredient_normalized = active_ingredient_normalized
        self.drug_class_normalized = drug_class_normalized
        self.route_normalized = route_normalized
        self.formulation_features_normalized = formulation_features_normalized
        self.confidence = confidence
        self.method = method
