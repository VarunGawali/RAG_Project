"""
Streamlit frontend for Contract360 GraphRAG demo.

Run:
streamlit run streamlit_app.py
"""

from pathlib import Path

import streamlit as st
from app.indexing.search_tester import AzureSearchTester

from app.services.frontend_ingestion_service import (
    ingest_and_upload_to_search,
    sanitize_contract_id,
)
from app.rag.query_service import answer_question


DEFAULT_CONTRACT_ID = "Edison_NYPA_OandM_Contract_1"

@st.cache_data(ttl=60)
def load_contract_ids():
    """
    Load contract IDs from Azure AI Search.
    Cached for 60 seconds.
    """
    try:
        searcher = AzureSearchTester()
        return searcher.list_contract_ids()
    except Exception:
        return []


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Contract360 GraphRAG Demo",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Contract360 GraphRAG Demo")

st.caption(
    "Upload contracts into Azure AI Search and ask questions using "
    "Search, Graph, or Hybrid GraphRAG retrieval."
)


# ============================================================
# SIDEBAR SETTINGS
# ============================================================

with st.sidebar:
    st.header("Settings")

    contract_ids = load_contract_ids()

    # Always include Edison because it is the graph-enabled demo contract.
    unique_contract_ids = []
    for cid in [DEFAULT_CONTRACT_ID] + contract_ids:
        if cid and cid not in unique_contract_ids:
            unique_contract_ids.append(cid)

    contract_options = ["All contracts"] + unique_contract_ids

    # Default should be Edison unless user already selected another contract.
    default_contract = st.session_state.get("contract_id", DEFAULT_CONTRACT_ID)

    if default_contract in contract_options:
        default_index = contract_options.index(default_contract)
    elif DEFAULT_CONTRACT_ID in contract_options:
        default_index = contract_options.index(DEFAULT_CONTRACT_ID)
    else:
        default_index = 0

    selected_contract_label = st.selectbox(
        "Contract",
        options=contract_options,
        index=default_index,
        help=(
            "Use Edison_NYPA_OandM_Contract_1 for the graph-enabled demo. "
            "Use All contracts for search-only questions across all indexed contracts."
        ),
    )

    selected_contract_id = (
        None
        if selected_contract_label == "All contracts"
        else selected_contract_label
    )

    st.session_state["contract_id"] = selected_contract_label

    if selected_contract_id == DEFAULT_CONTRACT_ID:
        st.success("Graph enabled for this contract")
    elif selected_contract_id is None:
        st.info("Searching across all indexed contracts. Graph route disabled.")
    else:
        st.info("Search-only contract. Graph route will fall back to search.")

    top_k = st.slider(
        "Top K retrieval results",
        min_value=2,
        max_value=10,
        value=4,
    )

    route_override = st.selectbox(
        "Route override",
        options=["auto", "search", "graph", "hybrid"],
        index=0,
        help=(
            "Use auto for normal routing. Uploaded PDFs without graph "
            "will automatically fall back to search."
        ),
    )

    show_context = st.checkbox(
        "Show retrieval context",
        value=False,
    )

    if st.button("Refresh contract list"):
        st.cache_data.clear()
        st.session_state["contract_id"] = DEFAULT_CONTRACT_ID
        st.rerun()

# ============================================================
# TABS
# ============================================================

tab_upload, tab_chat, tab_info = st.tabs(
    [
        "📤 Upload & Index",
        "💬 Ask Questions",
        "ℹ️ Demo Info",
    ]
)


# ============================================================
# UPLOAD TAB
# ============================================================

