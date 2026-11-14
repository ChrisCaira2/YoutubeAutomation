"""Downloaded and recorded videos go to the Trash a week after clipping, to keep the disk free.

Only once every moment has been judged and every pick edited. Words, moments and finished clips stay;
files you added from this Mac are never touched. Nothing is deleted outright: the Trash can give it back.
"""
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import DB, now

TRASH = Path.home() / ".Trash"


def due(cfg: dict, db: DB, at: datetime | None = None) -> list[dict]:
    """Sources whose video can go: finished, fully clipped, and untouched for the configured days."""
    cutoff = ((at or datetime.now(timezone.utc)) - timedelta(days=cfg["ingest"]["source_trash_days"])).isoformat()
    return db.all(
        "SELECT s.* FROM sources s WHERE s.kind IN ('vod', 'live') AND s.status = 'ready' AND s.trashed_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM candidates c WHERE c.source_id = s.id AND c.status = 'found') "
        "AND NOT EXISTS (SELECT 1 FROM candidates c LEFT JOIN clips k ON k.candidate_id = c.id WHERE c.source_id = s.id AND c.status = 'judged' AND k.id IS NULL) "
        "AND MAX(s.updated_at, COALESCE((SELECT MAX(created_at) FROM clips k WHERE k.source_id = s.id), '')) < ?", (cutoff,))


def run(cfg: dict, db: DB, log=None, trash: Path = TRASH, at: datetime | None = None) -> int:
    moved = 0
    for source in due(cfg, db, at):
        stamp = now()[:19].replace(":", "-")
        for piece in {s["path"] for s in db.segments(source["id"])}:
            path = Path(piece)
            if path.exists():
                shutil.move(str(path), str(trash / f"clipper-source-{source['id']:05}-{stamp}-{path.name}"))
        live = cfg["paths"]["media"] / "sources" / f"{source['id']:05}" / "live"
        if live.exists():
            shutil.move(str(live), str(trash / f"clipper-source-{source['id']:05}-{stamp}-live"))
        db.set_source(source["id"], trashed_at=now())
        moved += 1
        log and log.info("Source %s's video went to the Trash: %s", source["id"], source["title"])
    return moved
