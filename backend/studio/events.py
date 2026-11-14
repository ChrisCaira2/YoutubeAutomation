"""Append-only event log plus a live broadcast to every connected hub."""
import asyncio
import json
from contextlib import contextmanager

from .db import DB, now


class EventBus:
    def __init__(self, db: DB):
        self.db = db
        self.subscribers: set[asyncio.Queue] = set()

    def broadcast(self, kind: str, data: dict) -> None:
        msg = {"kind": kind, "data": data}
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # a stalled browser tab drops messages; it re-syncs on reconnect

    def emit(
        self,
        agent: str,
        type: str,
        message: str,
        job_id: int | None = None,
        severity: str = "info",
        details: dict | None = None,
        cost_usd: float = 0.0,
    ) -> dict:
        event = {
            "ts": now(),
            "agent": agent,
            "job_id": job_id,
            "type": type,
            "severity": severity,
            "message": message,
            "details": details or {},
            "cost_usd": round(cost_usd, 4),
        }
        event["id"] = self.db.run(
            "INSERT INTO events (ts, agent, job_id, type, severity, message, details, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event["ts"], agent, job_id, type, severity, message, json.dumps(event["details"]), event["cost_usd"]),
        )
        self.broadcast("event", event)
        return event

    @contextmanager
    def subscribe(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.subscribers.add(q)
        try:
            yield q
        finally:
            self.subscribers.discard(q)


def recent(db: DB, limit: int = 200, job_id: int | None = None) -> list[dict]:
    if job_id is None:
        rows = db.all("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.all("SELECT * FROM events WHERE job_id = ? ORDER BY id DESC LIMIT ?", (job_id, limit))
    for r in rows:
        r["details"] = json.loads(r["details"] or "{}")
    return list(reversed(rows))
