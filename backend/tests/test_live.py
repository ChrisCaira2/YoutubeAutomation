"""Live mode with a fake Claude client: no network, no spending."""
import asyncio
import json
import time
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from studio import artifacts
from studio.api import build, create_app
from studio.agents.base import Outcome
from studio.agents.live import chapter_list, clock, complete_beats, full_description, trim_tags
from studio.llm import Claude, api_schema, usage_cost

LONG_BEATS = [
    {"id": f"b{i}", "narration": "word " * 70, "on_screen_text": "Text", "visual_intent": "Scoreboard diagram",
     "retention_purpose": "hook" if i == 1 else "context", "source_ref": 1, "est_seconds": 28}
    for i in range(1, 21)
]
BRIEF = {
    "audience": "Fans", "promise": "The real story", "angle": "How unlikely it was",
    "facts": [{"claim": f"Fact {i}", "source_title": "Source", "source_url": "https://example.com"} for i in range(1, 7)],
    "competitors": [{"title": "Clip", "url": None, "how_we_differ": "Numbers"}],
    "hooks": ["a", "b", "c", "d", "e"],
    "package_concepts": [{"title": "T", "thumbnail_concept": "C"}] * 3,
    "look": {"team": "Warriors", "primary": "#003DA5", "secondary": "#FFC72C", "highlight": "#FFC72C", "background": "dark", "texture": "plain", "font": "din"},
    "pronunciations": [],
}
SCRIPT = {"format": "long", "target_seconds": 560, "beats": LONG_BEATS, "originality_statement": "Adds odds",
          "self_check": [{"rule": "No greeting", "passed": True, "note": ""}]}


def qa(passed: bool) -> dict:
    return {"gate": "script", "passed": passed,
            "checks": [{"name": "Hook test", "passed": passed, "note": "" if passed else "Greets first"}],
            "fixes": [] if passed else ["Cut the greeting in b1"]}


def usage(i=1000, o=2000, searches=0):
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0, cache_read_input_tokens=0,
              server_tool_use=NS(web_search_requests=searches))


class FakeStream:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self.message


