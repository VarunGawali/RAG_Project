import json
import re
import hashlib
from typing import Dict, Any

from openai import AzureOpenAI

from app import config
from app.kg.models import KGNode, LegalExtractionResult

# =============================================================================
# Canonical ontology — single source of truth used by BOTH the extractor
# prompt and the graph retriever.  Every label/edge emitted by the LLM must
# come from one of these lists.
# =============================================================================

LEGAL_NODE_TYPES = [
    # ── Parties and roles ──────────────────────────────────────────────
    "Party",                    # generic named party
    "Obligor",                  # party bearing a duty
    "Obligee",                  # party to whom a duty is owed
    "Indemnitor",               # party providing indemnification
    "Indemnitee",               # party receiving indemnification
    "BreachingParty",
    "NonBreachingParty",
    "NoticeRecipient",
    "Assignor",
    "Assignee",
    "ThirdParty",
    "GovernmentalAuthority",

    # ── Duties and entitlements ────────────────────────────────────────
    "Obligation",               # a duty imposed on a party
    "Right",                    # a permission or entitlement
    "Restriction",              # a prohibition or limitation
    "ObligationTrigger",        # condition that activates an obligation

    # ── Temporal / deadline entities ──────────────────────────────────
    "Deadline",                 # specific date/time a duty must be met
    "NoticePeriod",             # required advance-notice window
    "Frequency",                # recurring cadence (monthly, quarterly…)
    "EffectiveDate",
    "PerformanceMilestoneDate",

    # ── Events and conditions ──────────────────────────────────────────
    "Event",                    # triggering occurrence
    "Condition",                # a prerequisite or contingency
    "Exception",                # a carve-out or exclusion
    "ForceMajeureEvent",
    "TerminationEvent",
    "TerminationRight",
    "Breach",
    "CurePeriod",
    "Dispute",

    # ── Instruments and documents ──────────────────────────────────────
    "Agreement",
    "Contract",
    "Notice",
    "Invoice",
    "InsuranceCertificate",
    "InsurancePolicy",
    "Deliverable",
    "Consent",
    "Claim",

    # ── Financial ─────────────────────────────────────────────────────
    "Liability",
    "ReimbursableCost",
    "InterestRate",

    # ── Other ─────────────────────────────────────────────────────────
    "ConfidentialInformation",
    "LegalRequirement",
    "Service",
    "Facility",
]

LEGAL_RELATIONSHIP_TYPES = [
    # ── Obligation edges (CORE — retriever depends on these) ───────────
    "OWED_BY",                  # Obligation → Party  (party bears the duty)
    "OWED_TO",                  # Obligation → Party  (party benefits from duty)
    "OBLIGATES",                # Obligor → Obligation
    "IMPOSES_OBLIGATION_ON",    # any node → Party
    "TRIGGERS_OBLIGATION_OF",   # Event/Condition → Obligation

    # ── Temporal edges (CORE) ──────────────────────────────────────────
    "HAS_DEADLINE",             # Obligation → Deadline
    "HAS_NOTICE_PERIOD",        # Obligation/Right → NoticePeriod
    "HAS_FREQUENCY",            # Obligation → Frequency

    # ── Condition/exception edges ──────────────────────────────────────
    "SUBJECT_TO",               # Obligation/Right → Condition
    "EXCEPTS",                  # Obligation/Right → Exception
    "TRIGGERED_BY",             # Obligation → Event

    # ── Indemnification ────────────────────────────────────────────────
    "INDEMNIFIES",              # Indemnitor → Indemnitee
    "FALLS_WITHIN_INDEMNITY_SCOPE_OF",
    "LIMITS_INDEMNITY_OBLIGATION_OF",

    # ── Liability ─────────────────────────────────────────────────────
    "CAPS_LIABILITY_OF",

    # ── Payment / financial ────────────────────────────────────────────
    "PAYS",                     # Party → Party
    "MAKES_PAYMENT_TO",
    "REIMBURSES",
    "BEARS_COSTS_OF",

    # ── Notice / communication ─────────────────────────────────────────
    "GIVES_NOTICE_TO",
    "PROVIDES_NOTICE_TO",
    "NOTIFIES",
    "REQUIRES_NOTICE_FROM",

    # ── Assignment ────────────────────────────────────────────────────
    "ASSIGNS_RIGHTS_TO",

    # ── Access / rights ───────────────────────────────────────────────
    "GRANTS_ACCESS_TO",
    "GRANTS_RIGHT_TO",

    # ── Compliance / cooperation ───────────────────────────────────────
    "COMPLIES_WITH",
    "REQUIRES_COMPLIANCE_WITH",
    "COOPERATES_WITH",
    "MAINTAINS",
    "PROVIDES",
    "DELIVERS",

    # ── Termination / breach ──────────────────────────────────────────
    "TERMINATES",
    "TRIGGERS_CURE_PERIOD_OF",
    "EXCUSES_BREACH_OF",

    # ── Survival / applicability ───────────────────────────────────────
    "SURVIVES_TERMINATION_OF",
    "APPLIES_TO",
    "NAMES_AS_ADDITIONAL_INSURED",
]


def slugify(value: str, max_len: int = 80) -> str:
    value = value or "unknown"
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:max_len] or "unknown"


def short_hash(value: str, length: int = 8) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


