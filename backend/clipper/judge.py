"""Stage 4: Claude reads the stream around each moment and says whether it makes a clip, where to cut it,
and what to call it. Cuts are then moved onto word boundaries, so a clip never starts or ends mid-word.

Claude gets the transcript, the signal notes and a few small frames around each peak. The frames were added
2026-11-12, after an IRL skit with a GTA-style overlay read like gameplay from the words alone.
"""
import base64
import json
import re
import subprocess
from pathlib import Path

import anthropic

from studio.llm import _schema_problem, api_schema, usage_cost

from . import transcribe
from .db import DB, now

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["moments"],
    "properties": {"moments": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "keep", "hook", "standalone", "payoff", "start", "end", "moment", "title", "caption", "hashtags", "reason"],
        "properties": {
            "id": {"type": "integer"},
            "keep": {"type": "boolean"},
            "hook": {"type": "integer", "minimum": 0, "maximum": 10},
            "standalone": {"type": "integer", "minimum": 0, "maximum": 10},
            "payoff": {"type": "integer", "minimum": 0, "maximum": 10},
            "start": {"type": "number"},
            "end": {"type": "number"},
            "moment": {"type": "string", "enum": ["glitch_chaos", "chase_shootout", "reaction", "story_reveal", "other"]},
            "title": {"type": "string"},
            "caption": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
    }}},
}

SYSTEM = """You pick short-form clips for {channel}, a YouTube Shorts and TikTok channel of GTA 6 stream highlights.

For each moment you get the stream's transcript around a peak in the signals (loudness, raised voice, scene cuts,
speech speed, hype phrases, chat speed and emotes), with times in seconds from the start of the excerpt, and a few
frames from around the peak. Use the frames to tell what's on screen: GTA gameplay, a menu or loading screen, the
streamer's camera, or real life. A moment with little talking can still be a clip when the frames show action.

A strong clip:
- hooks in the first two seconds: it starts on the action or the line that makes you stay, not on setup;
- stands alone: someone scrolling, who has never seen this streamer, understands it without context;
- pays off quickly: the funny, shocking or impressive part lands, and the clip ends soon after it.
Moments worth the most: glitches and chaos, chases and shootouts, big streamer reactions, story moments and reveals.
{game_rule}

For each moment return:
- keep: whether it should become a clip;
- hook, standalone, payoff: 0-10 each, honestly (most moments aren't clips);
- start and end in excerpt seconds: {min_s}-{max_s} seconds long, starting just before the first line that matters
  and ending just after the payoff. They'll be moved onto word boundaries;
- moment: the kind;
- title: under 70 characters, saying what happens as a viewer would put it. No ALL CAPS, no emoji spam, nothing
  that didn't happen. Use the streamer's name when it helps;
- caption: one short line for the description;
- hashtags: 3 to 6, no spaces, starting with the tag of the game on screen (#GTA6 only for GTA 6; #GTA5 for GTA V,
  #GTA4 for GTA IV, and so on), never a tag for a game that isn't shown;
- reason: one sentence on why, for the owner checking your picks.
Return every moment you were given, by id."""


class BudgetExceeded(Exception):
    pass


def clock(t: float) -> str:
    return f"{int(t // 60):02}:{t % 60:04.1f}"


def excerpt(words: list[dict], start: float, end: float) -> str:
    """The transcript between two times, one line per sentence or pause, each with its time from `start`."""
    lines, line, line_start = [], [], None
    for w in words:
        if w["start"] < start or w["start"] > end:
            continue
        if line and (w["start"] - line[-1]["end"] > 1.2 or len(line) >= 18):
            lines.append(f"[{line_start - start:5.1f}] {' '.join(x['word'] for x in line)}")
            line = []
        if not line:
            line_start = w["start"]
        line.append(w)
        if w["word"][-1:] in ".?!":
            lines.append(f"[{line_start - start:5.1f}] {' '.join(x['word'] for x in line)}")
            line = []
    if line:
        lines.append(f"[{line_start - start:5.1f}] {' '.join(x['word'] for x in line)}")
    return "\n".join(lines) or "(nothing said)"