class FakeClient:
    """Answers each call from a queue of JSON payloads and records what was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.repairs = []
        self.beta = NS(messages=NS(stream=self._stream))
        self.messages = NS(stream=self._repair_stream)

    def _repair_stream(self, **params):
        """The fast-model JSON repair call: returns the next queued payload."""
        self.repairs.append(params)
        data, _ = self.replies.pop(0)
        return FakeStream(NS(model="claude-haiku-5-5", stop_reason="end_turn", usage=usage(500, 500),
                             content=[NS(type="text", text=json.dumps(data))]))

    def _stream(self, **params):
        self.calls.append(params)
        data, searches = self.replies.pop(0)
        msg = NS(model="claude-opus-5-5", stop_reason="end_turn", usage=usage(searches=searches),
                 content=[NS(type="text", text=json.dumps(data))])
        return FakeStream(msg)


async def run_until(sr, cond, timeout=10.0):
    loop = asyncio.create_task(sr.run())
    try:
        async def wait():
            while not cond():
                await asyncio.sleep(0.02)
        await asyncio.wait_for(wait(), timeout)
    finally:
        loop.cancel()
        for t in list(sr.inflight.values()):
            t.cancel()
        await asyncio.sleep(0)


class _LazyClaude(Claude):
    """build() creates the DB and bus, so the wrapper looks them up after construction."""

    def __init__(self, client, holder):
        self.client = client
        self.holder = holder

    @property
    def db(self):
        return self.holder["sr"].db

    @property
    def bus(self):
        return self.holder["sr"].bus


def live(replies, manual_review=False):
    holder = {}
    client = FakeClient(replies)
    holder["sr"] = build(":memory:", mode="live", claude=_LazyClaude(client, holder))
    holder["sr"].db.set_setting("manual_script_review", manual_review)
    holder["sr"].halt_stages = {"qa_script"}  # these tests stop before real media production
    return holder["sr"], client


@pytest.fixture(autouse=True)
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("studio.llm.MEDIA_DIR", tmp_path)
    return tmp_path


def test_usage_cost_includes_searches():
    cost, searches = usage_cost("claude-opus-5-5", usage(1_000_000, 100_000, searches=5))
    assert searches == 5
    assert cost == pytest.approx(4.00 + 2.00 + 0.05)


def test_unknown_model_priced_at_top_tier():
    cost, _ = usage_cost("claude-something-new", usage(1_000_000, 0))
    assert cost == pytest.approx(10.00)


def test_api_schema_strips_unsupported_keywords():
    schema = api_schema(json.loads((artifacts.SCHEMA_DIR / "brief.json").read_text()))
    text = json.dumps(schema)
    for kw in ("minLength", "maxLength", "$schema", '"minItems": 3'):
        assert kw not in text
    url = schema["properties"]["competitors"]["items"]["properties"]["url"]
    assert url == {"anyOf": [{"type": "string"}, {"type": "null"}]}


def test_api_schema_keeps_fields_named_like_keywords():
    # Regression: stripping the "title" keyword once also deleted fields named "title".
    for kind in ("brief", "package"):
        schema = api_schema(json.loads((artifacts.SCHEMA_DIR / f"{kind}.json").read_text()))
        items = schema["properties"]["competitors" if kind == "brief" else "options"]["items"]
        assert "title" in items["properties"] and "title" in items["required"]
    concepts = api_schema(json.loads((artifacts.SCHEMA_DIR / "brief.json").read_text()))["properties"]["package_concepts"]
    assert "title" in concepts["items"]["properties"]


def test_live_job_runs_research_script_qa_then_waits():
    sr, client = live([(BRIEF, 4), (SCRIPT, 0), (qa(True), 0)])
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "qa_script"))
    asyncio.run(run_until(sr, lambda: True, timeout=1))  # give the loop a chance to (not) go further
    j = sr.db.get_job(job["id"])
    assert j["stage"] == "qa_script" and j["status"] == "active"
    assert len(client.calls) == 3
    assert client.calls[0]["tools"][0]["type"] == "web_search_20260209"
    assert all(c["fallbacks"] == "default" for c in client.calls)
    assert sr.db.job_cost(job["id"]) > 0.04  # 4 searches alone are $0.04


def test_qa_failure_sends_fixes_back_to_script():
    sr, client = live([(BRIEF, 0), (SCRIPT, 0), (qa(False), 0), (SCRIPT, 0), (qa(True), 0)])
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "qa_script"))
    revision_prompt = client.calls[3]["messages"][0]["content"]
    assert "Cut the greeting in b1" in revision_prompt


def test_system_check_fails_bad_fact_reference():
    bad = json.loads(json.dumps(SCRIPT))
    bad["beats"][0]["source_ref"] = 99
    sr, client = live([(BRIEF, 0), (bad, 0), (qa(True), 0), (SCRIPT, 0), (qa(True), 0)])
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "qa_script"))
    reports = [a["data"] for a in artifacts.for_job(sr.db, job["id"]) if a["kind"] == "qa_report"]
    assert reports[0]["passed"] is False and "don't exist" in " ".join(reports[0]["fixes"])


def test_budget_cap_blocks_before_any_call():
    sr, client = live([(BRIEF, 0)])
    sr.db.set_setting("daily_budget_usd", 0.4)  # research reserves $0.50
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["status"] == "blocked"))
    assert client.calls == []
    assert "daily cap" in sr.db.get_job(job["id"])["note"]


def test_live_without_key_starts_paused(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sr = build(":memory:", mode="live")
    asyncio.run(run_until(sr, lambda: sr.settings()["paused"] is True))
    assert sr.db.one("SELECT COUNT(*) AS n FROM events WHERE message LIKE 'No ANTHROPIC_API_KEY%'")["n"] == 1


def test_research_call_is_bounded_and_cached():
    sr, client = live([(BRIEF, 2), (SCRIPT, 0), (qa(True), 0)])
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "qa_script"))
    research = client.calls[0]
    assert research["cache_control"] == {"type": "ephemeral"}
    search, fetch = research["tools"]
    assert search["max_uses"] == 5 and fetch["max_uses"] == 6 and fetch["max_content_tokens"] == 6000
    assert all(c["cache_control"] == {"type": "ephemeral"} for c in client.calls)
    assert research["model"] == "claude-sonnet-5-5"
    assert client.calls[1]["model"] == "claude-opus-5-5"  # script stays on Opus
    assert client.calls[1]["output_config"]["effort"] == "low" and client.calls[1]["max_tokens"] == 20000


def test_manual_review_replaces_qa_agent():
    sr, client = live([(BRIEF, 0), (SCRIPT, 0)], manual_review=True)
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "scripted"))
    assert len(client.calls) == 2  # research + script, no QA call
    sr.approve_script(job["id"], "Looks great")
    j = sr.db.get_job(job["id"])
    assert j["stage"] == "qa_script" and j["status"] == "active"
    report = artifacts.latest(sr.db, job["id"], "qa_report")
    assert report["passed"] and report["checks"][0]["name"] == "Manual review"


def test_manual_rewrite_reuses_research_and_passes_notes():
    sr, client = live([(BRIEF, 0), (SCRIPT, 0), (SCRIPT, 0)], manual_review=True)
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "scripted"))
    sr.revise_script(job["id"], "Open on the scoreboard")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "scripted"
                          and len(client.calls) == 3))
    assert "Open on the scoreboard" in client.calls[2]["messages"][0]["content"]
    assert "web_search" not in json.dumps(client.calls[2].get("tools", []))  # no new research


def test_bad_format_is_saved_and_repaired_not_thrown_away(raw_dir):
    broken = json.loads(json.dumps(BRIEF))
    del broken["competitors"][0]["title"]
    sr, client = live([(broken, 0), (BRIEF, 0), (SCRIPT, 0)], manual_review=True)
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "scripted"))
    assert len(client.repairs) == 1 and client.repairs[0]["model"] == "claude-haiku-5-5"
    assert "title" in client.repairs[0]["messages"][0]["content"]
    assert list((raw_dir / f"job-{job['id']}" / "raw").glob("brief-*.txt"))


def test_paid_failure_blocks_instead_of_retrying():
    broken = {"not": "a brief"}
    sr, client = live([(broken, 0), (broken, 0)])
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["status"] == "blocked"))
    assert len(client.calls) == 1  # one paid attempt, no automatic retry
    assert "Not retrying automatically" in sr.db.get_job(job["id"])["note"]


def test_complete_beats_recovers_finished_beats_and_the_cut_off_one():
    beats_json = ",".join(json.dumps(b) for b in LONG_BEATS[:4])
    text = '{"format":"long","beats":[' + beats_json + ',{"id":"b05","narration":"Forty-six seconds left. Chamber'
    beats, unfinished = complete_beats(text)
    assert [b["id"] for b in beats] == ["b1", "b2", "b3", "b4"]
    assert unfinished.startswith('{"id":"b05"') and "Forty-six seconds" in unfinished


def test_complete_beats_handles_braces_inside_text():
    beat = {**LONG_BEATS[0], "narration": 'He said "100 {points}" twice.'}
    beats, _ = complete_beats('{"beats":[' + json.dumps(beat) + ',{"id":"b2","narr')
    assert len(beats) == 1 and beats[0]["narration"] == 'He said "100 {points}" twice.'


def test_cut_off_script_is_finished_not_rewritten(raw_dir):
    recovered = [dict(b, id=f"b{i:02d}") for i, b in enumerate(LONG_BEATS[:15], 1)]
    ending = {"beats": [dict(LONG_BEATS[0], id="x1", retention_purpose="payoff"),
                        dict(LONG_BEATS[0], id="x2", retention_purpose="bridge")],
              "originality_statement": "Adds odds", "self_check": [{"rule": "Bridge", "passed": True, "note": ""}]}
    sr, client = live([(ending, 0)], manual_review=True)
    job = sr.create_job(1, "long")
    artifacts.save(sr.db, job["id"], "brief", BRIEF, "research")
    sr.move(sr.db.get_job(job["id"]), "researched")
    raw = raw_dir / f"job-{job['id']}" / "raw"
    raw.mkdir(parents=True)
    (raw / "script-cutoff-2026.txt").write_text(
        '{"format":"long","beats":[' + ",".join(json.dumps(b) for b in recovered) + ',{"id":"b16","narration":"Forty-six sec')
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "scripted"))
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_config"]["effort"] == "low"
    assert call["max_tokens"] == 12000 and "Don't rewrite or repeat them" in call["messages"][0]["content"]
    assert "Forty-six sec" in call["messages"][0]["content"]
    script = artifacts.latest(sr.db, job["id"], "script")
    assert [b["id"] for b in script["beats"]] == [f"b{i:02d}" for i in range(1, 18)]
    assert script["beats"][:15] == [dict(b, est_seconds=28.0) for b in recovered]


def test_qa_that_keeps_failing_blocks_after_three_strikes():
    # Regression: each rewrite used to reset the strikes, so this looped and paid forever.
    replies = [(BRIEF, 0)] + [(SCRIPT, 0), (qa(False), 0)] * 3 + [(SCRIPT, 0), (qa(False), 0)] * 5
    sr, client = live(replies)
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["status"] == "blocked"))
    assert len(client.calls) == 1 + 3 * 2  # research, then exactly three script + QA rounds
    assert "Failed QA 3" in sr.db.get_job(job["id"])["note"]
    assert not sr.inflight


def test_passing_qa_clears_the_strikes():
    sr, client = live([(BRIEF, 0), (SCRIPT, 0), (qa(False), 0), (SCRIPT, 0), (qa(True), 0)])
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "qa_script"))
    assert sr.db.get_job(job["id"])["attempts"] == 0


def previewed(replies):
    """A live job that has a script and is sitting at the preview stage."""
    sr, client = live([(BRIEF, 0), (SCRIPT, 0), *replies], manual_review=True)
    sr.halt_stages = {"qa_video"}
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["stage"] == "scripted"))
    sr.db.update_job(job["id"], stage="qa_video")
    return sr, client, job["id"]


def expand(sr, job_id, done):
    async def go():
        sr.expand_narration(job_id, "b1 says ten more, which misleads")
        await run_until(sr, done)
    asyncio.run(go())


def test_narration_pass_changes_only_narration_and_returns_to_your_review():
    answer = {"beats": [{"id": "b1", "narration": "He beat 78 by 22."}, {"id": "nope", "narration": "Not a beat."}]}
    sr, client, jid = previewed([(answer, 0)])
    expand(sr, jid, lambda: sr.db.get_job(jid)["stage"] == "scripted")
    new = artifacts.latest(sr.db, jid, "script")
    assert new["beats"][0]["narration"] == "He beat 78 by 22."
    assert new["beats"][0]["visual_intent"] == LONG_BEATS[0]["visual_intent"]
    assert new["beats"][1:] == LONG_BEATS[1:] and len(new["beats"]) == len(LONG_BEATS)
    assert new["beats"][0]["est_seconds"] == 2.0  # timing follows the new words
    assert new["target_seconds"] == 2.0 + 28 * 19
    prompt = client.calls[2]["messages"][0]["content"]
    assert "b1 says ten more" in prompt
    assert "web_search" not in json.dumps(client.calls[2].get("tools", []))
    assert "New figures to check: b1: 78, b1: 22." in sr.db.get_job(jid)["note"]
    assert len(client.calls) == 3  # held at your review: nothing else ran


def test_failed_narration_pass_keeps_the_preview_and_does_not_retry():
    broken = {"not": "narration"}
    sr, client, jid = previewed([(broken, 0), (broken, 0)])
    expand(sr, jid, lambda: "Narration pass failed" in (sr.db.get_job(jid)["note"] or ""))
    job = sr.db.get_job(jid)
    assert (job["stage"], job["status"]) == ("qa_video", "active")
    assert len(client.calls) == 3 and artifacts.latest(sr.db, jid, "script")["beats"] == LONG_BEATS


def test_narration_pass_that_matches_no_beats_saves_nothing():
    sr, _, jid = previewed([({"beats": [{"id": "nope", "narration": "Not a beat."}]}, 0)])
    expand(sr, jid, lambda: "Narration pass failed" in (sr.db.get_job(jid)["note"] or ""))
    assert artifacts.latest(sr.db, jid, "script")["beats"] == LONG_BEATS


def test_narration_pass_needs_a_previewed_long_form_job():
    sr, _, jid = previewed([])
    sr.db.update_job(jid, stage="scripted")
    with pytest.raises(ValueError):
        sr.expand_narration(jid, "notes")
    sr.db.update_job(jid, stage="qa_video", format="short")
    with pytest.raises(ValueError):
        sr.expand_narration(jid, "notes")


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    assert cond()


def test_background_actions_start_through_the_real_api():
    """Run on a worker thread, these can't start their task: the request crashes and the agent stays stuck."""
    app = create_app(":memory:", run_loop=False)
    sr = app.state.showrunner
    job = sr.create_job(1, "long")
    sr.db.update_job(job["id"], stage="qa_video")

    async def expand(job, notes):
        return SCRIPT, "Narration rewritten."

    async def finalize(job):
        return {"path": "final.mp4", "width": 1920, "height": 1080}

    sr.agents["script"].expand_narration = expand
    sr.agents["studio"].finalize = finalize
    with TestClient(app) as client:
        assert client.post(f"/api/jobs/{job['id']}/render_final").status_code == 200
        wait_for(lambda: sr.agents["studio"].status == "idle")
        assert "Final video ready" in sr.db.get_job(job["id"])["note"]
        assert client.post(f"/api/jobs/{job['id']}/expand_narration", json={"reason": "Explain the numbers"}).status_code == 200
        wait_for(lambda: sr.db.get_job(job["id"])["stage"] == "scripted")
        assert sr.agents["script"].status == "idle"


