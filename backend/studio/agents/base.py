"""Shared agent machinery: live state for the hub and step-by-step event reporting."""
import asyncio
from dataclasses import dataclass, field

from ..db import DB, now
from ..events import EventBus
from ..pipeline import Route

# Add an agent here (and a class for it) to extend the studio.
# `tier` picks the model class in Phase 2: "strong" for judgment, "fast" for formatting.
AGENT_DEFS = {
    "showrunner": {"label": "Showrunner", "role": "Routes jobs, enforces gates, budget and approvals", "tier": "none"},
    "research": {"label": "Research & Virality", "role": "Briefs, sourced facts, hooks, the Playbook", "tier": "strong"},
    "script": {"label": "Script", "role": "Beat-by-beat scripts with retention notes", "tier": "strong"},
    "qa": {"label": "QA & Compliance", "role": "Independent review; can block a job", "tier": "strong"},
    "studio": {"label": "Studio", "role": "Style Bible, storyboard, images, voice, render", "tier": "fast"},
    "packaging": {"label": "Packaging", "role": "Titles, thumbnails, description, chapters", "tier": "fast"},
    "publisher": {"label": "Publisher & Analytics", "role": "Exports files now; uploads and analytics later", "tier": "fast"},
}


@dataclass
class Outcome:
    passed: bool = True
    artifacts: dict[str, dict] = field(default_factory=dict)
    note: str | None = None


class Agent:
    name = "agent"

    def __init__(self, db: DB, bus: EventBus, speed: float = 1.0):
        self.db = db
        self.bus = bus
        self.speed = max(speed, 0.01)
        self.status = "idle"
        self.task: str | None = None
        self.job_id: int | None = None
        self.job_title: str | None = None
        self.progress = 0.0
        self.started_at: str | None = None
        self.heartbeat = now()
        self.paused = False
        self._steps_total = 1
        self._steps_done = 0

    # hub state --------------------------------------------------------------

    def public(self) -> dict:
        d = AGENT_DEFS[self.name]
        return {
            "name": self.name,
            "label": d["label"],
            "role": d["role"],
            "tier": d["tier"],
            "status": "paused" if self.paused and self.status == "idle" else self.status,
            "task": self.task,
            "job_id": self.job_id,
            "job_title": self.job_title,
            "progress": round(self.progress, 3),
            "started_at": self.started_at,
            "heartbeat": self.heartbeat,
            "paused": self.paused,
            "cost_today": self.db.cost_today(self.name),
        }

    def push(self) -> None:
        self.heartbeat = now()
        self.bus.broadcast("agent", self.public())

    def begin(self, job: dict, task: str, steps: int) -> None:
        self.status, self.task = "working", task
        self.job_id, self.job_title = job["id"], job["title"]
        self.progress, self._steps_total, self._steps_done = 0.0, max(steps, 1), 0
        self.started_at = now()
        self.push()
        self.bus.emit(self.name, "started", f"{AGENT_DEFS[self.name]['label']} started: {task.lower()} for “{job['title']}”.", job["id"])

    def finish(self, status: str = "idle") -> None:
        self.status, self.task, self.job_id, self.job_title = status, None, None, None
        self.progress, self.started_at = 0.0, None
        self.push()

    async def step(self, job: dict, message: str, seconds: float, cost: float = 0.0, tool: str | None = None) -> None:
        """One visible unit of work: an event, a wait, and a progress tick."""
        self.bus.emit(self.name, "tool_call" if tool else "progress", message, job["id"], details={"tool": tool} if tool else None)
        await asyncio.sleep(seconds / self.speed)
        if cost:
            self.bus.emit(self.name, "cost", f"Forecast ${cost:.3f} for {tool or 'work'} (simulated, nothing charged).", job["id"], cost_usd=cost, details={"tool": tool, "simulated": True})
        self._steps_done += 1
        self.progress = self._steps_done / self._steps_total
        self.push()

    async def run(self, job: dict, route: Route) -> Outcome:
        raise NotImplementedError
