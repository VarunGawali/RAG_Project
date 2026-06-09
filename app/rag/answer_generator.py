"""
Answer generator for Contract360.
Returns (answer, follow_up_suggestions) in a single LLM call.
"""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from openai import AzureOpenAI

from app import config


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are a legal contract analyst.

Use ONLY the provided retrieval context. The context may include:
- source clause text from Azure AI Search
- clause metadata such as title, page range, and source path
- structural graph context such as parent section and sibling clauses
- semantic graph facts such as obligations, rights, restrictions, parties, deadlines, notice periods, and frequencies
- evidence quotes extracted from contract clauses

Do not use outside knowledge.

Your job is to produce a concise, user-facing answer, not to dump raw retrieval facts.

When answering:
1. Give a direct answer first.
2. If many facts are present, group them by theme.
3. Do not list more than 8-10 items unless the user explicitly asks for an exhaustive list.
4. For each key point, include source clause title and page range when available.
5. Include short evidence quotes only when helpful.
6. Use graph facts when available, especially owed-by, owed-to, deadlines, rights, and obligations.
7. If the context does not support the answer, say:
   "Not found in provided contract context."

For obligation questions:
- Group obligations by category where possible, such as:
  environmental/reporting, compliance, O&M services, transition, cost/budget, emergency/site access.
- Mention that the graph contains more extracted obligations if only a summarized answer is provided.

Do not invent legal obligations, parties, deadlines, or clauses.

When multiple contracts are in scope:
- Always attribute each fact to its source contract by name.
- Never merge or conflate facts from different contracts without clearly labelling them.
- If contracts differ on the same point, state each contract's position separately.
- Format multi-contract answers with a clear contract heading per section, e.g.:
  **Contract A:**
  - ...
  **Contract B:**
  - ...

Formatting requirements:
- Use clean professional formatting in Markdown.
- CRITICAL: put each numbered item and each bullet on its OWN line with a real
  line break. NEVER write a run-on paragraph with inline "1. ... 2. ... 3.".
  Separate top-level numbered items with a blank line.
- Begin with a 1-2 sentence direct answer, THEN the list.
- Use sequential numbering for top-level lists (1, 2, 3, ...).
- Never restart numbering within the same answer unless starting a clearly new section.
- Use bullet points (-) for supporting details beneath numbered items.
- Keep spacing compact and readable.
- Avoid excessive nesting.
- Prefer concise executive-style summaries over long legal prose.

Example format:

1. Payment Obligations
   - Submit monthly invoices.
   - Provide supporting cost documentation.

2. Compliance Obligations
   - Maintain NERC compliance.
   - Follow environmental reporting requirements.

SOURCE CITATIONS
----------------
- The context may end with a numbered SOURCES list, each item tagged [S1], [S2], ...
- After each factual claim, cite the supporting source inline as [S#]
  (e.g. "Con Edison furnishes O&M services at its discretion [S3].").
- Cite ONLY sources that genuinely support the claim; prefer the single most
  specific one. Do not invent [S#] numbers that are not in the SOURCES list.
- If no SOURCES list is provided, do not add [S#] markers.

OUTPUT FORMAT
-------------
You MUST respond with valid JSON only — no markdown fences, no extra text:
{
  "answer": "<your full answer text here>",
  "follow_up_suggestions": [
    "<follow-up question 1>",
    "<follow-up question 2>",
    "<follow-up question 3>"
  ]
}

For follow_up_suggestions: generate exactly 3 short follow-up questions a user
would naturally ask next, based on the answer content and the contract topic.
Make them specific and actionable — e.g. "What are the deadlines for these obligations?"
not "Tell me more".
"""


class AnswerGenerator:
    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )

    def generate(
        self,
        question: str,
        context: str,
        route: str,
        chat_history: List[Dict[str, str]] | None = None,
        active_contract_ids: Optional[List[str]] = None,
    ) -> Tuple[str, List[str]]:
        """
        Generate an answer and 3 follow-up suggestions in one LLM call.

        Returns (answer: str, follow_up_suggestions: List[str]).
        """
        if active_contract_ids:
            scope_lines = "\n".join(f"  - {cid}" for cid in active_contract_ids)
            scope_header = (
                f"SCOPE — you are answering ONLY from these contracts:\n{scope_lines}\n\n"
                "Every claim in your answer MUST be attributed to one of these contracts. "
                "If a retrieved chunk belongs to a contract not in this list, ignore it.\n"
            )
        else:
            scope_header = "SCOPE — portfolio-wide query (all available contracts).\n"

        current_prompt = f"""
============================================================
QUERY SCOPE
============================================================

{scope_header}
============================================================
ROUTE
============================================================

{route}

============================================================
RETRIEVAL CONTEXT
============================================================

{context}

============================================================
QUESTION
============================================================

{question}

============================================================
ANSWER (JSON only)
============================================================
"""

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": current_prompt})

        response = self.client.chat.completions.create(
            model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0,
            max_tokens=1500,
            messages=messages,
        )

        raw = response.choices[0].message.content or ""
        return _parse_response(raw, question)


def _parse_response(raw: str, fallback_question: str) -> Tuple[str, List[str]]:
    """Parse JSON response; gracefully degrade if malformed."""
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
        answer = data.get("answer") or cleaned
        suggestions = data.get("follow_up_suggestions") or []
        if isinstance(suggestions, list):
            suggestions = [s for s in suggestions if isinstance(s, str)][:3]
        else:
            suggestions = []
        return answer, suggestions
    except (json.JSONDecodeError, AttributeError):
        # LLM didn't return JSON — treat entire response as the answer
        logger.warning("AnswerGenerator returned non-JSON; using raw text as answer.")
        return raw.strip(), []
