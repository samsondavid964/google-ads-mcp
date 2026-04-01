import os
import json
import secrets
import time
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Form
from fastapi.responses import JSONResponse, RedirectResponse
from mcp.server.fastmcp import FastMCP

from google_ads_client import get_accessible_customers, execute_query


mcp = FastMCP("Google Ads MCP Server")


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


app = FastAPI()

# In-memory store for OAuth authorization codes and access tokens
_auth_codes: dict[str, dict] = {}
_access_tokens: dict[str, dict] = {}

OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "google-ads-mcp")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")


@app.get("/oauth/authorize")
async def oauth_authorize(
    response_type: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
):
    """OAuth 2.0 authorization endpoint. Auto-approves and redirects back with a code."""
    if response_type != "code":
        return JSONResponse(status_code=400, content={"error": "unsupported_response_type"})

    if client_id != OAUTH_CLIENT_ID:
        return JSONResponse(status_code=400, content={"error": "invalid_client"})

    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "redirect_uri": redirect_uri,
        "created_at": time.time(),
    }

    params = {"code": code}
    if state:
        params["state"] = state

    return RedirectResponse(url=f"{redirect_uri}?{urlencode(params)}")


@app.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form(""),
    code: str = Form(""),
    redirect_uri: str = Form(""),  # noqa: ARG001
    client_id: str = Form(""),
    client_secret: str = Form(""),
    refresh_token: str = Form(""),
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


@app.middleware("http")
async def validate_bearer_token(request: Request, call_next):
    path = request.url.path

    # Skip auth for health check and OAuth endpoints
    if path in ("/health", "/oauth/authorize", "/oauth/token"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    token = auth_header.removeprefix("Bearer ")

    # Accept tokens issued by our OAuth flow
    if token in _access_tokens:
        return await call_next(request)

    # Also accept the static MCP_AUTH_TOKEN for direct testing
    mcp_token = os.environ.get("MCP_AUTH_TOKEN")
    if mcp_token and token == mcp_token:
        return await call_next(request)

    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


@app.get("/health")
async def health():
    return {"status": "ok"}


app.mount("/mcp", mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
