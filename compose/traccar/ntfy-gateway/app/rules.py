"""Clasificación de eventos de Traccar en avisos, con cooldown y reloj inyectable."""

import time
from dataclasses import dataclass
from typing import Callable, Optional


CATEGORY_URGENT = "urgent"
CATEGORY_INFO = "info"

# Títulos en español por clave de aviso (alarm:<valor> o el tipo de evento)
TITLES = {
    "alarm:powerCut": "Corte de corriente",
    "alarm:sos": "SOS",
    "alarm:tow": "Vehículo remolcado",
    "alarm:vibration": "Vibración",
    "alarm:jamming": "Jamming de señal",
    "alarm:tampering": "Manipulación detectada",
    "alarm:removing": "Dispositivo desmontado",
    "alarm:gpsAntennaCut": "Antena GPS cortada",
    "alarm:powerOff": "Alimentación apagada",
    "alarm:lowBattery": "Batería baja",
    "alarm:lowPower": "Batería externa baja",
    "alarm:powerRestored": "Alimentación restaurada",
    "deviceOverspeed": "Exceso de velocidad",
    "geofenceEnter": "Entrada a geocerca",
    "geofenceExit": "Salida de geocerca",
    "ignitionOn": "Contacto encendido",
    "ignitionOff": "Contacto apagado",
    "deviceOnline": "Dispositivo en línea",
    "deviceOffline": "Dispositivo desconectado",
    "deviceUnknown": "Dispositivo en estado desconocido",
    "deviceMoving": "En movimiento",
    "deviceStopped": "Detenido",
    "deviceInactive": "Dispositivo inactivo",
    "moving_ignition_off": "Moviéndose sin contacto",
    "offline_sustained": "Sin reportar",
}


@dataclass(frozen=True)
class Alert:
    key: str                 # p.ej. "alarm:powerCut", "geofenceExit", "moving_ignition_off"
    category: str            # urgent | info
    title: str
    device_name: str
    device_key: str          # uniqueId si existe, si no name, si no deviceId
    payload: dict            # payload original de Traccar (o dict del scheduler)


class Rules:
    def __init__(self, config: dict, cooldown_minutes: int = 10,
                 clock: Callable[[], float] = time.time):
        self._events = config.get("events", {})
        self._alarms = config.get("alarms", {})
        self._special = config.get("special", {})
        self._overrides = config.get("device_overrides", {})
        self._cooldown_seconds = float(cooldown_minutes) * 60.0
        self._clock = clock
        self._cooldowns: dict[tuple, float] = {}

    def offline_sustained_rule(self) -> dict:
        """Regla especial offline_sustained (enabled/category), respetada por el scheduler."""
        return dict(self._special.get("offline_sustained", {}))

    # -- consultas de reglas -------------------------------------------------
    def _rule(self, kind: str, key: str, device_key: str) -> Optional[dict]:
        table = {"event": self._events, "alarm": self._alarms}.get(kind, {})
        rule = dict(table.get(key, {}))
        override = self._overrides.get(device_key, {}).get(key)
        if override:
            rule.update(override)
        return rule or None

    def _device(self, payload: dict):
        device = payload.get("device") or {}
        event = payload.get("event") or {}
        name = device.get("name") or str(event.get("deviceId", "desconocido"))
        key = device.get("uniqueId") or device.get("name") or str(event.get("deviceId", "desconocido"))
        return name, key

    def _alert(self, key: str, category: str, payload: dict) -> Alert:
        name, dev_key = self._device(payload)
        return Alert(key=key, category=category, title=TITLES.get(key, key),
                     device_name=name, device_key=dev_key, payload=payload)

    # -- clasificación ---------------------------------------------------------
    def classify(self, payload: dict) -> list:
        event = payload.get("event") or {}
        etype = event.get("type", "")
        _, dev_key = self._device(payload)
        alerts = []

        if etype == "alarm":
            # La alarma viene en event.attributes.alarm (position es respaldo)
            attrs = event.get("attributes") or {}
            if not attrs.get("alarm"):
                attrs = (payload.get("position") or {}).get("attributes") or {}
            for value in str(attrs.get("alarm", "")).split(","):
                value = value.strip()
                if not value:
                    continue
                rule = self._rule("alarm", value, dev_key)
                if rule and rule.get("enabled"):
                    alerts.append(self._alert(f"alarm:{value}", rule["category"], payload))
        else:
            rule = self._rule("event", etype, dev_key)
            if rule and rule.get("enabled"):
                alerts.append(self._alert(etype, rule["category"], payload))

        # Regla especial: deviceMoving con ignition=false (independiente de
        # si deviceMoving está activado como evento suelto).
        position = payload.get("position") or {}
        pattrs = position.get("attributes") or {}
        if etype == "deviceMoving" and pattrs.get("ignition") is False:
            rule = self._special.get("moving_ignition_off", {})
            if rule.get("enabled"):
                alerts.append(self._alert("moving_ignition_off", rule["category"], payload))

        return alerts

    # -- cooldown en memoria (se pierde al reiniciar el contenedor) -------------
    def pass_cooldown(self, alert: Alert) -> bool:
        now = self._clock()
        ck = (alert.device_key, alert.key)
        last = self._cooldowns.get(ck)
        if last is not None and now - last < self._cooldown_seconds:
            return False
        self._cooldowns[ck] = now
        return True
