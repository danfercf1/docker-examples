"""Regla offline_sustained: aviso urgente si el dispositivo no reporta en N minutos.

event.forward solo reenvía EVENTOS (no posiciones sueltas): la cancelación
ocurre cuando llega un deviceOnline (o cualquier otro evento del mismo
dispositivo). Los temporizadores se guardan en SQLite (ver State) para
sobrevivir un reinicio del gateway.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
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
                 category: str = "urgent", state=None):
        self._minutes = minutes
        self._clock = clock
        self._on_fire = on_fire
        self._enabled = enabled
        self._category = category
        self._state = state
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
                pending = _Pending(since=now, deadline=now + self._minutes * 60.0,
                                    device_name=name, device_key=key,
                                    last_position=payload.get("position"))
                self._pending[key] = pending
                if self._state:
                    self._state.save_pending(key, name, pending.since, pending.deadline,
                                              pending.last_position)
                log.info("offline_sustained: programado aviso para %s en %d min", name, self._minutes)
        elif key in self._pending:
            # Reconexión (deviceOnline) o cualquier otro evento del
            # dispositivo: cancela el aviso pendiente.
            del self._pending[key]
            if self._state:
                self._state.delete_pending(key)
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
            if self._state:
                self._state.delete_pending(key)
            self._fire(p, after_restart=False)

    def _fire(self, p: _Pending, after_restart: bool) -> None:
        self._on_fire({
            "key": "offline_sustained",
            "category": self._category,
            "device_name": p.device_name,
            "device_key": p.device_key,
            "since": p.since,
            "minutes": self._minutes,
            "position": p.last_position,
            "after_restart": after_restart,
        })

    # -- restauración al arrancar --------------------------------------------
    async def restore(self, traccar_client) -> None:
        """Restaura pending_offline desde SQLite. Los temporizadores ya
        vencidos durante la caída del gateway se reconcilian contra la API
        de Traccar antes de disparar (ver docs/MANUAL-ADMIN.md)."""
        if not self._state:
            return
        now = self._clock()
        rows = self._state.load_all_pending()
        restored = 0
        fired = 0
        cancelled = 0
        for row in rows:
            key = row["device_key"]
            if now < row["deadline"]:
                self._pending[key] = _Pending(since=row["since"], deadline=row["deadline"],
                                               device_name=row["device_name"], device_key=key,
                                               last_position=row["last_position"])
                restored += 1
                continue

            p = _Pending(since=row["since"], deadline=row["deadline"],
                         device_name=row["device_name"], device_key=key,
                         last_position=row["last_position"])
            reconnected = await self._is_reconnected(traccar_client, key, row["since"])
            self._state.delete_pending(key)
            if reconnected:
                cancelled += 1
                log.info("offline_sustained: %s se reconectó mientras el gateway estaba caído; "
                          "temporizador cancelado", row["device_name"])
            else:
                fired += 1
                log.info("offline_sustained: %s seguía desconectado tras el reinicio; disparando aviso",
                          row["device_name"])
                self._fire(p, after_restart=True)
        if rows:
            log.info("offline_sustained: restauración completa (%d vigentes, %d disparados, "
                      "%d cancelados por reconexión)", restored, fired, cancelled)

    @staticmethod
    async def _is_reconnected(traccar_client, device_key: str, since: float) -> bool:
        status = await traccar_client.device_status(device_key)
        if status is None:
            # API caída: mejor un aviso de más que uno perdido.
            return False
        if status.get("status") == "online":
            return True
        last_update = status.get("lastUpdate")
        if last_update:
            try:
                ts = datetime.fromisoformat(last_update.replace("Z", "+00:00")).timestamp()
                if ts > since:
                    return True
            except ValueError:
                pass
        return False
