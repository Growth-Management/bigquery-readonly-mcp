from __future__ import annotations

from datetime import datetime
from typing import Any

from google.cloud import firestore

from app.persistence_models import (
    McpSessionRecord,
    OAuthAuthorizationCodeRecord,
    OAuthAuthRequestRecord,
    OAuthTokenRecord,
    utc_now,
)


class FirestoreStore:
    def __init__(
        self,
        *,
        project_id: str,
        oauth_token_collection: str,
        oauth_auth_request_collection: str,
        oauth_authorization_code_collection: str,
        mcp_session_collection: str,
        client: firestore.Client | None = None,
    ) -> None:
        self.client = client or firestore.Client(project=project_id)
        self.oauth_token_collection = oauth_token_collection
        self.oauth_auth_request_collection = oauth_auth_request_collection
        self.oauth_authorization_code_collection = oauth_authorization_code_collection
        self.mcp_session_collection = mcp_session_collection

    def save_auth_request(self, document_id: str, record: OAuthAuthRequestRecord) -> None:
        self.client.collection(self.oauth_auth_request_collection).document(document_id).set(record.to_firestore())

    def consume_auth_request(self, document_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        return self._consume_once(self.oauth_auth_request_collection, document_id, now=now)

    def save_authorization_code(self, document_id: str, record: OAuthAuthorizationCodeRecord) -> None:
        self.client.collection(self.oauth_authorization_code_collection).document(document_id).set(record.to_firestore())

    def consume_authorization_code(self, document_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        return self._consume_once(self.oauth_authorization_code_collection, document_id, now=now)

    def save_mcp_session(self, document_id: str, record: McpSessionRecord) -> None:
        self.client.collection(self.mcp_session_collection).document(document_id).set(record.to_firestore())

    def get_mcp_session(self, document_id: str) -> dict[str, Any] | None:
        document_ref = self.client.collection(self.mcp_session_collection).document(document_id)
        snapshot = document_ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        expires_at = data.get("expires_at")
        if expires_at and expires_at <= utc_now():
            return None
        if data.get("status") != "active":
            return None
        document_ref.update({"last_used_at": utc_now()})
        return data

    def save_token_record(self, document_id: str, record: OAuthTokenRecord) -> None:
        self.client.collection(self.oauth_token_collection).document(document_id).set(record.to_firestore())

    def get_token_record(self, document_id: str) -> dict[str, Any] | None:
        snapshot = self.client.collection(self.oauth_token_collection).document(document_id).get()
        if not snapshot.exists:
            return None
        return snapshot.to_dict() or {}

    def mark_token_status(self, document_id: str, *, status: str, reason_field: str | None = None, reason: str | None = None) -> None:
        updates: dict[str, Any] = {"status": status, "updated_at": utc_now()}
        if reason_field:
            updates[reason_field] = reason
        self.client.collection(self.oauth_token_collection).document(document_id).update(updates)

    def _consume_once(self, collection_name: str, document_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        current_time = now or utc_now()
        document_ref = self.client.collection(collection_name).document(document_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def consume(transaction: firestore.Transaction) -> dict[str, Any] | None:
            snapshot = document_ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            expires_at = data.get("expires_at")
            if expires_at and expires_at <= current_time:
                return None
            if data.get("consumed_at") is not None:
                return None
            transaction.update(document_ref, {"consumed_at": current_time})
            data["consumed_at"] = current_time
            return data

        return consume(transaction)
