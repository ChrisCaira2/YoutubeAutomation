"""Studio: storyboards, captions and a real short video through the live pipeline. Free."""
import asyncio
import json

import pytest
from test_live import BRIEF, live, run_until

from studio import artifacts
from studio.media import assemble, captions, produce, storyboard, voice
from studio.media.voice import MODEL_DIR

SENTENCES = [
    "Wilt Chamberlain scored one hundred points in a single game.",
    "Nobody has come close to that mark in more than sixty years.",
    "He made twenty eight of thirty two free throws that night.",
    "Even he usually missed about half of them, which makes it stranger.",
]
SHORT = {
    "format": "short", "target_seconds": 18, "originality_statement": "Adds the free-throw math",
    "self_check": [{"rule": "Hook", "passed": True, "note": ""}],
    "beats": [
        {"id": f"b{i}", "narration": s, "on_screen_text": "100 points", "visual_intent": "Scoreboard showing 100",
         "retention_purpose": "hook" if i == 1 else "context", "source_ref": 1, "est_seconds": 4.5}
        for i, s in enumerate(SENTENCES, 1)
    ],
}
VARIED_SLIDES = {"slides": [
    {"id": f"s{i:03}", "layout": "big_stat" if i % 2 else "statement", "headline": "A single clear point", "value": "100", "label": "points in one game",
     "kicker": "", "emphasis": "", "context": "", "body": "", "points": None, "reference_value": None, "reference_label": "", "items": None, "highlight": None, "target": None, "quote": "", "attribution": "", "number": None,
     "calculated": False, "bug": None, "surface": "", "moves": None, "actors": None, "formation": None}
    for i in range(1, 30)
]}
needs_voice = pytest.mark.skipif(not (MODEL_DIR / "kokoro-v1.0.onnx").exists(), reason="Kokoro model not downloaded")


def beat(narration="He scored 100.", intent="Scoreboard", text="100"):
    return {"id": "b1", "narration": narration, "on_screen_text": text, "visual_intent": intent, "est_seconds": 5}


def frames(b, fmt="long", title="Wilt"):
    return storyboard.plan({"format": fmt, "beats": [b]}, title, "style")["frames"]


def test_chart_only_from_a_real_list_of_values():
    assert frames(beat(intent="A bar chart: 23, 18, 28, 31 by quarter"))[0]["mode"] == "chart"
    assert frames(beat(intent="Chart of record: 78 points set in 1962"))[0]["mode"] != "chart"


def test_chart_values_and_quarter_labels():
    spec = frames(beat(narration="Line up the quarters.", intent="The chart completes: 23, 18, 28, 31."))[0]["spec"]
    assert spec["numbers"] == ["23", "18", "28", "31"] and spec["labels"] == ["Q1", "Q2", "Q3", "Q4"]


def test_numbers_keep_their_display_form():
    assert storyboard.numbers_in("Attendance: 4,124, and 51.1 percent.") == ["4,124", "51.1%"]


def test_big_number_comes_from_the_on_screen_text_not_the_visual_note():
    spec = frames(beat(intent="Scoreboard: Q2 18, half 41, pace 100", text="Halftime: 41"))[0]["spec"]
    assert spec["numbers"] == ["41"]


def test_chapter_number_is_not_a_stat():
    spec = frames(beat(intent="Scoreboard at 0:00", text="Chapter 1: The First Half"))[0]["spec"]
    assert spec["numbers"] == [] and spec["headline"].startswith("Chapter 1")
    assert frames(beat(intent="Scoreboard", text="Chapter 3: 31 to go"))[0]["spec"]["numbers"] == ["31"]


def test_dates_and_years_are_never_the_big_number():
    assert frames(beat(intent="Scoreboard", text="March 2, 1962: 100 points"))[0]["spec"]["numbers"] == ["100"]
    assert storyboard.numbers_in("In 1962, he scored 100 on March 2.") == ["100"]


def test_long_sentences_leave_no_stray_fragments():
    sentence = "But twenty assists and sixty three shots from one man tell you exactly where this entire offense pointed."
    fs = frames(beat(narration=sentence + " " + sentence))
    assert all(len(f["spec"]["headline"].split()) >= 4 for f in fs[1:])


def test_slide_text_is_capitalized_without_dangling_commas():
    assert storyboard._pull("the free-throw mystery,") == "The free-throw mystery"


def test_diagrams_draw_no_invented_players(monkeypatch):
    from studio.media import visuals
    drawn = []
    real = visuals.ImageDraw.ImageDraw.polygon
    monkeypatch.setattr(visuals.ImageDraw.ImageDraw, "polygon", lambda self, *a, **k: (drawn.append(k.get("fill")), real(self, *a, **k))[1])
    visuals.diagram((640, 360), {"headline": "Buckner: 33 points", "sport": "basketball"})
    assert visuals.STYLE["red"] not in drawn  # no play arrow


