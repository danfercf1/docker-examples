"""Construcción del mapa dispositivo -> destinatarios desde la API real de
Traccar, simulada con httpx.MockTransport. Cubre el diseño descrito en
docs/MANUAL-ADMIN.md: GET /api/users, GET /api/devices?all=true y
GET /api/devices?userId=, exclusión de la cuenta de servicio, caché con
TTL, refresco por dispositivo desconocido con límite de frecuencia, y el
manejo de 401/403 (token inválido) con la alerta administrativa."""

import httpx

from app.main import create_app
from app.rules import Rules
from app.state import State
from app.traccar_client import TraccarClient
from conftest import FAKE_SETTINGS, FakeClock, Recorder, base_config, make_payload, post_event


def patch_transport(monkeypatch, handler):
    """Redirige a MockTransport solo los clientes SIN transporte propio (los
    que crean TraccarClient/Notifier); deja intactos los que sí lo indican
    (el ASGITransport que usa post_event() para hablar con nuestra app)."""
    real_cls = httpx.AsyncClient

    def factory(*a, **k):
        if a or "transport" in k:
            return real_cls(*a, **k)
        return real_cls(transport=httpx.MockTransport(handler), timeout=k.get("timeout"))
    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_mapa_basico_excluye_sin_topic_y_cuenta_de_servicio(monkeypatch):
    users = [
        {"id": 1, "name": "Ana", "email": "ana@example.com",
         "attributes": {"ntfyTopic": "tema-ana"}},
        {"id": 2, "name": "Beto", "email": "beto@example.com", "attributes": {}},
        {"id": 3, "name": "Servicio", "email": "service@example.com",
         "attributes": {"ntfyTopic": "no-debe-usarse"}},
    ]
    devices = [{"id": 10, "uniqueId": "DEV1", "name": "Auto 1", "status": "online"}]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/users":
            return httpx.Response(200, json=users)
        if path == "/api/devices":
            params = dict(request.url.params)
            if params.get("userId") == "1":
                return httpx.Response(200, json=devices)
            if params.get("userId") == "2":
                return httpx.Response(200, json=[])
            if params.get("all") == "true":
                return httpx.Response(200, json=devices)
        return httpx.Response(404)

    patch_transport(monkeypatch, handler)
    client = TraccarClient("http://traccar.test", "tok", cache_seconds=300,
                           service_user="service@example.com")
    recipients, has_cache = await client.get_recipients("DEV1")
    assert has_cache is True
    assert [r.username for r in recipients] == ["Ana"]
    assert recipients[0].topic == "tema-ana"


async def test_usuario_deshabilitado_omitido(monkeypatch):
    users = [{"id": 1, "name": "Ana", "email": "ana@example.com", "disabled": True,
              "attributes": {"ntfyTopic": "tema-ana"}}]
    devices = [{"id": 10, "uniqueId": "DEV1"}]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/users":
            return httpx.Response(200, json=users)
        if path == "/api/devices":
            return httpx.Response(200, json=devices)
        return httpx.Response(404)

    patch_transport(monkeypatch, handler)
    client = TraccarClient("http://traccar.test", "tok", 300, "service@example.com")
    recipients, _ = await client.get_recipients("DEV1")
    assert recipients == []


async def test_usuario_vencido_omitido(monkeypatch):
    users = [{"id": 1, "name": "Ana", "email": "ana@example.com",
              "expirationTime": "2020-01-01T00:00:00.000+0000",
              "attributes": {"ntfyTopic": "tema-ana"}}]
    devices = [{"id": 10, "uniqueId": "DEV1"}]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/users":
            return httpx.Response(200, json=users)
        if path == "/api/devices":
            return httpx.Response(200, json=devices)
        return httpx.Response(404)

    patch_transport(monkeypatch, handler)
    client = TraccarClient("http://traccar.test", "tok", 300, "service@example.com")
    recipients, _ = await client.get_recipients("DEV1")
    assert recipients == []


async def test_dispositivo_deshabilitado_omitido(monkeypatch):
    users = [{"id": 1, "name": "Ana", "email": "ana@example.com",
              "attributes": {"ntfyTopic": "tema-ana", "ntfyAllDevices": True}}]
    devices = [{"id": 10, "uniqueId": "DEV1", "disabled": True},
               {"id": 11, "uniqueId": "DEV2"}]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/users":
            return httpx.Response(200, json=users)
        if path == "/api/devices":
            return httpx.Response(200, json=devices)
        return httpx.Response(404)

    patch_transport(monkeypatch, handler)
    client = TraccarClient("http://traccar.test", "tok", 300, "service@example.com")
    r_dev1, _ = await client.get_recipients("DEV1")
    r_dev2, _ = await client.get_recipients("DEV2")
    assert r_dev1 == []           # dispositivo deshabilitado: nunca aparece en el mapa
    assert [r.username for r in r_dev2] == ["Ana"]