PACKAGE = {
    "options": [
        {"angle": "myth_bust", "title": "The famous 100 photo wasn't taken during the game", "layout": "number", "big": "100", "small": "", "headline": "NOT FROM THE GAME"},
        {"angle": "curiosity", "title": "A 51.1% shooter went 28 for 32", "layout": "versus", "big": "87.5%", "small": "", "headline": "HOW?"},
        {"angle": "story", "title": "x " * 60, "layout": "silhouette", "big": "28/32", "small": "", "headline": "ONE MAN ONE WHOLE GAME TOO LONG"},
    ],
    "description": "How one night was built.",
    "chapters": [{"beat_id": "b3", "title": "Setup"}, {"beat_id": "b1", "title": "The number"}, {"beat_id": "b9", "title": "The fouls"},
                 {"beat_id": "b10", "title": "Too close"}, {"beat_id": "nope", "title": "Not a beat"}],
    "tags": ["wilt chamberlain", "100 points"],
    "pinned_comment": "Which number surprises you most?",
}


def packaged_job(replies, monkeypatch, tmp_path):
    monkeypatch.setattr("studio.agents.live.MEDIA_DIR", tmp_path)
    sr, client, jid = previewed(replies)
    sr.halt_stages = {"qa_video", "scheduled"}
    folder = tmp_path / f"job-{jid}"
    folder.mkdir(exist_ok=True)
    timeline = [{"beat_id": f"b{i}", "start": (i - 1) * 28.0, "mode": "bars", "spec": {}} for i in range(1, 21)]
    timeline[9]["start"] = timeline[8]["start"] + 3  # too soon after the last chapter for YouTube
    (folder / "timeline.json").write_text(json.dumps(timeline))
    return sr, client, jid, folder


