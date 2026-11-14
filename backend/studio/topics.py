"""Load the topic backlog from strategy/topics.md into the database."""
import re
from pathlib import Path

from .db import DB

SERIES = {"Record": "Record Breakers", "Replay": "Instant Replay", "Upset": "Miracles & Upsets"}


def parse_topics(path: Path) -> list[dict]:
    topics = []
    for line in path.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6 or not cells[0].isdigit():
            continue
        num, series, title, year, visuals, short = cells
        topics.append(
            {
                "id": int(num),
                "series": SERIES.get(series, series),
                "title": title,
                "year": int(year) if re.fullmatch(r"\d{4}", year) else None,
                "visuals": visuals,
                "short_spinoff": short,
            }
        )
    return topics


def sync_topics(db: DB, path: Path) -> int:
    """Insert new topics and refresh text of existing ones; never touches status."""
    topics = parse_topics(path)
    for t in topics:
        db.run(
            "INSERT INTO topics (id, series, title, year, visuals, short_spinoff) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET series = excluded.series, title = excluded.title, "
            "year = excluded.year, visuals = excluded.visuals, short_spinoff = excluded.short_spinoff",
            (t["id"], t["series"], t["title"], t["year"], t["visuals"], t["short_spinoff"]),
        )
    return len(topics)
