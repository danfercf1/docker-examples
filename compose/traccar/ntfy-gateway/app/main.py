"""Gateway event.forward (Traccar) -> ntfy.sh.

Responde 200 rápido; el envío a ntfy es una tarea asyncio en segundo plano
con reintentos, y nunca bloquea ni devuelve error a Traccar.

La app se crea con la fábrica (uvicorn --factory); no hay instancia a nivel
de módulo, así que importar el módulo en los tests no exige variables de
entorno.
"""

import asyncio
import contextlib
import logging
import pathlib
import secrets
import time

import yaml
from fastapi import FastAPI, Request, HTTPException

from .settings import Settings, load_settings
from .rules import Rules, Alert
from .scheduler import OfflineScheduler
from .notify import Notifier, format_alert

log = logging.getLogger(__name__)
CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config" / "events.yaml"
SCHEDULER_INTERVAL_SECONDS = 15


def create_app(settings: Settings | None = None, rules: Rules | None = None,
               clock=None) -> FastAPI:
    clock = clock or time.time
    settings = settings or load_settings()
    if rules is None:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            rules = Rules(yaml.safe_load(f), cooldown_minutes=settings.cooldown_minutes,
                          clock=clock)

    notifier = Notifier(settings.ntfy_url, settings.ntfy_topic)
    send_tasks: set[asyncio.Task] = set()

    def dispatch(alert: Alert) -> None:
        if not rules.pass_cooldown(alert):
            log.debug("cooldown: omitido %s para %s", alert.key, alert.device_key)
            return
        title, body, click = format_alert(alert)
        task = asyncio.create_task(app.state.notifier.send(title, body, alert.category, click))
        send_tasks.add(task)
        task.add_done_callback(send_tasks.discard)

    offline_rule = rules.offline_sustained_rule()

    def fire_offline(info: dict) -> None:
        alert = Alert(key="offline_sustained", category=info.get("category", "urgent"),
                      title="Sin reportar", device_name=info["device_name"],
                      device_key=info["device_key"], payload=info)
        dispatch(alert)

    scheduler = OfflineScheduler(
        minutes=settings.offline_sustained_minutes, clock=clock, on_fire=fire_offline,
        enabled=offline_rule.get("enabled", False),
        category=offline_rule.get("category", "urgent"),
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async def periodic():
            while True:
                await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
                try:
                    scheduler.check_due()
                except Exception:
                    log.exception("offline_sustained: error en el ciclo periódico")
        task = asyncio.create_task(periodic())
        log.info("gateway listo: topic=%s cooldown=%dmin offline=%dmin",
                 settings.ntfy_topic, settings.cooldown_minutes,
                 settings.offline_sustained_minutes)
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="traccar-ntfy-gateway", lifespan=lifespan)
    app.state.settings = settings
    app.state.rules = rules
    app.state.notifier = notifier
    app.state.scheduler = scheduler
    app.state.send_tasks = send_tasks

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/event")
    async def event(req: Request):
        auth = req.headers.get("authorization", "")
        if not secrets.compare_digest(auth, f"Bearer {settings.gateway_token}"):
            raise HTTPException(status_code=401, detail="token inválido")
        try:
            payload = await req.json()
            scheduler.process(payload)
            for alert in rules.classify(payload):
                dispatch(alert)
        except HTTPException:
            raise
        except Exception:
            # Traccar no debe recibir error por un evento malformado
            log.exception("error procesando evento (se responde 200 igualmente)")
        return {"ok": True}

    return app
