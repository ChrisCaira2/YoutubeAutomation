"""The clipper's wing of the hub, on its own port beside the two studios.

Serves the same hub build. The page sees `"clipper": true` in /api/state and shows the clip command screen.
With automation on, a worker checks the watch list, records, transcribes, finds moments and has Claude judge them;
it starts off, since recording uses disk and judging spends.
"""
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from studio import config as studio_config

from . import detect, edit, facecam, ingest, judge, settings, sweep, transcribe
from .db import DB

ROOT_DIR = Path(__file__).resolve().parents[1]
STAGES = [("sources", "Streams in"), ("transcribed", "Transcribed"), ("found", "Moments found"), ("kept", "Clips picked"),
          ("edited", "Edited"), ("waiting", "Waiting for you"), ("approved", "Approved"), ("posted", "Posted")]
COMING = {"posted": 5}  # the milestone that builds each stage


class Record(BaseModel):
    url: str


class Toggle(BaseModel):
    on: bool


class Review(BaseModel):
    decision: str  # "approved", "rejected", or "edited" to undo


class Trim(BaseModel):
    start_by: float = 0.0
    end_by: float = 0.0


class Facecam(BaseModel):
    box: list[float] | None  # [left, top, right, bottom] as shares of the frame, or None for no facecam


class CreatorChange(BaseModel):
    permission: str | None = None
    watch: bool | None = None


class Worker:
    """The automatic pipeline. Every step is safe to repeat, so it just keeps going round."""

    def __init__(self, cfg: dict, db_path: Path):
        self.cfg, self.db_path = cfg, db_path
        self.log = settings.logger(cfg)
        self.starting: dict[str, tuple[float, subprocess.Popen]] = {}  # recordings started here that haven't checked in yet
        self.live: dict[int, dict] = {}  # creator id: what the last check found
        self.last_watch = 0.0
        self.task = "Idle"
        self.stop = threading.Event()
        self.db = DB(db_path)

    def record(self, url: str) -> None:
        """Record a live stream and clip it as it goes, in processes of their own, so it outlives a restart of the hub."""
        if same(url) in {same(u) for u in self.recording()}:
            raise ValueError("Already recording that stream.")
        self.starting[same(url)] = (time.time(), subprocess.Popen([sys.executable, "-m", "clipper", "ingest", url, "--follow"], cwd=ROOT_DIR))

    def recording(self) -> list[str]:
        """Every stream being recorded, however it was started (here, the watch list, or the command line)."""
        live = [s["url"] for s in self.db.live(heartbeat(self.cfg))]
        waiting = [u for u, (at, proc) in self.starting.items() if proc.poll() is None and time.time() - at < 60 and u not in {same(x) for x in live}]
        return live + waiting

    def check_watch_list(self, db: DB) -> None:
        keywords = [k.lower() for k in self.cfg["ingest"]["game_keywords"]]
        for creator in db.all("SELECT * FROM creators WHERE watch = 1"):
            try:
                info = ingest.probe(creator["channel_url"], creator["platform"])
            except ingest.NotLive:
                self.live[creator["id"]] = {"live": False, "checked": time.time()}
                continue
            except Exception as exc:
                self.live[creator["id"]] = {"live": None, "error": str(exc)[:200], "checked": time.time()}
                continue
            gta = not keywords or any(k in info["title"].lower() for k in keywords)
            self.live[creator["id"]] = {"live": info["live"], "gta": gta, "title": info["title"], "checked": time.time()}
            if info["live"] and gta and same(creator["channel_url"]) not in {same(u) for u in self.recording()}:
                self.log.info("%s is live with GTA: %s", creator["name"], info["title"])
                self.record(creator["channel_url"])

    def loop(self) -> None:
        db = DB(self.db_path)
        while not self.stop.wait(self.cfg["ingest"]["live_poll_seconds"] * 6):
            if db.setting("automation", "off") != "on":
                self.task = "Automation is off"
                continue
            try:
                if time.time() - self.last_watch > self.cfg["ingest"]["watch_poll_seconds"]:
                    self.task = "Checking the watch list"
                    self.check_watch_list(db)
                    self.last_watch = time.time()
                # Catch-up for anything no `follow` loop is looking after (recordings bring their own).
                cutoff = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
                for row in db.all("SELECT id FROM sources WHERE status = 'ready' AND trashed_at IS NULL AND (followed_at IS NULL OR followed_at < ?)", (cutoff,)):
                    self.task = "Transcribing"
                    transcribe.run(self.cfg, db, row["id"], log=self.log)
                    self.task = "Finding moments"
                    detect.run(self.cfg, db, row["id"])
                    if db.candidates(row["id"], "found"):
                        self.task = "Claude is judging moments"
                        judge.run(self.cfg, db, row["id"], log=self.log)
                    self.task = "Editing clips"
                    edit.run(self.cfg, db, row["id"], log=self.log)
                sweep.run(self.cfg, db, self.log)
                self.task = "Waiting for new pieces"
            except judge.BudgetExceeded as exc:
                db.set_setting("automation", "off")
                self.task = f"Stopped: {exc}"
                self.log.warning("Automation stopped: %s", exc)
            except Exception as exc:  # one bad source shouldn't stop the rest; the log says what happened
                self.task = f"Error: {exc}"
                self.log.exception("Worker step failed")


