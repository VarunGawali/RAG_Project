def build_rag_prompt(
    query: str,
    retrieved_chunks: list
):

    context_parts = []

    seen_nodes = set()

    MAX_CONTEXT_CHARS = 12000

    for chunk in retrieved_chunks:

        # -----------------------------------------
        # MAIN RETRIEVED CHUNK
        # -----------------------------------------

        context_parts.append(
            f"""
==============================
MAIN RETRIEVED CHUNK
==============================

Contract:
{chunk.get("contractId")}

Score:
{round(chunk.get("score", 0), 4)}

Section:
{chunk.get("sectionTitle")}

Clause Type:
{chunk.get("clauseType")}

Text:
{chunk.get("text")}
"""
        )

        # -----------------------------------------
        # HIERARCHICAL CONTEXT
        # -----------------------------------------

        expanded_nodes = chunk.get(
            "contextExpansion",
            []
        )

        for node in expanded_nodes:

            node_id = node.get("nodeId")

            if node_id in seen_nodes:
                continue

            seen_nodes.add(node_id)

            node_text = node.get("text")

            if not node_text:
                continue

            node_type = node.get("nodeType")

            # -----------------------------------------
            # COMPRESS CONTEXT
            # -----------------------------------------

            if node_type == "section":
                compressed_text = node_text[:300]

            elif node_type == "clause":
                compressed_text = node_text[:500]

            else:
                compressed_text = node_text[:200]

            context_parts.append(
                f"""
------------------------------
EXPANDED CONTEXT NODE
------------------------------

Title:
{node.get("title")}

Node Type:
{node_type}

Text:
{compressed_text}
"""
            )

    final_context = "\n\n".join(context_parts)

    # -----------------------------------------
    # TOKEN SAFETY
    # -----------------------------------------

    final_context = final_context[:MAX_CONTEXT_CHARS]

    prompt = f"""
You are a contract intelligence assistant.

Answer ONLY using the provided context.

Use the hierarchical context to understand:
- related clauses
- neighboring obligations
- termination conditions
- notice requirements
- legal dependencies

If the answer is not found, say:
"I could not find relevant information."

Provide a concise legally grounded answer.

CONTEXT:
{final_context}

QUESTION:
{query}

ANSWER:
"""

    return prompt
