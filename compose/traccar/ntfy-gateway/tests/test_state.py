"""Persistencia SQLite: migraciones, sobrevivir a un reinicio del gateway,
sent_log/retención/history, y que no se guarden temas ni tokens."""

import asyncio
import sqlite3
from dataclasses import replace

from app.main import create_app
from app.rules import Rules
from app.state import State, _SCHEMA_STEPS
from app.traccar_client import Recipient
from conftest import (FAKE_SETTINGS, FakeClock, Recorder, StubTraccarClient, app_lifespan,
                      base_config, get_history, make_payload, post_event)

DEVICE_KEY = "1234567890"
OTHER_DEVICE_KEY = "9999999999"


# -- migraciones --------------------------------------------------------------------
def test_migracion_desde_base_vacia(db_path):
    state = State(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA user_version;").fetchone()[0] == len(_SCHEMA_STEPS)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"pending_offline", "cooldowns", "sent_log", "kv_state"} <= tables
    conn.close()
    state.close()


def test_migracion_idempotente_desde_version_anterior(db_path):
    state1 = State(db_path)
    state1.save_cooldown("dev", "alarm:sos", 123.0)
    state1.close()

    state2 = State(db_path)   # reabre una base ya migrada: no debe fallar ni duplicar
    assert state2.load_all_cooldowns() == {("dev", "alarm:sos"): 123.0}
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA user_version;").fetchone()[0] == len(_SCHEMA_STEPS)
    conn.close()
    state2.close()


# -- sent_log / retención / history --------------------------------------------------
def test_retencion_sent_log(db_path):
    state = State(db_path)
    now = 1_000_000.0
    state.log_sent(now - 200 * 86400, "d", "Auto", "alarm:sos", "urgent", "ana", "ok", "t")
    state.log_sent(now - 10 * 86400, "d", "Auto", "alarm:sos", "urgent", "ana", "ok", "t")
    purged = state.purge_sent_log(90, now)
    assert purged == 1
    assert len(state.recent_sent(10)) == 1
    state.close()


async def test_sent_log_registra_resultado_ok_y_error(build):
    class NotifierParcial:
        def __init__(self):
            self.calls = 0
        async def send(self, topic, title, body, category, click=None):
            self.calls += 1
            return self.calls == 1   # el primer envío ok, el resto falla

    stub = StubTraccarClient(device_map={
        DEVICE_KEY: [Recipient("ana", "tema-ana"), Recipient("beto", "tema-beto")],
    })
    app, _, clock, state, _ = build(traccar_client=stub)
    app.state.notifier = NotifierParcial()
    await post_event(app, make_payload("alarm", alarm="sos", unique_id=DEVICE_KEY))
    rows = state.recent_sent(10)
    assert len(rows) == 2
    results = {row["recipient"]: row["result"] for row in rows}
    assert results == {"ana": "ok", "beto": "error"} or results == {"ana": "error", "beto": "ok"}
    assert "ok" in results.values() and "error" in results.values()


async def test_sent_log_no_guarda_temas_ni_tokens(build):
    stub = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-secreto-xyz")]})
    app, _, clock, state, _ = build(traccar_client=stub)
    await post_event(app, make_payload("alarm", alarm="sos", unique_id=DEVICE_KEY))
    rows = state.recent_sent(10)
    dumped = str(rows)
    assert "tema-secreto-xyz" not in dumped
    assert "token-prueba" not in dumped


async def test_history_endpoint_exige_token_y_devuelve_entradas(build):
    stub = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]})
    app, _, clock, state, _ = build(traccar_client=stub)
    await post_event(app, make_payload("alarm", alarm="sos", unique_id=DEVICE_KEY))

    r = await get_history(app, token=None)
    assert r.status_code == 401

    r = await get_history(app, limit=5)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["recipient"] == "ana"


# -- persistencia tras "reiniciar" el gateway ----------------------------------------
def _settings(db_path):
    return replace(FAKE_SETTINGS, state_db=db_path)


