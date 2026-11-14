"""SQLite shared state. Plain SQL so the move to Postgres is a driver swap."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    series TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    visuals TEXT,
    short_spinoff TEXT,
    status TEXT NOT NULL DEFAULT 'backlog'
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER REFERENCES topics(id),
    title TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('long', 'short')),
    series TEXT,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    data TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (job_id, kind, version)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    job_id INTEGER,
    type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    details TEXT,
    cost_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS events_job ON events(job_id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DB:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.lock = threading.Lock()
        self.conn.executescript(SCHEMA)

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def run(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    # settings ---------------------------------------------------------------

    def get_settings(self, defaults: dict) -> dict:
        stored = {r["key"]: json.loads(r["value"]) for r in self.all("SELECT * FROM settings")}
        return {**defaults, **stored}

    def set_setting(self, key: str, value) -> None:
        self.run(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # jobs -------------------------------------------------------------------

    def get_job(self, job_id: int) -> dict | None:
        return self.one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def update_job(self, job_id: int, **fields) -> dict:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.run(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
        return self.get_job(job_id)

    def cost_today(self, agent: str | None = None) -> float:
        sql = "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM events WHERE ts >= ?"
        args: list = [datetime.now(timezone.utc).date().isoformat()]
        if agent:
            sql += " AND agent = ?"
            args.append(agent)
        return round(self.one(sql, tuple(args))["c"], 4)

    def job_cost(self, job_id: int) -> float:
        row = self.one("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM events WHERE job_id = ?", (job_id,))
        return round(row["c"], 4)
