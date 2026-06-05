"""
Cosmos DB NoSQL client for chat session persistence.

Container schema (partition key = /userId):
{
  "id":             <sessionId>,
  "userId":         <str>,
  "title":          <str>,
  "contractFilter": <str | null>,
  "createdAt":      <ISO-8601>,
  "updatedAt":      <ISO-8601>,
  "messages": [
    {
      "id":        <str>,
      "role":      "user" | "assistant",
      "content":   <str>,
      "timestamp": <ISO-8601>,
      "route":     <str | null>,
      "sources":   <list | null>
    },
    ...
  ]
}
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from azure.cosmos import CosmosClient, PartitionKey, exceptions

from app import config

logger = logging.getLogger(__name__)

_CONTAINER_NAME = "chat_sessions"


class CosmosChatStore:
    """Thin wrapper around Cosmos DB NoSQL for chat sessions."""

    def __init__(self):
        self._client = CosmosClient(
            url=config.COSMOS_NOSQL_ENDPOINT,
            credential=config.COSMOS_NOSQL_KEY,
        )
        self._db = self._client.get_database_client(config.COSMOS_NOSQL_DATABASE)
        self._container = self._db.get_container_client(_CONTAINER_NAME)

    # ------------------------------------------------------------------
    # One-time setup (idempotent)
    # ------------------------------------------------------------------

    def ensure_container(self) -> None:
        """Create database and container if they don't already exist."""
        db = self._client.create_database_if_not_exists(config.COSMOS_NOSQL_DATABASE)
        db.create_container_if_not_exists(
            id=_CONTAINER_NAME,
            partition_key=PartitionKey(path="/userId"),
            offer_throughput=400,
        )
        self._db = db
        self._container = db.get_container_client(_CONTAINER_NAME)
        logger.info("Cosmos container '%s' ready.", _CONTAINER_NAME)

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def create_session(
        self,
        user_id: str,
        title: str = "New Conversation",
        contract_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _now()
        session: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "userId": user_id,
            "title": title,
            "contractFilter": contract_filter,
            "createdAt": now,
            "updatedAt": now,
            "messages": [],
        }
        self._container.create_item(body=session)
        return session

    def get_session(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._container.read_item(item=session_id, partition_key=user_id)
        except exceptions.CosmosResourceNotFoundError:
            return None

    def list_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        query = (
            "SELECT c.id, c.title, c.contractFilter, c.createdAt, c.updatedAt, "
            "c.previewText "
            "FROM c WHERE c.userId = @uid "
            "ORDER BY c.updatedAt DESC"
        )
        params = [{"name": "@uid", "value": user_id}]
        return list(
            self._container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=False,
            )
        )

    def get_messages(self, session_id: str, user_id: str) -> List[Dict[str, Any]]:
        session = self.get_session(session_id, user_id)
        if session is None:
            return []
        return session.get("messages", [])

    def append_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        route: Optional[str] = None,
        sources: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Append a single message and update the session's updatedAt + title."""
        session = self.get_session(session_id, user_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found for user {user_id}")

        msg: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": _now(),
            "route": route,
            "sources": sources or [],
        }

        messages: list = session.get("messages", [])
        messages.append(msg)
        session["messages"] = messages
        session["updatedAt"] = _now()

        # Auto-title: use first user message (truncated)
        if role == "user" and session.get("title") == "New Conversation":
            session["title"] = content[:72] + ("…" if len(content) > 72 else "")

        # Keep a short preview for the sidebar
        if role == "assistant":
            session["previewText"] = content[:120] + ("…" if len(content) > 120 else "")

        self._container.replace_item(item=session_id, body=session)
        return msg

    def update_title(self, session_id: str, user_id: str, title: str) -> None:
        session = self.get_session(session_id, user_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found for user {user_id}")
        session["title"] = title
        session["updatedAt"] = _now()
        self._container.replace_item(item=session_id, body=session)

    def delete_session(self, session_id: str, user_id: str) -> bool:
        try:
            self._container.delete_item(item=session_id, partition_key=user_id)
            return True
        except exceptions.CosmosResourceNotFoundError:
            return False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()