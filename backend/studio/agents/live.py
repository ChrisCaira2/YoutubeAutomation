"""Real agents backed by Claude: Research (with web search), Script, and QA-1.

Each agent is a separate Claude task with its own system prompt. QA never sees
the drafting conversation, only the brief and the finished script.
"""
import asyncio
import json
from pathlib import Path

from .. import artifacts
from ..config import CHANNEL_NAME, HOST_NAME, MEDIA_DIR, PITCH, PLAYBOOK_FILE, RECIPE, STRATEGY_DIR, VISUAL_RULES, VISUAL_STYLE
from ..llm import MODEL_RESEARCH, Claude
from ..media.storyboard import numbers_in
from ..pipeline import Route
from .base import Agent, Outcome

# Worst-case spend reserved before each call (checked against the daily and per-video caps).
# Research (Sonnet 5.5): up to 5 searches + 6 page reads + 14k output, priced as if nothing caches.
# Script: ~11k input + up to 20k output on Opus 5.5 at low effort (high and medium spent 24k and 32k and still ran out).
# Script finish: ~12k input + up to 12k output on Opus 5.5 at low effort.
# Narration pass: ~13k input + up to 10k output on Opus 5.5 at low effort.
# Package: ~8k input + up to 5k output on Sonnet 5.5 at low effort.
# Shorts: ~10k input + up to 7k output on Opus 5.5 at low effort, for all three together.
RESERVE = {"brief": 0.70, "script": 0.60, "script_finish": 0.30, "narration": 0.30, "package": 0.08, "shorts": 0.20, "qa_report": 0.35}
MIN_RECOVERED_BEATS = 3
NARRATION_WORDS = (1450, 1650)  # about 10 to 11 minutes as the voice actually reads it
NARRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "narration": {"type": "string"}},
                "required": ["id", "narration"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["beats"],
    "additionalProperties": False,
}

QA_CHECKS = [
    "Hook test",
    "Promise match",
    "Retention audit",
    "Originality and anti-template",
    "Facts and sources",
    "Rights and safety",
    "Length and pacing",
]

WORDS_PER_SECOND = 2.5  # ~150 words per minute


def _playbook(areas: set[str]) -> str:
    entries = json.loads(PLAYBOOK_FILE.read_text())["entries"]
    return "\n".join(f"- [{e['confidence']}] {e['rule']}" for e in entries if e["area"] in areas)


def _strategy() -> str:
    return (STRATEGY_DIR / "channel-strategy.md").read_text()


def _persona() -> str:
    return (STRATEGY_DIR / "persona.md").read_text()


def _schema(kind: str) -> dict:
    return json.loads((artifacts.SCHEMA_DIR / f"{kind}.json").read_text())


def _compact(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _words(text: str) -> int:
    return len(text.split())


def complete_beats(text: str) -> tuple[list[dict], str]:
    """Pull every fully written beat out of a cut-off script answer.

    Returns the complete beats and the text of the beat that was cut off (if any),
    so a finish step can continue from exactly where the answer stopped.
    """
    marker = '"beats":['
    if marker not in text:
        return [], ""
    start = text.index(marker) + len(marker)
    beats, depth, obj_start, in_str, esc, last_end = [], 0, None, False, False, start
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    beats.append(json.loads(text[obj_start:i + 1]))
                    last_end = i + 1
                except json.JSONDecodeError:
                    break
        elif ch == "]" and depth == 0:
            break
    return beats, text[last_end:].lstrip(",").strip()


SHORTS_WANTED = 3
SHORT_SECONDS = (20, 45)
SHORTS_SCHEMA = {
    "type": "object",
    "properties": {
        "shorts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "idea": {"type": "string", "minLength": 1},
                    "adds": {"type": "string", "minLength": 1},
                    "beats": {
                        "type": "array",
                        "minItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "narration": {"type": "string", "minLength": 1},
                                "on_screen_text": {"type": "string"},
                                "visual_intent": {"type": "string", "minLength": 1},
                                "retention_purpose": {"enum": ["hook", "loop_opened", "loop_closed", "pattern_interrupt", "payoff", "context", "bridge"]},
                                "source_ref": {"type": ["integer", "null"]},
                            },
                            "required": ["narration", "on_screen_text", "visual_intent", "retention_purpose", "source_ref"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["idea", "adds", "beats"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["shorts"],
    "additionalProperties": False,
}
PACKAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "angle": {"enum": ["curiosity", "myth_bust", "story"]},
                    "title": {"type": "string", "minLength": 1},
                    "layout": {"enum": ["number", "versus", "silhouette", "sketch"]},
                    "big": {"type": "string", "minLength": 1},
                    "small": {"type": "string"},
                    "headline": {"type": "string", "minLength": 1},
                },
                "required": ["angle", "title", "layout", "big", "small", "headline"],
                "additionalProperties": False,
            },
        },
        "description": {"type": "string", "minLength": 1},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"beat_id": {"type": "string"}, "title": {"type": "string", "minLength": 1}},
                "required": ["beat_id", "title"],
                "additionalProperties": False,
            },
        },
        "tags": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "pinned_comment": {"type": "string", "minLength": 1},
    },
    "required": ["options", "description", "chapters", "tags", "pinned_comment"],
    "additionalProperties": False,
}
DISCLOSURE = {
    "required": False,
    "reason": "The Professor and all drawn art are clearly illustrated, real photos aren't altered, and the synthetic narration is a fictional host's voice, not a real person's.",
}
SKETCH_DISCLOSURE = {
    "required": False,
    "reason": "The pictures are AI-made but plainly drawn sketches, not realistic, and show no real person. Tick \"made with AI\" at upload anyway, as the model channel does.",
}
SKETCH_NOTE = "Illustrations made with AI (FLUX.1). Narration by a synthetic voice."
MAX_TITLE = 100
MAX_DESCRIPTION = 5000
MAX_TAG_CHARS = 500
MIN_CHAPTERS = 3  # YouTube's rules: at least 3, the first at 0:00, each at least 10 seconds long
MIN_CHAPTER_SECONDS = 10


