"""Enumerations for the correlated-evidence retrieval system."""

from enum import StrEnum


class SourceType(StrEnum):
    pubmed_paper = "pubmed_paper"
    pmc_article = "pmc_article"
    fda_510k = "fda_510k"
    fda_pma = "fda_pma"
    fda_denovo = "fda_denovo"
    fda_ssed = "fda_ssed"
    fda_review = "fda_review"
    fda_label = "fda_label"
    dailymed_label = "dailymed_label"
    clinicaltrials = "clinicaltrials"
    accessgudid_device = "accessgudid_device"
    maude_event = "maude_event"
    fda_recall = "fda_recall"
    fda_denovo_pdf = "fda_denovo_pdf"
    fda_510k_pdf = "fda_510k_pdf"


class TierLevel(StrEnum):
    Tier0 = "Tier0"
    Tier1 = "Tier1"
    Tier2 = "Tier2"
    Tier3 = "Tier3"
    Tier4 = "Tier4"
    Tier5 = "Tier5"


class RelationLabel(StrEnum):
    self_match = "self_match"
    direct_predicate = "direct_predicate"
    direct_review = "direct_review"
    label = "label"
    linked_trial = "linked_trial"
    direct_same_product = "direct_same_product"
    direct_citation = "direct_citation"
    same_ingredient = "same_ingredient"
    same_active_ingredient = "same_active_ingredient"
    same_device_family = "same_device_family"
    same_indication = "same_indication"
    same_endpoint = "same_endpoint"
    same_endpoint_or_metric = "same_endpoint_or_metric"
    same_trial_design_or_comparator_logic = "same_trial_design_or_comparator_logic"
    contextual = "contextual"
    weak_context_only = "weak_context_only"
    distractor = "distractor"
    hard_negative = "hard_negative"
