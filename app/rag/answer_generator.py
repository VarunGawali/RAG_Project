"""
Answer generator for Contract360 GraphRAG demo.
"""

import logging
from typing import List, Dict, Optional

from openai import AzureOpenAI

from app import config


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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
- Use clean professional formatting.
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
    ) -> str:
        """
        Generate an answer.

        chat_history: list of {"role": "user"|"assistant", "content": "..."}
                      representing prior turns in this session.
        active_contract_ids: the contracts in scope for this query. Injected
                      as an explicit scope header so the model knows exactly
                      which documents it is drawing from.
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
ANSWER
============================================================
"""

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]

        # Inject prior turns so the model can resolve follow-up references
        if chat_history:
            messages.extend(chat_history)

        messages.append({"role": "user", "content": current_prompt})

        response = self.client.chat.completions.create(
            model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0,
            max_tokens=1200,
            messages=messages,
        )

        return response.choices[0].message.content


if __name__ == "__main__":
    generator = AnswerGenerator()

    answer = generator.generate(
        question="What obligations does Con Edison have?",
        route="test",
        context="""
Fact 1:
Name: Notify Power Authority within five business days of new or removed chemicals
Evidence: Con Edison shall notify the Power Authority within five (5) business days...
Source clause: 12.4 Community Right to Know
Pages: 34-35
""",
    )

    print(answer)