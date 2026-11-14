"""Recover a paid answer that failed the format check, without paying for it again.

Usage (with the studio server stopped):
    ../.venv/bin/python recover_raw.py <job_id> brief

Reformats the newest saved raw answer for that job with the fast model,
validates it, saves it as the job's artifact, and moves the job past the
stage that produced it. Costs about a third of a cent.
"""
import asyncio
import json
import sys

from studio import artifacts, config
from studio.api import build
from studio.llm import Claude, ClaudeFailed, _schema_problem
from studio.pipeline import ROUTES

PRODUCED_AT = {route.produces: stage for stage, route in ROUTES.items()}


async def main(job_id: int, kind: str) -> None:
    sr = build(config.DB_PATH, mode="live")
    db, bus = sr.db, sr.bus
    job = db.get_job(job_id)
    stage = PRODUCED_AT[kind]
    if not job or job["stage"] != stage:
        sys.exit(f"Job {job_id} isn't at the {stage} stage.")
    raws = sorted((config.MEDIA_DIR / f"job-{job_id}" / "raw").glob(f"{kind}-*.txt"))
    if not raws:
        sys.exit(f"No saved raw {kind} for job {job_id}.")
    raw = raws[-1]
    schema = json.loads((artifacts.SCHEMA_DIR / f"{kind}.json").read_text())
    claude = Claude(db, bus)
    data, cost = await claude._repair("research", job, sr.settings(), raw.read_text(), schema, "fields were missing from the format given to the model")
    problem = _schema_problem(schema, data)
    if problem:
        raise ClaudeFailed(f"Recovered {kind} still fails the format check: {problem}")
    version = artifacts.save(db, job_id, kind, data, "research")
    bus.emit("research", "output", f"Recovered {kind} v{version} from the saved paid answer (${cost:.4f}, no new research).", job_id)
    sr.move(job, ROUTES[stage].on_success, note=None, attempts=0)
    db.update_job(job_id, status="active")
    print(f"Recovered {kind} v{version} for job {job_id} for ${cost:.4f}; job moved to {ROUTES[stage].on_success}.")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), sys.argv[2]))
