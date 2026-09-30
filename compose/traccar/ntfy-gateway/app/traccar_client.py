"""Cliente de solo lectura para la API de Traccar (cuenta de servicio).

Nunca emite POST/PUT/DELETE: la única garantía real de "solo lectura" es
que este código no lo hace (el flag readonly de Traccar no restringe a un
usuario con administrator=true). Construye y cachea en memoria el mapa
dispositivo -> usuarios con ntfyTopic configurado en su atributo personal.

Diseño de llamadas (ver docs/MANUAL-ADMIN.md para el razonamiento):
  GET /api/users            -> todos los usuarios (excepto TRACCAR_SERVICE_USER)
  GET /api/devices?all=true -> todos los dispositivos
  GET /api/devices?userId=N -> dispositivos vinculados directamente a N
                                (se omite si el usuario tiene ntfyAllDevices)

Limitación conocida: el acceso otorgado solo vía grupo de dispositivos no se
detecta (GET /api/devices?userId= excluye grupos). Debe compartirse el
dispositivo directamente para que el usuario reciba avisos.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import httpx

log = logging.getLogger(__name__)

CATEGORY_URGENT = "urgent"
CATEGORY_INFO = "info"
MIN_FORCED_REFRESH_INTERVAL_SECONDS = 30.0


def device_key_of(device: dict) -> str:
    return str(device.get("uniqueId") or device.get("name") or device.get("id") or "desconocido")


@dataclass(frozen=True)
class Recipient:
    username: str
    topic: str
    min_category: str = CATEGORY_INFO


class TraccarClient:
    def __init__(self, base_url: str, token: str, cache_seconds: float,
                 service_user: str, clock: Callable[[], float] = time.time,
                 on_auth_failure: Optional[Callable[[], None]] = None):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._cache_seconds = cache_seconds
        self._service_user = service_user.strip().lower()
        self._clock = clock
        self._on_auth_failure = on_auth_failure

        self._device_map: Optional[dict] = None
        self._device_meta: dict = {}
        self._cache_time: float = 0.0
        self._last_forced_refresh: float = 0.0
        self._refresh_lock = asyncio.Lock()

    @staticmethod
    def _active_devices(devices: list) -> list:
        return [d for d in devices if not d.get("disabled")]

    @staticmethod
    def _is_expired(expiration: Optional[str], now: float) -> bool:
        if not expiration:
            return False
        try:
            ts = datetime.fromisoformat(expiration.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return False
        return ts <= now

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict = None) -> list:
        headers = {"Authorization": f"Bearer {self._token}"}
        r = await client.get(f"{self._base_url}{path}", headers=headers, params=params, timeout=10)
        if r.status_code in (401, 403):
            if self._on_auth_failure:
                self._on_auth_failure()
            raise PermissionError(f"Traccar API respondió {r.status_code} en {path}")
        r.raise_for_status()
        return r.json()

    async def _refresh(self) -> None:
        async with httpx.AsyncClient() as client:
            now = self._clock()
            users = await self._get(client, "/api/users")
            devices = self._active_devices(await self._get(client, "/api/devices", {"all": "true"}))

            device_meta = {}
            for device in devices:
                key = device_key_of(device)
                device_meta[key] = {"name": device.get("name") or key,
                                     "unique_id": device.get("uniqueId")}
            device_map = {key: [] for key in device_meta}

            for user in users:
                if user.get("disabled"):
                    log.debug("traccar: usuario '%s' deshabilitado, omitido", user.get("name"))
                    continue
                if self._is_expired(user.get("expirationTime"), now):
                    log.debug("traccar: usuario '%s' vencido, omitido", user.get("name"))
                    continue
                identity = str(user.get("email") or user.get("login") or "").strip().lower()
                if identity and identity == self._service_user:
                    continue
                attrs = user.get("attributes") or {}
                topic = attrs.get("ntfyTopic")
                if not topic:
                    log.debug("traccar: usuario '%s' sin ntfyTopic, omitido", user.get("name"))
                    continue
                min_category = attrs.get("ntfyMinCategory") or CATEGORY_INFO
                if min_category not in (CATEGORY_URGENT, CATEGORY_INFO):
                    min_category = CATEGORY_INFO
                recipient = Recipient(username=user.get("name") or str(user.get("id")),
                                       topic=topic, min_category=min_category)

                if attrs.get("ntfyAllDevices") is True:
                    for key in device_map:
                        device_map[key].append(recipient)
                    continue

                own_devices = self._active_devices(
                    await self._get(client, "/api/devices", {"userId": user["id"]}))
                for device in own_devices:
                    key = device_key_of(device)
                    device_map.setdefault(key, [])
                    device_map[key].append(recipient)

        self._device_map = device_map
        self._device_meta = device_meta
        self._cache_time = self._clock()
        log.info("traccar: caché de destinatarios actualizada (%d dispositivos, %d usuarios)",
                 len(device_map), len(users))

    async def _try_refresh(self) -> None:
        async with self._refresh_lock:
            try:
                await self._refresh()
            except PermissionError:
                log.warning("traccar: token de API rechazado (401/403); se usa la última caché válida")
            except Exception as e:
                log.warning("traccar: no se pudo refrescar la caché (%s); se usa la última caché válida", e)

    async def _ensure_fresh(self, device_key: str) -> None:
        now = self._clock()
        if self._device_map is None:
            self._last_forced_refresh = now
            await self._try_refresh()
            return
        if now - self._cache_time >= self._cache_seconds:
            self._last_forced_refresh = now
            await self._try_refresh()
            return
        if (device_key not in self._device_map
                and now - self._last_forced_refresh >= MIN_FORCED_REFRESH_INTERVAL_SECONDS):
            self._last_forced_refresh = now
            await self._try_refresh()

    async def get_recipients(self, device_key: str) -> tuple:
        """Devuelve (destinatarios, hubo_cache_alguna_vez)."""
        await self._ensure_fresh(device_key)
        if self._device_map is None:
            return [], False
        return list(self._device_map.get(device_key, [])), True

    def device_name(self, device_key: str) -> Optional[str]:
        meta = self._device_meta.get(device_key)
        return meta["name"] if meta else None

    async def device_status(self, device_key: str) -> Optional[dict]:
        """Estado en vivo (status/lastUpdate), para reconciliar temporizadores
        pendientes tras un reinicio del gateway. None si la API falla."""
        try:
            async with httpx.AsyncClient() as client:
                devices = await self._get(client, "/api/devices", {"all": "true"})
        except Exception as e:
            log.warning("traccar: no se pudo consultar el estado de %s (%s)", device_key, e)
            return None
        for device in devices:
            if device_key_of(device) == device_key:
                return {"status": device.get("status"), "lastUpdate": device.get("lastUpdate")}
        return None