def test_preview_waits_for_you_before_any_packaging_money(monkeypatch, tmp_path):
    sr, client, jid, _ = packaged_job([], monkeypatch, tmp_path)

    async def idle():
        loop = asyncio.create_task(sr.run())
        await asyncio.sleep(1.2)
        loop.cancel()
    asyncio.run(idle())
    assert len(client.calls) == 2 and sr.db.get_job(jid)["stage"] == "qa_video"


def test_package_is_made_on_request_and_reaches_your_approval(monkeypatch, tmp_path):
    sr, client, jid, folder = packaged_job([(PACKAGE, 0)], monkeypatch, tmp_path)

    async def go():
        sr.make_package(jid)
        await run_until(sr, lambda: sr.db.get_job(jid)["stage"] == "awaiting_approval")
    asyncio.run(go())
    pkg = artifacts.latest(sr.db, jid, "package")
    assert client.calls[2]["model"] == "claude-sonnet-5-5"
    assert [o["thumbnail_path"] for o in pkg["options"]] == ["thumbnail-a.png", "thumbnail-b.png", "thumbnail-c.png"]
    from PIL import Image
    assert Image.open(folder / "thumbnail-b.png").size == (1280, 720)  # versus with no second number still draws
    assert (folder / "thumbnails-phone.png").is_file()
    assert all(len(o["title"]) <= 100 for o in pkg["options"])
    assert "ONE MAN ONE WHOLE with" in pkg["options"][2]["thumbnail_concept"]  # four words at most
    assert pkg["chapters"][0]["t"] == "0:00" and [c["title"] for c in pkg["chapters"]] == ["The number", "Setup", "The fouls"]
    assert "Chapters:\n0:00 The number" in pkg["description"] and "Sources:" in pkg["description"]
    assert (folder / "description.txt").read_text() == pkg["description"]
    assert pkg["ai_disclosure"]["required"] is False
    note = sr.db.get_job(jid)["note"]
    assert "A: 100" in note and "C: 28" in note  # numbers the fake brief doesn't contain get flagged

    sr.approve(jid)
    job = sr.db.get_job(jid)
    assert job["stage"] == "scheduled" and "upload" in job["note"]
    asyncio.run(run_until(sr, lambda: True))
    assert sr.db.get_job(jid)["stage"] == "scheduled"  # nothing tries to publish


