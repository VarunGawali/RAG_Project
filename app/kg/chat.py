# phase4_chat.py

"""
GraphRAG legal contract chatbot.

Pipeline:
Question
→ Hybrid retrieval
→ Graph expansion
→ Context assembly
→ LLM reasoning
→ Grounded legal answer

Features:
- graph-aware reasoning
- obligation tracing
- dependency explanation
- hallucination reduction
- provenance-aware grounding
"""

import logging

from config import get_llm
from retriever import (
    graph_rag_retrieve
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ============================================================
# INITIALIZE LLM
# ============================================================

llm = get_llm()

# ============================================================
# PROMPT TEMPLATE
# ============================================================

SYSTEM_PROMPT = """
You are a legal contract analyst.

Use ONLY the provided graph context.

The graph contains:
- legal entities
- obligations
- liabilities
- events
- agreements
- contractual relationships

Reason using the graph relationships.

If obligations depend on conditions,
explain the dependency chain clearly.

When relevant:
- explain triggering events
- explain liability relationships
- explain payment dependencies
- explain contractual responsibilities

Prefer graph-supported reasoning over assumptions.

Always reference:
- entity names
- relationship chains
- graph paths

If the answer is not supported by the graph,
say:

"Not found in provided contract context."

Do not invent legal obligations,
relationships,
or contract clauses.
"""

# ============================================================
# GRAPHRAG CHAT
# ============================================================

def graph_rag_chat(
    question,
    k=4,
    hops=2,
):
    """
    Graph-enhanced legal QA.
    """

    logger.info(
        f"Running GraphRAG chat for: "
        f"{question}"
    )

    # ========================================================
    # RETRIEVE GRAPH CONTEXT
    # ========================================================

    context = graph_rag_retrieve(
        question=question,
        k=k,
        hops=hops,
    )

    # ========================================================
    # BUILD FINAL PROMPT
    # ========================================================

    prompt = f"""
{SYSTEM_PROMPT}

============================================================
GRAPH CONTEXT
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

    # ========================================================
    # LLM INFERENCE
    # ========================================================

    response = llm.invoke(prompt)

    logger.info(
        "GraphRAG response generated"
    )

    return response.content

# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    test_questions = [

        "If the Buyer defaults, what remedies and payment obligations are triggered?",

        "What obligations are associated with force majeure events?",

        "What is the Contractor responsible for?",

        "Which clauses relate to indemnification and liability protection?",

        "What insurance obligations exist in the agreement?",
    ]

    for i, question in enumerate(
        test_questions,
        start=1
    ):

        print("\n")
        print("=" * 90)
        print(f"QUESTION {i}")
        print("=" * 90)

        print("\nUSER QUESTION:\n")