with tab_upload:
    st.subheader("Upload a contract and index it into Azure AI Search")

    st.info(
        "For demo, upload creates tree/chunks/index_docs and uploads them "
        "to Azure AI Search. Cosmos Gremlin graph upsertion is skipped for "
        "uploaded PDFs."
    )

    uploaded_file = st.file_uploader(
        "Upload PDF / TXT / MD",
        type=["pdf", "txt", "md"],
    )

    proposed_contract_id = ""

    if uploaded_file:
        proposed_contract_id = sanitize_contract_id(
            Path(uploaded_file.name).stem
        )

    contract_id_input = st.text_input(
        "Contract ID for uploaded file",
        value=proposed_contract_id,
        help=(
            "This contractId will be used in processed outputs and "
            "Azure AI Search."
        ),
    )

    ensure_index = st.checkbox(
        "Ensure Azure AI Search index exists before upload",
        value=False,
        help=(
            "This calls create_or_update_index(). It does not recreate/delete "
            "the existing index."
        ),
    )

    if st.button("Process and upload to Azure AI Search", type="primary"):
        if not uploaded_file:
            st.error("Please upload a file first.")
        elif not contract_id_input.strip():
            st.error("Please provide a contract ID.")
        else:
            try:
                with st.spinner(
                    "Parsing contract, building tree/chunks, creating embeddings, "
                    "and uploading to Azure AI Search..."
                ):
                    result = ingest_and_upload_to_search(
                        uploaded_file=uploaded_file,
                        contract_id=contract_id_input.strip(),
                        ensure_index=ensure_index,
                    )

                st.session_state["contract_id"] = result["contractId"]
                st.cache_data.clear()

                st.success(
                    f"Uploaded {result['uploadedToAzureSearch']} documents "
                    f"to Azure AI Search for contractId={result['contractId']}"
                )

                st.json(result)

                st.warning(
                    "Graph was not created for this uploaded contract. "
                    "Questions for this uploaded contract will use Azure AI Search "
                    "only until graph upsertion is added."
                )

            except Exception as exc:
                st.exception(exc)


# ============================================================
# CHAT TAB
# ============================================================

SUGGESTED_QUESTIONS = [
"What services are excluded from Con Edison’s O&M responsibilities?",
"Who is responsible for NERC compliance before and after the Compliance Transfer Periods?",
"What environmental reporting obligations exist under the agreement?",
"If environmental contamination is discovered during O&M activities, who must report it, remediate it, and bear the costs?",
"How are waste management responsibilities allocated between the parties?",
"How does the agreement allocate responsibility for construction defects versus operational maintenance?",
"Under what circumstances is Con Edison excused from performance obligations?",
"What risks did the Power Authority assume when requesting early commencement of O&M Services?",
]


with tab_chat:
    st.subheader("Ask a question")

    # Initialize session state BEFORE creating widgets
    if "question_text" not in st.session_state:
        st.session_state["question_text"] = SUGGESTED_QUESTIONS[0]

    if "auto_ask" not in st.session_state:
        st.session_state["auto_ask"] = False

    st.markdown("#### Suggested questions")

    cols = st.columns(2)

    for idx, suggested_question in enumerate(SUGGESTED_QUESTIONS):
        with cols[idx % 2]:
            if st.button(
                suggested_question,
                key=f"suggested_question_{idx}",
                use_container_width=True,
            ):
                st.session_state["question_text"] = suggested_question
                st.session_state["auto_ask"] = True

    question = st.text_area(
        "Question",
        key="question_text",
        height=100,
    )

    ask_clicked = st.button("Ask", type="primary")

    if st.session_state.get("auto_ask"):
        ask_clicked = True
        st.session_state["auto_ask"] = False

    if ask_clicked:
        if not question.strip():
            st.error("Please enter a question.")
        else:
            try:
                with st.spinner("Retrieving context and generating answer..."):
                    result = answer_question(
                        question=question,
                        contract_id=selected_contract_id,
                        top=top_k,
                        route_override=route_override,
                        return_context=show_context,
                    )

                st.markdown("### Route")
                st.write(result["route"])
                st.caption(result["reason"])

                st.markdown("### Answer")
                st.write(result["answer"])

                if show_context:
                    st.markdown("### Retrieval Context")
                    st.text_area(
                        "Context",
                        value=result.get("context", ""),
                        height=500,
                    )

            except Exception as exc:
                st.exception(exc)


# ============================================================
# INFO TAB
# ============================================================

with tab_info:
    st.subheader("Current demo behavior")

    st.markdown(
        """
### Graph-enabled contract

```text
Edison_NYPA_OandM_Contract_1
This contract is graph-enabled for the demo.
Uploaded PDFs are currently search-only until graph ingestion is added.
"""
)