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

IMPORTANT RULES:
- Do NOT use a predefined list of entity or relationship types.
- Name entity types and relationship types based on their actual legal meaning.
- Use precise legal terminology (e.g. "Indemnitor", "Cure Period", "Step-In Right",
  "Liquidated Damages Cap", "Regulatory Trigger", "Force Majeure Event").
- For each entity, explain its legal role in one sentence.
- For each relationship, explain why the connection is legally significant.
- Extract only what is explicitly present in the text — do not infer.
- Include exact evidence quotes.
- Return valid JSON only."""


def build_discovery_prompt(clause: KGNode) -> str:
    return f"""Read the following contract clause and extract all legally significant entities and relationships.

Contract ID: {clause.contractId}
Clause ID: {clause.kgId}
Clause title: {clause.title}
Clause type hint: {clause.clauseTypeHint}
Page: {clause.pageStart}-{clause.pageEnd}
Source path: {clause.sourcePath}

Clause text:
\"\"\"
{clause.text}
\"\"\"

Return JSON in exactly this shape:
{{
  "entities": [
    {{
      "id": "ent_<short_slug>",
      "entity_type": "<legal type name — be specific, use legal terminology>",
      "name": "<the specific instance name>",
      "legal_role": "<one sentence: why is this legally significant?>",
      "confidence": 0.0,
      "evidence_quote": "<exact quote from clause text>"
    }}
  ],
  "relationships": [
    {{
      "source_id": "<entity id or clause id>",
      "target_id": "<entity id or clause id>",
      "relationship_type": "<legal relationship name — be specific>",
      "legal_significance": "<one sentence: why does this connection matter legally?>",
      "confidence": 0.0,
      "evidence_quote": "<exact quote from clause text>"
    }}
  ],
  "extractor_notes": "<optional: anything unusual about this clause>"
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