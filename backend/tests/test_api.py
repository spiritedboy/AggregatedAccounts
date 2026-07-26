def test_health_is_public_and_redacted(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["database"] == "connected"
    assert payload["database_host"] == "host.docker.internal"
    serialized = response.text.lower()
    assert "password" not in serialized
    assert "postgresql://" not in serialized


def test_unauthenticated_request_is_blocked(client):
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 401
    assert response.json()["success"] is False


def test_login_status_logout_flow(authenticated):
    client, headers = authenticated
    assert client.get("/api/auth/status").json()["data"]["authenticated"] is True
    blocked = client.post("/api/auth/logout")
    assert blocked.status_code == 403
    response = client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 200
    assert client.get("/api/auth/status").status_code == 401


def test_demo_dashboard_positions_and_pnl(authenticated):
    client, _ = authenticated
    dashboard = client.get("/api/dashboard/summary")
    assert dashboard.status_code == 200
    assert dashboard.json()["data"]["estimated_total_equity"] > 0
    assert dashboard.json()["data"]["demo_mode"] is True
    positions = client.get("/api/positions/current").json()["data"]
    assert positions["total"] >= 4
    assert {item["side"] for item in positions["items"]} <= {"LONG", "SHORT"}
    pnl = client.get("/api/pnl/daily").json()["data"]
    assert len(pnl) == 30


def test_account_responses_do_not_leak_credentials(authenticated):
    client, _ = authenticated
    response = client.get("/api/exchange-accounts")
    assert response.status_code == 200
    serialized = response.text.lower()
    for forbidden in (
        "api_secret",
        "passphrase_ciphertext",
        "authentication_tag",
        "encryption_key",
        "nonce",
    ):
        assert forbidden not in serialized


def test_history_filters_and_csv_export(authenticated):
    client, _ = authenticated
    response = client.get("/api/positions/history?side=LONG&page_size=5")
    assert response.status_code == 200
    assert all(item["side"] == "LONG" for item in response.json()["data"]["items"])
    exported = client.get("/api/positions/history/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "data_source" in exported.text.splitlines()[0]


def test_api_key_validation_does_not_echo_secret(authenticated):
    client, headers = authenticated
    response = client.post(
        "/api/exchange-accounts",
        headers=headers,
        json={
            "exchange": "OKX",
            "connection_name": "invalid",
            "api_key": "api-key-value",
            "api_secret": "very-secret-value",
        },
    )
    assert response.status_code == 422
    assert "very-secret-value" not in response.text


def test_polymarket_account_uses_public_address_only(authenticated, monkeypatch):
    from app.services.accounts import ADAPTERS

    class FakePolymarketAdapter:
        def __init__(self, **kwargs):
            self.wallet_address = kwargs["wallet_address"]

        async def test_connection(self):
            return True

        async def get_permissions(self):
            return {
                "read": True,
                "spot_trade": False,
                "futures_trade": False,
                "transfer": False,
                "withdraw": False,
                "public_address_only": True,
            }

        async def get_account_summary(self):
            return {
                "total_equity_usd": 52,
                "available_balance_usd": 14.5,
                "margin_balance_usd": 37.5,
                "unrealized_pnl_usd": 20,
            }

        async def get_open_positions(self):
            return []

        async def close(self):
            return None

    monkeypatch.setitem(ADAPTERS, "POLYMARKET", FakePolymarketAdapter)
    client, headers = authenticated
    response = client.post(
        "/api/exchange-accounts",
        headers=headers,
        json={
            "exchange": "POLYMARKET",
            "connection_name": "预测市场",
            "wallet_address": "0x" + "d" * 40,
        },
    )
    assert response.status_code == 201
    account = response.json()["data"]
    assert account["exchange"] == "POLYMARKET"
    assert account["data_completeness"] == "PARTIAL"
    assert account["permission_status"]["public_address_only"] is True
