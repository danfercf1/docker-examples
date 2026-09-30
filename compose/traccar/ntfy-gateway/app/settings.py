"""Configuración por variables de entorno (falla claro si falta lo obligatorio)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    gateway_token: str
    ntfy_url: str
    ntfy_topic: str
    cooldown_minutes: int
    offline_sustained_minutes: int


def load_settings(environ=None) -> Settings:
    env = os.environ if environ is None else environ
    token = (env.get("GATEWAY_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("GATEWAY_TOKEN no definido: es obligatorio (ver example.env)")
    topic = (env.get("NTFY_TOPIC_ALERTS") or "").strip()
    if not topic:
        raise RuntimeError("NTFY_TOPIC_ALERTS no definido: es obligatorio (ver example.env)")
    return Settings(
        gateway_token=token,
        ntfy_url=(env.get("NTFY_URL") or "https://ntfy.sh").rstrip("/"),
        ntfy_topic=topic,
        cooldown_minutes=int(env.get("COOLDOWN_MINUTES") or 10),
        offline_sustained_minutes=int(env.get("OFFLINE_SUSTAINED_MINUTES") or 15),
    )
