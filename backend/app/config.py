"""Application settings, loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

# Load the repo-root .env no matter which directory uvicorn is started from.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Laya Ops"
    app_version: str = "1.0.0"

    # plane identity shown by the UI (also used for the SSH helper commands)
    plane_name: str = "VM105"
    plane_site: str = "hq1"
    plane_host: str = "10.10.0.107"
    plane_ssh_user: str = "root"

    # upstread services, reachable from the backend host (VM105: all localhost)
    healer_base: str = "http://127.0.0.1:9181"
    prometheus_base: str = "http://127.0.0.1:9090"
    alertmanager_base: str = "http://127.0.0.1:9093"
    grafana_base: str = "http://127.0.0.1:3000"
    grafana_public_url: str = "https://grafana.smkn12jakarta.sch.id"
    # optional runtimes — probes are skipped when the base is empty
    classifier_base: str = ""
    engine_healer_base: str = ""
    upstream_timeout: float = 6.0
    cache_ttl: float = 4.0

    # auth: off (LAN only) | password (env secret) | oidc (Keycloak)
    auth_mode: Literal["off", "password", "oidc"] = "off"
    app_password: str = ""
    session_secret: str = "dev-only-change-me"
    cookie_secure: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""

    # optional hardening
    allowed_hosts: str = ""
    public_origin: str = ""
    max_request_body: int = 64 * 1024

    # AI goals (Phase 1/2) — every switch defaults to off.
    goals_enabled: bool = False
    goals_execute_enabled: bool = False
    goals_data_dir: str = "/app/data"
    goals_llm_enabled: bool = False
    goals_llm_url: str = ""
    goals_llm_key: str = ""
    goals_llm_model: str = ""
    goals_approvers: str = ""
    goals_approver_groups: str = ""
    goals_allow_self_approval: bool = False
    goals_allow_password_approval: bool = False
    goals_high_risk_passphrase: str = ""
    goals_preview_ttl: int = 300
    goals_approval_ttl: int = 900
    goals_execution_ttl: int = 600
    goals_max_goal_chars: int = 1000
    goals_rate_limit_per_hour: int = 10
    goals_control_base: str = "http://127.0.0.1:9182"
    goals_control_key: str = ""
    goals_control_timeout: float = 150.0
    goals_control_request_timeout: float = 15.0
    goals_control_poll_interval: float = 2.0
    goals_auto_execute_after_approval: bool = False

    @property
    def public_origins(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.public_origin.split(",") if item.strip()]

    @property
    def goals_approver_names(self) -> set[str]:
        return {item.strip() for item in self.goals_approvers.split(",") if item.strip()}

    @property
    def goals_approver_group_names(self) -> set[str]:
        return {item.strip() for item in self.goals_approver_groups.split(",") if item.strip()}

    @property
    def goals_control_is_loopback(self) -> bool:
        try:
            parsed = urlsplit(self.goals_control_base)
        except ValueError:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if parsed.path not in ("", "/"):
            return False
        return (parsed.hostname or "").lower() in {"127.0.0.1", "::1", "localhost"}

    @property
    def links(self) -> dict[str, str]:
        return {
            "grafana": self.grafana_public_url,
            "grafana_local": self.grafana_base,
            "grafana_healer_dashboard": self.grafana_public_url.rstrip("/") + "/d/sre-healer",
            "prometheus": self.prometheus_base,
            "alertmanager": self.alertmanager_base,
            "healer_ui": self.healer_base.rstrip("/") + "/ui/live.html",
            "healer_api": self.healer_base.rstrip("/") + "/api/summary",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
