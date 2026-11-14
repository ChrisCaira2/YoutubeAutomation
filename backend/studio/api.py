"""FastAPI app: REST for state and actions, server-sent events for the live hub."""
import asyncio
import fcntl
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import artifacts, config, events, forecast, system
from .agents import AGENT_DEFS
from .agents.mock import MockAgent
from .db import DB
from .events import EventBus
from .media import finder
from .pipeline import CHANGE_TARGETS, STAGE_LABELS, STAGES
from .showrunner import Showrunner
from .topics import sync_topics


def single_instance(db_path: str, wait_seconds: float = 15.0):
    """Hold an exclusive lock so two Showrunners never drive the same database.

    A restarted server can overlap the old one while it drains open hub
    connections; the new one waits here until the old one has exited.
    """
    if db_path == ":memory:":
        return None
    lock = open(f"{db_path}.lock", "w")
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except BlockingIOError:
            if time.monotonic() > deadline:
                raise RuntimeError("Another studio is already running on this database. Stop it first.")
            time.sleep(0.25)


LIVE_AGENTS = {"research", "script", "qa", "packaging"}  # Studio has its own class; the Publisher stays mock until its phase
MEDIA_FILES = {"preview.mp4", "final.mp4", "captions.srt", "credits.txt", "contact-sheet.png", "description.txt",
               "thumbnail-a.png", "thumbnail-b.png", "thumbnail-c.png", "thumbnails-phone.png"}


def build(db_path: str = config.DB_PATH, speed: float = config.MOCK_SPEED, mode: str = config.MODE, claude=None) -> Showrunner:
    if mode not in ("mock", "live"):
        raise RuntimeError("STUDIO_MODE must be mock or live.")
    db = DB(db_path)
    bus = EventBus(db)
    sync_topics(db, config.TOPICS_FILE)
    if mode == "mock":
        agents = {name: MockAgent(name, db, bus, speed=speed) for name in AGENT_DEFS if name != "showrunner"}
        return Showrunner(db, bus, agents, mock=True, speed=speed)

    from .agents.live import LiveAgent
    from .agents.studio import StudioAgent
    from .llm import Claude

    problem = None
    if claude is None and not os.getenv("ANTHROPIC_API_KEY"):
        problem = "No ANTHROPIC_API_KEY in .env, so live agents can't run."
    claude = claude or Claude(db, bus)
    settings_fn = lambda: db.get_settings(config.DEFAULT_SETTINGS)  # noqa: E731
    agents = {
        name: LiveAgent(name, claude, settings_fn, db, bus) if name in LIVE_AGENTS else MockAgent(name, db, bus, speed=speed)
        for name in AGENT_DEFS if name != "showrunner"
    }
    agents["studio"] = StudioAgent(settings_fn, claude, db, bus)
    return Showrunner(db, bus, agents, mock=False, halt_stages=config.LIVE_HALT_STAGES, startup_problem=problem)


