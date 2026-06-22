import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import parse_qs, urlencode

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.mcp import handle_json_rpc
from app.sessions import session_store_from_settings

logging.basicConfig(level=logging.INFO)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
OAUTH_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/bigquery",
]
AUTH_REQUEST_TTL_SECONDS = 600
AUTH_CODE_TTL_SECONDS = 600

auth_requests: dict[str, dict[str, object]] = {}
auth_codes: dict[str, dict[str, object]] = {}

app = FastAPI(title="BigQuery Readonly MCP")


def _prune_oauth_state() -> None:
    now = time.time()
    for key, value in list(auth_requests.items()):
        if float(value["expires_at"]) <= now:
            auth_requests.pop(key, None)
    for key, value in list(auth_codes.items()):
        if float(value["expires_at"]) <= now:
            auth_codes.pop(key, None)


def _verify_pkce(code_verifier: str | None, code_challenge: object, code_challenge_method: object) -> None:
    if not code_challenge:
        return
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing code_verifier")

    method = str(code_challenge_method or "plain")
    if method == "plain":
        calculated = code_verifier
    elif method == "S256":
        digest = hashlib.sha256(code_verifier.encode()).digest()
        calculated = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    else:
        raise HTTPException(status_code=400, detail="Unsupported code_challenge_method")

    if not secrets.compare_digest(calculated, str(code_challenge)):
        raise HTTPException(status_code=400, detail="Invalid code_verifier")


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/oauth-authorization-server")
def oauth_metadata(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    base_url = settings.base_url.rstrip("/")
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["plain", "S256"],
        "scopes_supported": OAUTH_SCOPES,
    }


@app.get("/oauth/authorize")
def oauth_authorize(request: Request, settings: Settings = Depends(get_settings)) -> RedirectResponse:
    _prune_oauth_state()
    google_state = secrets.token_urlsafe(24)
    params = request.query_params
    auth_requests[google_state] = {
        "redirect_uri": params.get("redirect_uri"),
        "client_state": params.get("state"),
        "code_challenge": params.get("code_challenge"),
        "code_challenge_method": params.get("code_challenge_method"),
        "expires_at": time.time() + AUTH_REQUEST_TTL_SECONDS,
    }
    query = urlencode(
        {
            "client_id": settings.oauth_client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(OAUTH_SCOPES),
            "state": google_state,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": params.get("prompt") or "consent select_account",
        }
    )
    redirect = RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}")
    redirect.set_cookie("oauth_state", google_state, httponly=True, secure=True, samesite="lax", max_age=AUTH_REQUEST_TTL_SECONDS)
    return redirect


@app.get("/oauth/callback")
async def oauth_callback(
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _prune_oauth_state()
    auth_request = auth_requests.pop(state, None)
    if auth_request is None and (not oauth_state or not secrets.compare_digest(state, oauth_state)):
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

    redirect_uri = str(auth_request.get("redirect_uri") or "") if auth_request else ""
    if redirect_uri:
        auth_code = secrets.token_urlsafe(32)
        auth_codes[auth_code] = {
            "email": email,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "access_token_expires_in": token_data.get("expires_in"),
            "code_challenge": auth_request.get("code_challenge"),
            "code_challenge_method": auth_request.get("code_challenge_method"),
            "expires_at": time.time() + AUTH_CODE_TTL_SECONDS,
        }
        query: dict[str, str] = {"code": auth_code}
        client_state = auth_request.get("client_state")
        if client_state:
            query["state"] = str(client_state)
        redirect = RedirectResponse(f"{redirect_uri}?{urlencode(query)}")
        redirect.delete_cookie("oauth_state")
        return redirect

    session_id = session_store_from_settings(settings).create(
        email=email,
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        access_token_expires_in=token_data.get("expires_in"),
        ttl_seconds=settings.session_ttl_seconds,
    )
    redirect = RedirectResponse("/health")
    redirect.set_cookie("mcp_session", session_id, httponly=True, secure=True, samesite="lax", max_age=settings.session_ttl_seconds)
    redirect.delete_cookie("oauth_state")
    return redirect


@app.post("/oauth/token")
async def oauth_token(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    _prune_oauth_state()
    form = parse_qs((await request.body()).decode())
    grant_type = (form.get("grant_type") or [""])[0]
    code = (form.get("code") or [""])[0]
    code_verifier = (form.get("code_verifier") or [None])[0]

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")
    auth_code = auth_codes.pop(code, None)
    if not auth_code:
        raise HTTPException(status_code=400, detail="Invalid authorization code")

    _verify_pkce(code_verifier, auth_code.get("code_challenge"), auth_code.get("code_challenge_method"))
    session_id = session_store_from_settings(settings).create(
        email=str(auth_code["email"]),
        access_token=str(auth_code["access_token"]),
        refresh_token=str(auth_code["refresh_token"]) if auth_code.get("refresh_token") else None,
        access_token_expires_in=int(auth_code["access_token_expires_in"]) if auth_code.get("access_token_expires_in") else None,
        ttl_seconds=settings.session_ttl_seconds,
    )
    return {
        "access_token": session_id,
        "token_type": "Bearer",
        "expires_in": settings.session_ttl_seconds,
        "scope": " ".join(OAUTH_SCOPES),
    }


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
    mcp_session: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    session = session_store_from_settings(settings).get(_bearer_token(authorization) or mcp_session)
    if not session:
        raise HTTPException(status_code=401, detail="Login required at /oauth/authorize")
    payload = await request.json()
    return handle_json_rpc(payload, session, settings)
