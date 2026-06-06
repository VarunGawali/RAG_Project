import json
import re
import hashlib
from typing import Dict, Any

from openai import AzureOpenAI

from app import config
from app.kg.models import KGNode, LegalExtractionResult

LEGAL_NODE_TYPES = [
    # Layer 1 — Universal (all 8 contracts)
    "Obligee",
    "Obligation",             # renamed from Paymentobligation — covers all 33 obligation subtypes
    "NoticeRecipient",
    "Indemnitor",
    "Obligor",
    "Agreement",
    "ForceMajeureEvent",
    "Indemnitee",
    "InsurancePolicy",

    # Layer 2 — Common (50–75% contracts)
    "Breach",
    "Party",
    "CurePeriod",
    "BreachingParty",
    "NonBreachingParty",      # split from BreachingParty
    "EffectiveDate",
    "PerformanceMilestoneDate", # split from EffectiveDate
    "TerminationEvent",
    "ConfidentialInformation",
    "Contract",
    "Dispute",
    "GovernmentalAuthority",
    "Invoice",
    "Notice",
    "ThirdParty",
    "ObligationTrigger",
    "InsuranceCertificate",
    "Claim",
    "Consent",
    "Deliverable",
    "Facility",
    "InterestRate",
    "LegalRequirement",
    "Liability",
    "ReimbursableCost",
    "Service",
    "TerminationRight",
    "Assignee",               # keep separate
    "Assignor",               # split from Assignee
]

LEGAL_RELATIONSHIP_TYPES = [
    # Layer 1 — Universal
    "INDEMNIFIES",
    "CAPS_LIABILITY_OF",
    "GIVES_NOTICE_TO",
    "GRANTS_ACCESS_TO",
    "GRANTS_RIGHT_TO",
    "NOTIFIES",
    "PAYS",
    "PROVIDES_NOTICE_TO",
    "REIMBURSES",
    "TRIGGERS_OBLIGATION_OF",

    # Layer 2 — Common (use the canonical forms from the proposal)
    "APPLIES_TO",
    "OBLIGATES",
    "SURVIVES_TERMINATION_OF",
    "COOPERATES_WITH",
    "DELIVERS",
    "MAINTAINS",
    "MAKES_PAYMENT_TO",
    "PROVIDES",
    "REQUIRES_NOTICE_FROM",
    "LIMITS_INDEMNITY_OBLIGATION_OF",
    "ASSIGNS_RIGHTS_TO",
    "REQUIRES_COMPLIANCE_WITH",
    "BEARS_COSTS_OF",
    "COMPLIES_WITH",
    "NAMES_AS_ADDITIONAL_INSURED",
    "EXCUSES_BREACH_OF",
    "TRIGGERS_CURE_PERIOD_OF",
    "IMPOSES_OBLIGATION_ON",
    "FALLS_WITHIN_INDEMNITY_SCOPE_OF",
    "TERMINATES",
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

Allowed entity types:
{LEGAL_NODE_TYPES}

Allowed relationship types:
{LEGAL_RELATIONSHIP_TYPES}

Rules:
1. Extract only information explicitly supported by the text.
2. Every entity must have a stable id.
3. Every relationship source_id and target_id must refer to extracted entity ids or the source clause id.
4. The source clause id is: {clause.kgId}
5. Include confidence from 0 to 1.
6. Include exact evidence quote where possible.
7. If the clause imposes a duty, create an Obligation.
8. If the clause gives permission or entitlement, create a Right.
9. If the clause forbids conduct, create a Restriction.
10. Extract deadlines, notice periods, frequency, systems, assets, events, and risk signals if present.
11. Do not hallucinate missing parties or dates.
12. Return valid JSON only.
13. For every Obligation, if the obligated party is stated or clearly implied, create a Party entity and an OWED_BY relationship from the Obligation to the Party.
14. For every Obligation, if the beneficiary or recipient party is stated, create a Party entity and an OWED_TO relationship from the Obligation to the Party.
15. If a deadline is present, create a Deadline entity and a HAS_DEADLINE relationship from the Obligation to the Deadline.
16. If a notice period is present, create a NoticePeriod entity and a HAS_NOTICE_PERIOD relationship from the Obligation or Right to the NoticePeriod.
17. If a recurring frequency is present, create a Frequency entity and a HAS_FREQUENCY relationship.
18. If a condition is present, create a Condition entity and a SUBJECT_TO relationship.
19. If an exception is present, create an Exception entity and an EXCEPTS relationship.
20. If a triggering event is present, create an Event entity and a TRIGGERED_BY relationship.
21. Do not create duplicate Party entities within one clause.
22. Prefer normalized party names: "Con Edison", "Power Authority", "Either Party", "Party".
23. Use deterministic IDs based on source clause id and normalized entity name.



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

Return JSON in this exact shape:
{{
  "source_clause_id": "{clause.kgId}",
  "source_clause_title": "{clause.title}",
  "source_page_start": {clause.pageStart},
  "source_page_end": {clause.pageEnd},
  "entities": [
    {{
      "id": "obligation:<contract_id>:<short_slug>",
      "type": "Obligation",
      "name": "...",
      "properties": {{}},
      "confidence": 0.0,
      "evidenceQuote": "..."
    }}
  ],
  "relationships": [
    {{
      "source_id": "{clause.kgId}",
      "target_id": "obligation:<contract_id>:<short_slug>",
      "type": "IMPOSES_OBLIGATION",
      "properties": {{}},
      "confidence": 0.0,
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
                    "content": "You extract legal contract knowledge graphs as strict JSON."
                },
                {
                    "role": "user",
                    "content": prompt
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