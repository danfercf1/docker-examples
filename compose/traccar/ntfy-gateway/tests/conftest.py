import asyncio
import contextlib
import pathlib
import time

import httpx
import pytest
import yaml

from app.settings import Settings
from app.rules import Rules
from app.main import create_app
from app.state import State
from app.traccar_client import Recipient


FAKE_SETTINGS = Settings(
    gateway_token="token-prueba",
    ntfy_url="http://ntfy.test",
    ntfy_topic_admin="admin-prueba",
    cooldown_minutes=10,
    offline_sustained_minutes=15,
    traccar_url="http://traccar.test",
    traccar_api_token="traccar-token-prueba",
    traccar_service_user="service@example.com",
    traccar_cache_seconds=300,
    state_db=":memory:",   # sobreescrito por el fixture `build` con un archivo temporal
    sent_log_days=90,
    log_level="INFO",
)


class FakeClock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now

    def advance(self, minutes):
        self.now += minutes * 60.0


def base_config():
    p = pathlib.Path(__file__).parent.parent / "config" / "events.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_payload(etype, *, alarm=None, ignition=None, speed=5.0, course=90.0,
                 unique_id="1234567890", name="SinoTrack ST-906L",
                 lat=-17.78, lon=-63.18, address=None, event_time="2026-09-29T21:00:00.000Z",
                 device_attributes=None):
    eattrs = {}
    pattrs = {}
    if alarm:
        eattrs["alarm"] = alarm        # event.forward la envía en event.attributes
    if ignition is not None:
        pattrs["ignition"] = ignition
    if address:
        pattrs["address"] = address
    return {
        "event": {
            "type": etype,
            "eventTime": event_time,
            "deviceId": 1,
            "positionId": 10,
            "attributes": eattrs,
        },
        "position": {
            "latitude": lat, "longitude": lon,
            "speed": speed, "course": course,
            "deviceTime": event_time,
            "fixTime": event_time,
            "attributes": pattrs,
        },
        "device": {"id": 1, "name": name, "uniqueId": unique_id, "status": "online",
                   "attributes": device_attributes or {}},
    }


class Recorder:
    """Notifier falso: registra (topic, title, body, category, click) de cada envío."""

    def __init__(self):
        self.sent = []

    async def send(self, topic, title, body, category, click=None):
        self.sent.append((topic, title, body, category, click))
        return True


class StubTraccarClient:
    """Sustituto en memoria de TraccarClient, sin HTTP (las pruebas de la
    llamada real a la API viven en test_traccar_client.py con MockTransport)."""

    def __init__(self, device_map=None, has_cache=True, device_statuses=None):
        self.device_map = device_map or {}
        self.has_cache = has_cache
        self.device_statuses = device_statuses or {}
        self.calls = []

    async def get_recipients(self, device_key):
        self.calls.append(device_key)
        return list(self.device_map.get(device_key, [])), self.has_cache

    async def device_status(self, device_key):
        return self.device_statuses.get(device_key)


@pytest.fixture
def build(tmp_path):
    """Fábrica: build(config_overrides=None, **kwargs) -> (app, recorder, clock, state, traccar)."""
    counter = {"n": 0}

    def _build(config_overrides=None, traccar_client=None, settings=None):
        clock = FakeClock()
        config = base_config()
        for section, values in (config_overrides or {}).items():
            if isinstance(values, dict) and isinstance(config.get(section), dict):
                config[section].update(values)
            else:
                config[section] = values
        rules = Rules(config, cooldown_minutes=FAKE_SETTINGS.cooldown_minutes, clock=clock)
        recorder = Recorder()
        traccar = traccar_client if traccar_client is not None else StubTraccarClient()
        counter["n"] += 1
        db_path = tmp_path / f"gateway-{counter['n']}.db"
        state = State(str(db_path))
        used_settings = settings or FAKE_SETTINGS
        app = create_app(settings=used_settings, rules=rules, clock=clock, state=state,
                          traccar_client=traccar)
        app.state.notifier = recorder
        return app, recorder, clock, state, traccar
    return _build


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "gateway.db")


async def post_event(app, payload, token="token-prueba"):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = await client.post("/event", json=payload, headers=headers)
    # drena las tareas de envío en segundo plano para aserciones deterministas
    if r.status_code == 200 and app.state.send_tasks:
        await asyncio.gather(*list(app.state.send_tasks), return_exceptions=True)
    return r


async def get_history(app, limit=50, token="token-prueba"):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = await client.get(f"/history?limit={limit}", headers=headers)
    return r


@contextlib.asynccontextmanager
async def app_lifespan(app):
    """Ejecuta startup/shutdown reales (restauración de pending_offline,
    resumen de arranque). httpx.ASGITransport no los dispara por sí solo."""
    async with app.router.lifespan_context(app):
        yield