def test_package_notes_reach_the_rewrite(monkeypatch, tmp_path):
    sr, client, jid, _ = packaged_job([(PACKAGE, 0), (PACKAGE, 0)], monkeypatch, tmp_path)

    async def go(done):
        sr.make_package(jid)
        await run_until(sr, done)
    asyncio.run(go(lambda: sr.db.get_job(jid)["stage"] == "awaiting_approval"))
    sr.request_changes(jid, "package", "Lead with the free throws")
    assert sr.db.get_job(jid)["stage"] == "qa_video"
    asyncio.run(go(lambda: sr.db.get_job(jid)["stage"] == "awaiting_approval" and len(client.calls) == 4))
    assert "Lead with the free throws" in client.calls[3]["messages"][0]["content"]


def test_failed_package_blocks_without_retrying(monkeypatch, tmp_path):
    broken = {"not": "a package"}
    sr, client, jid, _ = packaged_job([(broken, 0), (broken, 0)], monkeypatch, tmp_path)

    async def go():
        sr.make_package(jid)
        await run_until(sr, lambda: sr.db.get_job(jid)["status"] == "blocked")
    asyncio.run(go())
    assert len(client.calls) == 3 and sr.db.get_job(jid)["stage"] == "qa_video"


def test_chapters_follow_youtubes_rules():
    starts = {"b1": 2.0, "b2": 30.0, "b3": 35.0, "b4": 90.0}
    both = [{"beat_id": b, "title": b} for b in starts]
    assert chapter_list(both, starts) == [{"t": "0:00", "title": "b1"}, {"t": "0:30", "title": "b2"}, {"t": "1:30", "title": "b4"}]
    assert chapter_list(both[:2], starts) == []  # fewer than 3: YouTube ignores them, so don't list any
    assert clock(3725) == "1:02:05"


