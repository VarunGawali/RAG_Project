"""
Stage 1: Open-ended domain-framed discovery extraction.

No predefined entity/relationship list is given to the LLM.
The LLM is framed as a legal expert and asked to name what it sees.

Output per clause:
  - raw entity type names + instances
  - raw relationship type names + instances
  - evidence quotes

These raw outputs feed Stage 2 (schema_inducer.py) for clustering
and frequency analysis — NOT Gremlin directly.
"""

import json
import re
import hashlib
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from openai import AzureOpenAI
from app import config
from app.kg.models import KGNode


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------

class DiscoveredEntity(BaseModel):
    id: str
    entity_type: str           # raw name from LLM, e.g. "Cure Period", "Step-In Right"
    name: str
    legal_role: str            # why this is legally significant
    confidence: float = 0.0
    evidence_quote: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class DiscoveredRelationship(BaseModel):
    source_id: str
    target_id: str
    relationship_type: str     # raw name from LLM, e.g. "TRIGGERS", "CAPS_LIABILITY_OF"
    legal_significance: str    # why this connection matters legally
    confidence: float = 0.0
    evidence_quote: Optional[str] = None


class DiscoveryResult(BaseModel):
    source_clause_id: str
    source_clause_title: Optional[str] = None
    contract_id: str
    source_page_start: Optional[int] = None
    source_page_end: Optional[int] = None
    clause_type_hint: Optional[str] = None
    entities: List[DiscoveredEntity] = Field(default_factory=list)
    relationships: List[DiscoveredRelationship] = Field(default_factory=list)
    extractor_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(value: str, max_len: int = 80) -> str:
    value = value or "unknown"
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:max_len] or "unknown"


def short_hash(value: str, length: int = 8) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

DISCOVERY_SYSTEM_PROMPT = """You are a senior legal contract expert and knowledge graph specialist.
Your task is to read a contract clause and identify every legally significant
entity and relationship present in it.

━━━ ENTITY TYPE RULES ━━━

1. NO PREDEFINED LIST — name types based on actual legal meaning in this clause.

2. SINGLE-ROLE TYPES ONLY — each entity_type must describe exactly one legal role.
   ✗ Bad:  "Indemnitor and Contracting Party"  (compound — two roles)
   ✗ Bad:  "Obligor under Insurance Obligations"  (over-qualified — just "Obligor")
   ✓ Good: "Indemnitor", "Indemnitee", "Obligor", "Obligee"

3. PREFERRED CANONICAL FORMS — use these root forms, not verbose paraphrases:
   • Party giving indemnity  → "Indemnitor"   (not "Indemnifying Party")
   • Party receiving indemnity → "Indemnitee"  (not "Indemnified Party")
   • Party bearing a duty   → "Obligor"       (not "Obligated Party" or "Performing Party")
   • Party holding a right  → "Obligee"       (not "Benefiting Party")
   • Party in breach        → "BreachingParty" (not "Defaulting Counterparty")
   • Party not in breach    → "NonBreachingParty"
   • Party giving notice    → "NoticeObligor"
   • Party receiving notice → "NoticeRecipient"

4. ALWAYS SEPARATE OPPOSITE ROLES — for every legal relationship, extract BOTH sides
   as distinct entities with distinct types.
   Example — indemnification clause must produce TWO entities:
     { "entity_type": "Indemnitor", "name": "Contractor" }
     { "entity_type": "Indemnitee", "name": "Owner" }
   Never merge them into one entity or one compound type.

5. PARTY ROLES NOT PARTY NAMES — entity_type is the legal role, not the proper noun.
   ✗ Bad:  entity_type = "Con Edison"
   ✓ Good: entity_type = "ServiceProvider", name = "Con Edison"

━━━ RELATIONSHIP TYPE RULES ━━━

6. DIRECTIONAL VERB PHRASES — relationship_type must read as source → target.
   ✗ Bad:  "Indemnification Obligation"  (unclear direction)
   ✓ Good: "INDEMNIFIES"  (source=Indemnitor, target=Indemnitee)
   ✓ Good: "TRIGGERS_DEFAULT_OF"  (source=Event, target=Party)
   ✓ Good: "CAPS_LIABILITY_OF"  (source=Clause, target=Obligor)

7. SCREAMING_SNAKE_CASE for relationship types — makes them visually distinct
   from entity types in downstream processing.
   Examples: "OBLIGATES", "TERMINATES", "EXCUSES_PERFORMANCE_OF",
             "SURVIVES_TERMINATION_OF", "GRANTS_CURE_PERIOD_TO",
             "ASSIGNS_RIGHT_TO", "REQUIRES_NOTICE_FROM"

8. EXTRACT ONLY WHAT IS EXPLICIT — do not infer relationships not stated in the text.

━━━ CONFIDENCE SCORING ━━━
- 1.0 = explicitly stated in exact words
- 0.8 = clearly implied by the clause structure
- 0.6 = reasonable legal inference from context

Return valid JSON only."""