async def test_cooldown_y_temporizador_vigente_sobreviven_al_reinicio(db_path):
    settings = _settings(db_path)
    clock = FakeClock()

    device_map = {DEVICE_KEY: [Recipient("ana", "tema-ana")],
                  OTHER_DEVICE_KEY: [Recipient("ana", "tema-ana")]}

    rules1 = Rules(base_config(), cooldown_minutes=settings.cooldown_minutes, clock=clock)
    state1 = State(db_path)
    stub1 = StubTraccarClient(device_map=device_map)
    app1 = create_app(settings=settings, rules=rules1, clock=clock, state=state1, traccar_client=stub1)
    rec1 = Recorder()
    app1.state.notifier = rec1
    async with app_lifespan(app1):
        # Dispositivo distinto: un evento del MISMO dispositivo que el
        # offline_sustained cancelaría su temporizador (comportamiento
        # esperado), así que la alarma de cooldown va en otro dispositivo.
        await post_event(app1, make_payload("alarm", alarm="sos", unique_id=OTHER_DEVICE_KEY))
        await post_event(app1, make_payload("deviceOffline", unique_id=DEVICE_KEY))
        assert len(rec1.sent) == 1   # solo la alarma; offline_sustained aún no vence

    clock.advance(5)   # < 15 min: el temporizador sigue vigente al "reiniciar"

    rules2 = Rules(base_config(), cooldown_minutes=settings.cooldown_minutes, clock=clock)
    state2 = State(db_path)
    stub2 = StubTraccarClient(device_map=device_map)
    app2 = create_app(settings=settings, rules=rules2, clock=clock, state=state2, traccar_client=stub2)
    rec2 = Recorder()
    app2.state.notifier = rec2
    async with app_lifespan(app2):
        # cooldown restaurado: repetir la misma alarma sigue bloqueada
        await post_event(app2, make_payload("alarm", alarm="sos", unique_id=OTHER_DEVICE_KEY))
        assert rec2.sent == []
        # el temporizador pendiente sigue vivo: aún no disparó al restaurar
        assert len(app2.state.scheduler._pending) == 1

        clock.advance(11)   # total 16 min desde el deviceOffline: ahora sí vence
        app2.state.scheduler.check_due()
        await asyncio.gather(*list(app2.state.send_tasks), return_exceptions=True)
        assert any("Sin reportar" in s[1] for s in rec2.sent)


async def _restart_with_expired_timer(db_path, device_status):
    settings = _settings(db_path)
    clock = FakeClock()

    rules1 = Rules(base_config(), cooldown_minutes=settings.cooldown_minutes, clock=clock)
    state1 = State(db_path)
    stub1 = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]})
    app1 = create_app(settings=settings, rules=rules1, clock=clock, state=state1, traccar_client=stub1)
    app1.state.notifier = Recorder()
    async with app_lifespan(app1):
        await post_event(app1, make_payload("deviceOffline", unique_id=DEVICE_KEY))

    clock.advance(20)   # > 15 min: vencido "durante la caída" del gateway

    rules2 = Rules(base_config(), cooldown_minutes=settings.cooldown_minutes, clock=clock)
    state2 = State(db_path)
    statuses = {DEVICE_KEY: device_status} if device_status is not None else {}
    stub2 = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]},
                              device_statuses=statuses)
    app2 = create_app(settings=settings, rules=rules2, clock=clock, state=state2, traccar_client=stub2)
    rec2 = Recorder()
    app2.state.notifier = rec2
    async with app_lifespan(app2):
        await asyncio.gather(*list(app2.state.send_tasks), return_exceptions=True)
    return rec2


async def test_temporizador_vencido_dispositivo_reconectado_se_cancela(db_path):
    rec2 = await _restart_with_expired_timer(db_path, {"status": "online", "lastUpdate": None})
    assert rec2.sent == []


async def test_temporizador_vencido_dispositivo_sigue_offline_dispara_con_nota(db_path):
    rec2 = await _restart_with_expired_timer(
        db_path, {"status": "offline", "lastUpdate": "2020-01-01T00:00:00.000Z"})
    assert len(rec2.sent) == 1
    assert "reinicio del gateway" in rec2.sent[0][2]


async def test_temporizador_vencido_api_caida_dispara_igual(db_path):
    rec2 = await _restart_with_expired_timer(db_path, None)
    assert len(rec2.sent) == 1
    assert "reinicio del gateway" in rec2.sent[0][2]
