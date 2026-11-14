"""Stage 3b: turn the signals' peaks into saved candidate moments. Free: nothing here calls Claude."""
import json
import time

from . import signals
from .db import DB, now


def run(cfg: dict, db: DB, source_id: int, log=None) -> int:
    """Measure what's new and save any moment not already found. Running it again finds nothing twice."""
    source = db.source(source_id)
    signals.measure(cfg, db, source_id, log)
    known = [c["peak"] for c in db.candidates(source_id)]
    gap = cfg["detect"]["min_gap_seconds"]
    added = 0
    for m in signals.moments(cfg, db, source_id, finished=source["status"] == "ready"):
        if any(abs(m["peak"] - k) < gap for k in known):  # a live stream's peaks move a little as more of it arrives
            continue
        db.run("INSERT OR IGNORE INTO candidates (source_id, peak, signal, signals, created_at) VALUES (?, ?, ?, ?, ?)",
               (source_id, m["peak"], m["signal"], json.dumps(m["signals"]), now()))
        known.append(m["peak"])
        added += 1
    signals.write_debug(cfg, db, source_id)
    if log:
        log.info("Source %s: %d new moments (%d in all).", source_id, added, len(known))
    return added


def follow(cfg: dict, db: DB, log=None) -> None:
    """Keep finding moments in sources as their pieces are transcribed, live ones included."""
    while True:
        busy = db.all("SELECT DISTINCT source_id FROM segments WHERE status = 'transcribed'")
        for row in busy:
            run(cfg, db, row["source_id"], log)
        time.sleep(cfg["ingest"]["live_poll_seconds"] * 6)
