import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.mcp import handle_json_rpc
from app.sessions import session_store

logging.basicConfig(level=logging.INFO)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
OAUTH_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/bigquery.readonly",
]

app = FastAPI(title="BigQuery Readonly MCP")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/oauth-authorization-server")
def oauth_metadata(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    return {
        "issuer": settings.base_url.rstrip("/"),
        "authorization_endpoint": f"{settings.base_url.rstrip('/')}/oauth/authorize",
        "token_endpoint": GOOGLE_TOKEN_URL,
        "response_types_supported": ["code"],
        "scopes_supported": OAUTH_SCOPES,
    }


@app.get("/oauth/authorize")
def oauth_authorize(response: Response, settings: Settings = Depends(get_settings)) -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    response.set_cookie("oauth_state", state, httponly=True, secure=True, samesite="lax", max_age=600)
    query = urlencode(
        {
            "client_id": settings.oauth_client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(OAUTH_SCOPES),
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    redirect = RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}")
    redirect.set_cookie("oauth_state", state, httponly=True, secure=True, samesite="lax", max_age=600)
    return redirect


@app.get("/oauth/callback")
async def oauth_callback(
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if not oauth_state or not secrets.compare_digest(state, oauth_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
                "redirect_uri": settings.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()

    email = userinfo.get("email")
    if not email or not email.endswith(f"@{settings.allowed_domain}"):
        raise HTTPException(status_code=403, detail="Email domain is not allowed")

    session_id = session_store.create(
        email=email,
        access_token=token_data["access_token"],
        ttl_seconds=settings.session_ttl_seconds,
    )
    redirect = RedirectResponse("/healthz")
    redirect.set_cookie("mcp_session", session_id, httponly=True, secure=True, samesite="lax", max_age=settings.session_ttl_seconds)
    redirect.delete_cookie("oauth_state")
    return redirect


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    mcp_session: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    session = session_store.get(mcp_session)
    if not session:
        raise HTTPException(status_code=401, detail="Login required at /oauth/authorize")
    payload = await request.json()
    return handle_json_rpc(payload, session, settings)