_available = {"at": 0.0, "bytes": None}


def available_bytes() -> int | None:
    """Space as macOS counts it (Finder, Settings): free now plus purgeable space it clears when room is needed,
    such as local Time Machine snapshots and iCloud copies. On 2026-11-12: 37 GB free, 139 GB available."""
    if time.time() - _available["at"] > 60:
        try:
            out = subprocess.run(["osascript", "-e", 'tell application "Finder" to get free space of startup disk'], capture_output=True, text=True, timeout=10).stdout
            _available["bytes"] = int(float(out.strip()))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _available["bytes"] = None
        _available["at"] = time.time()
    return _available["bytes"]


def same(url: str) -> str:
    """A stream link in one spelling, so twitch.tv/x and https://www.twitch.tv/x/ match."""
    return url.split("://")[-1].removeprefix("www.").rstrip("/").lower()


def heartbeat(cfg: dict) -> float:
    """How recently a recorder must have checked in to count as recording."""
    return cfg["ingest"]["live_poll_seconds"] * 3 + 30


def state(cfg: dict, db: DB, worker: Worker) -> dict:
    sources = db.all("SELECT s.*, c.name AS creator, c.permission FROM sources s LEFT JOIN creators c ON c.id = s.creator_id ORDER BY s.id DESC")
    pieces = db.one("SELECT COUNT(*) AS n, SUM(status = 'transcribed') AS done FROM segments")
    counts = {"sources": len(sources), "transcribed": pieces["done"] or 0, "found": db.one("SELECT COUNT(*) AS n FROM candidates")["n"],
              "kept": db.one("SELECT COUNT(*) AS n FROM candidates WHERE status = 'judged'")["n"],
              "edited": db.one("SELECT COUNT(*) AS n FROM clips")["n"],
              "waiting": db.one("SELECT COUNT(*) AS n FROM clips WHERE status = 'edited'")["n"],
              "approved": db.one("SELECT COUNT(*) AS n FROM clips WHERE status = 'approved'")["n"], "posted": 0}
    by_source = {s["id"]: s for s in sources}
    moments = []
    clips = {k["candidate_id"]: k for k in db.all("SELECT * FROM clips")}
    for m in db.all("SELECT * FROM candidates WHERE status IN ('judged', 'dropped') ORDER BY status = 'judged' DESC, score DESC LIMIT 60"):
        clip = clips.get(m["id"])
        s = by_source.get(m["source_id"], {})
        at = (s.get("window_start") or 0) + m["start"]
        moments.append({"id": m["id"], "kept": m["status"] == "judged", "score": m["score"], "title": m["title"], "moment": m["moment"],
                        "length": round(m["end"] - m["start"], 1), "at": ingest.clock(at), "creator": s.get("creator"), "permitted": s.get("permission") == "permitted",
                        "reason": m["reason"], "hashtags": json.loads(m["hashtags"] or "[]"), "scores": json.loads(m["scores"] or "{}"),
                        "caption": m["caption"], "source_id": m["source_id"], "creator_id": s.get("creator_id"),
                        "clip": clip and {"id": clip["id"], "video": f"/api/clips/{clip['id']}/video?v={clip['created_at']}",
                                          "poster": f"/api/clips/{clip['id']}/poster?v={clip['created_at']}", "status": clip["status"],
                                          "layout": clip["layout"], "lufs": clip["lufs"], "duration": clip["duration"]}})
    recording = {same(u) for u in worker.recording()}
    stamp = lambda iso: datetime.fromisoformat(iso).timestamp()  # noqa: E731
    recordings = [{"id": s["id"], "url": s["url"], "title": s["title"], "creator": next((c["name"] for c in db.all("SELECT name FROM creators WHERE id = ?", (s["creator_id"],))), ""),
                   "started": stamp(s["created_at"]), "recorded": round(db.length(s["id"])), "pieces": len(db.segments(s["id"])),
                   "chat": db.one("SELECT COUNT(*) AS n FROM chat WHERE source_id = ?", (s["id"],))["n"], "stopping": bool(s["stop_requested"])}
                  for s in db.live(heartbeat(cfg))]
    creators = []
    for c in db.all("SELECT * FROM creators WHERE platform != 'file' ORDER BY watch DESC, name"):
        check = worker.live.get(c["id"], {})
        creators.append({"id": c["id"], "name": c["name"], "platform": c["platform"], "url": c["channel_url"], "watch": bool(c["watch"]),
                         "permission": c["permission"], "recording": same(c["channel_url"]) in recording, "live": check.get("live"), "gta": check.get("gta"),
                         "title": check.get("title"), "checked": check.get("checked")})
    disk = shutil.disk_usage(studio_config.ROOT)
    available = available_bytes() or disk.free
    return {
        "clipper": True,
        "workspace": "clips",
        "channel": cfg["judge"]["channel"],
        "workspaces": [{"id": k, "label": w["label"], "url": f"http://127.0.0.1:{w['port']}", "current": k == "clips"}
                       for k, w in {**studio_config.WORKSPACES, **studio_config.WINGS}.items()],
        "automation": db.setting("automation", "off") == "on",
        "task": worker.task,
        "stages": [{"id": k, "label": label, "count": counts[k], "milestone": COMING.get(k)} for k, label in STAGES],
        "creators": creators,
        "recording": sorted(recording),
        "recordings": recordings,
        "sources": [{"id": s["id"], "kind": s["kind"], "status": s["status"], "title": s["title"], "creator": s["creator"],
                     "duration": s["duration"], "permitted": s["permission"] == "permitted"} for s in sources[:8]],
        "moments": moments,
        "schedule": [],
        "spend": {"month": round(db.spent_this_month(), 4), "cap": cfg["budget"]["monthly_usd"]},
        "disk": {"free_gb": round(disk.free / 1e9, 1), "available_gb": round(available / 1e9, 1),
                 "used_pct": round((disk.total - available) / disk.total * 100)},
    }