def test_long_narration_is_split_so_no_frame_overstays():
    long_sentence = " ".join(["word"] * 80) + "."
    fs = frames(beat(narration=long_sentence))
    assert len(fs) >= 4 and all(len(f["spec"]["say"].split()) <= 25 for f in fs)


def test_modes_never_repeat_back_to_back():
    fs = storyboard.plan({"format": "long", "beats": [dict(beat(), id=f"b{i}") for i in range(6)]}, "Wilt", "s")["frames"]
    assert all(a["mode"] != b["mode"] for a, b in zip(fs, fs[1:]))


def test_sport_detection():
    assert storyboard.sport_of("Wilt Chamberlain scores 100") == "basketball"
    assert storyboard.sport_of("Babe Ruth hits 60 home runs") == "baseball"
    assert storyboard.sport_of("Isner vs. Mahut") == "generic"


def test_captions_use_script_spelling_when_counts_differ():
    heard = [{"word": w, "start": i, "end": i + 1} for i, w in enumerate(["made", "51", ".1", "%", "of"])]
    words = captions.align(heard, ["made", "51.1", "percent", "of"])
    assert [w["word"] for w in words] == ["made", "51.1", "percent", "of"]
    assert all(a["start"] <= b["start"] for a, b in zip(words, words[1:]))


def test_captions_drop_words_the_script_never_says():
    heard = [{"word": w, "start": i, "end": i + 1} for i, w in enumerate(["he", "uh", "scored"])]
    assert [w["word"] for w in captions.align(heard, ["he", "scored"])] == ["he", "scored"]


def test_srt_format(tmp_path):
    out = tmp_path / "c.srt"
    captions.write_srt([{"word": "Hi.", "start": 1.5, "end": 2.0}], out)
    assert out.read_text().startswith("1\n00:00:01,500 --> 00:00:02,000\nHi.")


@needs_voice
def test_real_short_runs_from_script_review_to_final_video(tmp_path, monkeypatch):
    monkeypatch.setattr("studio.llm.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.agents.studio.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.agents.live.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.media.produce.MUSIC_DIR", tmp_path / "no-music")
    sr, client = live([(BRIEF, 0), (SHORT, 0), (VARIED_SLIDES, 0)], manual_review=True)
    sr.halt_stages = {"qa_video"}
    job = sr.create_job(1, "short")
    jid = job["id"]
    asyncio.run(run_until(sr, lambda: sr.db.get_job(jid)["stage"] == "scripted"))
    sr.approve_script(jid)
    asyncio.run(run_until(sr, lambda: sr.db.get_job(jid)["stage"] == "qa_video" or sr.db.get_job(jid)["status"] != "active", timeout=240))
    state = sr.db.get_job(jid)
    assert (state["stage"], state["status"]) == ("qa_video", "active"), state["note"]
    assert len(client.calls) == 3  # slide design is the only Claude call after the script
    assert client.calls[2]["model"] == "claude-haiku-5-5" and "fallbacks" not in client.calls[2]

    folder = tmp_path / f"job-{jid}"
    preview = assemble.probe(folder / "preview.mp4")
    assert (preview["width"], preview["height"]) == (540, 960) and preview["has_audio"]
    assert (folder / "contact-sheet.png").exists() and (folder / "captions.srt").exists()
    assert abs(assemble.loudness(folder / "preview.mp4") + 14) <= 2
    report = artifacts.latest(sr.db, jid, "qa_report")
    assert report["gate"] == "video" and report["passed"]
    words = json.loads((folder / "words.json").read_text())
    assert len(words) >= 35

    async def finalize():
        sr.render_final(jid)
        await asyncio.gather(*sr.inflight.values())

    asyncio.run(finalize())
    final = artifacts.latest(sr.db, jid, "render")
    assert final["preview"] is False and (final["width"], final["height"]) == (1080, 1920)
    assert (folder / "final.mp4").exists()
    assert sr.agents["studio"].status == "idle"


@needs_voice
def test_video_qa_failure_blocks_once_instead_of_looping(tmp_path, monkeypatch):
    monkeypatch.setattr("studio.llm.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.agents.studio.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.agents.live.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.media.produce.MUSIC_DIR", tmp_path / "no-music")
    # With no slides from Haiku, every frame is the same plain layout: QA-2 fails on variety.
    sr, client = live([(BRIEF, 0), (SHORT, 0), ({"slides": []}, 0)], manual_review=True)
    sr.halt_stages = {"qa_video"}
    jid = sr.create_job(1, "short")["id"]
    asyncio.run(run_until(sr, lambda: sr.db.get_job(jid)["stage"] == "scripted"))
    sr.approve_script(jid)
    asyncio.run(run_until(sr, lambda: sr.db.get_job(jid)["status"] == "blocked", timeout=120))
    job = sr.db.get_job(jid)
    assert "visual modes" in job["note"]
    reports = sr.db.one("SELECT COUNT(*) AS n FROM artifacts WHERE job_id = ? AND kind = 'qa_report' AND created_by = 'qa'", (jid,))["n"]
    assert reports == 1


