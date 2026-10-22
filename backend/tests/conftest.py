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
    AM_ALERTS,
    CLASSIFIER_HEALTH,
    DECISIONS,
    ENGINE_DECISIONS,
    ENGINE_HEALTH,
    JOBS,
    JOBS_DOWN,
    K8S_STATE,
    KNOBS,
    METRICS,
    PENDING,
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
    return Settings(_env_file=None, **values)


@pytest.fixture
def upstream():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://healer.test/api/summary").mock(return_value=httpx.Response(200, json=SUMMARY))
        mock.get("http://healer.test/api/state").mock(return_value=httpx.Response(200, json=STATE))
        mock.get("http://healer.test/api/decisions").mock(return_value=httpx.Response(200, json=DECISIONS))
        mock.get("http://healer.test/api/knobs").mock(return_value=httpx.Response(200, json=KNOBS))
        mock.get("http://healer.test/api/pending").mock(return_value=httpx.Response(200, json=PENDING))
        mock.get("http://healer.test/api/k8s").mock(
            return_value=httpx.Response(200, json=K8S_STATE)
        )
        mock.get("http://healer.test/metrics").mock(return_value=httpx.Response(200, text=METRICS))
        mock.get("http://prom.test/api/v1/query").mock(
            side_effect=lambda request: httpx.Response(
                200, json=prom_response(request.url.params.get("query", ""))
            )
        )
        mock.get("http://prom.test/-/ready").mock(return_value=httpx.Response(200, text="Prometheus ready"))
        mock.get("http://am.test/-/ready").mock(return_value=httpx.Response(200, text="OK"))
        mock.get("http://am.test/api/v2/alerts").mock(
            return_value=httpx.Response(200, json=AM_ALERTS)
        )
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


@pytest.fixture
def runtime_client(upstream):
    """App with the optional classifier + k8s engine-healer runtimes configured."""
    upstream.get("http://classifier.test/healthz").mock(
        return_value=httpx.Response(200, json=CLASSIFIER_HEALTH)
    )
    upstream.get("http://engine.test/healthz").mock(
        return_value=httpx.Response(200, json=ENGINE_HEALTH)
    )
    upstream.get("http://engine.test/decisions").mock(
        return_value=httpx.Response(200, json=ENGINE_DECISIONS)
    )
    app = create_app(
        build_settings(
            classifier_base="http://classifier.test",
            engine_healer_base="http://engine.test",
        )
    )
    with TestClient(app) as test_client:
        yield test_client


GOALS_PASSWORD = "correct-horse"
GOALS_ORIGIN = "http://testserver"
GOALS_CONTROL_BASE = "http://127.0.0.1:9182"
GOALS_CONTROL_KEY = "test-control-key-0123456789abcdef0123456789"


def goals_settings(tmp_path, **overrides) -> Settings:
    values = {
        "auth_mode": "password",
        "app_password": GOALS_PASSWORD,
        "session_secret": "goals-test-secret-0123456789",
        "public_origin": GOALS_ORIGIN,
        "goals_enabled": True,
        "goals_data_dir": str(tmp_path / "data"),
        "goals_approvers": "operator",
        "goals_allow_password_approval": True,
        "goals_allow_self_approval": True,
        "goals_max_goal_chars": 1000,
    }
    values.update(overrides)
    return build_settings(**values)


@pytest.fixture
def goals_client(upstream, tmp_path):
    app = create_app(goals_settings(tmp_path))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def goals_two_person_client(upstream, tmp_path):
    app = create_app(goals_settings(tmp_path, goals_allow_self_approval=False))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def goals_llm_client(upstream, tmp_path):
    app = create_app(
        goals_settings(
            tmp_path,
            goals_llm_enabled=True,
            goals_llm_url="http://llm.test/v1",
            goals_llm_model="test-model",
            goals_llm_key="server-side-test-key",
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def goals_execute_client(upstream, tmp_path):
    app = create_app(
        goals_settings(
            tmp_path,
            goals_execute_enabled=True,
            goals_control_base=GOALS_CONTROL_BASE,
            goals_control_key=GOALS_CONTROL_KEY,
            goals_control_timeout=10,
            goals_control_request_timeout=2,
            goals_control_poll_interval=0.5,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


# keep ruff from flagging imported payloads used only by tests via fixtures
_ = (ALERTS, ALERTS_AGE, JOBS, JOBS_DOWN)