from app.audit import build_audit_payload


def test_build_audit_payload_includes_cloud_logging_fields() -> None:
    payload = build_audit_payload(
        user_email="user@impress.co.jp",
        tool="run_readonly_query",
        project_id="ice-sh",
        dataset="analytics",
        table="events",
        bytes_processed=123,
        success=True,
    )

    assert payload["severity"] == "INFO"
    assert payload["message"] == "bigquery_mcp_tool_call"
    assert payload["event_type"] == "bigquery_mcp_tool_call"
    assert payload["user_email"] == "user@impress.co.jp"
    assert payload["tool"] == "run_readonly_query"
    assert payload["project_id"] == "ice-sh"
    assert payload["dataset"] == "analytics"
    assert payload["table"] == "events"
    assert payload["bytes_processed"] == 123
    assert payload["success"] is True
    assert payload["error"] is None
    assert "timestamp" in payload


def test_build_audit_payload_marks_errors_as_warning() -> None:
    payload = build_audit_payload(
        user_email="user@impress.co.jp",
        tool="run_readonly_query",
        project_id="ice-sh",
        success=False,
        error="Forbidden SQL keyword: DELETE",
    )

    assert payload["severity"] == "WARNING"
    assert payload["success"] is False
    assert payload["error"] == "Forbidden SQL keyword: DELETE"
