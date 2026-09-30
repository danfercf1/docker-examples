"""Cliente ntfy.sh vía JSON (httpx no admite tildes en cabeceras HTTP)."""

import logging
import asyncio
from datetime import datetime, timezone

import httpx

from .tz import TZ

log = logging.getLogger(__name__)

KNOTS_TO_KMH = 1.852


def format_alert(alert) -> tuple:
    """Devuelve (title, body, click_url) para un Alert."""
    title = f"{alert.device_name}: {alert.title}"
    if alert.key == "offline_sustained":
        # payload dict del scheduler
        info = alert.payload
        since = datetime.fromtimestamp(info["since"], tz=timezone.utc).astimezone(TZ)
        body = f"Sin reportar desde {since:%Y-%m-%d %H:%M} (umbral: {info.get('minutes', '?')} min)."
        if info.get("after_restart"):
            body += " Detectado tras un reinicio del gateway."
        pos = info.get("position") or {}
    else:
        event = alert.payload.get("event") or {}
        t = event.get("eventTime")
        when = ""
        if t:
            when = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(TZ).strftime("%Y-%m-%d %H:%M")
        pos = alert.payload.get("position") or {}
        speed = pos.get("speed")
        parts = [f"Hora: {when}" if when else "Hora: desconocida"]
        if speed is not None:
            parts.append(f"Velocidad: {speed * KNOTS_TO_KMH:.0f} km/h")
        course = pos.get("course")
        if course is not None:
            parts.append(f"Rumbo: {course:.0f}°")
        attrs = pos.get("attributes") or {}
        if attrs.get("address"):
            parts.append(f"Lugar: {attrs['address']}")
        body = ". ".join(parts) + "."

    click = None
    if pos.get("latitude") is not None and pos.get("longitude") is not None:
        click = (f"https://www.openstreetmap.org/?mlat={pos['latitude']}"
                 f"&mlon={pos['longitude']}#map=17/{pos['latitude']}/{pos['longitude']}")
    return title, body, click


def format_token_alert() -> tuple:
    """Aviso técnico cuando la API de Traccar rechaza el token del gateway."""
    title = "Gateway ntfy: token de Traccar inválido"
    body = ("La API de Traccar rechazó el token del gateway (401/403): puede haber "
            "caducado o haber sido revocado. Revisa TRACCAR_API_TOKEN y genera uno "
            "nuevo (ver MANUAL-ADMIN.md).")
    return title, body


class Notifier:
    """Publica en ntfy con la API JSON: POST a la raíz del servidor.
    Reintentos con backoff; nunca propaga el error al llamador. El topic se
    indica por llamada porque un mismo gateway envía a varios destinatarios."""

    def __init__(self, ntfy_url: str, max_retries: int = 3):
        self._root = ntfy_url
        self._max_retries = max_retries

    async def send(self, topic: str, title: str, body: str, category: str, click: str = None) -> bool:
        payload = {
            "topic": topic,
            "title": title,
            "message": body,
            "priority": 5 if category == "urgent" else 3,
            "tags": ["rotating_light"] if category == "urgent" else ["information_source"],
        }
        if click:
            payload["click"] = click
        delay = 1.0
        async with httpx.AsyncClient(timeout=10) as client:
            for attempt in range(1, self._max_retries + 1):
                try:
                    r = await client.post(self._root, json=payload)
                    if r.status_code < 400:
                        return True
                    log.error("ntfy respondió %s (intento %d/%d)", r.status_code, attempt, self._max_retries)
                except Exception as e:
                    log.error("ntfy error %s (intento %d/%d)", e, attempt, self._max_retries)
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
        log.error("ntfy: se agotaron los reintentos; notificación perdida (no se propaga el error)")
        return False