def snap(cfg: dict, words: list[dict], start: float, end: float, bounds: tuple[float, float]) -> tuple[float, float]:
    """Move a cut onto word boundaries, finish a sentence that ends just after, and keep it within the clip lengths."""
    c = cfg["clips"]
    lo, hi = bounds
    inside = [w for w in words if w["end"] > start - 0.3 and w["start"] < end + 0.3]
    if inside:
        start = inside[0]["start"] - c["lead_seconds"]
        last = inside[-1]
        first = inside[0]
        finished = last["word"][-1:] in ".?!"
        for w in words[words.index(last):]:  # finish the sentence if it ends soon
            if w["end"] - last["end"] > c["sentence_reach_seconds"]:
                break
            if w["word"][-1:] in ".?!":
                last, finished = w, True
                break
        if not finished:  # it runs on too long: end instead on the last sentence that did finish ("…my aim bro." not "…bro. Can")
            done = [w for w in inside if w["word"][-1:] in ".?!" and last["end"] - w["end"] <= c["sentence_reach_seconds"]
                    and w["end"] - first["start"] >= c["min_seconds"]]
            last = done[-1] if done else last
        end = last["end"] + c["tail_seconds"]
    start, end = max(start, lo), min(end, hi)
    if end - start < c["min_seconds"]:  # too short: grow the end by whole words, then the start
        later = [w for w in words if w["end"] > end and w["end"] <= start + c["min_seconds"] + 5]
        end = min(max([w["end"] + c["tail_seconds"] for w in later] + [start + c["min_seconds"]]), hi)
        start = max(min(start, end - c["min_seconds"]), lo)
    if end - start > c["max_seconds"]:  # too long: end at the last sentence (or word) that fits
        fits = [w for w in words if start < w["end"] <= start + c["max_seconds"] - c["tail_seconds"]]
        sentence = [w for w in fits if w["word"][-1:] in ".?!"]
        end = ((sentence or fits)[-1]["end"] + c["tail_seconds"]) if fits else start + c["max_seconds"]
    return round(start, 2), round(end, 2)


def frame(db: DB, source_id: int, t: float, width: int) -> bytes | None:
    """A small JPEG of the stream at `t` seconds, from whichever piece holds that moment."""
    piece = next((s for s in db.segments(source_id) if s["start"] <= t < s["start"] + s["duration"]), None)
    if not piece:
        return None
    at = t - piece["start"] + piece["offset"]
    shot = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", piece["path"], "-frames:v", "1", "-vf", f"scale={width}:-2,format=yuvj420p",  # JPEG wants full range; live pieces are limited
                           "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "5", "pipe:1"], capture_output=True).stdout
    return shot or None


def frames_for(cfg: dict, db: DB, source_id: int, moment: dict, window: tuple[float, float]) -> list[dict]:
    """Content blocks: a few frames spread around the peak, each labelled with its time in the excerpt."""
    j = cfg["judge"]
    before, after = j["frame_span"]
    n = j["frames"]
    times = [moment["peak"] + before + (after - before) * i / max(n - 1, 1) for i in range(n)]
    blocks = []
    for t in (min(max(t, window[0]), window[1] - 0.5) for t in times):
        shot = frame(db, source_id, t, j["frame_width"])
        if shot:
            blocks += [{"type": "text", "text": f"Frame at {t - window[0]:.1f} s:"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(shot).decode()}}]
    return blocks


def reserve(cfg: dict, prompt: str, images: int = 0) -> float:
    """The most a call could cost: its prompt at a cautious 3 characters a token, its frames, and every output token used."""
    tokens = len(prompt) // 3 + images * cfg["judge"]["tokens_per_frame"]
    usage = type("U", (), {"input_tokens": tokens, "output_tokens": cfg["judge"]["max_tokens"]})()
    return usage_cost(cfg["judge"]["model"], usage)[0]


