# Google Ads MCP Server

A remote MCP server that lets Claude query Google Ads data. Deploy once, connect as a Claude.ai team integration — all team members get access without local setup.

## Architecture

```
Claude.ai ──HTTPS──▶ FastAPI + FastMCP (Streamable HTTP)
                            │
                     google-ads client
                            │
                     Google Ads API (read-only)
```

## Tools

| Tool | Description |
|------|-------------|
| `list_accessible_customers` | Returns accessible Google Ads customer IDs |
| `search` | Executes GAQL queries for campaign data, metrics, budgets |

## Prerequisites

- Google Cloud service account with Google Ads API enabled
- Google Ads developer token
- Docker (for deployment)

## Local Development

1. Create a `.env` file from the template:
   ```bash
   cp .env.example .env
   # Edit .env with your actual values
   ```

2. Install dependencies:
   ```bash
   pip install -e .
   ```

3. Run the server:
   ```bash
   python server.py
   ```

4. The server runs at `http://localhost:8080` with MCP endpoint at `/mcp`.

## Deploy to Cloud Run

```bash
# Build and push
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/google-ads-mcp

# Deploy
gcloud run deploy google-ads-mcp \
  --image gcr.io/YOUR_PROJECT_ID/google-ads-mcp \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars "GOOGLE_ADS_DEVELOPER_TOKEN=your-token,MCP_AUTH_TOKEN=your-auth-token" \
  --set-env-vars "GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json"
```

## Connect to Claude.ai

1. Go to your Claude.ai team Settings > Integrations
2. Add a custom MCP connector:
   - **URL**: `https://your-cloud-run-url/mcp`
   - **Auth token**: Your `MCP_AUTH_TOKEN` value
3. All team members can now query Google Ads from Claude

## Example Queries

- "What Google Ads customers do I have access to?"
- "Show me campaign performance for the last 7 days"
- "What's my total spend this month?"
- "List my top 5 campaigns by clicks"

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes | Path to service account JSON |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Yes | Google Ads developer token |
| `MCP_AUTH_TOKEN` | Yes | Bearer token for authenticating requests |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | No | Manager account ID for sub-account access |
| `PORT` | No | Server port (default: 8080) |
