import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("bigquery_readonly_mcp.audit")


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
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
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
    logger.info("bigquery_mcp_tool_call", extra={"json_fields": payload})