def test_description_stays_under_youtubes_limit():
    brief = {"facts": [{"source_url": "https://a.example", "source_title": "A"}, {"source_url": "https://a.example", "source_title": "A"}]}
    text = full_description("word " * 2000, [{"t": "0:00", "title": "Start"}], brief, "Photo credits:\n- One\n")
    assert len(text) <= 5000 and text.count("https://a.example") == 1 and text.endswith("- One")


def test_tags_stay_under_youtubes_limit():
    assert sum(len(t) + 1 for t in trim_tags(["long tag " * 5] * 40)) <= 500


def test_package_action_starts_through_the_real_api():
    app = create_app(":memory:", run_loop=False)
    sr = app.state.showrunner
    job = sr.create_job(1, "long")
    sr.db.update_job(job["id"], stage="qa_video")
    agent = sr.agents["packaging"]
    agent._package = object()

    async def run(job, route):
        return Outcome(artifacts={"package": {"options": [{"title": "T", "thumbnail_concept": "C", "thumbnail_path": None}], "description": "D", "chapters": [],
                                              "tags": [], "pinned_comment": "P", "ai_disclosure": {"required": False, "reason": "R"}}})
    agent.run = run
    with TestClient(app) as client:
        assert client.post(f"/api/jobs/{job['id']}/make_package").status_code == 200
        wait_for(lambda: sr.db.get_job(job["id"])["stage"] == "packaged")
        assert client.post(f"/api/jobs/{job['id']}/make_package").status_code == 409  # not at the preview any more


