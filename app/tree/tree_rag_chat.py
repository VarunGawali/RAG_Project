"""
TreeRAG chat agent.

Loads the contract tree from Azure Blob Storage via SemanticRetriever,
runs vector search, expands hierarchical context, and generates an answer
through Azure OpenAI.

This module is self-contained — it can be used directly or invoked
via the query_service tree route.
"""

import logging
from typing import Dict, List, Optional

from openai import AzureOpenAI

from app import config
from app.tree.semantic_retriever import SemanticRetriever
from app.services.prompt_builder import build_rag_prompt

logger = logging.getLogger(__name__)


class SemanticRAGChatAgent:
    """
    End-to-end TreeRAG agent: retrieve → expand → generate.

    The tree for a contract is loaded from Azure Blob Storage on first
    use and cached in memory for subsequent queries.
    """

    def __init__(self, contract_id: Optional[str] = None):
        self._contract_id = contract_id
        self._retriever = SemanticRetriever(contract_id=contract_id)
        self._llm = AzureOpenAI(
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(
        self,
        query: str,
        top_k: int = 5,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict:
        """
        Retrieve chunks, expand context, generate an answer.

        Returns
        -------
        {
          "query":             str,
          "answer":            str,
          "citations":         list[dict],
          "retrieved_chunks":  int,
          "context_string":    str,   # formatted context passed to LLM
        }
        """
        retrieved_chunks = self._retriever.retrieve(
            query=query,
            top_k=top_k,
            contract_id=self._contract_id,
        )

        context_string = build_rag_prompt(
            query=query,
            retrieved_chunks=retrieved_chunks,
        )

        answer = self._generate(context_string, query, chat_history)

        citations = [
            {
                "contractId":   c.get("contractId"),
                "sectionTitle": c.get("sectionTitle"),
                "clauseTitle":  c.get("clauseTitle"),
                "pageStart":    c.get("pageStart"),
                "pageEnd":      c.get("pageEnd"),
                "score":        round(c.get("score") or 0, 4),
            }
            for c in retrieved_chunks
            if (c.get("score") or 0) >= 0.65
        ]

        return {
            "query":            query,
            "answer":           answer,
            "citations":        citations,
            "retrieved_chunks": len(retrieved_chunks),
            "context_string":   context_string,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate(
        self,
        context_prompt: str,
        query: str,
        chat_history: Optional[List[Dict[str, str]]],
    ) -> str:
        """Call Azure OpenAI with optional chat history prepended."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a contract intelligence assistant. "
                    "Answer ONLY using the provided retrieval context. "
                    "If the answer is not in the context, say so."
                ),
            }
        ]

        if chat_history:
            messages.extend(chat_history)

        messages.append({"role": "user", "content": context_prompt})

        response = self._llm.chat.completions.create(
            model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=messages,
            temperature=0,
            max_tokens=1200,
        )

        return response.choices[0].message.content