def test_health_is_public_and_redacted(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["database"] == "connected"
    assert payload["database_host"] == "host.docker.internal"
    serialized = response.text.lower()
    assert "password" not in serialized
    assert "postgresql://" not in serialized


def test_public_dashboard_does_not_require_login(client):
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_public_mode_disables_login_and_write_operations(client):
    status = client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.json()["data"]["mode"] == "PUBLIC_READ_ONLY"
    assert client.post("/api/auth/login", json={"password": "unused"}).status_code == 404
    assert client.post("/api/sync/refresh").status_code == 403


def test_public_mode_blocks_single_account_test_and_sync(authenticated):
    client, _ = authenticated
    account_id = client.get("/api/exchange-accounts").json()["data"][0]["id"]
    assert client.post(f"/api/exchange-accounts/{account_id}/test").status_code == 403
    assert client.post(f"/api/exchange-accounts/{account_id}/sync").status_code == 403


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


def test_sync_reconciliation_and_risk_analytics_are_public(authenticated):
    client, _ = authenticated
    sync = client.get("/api/sync/status")
    assert sync.status_code == 200
    assert sync.json()["data"]["summary"]["total_accounts"] >= 4
    assert len(sync.json()["data"]["accounts"]) >= 4

    reconciliation = client.get("/api/analytics/reconciliation")
    assert reconciliation.status_code == 200
    assert "equity_return" in reconciliation.json()["data"]["totals"]
    assert reconciliation.json()["data"]["accounts"]

    risk = client.get("/api/analytics/risk")
    assert risk.status_code == 200
    assert risk.json()["data"]["summary"]["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
    assert "max_drawdown_percent" in risk.json()["data"]["summary"]


def test_accounting_records_export_and_completeness_are_public(authenticated):
    client, _ = authenticated
    records = client.get("/api/accounting/records?page_size=20")
    assert records.status_code == 200
    assert {"items", "total", "summary"} <= records.json()["data"].keys()

    exported = client.get("/api/accounting/records/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "source_record_id" in exported.text.splitlines()[0]

    completeness = client.get("/api/data-completeness")
    assert completeness.status_code == 200
    payload = completeness.json()["data"]
    assert payload["accounts"]
    assert set(payload["accounts"][0]["components"]) == {
        "equity",
        "positions",
        "realized_pnl",
        "funding_fee",
        "trading_fee",
        "cash_flow",
    }


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
    assert response.status_code == 403
    assert "very-secret-value" not in response.text


def test_account_creation_api_is_disabled_in_public_mode(authenticated):
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
    assert response.status_code == 403
    assert "公开只读模式" in response.text
