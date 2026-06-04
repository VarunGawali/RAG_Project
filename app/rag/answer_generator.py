"""
Answer generator for Contract360 GraphRAG demo.
"""

import logging

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
"""


class AnswerGenerator:
    def __init__(self):
        self.client = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )

    def generate(self, question: str, context: str, route: str) -> str:
        prompt = f"""
{SYSTEM_PROMPT}

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

        response = self.client.chat.completions.create(
            model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0,
            max_tokens=1200,
            messages=[
                {
                    "role": "system",
                    "content": "You answer contract questions using only provided retrieval context.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
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