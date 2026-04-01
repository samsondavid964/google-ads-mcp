import os
import json
import tempfile

from google.ads.googleads.client import GoogleAdsClient
from google.auth import default as google_auth_default
from google.protobuf.json_format import MessageToDict


_client = None


def _setup_credentials():
    """If GOOGLE_CREDENTIALS_JSON env var is set (raw JSON string),
    write it to a temp file and point GOOGLE_APPLICATION_CREDENTIALS at it.
    This allows passing credentials as an env var on platforms like Railway."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_json)
        tmp.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name


def _get_client() -> GoogleAdsClient:
    global _client
    if _client is None:
        _setup_credentials()
        credentials, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/adwords"]
        )
        _client = GoogleAdsClient(
            credentials=credentials,
            developer_token=os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            use_proto_plus=True,
        )
        login_customer_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        if login_customer_id:
            _client.login_customer_id = login_customer_id
    return _client


def get_accessible_customers() -> list[dict]:
    client = _get_client()
    customer_service = client.get_service("CustomerService")
    response = customer_service.list_accessible_customers()

    customers = []
    for resource_name in response.resource_names:
        customer_id = resource_name.split("/")[-1]
        customers.append({
            "customer_id": customer_id,
            "resource_name": resource_name,
        })
    return customers


def execute_query(customer_id: str, query: str) -> list[dict]:
    client = _get_client()
    ga_service = client.get_service("GoogleAdsService")

    rows = []
    stream = ga_service.search_stream(customer_id=customer_id, query=query)
    for batch in stream:
        for row in batch.results:
            rows.append(MessageToDict(type(row).pb(row)))
    return rows
