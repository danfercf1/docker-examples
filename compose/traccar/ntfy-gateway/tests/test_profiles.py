"""Perfiles (ntfyProfile), ventanas horarias y validación al arrancar."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import make_payload, post_event, StubTraccarClient
from app.rules import ConfigError, Rules
from app.traccar_client import Recipient

TZ = ZoneInfo("America/La_Paz")
UTC = ZoneInfo("UTC")
DEVICE_KEY = "1234567890"


def event_time_for_local(hh, mm, day=29):
    local = datetime(2026, 9, day, hh, mm, tzinfo=TZ)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def _category_for(build, etype, hh, mm, profile="vehiculo", unique_id=DEVICE_KEY):
    stub = StubTraccarClient(device_map={unique_id: [Recipient("ana", "tema-ana")]})
    app, rec, _, _, _ = build(traccar_client=stub)
    payload = make_payload(etype, unique_id=unique_id,
                           device_attributes={"ntfyProfile": profile} if profile else None,
                           event_time=event_time_for_local(hh, mm))
    await post_event(app, payload)
    assert len(rec.sent) == 1, f"se esperaba 1 envío, hubo {len(rec.sent)}"
    return rec.sent[0][3]   # category


# -- perfil vehiculo ----------------------------------------------------------------
async def test_geofence_exit_de_dia_es_info(build):
    assert await _category_for(build, "geofenceExit", 14, 0) == "info"


async def test_geofence_exit_de_noche_es_urgent(build):
    assert await _category_for(build, "geofenceExit", 2, 0) == "urgent"


async def test_ignition_on_de_dia_es_info(build):
    assert await _category_for(build, "ignitionOn", 14, 0) == "info"


async def test_ignition_on_de_noche_es_urgent(build):
    assert await _category_for(build, "ignitionOn", 2, 0) == "urgent"


async def test_sin_perfil_geofence_exit_usa_regla_por_defecto(build):
    # Sin ntfyProfile, geofenceExit siempre es urgent (regla por defecto,
    # sin "during"), incluso a las 02:00.
    assert await _category_for(build, "geofenceExit", 2, 0, profile=None) == "urgent"


# -- ventana que cruza medianoche ---------------------------------------------------
@pytest.mark.parametrize("hh,mm,expected", [
    (23, 30, "urgent"),   # dentro
    (5, 59, "urgent"),    # dentro
    (6, 0, "info"),       # fuera (límite superior exclusivo)
    (22, 59, "info"),     # fuera
])
async def test_ventana_cruza_medianoche(build, hh, mm, expected):
    assert await _category_for(build, "geofenceExit", hh, mm) == expected


# -- perfil desconocido -----------------------------------------------------------
async def test_perfil_desconocido_avisa_y_usa_defecto(build, caplog):
    stub = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]})
    app, rec, _, _, _ = build(traccar_client=stub)
    payload = make_payload("geofenceExit", unique_id=DEVICE_KEY,
                           device_attributes={"ntfyProfile": "no-existe"},
                           event_time=event_time_for_local(2, 0))
    with caplog.at_level(logging.WARNING):
        await post_event(app, payload)
        await post_event(app, payload)
    assert rec.sent[0][3] == "urgent"          # regla por defecto (geofenceExit siempre urgent)
    warnings = [r for r in caplog.records if "ntfyProfile desconocido" in r.message]
    assert len(warnings) == 1                   # una sola vez pese a dos eventos


# -- eventTime / fixTime / reloj -----------------------------------------------------
async def test_usa_fix_time_si_falta_event_time(build):
    stub = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]})
    app, rec, _, _, _ = build(traccar_client=stub)
    payload = make_payload("geofenceExit", unique_id=DEVICE_KEY,
                           device_attributes={"ntfyProfile": "vehiculo"},
                           event_time=event_time_for_local(2, 0))
    payload["event"]["eventTime"] = None
    payload["position"]["fixTime"] = event_time_for_local(2, 0)
    await post_event(app, payload)
    assert rec.sent[0][3] == "urgent"


async def test_usa_reloj_inyectado_si_no_hay_hora_en_el_payload(build):
    stub = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]})
    app, rec, clock, _, _ = build(traccar_client=stub)
    # FakeClock arranca en time.time() real (hora actual real, no controlable
    # aquí); solo comprobamos que classify no falla sin eventTime/fixTime y
    # que produce igualmente un envío.
    payload = make_payload("geofenceExit", unique_id=DEVICE_KEY,
                           device_attributes={"ntfyProfile": "vehiculo"})
    payload["event"]["eventTime"] = None
    payload["position"]["fixTime"] = None
    await post_event(app, payload)
    assert len(rec.sent) == 1


# -- validación al arrancar ---------------------------------------------------------
def test_ventana_inexistente_falla_al_arrancar():
    config = {
        "events": {"geofenceExit": {"enabled": True, "category": "urgent",
                                     "during": [{"window": "no-existe", "category": "info"}]}},
        "windows": {},
    }
    with pytest.raises(ConfigError, match="no-existe"):
        Rules(config)


def test_hora_invalida_falla_al_arrancar():
    config = {"events": {}, "windows": {"noche": {"from": "25:00", "to": "06:00"}}}
    with pytest.raises(ConfigError):
        Rules(config)


def test_categoria_invalida_falla_al_arrancar():
    config = {"events": {"geofenceExit": {"enabled": True, "category": "muy-urgente"}}}
    with pytest.raises(ConfigError, match="muy-urgente"):
        Rules(config)


def test_categoria_invalida_en_during_falla_al_arrancar():
    config = {
        "windows": {"noche": {"from": "23:00", "to": "06:00"}},
        "profiles": {"vehiculo": {"geofenceExit": {
            "enabled": True, "category": "info",
            "during": [{"window": "noche", "category": "catastrofico"}],
        }}},
    }
    with pytest.raises(ConfigError, match="catastrofico"):
        Rules(config)
