import base64
import hashlib
import logging
import secrets
from urllib.parse import parse_qs, urlencode

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.audit import audit_event
from app.config import Settings, get_settings
from app.mcp import handle_json_rpc
from app.oauth_sessions import PersistentSessionError, create_persistent_mcp_session, resolve_persistent_user_session
from app.persistence import get_store, get_token_cipher
from app.persistence_models import OAuthAuthorizationCodeRecord, OAuthAuthRequestRecord, OAuthTokenRecord, expires_in
from app.security import hash_google_subject, oauth_auth_request_id, oauth_authorization_code_id, token_aad
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


def _scopes_from_token_response(token_data: dict[str, object]) -> list[str]:
    scope_text = str(token_data.get("scope") or "")
    return scope_text.split() if scope_text else OAUTH_SCOPES


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
    google_state = secrets.token_urlsafe(24)
    params = request.query_params
    store = get_store()
    document_id = oauth_auth_request_id(google_state, settings.effective_token_hash_secret)
    auth_request = OAuthAuthRequestRecord(
        google_state_hash=document_id,
        client_redirect_uri=params.get("redirect_uri"),
        client_state=params.get("state"),
        code_challenge=params.get("code_challenge"),
        code_challenge_method=params.get("code_challenge_method"),
        requested_scopes=OAUTH_SCOPES,
        force_consent=params.get("prompt") == "consent",
        expires_at=expires_in(settings.oauth_state_ttl_seconds),
    )
    store.save_auth_request(document_id, auth_request)
    audit_event(event_type="oauth_auth_request_created", success=True, source="chatgpt_mcp", oauth_state_hash=document_id)

    prompt = "consent select_account" if auth_request.force_consent else "select_account"
    query = urlencode(
        {
            "client_id": settings.oauth_client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": " ".join(OAUTH_SCOPES),
            "state": google_state,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": prompt,
        }
    )
    redirect = RedirectResponse(f"{GOOGLE_AUTH_URL}?{query}")
    redirect.set_cookie("oauth_state", google_state, httponly=True, secure=True, samesite="lax", max_age=settings.oauth_state_ttl_seconds)
    return redirect


