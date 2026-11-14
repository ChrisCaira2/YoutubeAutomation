"""The real Studio agent. Haiku designs the slides (about a cent); voice, captions, drawing and assembly are free and local."""
import asyncio
import re

from .. import artifacts
from ..config import MEDIA_DIR, PROFESSOR_INTRO, VISUAL_STYLE
from ..media import cartoon, footage, motion, photos, produce, sketch, sketch_writer, slide_writer, storyboard, themes, visuals
from ..pipeline import Route
from .base import Agent, Outcome


class StudioAgent(Agent):
    name = "studio"

    def __init__(self, settings_fn, claude, *args, **kwargs):
        self.settings_fn = settings_fn
        self.claude = claude
        super().__init__(*args, **kwargs)

    def folder(self, job_id: int):
        return MEDIA_DIR / f"job-{job_id}"

    async def run(self, job: dict, route: Route) -> Outcome:
        if route.produces == "storyboard":
            return await self._storyboard(job, route)
        return await self._render(job, route, "preview")

    async def _storyboard(self, job: dict, route: Route) -> Outcome:
        script = artifacts.latest(self.db, job["id"], "script")
        brief = artifacts.latest(self.db, job["id"], "brief")
        if VISUAL_STYLE == "sketch":
            return await self._sketches(job, route, script, brief)
        self.begin(job, route.task, 2)
        board = storyboard.plan(script, job["title"], visuals.STYLE["name"])
        # If this fails the job stops with a Retry button. Code-planned frames ignore the team's colors, and two Shorts went out of theme that way.
        board, rejected, cost = await slide_writer.write(self.claude, job, self.settings_fn(), script, brief, board, job["title"], self.name)
        self.bus.emit(self.name, "progress", f"Haiku designed {len(board['frames'])} slides (${cost:.3f}); {len(rejected)} failed the number check and fell back to plain text.",
                      job["id"], details={"rejected": rejected}, severity="warn" if rejected else "info")
        repeats = slide_writer.likely_repeats(board)
        if repeats:
            self.bus.emit(self.name, "progress", f"{len(repeats)} slides may repeat the slide before them: worth a look in review.", job["id"], details={"repeats": repeats}, severity="warn")
        board = self._fill_media(board, job)
        board = motion.plan(themes.attach(self._with_intro(board, script, job), themes.build(brief.get("look"), job.get("topic_id"))))
        self._steps_done, self.progress = 1, 0.5
        self.push()
        await asyncio.to_thread(produce.draw_storyboard, board, script["format"], self.folder(job["id"]))
        self._steps_done, self.progress = 2, 1.0
        self.push()
        return Outcome(artifacts={"storyboard": board})

    async def _sketches(self, job: dict, route: Route, script: dict, brief: dict) -> Outcome:
        """The sketch look: Haiku describes a picture for every few seconds (about a cent), then FLUX draws them here for free."""
        folder = self.folder(job["id"])
        board = sketch_writer.plan(script, job["title"])
        self.begin(job, route.task, len(board["frames"]) + 2)
        board, rejected, cost = await sketch_writer.write(self.claude, job, self.settings_fn(), script, brief, board, job["title"], self.name)
        board = motion.plan(sketch.attach_pictures(board, folder, script["format"]))
        to_draw = len(sketch.missing(board))
        self.bus.emit(self.name, "progress", f"Haiku described {len(board['frames'])} frames (${cost:.3f}); {to_draw} pictures to draw, about {to_draw * 40 // 60} minutes."
                      + (f" {len(rejected)} descriptions named a real person or brand, or were too thin, and were replaced." if rejected else ""),
                      job["id"], details={"rejected": rejected}, severity="warn" if rejected else "info")
        self._steps_total = to_draw + 2
        self._tick(job, "Drawing the pictures with FLUX on this Mac")
        loop = asyncio.get_running_loop()

        def drew(message: str) -> None:  # every picture moves the bar; the activity log hears about every tenth
            self._steps_done += 1
            self.progress = min(self._steps_done / self._steps_total, 1.0)
            count = re.search(r"(\d+) of (\d+)", message)
            if count:  # the hub's picture progress bar reads this
                self.task = f"Drawing pictures: {count.group(1)} of {count.group(2)}"
            if self._steps_done % 10 == 0:
                self.bus.emit(self.name, "progress", message, job["id"])
            self.push()

        await asyncio.to_thread(sketch.draw_pictures, board, script["format"], folder, lambda message: loop.call_soon_threadsafe(drew, message))
        self.task = route.task
        await asyncio.to_thread(produce.draw_storyboard, board, script["format"], folder)
        self._steps_done, self.progress = self._steps_total, 1.0
        self.push()
        return Outcome(artifacts={"storyboard": board})

    def _with_intro(self, board: dict, script: dict, job: dict) -> dict:
        """Every long-form video opens with the Professor's welcome: the owner's call, 2026-11-07."""
        if script["format"] != "long" or not PROFESSOR_INTRO or (board["frames"] and board["frames"][0]["beat_id"] == "intro"):
            return board
        say = cartoon.intro_line(job["title"]).replace("Sportington III", "Sportington the Third")  # the captions follow the voice
        frame = {"beat_id": "intro", "start": 0.0, "duration": round(len(say.split()) / storyboard.WORDS_PER_SECOND, 2), "mode": "intro",
                 "prompt": "The Professor's welcome", "motion": motion.ANIMATE, "spec": {"say": say, "title": job["title"]}}
        return {**board, "frames": [frame] + board["frames"]}

    def _fill_media(self, board: dict, job: dict) -> dict:
        board, film = footage.assign(board, job["title"])
        board, used = photos.assign(board, job["title"])
        if film or used:
            self.bus.emit(self.name, "progress", f"Placed {len(film)} film clips and {len(used)} photos, all with recorded licenses.", job["id"])
        if VISUAL_STYLE != "cartoon" and not any(f["mode"] in ("real_photo", "archive_film") for f in board["frames"]):
            self.bus.emit(self.name, "progress", "No photos or film on this video yet. Pick some in its Photos & film tab.", job["id"], severity="warn")
        return board

    def place_media(self, job: dict) -> None:
        """New photos or film on a finished board, with the current colors: no Claude call, so it's free."""
        board = artifacts.latest(self.db, job["id"], "storyboard")
        brief = artifacts.latest(self.db, job["id"], "brief") or {}
        script = artifacts.latest(self.db, job["id"], "script")
        theme = (board["frames"][0]["spec"].get("theme") if board["frames"] else None) or themes.build(brief.get("look"), job.get("topic_id"))
        board = motion.plan(themes.attach(self._fill_media(board, job), theme))  # a video keeps the look it was made in
        produce.draw_storyboard(board, script["format"], self.folder(job["id"]))
        artifacts.save(self.db, job["id"], "storyboard", board, self.name)

    async def _render(self, job: dict, route: Route, quality: str) -> Outcome:
        script = artifacts.latest(self.db, job["id"], "script")
        board = artifacts.latest(self.db, job["id"], "storyboard")
        steps = len(script["beats"]) + len(board["frames"]) // 5 + 3
        self.begin(job, f"{route.task} ({quality})", steps)
        loop = asyncio.get_running_loop()

        def report(message: str) -> None:  # called from the worker thread
            loop.call_soon_threadsafe(self._tick, job, message)

        brief = artifacts.latest(self.db, job["id"], "brief") or {}
        names = {p["name"]: p["sounds_like"] for p in brief.get("pronunciations", [])}
        result = await asyncio.to_thread(
            produce.render_video, script, board, self.folder(job["id"]), quality, self.settings_fn().get("tts_voice"), report, names
        )
        r = result["render"]
        music = "with music" if result["has_music"] else "no music track yet"
        self.bus.emit(self.name, "progress", f"Rendered {r['width']}x{r['height']}, {r['duration_seconds'] / 60:.1f} min, {music}. Cost: $0.", job["id"])
        return Outcome(artifacts={"render": r, "asset_manifest": result["asset_manifest"]})

    def _tick(self, job: dict, message: str) -> None:
        self._steps_done += 1
        self.progress = min(self._steps_done / self._steps_total, 1.0)
        self.bus.emit(self.name, "progress", message, job["id"])
        self.push()

    async def finalize(self, job: dict) -> dict:
        """The full-resolution render, made only after the preview passes QA-2."""
        route = Route("studio", "Rendering the final video", "render", job["stage"])
        outcome = await self._render(job, route, "final")
        for kind, data in outcome.artifacts.items():
            artifacts.save(self.db, job["id"], kind, data, self.name)
        return outcome.artifacts["render"]

