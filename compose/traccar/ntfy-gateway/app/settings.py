"""Configuración por variables de entorno (falla claro si falta lo obligatorio)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    gateway_token: str
    ntfy_url: str
    ntfy_topic_admin: str
    cooldown_minutes: int
    offline_sustained_minutes: int
    traccar_url: str
    traccar_api_token: str
    traccar_service_user: str
    traccar_cache_seconds: int
    state_db: str
    sent_log_days: int
    log_level: str


def _required(env, name) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} no definido: es obligatorio (ver example.env)")
    return value


def load_settings(environ=None) -> Settings:
    env = os.environ if environ is None else environ
    return Settings(
        gateway_token=_required(env, "GATEWAY_TOKEN"),
        ntfy_url=(env.get("NTFY_URL") or "https://ntfy.sh").rstrip("/"),
        ntfy_topic_admin=_required(env, "NTFY_TOPIC_ADMIN"),
        cooldown_minutes=int(env.get("COOLDOWN_MINUTES") or 10),
        offline_sustained_minutes=int(env.get("OFFLINE_SUSTAINED_MINUTES") or 15),
        traccar_url=(env.get("TRACCAR_URL") or "http://traccar:8082").rstrip("/"),
        traccar_api_token=_required(env, "TRACCAR_API_TOKEN"),
        traccar_service_user=_required(env, "TRACCAR_SERVICE_USER"),
        traccar_cache_seconds=int(env.get("TRACCAR_CACHE_SECONDS") or 300),
        state_db=(env.get("STATE_DB") or "/srv/state/gateway.db"),
        sent_log_days=int(env.get("SENT_LOG_DAYS") or 90),
        log_level=(env.get("LOG_LEVEL") or "INFO").strip().upper(),
    )
