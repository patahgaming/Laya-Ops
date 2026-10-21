from __future__ import annotations

import pytest

from app.config import Settings
from app.main import create_app

from .conftest import build_settings


def goals_base(**overrides) -> Settings:
    values = {
        "auth_mode": "password",
        "app_password": "correct-horse",
        "session_secret": "x" * 32,
        "public_origin": "https://ops.example.test",
        "goals_enabled": True,
        "goals_data_dir": "/tmp/laya-goals-test",
        "goals_approvers": "operator",
        "goals_allow_password_approval": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_goals_require_authentication():
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        create_app(goals_base(auth_mode="off"))


def test_goals_require_public_origin():
    with pytest.raises(RuntimeError, match="PUBLIC_ORIGIN"):
        create_app(goals_base(public_origin=""))


def test_goals_require_non_default_session_secret():
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app(goals_base(session_secret="dev-only-change-me"))


def test_execute_requires_goals():
    with pytest.raises(RuntimeError, match="GOALS_EXECUTE_ENABLED"):
        create_app(goals_base(goals_enabled=False, goals_execute_enabled=True))


def test_execute_requires_loopback_and_key():
    with pytest.raises(RuntimeError, match="loopback"):
        create_app(
            goals_base(
                goals_execute_enabled=True,
                goals_control_base="http://10.10.0.107:9182",
                goals_control_key="x" * 32,
            )
        )
    with pytest.raises(RuntimeError, match="GOALS_CONTROL_KEY"):
        create_app(
            goals_base(
                goals_execute_enabled=True,
                goals_control_base="http://127.0.0.1:9182",
                goals_control_key="short",
            )
        )


def test_auto_execute_is_not_supported():
    with pytest.raises(RuntimeError, match="AUTO_EXECUTE"):
        create_app(goals_base(goals_auto_execute_after_approval=True))


def test_llm_requires_a_server_side_url():
    with pytest.raises(RuntimeError, match="GOALS_LLM_URL"):
        create_app(goals_base(goals_llm_enabled=True, goals_llm_url=""))


def test_valid_goals_settings_app_builds():
    app = create_app(goals_base())
    assert app.state.settings.goals_enabled is True
    assert "/api/goals/templates" in app.openapi()["paths"]


def test_public_origins_are_normalised():
    settings = Settings(
        _env_file=None,
        public_origin="https://ops.example.test/, http://localhost:8000 ",
    )
    assert settings.public_origins == [
        "https://ops.example.test",
        "http://localhost:8000",
    ]


def test_goals_router_is_absent_when_disabled():
    app = create_app(build_settings())
    assert "/api/goals/templates" not in app.openapi()["paths"]