def create_app(cfg: dict | None = None, run_worker: bool = True) -> FastAPI:
    cfg = cfg or settings.load()
    db = DB(cfg["paths"]["database"])
    worker = Worker(cfg, cfg["paths"]["database"])
    app = FastAPI(title="GTA 6 Clip Central")
    if run_worker:
        app.add_event_handler("startup", lambda: threading.Thread(target=worker.loop, daemon=True).start())
        app.add_event_handler("shutdown", worker.stop.set)

    @app.get("/api/state")
    def get_state():
        return state(cfg, db, worker)

    @app.post("/api/clips/record")
    def record(body: Record):
        try:
            if ingest.platform_of(body.url.strip()) == "file":
                raise ValueError("Paste a Twitch, YouTube or Kick link.")
            worker.record(body.url.strip())
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return state(cfg, db, worker)

    @app.get("/api/clips/{clip_id}/{kind}")
    def clip_file(clip_id: int, kind: str):
        clip = db.one("SELECT * FROM clips WHERE id = ?", (clip_id,))
        if not clip or kind not in ("video", "poster"):
            raise HTTPException(404, "No such clip.")
        return FileResponse(clip["path"] if kind == "video" else clip["poster"])

    def guard(fn, *args):
        try:
            fn(*args)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return state(cfg, db, worker)

    @app.post("/api/clips/{clip_id}/review")
    def review(clip_id: int, body: Review):
        def apply():
            clip = db.one("SELECT * FROM clips WHERE id = ?", (clip_id,))
            if not clip:
                raise ValueError("No such clip.")
            if clip["status"] == "uploaded" or body.decision not in ("approved", "rejected", "edited"):
                raise ValueError("That clip can't be changed now.")
            db.run("UPDATE clips SET status = ? WHERE id = ?", (body.decision, clip_id))
        return guard(apply)

    @app.post("/api/clips/{clip_id}/trim")
    def trim(clip_id: int, body: Trim):
        clip = db.one("SELECT * FROM clips WHERE id = ?", (clip_id,))
        if not clip:
            raise HTTPException(404, "No such clip.")
        return guard(edit.trim, cfg, db, clip["candidate_id"], body.start_by, body.end_by, worker.log)

    @app.post("/api/sources/{source_id}/stop")
    def stop_recording(source_id: int):
        def apply():
            source = db.source(source_id)
            if not source or source["status"] != "recording":
                raise ValueError("That stream isn't recording.")
            db.set_source(source_id, stop_requested=1)  # the recorder sees it within a few seconds, saves what it has and stops
        return guard(apply)

    @app.get("/api/sources/{source_id}/frame")
    def source_frame(source_id: int):
        source = db.source(source_id)
        shot = source and not source["trashed_at"] and judge.frame(db, source_id, db.length(source_id) / 2, 960)
        if not shot:
            raise HTTPException(404, "No picture for that stream.")
        return Response(shot, media_type="image/jpeg")

    @app.get("/api/sources/{source_id}/facecam")
    def get_facecam(source_id: int):
        source = db.source(source_id)
        if not source:
            raise HTTPException(404, "No such stream.")
        return json.loads(source["facecam"] or '{"box": null, "by": null}')

    @app.post("/api/sources/{source_id}/facecam")
    def set_facecam(source_id: int, body: Facecam):
        def apply():
            box = body.box
            if box is not None and not (len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                raise ValueError("The box has to sit inside the picture.")
            db.set_source(source_id, facecam=json.dumps({"box": [round(v, 4) for v in box] if box else None, "by": "you"}))
            edit.redo_source(cfg, db, source_id, worker.log)
        return guard(apply)

    @app.post("/api/creators/{creator_id}")
    def change_creator(creator_id: int, body: CreatorChange):
        def apply():
            fields = {}
            if body.permission is not None:
                if body.permission not in ("permitted", "unknown", "refused"):
                    raise ValueError("Permission is permitted, unknown or refused.")
                fields["permission"] = body.permission
            if body.watch is not None:
                fields["watch"] = int(body.watch)
            if fields:
                db.set_creator(creator_id, **fields)
        return guard(apply)

    @app.post("/api/clips/automation")
    def automation(body: Toggle):
        db.set_setting("automation", "on" if body.on else "off")
        worker.last_watch = 0  # check the watch list straight away
        return state(cfg, db, worker)

    hub = studio_config.HUB_DIST
    if hub.exists():
        app.mount("/assets", StaticFiles(directory=hub / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            file = hub / path
            return FileResponse(file if path and file.is_file() else hub / "index.html")

    return app
