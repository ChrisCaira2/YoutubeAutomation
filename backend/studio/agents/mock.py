"""Fake providers: every agent does visible, schema-valid work at no cost.

Costs shown in mock mode are the forecast of a real run (see forecast.py), never charged.

Mock output is labeled [mock] so it can never be mistaken for research.
"""
import random

from .. import artifacts, forecast
from ..config import HOST_NAME, MEDIA_DIR
from ..pipeline import Route
from .base import Agent, Outcome

M = "[mock]"


PAID = 1.0  # marks a step that would call Claude in a real run


class MockAgent(Agent):
    def __init__(self, name: str, *args, **kwargs):
        self.name = name
        super().__init__(*args, **kwargs)

    async def run(self, job: dict, route: Route) -> Outcome:
        maker = getattr(self, f"_make_{route.produces}")
        steps = self._plan(job, route)
        self.begin(job, route.task, len(steps))
        # Nothing is charged: each step reports its share of the forecast for this stage.
        expected = forecast.expected(route.produces, job["format"], job["stage"])
        paid = sum(1 for step in steps if step[2]) or 1
        for message, seconds, cost, tool in steps:
            await self.step(job, message, seconds * random.uniform(0.7, 1.3), expected / paid if cost else 0.0, tool)
        return maker(job)

    def _plan(self, job: dict, route: Route) -> list[tuple[str, float, float, str | None]]:
        t = job["title"]
        plans = {
            "brief": [
                (f"Searching archives and box scores for “{t}”", 2.0, 0, "web_search"),
                ("Reading 6 sources and extracting dated facts", 2.5, PAID, "claude"),
                ("Checking competing videos on the same moment", 1.5, 0, "youtube_search"),
                ("Drafting 5 hooks and 3 package concepts", 2.0, PAID, "claude"),
            ],
            "script": [
                ("Outlining the setup, turning point and payoff", 2.0, PAID, "claude"),
                ("Writing narration beat by beat", 3.0, PAID, "claude"),
                ("Self-checking against the retention checklist", 1.5, PAID, "claude"),
            ],
            "qa_report": [
                ("Running hook, promise-match and retention checks", 2.0, PAID, "claude"),
                ("Checking every claim has a source", 1.5, PAID, "claude"),
                ("Comparing against the last 20 videos for similarity", 1.0, 0, "similarity"),
            ],
            "storyboard": [
                ("Loading the series Style Bible", 1.0, 0, None),
                ("Planning frames and visual modes per beat", 2.0, PAID, "claude"),
                ("Writing image prompts", 1.5, PAID, "claude"),
            ],
            "render": [
                ("Generating illustrated frames", 3.0, 0, "flux"),
                (f"Recording narration in {HOST_NAME}'s voice", 2.0, 0, "kokoro_tts"),
                ("Timing word-level captions", 1.5, 0, "whisper"),
                ("Assembling preview render with FFmpeg", 2.5, 0, "ffmpeg"),
            ],
            "package": [
                ("Writing 3 distinct title and thumbnail angles", 2.0, PAID, "claude"),
                ("Composing thumbnails and checking mobile legibility", 2.0, 0, "thumbnail"),
                ("Writing description, chapters and pinned comment", 1.5, PAID, "claude"),
            ],
            "export": [
                ("Copying final MP4, thumbnails and metadata to the export folder", 1.5, 0, "filesystem"),
            ],
            "analytics_snapshot": [
                ("Waiting for first numbers (simulated)", 2.0, 0, None),
                ("Reading retention and click-through", 1.0, 0, "youtube_analytics"),
            ],
            "lessons": [
                ("Comparing results with the Playbook's predictions", 2.0, PAID, "claude"),
            ],
        }
        return plans[route.produces]

    # artifact makers ----------------------------------------------------------

    def _make_brief(self, job: dict) -> Outcome:
        t = job["title"]
        return Outcome(artifacts={"brief": {
            "audience": f"{M} US sports fans 25-55 who know the highlight but not the story",
            "promise": f"{M} What really happened in “{t}”, and why it almost didn't",
            "angle": f"{M} Rebuild the moment play by play and measure how unlikely it was",
            "facts": [
                {"claim": f"{M} Dated fact {i} about {t}", "source_title": f"{M} Source {i}", "source_url": f"https://example.com/mock-source-{i}"}
                for i in range(1, 6)
            ],
            "competitors": [{"title": f"{M} A popular highlight clip of this moment", "url": None, "how_we_differ": f"{M} We add the numbers and the aftermath"}],
            "hooks": [f"{M} Myth-bust hook", f"{M} Surprising-number hook", f"{M} Story-teaser hook", f"{M} Open-question hook", f"{M} Counterintuitive-claim hook"],
            "package_concepts": [
                {"title": f"{M} The number nobody believes", "thumbnail_concept": "Professor + giant scoreline"},
                {"title": f"{M} It almost never happened", "thumbnail_concept": "Faceless silhouette mid-action + clock"},
                {"title": f"{M} What the highlight leaves out", "thumbnail_concept": "Professor pointing at a chalkboard play"},
            ],
        }})

    def _make_script(self, job: dict) -> Outcome:
        long = job["format"] == "long"
        purposes = (
            ["hook", "loop_opened", "context", "pattern_interrupt", "context", "payoff", "loop_closed", "bridge"]
            if long else ["hook", "context", "payoff", "loop_closed"]
        )
        per = 75 if long else 8
        beats = [
            {
                "id": f"b{i + 1}",
                "narration": f"{M} Narration for beat {i + 1} ({p}).",
                "on_screen_text": f"{M} Beat {i + 1}",
                "visual_intent": f"{M} {'Scoreboard' if i == 0 else 'Play diagram'} for beat {i + 1}",
                "retention_purpose": p,
                "source_ref": (i % 5) + 1 if p in ("context", "payoff") else None,
                "est_seconds": per,
            }
            for i, p in enumerate(purposes)
        ]
        if job.get("note"):
            beats[0]["narration"] += f" (Revised per note: {job['note']})"
        return Outcome(artifacts={"script": {
            "format": job["format"],
            "target_seconds": per * len(beats),
            "beats": beats,
            "originality_statement": f"{M} Adds a win-probability reconstruction the top results don't show",
            "self_check": [
                {"rule": "No greeting before the hook", "passed": True, "note": ""},
                {"rule": "Payoff before the final third", "passed": True, "note": ""},
            ],
        }})

    def _make_qa_report(self, job: dict) -> Outcome:
        gate = "script" if job["stage"] == "scripted" else "video"
        prior_fails = sum(
            1 for a in artifacts.for_job(self.db, job["id"])
            if a["kind"] == "qa_report" and a["data"]["gate"] == gate and not a["data"]["passed"]
        )
        failed = prior_fails == 0 and random.random() < 0.3
        if gate == "script":
            checks = ["Hook test", "Promise match", "Retention audit", "Originality and anti-template", "Facts and sources", "Rights and safety"]
            fix = "Hook opens with context; lead with the record number in the first sentence."
        else:
            checks = ["Technical: resolution and loudness", "Caption sync and safe areas", "Visual change cadence", "Rights and safety", "AI-disclosure decision recorded"]
            fix = "Frames 14-17 hold the same diagram for 11 s; add a zoom or a cutaway."
        bad = random.choice(checks) if failed else None
        report = {
            "gate": gate,
            "passed": not failed,
            "checks": [{"name": c, "passed": c != bad, "note": fix if c == bad else ""} for c in checks],
            "fixes": [f"{M} {fix}"] if failed else [],
        }
        note = f"QA sent it back: {fix}" if failed else None
        return Outcome(passed=not failed, artifacts={"qa_report": report}, note=note)

    def _make_storyboard(self, job: dict) -> Outcome:
        script = artifacts.latest(self.db, job["id"], "script") or {"beats": []}
        modes = ["scoreboard", "professor", "diagram", "chart", "illustration", "photo", "text_card"]
        frames, t = [], 0.0
        for i, beat in enumerate(script["beats"]):
            mode = modes[i % len(modes)]
            frames.append({"beat_id": beat["id"], "start": t, "duration": beat["est_seconds"], "mode": mode,
                           "prompt": f"{M} {mode} frame for {beat['id']}", "motion": "still"})
            t += beat["est_seconds"]
        return Outcome(artifacts={"storyboard": {"style_bible": "Archive ink-and-watercolor v1", "frames": frames}})

    def _make_render(self, job: dict) -> Outcome:
        long = job["format"] == "long"
        folder = MEDIA_DIR / f"job-{job['id']}"
        script = artifacts.latest(self.db, job["id"], "script") or {"target_seconds": 0}
        return Outcome(artifacts={
            "render": {"path": str(folder / "preview.mp4"), "preview": True, "width": 1920 if long else 1080,
                       "height": 1080 if long else 1920, "fps": 30, "duration_seconds": script["target_seconds"]},
            "asset_manifest": {"assets": [
                {"path": str(folder / "frames"), "kind": "image", "source": f"{M} FLUX.1-schnell", "license": "Apache-2.0 model output", "sha256": None},
                {"path": str(folder / "narration.wav"), "kind": "narration", "source": f"{M} Kokoro TTS", "license": "Apache-2.0 model output", "sha256": None},
                {"path": str(folder / "music.mp3"), "kind": "music", "source": f"{M} YouTube Audio Library", "license": "YouTube Audio Library terms", "sha256": None},
            ]},
        })

    def _make_package(self, job: dict) -> Outcome:
        t = job["title"]
        n = 3 if job["format"] == "long" else 1
        return Outcome(artifacts={"package": {
            "options": [
                {"title": f"{M} {t}"[:100], "thumbnail_concept": "Professor + giant number", "thumbnail_path": None},
                {"title": f"{M} The real story of {t}"[:100], "thumbnail_concept": "Faceless silhouette + clock", "thumbnail_path": None},
                {"title": f"{M} Why {t} should never have happened"[:100], "thumbnail_concept": "Chalkboard play + red circle", "thumbnail_path": None},
            ][:n],
            "description": f"{M} Description with sources and Creative Commons credits.",
            "chapters": [{"t": "0:00", "title": "The moment"}, {"t": "1:10", "title": "The setup"}, {"t": "4:30", "title": "The turning point"}],
            "tags": ["sports history", "The Athletics Archive"],
            "pinned_comment": f"{M} Which moment should the Professor replay next?",
            "ai_disclosure": {"required": False, "reason": "All generated art is clearly illustrated and faceless; no realistic depiction of real people or events."},
        }})

    def _make_export(self, job: dict) -> Outcome:
        folder = MEDIA_DIR / "exports" / f"job-{job['id']}"
        return Outcome(artifacts={"export": {"folder": str(folder), "files": ["final.mp4", "thumbnail-a.png", "metadata.json"]}})

    def _make_analytics_snapshot(self, job: dict) -> Outcome:
        long = job["format"] == "long"
        return Outcome(artifacts={"analytics_snapshot": {
            "retention_30s": round(random.uniform(0.6, 0.8), 3) if long else None,
            "avg_percent_viewed": round(random.uniform(0.35, 0.6) if long else random.uniform(0.7, 1.1), 3),
            "ctr": round(random.uniform(0.03, 0.08), 3) if long else None,
            "viewed_vs_swiped": None if long else round(random.uniform(0.6, 0.8), 3),
            "notes": f"{M} Simulated numbers; real analytics arrive in Phase 5.",
        }})

    def _make_lessons(self, job: dict) -> Outcome:
        return Outcome(artifacts={"lessons": {
            "worked": [f"{M} Number-first hook held 30-second retention"],
            "did_not": [f"{M} Chapter 3 diagram ran long"],
            "playbook_updates": [f"{M} Test scoreboard cold opens on the next two Record Breakers"],
        }})
