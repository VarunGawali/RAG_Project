"""
Session service — high-level operations used by the API layer.
Keeps the API routes thin and the store logic separate.
"""

from typing import Any, Dict, List, Optional

from app.chat_history.cosmos_chat_store import CosmosChatStore

# How many prior turns to inject into the LLM prompt.
# One "turn" = one user message + one assistant message.
HISTORY_TURNS = 6


class SessionService:
    def __init__(self):
        self._store = CosmosChatStore()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create(
        self,
        user_id: str,
        contract_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._store.create_session(
            user_id=user_id,
            contract_filter=contract_filter,
        )

    def get(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get_session(session_id, user_id)

    def list_all(self, user_id: str) -> List[Dict[str, Any]]:
        return self._store.list_sessions(user_id)

    def delete(self, session_id: str, user_id: str) -> bool:
        return self._store.delete_session(session_id, user_id)

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    def get_history(self, session_id: str, user_id: str) -> List[Dict[str, Any]]:
        return self._store.get_messages(session_id, user_id)

    def save_user_message(
        self,
        session_id: str,
        user_id: str,
        content: str,
    ) -> Dict[str, Any]:
        return self._store.append_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=content,
        )

    def save_assistant_message(
        self,
        session_id: str,
        user_id: str,
        content: str,
        route: Optional[str] = None,
        sources: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        return self._store.append_message(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=content,
            route=route,
            sources=sources,
        )

    # ------------------------------------------------------------------
    # Build LLM-ready history slice
    # ------------------------------------------------------------------

    def build_llm_history(
        self,
        session_id: str,
        user_id: str,
    ) -> List[Dict[str, str]]:
        """
        Return the last HISTORY_TURNS turns as a list of
        {"role": "user"|"assistant", "content": "..."} dicts,
        ready to be prepended in the messages array sent to Azure OpenAI.

        The current (in-flight) user message is NOT included here —
        it is appended by the caller right before the final prompt.
        """
        all_msgs = self._store.get_messages(session_id, user_id)

        # Keep only the tail window (each turn = user + assistant pair)
        tail = all_msgs[-(HISTORY_TURNS * 2):]

        return [
            {"role": m["role"], "content": m["content"]}
            for m in tail
        ]