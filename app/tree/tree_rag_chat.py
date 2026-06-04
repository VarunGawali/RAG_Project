import os

from dotenv import load_dotenv
from openai import AzureOpenAI

from core.ai_assistant.semantic_retriever import (
    SemanticRetriever
)

from core.ai_assistant.prompt_builder import (
    build_rag_prompt
)

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv(
        "AZURE_OPENAI_API_KEY"
    ),

    api_version=os.getenv(
        "AZURE_OPENAI_API_VERSION"
    ),

    azure_endpoint=os.getenv(
        "AZURE_OPENAI_ENDPOINT"
    )
)

LLM_MODEL = os.getenv(
    "AZURE_OPENAI_LLM_DEPLOYMENT"
)


class SemanticRAGChatAgent:

    def __init__(
        self,
        tree_path=None
    ):

        self.retriever = SemanticRetriever(
            tree_path=tree_path
        )

    # =====================================================
    # ASK
    # =====================================================

    def ask(
        self,
        query: str,
        contract_id: str = None
    ):

        # -----------------------------------------
        # RETRIEVE RELEVANT CHUNKS
        # -----------------------------------------

        retrieved_chunks = self.retriever.retrieve(
            query=query,
            contract_id=contract_id
        )

        # -----------------------------------------
        # BUILD TREE-RAG PROMPT
        # -----------------------------------------

        prompt = build_rag_prompt(
            query=query,
            retrieved_chunks=retrieved_chunks
        )

        # -----------------------------------------
        # GENERATE ANSWER
        # -----------------------------------------

        response = client.chat.completions.create(
            model=LLM_MODEL,

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0
        )

        answer = (
            response
            .choices[0]
            .message
            .content
        )

        # -----------------------------------------
        # BUILD CITATIONS
        # -----------------------------------------

        citations = []

        for chunk in retrieved_chunks:

            score = chunk.get("score", 0)

            if score < 0.65:
                continue

            citations.append({
                "contractId": chunk.get(
                    "contractId"
                ),

                "sectionTitle": chunk.get(
                    "sectionTitle"
                ),

                "clauseTitle": chunk.get(
                    "clauseTitle"
                ),

                "pageStart": chunk.get(
                    "pageStart"
                ),

                "pageEnd": chunk.get(
                    "pageEnd"
                ),

                "score": round(score, 4)
            })

        return {
            "query": query,
            "answer": answer,
            "citations": citations,
            "retrieved_chunks": len(
                retrieved_chunks
            )
        }
