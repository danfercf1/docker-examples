import json

import httpx

from conftest import make_payload, post_event
from app.notify import Notifier


# Con StubTraccarClient() por defecto (sin destinatarios para ningún
# dispositivo) todo cae al tema de respaldo NTFY_TOPIC_ADMIN: reproduce el
# comportamiento previo a perfiles/destinatarios (compatibilidad).

# -- categorías e interruptores enabled ----------------------------------------
async def test_alarm_urgente(build):
    app, rec, _, _, _ = build()
    r = await post_event(app, make_payload("alarm", alarm="powerCut"))
    assert r.status_code == 200
    assert len(rec.sent) == 1
    topic, title, body, category, click = rec.sent[0]
    assert topic == "admin-prueba"
    assert category == "urgent"
    assert "SinoTrack ST-906L" in title and "Corte de corriente" in title
    assert "9 km/h" in body            # 5 nudos * 1.852 = 9.26 km/h
    assert "Rumbo: 90°" in body
    assert "openstreetmap.org" in click


async def test_evento_info(build):
    app, rec, _, _, _ = build()
    await post_event(app, make_payload("ignitionOn"))
    assert len(rec.sent) == 1
    _, title, _, category, _ = rec.sent[0]
    assert category == "info"
    assert "Contacto encendido" in title


async def test_desactivados_por_defecto_y_no_listados(build):
    app, rec, _, _, _ = build()
    await post_event(app, make_payload("deviceOnline"))
    await post_event(app, make_payload("deviceMoving"))
    await post_event(app, make_payload("media"))                   # tipo no listado
    await post_event(app, make_payload("alarm", alarm="general"))  # alarma no listada
    assert rec.sent == []


# -- override por dispositivo ----------------------------------------------------
async def test_override_por_dispositivo(build):
    app, rec, _, _, _ = build({
        "device_overrides": {
            "1234567890": {"deviceMoving": {"enabled": True, "category": "info"}}
        }
    })
    await post_event(app, make_payload("deviceMoving", unique_id="1234567890"))
    await post_event(app, make_payload("deviceMoving", unique_id="OTRO"))  # sin override
    assert len(rec.sent) == 1
    assert rec.sent[0][1].startswith("SinoTrack ST-906L")


# -- moving_ignition_off -----------------------------------------------------------
async def test_moving_ignition_off(build):
    app, rec, _, _, _ = build()
    # ignition=false -> avisa aunque deviceMoving esté desactivado
    await post_event(app, make_payload("deviceMoving", ignition=False))
    assert len(rec.sent) == 1
    assert "Moviéndose sin contacto" in rec.sent[0][1]

    rec.sent.clear()
    await post_event(app, make_payload("deviceMoving", ignition=True))
    await post_event(app, make_payload("deviceMoving"))  # sin atributo ignition
    assert rec.sent == []


# -- offline_sustained ---------------------------------------------------------------
async def test_offline_sustained_cancelado_por_reconexion(build):
    app, rec, clock, _, _ = build()
    await post_event(app, make_payload("deviceOffline"))
    clock.advance(0.5)                                    # ciclo de 30 s del ST-906L
    await post_event(app, make_payload("deviceOnline"))
    clock.advance(20)
    app.state.scheduler.check_due()
    assert rec.sent == []


async def test_offline_sustained_dispara_tras_minutos(build):
    app, rec, clock, _, _ = build()
    await post_event(app, make_payload("deviceOffline", speed=0.0))
    clock.advance(16)
    app.state.scheduler.check_due()
    import asyncio
    await asyncio.sleep(0)          # deja ejecutar la tarea de envío
    await asyncio.gather(*list(app.state.send_tasks), return_exceptions=True)
    assert len(rec.sent) == 1
    topic, title, body, category, click = rec.sent[0]
    assert topic == "admin-prueba"
    assert category == "urgent"
    assert "Sin reportar" in title
    assert "Sin reportar desde" in body and "15 min" in body
    assert "openstreetmap.org" in click


async def test_offline_sustained_disabled(build):
    app, rec, clock, _, _ = build({"special": {"offline_sustained": {"enabled": False}}})
    await post_event(app, make_payload("deviceOffline"))
    clock.advance(16)
    app.state.scheduler.check_due()
    assert rec.sent == []


# -- cooldown ---------------------------------------------------------------------------
async def test_cooldown(build):
    app, rec, clock, _, _ = build()
    await post_event(app, make_payload("alarm", alarm="sos"))
    await post_event(app, make_payload("alarm", alarm="sos"))
    assert len(rec.sent) == 1                      # el segundo queda en cooldown
    clock.advance(11)
    await post_event(app, make_payload("alarm", alarm="sos"))
    assert len(rec.sent) == 2


# -- token ---------------------------------------------------------------------------
async def test_token(build):
    app, rec, _, _, _ = build()
    r = await post_event(app, make_payload("alarm", alarm="sos"), token=None)
    assert r.status_code == 401
    r = await post_event(app, make_payload("alarm", alarm="sos"), token="malo")
    assert r.status_code == 401
    assert rec.sent == []


# -- ntfy no bloquea ------------------------------------------------------------------------
async def test_ntfy_fallo_no_bloquea(build, monkeypatch):
    app, rec, _, _, _ = build()

    class Boom:
        async def send(self, *a, **k):
            raise ConnectionError("ntfy caído")

    monkeypatch.setattr(app.state, "notifier", Boom())
    r = await post_event(app, make_payload("alarm", alarm="sos"))
    assert r.status_code == 200     # el error de ntfy no llega a Traccar


# -- notificación JSON con tildes --------------------------------------------------------------
async def test_ntfy_json_utf8(monkeypatch):
    cuerpos = []

    def handler(request: httpx.Request) -> httpx.Response:
        cuerpos.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ctx = type("Ctx", (), {})
    ctx.__aenter__ = lambda self: mock_client.__aenter__()
    ctx.__aexit__ = lambda self, *a: mock_client.__aexit__(*a)

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: ctx())

    notifier = Notifier("http://ntfy.test")
    ok = await notifier.send("alertas-prueba", "Auto: Vibración detectada",
                             "Hora: 2026-09-29 17:00", "urgent",
                             "https://www.openstreetmap.org/?mlat=-17.78&mlon=-63.18")
    assert ok is True
    assert len(cuerpos) == 1
    body = cuerpos[0]
    assert body["topic"] == "alertas-prueba"
    assert body["title"] == "Auto: Vibración detectada"     # tildes intactas en el JSON
    assert body["message"] == "Hora: 2026-09-29 17:00"
    assert body["priority"] == 5
    assert body["tags"] == ["rotating_light"]
    assert "openstreetmap.org" in body["click"]
    await mock_client.aclose()