def clock(seconds: float) -> str:
    total = int(seconds)
    hours, minutes, secs = total // 3600, total % 3600 // 60, total % 60
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def beat_starts(timeline: list[dict]) -> dict[str, float]:
    starts: dict[str, float] = {}
    for frame in timeline:
        starts.setdefault(frame["beat_id"], frame["start"])
    return starts


def chapter_list(chosen: list[dict], starts: dict[str, float]) -> list[dict]:
    """Real timestamps from the render, kept only if YouTube will accept them as chapters."""
    timed = sorted((starts[c["beat_id"]], c["title"].strip()) for c in chosen if c["beat_id"] in starts)
    chapters: list[tuple[float, str]] = []
    for i, (start, title) in enumerate(timed):
        start = 0.0 if i == 0 else start  # YouTube requires the first chapter at 0:00
        if not chapters or start - chapters[-1][0] >= MIN_CHAPTER_SECONDS:
            chapters.append((start, title))
    return [{"t": clock(s), "title": t} for s, t in chapters] if len(chapters) >= MIN_CHAPTERS else []


def short_title(title: str) -> str:
    title = title.strip()
    return title if len(title) <= MAX_TITLE else title[:MAX_TITLE].rsplit(" ", 1)[0]


def full_description(body: str, chapters: list[dict], brief: dict, credits: str) -> str:
    """The writer's text plus what code can get exactly right: chapters, sources and photo credits."""
    sources = {f["source_url"]: f["source_title"] for f in brief["facts"]}
    tail = []
    if chapters:
        tail.append("Chapters:\n" + "\n".join(f"{c['t']} {c['title']}" for c in chapters))
    tail.append("Sources:\n" + "\n".join(f"- {title}: {url}" for url, title in sources.items()))
    if credits:
        tail.append(credits.strip())
    end = "\n\n" + "\n\n".join(tail)
    return body.strip()[:MAX_DESCRIPTION - len(end)].rstrip() + end


def thumbnail_pictures(board: dict) -> list[str]:
    """Drawings for the sketch thumbnails: the mascot first, since he's the viewer, then the numbered items' pictures. Three different ones."""
    found = [f["spec"] for f in board["frames"] if f["mode"] in ("picture", "item") and f["spec"].get("picture")]
    ranked = [s["picture"] for s in found if s.get("mascot")] + [s["picture"] for s in found if not s.get("mascot")]
    return list(dict.fromkeys(p for p in ranked if Path(p).exists()))[:3]


def trim_tags(tags: list[str]) -> list[str]:
    kept, used = [], 0
    for tag in (t.strip() for t in tags):
        if tag and used + len(tag) + 1 <= MAX_TAG_CHARS:
            kept.append(tag)
            used += len(tag) + 1
    return kept


def package_figures(options: list[dict], brief: dict, script: dict) -> list[str]:
    """Numbers promised in a title or thumbnail that the brief and script don't contain."""
    known = " ".join([f["claim"] for f in brief["facts"]] + [b["narration"] for b in script["beats"]])
    seen = set(numbers_in(known))
    found = []
    for letter, option in zip("ABC", options):
        for number in numbers_in(" ".join((option["title"], option["big"], option["small"], option["headline"]))):
            if number not in seen:
                found.append(f"{letter}: {number}")
    return found


def new_numbers(brief: dict, before: dict, after: dict) -> list[str]:
    """Figures the narration didn't have and the brief doesn't state: worked out by the writer, so a person checks them."""
    known = " ".join([f["claim"] for f in brief["facts"]] + [b["narration"] for b in before["beats"]])
    seen = set(numbers_in(known))
    found = []
    for beat in after["beats"]:
        for number in numbers_in(beat["narration"]):
            if number not in seen:
                seen.add(number)
                found.append(f"{beat['id']}: {number}")
    return found


def _timed(script: dict) -> dict:
    """Recompute timing from the words actually written."""
    for beat in script.get("beats", []):
        beat["est_seconds"] = round(_words(beat.get("narration", "")) / WORDS_PER_SECOND, 1)
    script["target_seconds"] = round(sum(b["est_seconds"] for b in script.get("beats", [])), 1)
    return script


