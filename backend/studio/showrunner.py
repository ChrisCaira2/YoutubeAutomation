"""The Showrunner: routes jobs to agents, enforces gates, budget and approvals.

It never writes content. Agents hand off only through the database: an agent
saves its artifact, the Showrunner moves the job's stage, and the next agent
picks the job up from that stage.
"""
import asyncio
import time

from . import artifacts
from .agents import AGENT_DEFS, Agent
from .config import DEFAULT_SETTINGS
from .db import DB, now
from .events import EventBus
from .llm import BudgetExceeded
from .config import VISUAL_STYLE
from .media import finder
from .pipeline import CHANGE_TARGETS, ROUTES, STAGE_LABELS, check_transition

MAX_ATTEMPTS = 3
FINAL_RENDER_STAGES = ("qa_video", "awaiting_approval", "scheduled")
HOLD_NOTES = {"qa_video": "Preview ready. Watch it, then make the title and thumbnails or render the final video."}
ACTIVE_TARGET = 5  # mock feed keeps this many jobs in flight


class Showrunner:
    name = "showrunner"

    def __init__(self, db: DB, bus: EventBus, agents: dict[str, Agent], mock: bool = True, speed: float = 1.0,
                 halt_stages: set[str] | None = None, startup_problem: str | None = None):
        self.db = db
        self.bus = bus
        self.agents = agents
        self.mock = mock
        self.speed = speed
        self.halt_stages = halt_stages or set()
        self.startup_problem = startup_problem
        self.inflight: dict[int, asyncio.Task] = {}
        self.status = "idle"
        self.task: str | None = None
        self.heartbeat = now()
        self._last_feed = 0.0
        self._last_push = 0.0

    # state --------------------------------------------------------------------

    def settings(self) -> dict:
        return self.db.get_settings(DEFAULT_SETTINGS)

    def public(self) -> dict:
        d = AGENT_DEFS[self.name]
        return {
            "name": self.name, "label": d["label"], "role": d["role"], "tier": d["tier"],
            "status": self.status, "task": self.task, "job_id": None, "job_title": None,
            "progress": 0.0, "started_at": None, "heartbeat": self.heartbeat, "paused": False,
            "cost_today": 0.0,
        }

    def _set(self, status: str, task: str | None) -> None:
        self.heartbeat = now()
        changed = (status, task) != (self.status, self.task)
        self.status, self.task = status, task
        if changed or time.monotonic() - self._last_push > 5:
            self._last_push = time.monotonic()
            self.bus.broadcast("agent", self.public())
            for agent in self.agents.values():
                if agent.status != "working":
                    agent.push()  # idle agents still report a heartbeat

    def push_job(self, job_id: int) -> dict:
        job = self.db.get_job(job_id)
        job["cost"] = self.db.job_cost(job_id)
        job["working"] = next((a.name for a in self.agents.values() if a.job_id == job_id), None)
        self.bus.broadcast("job", job)
        return job

    def push_settings(self) -> None:
        self.bus.broadcast("settings", self.settings())

    # main loop ------------------------------------------------------------------

    async def run(self) -> None:
        active = self.db.one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'active'")["n"]
        self.bus.emit(self.name, "info", f"Studio online ({'mock' if self.mock else 'live'} mode). Resuming {active} active job(s) from their last completed stage.")
        if self.startup_problem:
            self.db.set_setting("paused", True)
            self.bus.emit(self.name, "error", f"{self.startup_problem} The studio is paused.", severity="error")
            self.push_settings()
        while True:
            try:
                self.tick()
            except Exception as exc:  # keep the loop alive; the hub shows the error
                self.bus.emit(self.name, "error", f"Showrunner error: {exc}", severity="error")
            await asyncio.sleep(0.5)

    def tick(self) -> None:
        s = self.settings()
        if s["paused"]:
            self._set("waiting", "Studio paused")
            return
        spent = self.db.cost_today()
        if spent >= s["daily_budget_usd"]:
            self.db.set_setting("paused", True)
            self.bus.emit(self.name, "budget", f"Daily budget of ${s['daily_budget_usd']:.2f} reached (${spent:.2f}). Pausing the studio.", severity="warn")
            self.push_settings()
            return
        self.gate_packaged(s)
        if self.mock and s["mock_feed"]:
            self.feed()
        started = self.dispatch()
        busy = len(self.inflight)
        self._set("working" if busy else "idle", f"Coordinating {busy} job(s)" if busy else "Waiting for work")
        if started:
            self.bus.broadcast("agent", self.public())

    def gate_packaged(self, s: dict) -> None:
        for job in self.db.all("SELECT * FROM jobs WHERE stage = 'packaged' AND status = 'active'"):
            approvals = self.db.one("SELECT COUNT(*) AS n FROM events WHERE type = 'approved' AND agent = 'you' AND details NOT LIKE '%script%'")["n"]
            if approvals >= s["approve_first_n"]:
                self.move(job, "awaiting_approval")
                self.move(self.db.get_job(job["id"]), "scheduled")
                self.bus.emit(self.name, "approved", f"Auto-approved “{job['title']}” ({approvals} manual approvals done).", job["id"])
                self.handoff(job, "showrunner", "publisher", "package")
            else:
                self.move(job, "awaiting_approval")
                self.bus.emit(self.name, "approval_needed", f"“{job['title']}” is ready for your review.", job["id"], severity="warn")
                self.handoff(job, "packaging", "you", "package")

    def feed(self) -> None:
        if time.monotonic() - self._last_feed < 6 / self.speed:
            return
        # Count jobs waiting on you too, so the demo doesn't pile up an endless approval queue.
        active = self.db.one("SELECT COUNT(*) AS n FROM jobs WHERE status = 'active'")["n"]
        if active >= ACTIVE_TARGET:
            return
        topic = self.db.one("SELECT * FROM topics WHERE status = 'backlog' ORDER BY id LIMIT 1")
        if not topic:
            return
        self._last_feed = time.monotonic()
        n = self.db.one("SELECT COUNT(*) AS n FROM jobs")["n"]
        self.create_job(topic["id"], "short" if n % 3 == 2 else "long")

    def held_stages(self, s: dict) -> set[str]:
        """Stages no agent picks up: not built yet, or waiting on you."""
        return self.halt_stages | ({"scripted"} if s.get("manual_script_review") else set())

    def dispatch(self) -> int:
        started = 0
        held = self.held_stages(self.settings())
        for agent in self.agents.values():
            if agent.status != "idle" or agent.paused:
                continue
            stages = [st for st, r in ROUTES.items() if r.agent == agent.name and st not in held]
            if not stages:
                continue
            marks = ",".join("?" * len(stages))
            busy = list(self.inflight) or [-1]
            job = self.db.one(
                f"SELECT * FROM jobs WHERE status = 'active' AND stage IN ({marks}) "
                f"AND id NOT IN ({','.join('?' * len(busy))}) ORDER BY priority DESC, id LIMIT 1",
                (*stages, *busy),
            )
            if job:
                agent.status = "working"  # claim before the task starts
                self.inflight[job["id"]] = asyncio.create_task(self.execute(agent, job))
                started += 1
        return started

    async def execute(self, agent: Agent, job: dict) -> None:
        route = ROUTES[job["stage"]]
        s = self.settings()
        try:
            if self.db.job_cost(job["id"]) >= s["per_video_budget_usd"]:
                self.block(job, f"Per-video budget of ${s['per_video_budget_usd']:.2f} reached.")
                return
            self.push_job(job["id"])
            outcome = await agent.run(job, route)
            for kind, data in outcome.artifacts.items():
                version = artifacts.save(self.db, job["id"], kind, data, agent.name)
                self.bus.emit(agent.name, "output", f"Saved {kind.replace('_', ' ')} v{version}.", job["id"], details={"kind": kind, "version": version})
            job = self.db.get_job(job["id"])
            if outcome.passed:
                held = route.on_success in self.halt_stages
                hold = HOLD_NOTES.get(route.on_success, f"{STAGE_LABELS[route.on_success]}. The next stage isn't built yet, so the job waits here.")
                hold = self._with_media_warning(job, hold) if held else hold
                note = hold if held else outcome.note
                # Only passing a QA gate clears the strikes. If a redo cleared them too, a job
                # QA keeps rejecting would loop forever, and on the script gate each loop costs money.
                self.move(job, route.on_success, note=note, **({"attempts": 0} if route.on_fail else {}))
                if held:
                    self.bus.emit(self.name, "info", f"“{job['title']}” is waiting. {hold}", job["id"])
                    return
                if route.on_success == "scripted" and s.get("manual_script_review"):
                    self.bus.emit(self.name, "approval_needed", f"The script for “{job['title']}” is ready for your review.", job["id"], severity="warn")
                    self.handoff(job, agent.name, "you", route.produces)
                    return
                nxt = ROUTES.get(route.on_success)
                to = nxt.agent if nxt else ("you" if route.on_success == "packaged" else None)
                if to and to != agent.name:
                    self.handoff(job, agent.name, to, route.produces)
            else:
                attempts = job["attempts"] + 1
                self.move(job, route.on_fail, note=outcome.note, attempts=attempts)
                back_to = ROUTES[route.on_fail].agent
                self.bus.emit(agent.name, "qa_failed", f"QA failed “{job['title']}” and sent it back to {AGENT_DEFS[back_to]['label']}: {outcome.note}", job["id"], severity="warn")
                self.handoff(job, agent.name, back_to, "qa_report")
                # Video QA measures a render of unchanged inputs, so redoing it can't change the result.
                pointless_redo = not self.mock and route.on_fail == "storyboarded"
                if attempts >= MAX_ATTEMPTS or pointless_redo:
                    self.block(job, f"Failed QA {attempts} time(s). Needs your review. {outcome.note}")
        except asyncio.CancelledError:
            raise
        except BudgetExceeded as exc:
            self.block(self.db.get_job(job["id"]), str(exc))
        except Exception as exc:
            job = self.db.get_job(job["id"])
            attempts = job["attempts"] + 1
            self.db.update_job(job["id"], attempts=attempts)
            self.bus.emit(agent.name, "error", f"{AGENT_DEFS[agent.name]['label']} failed on “{job['title']}”: {exc}", job["id"], severity="error")
            if not self.mock:
                # A retry would spend again; you decide from the hub.
                self.block(job, f"{AGENT_DEFS[agent.name]['label']} failed: {exc} Not retrying automatically, since a retry costs money.")
            elif attempts >= MAX_ATTEMPTS:
                self.block(job, f"Errored {attempts} times: {exc}")
        finally:
            self.inflight.pop(job["id"], None)
            agent.finish()
            self.push_job(job["id"])

    # job operations ---------------------------------------------------------------

    def move(self, job: dict, dst: str, **fields) -> dict:
        check_transition(job["stage"], dst)
        status = "done" if dst == "learned" else job["status"]
        job = self.db.update_job(job["id"], stage=dst, status=status, **fields)
        self.bus.emit(self.name, "stage", f"“{job['title']}” moved to {STAGE_LABELS[dst]}.", job["id"], details={"stage": dst})
        self.push_job(job["id"])
        return job

    def handoff(self, job: dict, src: str, dst: str, artifact: str) -> None:
        self.bus.emit(src, "handoff", f"{_label(src)} handed “{job['title']}” to {_label(dst)}.", job["id"],
                      details={"from": src, "to": dst, "artifact": artifact})

    def block(self, job: dict, reason: str) -> None:
        self.db.update_job(job["id"], status="blocked", note=reason)
        self.bus.emit(self.name, "blocked", f"Blocked “{job['title']}”: {reason}", job["id"], severity="error")
        self.push_job(job["id"])

    def create_job(self, topic_id: int, fmt: str, priority: int = 0, note: str | None = None) -> dict:
        topic = self.db.one("SELECT * FROM topics WHERE id = ?", (topic_id,))
        if not topic:
            raise KeyError(f"topic {topic_id} not found")
        ts = now()
        job_id = self.db.run(
            "INSERT INTO jobs (topic_id, title, format, series, stage, status, priority, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'idea', 'active', ?, ?, ?, ?)",
            (topic_id, topic["title"], fmt, topic["series"], priority, note, ts, ts),
        )
        self.db.run("UPDATE topics SET status = 'queued' WHERE id = ?", (topic_id,))
        kind = "Short" if fmt == "short" else "long-form video"
        self.bus.emit(self.name, "created", f"New {kind}: “{topic['title']}” ({topic['series']}).", job_id)
        return self.push_job(job_id)

    # your actions from the hub ----------------------------------------------------------

    def approve(self, job_id: int, comment: str | None = None) -> dict:
        job = self._require(job_id, "awaiting_approval")
        waits = "scheduled" in self.halt_stages
        job = self.move(job, "scheduled", note="Approved. Render the final video if you haven't, then upload it with your chosen title and thumbnail." if waits else None)
        self.bus.emit("you", "approved", f"You approved “{job['title']}”." + (f" Note: {comment}" if comment else ""), job_id)
        self.handoff(job, "you", "publisher", "package")
        return job

    def request_changes(self, job_id: int, target: str, comment: str) -> dict:
        if target not in CHANGE_TARGETS:
            raise ValueError(f"target must be one of {sorted(CHANGE_TARGETS)}")
        job = self._require(job_id, "awaiting_approval")
        job = self.move(job, CHANGE_TARGETS[target], note=comment, attempts=0)
        to = ROUTES[CHANGE_TARGETS[target]].agent
        self.bus.emit("you", "changes_requested", f"You asked {_label(to)} to revise “{job['title']}”: {comment}", job_id)
        self.handoff(job, "you", to, "feedback")
        return job

    def render_final(self, job_id: int) -> dict:
        """Start the full-resolution render once the preview has passed QA-2. Same timing, so a package still fits it."""
        job = self.db.get_job(job_id)
        if not job:
            raise KeyError(f"job {job_id} not found")
        if job["stage"] not in FINAL_RENDER_STAGES or job["status"] != "active":
            raise ValueError(f"job is at {job['stage']} ({job['status']}), which can't render a final video")
        studio = self.agents["studio"]
        if not hasattr(studio, "finalize"):
            raise ValueError("final renders only exist in live mode")
        if studio.status != "idle":
            raise ValueError("Studio is busy; try again when it finishes")
        studio.status = "working"  # claim before the task starts
        self.inflight[job_id] = asyncio.create_task(self._finalize(studio, job))
        self.bus.emit("you", "control", f"You started the final render of “{job['title']}”.", job_id)
        return job

    async def _finalize(self, studio: Agent, job: dict) -> None:
        try:
            render = await studio.finalize(job)
            self.db.update_job(job["id"], note=f"Final video ready: {render['path']}")
            self.bus.emit("studio", "output", f"Final video ready: {render['width']}x{render['height']}. Cost: $0.", job["id"])
        except Exception as exc:
            self.bus.emit("studio", "error", f"Final render failed for “{job['title']}”: {exc}", job["id"], severity="error")
        finally:
            self.inflight.pop(job["id"], None)
            studio.finish()
            self.push_job(job["id"])

    def redo_research(self, job_id: int, notes: str) -> dict:
        """Send a video back for deeper research and a rewrite, from your script review or its preview. The next stop is your script review."""
        job = self.db.get_job(job_id)
        job = self._require(job_id, "scripted" if job and job["stage"] == "scripted" else "qa_video")
        if not hasattr(self.agents["research"], "_brief"):
            raise ValueError("redoing research only exists in live mode")
        if self.settings()["paused"]:
            raise ValueError("The studio is paused")
        job = self.move(job, "idea", note=notes, attempts=0)
        self.bus.emit("you", "changes_requested", f"You sent “{job['title']}” back for deeper research: {notes}", job_id)
        self.handoff(job, "you", "research", "feedback")
        return job

    def redo_slides(self, job_id: int) -> dict:
        """Rebuild a video's slides and render, after new photos or corrections. About 2 cents for Haiku. An approved video comes back for approval."""
        job = self.db.get_job(job_id)
        job = self._require(job_id, "scheduled" if job and job["stage"] == "scheduled" else "qa_video")
        if self.settings()["paused"]:
            raise ValueError("The studio is paused")
        job = self.move(job, "qa_script", note=None, attempts=0)
        self.bus.emit("you", "control", f"You asked Studio to rebuild the slides for “{job['title']}”.", job_id)
        self.handoff(job, "you", "studio", "feedback")
        return job

    def _with_media_warning(self, job: dict, note: str) -> str:
        board = artifacts.latest(self.db, job["id"], "storyboard") or {"frames": []}
        if VISUAL_STYLE in ("cartoon", "sketch") or any(f["mode"] in ("real_photo", "archive_film") for f in board["frames"]):  # drawn looks never use photos
            return note
        return f"{note} This video has no photos or film yet: pick some in its Photos & film tab."

    def choose_media(self, job_id: int, chosen: list[str]) -> dict:
        """Download the photos and film you ticked, then put them in the video. Free: no Claude call."""
        job = self.db.get_job(job_id)
        if not job:
            raise KeyError(f"job {job_id} not found")
        if job["stage"] in ("awaiting_approval", "scheduled", "published", "analyzing", "learned"):
            raise ValueError("This video is past review. Send it back with Request changes before adding media.")
        added = finder.download(chosen, job["id"], job["title"])
        self.bus.emit("you", "control", f"You chose {len(added)} photos and film clips for “{job['title']}”.", job_id, details={"files": added})
        studio = self.agents["studio"]
        if job["stage"] == "qa_video" and job["status"] == "active" and hasattr(studio, "place_media"):
            if studio.status != "idle":
                raise ValueError("Studio is busy; try again when it finishes")
            studio.place_media(job)
            return self.move(job, "storyboarded", note=None, attempts=0)
        return self.push_job(job_id)

    def redo_render(self, job_id: int) -> dict:
        """Re-record and re-render with the same slides, after a pronunciation fix. Free."""
        job = self._require(job_id, "qa_video")
        job = self.move(job, "storyboarded", note=None, attempts=0)
        self.bus.emit("you", "control", f"You asked Studio to re-record “{job['title']}”.", job_id)
        return job

    def reuse_package(self, job_id: int) -> dict:
        """New slides, same narration: the title, thumbnails and description still fit, so send it to your approval as it is. Free."""
        job = self._require(job_id, "qa_video")
        if not artifacts.latest(self.db, job_id, "package"):
            raise ValueError("This video has no title and thumbnails yet.")
        return self.move(job, "packaged", note=None, attempts=0)

    def make_package(self, job_id: int) -> dict:
        """Packaging is paid, so in live mode it starts only when you've watched the preview and ask for it."""
        job = self._require(job_id, "qa_video")
        agent = self.agents["packaging"]
        if not hasattr(agent, "_package"):
            raise ValueError("real packages only exist in live mode")
        if agent.status != "idle":
            raise ValueError("Packaging is busy; try again when it finishes")
        if self.settings()["paused"]:
            raise ValueError("The studio is paused")
        agent.status = "working"  # claim before the task starts
        self.inflight[job_id] = asyncio.create_task(self.execute(agent, job))
        self.bus.emit("you", "control", f"You asked Packaging to make the title and thumbnails for “{job['title']}”.", job_id)
        return job

    def _shorts_of(self, job: dict) -> list[dict]:
        """Shorts made from this job, unless you rejected them. A Short's title starts with its long-form's title."""
        start = f"{job['title']}: "
        return self.db.all("SELECT * FROM jobs WHERE format = 'short' AND status != 'failed' AND substr(title, 1, ?) = ?", (len(start), start))

    def make_shorts(self, job_id: int) -> dict:
        """Write 3 Shorts from a finished long-form. One paid call, never retried; each then waits for your script review."""
        job = self.db.get_job(job_id)
        if not job:
            raise KeyError(f"job {job_id} not found")
        if job["stage"] not in FINAL_RENDER_STAGES or job["status"] != "active" or job["format"] != "long":
            raise ValueError("Shorts come from a long-form video that has passed its preview")
        agent = self.agents["script"]
        if not hasattr(agent, "write_shorts"):
            raise ValueError("real Shorts only exist in live mode")
        if job_id in self.inflight or agent.status != "idle":
            raise ValueError("That job or Script is busy; try again when it finishes")
        if self.settings()["paused"]:
            raise ValueError("The studio is paused")
        if self._shorts_of(job):
            raise ValueError("This video already has Shorts. Reject them first to write new ones")
        agent.status = "working"  # claim before the task starts
        self.inflight[job_id] = asyncio.create_task(self._write_shorts(agent, job))
        self.bus.emit("you", "control", f"You asked Script for Shorts from “{job['title']}”.", job_id)
        return job

    async def _write_shorts(self, agent: Agent, job: dict) -> None:
        try:
            shorts = await agent.write_shorts(job)
            brief = artifacts.latest(self.db, job["id"], "brief")
            for item in shorts:
                ts = now()
                title = f"{job['title']}: {item['idea']}"
                short_id = self.db.run(
                    "INSERT INTO jobs (topic_id, title, format, series, stage, status, note, created_at, updated_at) "
                    "VALUES (?, ?, 'short', 'One Moment', 'scripted', 'active', ?, ?, ?)",
                    (job["topic_id"], title, item["note"], ts, ts),
                )
                artifacts.save(self.db, short_id, "brief", brief, "research")
                artifacts.save(self.db, short_id, "script", item["script"], agent.name)
                self.bus.emit(self.name, "created", f"New Short from job #{job['id']}: “{item['idea']}”.", short_id)
                self.bus.emit(self.name, "approval_needed", f"The script for the Short “{item['idea']}” is ready for your review.", short_id, severity="warn")
                self.handoff(self.db.get_job(short_id), agent.name, "you", "script")
                self.push_job(short_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = f"Writing Shorts failed: {exc} Nothing was created. Not retrying automatically, since a retry costs money."
            self.db.update_job(job["id"], note=reason)
            self.bus.emit(agent.name, "error", reason, job["id"], severity="error")
        finally:
            self.inflight.pop(job["id"], None)
            agent.finish()
            self.push_job(job["id"])

    def expand_narration(self, job_id: int, notes: str) -> dict:
        """Send a previewed long-form video back to your script review with fuller narration. One paid call, never retried."""
        job = self._require(job_id, "qa_video")
        agent = self.agents["script"]
        if not hasattr(agent, "expand_narration"):
            raise ValueError("narration passes only exist in live mode")
        if job["format"] != "long":
            raise ValueError("only long-form scripts have room for more narration")
        if agent.status != "idle":
            raise ValueError("Script is busy; try again when it finishes")
        self.db.update_job(job_id, note=None)  # don't leave an old failure showing while this runs
        agent.status = "working"  # claim before the task starts
        self.inflight[job_id] = asyncio.create_task(self._expand(agent, job, notes))
        self.bus.emit("you", "control", f"You asked Script to explain the numbers in “{job['title']}”.", job_id)
        return job

    async def _expand(self, agent: Agent, job: dict, notes: str) -> None:
        try:
            script, summary = await agent.expand_narration(job, notes)
            version = artifacts.save(self.db, job["id"], "script", script, agent.name)
            self.bus.emit(agent.name, "output", f"Saved script v{version}.", job["id"], details={"kind": "script", "version": version})
            job = self.move(self.db.get_job(job["id"]), "scripted", note=summary, attempts=0)
            self.bus.emit(self.name, "approval_needed", f"The new narration for “{job['title']}” is ready for your review.", job["id"], severity="warn")
            self.handoff(job, agent.name, "you", "script")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = f"Narration pass failed: {exc} The script and preview are unchanged. Not retrying automatically, since a retry costs money."
            self.db.update_job(job["id"], note=reason)
            self.bus.emit(agent.name, "error", reason, job["id"], severity="error")
        finally:
            self.inflight.pop(job["id"], None)
            agent.finish()
            self.push_job(job["id"])

    def approve_script(self, job_id: int, comment: str | None = None) -> dict:
        """Your manual review stands in for QA-1; recorded as a QA report written by you."""
        job = self._require(job_id, "scripted")
        artifacts.save(self.db, job_id, "qa_report", {
            "gate": "script", "passed": True,
            "checks": [{"name": "Manual review", "passed": True, "note": comment or "Approved by the channel owner."}],
            "fixes": [],
        }, "you")
        held = "qa_script" in self.halt_stages
        note = "Script approved by you. Production arrives in Phase 3, so the job waits here." if held else None
        job = self.move(job, "qa_script", note=note, attempts=0)
        self.bus.emit("you", "approved", f"You approved the script for “{job['title']}”." + (f" Note: {comment}" if comment else ""), job_id,
                      details={"gate": "script"})
        return job

    def revise_script(self, job_id: int, comment: str) -> dict:
        job = self._require(job_id, "scripted")
        artifacts.save(self.db, job_id, "qa_report", {
            "gate": "script", "passed": False,
            "checks": [{"name": "Manual review", "passed": False, "note": comment}],
            "fixes": [comment],
        }, "you")
        job = self.move(job, "researched", note=f"Your script notes: {comment}", attempts=0)
        self.bus.emit("you", "changes_requested", f"You asked Script to revise “{job['title']}”: {comment}", job_id)
        self.handoff(job, "you", "script", "feedback")
        return job

    def reject(self, job_id: int, reason: str) -> dict:
        job = self.db.get_job(job_id)
        waiting = job and job["status"] == "active" and job["stage"] in ("awaiting_approval", "scripted")
        if not job or not (waiting or job["status"] == "blocked"):
            raise ValueError("only blocked videos or ones waiting on your review can be rejected")
        job = self.db.update_job(job_id, status="failed", note=reason)
        self.bus.emit("you", "rejected", f"You rejected “{job['title']}”: {reason}", job_id, severity="warn")
        return self.push_job(job_id)

    def retry(self, job_id: int, note: str | None = None) -> dict:
        job = self.db.get_job(job_id)
        if not job or job["status"] not in ("blocked", "failed"):
            raise ValueError("only blocked or failed jobs can be retried")
        self.db.update_job(job_id, status="active", attempts=0, note=note)
        self.bus.emit("you", "retried", f"You restarted “{job['title']}” from {STAGE_LABELS[job['stage']]}." + (f" Note: {note}" if note else ""), job_id)
        return self.push_job(job_id)

    def set_priority(self, job_id: int, priority: int) -> dict:
        self.db.update_job(job_id, priority=priority)
        return self.push_job(job_id)

    def _require(self, job_id: int, stage: str) -> dict:
        job = self.db.get_job(job_id)
        if not job:
            raise KeyError(f"job {job_id} not found")
        if job["stage"] != stage or job["status"] != "active":
            raise ValueError(f"job is at {job['stage']} ({job['status']}), not {stage}")
        return job


def _label(name: str) -> str:
    return "you" if name == "you" else AGENT_DEFS[name]["label"]
