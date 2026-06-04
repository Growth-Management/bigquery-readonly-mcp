import pytest

from app import bigquery_tools
from app.bigquery_tools import ProjectNotAllowedError, UserNotAllowedError, call_tool
from app.config import Settings
from app.sessions import UserSession


def make_settings(
    *,
    default_project_id: str = "ice-sh",
    allowed_project_ids: str = "",
    allowed_user_emails: str = "",
) -> Settings:
    return Settings(
        SESSION_SECRET="test-session-secret",
        GOOGLE_OAUTH_CLIENT_ID="test-client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="test-client-secret",
        DEFAULT_PROJECT_ID=default_project_id,
        ALLOWED_PROJECT_IDS=allowed_project_ids,
        ALLOWED_USER_EMAILS=allowed_user_emails,
    )


def make_session(email: str = "sinohara@impress.co.jp") -> UserSession:
    return UserSession(email=email, access_token="test-token", expires_at=9999999999)


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


def test_call_tool_allows_user_when_user_allowlist_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_handler(session: UserSession, args: dict[str, object], settings: Settings) -> dict[str, object]:
        called.append(session.email)
        return {"ok": True}

    monkeypatch.setitem(bigquery_tools.TOOL_HANDLERS, "fake_tool", fake_handler)

    result = call_tool(
        "fake_tool",
        make_session("anyone@impress.co.jp"),
        {"project_id": "ice-sh"},
        make_settings(allowed_user_emails=""),
    )

    assert result == {"ok": True}
    assert called == ["anyone@impress.co.jp"]


def test_call_tool_allows_user_in_allowlist_case_insensitively(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_handler(session: UserSession, args: dict[str, object], settings: Settings) -> dict[str, object]:
        called.append(session.email)
        return {"ok": True}

    monkeypatch.setitem(bigquery_tools.TOOL_HANDLERS, "fake_tool", fake_handler)

    result = call_tool(
        "fake_tool",
        make_session("Sinohara@Impress.Co.Jp"),
        {"project_id": "ice-sh"},
        make_settings(allowed_user_emails="sinohara@impress.co.jp"),
    )

    assert result == {"ok": True}
    assert called == ["Sinohara@Impress.Co.Jp"]


def test_call_tool_rejects_user_outside_allowlist_before_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_handler(session: UserSession, args: dict[str, object], settings: Settings) -> dict[str, object]:
        called.append(session.email)
        return {"ok": True}

    monkeypatch.setitem(bigquery_tools.TOOL_HANDLERS, "fake_tool", fake_handler)

    with pytest.raises(UserNotAllowedError, match="User is not allowed by ALLOWED_USER_EMAILS: other@impress.co.jp"):
        call_tool(
            "fake_tool",
            make_session("other@impress.co.jp"),
            {"project_id": "ice-sh"},
            make_settings(allowed_user_emails="sinohara@impress.co.jp"),
        )

    assert called == []
