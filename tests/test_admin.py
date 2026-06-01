import pytest

from app.admin import AdminActionError, delete_user_connection, disable_user_connection, force_user_reauth, token_record_id_from_google_sub
from app.security import hash_google_subject


class FakeStore:
    def __init__(self) -> None:
        self.token_record = {"user_email": "user@impress.co.jp"}
        self.updates = []
        self.deleted = []
        self.revocations = []

    def get_token_record(self, token_record_id):
        return self.token_record

    def update_token_record(self, token_record_id, updates):
        self.updates.append({"token_record_id": token_record_id, "updates": updates})

    def revoke_mcp_sessions_for_token_record(self, token_record_id, *, reason):
        self.revocations.append({"token_record_id": token_record_id, "reason": reason})
        return 2

    def delete_token_record(self, token_record_id):
        self.deleted.append(token_record_id)


def test_token_record_id_from_google_sub_hashes_subject() -> None:
    assert token_record_id_from_google_sub("google-sub") == hash_google_subject("google-sub")


def test_token_record_id_from_google_sub_requires_value() -> None:
    with pytest.raises(AdminActionError):
        token_record_id_from_google_sub("")


def test_disable_user_connection_marks_token_disabled_and_revokes_sessions() -> None:
    store = FakeStore()

    result = disable_user_connection(store=store, token_record_id="token-doc", reason="left company", actor_email="admin@impress.co.jp")

    assert result == {"action": "disable", "token_record_id": "token-doc", "revoked_sessions": 2}
    assert store.updates[0]["token_record_id"] == "token-doc"
    assert store.updates[0]["updates"]["status"] == "disabled"
    assert store.updates[0]["updates"]["disabled_reason"] == "left company"
    assert store.revocations == [{"token_record_id": "token-doc", "reason": "token_disabled"}]


def test_force_user_reauth_marks_token_and_revokes_sessions() -> None:
    store = FakeStore()

    result = force_user_reauth(store=store, token_record_id="token-doc", reason="scope review", actor_email="admin@impress.co.jp")

    assert result == {"action": "force_reauth", "token_record_id": "token-doc", "revoked_sessions": 2}
    assert store.updates[0]["updates"]["status"] == "reauth_required"
    assert store.updates[0]["updates"]["reauth_required_reason"] == "scope review"
    assert store.updates[0]["updates"]["last_error_class"] == "admin_force_reauth"
    assert store.revocations == [{"token_record_id": "token-doc", "reason": "force_reauth"}]


def test_delete_user_connection_marks_deleted_revokes_sessions_and_deletes_record() -> None:
    store = FakeStore()

    result = delete_user_connection(store=store, token_record_id="token-doc", reason="user request", actor_email="admin@impress.co.jp")

    assert result == {"action": "delete", "token_record_id": "token-doc", "revoked_sessions": 2}
    assert store.revocations == [{"token_record_id": "token-doc", "reason": "token_deleted"}]
    assert store.updates[0]["updates"]["status"] == "deleted"
    assert store.updates[0]["updates"]["disabled_reason"] == "user request"
    assert store.deleted == ["token-doc"]


def test_admin_action_requires_existing_token_record() -> None:
    store = FakeStore()
    store.token_record = None

    with pytest.raises(AdminActionError):
        disable_user_connection(store=store, token_record_id="missing", reason="reason")