_FEW_SHOT_EXAMPLE = '''
━━━ EXAMPLE — correct extraction for an indemnification clause ━━━

Clause text:
"Contractor shall defend, indemnify and hold harmless Owner and its officers,
employees and agents from and against any Claims arising out of Contractor's
negligent acts or willful misconduct in performing the Work."

Correct output:
{
  "entities": [
    {
      "id": "ent_contractor",
      "entity_type": "Indemnitor",
      "name": "Contractor",
      "legal_role": "Bears the indemnification obligation; must defend and compensate Owner.",
      "confidence": 1.0,
      "evidence_quote": "Contractor shall defend, indemnify and hold harmless Owner"
    },
    {
      "id": "ent_owner",
      "entity_type": "Indemnitee",
      "name": "Owner",
      "legal_role": "Beneficiary of indemnification; protected against claims from Contractor's misconduct.",
      "confidence": 1.0,
      "evidence_quote": "hold harmless Owner and its officers, employees and agents"
    },
    {
      "id": "ent_claims",
      "entity_type": "IndemnifiableClaim",
      "name": "Claims from negligent acts or willful misconduct",
      "legal_role": "Defines the scope of losses covered by the indemnity obligation.",
      "confidence": 1.0,
      "evidence_quote": "any Claims arising out of Contractor's negligent acts or willful misconduct"
    },
    {
      "id": "ent_trigger",
      "entity_type": "IndemnityTrigger",
      "name": "Negligent acts or willful misconduct in performing Work",
      "legal_role": "The conduct that activates the indemnification obligation.",
      "confidence": 1.0,
      "evidence_quote": "arising out of Contractor's negligent acts or willful misconduct in performing the Work"
    }
  ],
  "relationships": [
    {
      "source_id": "ent_contractor",
      "target_id": "ent_owner",
      "relationship_type": "INDEMNIFIES",
      "legal_significance": "Creates a primary financial protection obligation running from Contractor to Owner.",
      "confidence": 1.0,
      "evidence_quote": "Contractor shall defend, indemnify and hold harmless Owner"
    },
    {
      "source_id": "ent_trigger",
      "target_id": "ent_contractor",
      "relationship_type": "ACTIVATES_INDEMNITY_OBLIGATION_OF",
      "legal_significance": "Connects the triggering conduct to the party bearing the resulting liability.",
      "confidence": 1.0,
      "evidence_quote": "Claims arising out of Contractor's negligent acts or willful misconduct"
    },
    {
      "source_id": "ent_claims",
      "target_id": "ent_contractor",
      "relationship_type": "FALLS_WITHIN_INDEMNITY_SCOPE_OF",
      "legal_significance": "Defines which losses Contractor must cover.",
      "confidence": 1.0,
      "evidence_quote": "any Claims arising out of Contractor's negligent acts"
    }
  ],
  "extractor_notes": "Classic unilateral indemnity running from service provider to client. Scope limited to Contractor's own acts — not absolute."
}

Note what the example does:
- Indemnitor and Indemnitee are SEPARATE entities with OPPOSITE types
- No compound types ("Indemnitor and Contractor" is never used)
- Relationship types are directional verb phrases in SCREAMING_SNAKE_CASE
- The trigger condition is its own entity, not folded into the Indemnitor
━━━ END EXAMPLE ━━━
'''


def build_discovery_prompt(clause: KGNode) -> str:
    return f"""Read the following contract clause and extract all legally significant entities and relationships.
Follow the system prompt rules precisely. Study the example below before extracting.

{_FEW_SHOT_EXAMPLE}

━━━ NOW EXTRACT FROM THIS CLAUSE ━━━

Contract ID: {clause.contractId}
Clause ID: {clause.kgId}
Clause title: {clause.title}
Clause type hint: {clause.clauseTypeHint}
Page: {clause.pageStart}-{clause.pageEnd}

Clause text:
\"\"\"
{clause.text}
\"\"\"

Return JSON in exactly this shape:
{{
  "entities": [
    {{
      "id": "ent_<short_slug>",
      "entity_type": "<single-role legal type — use canonical forms from system prompt>",
      "name": "<the specific instance or value from this clause>",
      "legal_role": "<one sentence: what legal function does this play?>",
      "confidence": 0.0,
      "evidence_quote": "<exact quote from clause text>"
    }}
  ],
  "relationships": [
    {{
      "source_id": "<entity id>",
      "target_id": "<entity id>",
      "relationship_type": "<DIRECTIONAL_VERB in SCREAMING_SNAKE_CASE>",
      "legal_significance": "<one sentence: why does this connection matter legally?>",
      "confidence": 0.0,
      "evidence_quote": "<exact quote from clause text>"
    }}
  ],
  "extractor_notes": "<optional: note anything unusual, ambiguous, or cross-referencing another clause>"
}}"""


class DiscoveryExtractor:
    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )

    def extract_from_clause(self, clause: KGNode) -> DiscoveryResult:
        prompt = build_discovery_prompt(clause)

        response = self.client.chat.completions.create(
            model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": DISCOVERY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        data = self._repair_and_stamp(data, clause)

        return DiscoveryResult(**data)

    def _repair_and_stamp(self, data: Dict[str, Any], clause: KGNode) -> Dict[str, Any]:
        """Stamp clause metadata and fix any missing entity IDs."""
        data["source_clause_id"] = clause.kgId
        data["source_clause_title"] = clause.title
        data["contract_id"] = clause.contractId
        data["source_page_start"] = clause.pageStart
        data["source_page_end"] = clause.pageEnd
        data["clause_type_hint"] = clause.clauseTypeHint

        id_map: Dict[str, str] = {}

        for ent in data.get("entities", []):
            old_id = ent.get("id", "")
            name = ent.get("name", "unknown")
            entity_type = ent.get("entity_type", "Entity")

            if not old_id or " " in old_id or old_id == "unknown":
                new_id = (
                    f"ent_{short_hash(clause.kgId + entity_type + name)}_{slugify(name, 30)}"
                )
                ent["id"] = new_id
                if old_id:
                    id_map[old_id] = new_id

        for rel in data.get("relationships", []):
            if rel.get("source_id") in id_map:
                rel["source_id"] = id_map[rel["source_id"]]
            if rel.get("target_id") in id_map:
                rel["target_id"] = id_map[rel["target_id"]]

        return data