"""Estado persistente en SQLite (stdlib): temporizadores, cooldowns, historial.

Un solo worker de uvicorn accede a este archivo: sqlite3 no resuelve bien la
escritura concurrente entre procesos, y no la necesitamos (event.forward de
Traccar es de bajo volumen). Modo WAL para que /history pueda leer mientras
se escribe un evento.

El volumen que contiene STATE_DB no forma parte de las copias de seguridad:
es reconstruible (se pierden cooldowns e historial, no hay pérdida de datos
de Traccar).
"""

import json
import logging
import pathlib
import sqlite3

log = logging.getLogger(__name__)

_SCHEMA_STEPS = [
    """
    CREATE TABLE pending_offline (
        device_key TEXT PRIMARY KEY,
        device_name TEXT NOT NULL,
        since REAL NOT NULL,
        deadline REAL NOT NULL,
        last_position TEXT
    );
    """,
    """
    CREATE TABLE cooldowns (
        device_key TEXT NOT NULL,
        alert_key TEXT NOT NULL,
        last_sent REAL NOT NULL,
        PRIMARY KEY (device_key, alert_key)
    );
    """,
    """
    CREATE TABLE sent_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        device_key TEXT NOT NULL,
        device_name TEXT NOT NULL,
        alert_key TEXT NOT NULL,
        category TEXT NOT NULL,
        recipient TEXT NOT NULL,
        result TEXT NOT NULL,
        title TEXT NOT NULL
    );
    """,
    "CREATE INDEX idx_sent_log_ts ON sent_log(ts);",
    """
    CREATE TABLE kv_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


class State:
    """Envuelve la conexión sqlite3. No es segura para hilos concurrentes;
    uvicorn corre con un solo worker y asyncio es monohilo, así que basta."""

    def __init__(self, db_path: str):
        path = pathlib.Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version;").fetchone()[0]
        target = len(_SCHEMA_STEPS)
        if version >= target:
            return
        with self._conn:
            for step in _SCHEMA_STEPS[version:]:
                self._conn.execute(step)
            self._conn.execute(f"PRAGMA user_version = {target};")
        log.info("state: esquema migrado de versión %d a %d", version, target)

    # -- pending_offline --------------------------------------------------
    def save_pending(self, device_key: str, device_name: str, since: float,
                      deadline: float, last_position: dict | None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO pending_offline "
                "(device_key, device_name, since, deadline, last_position) "
                "VALUES (?, ?, ?, ?, ?)",
                (device_key, device_name, since, deadline,
                 json.dumps(last_position) if last_position is not None else None),
            )

    def delete_pending(self, device_key: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM pending_offline WHERE device_key = ?", (device_key,))

    def load_all_pending(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT device_key, device_name, since, deadline, last_position FROM pending_offline"
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "device_key": row["device_key"],
                "device_name": row["device_name"],
                "since": row["since"],
                "deadline": row["deadline"],
                "last_position": json.loads(row["last_position"]) if row["last_position"] else None,
            })
        return result

    # -- cooldowns ----------------------------------------------------------
    def save_cooldown(self, device_key: str, alert_key: str, last_sent: float) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO cooldowns (device_key, alert_key, last_sent) VALUES (?, ?, ?)",
                (device_key, alert_key, last_sent),
            )

    def load_all_cooldowns(self) -> dict:
        rows = self._conn.execute("SELECT device_key, alert_key, last_sent FROM cooldowns").fetchall()
        return {(row["device_key"], row["alert_key"]): row["last_sent"] for row in rows}

    # -- sent_log -------------------------------------------------------------
    def log_sent(self, ts: float, device_key: str, device_name: str, alert_key: str,
                 category: str, recipient: str, result: str, title: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO sent_log (ts, device_key, device_name, alert_key, category, "
                "recipient, result, title) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, device_key, device_name, alert_key, category, recipient, result, title),
            )

    def recent_sent(self, limit: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts, device_key, device_name, alert_key, category, recipient, result, title "
            "FROM sent_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def purge_sent_log(self, older_than_days: float, now: float) -> int:
        cutoff = now - older_than_days * 86400.0
        with self._conn:
            cur = self._conn.execute("DELETE FROM sent_log WHERE ts < ?", (cutoff,))
            return cur.rowcount

    # -- kv_state (estado singular: última alerta de token, etc.) --------------
    def get_kv(self, key: str, default=None):
        row = self._conn.execute("SELECT value FROM kv_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_kv(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv_state (key, value) VALUES (?, ?)", (key, value)
            )