def test_final_render_refused_before_qa_passes():
    sr, _ = live([])
    job = sr.create_job(1, "short")
    with pytest.raises(ValueError):
        sr.render_final(job["id"])


def _frames(*says):
    return [{"beat_id": "b1", "duration": 5.0, "mode": "bars", "spec": {"say": say}} for say in says]


def test_slides_hold_until_their_words_are_spoken():
    beats = [{"id": "b1", "narration": "One two three. Four five six seven."}]
    words = [{"word": w, "start": i * 1.0, "end": i + 0.9} for i, w in enumerate("One two three. Four five six seven.".split())]
    out = produce._timeline(_frames("One two three.", "Four five six seven."), [(0.0, 7.0)], beats, words)
    assert out[0]["start"] == 0.0 and out[1]["start"] == pytest.approx(2.95)  # planned durations would have cut at 3.5
    assert out[0]["start"] + out[0]["duration"] >= words[2]["end"]
    assert out[1]["start"] + out[1]["duration"] == pytest.approx(7.0)


def test_slide_timing_copes_with_words_whisper_attached_together():
    beats = [{"id": "b1", "narration": "One two three four."}]
    words = [{"word": "One two", "start": 0.0, "end": 1.0}, {"word": "three", "start": 1.5, "end": 2.0}, {"word": "four.", "start": 2.5, "end": 3.0}]
    out = produce._timeline(_frames("One two", "three four."), [(0.0, 3.0)], beats, words)
    assert out[1]["start"] == pytest.approx(1.45)


def test_slide_timing_falls_back_when_the_words_do_not_line_up():
    beats = [{"id": "b1", "narration": "One two three four."}]
    for words in (None, [{"word": "One", "start": 0.0, "end": 1.0}]):
        out = produce._timeline(_frames("One two", "three four."), [(0.0, 4.0)], beats, words)
        assert out[1]["start"] == pytest.approx(2.0)


def test_a_very_short_slide_still_shows():
    beats = [{"id": "b1", "narration": "One two."}]
    words = [{"word": "One", "start": 0.0, "end": 0.1}, {"word": "two.", "start": 0.1, "end": 0.2}]
    out = produce._timeline(_frames("One", "two."), [(0.0, 2.0)], beats, words)
    assert out[0]["duration"] >= produce.MIN_SLIDE_SECONDS


def test_pauses_vary_with_the_story_and_shorts_stay_quick():
    beats = [{"id": "b1"}, {"id": "b2", "retention_purpose": "pattern_interrupt"}, {"id": "b3", "retention_purpose": "payoff"}]
    assert voice.pauses_after(beats, "long") == [voice.RESET_PAUSE, voice.BEAT_PAUSE["long"], voice.BEAT_PAUSE["long"]]
    assert voice.pauses_after(beats, "short") == [voice.BEAT_PAUSE["short"]] * 3


def test_failed_slide_design_stops_the_job_instead_of_going_off_theme(tmp_path, monkeypatch):
    """Two Red Sox Shorts got the old slide style, with no team colors, when slide design ran out of room."""
    from studio.llm import ClaudeFailed

    async def cut_off(*args, **kwargs):
        raise ClaudeFailed("Claude's answer was cut off.")

    monkeypatch.setattr("studio.llm.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.agents.studio.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.agents.live.MEDIA_DIR", tmp_path)
    monkeypatch.setattr("studio.agents.studio.slide_writer.write", cut_off)
    sr, _ = live([(BRIEF, 0), (SHORT, 0)], manual_review=True)
    sr.halt_stages = {"qa_video"}
    jid = sr.create_job(1, "short")["id"]
    asyncio.run(run_until(sr, lambda: sr.db.get_job(jid)["stage"] == "scripted"))
    sr.approve_script(jid)
    asyncio.run(run_until(sr, lambda: sr.db.get_job(jid)["status"] != "active"))
    job = sr.db.get_job(jid)
    assert (job["status"], job["stage"]) == ("blocked", "qa_script") and "cut off" in job["note"]
    assert artifacts.latest(sr.db, jid, "storyboard") is None and sr.agents["studio"].status == "idle"


def test_an_approved_video_can_get_new_slides_and_keep_its_package():
    sr, _ = live([(BRIEF, 0)], manual_review=True)
    jid = sr.create_job(1, "short")["id"]
    sr.db.update_job(jid, stage="scheduled", status="active")
    job = sr.redo_slides(jid)
    assert job["stage"] == "qa_script"  # it goes back through the slide checks and QA-2
    sr.db.update_job(jid, stage="qa_video")
    with pytest.raises(ValueError, match="no title"):
        sr.reuse_package(jid)
    sr.db.run("INSERT INTO artifacts (job_id, kind, version, data, created_by, created_at) VALUES (?, 'package', 1, ?, 'packaging', 'now')", (jid, json.dumps({"options": []})))
    assert sr.reuse_package(jid)["stage"] == "packaged"
    sr.db.update_job(jid, stage="awaiting_approval")
    with pytest.raises(ValueError):
        sr.redo_slides(jid)  # under review, you send it back with Request changes instead
