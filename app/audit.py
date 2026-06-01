import json
from datetime import UTC, datetime
from typing import Any


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
    payload: dict[str, Any] = {
        "severity": "INFO" if success else "WARNING",
        "message": "bigquery_mcp_tool_call",
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": "bigquery_mcp_tool_call",
        "user_email": user_email,
        "tool": tool,
        "project_id": project_id,
        "dataset": dataset,
        "table": table,
        "bytes_processed": bytes_processed,
        "success": success,
        "error": error,
    }
    if extra:
        payload.update(extra)
    return payload


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
