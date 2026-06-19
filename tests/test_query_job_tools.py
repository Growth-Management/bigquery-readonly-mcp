import json

import httpx
import pytest

from app.bigquery_tools import (
    BigQueryApiError,
    TOOL_HANDLERS,
    _bounded_max_results,
    _job_labels,
    _raise_for_status_with_body,
)
from app.config import Settings
from app.mcp import TOOLS
from app.sql_guard import SqlValidationError


def _settings() -> Settings:
    return Settings(
        SESSION_SECRET="test-secret",
        GOOGLE_OAUTH_CLIENT_ID="client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
        MAX_RESULTS=1000,
    )


def test_query_job_tools_are_registered() -> None:
    tool_names = {tool["name"] for tool in TOOLS}

    assert "start_readonly_query_job" in tool_names
    assert "get_query_job_status" in tool_names
    assert "fetch_query_job_results" in tool_names
    assert "cancel_query_job" in tool_names
    assert "run_readonly_query" in tool_names
    assert "dry_run_query" in tool_names
    assert tool_names.issubset(TOOL_HANDLERS.keys())


def test_start_query_job_reuses_readonly_sql_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("BigQuery API must not be called for rejected SQL")

    monkeypatch.setattr("app.bigquery_tools._request_json", fail_if_called)
    monkeypatch.setattr("app.bigquery_tools._post_query", fail_if_called)

    with pytest.raises(SqlValidationError):
        TOOL_HANDLERS["start_readonly_query_job"](
            type("Session", (), {"email": "sinohara@impress.co.jp", "access_token": "token"})(),
            {"project_id": "ice-sh", "sql": "DELETE FROM dataset.table WHERE TRUE"},
            _settings(),
        )


def test_fetch_results_caps_max_results_to_configured_limit() -> None:
    settings = _settings()

    assert _bounded_max_results({"max_results": 5000}, settings) == 1000
    assert _bounded_max_results({"max_results": 0}, settings) == 1
    assert _bounded_max_results({}, settings) == 1000


def test_job_labels_must_be_object() -> None:
    assert _job_labels({"audit_target": "38079", "datamart_id": 123}) == {
        "audit_target": "38079",
        "datamart_id": "123",
    }

    with pytest.raises(ValueError, match="job_labels must be an object"):
        _job_labels(["audit_target"])


def test_bigquery_api_error_preserves_error_result_and_errors() -> None:
    response = httpx.Response(
        400,
        json={
            "error": {
                "code": 400,
                "message": "Resources exceeded during query execution",
                "errors": [{"reason": "resourcesExceeded", "message": "Resources exceeded"}],
            }
        },
        request=httpx.Request("POST", "https://bigquery.googleapis.com/bigquery/v2/projects/ice-sh/jobs"),
    )

    with pytest.raises(BigQueryApiError) as exc_info:
        _raise_for_status_with_body(response)

    payload = json.loads(str(exc_info.value))
    assert payload["status_code"] == 400
    assert payload["errorResult"]["message"] == "Resources exceeded during query execution"
    assert payload["errors"][0]["reason"] == "resourcesExceeded"