def short_answer(idea, number):
    beat = {"narration": f"He made {number} of them, and nobody expected that at all. " * 2, "on_screen_text": f"{number}", "visual_intent": "A chart",
            "retention_purpose": "payoff", "source_ref": 1}
    return {"idea": idea, "adds": "A number explained.", "beats": [beat, beat, beat, beat]}


SHORTS = {"shorts": [short_answer("The photo", 7), short_answer("Free throws", 28), short_answer("Fouls", 6)]}


def test_three_shorts_reuse_research_and_each_wait_for_your_review():
    sr, client, jid = previewed([(SHORTS, 0)])

    async def go():
        sr.make_shorts(jid)
        await run_until(sr, lambda: sr.db.one("SELECT COUNT(*) AS n FROM jobs WHERE format = 'short'")["n"] == 3 and not sr.inflight)
    asyncio.run(go())
    shorts = sr.db.all("SELECT * FROM jobs WHERE format = 'short' ORDER BY id")
    assert len(client.calls) == 3  # research + long script + one call for all three Shorts
    assert client.calls[2]["model"] == "claude-opus-5-5"
    assert "web_search" not in json.dumps(client.calls[2].get("tools", []))
    assert all(s["stage"] == "scripted" and s["status"] == "active" and s["series"] == "One Moment" for s in shorts)
    assert shorts[0]["title"].endswith(": The photo") and shorts[0]["title"].startswith(sr.db.get_job(jid)["title"])
    assert "New figures to check" in shorts[0]["note"]
    for short in shorts:
        script = artifacts.latest(sr.db, short["id"], "script")
        assert script["format"] == "short" and script["beats"][0]["id"] == "b01" and script["beats"][0]["est_seconds"] > 0
        assert artifacts.latest(sr.db, short["id"], "brief") == BRIEF
    assert sr.db.get_job(jid)["stage"] == "qa_video"  # the long-form doesn't move
    with pytest.raises(ValueError):
        sr.make_shorts(jid)  # never pay for a second set by accident
    for short in shorts:
        sr.reject(short["id"], "Not these")
    assert sr._shorts_of(sr.db.get_job(jid)) == []


def test_failed_shorts_create_nothing_and_do_not_retry():
    broken = {"not": "shorts"}
    sr, client, jid = previewed([(broken, 0), (broken, 0)])

    async def go():
        sr.make_shorts(jid)
        await run_until(sr, lambda: "Writing Shorts failed" in (sr.db.get_job(jid)["note"] or ""))
    asyncio.run(go())
    assert len(client.calls) == 3
    assert sr.db.one("SELECT COUNT(*) AS n FROM jobs WHERE format = 'short'")["n"] == 0


def test_shorts_need_a_previewed_long_form():
    sr, _, jid = previewed([])
    sr.db.update_job(jid, stage="scripted")
    with pytest.raises(ValueError):
        sr.make_shorts(jid)
    sr.db.update_job(jid, stage="scheduled", format="short")
    with pytest.raises(ValueError):
        sr.make_shorts(jid)


def test_shorts_action_starts_through_the_real_api():
    app = create_app(":memory:", run_loop=False)
    sr = app.state.showrunner
    job = sr.create_job(1, "long")
    sr.db.update_job(job["id"], stage="scheduled")
    artifacts.save(sr.db, job["id"], "brief", BRIEF, "research")
    made = {**SCRIPT, "format": "short"}

    async def write(job):
        return [{"idea": "One", "script": made, "note": "N"}]
    sr.agents["script"].write_shorts = write
    with TestClient(app) as client:
        assert client.post(f"/api/jobs/{job['id']}/make_shorts").status_code == 200
        wait_for(lambda: sr.db.one("SELECT COUNT(*) AS n FROM jobs WHERE format = 'short'")["n"] == 1 and sr.agents["script"].status == "idle")
        assert client.post(f"/api/jobs/{job['id']}/make_shorts").status_code == 409


