"""
SessionStore — Azure Table Storage CRUD for ExamSession.

Environment variables required:
    AZURE_STORAGE_CONNECTION_STRING
    AZURE_TABLE_NAME  (default: ExamSessions)
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

TABLE_NAME = os.getenv("AZURE_TABLE_NAME", "ExamSessions")

# JSON-serialized list fields stored as strings in Table Storage
_LIST_FIELDS = ("clo_list", "plo_list", "materials_urls", "questions")


@dataclass
class ExamSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    syllabus_url: str = ""
    clo_list: List[str] = field(default_factory=list)
    plo_list: List[str] = field(default_factory=list)
    materials_urls: List[str] = field(default_factory=list)
    questions: List[dict] = field(default_factory=list)
    moderation_form_url: str = ""
    formatted_exam_url: str = ""
    compliance_score: float = 0.0


class SessionStore:
    """Azure Table Storage CRUD for ExamSession."""

    def __init__(self) -> None:
        self._connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    def _get_client(self):
        from azure.data.tables import TableServiceClient

        service = TableServiceClient.from_connection_string(self._connection_string)
        return service.get_table_client(TABLE_NAME)

    def _to_entity(self, session: ExamSession) -> dict:
        entity = asdict(session)
        entity["PartitionKey"] = session.session_id
        entity["RowKey"] = session.session_id
        for f in _LIST_FIELDS:
            entity[f] = json.dumps(entity[f])
        return entity

    def _from_entity(self, entity: dict) -> ExamSession:
        data = dict(entity)
        data.pop("PartitionKey", None)
        data.pop("RowKey", None)
        data.pop("Timestamp", None)
        data.pop("etag", None)
        for f in _LIST_FIELDS:
            if f in data and isinstance(data[f], str):
                data[f] = json.loads(data[f])
        return ExamSession(**{k: v for k, v in data.items() if k in ExamSession.__dataclass_fields__})

    def create_session(self) -> ExamSession:
        """Create a new ExamSession and persist it."""
        session = ExamSession()
        client = self._get_client()
        client.create_entity(self._to_entity(session))
        logger.info("Created session %s", session.session_id)
        return session

    def get_session(self, session_id: str) -> Optional[ExamSession]:
        """Retrieve a session by ID. Returns None if not found."""
        client = self._get_client()
        try:
            entity = client.get_entity(partition_key=session_id, row_key=session_id)
            return self._from_entity(entity)
        except Exception:
            logger.warning("Session not found: %s", session_id)
            return None

    def update_session(self, session: ExamSession) -> None:
        """Upsert (merge) session fields into Table Storage."""
        client = self._get_client()
        client.upsert_entity(self._to_entity(session))
        logger.info("Updated session %s", session.session_id)

    def get_or_create(self, session_id: Optional[str] = None) -> ExamSession:
        """Get existing session or create a new one."""
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session
        return self.create_session()