def run(cfg: dict, db: DB, source_id: int, client: anthropic.Anthropic | None = None, log=None) -> int:
    """Judge every moment not yet judged, a few per call. Stops before a call that could pass the monthly cap."""
    j, d, c = cfg["judge"], cfg["detect"], cfg["clips"]
    source = db.source(source_id)
    creator = db.one("SELECT * FROM creators WHERE id = ?", (source["creator_id"],)) or {"name": "the streamer"}
    words = transcribe.transcript(db, source_id)
    waiting = sorted(db.candidates(source_id, "found"), key=lambda x: x["peak"])
    game_rule = ("Not GTA (another game, just chatting, sponsor reads, waiting screens) is never a keep." if j["require_gta"] else
                 "This is a test run on a stream that may not be GTA: judge the moment on its own merits, whatever the game. "
                 "Just chatting, sponsor reads and waiting screens still aren't clips.")
    system = SYSTEM.format(channel=j["channel"], min_s=c["min_seconds"], max_s=c["max_seconds"], game_rule=game_rule)
    client = client or anthropic.Anthropic()
    judged = 0
    for batch in (waiting[i:i + j["per_call"]] for i in range(0, len(waiting), j["per_call"])):
        windows = {m["id"]: (max(m["peak"] - d["context_before"], 0), min(m["peak"] + d["context_after"], db.length(source_id))) for m in batch}
        content = [{"type": "text", "text": f"Streamer: {creator['name']}. Stream title: {source['title']}"}]
        for m in batch:
            content.append({"type": "text", "text": f"## Moment {m['id']}\nPeak at {m['peak'] - windows[m['id']][0]:.1f} s into this excerpt. "
                            f"Signals at the peak: {', '.join(f'{k} {v}' for k, v in json.loads(m['signals']).items()) or 'none'}.\n"
                            + excerpt(words, *windows[m["id"]])})
            content += frames_for(cfg, db, source_id, m, windows[m["id"]])
        prompt = "\n\n".join(b["text"] for b in content if b["type"] == "text")
        worst = reserve(cfg, system + prompt, sum(b["type"] == "image" for b in content))
        spent = db.spent_this_month()
        if spent + worst > cfg["budget"]["monthly_usd"]:
            raise BudgetExceeded(f"Judging the next {len(batch)} moments could cost up to ${worst:.2f}; this month's spend is ${spent:.2f} "
                                 f"of the ${cfg['budget']['monthly_usd']:.2f} cap. Not starting it.")
        response = client.messages.create(model=j["model"], max_tokens=j["max_tokens"], system=system, messages=[{"role": "user", "content": content}],
                                          output_config={"format": {"type": "json_schema", "schema": api_schema(SCHEMA)}})
        cost = usage_cost(response.model, response.usage)[0]
        db.add_spend("judge", source_id, response.model, response.usage.input_tokens, response.usage.output_tokens, cost)
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            answer = json.loads(text)
            problem = _schema_problem(SCHEMA, answer)
        except json.JSONDecodeError:
            answer, problem = None, "not valid JSON"
        if problem:
            raw = cfg["paths"]["media"] / "sources" / f"{source_id:05}" / "raw" / f"judge-{now().replace(':', '-')}.txt"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(text)
            for m in batch:
                db.set_candidate(m["id"], status="error", reason=f"Claude's answer didn't fit ({problem}); saved to {raw}")
            log and log.error("Judging failed for %d moments (%s). Raw answer: %s", len(batch), problem, raw)
            continue
        verdicts = {v["id"]: v for v in answer["moments"]}
        for m in batch:
            v = verdicts.get(m["id"])
            if not v:
                db.set_candidate(m["id"], status="error", reason="Claude left this moment out.")
                continue
            lo, hi = windows[m["id"]]
            start, end = snap(cfg, words, lo + v["start"], lo + v["end"], (lo, hi))
            claude = (v["hook"] + v["standalone"] + v["payoff"]) / 3
            signal = min(m["signal"] / (d["z_cap"] * sum(d["weights"].values()) / 4), 1) * 10  # the signals' score on Claude's 0-10 scale
            tags = [t if t.startswith("#") else f"#{t}" for t in (x.replace(" ", "") for x in v["hashtags"])]
            db.set_candidate(m["id"], status="judged" if v["keep"] else "dropped", start=start, end=end, moment=v["moment"],
                             scores=json.dumps({k: v[k] for k in ("hook", "standalone", "payoff")}),
                             score=round(j["claude_weight"] * claude + j["signal_weight"] * signal, 2),
                             title=v["title"].strip(), caption=v["caption"].strip(), hashtags=json.dumps(tags), reason=v["reason"].strip(), judged_at=now())
            judged += 1
        log and log.info("Judged %d moments for $%.4f (%s).", len(batch), cost, response.model)
    export(cfg, db, source_id)
    return judged


def export(cfg: dict, db: DB, source_id: int) -> Path:
    """The ranked list as JSON, to check by eye: kept clips first, each with a link back to that second of the VOD."""
    source = db.source(source_id)
    rows = []
    for m in db.candidates(source_id):
        at = int((source["window_start"] or 0) + (m["start"] if m["start"] is not None else m["peak"]))
        base = source["url"].split("?")[0] if source["platform"] == "twitch" else re.sub(r"[&?]t=[^&]*", "", source["url"])
        link = f"{base}?t={at // 3600}h{at // 60 % 60}m{at % 60}s" if source["platform"] == "twitch" else \
            (f"{base}&t={at}s" if source["platform"] == "youtube" else None)
        rows.append({"id": m["id"], "status": m["status"], "score": m["score"], "title": m["title"], "moment": m["moment"],
                     "start": m["start"], "end": m["end"], "length": round(m["end"] - m["start"], 1) if m["end"] else None,
                     "peak": m["peak"], "signal": m["signal"], "signals": json.loads(m["signals"]), "scores": json.loads(m["scores"] or "null"),
                     "caption": m["caption"], "hashtags": json.loads(m["hashtags"] or "[]"), "reason": m["reason"], "watch": link})
    rows.sort(key=lambda r: (r["status"] != "judged", -(r["score"] or 0), -r["signal"]))
    path = cfg["paths"]["media"] / "sources" / f"{source_id:05}" / "candidates.json"
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    return path
