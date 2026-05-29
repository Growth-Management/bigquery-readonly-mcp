import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("bigquery_readonly_mcp.audit")


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
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