def test_a_short_gets_one_package_with_no_thumbnail_or_chapters(monkeypatch, tmp_path):
    sr, client, jid, folder = packaged_job([(PACKAGE, 0)], monkeypatch, tmp_path)
    sr.db.update_job(jid, format="short")

    async def go():
        sr.make_package(jid)
        await run_until(sr, lambda: sr.db.get_job(jid)["stage"] == "awaiting_approval")
    asyncio.run(go())
    pkg = artifacts.latest(sr.db, jid, "package")
    assert len(pkg["options"]) == 1 and pkg["options"][0]["thumbnail_path"] is None
    assert pkg["chapters"] == [] and "Chapters:" not in pkg["description"]
    assert not (folder / "thumbnail-a.png").exists()


def test_research_must_choose_a_look_and_differ_from_the_last_video():
    no_look = {k: v for k, v in BRIEF.items() if k not in ("look", "pronunciations")}
    sr, client = live([(BRIEF, 0), (SCRIPT, 0), (BRIEF, 0)], manual_review=True)
    first = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(first["id"])["stage"] == "scripted"))
    assert "previous video used a dark background, plain texture and condensed font" in client.calls[0]["messages"][0]["content"]
    assert "look" in client.calls[0]["output_config"]["format"]["schema"]["required"]
    second = sr.create_job(2, "long")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(second["id"])["stage"] == "researched" or len(client.calls) >= 3))
    assert "previous video used a dark background, plain texture and din font" in client.calls[2]["messages"][0]["content"]
    artifacts.validate("brief", no_look)  # briefs from before this change stay valid


def test_redo_research_goes_deeper_and_carries_the_notes_to_the_script():
    sr, client, jid = previewed([(BRIEF, 0), (SCRIPT, 0)])
    sr.redo_research(jid, "Find monthly home run totals. Fix the Gehrig claim.")
    assert sr.db.get_job(jid)["stage"] == "idea"
    asyncio.run(run_until(sr, lambda: sr.db.get_job(jid)["stage"] == "scripted"))
    research, script = client.calls[2], client.calls[3]
    assert "Find monthly home run totals" in research["messages"][0]["content"]
    assert "Earlier facts and look" in research["messages"][0]["content"]
    assert [t["max_uses"] for t in research["tools"]] == [5, 6]
    assert "Fix the Gehrig claim" in script["messages"][0]["content"] and "Previous script" in script["messages"][0]["content"]
    assert len(client.calls) == 4  # held at your script review
    assert artifacts.latest(sr.db, jid, "script") is not None
    assert sr.redo_research(jid, "again")["stage"] == "idea"  # from your script review too, before anything else is made


def test_slides_can_be_rebuilt_from_the_preview_stage_only():
    sr, _, jid = previewed([])
    sr.halt_stages = {"qa_video", "qa_script"}  # stop before real media production
    sr.redo_slides(jid)
    assert sr.db.get_job(jid)["stage"] == "qa_script"
    with pytest.raises(ValueError):
        sr.redo_slides(jid)


def test_rerecording_goes_back_to_render_only():
    sr, _, jid = previewed([])
    sr.redo_render(jid)
    assert sr.db.get_job(jid)["stage"] == "storyboarded"
    with pytest.raises(ValueError):
        sr.redo_render(jid)


def test_a_blocked_job_can_be_rejected_without_spending():
    sr, client, jid = previewed([])
    calls = len(client.calls)
    sr.block(sr.db.get_job(jid), "Budget reached")
    assert sr.reject(jid, "Replaced by a later job")["status"] == "failed"
    assert len(client.calls) == calls
    with pytest.raises(ValueError):
        sr.reject(jid, "again")


def test_research_can_be_redone_from_script_review():
    sr, _ = live([(BRIEF, 0)], manual_review=True)
    sr.agents["research"]._brief = lambda *a: None  # live-mode marker; nothing runs in this test
    jid = sr.create_job(1, "long")["id"]
    sr.db.update_job(jid, stage="scripted", status="active")
    assert sr.redo_research(jid, "Use more sources.")["stage"] == "idea"
