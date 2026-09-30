"""Gateway event.forward (Traccar) -> ntfy.sh.

Responde 200 rápido; el envío a ntfy es una tarea asyncio en segundo plano
con reintentos, y nunca bloquea ni devuelve error a Traccar.

La app se crea con la fábrica (uvicorn --factory); no hay instancia a nivel
de módulo, así que importar el módulo en los tests no exige variables de
entorno.

Un solo worker de uvicorn: SQLite (app/state.py) no está pensado para
escritura concurrente entre procesos, y no la necesitamos (event.forward de
Traccar es de bajo volumen). No añadir `--workers` sin revisar esto.
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
from .notify import Notifier, format_alert, format_token_alert
from .state import State
from .traccar_client import TraccarClient

log = logging.getLogger(__name__)
CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config" / "events.yaml"
SCHEDULER_INTERVAL_SECONDS = 15
PURGE_INTERVAL_SECONDS = 86400
TOKEN_ALERT_COOLDOWN_SECONDS = 24 * 3600
TOKEN_ALERT_KV_KEY = "last_token_alert_ts"


def create_app(settings: Settings | None = None, rules: Rules | None = None,
               clock=None, state: State | None = None,
               traccar_client: TraccarClient | None = None) -> FastAPI:
    clock = clock or time.time
    settings = settings or load_settings()

    # Sin force=True: no debe desmontar handlers ya presentes (p.ej. el de
    # pytest's caplog en tests, o uno instalado por una llamada anterior).
    logging.basicConfig(level=settings.log_level,
                         format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(settings.log_level)

    if rules is None:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            rules = Rules(yaml.safe_load(f), cooldown_minutes=settings.cooldown_minutes,
                          clock=clock)

    state = state or State(settings.state_db)
    notifier = Notifier(settings.ntfy_url)
    send_tasks: set[asyncio.Task] = set()
    warned_no_recipients: set[str] = set()

    def spawn(coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        send_tasks.add(task)
        task.add_done_callback(send_tasks.discard)
        return task

    def on_auth_failure() -> None:
        log.warning("traccar: la API rechazó el token del gateway (401/403)")
        now = clock()
        last = state.get_kv(TOKEN_ALERT_KV_KEY)
        if last is not None and now - float(last) < TOKEN_ALERT_COOLDOWN_SECONDS:
            return
        state.set_kv(TOKEN_ALERT_KV_KEY, str(now))
        title, body = format_token_alert()
        spawn(app.state.notifier.send(settings.ntfy_topic_admin, title, body, "urgent"))

    traccar_client = traccar_client or TraccarClient(
        base_url=settings.traccar_url, token=settings.traccar_api_token,
        cache_seconds=settings.traccar_cache_seconds,
        service_user=settings.traccar_service_user, clock=clock,
        on_auth_failure=on_auth_failure,
    )

    rules.seed_cooldowns(state.load_all_cooldowns())

    async def resolve_topics(alert: Alert) -> dict:
        """device_key -> {topic: [usernames]}. El respaldo NTFY_TOPIC_ADMIN
        solo aplica cuando el dispositivo no tiene NINGÚN usuario con
        ntfyTopic (o no hay caché) — si tiene usuarios pero el filtro de
        ntfyMinCategory los descarta a todos para esta alerta, no se envía
        nada (no es lo mismo que "sin destinatarios configurados")."""
        recipients, has_cache = await app.state.traccar_client.get_recipients(alert.device_key)
        if not has_cache:
            log.warning("traccar: sin caché de destinatarios (API caída y sin datos previos); "
                        "aviso de %s enviado al tema de respaldo", alert.device_name)
            return {settings.ntfy_topic_admin: ["admin"]}

        if not recipients:
            if alert.device_key not in warned_no_recipients:
                warned_no_recipients.add(alert.device_key)
                log.warning("dispositivo sin usuarios con ntfyTopic (nombre=%s, uniqueId=%s); "
                            "usando el tema de respaldo", alert.device_name, alert.device_key)
            return {settings.ntfy_topic_admin: ["admin"]}

        filtered = [r for r in recipients
                    if not (r.min_category == "urgent" and alert.category != "urgent")]
        if not filtered:
            log.debug("todos los destinatarios de %s exigen ntfyMinCategory=urgent; "
                      "%s no calificado, no se envía nada", alert.device_key, alert.category)
            return {}

        topics: dict[str, list[str]] = {}
        for r in filtered:
            topics.setdefault(r.topic, []).append(r.username)
        return topics

    async def send_alert(alert: Alert, title: str, body: str, click) -> None:
        topics = await resolve_topics(alert)
        now = clock()
        for topic, usernames in topics.items():
            ok = await app.state.notifier.send(topic, title, body, alert.category, click)
            for username in usernames:
                app.state.state.log_sent(now, alert.device_key, alert.device_name, alert.key,
                                          alert.category, username, "ok" if ok else "error", title)

    def dispatch(alert: Alert) -> None:
        if not rules.pass_cooldown(alert):
            log.debug("cooldown: omitido %s para %s", alert.key, alert.device_key)
            return
        state.save_cooldown(alert.device_key, alert.key, clock())
        title, body, click = format_alert(alert)
        spawn(send_alert(alert, title, body, click))

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
        state=state,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        cooldowns_restored = rules.cooldown_count()

        recipients, has_cache = await traccar_client.get_recipients("__startup_probe__")
        api_status = "conectado" if has_cache else "sin conexión (se usará el tema de respaldo hasta que responda)"

        await scheduler.restore(traccar_client)

        purged = state.purge_sent_log(settings.sent_log_days, clock())
        if purged:
            log.info("sent_log: purgadas %d entradas de más de %d días al arrancar",
                     purged, settings.sent_log_days)

        log.info(
            "gateway listo: perfiles=%s ventanas=%s cooldown=%dmin offline_sustained=%dmin "
            "api_traccar=%s cooldowns_restaurados=%d",
            rules.profile_names(), rules.window_names(), settings.cooldown_minutes,
            settings.offline_sustained_minutes, api_status, cooldowns_restored,
        )

        async def periodic_scheduler():
            while True:
                await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
                try:
                    scheduler.check_due()
                except Exception:
                    log.exception("offline_sustained: error en el ciclo periódico")

        async def periodic_purge():
            while True:
                await asyncio.sleep(PURGE_INTERVAL_SECONDS)
                try:
                    n = state.purge_sent_log(settings.sent_log_days, clock())
                    if n:
                        log.info("sent_log: purgadas %d entradas de más de %d días", n,
                                 settings.sent_log_days)
                except Exception:
                    log.exception("sent_log: error en la purga periódica")

        tasks = [asyncio.create_task(periodic_scheduler()), asyncio.create_task(periodic_purge())]
        yield
        for t in tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        state.close()

    app = FastAPI(title="traccar-ntfy-gateway", lifespan=lifespan)
    app.state.settings = settings
    app.state.rules = rules
    app.state.notifier = notifier
    app.state.scheduler = scheduler
    app.state.send_tasks = send_tasks
    app.state.state = state
    app.state.traccar_client = traccar_client

    def check_token(req: Request) -> None:
        auth = req.headers.get("authorization", "")
        if not secrets.compare_digest(auth, f"Bearer {settings.gateway_token}"):
            raise HTTPException(status_code=401, detail="token inválido")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/event")
    async def event(req: Request):
        check_token(req)
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

    @app.get("/history")
    def history(req: Request, limit: int = 50):
        check_token(req)
        limit = max(1, min(limit, 500))
        return {"items": app.state.state.recent_sent(limit)}

    return app