@app.get("/oauth/callback")
async def oauth_callback(
    code: str,
    state: str,
    oauth_state: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    store = get_store()
    state_document_id = oauth_auth_request_id(state, settings.effective_token_hash_secret)
    auth_request = store.consume_auth_request(state_document_id)
    if auth_request is None:
        audit_event(event_type="oauth_auth_request_failed", success=False, error_class="invalid_state", oauth_state_hash=state_document_id)
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    if oauth_state and not secrets.compare_digest(state, oauth_state):
        audit_event(
            event_type="oauth_auth_request_failed",
            success=False,
            error_class="cookie_state_mismatch",
            oauth_state_hash=state_document_id,
        )
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    audit_event(event_type="oauth_auth_request_consumed", success=True, oauth_state_hash=state_document_id)

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
    google_sub = userinfo.get("sub")
    if not email or not str(email).endswith(f"@{settings.allowed_domain}"):
        audit_event(
            event_type="oauth_domain_rejected",
            user_email=str(email) if email else None,
            success=False,
            error_class="domain_mismatch",
            allowed_domain=settings.allowed_domain,
        )
        raise HTTPException(status_code=403, detail="Email domain is not allowed")
    if not google_sub:
        audit_event(event_type="oauth_authorization_code_failed", user_email=str(email), success=False, error_class="missing_google_sub")
        raise HTTPException(status_code=400, detail="Google user subject is required")

    token_record_id = hash_google_subject(str(google_sub))
    existing_token_record = store.get_token_record(token_record_id) or {}
    aad = token_aad(document_id=token_record_id, google_sub=str(google_sub))
    cipher = get_token_cipher()
    encrypted_access_token = cipher.encrypt(str(token_data["access_token"]), aad=aad)
    refresh_token = token_data.get("refresh_token")
    encrypted_refresh_token = cipher.encrypt(str(refresh_token), aad=aad) if refresh_token else None
    refresh_token_ciphertext = encrypted_refresh_token.ciphertext if encrypted_refresh_token else existing_token_record.get("refresh_token_ciphertext")
    refresh_token_kms_key_name = encrypted_refresh_token.kms_key_name if encrypted_refresh_token else existing_token_record.get("refresh_token_kms_key_name")
    scopes = _scopes_from_token_response(token_data)
    store.save_token_record(
        token_record_id,
        OAuthTokenRecord(
            user_email=str(email),
            google_sub=str(google_sub),
            allowed_domain=settings.allowed_domain,
            scopes=scopes,
            refresh_token_ciphertext=refresh_token_ciphertext,
            refresh_token_kms_key_name=refresh_token_kms_key_name,
            access_token_ciphertext=encrypted_access_token.ciphertext,
            access_token_expires_at=expires_in(int(token_data.get("expires_in") or 3600)),
        ),
    )
    audit_event(event_type="oauth_token_record_created", user_email=str(email), google_sub_hash=token_record_id, success=True)

    redirect_uri = str(auth_request.get("client_redirect_uri") or "")
    if redirect_uri:
        auth_code = secrets.token_urlsafe(32)
        auth_code_id = oauth_authorization_code_id(auth_code, settings.effective_token_hash_secret)
        store.save_authorization_code(
            auth_code_id,
            OAuthAuthorizationCodeRecord(
                auth_code_hash=auth_code_id,
                user_token_record_id=token_record_id,
                user_email=str(email),
                google_sub=str(google_sub),
                code_challenge=auth_request.get("code_challenge"),
                code_challenge_method=auth_request.get("code_challenge_method"),
                scopes=scopes,
                expires_at=expires_in(settings.oauth_code_ttl_seconds),
                client_redirect_uri=redirect_uri,
                client_state=auth_request.get("client_state"),
            ),
        )
        audit_event(event_type="oauth_authorization_code_created", user_email=str(email), google_sub_hash=token_record_id, success=True)
        query: dict[str, str] = {"code": auth_code}
        client_state = auth_request.get("client_state")
        if client_state:
            query["state"] = str(client_state)
        redirect = RedirectResponse(f"{redirect_uri}?{urlencode(query)}")
        redirect.delete_cookie("oauth_state")
        return redirect

    session_id = session_store.create(
        email=str(email),
        access_token=str(token_data["access_token"]),
        ttl_seconds=settings.session_ttl_seconds,
    )
    redirect = RedirectResponse("/health")
    redirect.set_cookie("mcp_session", session_id, httponly=True, secure=True, samesite="lax", max_age=settings.session_ttl_seconds)
    redirect.delete_cookie("oauth_state")
    return redirect


@app.post("/oauth/token")
async def oauth_token(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    form = parse_qs((await request.body()).decode())
    grant_type = (form.get("grant_type") or [""])[0]
    code = (form.get("code") or [""])[0]
    code_verifier = (form.get("code_verifier") or [None])[0]

    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="Unsupported grant_type")
    auth_code_id = oauth_authorization_code_id(code, settings.effective_token_hash_secret)
    auth_code = get_store().consume_authorization_code(auth_code_id)
    if not auth_code:
        audit_event(event_type="oauth_authorization_code_failed", success=False, error_class="invalid_authorization_code")
        raise HTTPException(status_code=400, detail="Invalid authorization code")

    _verify_pkce(code_verifier, auth_code.get("code_challenge"), auth_code.get("code_challenge_method"))
    token_record = get_store().get_token_record(str(auth_code["user_token_record_id"]))
    if not token_record or not token_record.get("access_token_ciphertext"):
        audit_event(
            event_type="oauth_authorization_code_failed",
            user_email=str(auth_code.get("user_email")),
            success=False,
            error_class="missing_token_record",
        )
        raise HTTPException(status_code=401, detail="Reauthentication required at /oauth/authorize")

    token_response = create_persistent_mcp_session(
        store=get_store(),
        settings=settings,
        user_token_record_id=str(auth_code["user_token_record_id"]),
        user_email=str(auth_code["user_email"]),
        google_sub=str(auth_code["google_sub"]),
        scopes=list(auth_code.get("scopes") or OAUTH_SCOPES),
    )
    audit_event(event_type="oauth_authorization_code_consumed", user_email=str(auth_code["user_email"]), success=True)
    audit_event(event_type="mcp_session_created", user_email=str(auth_code["user_email"]), success=True)
    return token_response


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
    mcp_session: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    bearer_token = _bearer_token(authorization) or mcp_session
    try:
        session = resolve_persistent_user_session(
            bearer_token=bearer_token,
            store=get_store(),
            settings=settings,
            cipher=get_token_cipher(),
        )
    except PersistentSessionError as exc:
        audit_event(event_type="mcp_session_rejected", success=False, error_class="token_record_unavailable", error=str(exc))
        raise HTTPException(status_code=401, detail="Reauthentication required at /oauth/authorize") from exc
    if not session:
        audit_event(event_type="mcp_session_rejected", success=False, error_class="missing_or_expired")
        raise HTTPException(status_code=401, detail="Login required at /oauth/authorize")
    payload = await request.json()
    return handle_json_rpc(payload, session, settings)
