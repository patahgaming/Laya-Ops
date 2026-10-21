from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import build_settings


def test_auth_off_exposes_anonymous(password_client):
    password_client.post("/api/auth/logout")
    config = password_client.get("/api/auth/config").json()
    assert config["mode"] == "password"
    assert config["user"] is None

    anonymous = TestClient(create_app(build_settings()))
    info = anonymous.get("/api/auth/config").json()
    assert info["mode"] == "off"
    assert info["user"]["name"] == "anonymous"
    assert info["app_name"] == "Laya Ops"
    assert info["app_version"] == "1.0.0"
    assert info["plane"] == {
        "name": "VM105",
        "site": "hq1",
        "host": "10.10.0.107",
        "ssh_user": "root",
    }


def test_auth_config_uses_plane_settings():
    app = create_app(
        build_settings(
            plane_name="lab-01",
            plane_site="lab",
            plane_host="192.0.2.10",
            plane_ssh_user="ops",
        )
    )
    with TestClient(app) as client:
        config = client.get("/api/auth/config").json()
    assert config["plane"] == {
        "name": "lab-01",
        "site": "lab",
        "host": "192.0.2.10",
        "ssh_user": "ops",
    }


def test_password_login_protects_api(password_client):
    assert password_client.get("/api/overview").status_code == 401

    bad = password_client.post("/api/auth/login", json={"password": "nope"})
    assert bad.status_code == 401

    good = password_client.post("/api/auth/login", json={"password": "correct-horse"})
    assert good.status_code == 200
    assert good.json()["user"]["name"] == "operator"
    assert "laya_session" in password_client.cookies

    assert password_client.get("/api/overview").status_code == 200

    password_client.post("/api/auth/logout")
    assert password_client.get("/api/overview").status_code == 401


def test_login_rate_limit(password_client):
    for _ in range(5):
        assert password_client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert password_client.post("/api/auth/login", json={"password": "nope"}).status_code == 429


def test_oidc_requires_configuration():
    with pytest.raises(RuntimeError):
        create_app(
            Settings(
                auth_mode="oidc",
                session_secret="x" * 32,
                oidc_issuer="https://sso.example.test/realms/school",
                oidc_client_id="laya-ops",
                oidc_client_secret="",
            )
        )


def test_oidc_registers_provider_without_network():
    app = create_app(
        Settings(
            auth_mode="oidc",
            session_secret="x" * 32,
            oidc_issuer="https://sso.example.test/realms/school",
            oidc_client_id="laya-ops",
            oidc_client_secret="secret",
        )
    )
    assert app.state.oauth is not None
    with TestClient(app) as client:
        config = client.get("/api/auth/config").json()
        assert config["mode"] == "oidc"
        assert config["login_url"] == "/api/auth/oidc/login"
        assert config["user"] is None
        assert client.get("/api/overview").status_code == 401


def test_password_mode_requires_secret():
    with pytest.raises(RuntimeError):
        create_app(Settings(auth_mode="password", session_secret="x" * 32, app_password=""))
