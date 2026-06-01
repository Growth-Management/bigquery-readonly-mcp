import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

DANGEROUS_AUDIT_KEYS = {
    "access_token",
    "refresh_token",
    "authorization_code",
    "code",
    "code_verifier",
    "client_secret",
    "bearer_token",
    "session_id",
    "mcp_session",
    "ciphertext",
    "plaintext",
}
REDACTED = "[REDACTED]"


def _scrub_for_audit(value: Any) -> Any:
    if isinstance(value, Mapping):
        scrubbed: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in DANGEROUS_AUDIT_KEYS:
                scrubbed[key_text] = REDACTED
            else:
                scrubbed[key_text] = _scrub_for_audit(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub_for_audit(item) for item in value]
    if isinstance(value, tuple):
        return [_scrub_for_audit(item) for item in value]
    return value


def _default_severity(success: bool) -> str:
    return "INFO" if success else "WARNING"


def build_audit_event(
    *,
    event_type: str,
    success: bool,
    severity: str | None = None,
    message: str | None = None,
    error: str | None = None,
    error_class: str | None = None,
    extra: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "severity": severity or _default_severity(success),
        "message": message or event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "success": success,
        "error_class": error_class,
        "error": error,
    }
    payload.update(fields)
    if extra:
        payload.update(extra)
    return _scrub_for_audit(payload)


def audit_event(
    *,
    event_type: str,
    success: bool,
    severity: str | None = None,
    message: str | None = None,
    error: str | None = None,
    error_class: str | None = None,
    extra: dict[str, Any] | None = None,
    **fields: Any,
) -> None:
    payload = build_audit_event(
        event_type=event_type,
        success=success,
        severity=severity,
        message=message,
        error=error,
        error_class=error_class,
        extra=extra,
        **fields,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def build_audit_payload(
    *,
    user_email: str | None,
    tool: str,
    project_id: str | None,
    dataset: str | None = None,
    table: str | None = None,
    bytes_processed: int | None = None,
    success: bool,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_audit_event(
        event_type="bigquery_mcp_tool_call",
        message="bigquery_mcp_tool_call",
        user_email=user_email,
        tool=tool,
        project_id=project_id,
        dataset=dataset,
        table=table,
        bytes_processed=bytes_processed,
        success=success,
        error=error,
        extra=extra,
    )


def audit_log(
    *,
    user_email: str | None,
    tool: str,
    project_id: str | None,
    dataset: str | None = None,
    table: str | None = None,
    bytes_processed: int | None = None,
    success: bool,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = build_audit_payload(
        user_email=user_email,
        tool=tool,
        project_id=project_id,
        dataset=dataset,
        table=table,
        bytes_processed=bytes_processed,
        success=success,
        error=error,
        extra=extra,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
