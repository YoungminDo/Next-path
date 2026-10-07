"""Kakao login through HMM ID: verify dash-access-token via GET /api/v1/auth/me."""
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hellomyme.auth import providers
from hellomyme.auth.providers import AuthError, AuthUnavailable, HmmIdProvider
from hellomyme.config import Settings, get_settings
from hellomyme.main import create_app

GOOD = "good-token"


def hmm_id_transport(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/v1/auth/me"
    auth = request.headers.get("authorization")
    if auth == f"Bearer {GOOD}":
        return httpx.Response(200, json={
            "id": "kakao_12345", "email": "user@example.com", "name": "유저",
            "kakao_id": "12345", "phone": None, "service_roles": {},
            "issued_at": 1, "expires_at": 2})
    if auth == "Bearer outage":
        return httpx.Response(500, json={"error": {"code": "INTERNAL_ERROR"}})
    return httpx.Response(401, json={"error": {"code": "INVALID_TOKEN"}})


def provider(**kw) -> HmmIdProvider:
    settings = Settings(auth_providers=["HMM_ID"], hmm_id_base_url="https://id.example.test", **kw)
    return HmmIdProvider(settings, client=httpx.Client(transport=httpx.MockTransport(hmm_id_transport)))


def test_valid_token_maps_to_dash_user_id():
    identity = provider().verify(GOOD)
    assert (identity.provider, identity.subject) == ("HMM_ID", "kakao_12345")


def test_rejected_token_is_auth_error():
    with pytest.raises(AuthError):
        provider().verify("expired")


def test_idp_outage_is_not_a_login():
    with pytest.raises(AuthUnavailable):
        provider().verify("outage")

    def broken(_request):
        raise httpx.ConnectError("down")

    settings = Settings(auth_providers=["HMM_ID"])
    p = HmmIdProvider(settings, client=httpx.Client(transport=httpx.MockTransport(broken)))
    with pytest.raises(AuthUnavailable):
        p.verify(GOOD)


def test_production_requires_https_idp():
    with pytest.raises(ValueError):
        Settings(env="production", career_map_data_layers=["SEED", "VERIFIED"],
                 auth_providers=["HMM_ID"], hmm_id_base_url="http://id.da-sh.io")


@pytest.fixture
def hmm_client(engine, monkeypatch):
    app = create_app()
    settings = Settings(auth_providers=["HMM_ID"], hmm_id_base_url="https://id.example.test")
    app.dependency_overrides[get_settings] = lambda: settings
    mock = httpx.Client(transport=httpx.MockTransport(hmm_id_transport))
    monkeypatch.setattr(providers, "HmmIdProvider",
                        lambda s: HmmIdProvider(s, client=mock))
    return TestClient(app)


def test_login_endpoint_creates_one_account_per_dash_user(hmm_client, engine):
    first = hmm_client.post("/auth/login", json={"provider": "HMM_ID", "token": GOOD})
    second = hmm_client.post("/auth/login", json={"provider": "HMM_ID", "token": GOOD})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["is_new_account"] is True and second.json()["is_new_account"] is False
    assert first.json()["account_id"] == second.json()["account_id"]
    assert first.json()["expires_at"]
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT auth_provider, provider_subject FROM account_identity "
            "WHERE account_id = :a"), {"a": first.json()["account_id"]}).one()
    assert tuple(row) == ("HMM_ID", "kakao_12345")


def test_login_endpoint_status_codes(hmm_client):
    assert hmm_client.post("/auth/login", json={"provider": "HMM_ID", "token": "bad"}
                           ).status_code == 401
    assert hmm_client.post("/auth/login", json={"provider": "HMM_ID", "token": "outage"}
                           ).status_code == 503
    # DEV is not enabled in this configuration
    assert hmm_client.post("/auth/login", json={"provider": "DEV", "token": "dev:x"}
                           ).status_code == 401
