"""
Slim ontology + drift maps for the resolution pipeline.

Single source of truth for:
  - LABEL_MAP        : raw extraction entity type → (core label, subtype, role)
  - EDGE_MAP / drift : raw edge label → canonical edge label (or DROP)
  - ROLE_GAZETTEER   : generic role placeholders (never canonicalized cross-contract)
  - KNOWN_CANONICALS : alias clusters for named entities needing merge (Con Edison family…)
  - REGULATORS       : shared cross-contract authorities
  - ORG_SUFFIX_RE    : heuristic for "this is a named org"

See docs/kg_redesign_spec.md §2, §6.
"""

import re

from app.kg.resolution.model import normalize_name

# ── Core labels (the slim ontology) ────────────────────────────────────────────
CORE_LABELS = {
    "Party", "GovernmentalAuthority", "Obligation", "Right", "Restriction",
    "TemporalConstraint", "Event", "Condition", "FinancialTerm", "Instrument",
    "Concept",
}

# Party-role labels → collapse to Party, role moved onto the node/edge.
# value = roleNormalized
PARTY_ROLE_LABELS = {
    "Obligor": "obligor",
    "Obligee": "obligee",
    "Indemnitor": "indemnitor",
    "Indemnitee": "indemnitee",
    "BreachingParty": "breaching",
    "NonBreachingParty": "non_breaching",
    "NoticeRecipient": "notice_recipient",
    "Assignor": "assignor",
    "Assignee": "assignee",
    "ThirdParty": "third_party",
}

# raw entity type → (core_label, subtype)
LABEL_MAP = {
    # parties / authorities
    "Party": ("Party", None),
    "GovernmentalAuthority": ("GovernmentalAuthority", None),
    # duties / entitlements
    "Obligation": ("Obligation", None),
    "Right": ("Right", None),
    "Restriction": ("Restriction", None),
    "TerminationRight": ("Right", "termination"),
    # temporal
    "Deadline": ("TemporalConstraint", "deadline"),
    "NoticePeriod": ("TemporalConstraint", "noticePeriod"),
    "Frequency": ("TemporalConstraint", "frequency"),
    "EffectiveDate": ("TemporalConstraint", "effectiveDate"),
    "PerformanceMilestoneDate": ("TemporalConstraint", "milestone"),
    "CurePeriod": ("TemporalConstraint", "curePeriod"),
    # events / conditions
    "Event": ("Event", None),
    "ObligationTrigger": ("Event", "trigger"),
    "NoticeTrigger": ("Event", "trigger"),
    "ForceMajeureEvent": ("Event", "forceMajeure"),
    "TerminationEvent": ("Event", "termination"),
    "Breach": ("Event", "breach"),
    "Dispute": ("Event", "dispute"),
    "Condition": ("Condition", "condition"),
    "Exception": ("Condition", "exception"),
    # financial
    "Liability": ("FinancialTerm", "liability"),
    "ReimbursableCost": ("FinancialTerm", "cost"),
    "InterestRate": ("FinancialTerm", "interestRate"),
    "Invoice": ("FinancialTerm", "invoice"),
    "MonetaryAmount": ("FinancialTerm", "amount"),
    # instruments / documents
    "Agreement": ("Instrument", "agreement"),
    "Contract": ("Instrument", "contract"),
    "Notice": ("Instrument", "notice"),
    "Deliverable": ("Instrument", "deliverable"),
    "InsurancePolicy": ("Instrument", "insurancePolicy"),
    "InsuranceCertificate": ("Instrument", "insuranceCertificate"),
    "Consent": ("Instrument", "consent"),
    "Claim": ("Instrument", "claim"),
    # concepts
    "ConfidentialInformation": ("Concept", "confidentialInfo"),
    "LegalRequirement": ("Concept", "legalRequirement"),
    "Service": ("Concept", "service"),
    "Facility": ("Concept", "facility"),
    "Asset": ("Concept", "asset"),
    "System": ("Concept", "system"),
    "RiskSignal": ("Concept", "riskSignal"),
}


def map_entity_type(raw_type: str):
    """Return (core_label, subtype, role_or_None). Unknown → (None, raw, None)."""
    if raw_type in PARTY_ROLE_LABELS:
        return "Party", None, PARTY_ROLE_LABELS[raw_type]
    if raw_type in LABEL_MAP:
        core, sub = LABEL_MAP[raw_type]
        return core, sub, None
    return None, raw_type, None  # unmapped → caller logs


# ── Edge drift / canonicalization ──────────────────────────────────────────────
# Edges whose label we drop entirely (provenance, redundant with denormalized
# citation fields, or junk).
DROP_EDGE_LABELS = {
    "IMPOSES_OBLIGATION",   # clause→obligation, no clause vertex, redundant
    "EXTRACTED_ENTITY",     # clause→entity provenance from the old loader
    "Party",                # junk: vertex label used as edge
}

# Light alias fixes for the few drifted edge labels seen in the data.
EDGE_ALIASES = {
    "GRANTS_RIGHT": "GRANTS_RIGHT_TO",
    "IMPOSES_OBLIGATION_ON": "IMPOSES_OBLIGATION_ON",  # canonical already
}


def map_edge_label(raw_label: str):
    """Return canonical edge label, or None to drop."""
    if raw_label in DROP_EDGE_LABELS:
        return None
    return EDGE_ALIASES.get(raw_label, raw_label)


# ── Role-vs-named classification inputs ────────────────────────────────────────

