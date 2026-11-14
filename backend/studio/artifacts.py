"""Versioned handoff artifacts, each validated against its JSON schema on write."""
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .db import DB, now

SCHEMA_DIR = Path(__file__).parent / "schemas"


@lru_cache
def validator(kind: str) -> Draft202012Validator:
    path = SCHEMA_DIR / f"{kind}.json"
    if not path.exists():
        raise KeyError(f"no schema for artifact kind '{kind}'")
    return Draft202012Validator(json.loads(path.read_text()))


def kinds() -> list[str]:
    return sorted(p.stem for p in SCHEMA_DIR.glob("*.json"))


class InvalidArtifact(ValueError):
    pass


def validate(kind: str, data: dict) -> None:
    errors = sorted(validator(kind).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        raise InvalidArtifact(f"{kind} invalid at {where}: {first.message}")


def save(db: DB, job_id: int, kind: str, data: dict, created_by: str) -> int:
    validate(kind, data)
    row = db.one("SELECT COALESCE(MAX(version), 0) AS v FROM artifacts WHERE job_id = ? AND kind = ?", (job_id, kind))
    version = row["v"] + 1
    db.run(
        "INSERT INTO artifacts (job_id, kind, version, data, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (job_id, kind, version, json.dumps(data), created_by, now()),
    )
    return version


def latest(db: DB, job_id: int, kind: str) -> dict | None:
    row = db.one(
        "SELECT data FROM artifacts WHERE job_id = ? AND kind = ? ORDER BY version DESC LIMIT 1", (job_id, kind)
    )
    return json.loads(row["data"]) if row else None


def for_job(db: DB, job_id: int) -> list[dict]:
    rows = db.all("SELECT * FROM artifacts WHERE job_id = ? ORDER BY kind, version", (job_id,))
    for r in rows:
        r["data"] = json.loads(r["data"])
    return rows