def create_app(db_path: str = config.DB_PATH, speed: float = config.MOCK_SPEED, run_loop: bool = True) -> FastAPI:
    sr = build(db_path, speed, config.MODE)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        lock = single_instance(db_path) if run_loop else None
        task = asyncio.create_task(sr.run()) if run_loop else None
        yield
        if task:
            task.cancel()
        for t in list(sr.inflight.values()):
            t.cancel()
        if lock:
            lock.close()

    app = FastAPI(title="AI YouTube Studio", lifespan=lifespan)
    app.state.showrunner = sr
    db = sr.db

    def agents_public() -> list[dict]:
        return [sr.public()] + [a.public() for a in sr.agents.values()]

    def jobs_public() -> list[dict]:
        rows = db.all("SELECT * FROM jobs ORDER BY id")
        working = {a.job_id: a.name for a in sr.agents.values() if a.job_id}
        for r in rows:
            r["cost"] = db.job_cost(r["id"])
            r["working"] = working.get(r["id"])
        return rows

    def guard(fn, *args):
        try:
            return fn(*args)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'"))
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    # read ---------------------------------------------------------------------

    @app.get("/api/state")
    def state():
        return {
            "channel": config.CHANNEL_NAME,
            "host": config.HOST_NAME,
            "workspace": config.WORKSPACE,
            "workspaces": [{"id": k, "label": w["label"], "url": f"http://127.0.0.1:{w['port']}", "current": k == config.WORKSPACE}
                           for k, w in {**config.WORKSPACES, **config.WINGS}.items()],
            "mode": config.MODE,
            "stages": [{"id": s, "label": STAGE_LABELS[s]} for s in STAGES],
            "change_targets": list(CHANGE_TARGETS),
            "agents": agents_public(),
            "jobs": jobs_public(),
            "settings": sr.settings(),
            "health": health(),
        }

    @app.get("/api/health")
    def health():
        s = sr.settings()
        return {
            "spent_today": db.cost_today(),
            "daily_budget": s["daily_budget_usd"],
            "queue_depth": db.one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'active' AND stage != 'awaiting_approval'")["n"],
            "awaiting_you": db.one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'active' AND (stage = 'awaiting_approval' OR (stage = 'scripted' AND ?))", (bool(s.get("manual_script_review")),))["n"],
            "blocked": db.one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'blocked'")["n"],
            "errors_today": db.one("SELECT COUNT(*) AS n FROM events WHERE severity = 'error' AND ts >= date('now')")["n"],
            "manual_approvals": db.one("SELECT COUNT(*) AS n FROM events WHERE type = 'approved' AND agent = 'you' AND details NOT LIKE '%script%'")["n"],
            "youtube_quota": None,  # Phase 4+: uploads are manual for now
        }

    @app.get("/api/system")
    def system_load():
        return system.machine()

    @app.get("/api/forecast")
    def cost_forecast(format: str = "long"):
        if format not in ("long", "short"):
            raise HTTPException(422, "format must be long or short")
        # Mock runs rehearse the live setup, where you review scripts yourself.
        manual = True if sr.mock else sr.settings()["manual_script_review"]
        return forecast.forecast(format, manual)

    @app.get("/api/events")
    def list_events(limit: int = 300, job_id: int | None = None):
        return events.recent(db, min(limit, 2000), job_id)

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int):
        job = db.get_job(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job["cost"] = db.job_cost(job_id)
        topic = db.one("SELECT * FROM topics WHERE id = ?", (job["topic_id"],))
        return {"job": job, "topic": topic, "artifacts": artifacts.for_job(db, job_id), "events": events.recent(db, 1000, job_id)}

    @app.get("/api/topics")
    def topics():
        return db.all("SELECT * FROM topics ORDER BY id")

    @app.get("/api/playbook")
    def playbook():
        return json.loads(config.PLAYBOOK_FILE.read_text())

    # actions ------------------------------------------------------------------

    class NewJob(BaseModel):
        topic_id: int
        format: str = "long"
        priority: int = 0

    class Comment(BaseModel):
        comment: str | None = None

    class Changes(BaseModel):
        target: str
        comment: str

    class Reason(BaseModel):
        reason: str

    class Priority(BaseModel):
        priority: int

    @app.post("/api/jobs")
    def new_job(body: NewJob):
        if body.format not in ("long", "short"):
            raise HTTPException(422, "format must be long or short")
        return guard(sr.create_job, body.topic_id, body.format, body.priority)

    class Idea(BaseModel):
        title: str
        format: str = "long"
        notes: str | None = None

    @app.post("/api/ideas")
    def new_idea(body: Idea):
        """Your own video idea: it joins the backlog and research starts right away."""
        title = body.title.strip()
        if not title or body.format not in ("long", "short"):
            raise HTTPException(422, "give the video a title, and a format of long or short")
        topic_id = max(1000, db.one("SELECT COALESCE(MAX(id), 0) AS n FROM topics")["n"] + 1)  # the backlog's own numbers stay below 1000
        db.run("INSERT INTO topics (id, series, title, year, visuals, short_spinoff) VALUES (?, 'Ideas', ?, NULL, ?, 'Yes')", (topic_id, title, (body.notes or "").strip()))
        note = f"Owner's idea: {body.notes.strip()}" if body.notes and body.notes.strip() else None  # research reads it, so it goes in before the job starts
        return guard(sr.create_job, topic_id, body.format, 0, note)

    @app.post("/api/jobs/{job_id}/approve")
    def approve(job_id: int, body: Comment | None = None):
        return guard(sr.approve, job_id, body.comment if body else None)

    @app.post("/api/jobs/{job_id}/request_changes")
    def request_changes(job_id: int, body: Changes):
        return guard(sr.request_changes, job_id, body.target, body.comment)

    @app.post("/api/jobs/{job_id}/approve_script")
    def approve_script(job_id: int, body: Comment | None = None):
        return guard(sr.approve_script, job_id, body.comment if body else None)

    @app.post("/api/jobs/{job_id}/revise_script")
    def revise_script(job_id: int, body: Reason):
        return guard(sr.revise_script, job_id, body.reason)

    @app.post("/api/jobs/{job_id}/redo_render")
    def redo_render(job_id: int):
        return guard(sr.redo_render, job_id)

    @app.post("/api/jobs/{job_id}/redo_slides")
    def redo_slides(job_id: int):
        return guard(sr.redo_slides, job_id)

    @app.post("/api/jobs/{job_id}/redo_research")
    def redo_research(job_id: int, body: Reason):
        return guard(sr.redo_research, job_id, body.reason)

    # These four start a background task, so they must run on the server's event loop, not a worker thread.
    @app.post("/api/jobs/{job_id}/make_shorts")
    async def make_shorts(job_id: int):
        return guard(sr.make_shorts, job_id)

    @app.post("/api/jobs/{job_id}/make_package")
    async def make_package(job_id: int):
        return guard(sr.make_package, job_id)

    @app.post("/api/jobs/{job_id}/expand_narration")
    async def expand_narration(job_id: int, body: Reason):
        return guard(sr.expand_narration, job_id, body.reason)

    class MediaChoice(BaseModel):
        ids: list[str]

    @app.get("/api/jobs/{job_id}/media")
    def media_candidates(job_id: int, refresh: bool = False):
        job = db.get_job(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return guard(finder.candidates, job_id, job["title"], artifacts.latest(db, job_id, "script"), artifacts.latest(db, job_id, "brief"), refresh)

    @app.post("/api/jobs/{job_id}/media")
    def choose_media(job_id: int, body: MediaChoice):
        return guard(sr.choose_media, job_id, body.ids)

    @app.post("/api/jobs/{job_id}/reuse_package")
    def reuse_package(job_id: int):
        return guard(sr.reuse_package, job_id)

    @app.post("/api/jobs/{job_id}/render_final")
    async def render_final(job_id: int):
        return guard(sr.render_final, job_id)

    @app.get("/api/media/{job_id}/{name}")
    def media_file(job_id: int, name: str):
        """Files from a job's own folder only: previews, the final video, captions, the contact sheet."""
        if name not in MEDIA_FILES:
            raise HTTPException(404, "not a media file")
        path = config.MEDIA_DIR / f"job-{job_id}" / name
        if not path.is_file():
            raise HTTPException(404, "not rendered yet")
        return FileResponse(path)

    @app.post("/api/jobs/{job_id}/reject")
    def reject(job_id: int, body: Reason):
        return guard(sr.reject, job_id, body.reason)

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: int, body: Comment | None = None):
        return guard(sr.retry, job_id, body.comment if body else None)

    @app.post("/api/jobs/{job_id}/priority")
    def priority(job_id: int, body: Priority):
        return guard(sr.set_priority, job_id, body.priority)

    @app.post("/api/control/{action}")
    def control(action: str):
        if action not in ("pause", "resume"):
            raise HTTPException(404, "unknown action")
        sr.db.set_setting("paused", action == "pause")
        sr.bus.emit("you", "control", "You paused the studio." if action == "pause" else "You resumed the studio.")
        sr.push_settings()
        return sr.settings()

    @app.post("/api/agents/{name}/{action}")
    def agent_control(name: str, action: str):
        agent = sr.agents.get(name)
        if not agent or action not in ("pause", "resume"):
            raise HTTPException(404, "unknown agent or action")
        agent.paused = action == "pause"
        sr.bus.emit("you", "control", f"You {'paused' if agent.paused else 'resumed'} {AGENT_DEFS[name]['label']}.")
        agent.push()
        return agent.public()

    @app.post("/api/settings")
    def update_settings(body: dict):
        allowed = set(config.DEFAULT_SETTINGS)
        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(422, f"unknown settings: {sorted(unknown)}")
        if body.get("tts_voice", "am_michael") not in ("am_michael", "am_adam", "am_eric", "am_onyx"):
            raise HTTPException(422, "unknown narrator voice")
        for k, v in body.items():
            db.set_setting(k, v)
        sr.bus.emit("you", "control", "You changed settings: " + ", ".join(f"{k} = {v}" for k, v in body.items()))
        sr.push_settings()
        return sr.settings()

    # live stream ----------------------------------------------------------------

    @app.get("/api/stream")
    async def stream(request: Request):
        async def gen():
            with sr.bus.subscribe() as q:
                yield "retry: 2000\n\n"
                while not await request.is_disconnected():
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {json.dumps(msg)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # the built hub ----------------------------------------------------------------

    if config.HUB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=config.HUB_DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            file = config.HUB_DIST / path
            if path and file.is_file():
                return FileResponse(file)
            return FileResponse(config.HUB_DIST / "index.html")

    return app