# Generic role placeholders. Compared against normalizedName. These are NEVER
# canonicalized across contracts ("Seller" in two PPAs = two different companies).
ROLE_GAZETTEER = {
    "party", "parties", "each party", "either party", "other party", "both parties",
    "such party", "relevant party", "injured party", "sending party", "receiving party",
    "requesting party", "granting party", "paying party", "invoicing party", "access party",
    "disclosing party", "defaulting party", "non-defaulting party", "breaching party",
    "non-breaching party", "indemnified party", "indemnifying party", "indemnified parties",
    "indemnitor", "indemnitee", "third party", "third parties", "third person", "other parties",
    "buyer", "seller", "contractor", "subcontractor", "subcontractors", "owner", "purchaser",
    "customer", "client", "supplier", "vendor", "guarantor", "lender", "licensee", "operator",
    "provider", "providers", "beneficiary", "applicant", "expert", "secured party",
    "permitted transferee", "affiliate", "affiliates", "developer", "new developer",
    "transmission developer", "connecting transmission owner", "system operator",
    "affected system operator", "scheduling coordinator",
    # generic authority / defined-term placeholders (not specific named orgs)
    "governmental authority", "governmental authorities", "government authority",
    "government authorities", "authority", "authorities", "company", "utility",
    "district", "state", "department", "fire department", "permitting department",
    "local municipal governments", "authority having jurisdiction",
    "authority having jurisdiction (ahj)", "ahj", "parties", "the parties",
}

# Known regulators / ISOs — shared cross-contract authorities (entityClass = regulator).
# key = canonical slug ; value = (canonicalName, {aliases lowercased})
REGULATORS = {
    "nerc": ("NERC", {"nerc", "north american electric reliability corporation"}),
    "ferc": ("FERC", {"ferc", "federal energy regulatory commission"}),
    "nyiso": ("NYISO", {"nyiso", "new york independent system operator"}),
    "caiso": ("CAISO", {"caiso", "california independent system operator"}),
    "serc": ("SERC", {"serc", "serc reliability corporation"}),
}

# Named-org alias clusters that REQUIRE merging variant surface forms.
# key = canonical slug ; value = (canonicalName, entityClass, {aliases lowercased})
# IMPORTANT: keep distinct orgs apart — Con Edison (Consolidated Edison) is NOT
# Southern California Edison ("Edison"/"SCE").
KNOWN_CANONICALS = {
    "con_edison": ("Con Edison", "org", {
        "con edison", "consolidated edison", "consolidated edison inc",
        "consolidated edison, inc.", "consolidated edison inc.",
        "consolidated edison company of new york, inc.",
        "consolidated edison company of new york inc",
    }),
    "southern_california_edison": ("Southern California Edison", "org", {
        "sce", "southern california edison", "edison",
    }),
    "nypa": ("New York Power Authority", "org", {
        "nypa", "new york power authority", "power authority", "nypa ecc",
    }),
    "nextera_energy_resources": ("NextEra Energy Resources, LLC", "org", {
        "nextera energy resources, llc", "nextera energy resources llc",
    }),
    "nextera_energy_transmission": ("NextEra Energy Transmission, LLC", "org", {
        "nextera energy transmission, llc", "nextera energy transmission llc",
    }),
    "sunpower": ("SunPower", "org", {"sunpower"}),
    "terra_gen": ("Terra-Gen, LLC", "org", {"terra-gen, llc", "terra-gen llc", "terra-gen"}),
    "san_jose_clean_energy": ("San José Clean Energy", "org", {
        "san josé clean energy", "san jose clean energy", "sjce",
    }),
    "florida_power_light": ("Florida Power & Light Company", "org", {
        "florida power & light company", "florida power and light company",
    }),
    "omnidian": ("Omnidian Inc.", "org", {"omnidian inc.", "omnidian inc", "omnidian"}),
}

# Positive heuristic: strong corporate/legal suffixes only (no generic words like
# "system", "services", "power"). Combined with a multi-token requirement in
# looks_like_org() so bare "Company"/"Utility"/"Authority" stay role placeholders.
ORG_SUFFIX_RE = re.compile(
    r"\b("
    r"inc|incorporated|llc|l\.l\.c|lp|l\.p|corp|corporation|company|co|ltd|plc|"
    r"gmbh|n\.a|commission"
    r")\b\.?$",
)


# ── Precomputed normalized alias index (named entities only) ───────────────────
# normalized_alias → (canonical_id, canonicalName, entityClass)
NAMED_ALIAS_INDEX = {}
for _slug, (_name, _aliases) in REGULATORS.items():
    for _a in _aliases:
        NAMED_ALIAS_INDEX[normalize_name(_a)] = (
            f"canonical:regulator:{_slug}", _name, "regulator",
        )
for _key, (_name, _cls, _aliases) in KNOWN_CANONICALS.items():
    for _a in _aliases:
        NAMED_ALIAS_INDEX[normalize_name(_a)] = (
            f"canonical:{_cls}:{_key}", _name, _cls,
        )


def looks_like_org(normalized_name: str) -> bool:
    """Multi-token name ending in a strong corporate suffix → named org."""
    if len(normalized_name.split()) < 2:
        return False
    return bool(ORG_SUFFIX_RE.search(normalized_name))


def classify_party(normalized_name: str) -> str:
    """entityClass: 'named' | 'role' (concept handled upstream)."""
    if normalized_name in NAMED_ALIAS_INDEX:
        return "named"
    if normalized_name in ROLE_GAZETTEER:
        return "role"
    if looks_like_org(normalized_name):
        return "named"
    return "role"
