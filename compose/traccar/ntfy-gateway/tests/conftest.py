import pathlib
import time

import pytest
import yaml

from app.settings import Settings
from app.rules import Rules
from app.main import create_app


FAKE_SETTINGS = Settings(
    gateway_token="token-prueba",
    ntfy_url="http://ntfy.test",
    ntfy_topic="alertas-prueba",
    cooldown_minutes=10,
    offline_sustained_minutes=15,
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
                 lat=-17.78, lon=-63.18, address=None):
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
            "eventTime": "2026-09-29T21:00:00.000Z",
            "deviceId": 1,
            "positionId": 10,
            "attributes": eattrs,
        },
        "position": {
            "latitude": lat, "longitude": lon,
            "speed": speed, "course": course,
            "deviceTime": "2026-09-29T21:00:00.000Z",
            "fixTime": "2026-09-29T21:00:00.000Z",
            "attributes": pattrs,
        },
        "device": {"id": 1, "name": name, "uniqueId": unique_id, "status": "online"},
    }


class Recorder:
    """Notifier falso: registra (title, body, category, click) de cada envío."""

    def __init__(self):
        self.sent = []

    async def send(self, title, body, category, click=None):
        self.sent.append((title, body, category, click))
        return True


@pytest.fixture
def build():
    """Fábrica: build(config_overrides=None) -> (app, recorder, clock)."""
    def _build(config_overrides=None):
        clock = FakeClock()
        config = base_config()
        for section, values in (config_overrides or {}).items():
            if isinstance(values, dict) and isinstance(config.get(section), dict):
                config[section].update(values)
            else:
                config[section] = values
        rules = Rules(config, cooldown_minutes=FAKE_SETTINGS.cooldown_minutes, clock=clock)
        recorder = Recorder()
        app = create_app(settings=FAKE_SETTINGS, rules=rules, clock=clock)
        app.state.notifier = recorder
        return app, recorder, clock
    return _build