async def test_ntfy_all_devices_recibe_todo(monkeypatch):
    users = [{"id": 5, "name": "Admin", "email": "admin@example.com",
              "attributes": {"ntfyTopic": "tema-admin", "ntfyAllDevices": True}}]
    devices = [{"id": 10, "uniqueId": "DEV1"}, {"id": 11, "uniqueId": "DEV2"}]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/users":
            return httpx.Response(200, json=users)
        if path == "/api/devices":
            return httpx.Response(200, json=devices)
        return httpx.Response(404)

    patch_transport(monkeypatch, handler)
    client = TraccarClient("http://traccar.test", "tok", 300, "service@example.com")
    r1, _ = await client.get_recipients("DEV1")
    r2, _ = await client.get_recipients("DEV2")
    assert [r.username for r in r1] == ["Admin"]
    assert [r.username for r in r2] == ["Admin"]


async def test_admin_sin_ntfy_all_devices_no_ve_dispositivo_no_vinculado(monkeypatch):
    # Ajuste confirmado: administrator=true ya NO da acceso implícito a todo;
    # solo el atributo ntfyAllDevices lo hace.
    users = [{"id": 7, "name": "AdminNormal", "email": "adminnormal@example.com",
              "administrator": True, "attributes": {"ntfyTopic": "tema-admin-normal"}}]
    devices = [{"id": 10, "uniqueId": "DEV1"}, {"id": 11, "uniqueId": "DEV2"}]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/users":
            return httpx.Response(200, json=users)
        if path == "/api/devices":
            params = dict(request.url.params)
            if params.get("userId") == "7":
                return httpx.Response(200, json=[devices[0]])
            return httpx.Response(200, json=devices)
        return httpx.Response(404)

    patch_transport(monkeypatch, handler)
    client = TraccarClient("http://traccar.test", "tok", 300, "service@example.com")
    r_dev1, _ = await client.get_recipients("DEV1")
    r_dev2, _ = await client.get_recipients("DEV2")
    assert [r.username for r in r_dev1] == ["AdminNormal"]
    assert r_dev2 == []


async def test_cache_se_refresca_tras_ttl(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[])

    patch_transport(monkeypatch, handler)
    clock = FakeClock()
    client = TraccarClient("http://traccar.test", "tok", cache_seconds=100,
                           service_user="x", clock=clock)
    await client.get_recipients("DEV1")
    first = calls["n"]
    await client.get_recipients("DEV1")             # dentro del TTL: no refresca
    assert calls["n"] == first
    clock.advance(2)                                # +120s > 100s
    await client.get_recipients("DEV1")
    assert calls["n"] > first


async def test_refresco_por_dispositivo_desconocido_con_limite_de_frecuencia(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[])

    patch_transport(monkeypatch, handler)
    clock = FakeClock()
    client = TraccarClient("http://traccar.test", "tok", cache_seconds=300,
                           service_user="x", clock=clock)
    await client.get_recipients("DESCONOCIDO")      # primer refresco (caché era None)
    first = calls["n"]
    await client.get_recipients("DESCONOCIDO")      # sigue desconocido, <30s: no refresca
    assert calls["n"] == first
    clock.advance(1)                                # +60s > 30s
    await client.get_recipients("DESCONOCIDO")
    assert calls["n"] > first


async def test_token_invalido_avisa_admin_con_limite_24h(monkeypatch, tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    patch_transport(monkeypatch, handler)
    clock = FakeClock()
    rules = Rules(base_config(), cooldown_minutes=10, clock=clock)
    state = State(str(tmp_path / "gw.db"))
    app = create_app(settings=FAKE_SETTINGS, rules=rules, clock=clock, state=state)
    rec = Recorder()
    app.state.notifier = rec

    await post_event(app, make_payload("alarm", alarm="sos"))
    assert len(rec.sent) == 2                        # alarma (respaldo) + alerta técnica de token
    assert any("token" in s[1].lower() for s in rec.sent)

    rec.sent.clear()
    await post_event(app, make_payload("alarm", alarm="tow"))
    assert len(rec.sent) == 1                        # dentro de 24h: no repite la alerta técnica
    assert "token" not in rec.sent[0][1].lower()

    rec.sent.clear()
    clock.advance(24 * 60 + 1)
    await post_event(app, make_payload("alarm", alarm="vibration"))
    assert len(rec.sent) == 2                        # pasadas 24h: vuelve a avisar
    assert any("token" in s[1].lower() for s in rec.sent)
