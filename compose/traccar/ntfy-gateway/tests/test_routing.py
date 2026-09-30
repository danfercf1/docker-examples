"""Enrutamiento de avisos a destinatarios (resolve_topics en app.main),
con un StubTraccarClient controlado por prueba. La construcción real del
mapa dispositivo -> destinatarios (vía la API de Traccar) se prueba en
test_traccar_client.py."""

import logging

from conftest import make_payload, post_event, StubTraccarClient
from app.traccar_client import Recipient

DEVICE_KEY = "1234567890"


async def test_dos_usuarios_con_tema_dos_envios(build):
    stub = StubTraccarClient(device_map={
        DEVICE_KEY: [Recipient("ana", "tema-ana"), Recipient("beto", "tema-beto")],
    })
    app, rec, _, _, _ = build(traccar_client=stub)
    await post_event(app, make_payload("ignitionOn", unique_id=DEVICE_KEY))
    assert len(rec.sent) == 2
    assert {s[0] for s in rec.sent} == {"tema-ana", "tema-beto"}


async def test_dos_usuarios_mismo_tema_un_envio(build):
    stub = StubTraccarClient(device_map={
        DEVICE_KEY: [Recipient("ana", "tema-compartido"), Recipient("beto", "tema-compartido")],
    })
    app, rec, _, _, _ = build(traccar_client=stub)
    await post_event(app, make_payload("ignitionOn", unique_id=DEVICE_KEY))
    assert len(rec.sent) == 1
    assert rec.sent[0][0] == "tema-compartido"


async def test_sin_destinatarios_usa_respaldo_y_avisa_una_vez(build, caplog):
    stub = StubTraccarClient(device_map={})
    app, rec, _, _, _ = build(traccar_client=stub)
    with caplog.at_level(logging.WARNING):
        await post_event(app, make_payload("ignitionOn", unique_id=DEVICE_KEY, name="Auto de prueba"))
        await post_event(app, make_payload("geofenceExit", unique_id=DEVICE_KEY, name="Auto de prueba"))
    assert len(rec.sent) == 2
    assert all(s[0] == "admin-prueba" for s in rec.sent)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                and "sin usuarios con ntfyTopic" in r.message]
    assert len(warnings) == 1
    assert "Auto de prueba" in warnings[0].message
    assert DEVICE_KEY in warnings[0].message


async def test_ntfy_min_category_urgent_filtra_info_sin_respaldo(build):
    # El único destinatario exige urgent; un evento info no califica para
    # él. El dispositivo SÍ tiene un usuario con ntfyTopic (no es el caso
    # de "sin destinatarios"), así que no debe caer al tema de respaldo:
    # no se envía nada.
    stub = StubTraccarClient(device_map={
        DEVICE_KEY: [Recipient("solo-urgente", "tema-urgente", min_category="urgent")],
    })
    app, rec, _, _, _ = build(traccar_client=stub)
    await post_event(app, make_payload("ignitionOn", unique_id=DEVICE_KEY))   # info
    assert rec.sent == []


async def test_ntfy_min_category_urgent_recibe_urgentes(build):
    stub = StubTraccarClient(device_map={
        DEVICE_KEY: [Recipient("solo-urgente", "tema-urgente", min_category="urgent")],
    })
    app, rec, _, _, _ = build(traccar_client=stub)
    await post_event(app, make_payload("alarm", alarm="sos", unique_id=DEVICE_KEY))  # urgent
    assert len(rec.sent) == 1
    assert rec.sent[0][0] == "tema-urgente"


async def test_api_caida_con_cache_usa_cache(build):
    stub = StubTraccarClient(
        device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]},
        has_cache=True,
    )
    app, rec, _, _, _ = build(traccar_client=stub)
    await post_event(app, make_payload("ignitionOn", unique_id=DEVICE_KEY))
    assert len(rec.sent) == 1
    assert rec.sent[0][0] == "tema-ana"


async def test_api_caida_sin_cache_usa_respaldo(build, caplog):
    stub = StubTraccarClient(device_map={DEVICE_KEY: [Recipient("ana", "tema-ana")]}, has_cache=False)
    app, rec, _, _, _ = build(traccar_client=stub)
    with caplog.at_level(logging.WARNING):
        await post_event(app, make_payload("alarm", alarm="sos", unique_id=DEVICE_KEY))
    assert len(rec.sent) == 1
    assert rec.sent[0][0] == "admin-prueba"
    assert any("sin caché" in r.message for r in caplog.records)
