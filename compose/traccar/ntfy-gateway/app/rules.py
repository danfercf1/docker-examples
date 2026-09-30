"""Clasificación de eventos de Traccar en avisos, con perfiles, ventanas
horarias, cooldown y reloj inyectable.

Compatibilidad: sin "profiles"/"windows" en la configuración y sin el
atributo ntfyProfile en ningún dispositivo, el comportamiento es idéntico
al de antes de esta funcionalidad (reglas events/alarms/special/
device_overrides tal cual).
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from .tz import TZ

log = logging.getLogger(__name__)

CATEGORY_URGENT = "urgent"
CATEGORY_INFO = "info"
_VALID_CATEGORIES = (CATEGORY_URGENT, CATEGORY_INFO)
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

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


class ConfigError(RuntimeError):
    """Error de validación de events.yaml al arrancar (mensaje claro)."""


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
        self._warned_profiles: set = set()

        self._windows = self._parse_windows(config.get("windows", {}))
        self._profiles = config.get("profiles", {})
        self._validate_config()

    # -- validación al arrancar ------------------------------------------------
    def _parse_windows(self, raw: dict) -> dict:
        windows = {}
        for name, spec in (raw or {}).items():
            if not isinstance(spec, dict) or "from" not in spec or "to" not in spec:
                raise ConfigError(f"windows.{name}: debe tener 'from' y 'to' (HH:MM)")
            windows[name] = (self._parse_hhmm(name, "from", spec["from"]),
                              self._parse_hhmm(name, "to", spec["to"]))
        return windows

    @staticmethod
    def _parse_hhmm(window_name: str, field: str, value) -> int:
        m = _HHMM_RE.match(str(value))
        if not m:
            raise ConfigError(f"windows.{window_name}.{field}: '{value}' no es una hora HH:MM válida")
        return int(m.group(1)) * 60 + int(m.group(2))

    def _validate_config(self) -> None:
        for key, rule in self._events.items():
            self._validate_rule(f"events.{key}", rule)
        for key, rule in self._alarms.items():
            self._validate_rule(f"alarms.{key}", rule)
        for pname, prules in (self._profiles or {}).items():
            for key, rule in prules.items():
                self._validate_rule(f"profiles.{pname}.{key}", rule)

    def _validate_rule(self, scope: str, rule: dict) -> None:
        if not isinstance(rule, dict):
            return
        category = rule.get("category")
        if category is not None and category not in _VALID_CATEGORIES:
            raise ConfigError(f"{scope}: categoría inválida '{category}'")
        for i, entry in enumerate(rule.get("during") or []):
            window = entry.get("window")
            if window not in self._windows:
                raise ConfigError(f"{scope}.during[{i}]: ventana '{window}' no existe en 'windows'")
            during_category = entry.get("category")
            if during_category is not None and during_category not in _VALID_CATEGORIES:
                raise ConfigError(f"{scope}.during[{i}]: categoría inválida '{during_category}'")

    # -- consultas de reglas -------------------------------------------------
    def offline_sustained_rule(self) -> dict:
        """Regla especial offline_sustained (enabled/category), respetada por el scheduler."""
        return dict(self._special.get("offline_sustained", {}))

    def _window_contains(self, window_name: str, minutes: int) -> bool:
        start, end = self._windows[window_name]
        if start <= end:
            return start <= minutes < end
        return minutes >= start or minutes < end

    def _event_datetime(self, payload: dict) -> datetime:
        event = payload.get("event") or {}
        t = event.get("eventTime") or (payload.get("position") or {}).get("fixTime")
        if t:
            return datetime.fromisoformat(t.replace("Z", "+00:00"))
        return datetime.fromtimestamp(self._clock(), tz=timezone.utc)

    def _event_minutes(self, payload: dict) -> int:
        local = self._event_datetime(payload).astimezone(TZ)
        return local.hour * 60 + local.minute

    def _resolve_during(self, rule: dict, payload: dict) -> dict:
        during = rule.get("during")
        if not during:
            return rule
        minutes = self._event_minutes(payload)
        for entry in during:
            if self._window_contains(entry["window"], minutes):
                merged = dict(rule)
                merged.update({k: v for k, v in entry.items() if k != "window"})
                return merged
        return rule

    def _warn_unknown_profile(self, device_key: str, profile_name: str) -> None:
        marker = (device_key, profile_name)
        if marker in self._warned_profiles:
            return
        self._warned_profiles.add(marker)
        log.warning(
            "ntfyProfile desconocido '%s' para %s; se usan las reglas por defecto",
            profile_name, device_key)

    def _rule(self, kind: str, key: str, payload: dict) -> Optional[dict]:
        table = {"event": self._events, "alarm": self._alarms}.get(kind, {})
        device = payload.get("device") or {}
        device_key = self._device_key(payload)
        profile_name = (device.get("attributes") or {}).get("ntfyProfile")

        rule = None
        if profile_name:
            profile = self._profiles.get(profile_name)
            if profile is None:
                self._warn_unknown_profile(device_key, profile_name)
            else:
                rule = profile.get(key)
        if rule is None:
            rule = table.get(key)
        if not rule:
            return None

        rule = dict(rule)
        override = self._overrides.get(device_key, {}).get(key)
        if override:
            rule.update(override)
        return self._resolve_during(rule, payload)

    def _device_key(self, payload: dict) -> str:
        device = payload.get("device") or {}
        event = payload.get("event") or {}
        return device.get("uniqueId") or device.get("name") or str(event.get("deviceId", "desconocido"))

    def _device(self, payload: dict):
        device = payload.get("device") or {}
        event = payload.get("event") or {}
        name = device.get("name") or str(event.get("deviceId", "desconocido"))
        return name, self._device_key(payload)

    def _alert(self, key: str, category: str, payload: dict) -> Alert:
        name, dev_key = self._device(payload)
        return Alert(key=key, category=category, title=TITLES.get(key, key),
                     device_name=name, device_key=dev_key, payload=payload)

    # -- clasificación ---------------------------------------------------------
    def classify(self, payload: dict) -> list:
        event = payload.get("event") or {}
        etype = event.get("type", "")
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
                rule = self._rule("alarm", value, payload)
                if rule and rule.get("enabled"):
                    alerts.append(self._alert(f"alarm:{value}", rule["category"], payload))
        else:
            rule = self._rule("event", etype, payload)
            if rule and rule.get("enabled"):
                alerts.append(self._alert(etype, rule["category"], payload))

        # Regla especial: deviceMoving con ignition=false (independiente de
        # si deviceMoving está activado como evento suelto). No es sensible
        # a perfiles/ventanas.
        position = payload.get("position") or {}
        pattrs = position.get("attributes") or {}
        if etype == "deviceMoving" and pattrs.get("ignition") is False:
            rule = self._special.get("moving_ignition_off", {})
            if rule.get("enabled"):
                alerts.append(self._alert("moving_ignition_off", rule["category"], payload))

        return alerts

    def profile_names(self) -> list:
        return sorted(self._profiles.keys())

    def window_names(self) -> list:
        return sorted(self._windows.keys())

    # -- cooldown (persistido en SQLite por el llamador) -------------------
    def seed_cooldowns(self, mapping: dict) -> None:
        """Restaura cooldowns guardados en SQLite al arrancar."""
        self._cooldowns.update(mapping)

    def cooldown_count(self) -> int:
        return len(self._cooldowns)

    def pass_cooldown(self, alert: Alert) -> bool:
        now = self._clock()
        ck = (alert.device_key, alert.key)
        last = self._cooldowns.get(ck)
        if last is not None and now - last < self._cooldown_seconds:
            return False
        self._cooldowns[ck] = now
        return True
