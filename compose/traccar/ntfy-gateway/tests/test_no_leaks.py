"""Ningún token ni tema de ntfy debe aparecer en los logs, ni en arranque,
ni al procesar eventos, ni al restaurar temporizadores."""

import asyncio
import logging

from conftest import FAKE_SETTINGS, StubTraccarClient, app_lifespan, make_payload, post_event
from app.traccar_client import Recipient

DEVICE_KEY = "1234567890"
SECRETOS = [FAKE_SETTINGS.gateway_token, FAKE_SETTINGS.traccar_api_token,
            "tema-secreto-uno", "tema-secreto-dos"]


async def test_ningun_secreto_en_los_logs(build, caplog):
    stub = StubTraccarClient(device_map={
        DEVICE_KEY: [Recipient("ana", "tema-secreto-uno"), Recipient("beto", "tema-secreto-dos")],
    })
    app, rec, clock, state, _ = build(traccar_client=stub)
    with caplog.at_level(logging.DEBUG):
        async with app_lifespan(app):
            await post_event(app, make_payload("alarm", alarm="sos", unique_id=DEVICE_KEY))
            await post_event(app, make_payload("deviceOffline", unique_id=DEVICE_KEY))
            clock.advance(16)
            app.state.scheduler.check_due()
            await asyncio.sleep(0)
            await asyncio.gather(*list(app.state.send_tasks), return_exceptions=True)

    log_text = caplog.text
    for secreto in SECRETOS:
        assert secreto not in log_text, f"'{secreto}' apareció en los logs"