class LegalLLMExtractor:
    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )

    def build_prompt(self, clause: KGNode) -> str:
        return f"""
You are a legal contract knowledge graph extraction expert.

Extract legal-semantic entities and relationships from the clause below.

ALLOWED ENTITY TYPES (use ONLY these labels):
{LEGAL_NODE_TYPES}

ALLOWED RELATIONSHIP TYPES (use ONLY these edge labels):
{LEGAL_RELATIONSHIP_TYPES}

EXTRACTION RULES
----------------
General:
1. Extract only information explicitly supported by the text. Do not hallucinate.
2. Every entity must have a stable, deterministic id.
3. Every relationship source_id and target_id must refer to extracted entity ids or the source clause id.
4. The source clause id is: {clause.kgId}
5. Include confidence 0–1. Include an exact evidence quote where possible.
6. Do not create duplicate Party entities within one clause.
7. Prefer normalized party names: "Con Edison", "Power Authority", "Either Party", "Party".
8. Use deterministic IDs: "<type_lower>:<contract_id>:<short_hash>:<slug>"

Duties (Obligation / Right / Restriction):
9.  If the clause imposes a duty → create an Obligation vertex.
10. If the clause grants a permission or entitlement → create a Right vertex.
11. If the clause forbids conduct → create a Restriction vertex.
12. For every Obligation, if the obligated party is stated, create a Party vertex (or Obligor)
    and an OWED_BY edge: Obligation → Party.
13. For every Obligation, if the beneficiary party is stated, create a Party vertex (or Obligee)
    and an OWED_TO edge: Obligation → Party.

Temporal:
14. If a deadline is present → create a Deadline vertex + HAS_DEADLINE edge from the Obligation.
15. If a notice period is present → create a NoticePeriod vertex + HAS_NOTICE_PERIOD edge.
16. If a recurring frequency is present → create a Frequency vertex + HAS_FREQUENCY edge.

Conditions / Exceptions / Triggers:
17. If a condition is present → create a Condition vertex + SUBJECT_TO edge.
18. If an exception/carve-out is present → create an Exception vertex + EXCEPTS edge.
19. If a triggering event is present → create an Event vertex + TRIGGERED_BY edge.

Indemnification:
20. If the clause provides indemnification → create Indemnitor and Indemnitee vertices
    + INDEMNIFIES edge: Indemnitor → Indemnitee.

Termination / Breach:
21. If the clause describes a termination right or event → create TerminationRight or TerminationEvent.
22. If the clause describes breach and cure → create Breach and CurePeriod vertices.

Payments:
23. If the clause involves payment → use Invoice, ReimbursableCost, or PAYS/MAKES_PAYMENT_TO edges.

Notice:
24. If the clause requires notice → create Notice vertex + GIVES_NOTICE_TO or PROVIDES_NOTICE_TO edge
    pointing to the NoticeRecipient.

Contract ID: {clause.contractId}
Clause ID: {clause.kgId}
Clause title: {clause.title}
Clause type hint: {clause.clauseTypeHint}
Page start: {clause.pageStart}
Page end: {clause.pageEnd}
Source path: {clause.sourcePath}

Clause text:
\"\"\"
{clause.text}
\"\"\"

Return JSON in this exact shape (no markdown fences):
{{
  "source_clause_id": "{clause.kgId}",
  "source_clause_title": "{clause.title}",
  "source_page_start": {clause.pageStart},
  "source_page_end": {clause.pageEnd},
  "entities": [
    {{
      "id": "obligation:{clause.contractId}:<short_hash>:<slug>",
      "type": "Obligation",
      "name": "...",
      "properties": {{}},
      "confidence": 0.9,
      "evidenceQuote": "..."
    }}
  ],
  "relationships": [
    {{
      "source_id": "obligation:{clause.contractId}:<short_hash>:<slug>",
      "target_id": "party:{clause.contractId}:<short_hash>:<slug>",
      "type": "OWED_BY",
      "properties": {{}},
      "confidence": 0.9,
      "evidenceQuote": "..."
    }}
  ]
}}
"""

    def extract_from_clause(self, clause: KGNode) -> LegalExtractionResult:
        prompt = self.build_prompt(clause)

        response = self.client.chat.completions.create(
            model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You extract legal contract knowledge graphs as strict JSON.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        data = self.repair_ids(data, clause)

        return LegalExtractionResult(**data)

    def repair_ids(self, data: Dict[str, Any], clause: KGNode) -> Dict[str, Any]:
        id_map = {}

        for ent in data.get("entities", []):
            old_id = ent.get("id")
            ent_type = ent.get("type", "Entity")
            name = ent.get("name", "unknown")

            if (
                not old_id
                or old_id == "unknown"
                or " " in old_id
                or old_id.count(":") < 2
            ):
                new_id = (
                    f"{ent_type.lower()}:"
                    f"{clause.contractId}:"
                    f"{short_hash(clause.kgId + name)}:"
                    f"{slugify(name)}"
                )
                ent["id"] = new_id
                if old_id:
                    id_map[old_id] = new_id

        for rel in data.get("relationships", []):
            if rel.get("source_id") in id_map:
                rel["source_id"] = id_map[rel["source_id"]]
            if rel.get("target_id") in id_map:
                rel["target_id"] = id_map[rel["target_id"]]

        data["source_clause_id"] = clause.kgId
        data["source_clause_title"] = clause.title
        data["source_page_start"] = clause.pageStart
        data["source_page_end"] = clause.pageEnd

        return data
