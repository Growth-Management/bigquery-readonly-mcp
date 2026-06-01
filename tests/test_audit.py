import json

from app.audit import REDACTED, audit_event, audit_log, build_audit_event, build_audit_payload


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


def test_build_audit_event_scrubs_secret_fields() -> None:
    payload = build_audit_event(
        event_type="oauth_token_refresh",
        user_email="user@impress.co.jp",
        success=False,
        error_class="invalid_grant",
        extra={
            "refresh_token": "secret-refresh-token",
            "nested": {"access_token": "secret-access-token"},
            "safe_status": "reauth_required",
        },
    )

    assert payload["refresh_token"] == REDACTED
    assert payload["nested"]["access_token"] == REDACTED
    assert payload["safe_status"] == "reauth_required"
    assert "secret-refresh-token" not in json.dumps(payload)
    assert "secret-access-token" not in json.dumps(payload)


def test_audit_log_writes_single_json_line(capsys) -> None:
    audit_log(
        user_email="user@impress.co.jp",
        tool="list_datasets",
        project_id="ice-sh",
        success=True,
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["event_type"] == "bigquery_mcp_tool_call"
    assert payload["tool"] == "list_datasets"
    assert payload["project_id"] == "ice-sh"
    assert payload["success"] is True


def test_audit_event_writes_generic_event(capsys) -> None:
    audit_event(
        event_type="mcp_session_rejected",
        user_email="user@impress.co.jp",
        success=False,
        error_class="expired",
        session_id="raw-session-id",
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["event_type"] == "mcp_session_rejected"
    assert payload["error_class"] == "expired"
    assert payload["session_id"] == REDACTED
