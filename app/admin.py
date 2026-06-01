from typing import Literal

from app.audit import audit_event
from app.firestore_store import FirestoreStore
from app.persistence_models import utc_now
from app.security import hash_google_subject

AdminAction = Literal["disable", "force_reauth", "delete"]


class AdminActionError(ValueError):
    pass


def token_record_id_from_google_sub(google_sub: str) -> str:
    if not google_sub:
        raise AdminActionError("google_sub is required")
    return hash_google_subject(google_sub)


def disable_user_connection(*, store: FirestoreStore, token_record_id: str, reason: str, actor_email: str | None = None) -> dict[str, object]:
    token_record = store.get_token_record(token_record_id)
    if not token_record:
        raise AdminActionError("OAuth token record was not found")
    store.update_token_record(
        token_record_id,
        {
            "status": "disabled",
            "disabled_reason": reason,
            "disabled_at": utc_now(),
        },
    )
    revoked_sessions = store.revoke_mcp_sessions_for_token_record(token_record_id, reason="token_disabled")
    result = {"action": "disable", "token_record_id": token_record_id, "revoked_sessions": revoked_sessions}
    audit_event(
        event_type="oauth_token_admin_action",
        success=True,
        action="disable",
        actor_email=actor_email,
        user_email=token_record.get("user_email"),
        token_record_id=token_record_id,
        revoked_sessions=revoked_sessions,
    )
    return result


def force_user_reauth(*, store: FirestoreStore, token_record_id: str, reason: str, actor_email: str | None = None) -> dict[str, object]:
    token_record = store.get_token_record(token_record_id)
    if not token_record:
        raise AdminActionError("OAuth token record was not found")
    store.update_token_record(
        token_record_id,
        {
            "status": "reauth_required",
            "reauth_required_reason": reason,
            "last_error_class": "admin_force_reauth",
        },
    )
    revoked_sessions = store.revoke_mcp_sessions_for_token_record(token_record_id, reason="force_reauth")
    result = {"action": "force_reauth", "token_record_id": token_record_id, "revoked_sessions": revoked_sessions}
    audit_event(
        event_type="oauth_token_admin_action",
        success=True,
        action="force_reauth",
        actor_email=actor_email,
        user_email=token_record.get("user_email"),
        token_record_id=token_record_id,
        revoked_sessions=revoked_sessions,
    )
    return result


def delete_user_connection(*, store: FirestoreStore, token_record_id: str, reason: str, actor_email: str | None = None) -> dict[str, object]:
    token_record = store.get_token_record(token_record_id)
    if not token_record:
        raise AdminActionError("OAuth token record was not found")
    revoked_sessions = store.revoke_mcp_sessions_for_token_record(token_record_id, reason="token_deleted")
    store.update_token_record(
        token_record_id,
        {
            "status": "deleted",
            "deleted_at": utc_now(),
            "disabled_reason": reason,
        },
    )
    store.delete_token_record(token_record_id)
    result = {"action": "delete", "token_record_id": token_record_id, "revoked_sessions": revoked_sessions}
    audit_event(
        event_type="oauth_token_admin_action",
        success=True,
        action="delete",
        actor_email=actor_email,
        user_email=token_record.get("user_email"),
        token_record_id=token_record_id,
        revoked_sessions=revoked_sessions,
    )
    return result


def run_admin_action(
    *,
    action: AdminAction,
    store: FirestoreStore,
    token_record_id: str,
    reason: str,
    actor_email: str | None = None,
) -> dict[str, object]:
    if action == "disable":
        return disable_user_connection(store=store, token_record_id=token_record_id, reason=reason, actor_email=actor_email)
    if action == "force_reauth":
        return force_user_reauth(store=store, token_record_id=token_record_id, reason=reason, actor_email=actor_email)
    if action == "delete":
        return delete_user_connection(store=store, token_record_id=token_record_id, reason=reason, actor_email=actor_email)
    raise AdminActionError(f"Unsupported admin action: {action}")
