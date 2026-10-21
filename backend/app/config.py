"""Application settings, loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