class LiveAgent(Agent):
    def __init__(self, name: str, claude: Claude, settings_fn, *args, **kwargs):
        self.name = name
        self.claude = claude
        self.settings_fn = settings_fn
        super().__init__(*args, **kwargs)

    def mark(self, job: dict, message: str, done: int) -> None:
        self.bus.emit(self.name, "progress", message, job["id"])
        self._steps_done = done
        self.progress = done / self._steps_total
        self.push()

    async def run(self, job: dict, route: Route) -> Outcome:
        return await getattr(self, f"_{route.produces}")(job, route)

    # Research ---------------------------------------------------------------------

    async def _brief(self, job: dict, route: Route) -> Outcome:
        topic = self.db.one("SELECT * FROM topics WHERE id = ?", (job["topic_id"],))
        self.begin(job, route.task, 2)
        self.mark(job, f"Searching the web and reading sources on “{job['title']}”", 0)
        earlier = artifacts.latest(self.db, job["id"], "brief")
        redo = f"""

This video was researched once already, and that wasn't deep enough. Earlier facts and look:
{_compact({"facts": earlier["facts"], "look": earlier.get("look")})}
Keep a fact only if it holds up and you can cite a page you opened this time. Keep the same look unless it's wrong.""" if earlier else ""
        before = self.db.one("SELECT a.data FROM artifacts a JOIN jobs j ON j.id = a.job_id WHERE a.kind = 'brief' AND j.topic_id != ? AND a.data LIKE '%\"look\"%' ORDER BY a.id DESC LIMIT 1", (job["topic_id"],))
        last = json.loads(before["data"])["look"] if before else {"background": "dark", "texture": "plain", "font": "condensed"}
        last_look = f" The previous video used a {last['background']} background, {last['texture']} texture and {last['font']} font, so differ from it in at least two of those."
        system = f"""You are the Research & Virality agent for {CHANNEL_NAME}, {PITCH}.

Your job: produce a Video Brief that every later agent relies on. Accuracy is the top priority; the channel's reputation depends on it.

Channel strategy:
{_strategy()}

Playbook rules you must follow (confidence in brackets):
{_playbook({"policy", "packaging", "algorithm", "niche"})}"""
        look = (f"{RECIPE['look']}." if VISUAL_STYLE == "sketch" else
                f"""{RECIPE['look']}. team: who the colors belong to. primary and secondary: their real colors as hex codes. highlight: a third color from their identity for emphasized words, or the same as secondary. opponent, opponent_primary and opponent_secondary: the other side in this moment and their real colors, so the cartoon players on both teams wear the right colors. background: "light" or "dark", whichever is truer to that team's look. texture: plain, pinstripes or diagonal; use pinstripes only for a team known for them. The team's colors must be unmistakable to a fan. font: condensed, slab, din or futura, suiting the era.{last_look}""")
        prompt = f"""Research this {RECIPE['subject']} and write the Video Brief.

{RECIPE['subject'].capitalize()}: {job['title']}
Year: {topic.get('year') or 'unknown'}
Series: {job['series']}
Format: {"long-form video, 8 to 12 minutes, 16:9" if job['format'] == 'long' else "YouTube Short, 20 to 45 seconds, 9:16"}
Visual ideas from the backlog: {topic.get('visuals') or 'none'}
{f"Notes from the channel owner: {job['note']}" if job.get('note') else ''}{redo}

How to research:
- Search the web, then open (fetch) the pages you rely on. Prefer primary and reference sources: official league, Olympic or governing-body records, Sports-Reference sites, contemporary newspaper archives, the Library of Congress, and respected histories. A search snippet alone is not a source.
- You have 5 searches and 6 page reads, so choose them well. Don't open YouTube pages; name competing videos from search results only.
- Use several different sources: facts from at least 4 different sites, and no more than a third resting on any one page. No more than a third may rest on Wikipedia alone; check key numbers against a specialist or primary source.
- Give 12 to 18 facts. Each is one specific, checkable claim (names, dates, scores, numbers) with the URL and title of a page you actually opened. Never invent or estimate a number. If sources disagree, say so inside the claim.
- Include a widely repeated myth or misconception only if a page you opened shows people really believe it. Never assume one to make a better hook.
- Include the data behind charts: series of comparable numbers such as totals by month, quarter or round, year-by-year figures, and how rivals or the league compared.
{RECIPE['research']}
- The script can only be as insightful as your facts, so don't stop at the numbers. Include facts that explain why this happened: conditions, strategy, rule or era differences, what the competition was doing, how people reacted at the time, and what changed afterward.

Then:
- audience, promise and angle: specific to this {RECIPE['subject']}, honest, and true to the channel strategy.
- competitors: 2 to 4 existing YouTube videos about this {RECIPE['subject']} you found, with URL if known and how our video will differ.
- hooks: 5 candidate opening lines of different types (myth-bust, surprising number, story teaser, open question, counterintuitive claim). Each must be provable by the facts.
- look: {look}
- pronunciations: for every person or place name that a text-to-speech voice could get wrong, the name and a respelling that says it the way the person is really known, using plain letters with no hyphens (Gehrig is "Gairig", Koenig is "Kaynig"). Use an empty list if there are none.
- package_concepts: 3 meaningfully different title + thumbnail ideas. Titles of 100 characters or fewer, honest about the payoff. Thumbnails follow the channel rule: {RECIPE['thumbnail_rule']}."""
        schema = _schema("brief")
        schema["required"] = [*schema["required"], "look", "pronunciations"]  # new briefs must have them; older ones stay valid without
        result = await self.claude.structured(
            agent=self.name, job=job, settings=self.settings_fn(), system=system, prompt=prompt,
            schema=schema, reserve_usd=RESERVE["brief"], effort="medium", max_tokens=14000,
            web=True, max_searches=5, max_fetches=6, kind="brief", model=MODEL_RESEARCH,
        )
        self.mark(job, f"Brief written: {len(result.data.get('facts', []))} sourced facts from {result.searches} searches (${result.cost_usd:.2f}).", 2)
        # On a redo, the notes stay with the job, so the Script agent gets them too.
        return Outcome(artifacts={"brief": result.data}, note=job.get("note") if earlier else None)

    # Script -----------------------------------------------------------------------

    async def _script(self, job: dict, route: Route) -> Outcome:
        brief = artifacts.latest(self.db, job["id"], "brief")
        previous = artifacts.latest(self.db, job["id"], "script")
        long = job["format"] == "long"
        system = self._script_system(long)

        # A paid answer that was cut off: keep its finished beats and write only the rest.
        if not previous:
            cutoff = self.claude.latest_raw(job["id"], "script-cutoff")
            if cutoff:
                beats, unfinished = complete_beats(cutoff.read_text())
                if len(beats) >= MIN_RECOVERED_BEATS:
                    return await self._finish_script(job, route, brief, beats, unfinished, system)

        self.begin(job, route.task, 2)
        self.mark(job, "Drafting the script beat by beat" + (" (revision)" if previous and job.get("note") else ""), 0)
        target = "1,400 to 1,700 words of narration, which runs about 10 to 12 minutes" if long else "20 to 45 seconds"
        revision = ""
        if previous and job.get("note"):
            revision = f"""

This is a revision. Previous script:
{_compact(previous)}

Fix these problems (from QA or the channel owner), and keep what already works:
{job['note']}"""
        planned = "; ".join(t["title"] for t in self.db.all("SELECT title FROM topics WHERE id != ? ORDER BY id", (job["topic_id"],)))
        prompt = f"""Write the {'long-form' if long else 'Short'} script for “{job['title']}”.

Video Brief (your only source of facts):
{_compact(brief)}

Requirements:
- Length: {target}. Earn that length with substance from the brief, never padding. Narration runs at about 150 words per minute; set each beat's est_seconds to its word count divided by 2.5, and target_seconds to the total.
- Beats: {"18 to 35 beats, none longer than about 40 seconds" if long else "4 to 8 beats, each 3 to 8 seconds"}. Each beat is one visual moment.
- {RECIPE['shape'] if long else "The first beat is the payoff or the strangest fact, readable as on-screen text on its own. The last line connects back to the first frame so it loops. One standalone idea."}
- retention_purpose: label each beat honestly (hook, loop_opened, loop_closed, pattern_interrupt, payoff, context, bridge).
- source_ref: for every beat that states a fact, the 1-based number of the supporting fact in the brief's facts list. Use null only for beats with no factual claim. Do not state any fact that is not in the brief.
- on_screen_text: 8 words or fewer.
- Write numbers as digits (1927, 60, .356, 110-44). The studio turns them into natural speech, and captions and charts need the digits.
- Only promise a chart the brief has the data for, and only tease a next episode from this list of planned topics: {planned}.
- visual_intent: what the viewer sees, using the channel's visual rules: {VISUAL_RULES.replace("{host}", HOST_NAME)}
- originality_statement: what this video adds that the top existing videos don't.
- Insight carries this channel. The audience is intelligent. Never say arithmetic they can do themselves: no "60 home runs, up from 47, that's 13 more". Give them what the numbers can't: why it happened, what made it possible or hard, what people at the time missed, what it changed, what a number hides. Interpretation is welcome when it's clearly your reading of the facts; new facts are not. A number only earns its place if it sets up that insight, and a comparison that truly surprises (the kind a viewer wouldn't think to make) is worth making. Prefer beats built around a comparison, a share or a running total, since those become charts on screen.
- Say each thing once. Never restate what the viewer just heard in slightly different words, and never set up a point by announcing it ("keep your eye on") when you can simply make it. Each sentence adds something new.
- self_check: check your script against each retention rule above and report honestly.
Keep your planning short: the beats are the deliverable.{revision}"""
        result = await self.claude.structured(
            agent=self.name, job=job, settings=self.settings_fn(), system=system, prompt=prompt,
            schema=_schema("script"), reserve_usd=RESERVE["script"], effort="low", max_tokens=20000, kind="script",
        )
        script = result.data
        script["format"] = job["format"]
        _timed(script)
        self.mark(job, f"Script written: {len(script.get('beats', []))} beats, about {script['target_seconds'] / 60:.1f} minutes (${result.cost_usd:.2f}).", 2)
        return Outcome(artifacts={"script": script})

    def _script_system(self, long: bool) -> str:
        return f"""You are the Script agent for {CHANNEL_NAME}. You write narration for {RECIPE['host']}.

Host persona:
{_persona()}

Retention playbook (follow it; confidence in brackets):
{_playbook({"long-form" if long else "shorts", "algorithm", "niche"})}

Voice: {RECIPE['voice']}. Write how someone actually talks when explaining something they love. Mix longer connected sentences with the occasional short one for punch, join related facts with words like because, but, so and which, and use contractions. A synthetic voice reads the narration, and it goes flat on fragments, so avoid strings of clipped phrases like "Free throws: 28 made, 32 attempted." Concrete numbers, no filler, no greetings, never "hey guys", never "in this video". Respectful to athletes. No gambling promotion."""

    async def _finish_script(self, job: dict, route: Route, brief: dict, beats: list[dict], unfinished: str, system: str) -> Outcome:
        """Write only the beats after a cut-off point, at low effort, and merge them in."""
        long = job["format"] == "long"
        so_far = sum(_words(b["narration"]) for b in beats) / WORDS_PER_SECOND
        lo, hi = (480, 600) if long else (20, 45)
        need_lo, need_hi = max(int(lo - so_far), 30), max(int(hi - so_far), 60)
        self.begin(job, "Finishing the script from recovered beats", 2)
        self.mark(job, f"Reusing {len(beats)} paid-for beats (about {so_far / 60:.1f} min); writing only the ending", 0)

        schema = _schema("script")
        for field in ("format", "target_seconds"):
            schema["properties"].pop(field)
            schema["required"].remove(field)
        schema["properties"]["beats"]["minItems"] = 1

        last_id = beats[-1]["id"]
        prompt = f"""An earlier draft of the {'long-form' if long else 'Short'} script for “{job['title']}” was cut off. These {len(beats)} beats are finished and final. Don't rewrite or repeat them:
{_compact(beats)}

{f"The next beat had started like this before the cutoff (write it in full): {unfinished[:800]}" if unfinished else ""}

Video Brief (your only source of facts):
{_compact(brief)}

Write ONLY the remaining beats, continuing straight after {last_id}:
- About {need_lo} to {need_hi} more seconds of narration (150 words per minute), so the whole video lands at {lo // 60} to {hi // 60} minutes. Usually 4 to 9 beats.
- Deliver the climax, close every open loop, give the aftermath and why it still matters, and {"end with a specific bridge to another big sports moment, not a subscribe plea" if long else "end on a line that loops back to the first frame"}.
- Same rules as the finished beats: honest retention_purpose labels, source_ref = 1-based brief fact number for every factual claim (null only for no claim), no fact outside the brief, on_screen_text of 8 words or fewer, visual_intent following the channel's visual rules (no AI likeness of real people, no logos, no broadcast footage).
- originality_statement and self_check cover the whole script, finished beats included.
Keep your planning short: the beats are the deliverable."""
        result = await self.claude.structured(
            agent=self.name, job=job, settings=self.settings_fn(), system=system, prompt=prompt,
            schema=schema, reserve_usd=RESERVE["script_finish"], effort="low", max_tokens=12000, kind="script-finish",
        )
        new = result.data["beats"]
        merged = beats + new
        for i, beat in enumerate(merged, 1):  # one clean id sequence across old and new beats
            beat["id"] = f"b{i:02d}"
        script = _timed({
            "format": job["format"],
            "beats": merged,
            "originality_statement": result.data["originality_statement"],
            "self_check": result.data["self_check"],
        })
        self.mark(job, f"Script finished: {len(beats)} recovered + {len(new)} new beats, about {script['target_seconds'] / 60:.1f} minutes (${result.cost_usd:.2f}).", 2)
        return Outcome(artifacts={"script": script})

    async def expand_narration(self, job: dict, notes: str) -> tuple[dict, str]:
        """Explain the numbers in an existing script. Only narration changes, so Opus writes only that."""
        brief = artifacts.latest(self.db, job["id"], "brief")
        script = artifacts.latest(self.db, job["id"], "script")
        current = sum(_words(b["narration"]) for b in script["beats"])
        lo, hi = NARRATION_WORDS
        self.begin(job, "Explaining the numbers in the narration", 2)
        self.mark(job, f"Rewriting narration only, from {current} words toward {lo} to {hi}", 0)
        listing = [{"id": b["id"], "narration": b["narration"], "on_screen_text": b["on_screen_text"]} for b in script["beats"]]
        prompt = f"""The channel owner wants the narration for “{job['title']}” to carry more analysis. The script is otherwise final.

Video Brief (your only source of facts):
{_compact(brief)}

Current narration, beat by beat:
{_compact(listing)}

Rewrite the narration so it gives real insight rather than a recital of numbers. The audience is intelligent. Say each thing once: never restate what the viewer just heard in slightly different words. Never say arithmetic they can do themselves: no "60 home runs, up from 47, that's 13 more". Give them what the numbers can't: why it happened, what made it possible or hard, what people at the time missed, what it changed, what a number hides. Interpretation is welcome when it's clearly your reading of the facts; new facts are not.
- Add a sentence or two after a number where that earns its place. A beat with nothing to explain stays as it is: leave it out of your answer. Never pad: no repeated points, no filler, no hype.
- The whole narration should come to about {lo} to {hi} words (it's {current} now). No beat over about 100 words.
- Keep each beat's job and the beat order, and keep what already works word for word. Each beat must still match its on-screen text.
- Use only numbers from the brief, or simple arithmetic on them: differences, shares, rates, ratios. Never bring in a player, game or record the brief doesn't have. Say a figure is worked out when it isn't quoted, without repeating that in every sentence.
- Write every figure in digits, so the studio can check them: 28 of 32, 7 in 8, 22 more.
- Spoken, not written: short sentences a person would actually say.

Fixes the owner asked for:
{notes}

Return only the beats whose narration changed, each with its id and its full new narration. Keep your planning short."""
        result = await self.claude.structured(
            agent=self.name, job=job, settings=self.settings_fn(), system=self._script_system(job["format"] == "long"), prompt=prompt,
            schema=NARRATION_SCHEMA, reserve_usd=RESERVE["narration"], effort="low", max_tokens=10000, kind="narration",
        )
        changed = {b["id"]: b["narration"].strip() for b in result.data["beats"] if b["narration"].strip()}
        expanded = json.loads(json.dumps(script))
        matched = [b for b in expanded["beats"] if b["id"] in changed]
        if not matched:
            raise ValueError("the narration pass returned no beats from this script")
        for beat in matched:
            beat["narration"] = changed[beat["id"]]
        _timed(expanded)
        words = sum(_words(b["narration"]) for b in expanded["beats"])
        to_check = new_numbers(brief, script, expanded)
        summary = (f"Narration rewritten: {len(matched)} of {len(expanded['beats'])} beats, {current} to {words} words, "
                   f"about {expanded['target_seconds'] / 60:.1f} minutes (${result.cost_usd:.2f}).")
        if to_check:
            summary += " New figures to check: " + ", ".join(to_check) + "."
        self.mark(job, summary, 2)
        return expanded, summary

    async def write_shorts(self, job: dict) -> list[dict]:
        """Three Shorts from one finished long-form, in one call: research is reused and they can't all pick the same idea."""
        brief = artifacts.latest(self.db, job["id"], "brief")
        script = artifacts.latest(self.db, job["id"], "script")
        lo, hi = SHORT_SECONDS
        self.begin(job, f"Writing {SHORTS_WANTED} Shorts from the finished video", 2)
        self.mark(job, f"Writing {SHORTS_WANTED} Short scripts, reusing the research", 0)
        facts = {"promise": brief["promise"], "angle": brief["angle"], "facts": brief["facts"]}
        listing = [{"id": b["id"], "narration": b["narration"]} for b in script["beats"]]
        prompt = f"""Write {SHORTS_WANTED} YouTube Shorts drawn from the finished long-form video “{job['title']}”.

Research (your only source of facts; source_ref is the 1-based number of the fact in this list):
{_compact(facts)}

The long-form narration, for wording and analysis you can reuse:
{_compact(listing)}

Requirements for each Short:
- A complete, standalone idea for someone who has never seen the long video. Never say "part 2", "in the full video" or "as we saw".
- The {SHORTS_WANTED} must be built on different ideas and different numbers, with no overlap in their hooks.
- {lo} to {hi} seconds: {int(lo * WORDS_PER_SECOND) + 10} to {int(hi * WORDS_PER_SECOND) - 5} words of narration at 150 words per minute, in 4 to 8 beats of 3 to 8 seconds each.
- The first beat is the payoff or the strangest fact, and its on_screen_text must work alone. No greeting, no channel name.
- The last line connects back to the first frame, so the Short replays naturally.
- The audience is intelligent. Never say arithmetic they can do themselves: no "60 home runs, up from 47, that's 13 more". Give them what the numbers can't: why it happened, what made it possible or hard, what people at the time missed, what it changed, what a number hides. Interpretation is welcome when it's clearly your reading of the facts; new facts are not.
- Say each thing once. Never restate what the viewer just heard in slightly different words, and never set up a point by announcing it ("keep your eye on") when you can simply make it. Each sentence adds something new.
- on_screen_text: 8 words or fewer. Write every figure in digits. Label a worked-out figure as worked out.
- visual_intent: {VISUAL_RULES.replace("{host}", HOST_NAME) if VISUAL_STYLE == "sketch" else "cartoon scenes of the key moments, animated charts, moving play diagrams, timelines and scoreboards. No likeness of a real person, no logo, no broadcast footage."}
- idea: a label of 2 to 5 words for the channel owner. adds: one sentence on what this Short gives a viewer.

Avoid these known problems in the long version:
- Don't call the crowd small: nothing here says what a normal crowd was.
- A gap between two percentages is "percentage points", never "points".
- Don't say Imhoff fouled out or ran out of fouls: the box score shows 6 fouls in 20 minutes, and that's all we know.
- Don't suggest the game ended at 100: play stopped with 46 seconds on the clock, and the final was 169-147.
Keep your planning short: the beats are the deliverable."""
        result = await self.claude.structured(
            agent=self.name, job=job, settings=self.settings_fn(), system=self._script_system(False), prompt=prompt,
            schema=SHORTS_SCHEMA, reserve_usd=RESERVE["shorts"], effort="low", max_tokens=7000, kind="shorts",
        )
        shorts = []
        for item in result.data["shorts"][:SHORTS_WANTED]:
            beats = [{**b, "id": f"b{i:02d}"} for i, b in enumerate(item["beats"], 1)]
            made = _timed({"format": "short", "beats": beats, "originality_statement": item["adds"], "self_check": []})
            seconds = made["target_seconds"]
            made["self_check"] = [{"rule": f"Runs {lo} to {hi} seconds", "passed": lo <= seconds <= hi, "note": f"About {seconds:.0f} seconds at 150 words per minute."}]
            artifacts.validate("script", made)  # before any job exists, so a bad answer leaves nothing half made
            note = f"From job #{job['id']}: {len(beats)} beats, about {seconds:.0f} seconds."
            to_check = new_numbers(brief, script, made)
            if to_check:
                note += " New figures to check: " + ", ".join(to_check) + "."
            shorts.append({"idea": item["idea"].strip(), "script": made, "note": note})
        self.mark(job, f"Wrote {len(shorts)} Short scripts (${result.cost_usd:.2f}).", 2)
        return shorts

    # Packaging ---------------------------------------------------------------------

    async def _package(self, job: dict, route: Route) -> Outcome:
        """Titles, thumbnails, description, chapters. Claude writes the words; code draws and checks everything else."""
        from ..media import photos, themes, thumbnails

        brief = artifacts.latest(self.db, job["id"], "brief")
        script = artifacts.latest(self.db, job["id"], "script")
        previous = artifacts.latest(self.db, job["id"], "package")
        long = job["format"] == "long"
        folder = MEDIA_DIR / f"job-{job['id']}"
        timeline = json.loads((folder / "timeline.json").read_text())
        starts = beat_starts(timeline)
        self.begin(job, route.task, 3)
        self.mark(job, f"Writing {'3 title and thumbnail angles' if long else 'the title'} and the description", 0)

        system = f"""You are the Packaging agent for {CHANNEL_NAME}, {PITCH}. You write what makes someone click, and the video has to keep that promise.

Playbook rules you must follow (confidence in brackets):
{_playbook({"packaging", "policy"})}"""
        listing = [{"id": b["id"], "start": clock(starts.get(b["id"], 0)), "narration": b["narration"]} for b in script["beats"]]
        revision = f"""

This replaces an earlier package:
{_compact(previous)}

The channel owner's notes on it:
{job['note']}""" if previous and job.get("note") else ""
        options = """- options: exactly 3, one per angle (curiosity, myth_bust, story). They must differ in promise or emotion, not be three wordings of one idea. Start from the brief's package_concepts where they're good.
- layout: use each once. "number" is one huge number beside the Professor. "versus" is two numbers with an arrow, small then big. "silhouette" is one number beside a faceless player.
- big: the number or scoreline on the thumbnail, as short as possible, like 100 or 28/32. small: the number it's compared with for "versus", otherwise an empty string.
- headline: up to 4 words on the thumbnail, adding to the title rather than repeating it. Thumbnails can't show anything else: no faces, photos or logos.
- chapters: 5 to 8, each with the beat_id where it starts (the first is the first beat) and a plain title of 40 characters or fewer.""" if long and VISUAL_STYLE != "sketch" else """- options: exactly 3, one per angle (curiosity, myth_bust, story). They must differ in promise or emotion, not be three wordings of one idea. Start from the brief's package_concepts where they're good.
- layout: "sketch" for all three: black capitals on white beside a drawing from the video, one word in a red box, a red arrow.
- headline: the thumbnail's words, 2 to 5, adding to the title rather than repeating it, like "WHEN YOUR TEAM LOSES" or "YOUR BRAIN ON GAME DAY".
- big: the one word of the headline that goes in the red box: the word that carries the emotion. small: an empty string.
- chapters: one per numbered item, plus the opening: each with the beat_id where it starts (the first is the first beat) and a plain title of 40 characters or fewer.""" if long else """- options: exactly 1, using the angle that suits a Short best. Set layout to "number", big to the key number, small to an empty string and headline to up to 4 words. No thumbnail gets drawn for a Short.
- chapters: an empty list."""
        prompt = f"""Write the YouTube package for “{job['title']}”.

Video Brief (your only source of facts):
{_compact(brief)}

The finished narration, with where each beat starts:
{_compact(listing)}

Requirements:
{options}
- title: under 70 characters if you can, never over {MAX_TITLE}, with the key idea in the first 40. Sentence case, no emoji. It must be true, and the video must deliver it in its first 30 seconds or as its main story.
- Every figure in a title or thumbnail must be exactly as it appears in the brief or narration: 51.1%, never a rounded 51%.
- description: 60 to 120 words, and the first two lines must make someone want to watch. Only the text: the studio adds chapters, sources and photo credits itself, so don't write those, and no links or hashtags.
- tags: 8 to 12 plain search terms.
- pinned_comment: one specific question that invites debate about this moment. Never ask people to subscribe, and nothing about betting.
Keep your planning short.{revision}"""
        result = await self.claude.structured(
            agent=self.name, job=job, settings=self.settings_fn(), system=system, prompt=prompt, schema=PACKAGE_SCHEMA,
            reserve_usd=RESERVE["package"], effort="low", max_tokens=5000, kind="package", model=MODEL_RESEARCH,
        )
        data = result.data
        chosen = data["options"][:3 if long else 1]
        self.mark(job, "Drawing thumbnails and checking them at phone size" if long else "Assembling the description", 1)

        theme = themes.build(brief.get("look"), job.get("topic_id"))
        pictures = thumbnail_pictures(artifacts.latest(self.db, job["id"], "storyboard") or {"frames": []})

        def draw() -> list[str]:
            paths = []
            for letter, option in zip("abc", chosen):
                layout = "number" if option["layout"] == "versus" and not option["small"].strip() else option["layout"]
                if VISUAL_STYLE == "sketch":
                    layout, option = "sketch", {**option, "picture": pictures[min(len(pictures) - 1, "abc".index(letter))] if pictures else None}
                paths.append(thumbnails.draw({**option, "layout": layout, "thumb": (theme or {}).get("thumb")}, folder / f"thumbnail-{letter}.png"))
            thumbnails.phone_check(paths, folder / "thumbnails-phone.png")
            return [p.name for p in paths]

        files = await asyncio.to_thread(draw) if long else [None] * len(chosen)
        used = photos.used_in(timeline)
        chapters = chapter_list(data["chapters"], starts) if long else []
        credits = photos.credits_text(used) if used else ""
        if VISUAL_STYLE == "sketch":
            credits = f"{credits}\n\n{SKETCH_NOTE}".strip()
        description = full_description(data["description"], chapters, brief, credits)
        (folder / "description.txt").write_text(description)
        package = {
            "options": [
                {"title": short_title(o["title"]),
                 "thumbnail_concept": (f"{o['angle'].replace('_', ' ')}: {thumbnails.short(o['headline'], 5)}, {o['big'].upper()} in the red box" if VISUAL_STYLE == "sketch"
                                       else f"{o['angle'].replace('_', ' ')}: {thumbnails.short(o['headline'])} with {o['big']}"),
                 "thumbnail_path": file}
                for o, file in zip(chosen, files)
            ],
            "description": description,
            "chapters": chapters,
            "tags": trim_tags(data["tags"]),
            "pinned_comment": data["pinned_comment"].strip(),
            "ai_disclosure": SKETCH_DISCLOSURE if VISUAL_STYLE == "sketch" else DISCLOSURE,
        }
        to_check = package_figures(chosen, brief, script)
        summary = f"Package ready: {len(chosen)} option(s), {len(chapters)} chapters (${result.cost_usd:.2f})."
        if to_check:
            summary += " Figures not in the brief or script, check them: " + ", ".join(to_check) + "."
        self.mark(job, summary, 3)
        return Outcome(artifacts={"package": package}, note=summary)

    # QA-2 -------------------------------------------------------------------------

    async def _qa_video(self, job: dict, route: Route) -> Outcome:
        """Measured checks on the preview. Free: this step never calls Claude."""
        from ..media import qa

        self.begin(job, route.task, 1)
        folder = MEDIA_DIR / f"job-{job['id']}"
        render = artifacts.latest(self.db, job["id"], "render")
        report = await asyncio.to_thread(
            qa.review, job["format"], Path(render["path"]), "preview" if render["preview"] else "final",
            json.loads((folder / "timeline.json").read_text()), json.loads((folder / "words.json").read_text()),
            artifacts.latest(self.db, job["id"], "script"), artifacts.latest(self.db, job["id"], "asset_manifest"),
        )
        self.mark(job, f"QA-2 {'passed' if report['passed'] else 'found ' + str(len(report['fixes'])) + ' problem(s)'}. Cost: $0.", 1)
        note = None if report["passed"] else "QA-2 fixes: " + " | ".join(report["fixes"])
        return Outcome(passed=report["passed"], artifacts={"qa_report": report}, note=note)

    # QA-1 -------------------------------------------------------------------------

    async def _qa_report(self, job: dict, route: Route) -> Outcome:
        if job["stage"] != "scripted":
            return await self._qa_video(job, route)
        brief = artifacts.latest(self.db, job["id"], "brief")
        script = artifacts.latest(self.db, job["id"], "script")
        long = job["format"] == "long"
        self.begin(job, route.task, 2)

        # Deterministic checks first; Claude can't overrule these.
        local = []
        n_facts = len(brief.get("facts", []))
        bad_refs = [b["id"] for b in script["beats"] if b.get("source_ref") is not None and not 1 <= b["source_ref"] <= n_facts]
        if bad_refs:
            local.append(f"Beats {', '.join(bad_refs)} cite fact numbers that don't exist in the brief.")
        secs = script["target_seconds"]
        lo, hi = (480, 720) if long else (15, 60)
        if not lo <= secs <= hi:
            local.append(f"Narration runs about {secs:.0f} s; the target is {lo} to {hi} s.")
        words = sum(_words(b["narration"]) for b in script["beats"])
        self.mark(job, f"Reviewing {len(script['beats'])} beats ({words} words, about {secs / 60:.1f} min)", 0)

        system = f"""You are the QA & Compliance agent for {CHANNEL_NAME}. You are an independent reviewer: you did not write this script and you owe its author nothing. Your job is to stop weak, misleading or risky scripts before money is spent producing them. Be specific and strict, but don't invent problems.

Channel strategy:
{_strategy()}

Playbook:
{_playbook({"policy", "long-form" if long else "shorts", "algorithm", "niche", "packaging"})}"""
        prompt = f"""Review this {'long-form' if long else 'Short'} script (QA-1, script gate) for “{job['title']}”.

Video Brief:
{_compact(brief)}

Script:
{_compact(script)}

Measured by the system: {words} narration words, about {secs:.0f} seconds.

Return gate "script" and exactly these checks, in this order, each with passed true/false and a short note:
1. Hook test: {"the first 30 seconds prove the title, say why it matters and give a roadmap, with no greeting or self-introduction" if long else "the first beat lands the payoff or strangest fact in 1 to 3 seconds and works as standalone on-screen text"}.
2. Promise match: the hook and content deliver what the brief's promise and package concepts claim; no bait-and-switch.
3. Retention audit: {"1 to 3 open loops, closed; pattern interrupts; no stretch over 60 seconds without a new beat or reset; a mid-video payoff; a re-hook near 3:00; no padding" if long else "dense, no wasted beat, ending loops back to the first frame"}.
4. Originality and anti-template: {RECIPE['originality']}.
5. Facts and sources: every factual statement is supported by the cited brief fact; no claim appears that isn't in the brief; no invented numbers.
6. Rights and safety: visual intents follow the channel's rules (no AI likeness of real people, no logos, no broadcast footage); advertiser-friendly; respectful.
7. Length and pacing: {"8 to 12 minutes" if long else "20 to 45 seconds"}, natural spoken pacing.

passed is true only if every check passes. For each failed check, add one concrete, actionable fix to fixes (what to change and where, by beat id)."""
        result = await self.claude.structured(
            agent=self.name, job=job, settings=self.settings_fn(), system=system, prompt=prompt,
            schema=_schema("qa_report"), reserve_usd=RESERVE["qa_report"], effort="high", max_tokens=8000, kind="qa_report",
        )
        report = result.data
        report["gate"] = "script"
        if local:
            report["checks"].append({"name": "System checks", "passed": False, "note": " ".join(local)})
            report["fixes"] = report.get("fixes", []) + local
            report["passed"] = False
        else:
            report["checks"].append({"name": "System checks", "passed": True, "note": "Fact references and length verified."})
        report["passed"] = bool(report["passed"]) and all(c["passed"] for c in report["checks"])
        note = None if report["passed"] else "QA-1 fixes: " + " | ".join(report["fixes"])
        verdict = "passed" if report["passed"] else f"sent it back with {len(report['fixes'])} fix(es)"
        self.mark(job, f"QA-1 {verdict} (${result.cost_usd:.2f}).", 2)
        return Outcome(passed=report["passed"], artifacts={"qa_report": report}, note=note)
