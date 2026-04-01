import os
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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


@app.middleware("http")
async def validate_bearer_token(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)

    auth_token = os.environ.get("MCP_AUTH_TOKEN")
    if auth_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {auth_token}":
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.mount("/mcp", mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
