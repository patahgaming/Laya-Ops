from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .fake_upstream import (
    ALERTS,
    ALERTS_AGE,
    DECISIONS,
    JOBS,
    JOBS_DOWN,
    KNOBS,
    METRICS,
    STATE,
    SUMMARY,
    prom_response,
)


def build_settings(**overrides) -> Settings:
    values = {
        "auth_mode": "off",
        "healer_base": "http://healer.test",
        "prometheus_base": "http://prom.test",
        "alertmanager_base": "http://am.test",
        "grafana_base": "http://grafana.test",
        "cache_ttl": 0,
        "session_secret": "test-secret-0123456789",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def upstream():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://healer.test/api/summary").mock(return_value=httpx.Response(200, json=SUMMARY))
        mock.get("http://healer.test/api/state").mock(return_value=httpx.Response(200, json=STATE))
        mock.get("http://healer.test/api/decisions").mock(return_value=httpx.Response(200, json=DECISIONS))
        mock.get("http://healer.test/api/knobs").mock(return_value=httpx.Response(200, json=KNOBS))
        mock.get("http://healer.test/metrics").mock(return_value=httpx.Response(200, text=METRICS))
        mock.get("http://prom.test/api/v1/query").mock(
            side_effect=lambda request: httpx.Response(
                200, json=prom_response(request.url.params.get("query", ""))
            )
        )
        mock.get("http://prom.test/-/ready").mock(return_value=httpx.Response(200, text="Prometheus ready"))
        mock.get("http://am.test/-/ready").mock(return_value=httpx.Response(200, text="OK"))
        mock.get("http://grafana.test/api/health").mock(
            return_value=httpx.Response(200, json={"database": "ok", "version": "12.2.0"})
        )
        yield mock


@pytest.fixture
def client(upstream):
    app = create_app(build_settings())
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def password_client(upstream):
    app = create_app(build_settings(auth_mode="password", app_password="correct-horse"))
    with TestClient(app) as test_client:
        yield test_client


# keep ruff from flagging imported payloads used only by tests via fixtures
_ = (ALERTS, ALERTS_AGE, JOBS, JOBS_DOWN)
