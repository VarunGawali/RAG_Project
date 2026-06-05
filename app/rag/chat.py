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
from app.rag.hybrid_retriever import (
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

Use ONLY the provided retrieval context. The context may include:
- source clause text from Azure AI Search
- clause metadata such as title, page range, and source path
- structural graph context such as parent section and sibling clauses
- semantic graph facts such as obligations, rights, parties, deadlines, notice periods, and frequencies

Do not use outside knowledge.

When answering:
1. Give a direct answer first.
2. Use graph facts when available.
3. Use source text excerpts as evidence.
4. Include source clause title and page range when available.
5. If the context does not support the answer, say:
   "Not found in provided contract context."

Do not invent legal obligations, parties, deadlines, or clauses.
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

        "If a Breach is not cured, what remedies does the non-Breaching Party have?",

        "What obligations does Con Edison have?",

        "Which obligations have deadlines?",

        "What NERC/CIP-related obligations are present?",

        "What reporting or notice obligations exist?",
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
