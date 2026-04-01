import os
import json
import secrets
import time
import hashlib
import base64
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Form
from fastapi.responses import JSONResponse, RedirectResponse
from mcp.server.fastmcp import FastMCP

from google_ads_client import get_accessible_customers, execute_query


mcp = FastMCP("Google Ads MCP Server", streamable_http_path="/")


@mcp.tool()
def list_accessible_customers() -> str:
    """Returns the Google Ads customer IDs accessible by this service account."""
    customers = get_accessible_customers()
    return json.dumps(customers, indent=2)


@mcp.tool()
def search(customer_id: str, query: str) -> str:
    """Executes a GAQL (Google Ads Query Language) query against a Google Ads account.

    Args:
        customer_id: The Google Ads customer ID (digits only, no dashes).
        query: A valid GAQL query string, e.g.
               "SELECT campaign.name, metrics.clicks FROM campaign WHERE metrics.clicks > 0"
    """
    rows = execute_query(customer_id, query)
    return json.dumps(rows, indent=2)


# In-memory store for OAuth authorization codes and access tokens
_auth_codes: dict[str, dict] = {}
_access_tokens: dict[str, dict] = {}

OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "google-ads-mcp")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")

# Paths that don't require bearer token auth
PUBLIC_PATHS = {
    "/health",
    "/authorize",
    "/token",
    "/oauth/authorize",
    "/oauth/token",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/mcp",
    "/favicon.ico",
}


def _is_valid_token(token: str) -> bool:
    """Check if a bearer token is valid."""
    if token in _access_tokens:
        return True
    mcp_token = os.environ.get("MCP_AUTH_TOKEN")
    if mcp_token and token == mcp_token:
        return True
    return False


def _get_base_url(request: Request) -> str:
    """Get the external base URL from the request."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{scheme}://{host}"


# Build the main FastAPI app
app = FastAPI()


@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    """OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
    base = _get_base_url(request)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
async def protected_resource_metadata(request: Request):
    """OAuth 2.0 Protected Resource Metadata."""
    base = _get_base_url(request)
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
    }


@app.get("/authorize")
@app.get("/oauth/authorize")
async def oauth_authorize(
    response_type: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
):
    """OAuth 2.0 authorization endpoint. Auto-approves and redirects back with a code."""
    if response_type != "code":
        return JSONResponse(status_code=400, content={"error": "unsupported_response_type"})

    if client_id != OAUTH_CLIENT_ID:
        return JSONResponse(status_code=400, content={"error": "invalid_client"})

    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "created_at": time.time(),
    }

    params = {"code": code}
    if state:
        params["state"] = state

    return RedirectResponse(url=f"{redirect_uri}?{urlencode(params)}")


@app.post("/token")
@app.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form(""),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    refresh_token: str = Form(""),
    code_verifier: str = Form(""),
):
    """OAuth 2.0 token endpoint. Exchanges auth code for access token."""
    if client_id != OAUTH_CLIENT_ID or client_secret != OAUTH_CLIENT_SECRET:
        return JSONResponse(status_code=401, content={"error": "invalid_client"})

    if grant_type == "authorization_code":
        if code not in _auth_codes:
            return JSONResponse(status_code=400, content={"error": "invalid_grant"})

        stored = _auth_codes.pop(code)
        if time.time() - stored["created_at"] > 300:
            return JSONResponse(status_code=400, content={"error": "invalid_grant"})

        # PKCE verification
        if stored.get("code_challenge"):
            expected = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode()).digest()
            ).rstrip(b"=").decode()
            if expected != stored["code_challenge"]:
                return JSONResponse(status_code=400, content={"error": "invalid_grant", "error_description": "PKCE verification failed"})

        access_token = secrets.token_urlsafe(48)
        new_refresh_token = secrets.token_urlsafe(48)
        _access_tokens[access_token] = {"created_at": time.time()}

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 86400,
            "refresh_token": new_refresh_token,
        }

    elif grant_type == "refresh_token":
        access_token = secrets.token_urlsafe(48)
        _access_tokens[access_token] = {"created_at": time.time()}

        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 86400,
            "refresh_token": refresh_token,
        }

    return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})


@app.get("/health")
async def health():
    return {"status": "ok"}


# Get the raw MCP ASGI app
mcp_asgi = mcp.streamable_http_app()


# Custom ASGI middleware that checks auth then delegates to MCP app
async def authed_mcp_app(scope, receive, send):
    if scope["type"] == "http":
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        if not auth_header.startswith("Bearer ") or not _is_valid_token(auth_header.removeprefix("Bearer ")):
            response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            await response(scope, receive, send)
            return
    await mcp_asgi(scope, receive, send)


app.mount("/mcp", authed_mcp_app)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
