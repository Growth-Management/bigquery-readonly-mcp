import pytest

from app import bigquery_tools
from app.bigquery_tools import ProjectNotAllowedError, call_tool
from app.config import Settings
from app.sessions import UserSession


def make_settings(*, default_project_id: str = "ice-sh", allowed_project_ids: str = "") -> Settings:
    return Settings(
        SESSION_SECRET="test-session-secret",
        GOOGLE_OAUTH_CLIENT_ID="test-client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="test-client-secret",
        DEFAULT_PROJECT_ID=default_project_id,
        ALLOWED_PROJECT_IDS=allowed_project_ids,
    )


def make_session() -> UserSession:
    return UserSession(email="sinohara@impress.co.jp", access_token="test-token", expires_at=9999999999)


def test_call_tool_allows_project_when_allowlist_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_handler(session: UserSession, args: dict[str, object], settings: Settings) -> dict[str, object]:
        called.append(str(args["project_id"]))
        return {"project_id": args["project_id"], "ok": True}

    monkeypatch.setitem(bigquery_tools.TOOL_HANDLERS, "fake_tool", fake_handler)

    result = call_tool(
        "fake_tool",
        make_session(),
        {"project_id": "any-visible-project"},
        make_settings(allowed_project_ids=""),
    )

    assert result == {"project_id": "any-visible-project", "ok": True}
    assert called == ["any-visible-project"]


def test_call_tool_allows_project_in_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_handler(session: UserSession, args: dict[str, object], settings: Settings) -> dict[str, object]:
        called.append(str(args["project_id"]))
        return {"project_id": args["project_id"], "ok": True}

    monkeypatch.setitem(bigquery_tools.TOOL_HANDLERS, "fake_tool", fake_handler)

    result = call_tool(
        "fake_tool",
        make_session(),
        {"project_id": "ice-sh"},
        make_settings(allowed_project_ids="ice-sh, ice-qb"),
    )

    assert result == {"project_id": "ice-sh", "ok": True}
    assert called == ["ice-sh"]


def test_call_tool_rejects_project_outside_allowlist_before_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_handler(session: UserSession, args: dict[str, object], settings: Settings) -> dict[str, object]:
        called.append(str(args["project_id"]))
        return {"project_id": args["project_id"], "ok": True}

    monkeypatch.setitem(bigquery_tools.TOOL_HANDLERS, "fake_tool", fake_handler)

    with pytest.raises(ProjectNotAllowedError, match="Project is not allowed by ALLOWED_PROJECT_IDS: ice-qb"):
        call_tool(
            "fake_tool",
            make_session(),
            {"project_id": "ice-qb"},
            make_settings(allowed_project_ids="ice-sh"),
        )

    assert called == []


def test_call_tool_checks_default_project_against_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_handler(session: UserSession, args: dict[str, object], settings: Settings) -> dict[str, object]:
        called.append("called")
        return {"ok": True}

    monkeypatch.setitem(bigquery_tools.TOOL_HANDLERS, "fake_tool", fake_handler)

    with pytest.raises(ProjectNotAllowedError, match="Project is not allowed by ALLOWED_PROJECT_IDS: ice-qb"):
        call_tool(
            "fake_tool",
            make_session(),
            {},
            make_settings(default_project_id="ice-qb", allowed_project_ids="ice-sh"),
        )

    assert called == []
