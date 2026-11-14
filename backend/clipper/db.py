"""SQLite: what's been ingested and how far each piece has got, so every stage can stop and pick up again."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    channel_url TEXT NOT NULL UNIQUE,
    permission TEXT NOT NULL DEFAULT 'unknown' CHECK (permission IN ('permitted', 'unknown', 'refused')),
    watch INTEGER NOT NULL DEFAULT 0,
    facecam TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,              -- platform and video or stream id: the same VOD under two URLs is one source
    creator_id INTEGER REFERENCES creators(id),
    platform TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('vod', 'live', 'file')),
    url TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL CHECK (status IN ('downloading', 'recording', 'ready', 'error')),
    chat TEXT NOT NULL DEFAULT 'none' CHECK (chat IN ('none', 'fetching', 'done', 'unavailable')),
    path TEXT,
    duration REAL,
    window_start REAL NOT NULL DEFAULT 0,  -- where a VOD taken in part begins, so a clip can point back to the full VOD
    window_end REAL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    idx INTEGER NOT NULL,
    path TEXT NOT NULL,
    start REAL NOT NULL,                   -- seconds into the whole source
    offset REAL NOT NULL,                  -- seconds into this piece's file (a VOD's pieces share one file)
    duration REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded', 'transcribed', 'error')),
    words_path TEXT,
    error TEXT,
    UNIQUE (source_id, idx)
);
CREATE TABLE IF NOT EXISTS chat (
    source_id INTEGER NOT NULL REFERENCES sources(id),
    t REAL NOT NULL,                       -- seconds into the source
    author TEXT,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_by_time ON chat (source_id, t);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    peak REAL NOT NULL,                    -- seconds into the source where the signals peaked
    signal REAL NOT NULL,                  -- the signals' combined score at the peak
    signals TEXT NOT NULL,                 -- JSON: which signals fired, and how strongly
    status TEXT NOT NULL DEFAULT 'found' CHECK (status IN ('found', 'judged', 'dropped', 'error')),
    start REAL,                            -- the cut, on word boundaries, once judged
    end REAL,
    scores TEXT,                           -- JSON: Claude's hook, standalone and payoff, 0-10
    score REAL,                            -- the final rank: Claude and the signals combined
    moment TEXT,
    title TEXT,
    caption TEXT,
    hashtags TEXT,                         -- JSON list
    reason TEXT,
    created_at TEXT NOT NULL,
    judged_at TEXT,
    UNIQUE (source_id, peak)
);
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL UNIQUE REFERENCES candidates(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    path TEXT NOT NULL,
    poster TEXT NOT NULL,
    layout TEXT NOT NULL,                  -- "stack" (facecam over gameplay) or "blur" (gameplay over a blurred copy)
    duration REAL NOT NULL,
    lufs REAL,
    status TEXT NOT NULL DEFAULT 'edited' CHECK (status IN ('edited', 'approved', 'rejected', 'uploaded')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spend (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    stage TEXT NOT NULL,
    source_id INTEGER,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    usd REAL NOT NULL
);
"""
COLUMNS_ADDED = [("sources", "window_start", "REAL NOT NULL DEFAULT 0"), ("sources", "window_end", "REAL"),
                 ("sources", "facecam", "TEXT"),        # JSON: {"box": [left, top, right, bottom] as shares of the frame, or null; "by": ...}
                 ("sources", "trashed_at", "TEXT"),     # when the video went to the Trash; its words and moments stay
                 ("sources", "stop_requested", "INTEGER NOT NULL DEFAULT 0"),  # the hub's Stop button; the recorder checks it
                 ("sources", "followed_at", "TEXT")]    # when a `follow` loop last worked on it, so nothing else processes it too


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # Autocommit, shared by the hub's request threads behind one lock. Live chat and the worker open their own.
        self.conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.lock = threading.Lock()
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        for table, column, kind in COLUMNS_ADDED:  # databases made before a column existed get it
            if column not in {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        with self.lock:
            row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def run(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    # creators ---------------------------------------------------------------------

    def creator(self, name: str, platform: str, channel_url: str) -> dict:
        """The creator behind a channel, added with unknown permission the first time they're seen."""
        self.run("INSERT OR IGNORE INTO creators (name, platform, channel_url, created_at) VALUES (?, ?, ?, ?)", (name, platform, channel_url, now()))
        return self.one("SELECT * FROM creators WHERE channel_url = ?", (channel_url,))

    def set_creator(self, creator_id: int, **fields) -> dict:
        self.run(f"UPDATE creators SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), creator_id))
        return self.one("SELECT * FROM creators WHERE id = ?", (creator_id,))

    # sources ----------------------------------------------------------------------

    def source(self, source_id: int) -> dict | None:
        return self.one("SELECT * FROM sources WHERE id = ?", (source_id,))

    def source_by_key(self, key: str) -> dict | None:
        return self.one("SELECT * FROM sources WHERE key = ?", (key,))

    def add_source(self, **fields) -> dict:
        fields = {**fields, "created_at": now(), "updated_at": now()}
        source_id = self.run(f"INSERT INTO sources ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})", tuple(fields.values()))
        return self.source(source_id)

    def set_source(self, source_id: int, **fields) -> dict:
        fields["updated_at"] = now()
        self.run(f"UPDATE sources SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), source_id))
        return self.source(source_id)

    # segments ---------------------------------------------------------------------

    def add_segment(self, source_id: int, idx: int, path: Path, start: float, offset: float, duration: float) -> None:
        self.run("INSERT OR IGNORE INTO segments (source_id, idx, path, start, offset, duration) VALUES (?, ?, ?, ?, ?, ?)",
                 (source_id, idx, str(path), round(start, 3), round(offset, 3), round(duration, 3)))

    def length(self, source_id: int) -> float:
        """How long a source is: all of it once finished, what's been recorded so far while it's live."""
        source = self.source(source_id)
        return source["duration"] or self.one("SELECT COALESCE(MAX(start + duration), 0) AS t FROM segments WHERE source_id = ?", (source_id,))["t"]

    def live(self, within_seconds: float) -> list[dict]:
        """Sources recording right now: their recorder has checked in within the last few seconds.
        A recorder that died without saying so drops off here instead of showing as live forever."""
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=within_seconds)).isoformat(timespec="milliseconds")
        return self.all("SELECT * FROM sources WHERE status = 'recording' AND updated_at >= ? ORDER BY id", (cutoff,))

    def segments(self, source_id: int) -> list[dict]:
        return self.all("SELECT * FROM segments WHERE source_id = ? ORDER BY idx", (source_id,))

    def pending_segments(self, source_id: int | None = None) -> list[dict]:
        where = "status = 'recorded'" + (" AND source_id = ?" if source_id else "")
        return self.all(f"SELECT * FROM segments WHERE {where} ORDER BY source_id, idx", (source_id,) if source_id else ())

    def set_segment(self, segment_id: int, **fields) -> None:
        self.run(f"UPDATE segments SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), segment_id))

    # chat -------------------------------------------------------------------------

    def add_chat(self, source_id: int, messages: list[tuple[float, str | None, str]]) -> None:
        with self.lock:
            self.conn.executemany("INSERT INTO chat (source_id, t, author, text) VALUES (?, ?, ?, ?)", [(source_id, *m) for m in messages])

    def clear_chat(self, source_id: int) -> None:
        self.run("DELETE FROM chat WHERE source_id = ?", (source_id,))

    # candidates and spend ---------------------------------------------------------

    def candidates(self, source_id: int | None = None, status: str | None = None) -> list[dict]:
        where = [w for w, v in (("source_id = ?", source_id), ("status = ?", status)) if v is not None]
        args = tuple(v for v in (source_id, status) if v is not None)
        return self.all(f"SELECT * FROM candidates {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY score DESC NULLS LAST, signal DESC", args)

    def set_candidate(self, candidate_id: int, **fields) -> None:
        self.run(f"UPDATE candidates SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), candidate_id))

    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.run("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))

    def spent_this_month(self) -> float:
        return self.one("SELECT COALESCE(SUM(usd), 0) AS usd FROM spend WHERE at >= ?", (now()[:7] + "-01",))["usd"]

    def add_spend(self, stage: str, source_id: int | None, model: str, input_tokens: int, output_tokens: int, usd: float) -> None:
        self.run("INSERT INTO spend (at, stage, source_id, model, input_tokens, output_tokens, usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (now(), stage, source_id, model, input_tokens, output_tokens, round(usd, 6)))
