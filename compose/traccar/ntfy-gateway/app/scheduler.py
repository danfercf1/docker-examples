"""Regla offline_sustained: aviso urgente si el dispositivo no reporta en N minutos.

event.forward solo reenvía EVENTOS (no posiciones sueltas): la cancelación
ocurre cuando llega un deviceOnline (o cualquier otro evento del mismo
dispositivo). Los temporizadores viven en memoria: se pierden si el
contenedor se reinicia.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class _Pending:
    since: float            # timestamp del deviceOffline
    deadline: float         # since + minutos configurados
    device_name: str
    device_key: str
    last_position: Optional[dict]


class OfflineScheduler:
    """Programa un aviso N minutos después de un deviceOffline; lo cancela si
    el dispositivo genera otro evento antes. No programa nada si la regla
    special.offline_sustained.enabled es false."""

    def __init__(self, minutes: int, clock: Callable[[], float],
                 on_fire: Callable[[dict], None], enabled: bool = True,
                 category: str = "urgent"):
        self._minutes = minutes
        self._clock = clock
        self._on_fire = on_fire
        self._enabled = enabled
        self._category = category
        self._pending: dict[str, _Pending] = {}

    def process(self, payload: dict) -> None:
        """Se invoca con cada payload recibido."""
        self._fire_due()
        event = payload.get("event") or {}
        etype = event.get("type", "")
        device = payload.get("device") or {}
        name = device.get("name") or str(event.get("deviceId", "desconocido"))
        key = device.get("uniqueId") or device.get("name") or str(event.get("deviceId", "desconocido"))

        if etype == "deviceOffline":
            if self._enabled and key not in self._pending:
                now = self._clock()
                self._pending[key] = _Pending(
                    since=now, deadline=now + self._minutes * 60.0,
                    device_name=name, device_key=key,
                    last_position=payload.get("position"),
                )
                log.info("offline_sustained: programado aviso para %s en %d min", name, self._minutes)
        elif key in self._pending:
            # Reconexión (deviceOnline) o cualquier otro evento del
            # dispositivo: cancela el aviso pendiente.
            del self._pending[key]
            log.info("offline_sustained: cancelado para %s (evento %s)", name, etype)

    def check_due(self) -> None:
        """Dispara avisos vencidos. En producción la invoca una tarea asyncio
        periódica creada en el lifespan (sin hilos)."""
        self._fire_due()

    def _fire_due(self) -> None:
        now = self._clock()
        due = [k for k, p in self._pending.items() if now >= p.deadline]
        for key in due:
            p = self._pending.pop(key)
            self._on_fire({
                "key": "offline_sustained",
                "category": self._category,
                "device_name": p.device_name,
                "device_key": key,
                "since": p.since,
                "minutes": self._minutes,
                "position": p.last_position,
            })
