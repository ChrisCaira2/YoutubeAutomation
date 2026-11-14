"""Milestone 1 of the GTA clipper: ingest and transcription, on the sample stream in tests/fixtures."""
import base64
import json
import re
import stat
import subprocess
from pathlib import Path

import pytest

from clipper import detect, edit, facecam, ingest, judge, settings, signals, sweep, transcribe
from clipper.db import DB

SAMPLE = Path(__file__).parent / "fixtures" / "sample-stream.mp4"


@pytest.fixture
def cfg(tmp_path):
    return settings.load(paths={"database": str(tmp_path / "clips.db"), "media": str(tmp_path / "media"), "log": str(tmp_path / "clips.log")},
                         ingest={"segment_seconds": 8, "live_poll_seconds": 0.2})


@pytest.fixture
def db(cfg):
    return DB(cfg["paths"]["database"])


def test_links_are_recognised_by_platform():
    assert ingest.platform_of("https://www.twitch.tv/videos/123") == "twitch"
    assert ingest.platform_of("twitch.tv/somestreamer") == "twitch"
    assert ingest.platform_of("https://youtu.be/abc") == ingest.platform_of("https://m.youtube.com/watch?v=abc") == "youtube"
    assert ingest.platform_of("https://kick.com/someone") == "kick"
    assert ingest.platform_of(str(SAMPLE)) == "file"
    with pytest.raises(ValueError):
        ingest.platform_of("https://notyoutube.com/watch")


def test_times_are_read_as_typed_or_from_a_link():
    assert ingest.seconds("02h31m57s") == ingest.seconds("2:31:57") == 9117 and ingest.seconds("30m") == 1800 and ingest.seconds("45") == 45
    assert ingest.link_start("https://www.twitch.tv/videos/2926082452?t=02h31m57s") == 9117 and ingest.link_start("https://youtu.be/x") is None
    with pytest.raises(ValueError):
        ingest.seconds("soon")


def test_part_of_a_vod_is_its_own_source_pointing_back_into_the_vod(cfg, db, monkeypatch):
    monkeypatch.setattr(ingest, "probe", lambda url, platform=None: {"id": "v1", "title": "GTA 6", "live": False, "creator": "Jynxzi",
                                                                      "channel_url": "https://www.twitch.tv/jynxzi", "page": "https://www.twitch.tv/videos/1", "duration": 21119})
    monkeypatch.setattr(ingest, "download", lambda cfg, db, source, log=None: source)
    part = ingest.ingest(cfg, db, "https://www.twitch.tv/videos/1?t=02h31m57s", length=1800)
    assert (part["key"], part["window_start"], part["window_end"]) == ("twitch:v1@9117-10917", 9117, 10917)
    assert ingest.ingest(cfg, db, "https://www.twitch.tv/videos/1")["key"] == "twitch:v1"  # the whole VOD is a different source
    assert db.one("SELECT COUNT(*) AS n FROM creators")["n"] == 1  # both from the one creator, by channel link


def test_a_short_last_piece_joins_the_one_before():
    assert ingest.pieces(17.5, 8) == [(0, 8), (8, 9.5)]
    assert ingest.pieces(21.7, 8) == [(0, 8), (8, 8), (16, pytest.approx(5.7))]
    assert ingest.pieces(5, 8) == [(0, 5)]


def test_a_local_file_is_added_once_and_transcribed_with_word_times(cfg, db):
    source = ingest.ingest(cfg, db, str(SAMPLE), "Test streamer")
    assert source["kind"] == "file" and source["status"] == "ready" and len(db.segments(source["id"])) == 3
    assert ingest.ingest(cfg, db, str(SAMPLE))["id"] == source["id"]  # the same file again is the same source
    assert transcribe.run(cfg, db) == 3 and transcribe.run(cfg, db) == 0  # finished pieces are never redone
    words = transcribe.transcript(db, source["id"])
    said = " ".join(w["word"] for w in words).lower()
    assert all(w in said for w in ("pier", "boat", "insane", "cops"))
    assert all(a["start"] <= b["start"] for a, b in zip(words, words[1:])) and words[-1]["end"] <= source["duration"] + 0.5
    second = db.segments(source["id"])[1]
    assert all(w["start"] >= second["start"] - 0.5 for w in json.loads(Path(second["words_path"]).read_text()))  # times are into the whole source


def test_a_live_stream_is_cut_into_pieces_while_it_records(cfg, db, tmp_path, monkeypatch):
    """A stand-in for streamlink plays the sample as a live feed, so the test needs no network."""
    fake = tmp_path / "bin" / "streamlink"
    fake.parent.mkdir()
    fake.write_text(f"#!/bin/sh\nexec ffmpeg -v error -i '{SAMPLE}' -c copy -f mpegts -\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(ingest, "BIN", fake.parent)
    who = db.creator("Kick streamer", "kick", "https://kick.com/someone")
    source = db.add_source(key="kick:live1", creator_id=who["id"], platform="kick", kind="live", url="https://kick.com/someone", title="GTA 6 day one", status="recording")
    done = ingest.record(cfg, db, source)
    pieces = db.segments(source["id"])
    assert done["status"] == "ready" and done["chat"] == "unavailable" and len(pieces) >= 2  # Kick has no chat source
    assert pieces[0]["start"] == 0 and all(round(a["start"] + a["duration"], 2) == round(b["start"], 2) for a, b in zip(pieces, pieces[1:]))
    assert abs(done["duration"] - ingest.ffprobe_duration(SAMPLE)) < 0.5
    assert ingest.register_finished(db, source, sorted(Path(pieces[0]["path"]).parent.glob("seg*.mkv")), include_last=True) == 0  # nothing twice
    assert transcribe.run(cfg, db, source["id"]) == len(pieces)
    assert "boat" in " ".join(w["word"] for w in transcribe.transcript(db, source["id"])).lower()


def test_an_unfinished_live_piece_waits_for_the_next(cfg, db, tmp_path):
    out = tmp_path / "live"
    out.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(SAMPLE), "-c", "copy", "-f", "segment", "-segment_time", "8", "-reset_timestamps", "1", str(out / "seg%05d.ts")], check=True)
    source = db.add_source(key="twitch:1", platform="twitch", kind="live", url="https://twitch.tv/x", status="recording")
    files = sorted(out.glob("seg*.ts"))
    assert ingest.register_finished(db, source, files, include_last=False) == len(files) - 1
    assert ingest.register_finished(db, source, files, include_last=True) == 1


def test_a_watched_creator_is_recorded_only_with_gta_in_the_title(cfg, db, monkeypatch):
    who = db.creator("streamer", "twitch", "https://twitch.tv/streamer")
    db.set_creator(who["id"], watch=1)
    started = []
    monkeypatch.setattr(ingest.subprocess, "Popen", lambda args, **kw: started.append(args) or type("P", (), {"poll": lambda self: None})())
    monkeypatch.setattr(ingest, "probe", lambda url: {"live": True, "title": "Just Chatting"})
    ingest.watch(cfg, db, rounds=1)
    monkeypatch.setattr(ingest, "probe", lambda url: {"live": True, "title": "GTA 6 DAY ONE!!"})
    ingest.watch(cfg, db, rounds=1)
    assert len(started) == 1 and started[0][-1] == "https://twitch.tv/streamer"


def test_twitch_vods_go_without_chat_but_live_twitch_chat_is_kept(cfg, db, monkeypatch):
    calls = []
    fake = type("CD", (), {"get_chat": lambda self, url, **kw: calls.append(kw) or iter([{"message": "KEKW", "timestamp": 2_000_000, "author": {"name": "a"}}])})
    monkeypatch.setattr("chat_downloader.ChatDownloader", fake)
    vod = db.add_source(key="twitch:v9", platform="twitch", kind="vod", url="https://www.twitch.tv/videos/9", status="ready")
    assert ingest.fetch_chat(cfg, db.path, vod) == 0 and db.source(vod["id"])["chat"] == "unavailable" and not calls
    live = db.add_source(key="twitch:l9", platform="twitch", kind="live", url="https://www.twitch.tv/x", status="recording")
    assert ingest.fetch_chat(cfg, db.path, live, live_start=1.0) == 1 and calls[0]["interruptible_retry"] is False
    assert db.one("SELECT t FROM chat WHERE source_id = ?", (live["id"],))["t"] == 1.0  # seconds after recording began


def _transcribed_sample(cfg, db):
    source = ingest.ingest(cfg, db, str(SAMPLE), "Test streamer")
    transcribe.run(cfg, db)
    return source


def test_the_shouted_moment_is_the_one_found(cfg, db):
    source = _transcribed_sample(cfg, db)
    assert detect.run(cfg, db, source["id"]) == 1 and detect.run(cfg, db, source["id"]) == 0  # nothing found twice
    moment = db.candidates(source["id"])[0]
    said = [w for w in transcribe.transcript(db, source["id"]) if w["word"].lower().startswith(("way", "landed", "insane"))]
    assert said[0]["start"] - 4 <= moment["peak"] <= said[-1]["end"] + 2  # "No way! It actually landed on the boat! That's insane!"
    assert {"loudness", "voice"} <= set(json.loads(moment["signals"]))


def test_chat_and_emotes_count_a_little_before_they_were_typed(cfg, db):
    source = db.add_source(key="youtube:c", platform="youtube", kind="vod", url="https://youtu.be/c", status="ready")
    db.add_chat(source["id"], [(30.0 + i * 0.1, "a", "KEKW KEKW") for i in range(40)])
    signals_, _ = signals.raw(cfg, db, source["id"]) if db.segments(source["id"]) else ({}, 0)
    assert signals_ == {}  # nothing measured yet: no timeline to place chat on
    db.add_segment(source["id"], 0, SAMPLE, 0, 0, 60)
    np = pytest.importorskip("numpy")
    path = signals._features_path(cfg, db.segments(source["id"])[0])
    path.parent.mkdir(parents=True)
    np.savez_compressed(path, start=0, loudness=np.full(120, -30.0), voice=np.zeros(120), scene=np.zeros(121))
    raw, covered = signals.raw(cfg, db, source["id"])
    b, lag = cfg["detect"]["bin_seconds"], cfg["detect"]["chat_lag_seconds"]
    busiest = int(raw["chat"].argmax()) * b
    assert covered == 60 and 30 - lag <= busiest <= 34 - lag and raw["emotes"].sum() == 80


class FakeClaude:
    """Answers like the API does, without calling it."""

    def __init__(self, verdict):
        self.verdict, self.prompts = verdict, []
        self.messages = self

    def create(self, **kw):
        kw["text"] = "\n".join(b["text"] for b in kw["messages"][0]["content"] if b["type"] == "text")
        self.prompts.append(kw)
        ids = [int(x) for x in re.findall(r"## Moment (\d+)", kw["text"])]
        text = json.dumps({"moments": [{**self.verdict, "id": i} for i in ids]})
        usage = type("U", (), {"input_tokens": 3000, "output_tokens": 600})()
        return type("R", (), {"model": "claude-sonnet-5-5", "usage": usage, "content": [type("B", (), {"type": "text", "text": text})()]})()


VERDICT = {"keep": True, "hook": 8, "standalone": 7, "payoff": 9, "start": 3.0, "end": 30.0, "moment": "reaction",
           "title": "He jumped a car off the pier and landed it", "caption": "Pier jump of the year", "hashtags": ["#GTA6", "gta6clips"], "reason": "Clear setup and a loud payoff."}


def test_claude_picks_are_cut_on_words_ranked_and_charged(cfg, db):
    source = _transcribed_sample(cfg, db)
    detect.run(cfg, db, source["id"])
    fake = FakeClaude(VERDICT)
    assert judge.run(cfg, db, source["id"], client=fake) == 1
    clip = db.candidates(source["id"], "judged")[0]
    words = transcribe.transcript(db, source["id"])
    starts, ends = {round(w["start"] - cfg["clips"]["lead_seconds"], 2) for w in words}, {round(w["end"] + cfg["clips"]["tail_seconds"], 2) for w in words}
    assert clip["start"] in starts | {0.0} and clip["end"] in ends and cfg["clips"]["min_seconds"] <= clip["end"] - clip["start"] <= cfg["clips"]["max_seconds"]
    assert json.loads(clip["hashtags"]) == ["#GTA6", "#gta6clips"] and clip["score"] > 0
    assert "Test streamer" in fake.prompts[0]["text"] and "GTA 6 Clip Central" in fake.prompts[0]["system"]
    images = [b for b in fake.prompts[0]["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == cfg["judge"]["frames"] and base64.b64decode(images[0]["source"]["data"])[:2] == b"\xff\xd8"  # real JPEGs from the stream
    assert db.spent_this_month() == pytest.approx(3000 * 2 / 1e6 + 600 * 10 / 1e6)
    assert judge.run(cfg, db, source["id"], client=fake) == 0 and len(fake.prompts) == 1  # judged once, paid once
    assert json.loads((cfg["paths"]["media"] / "sources" / f"{source['id']:05}" / "candidates.json").read_text())[0]["title"] == VERDICT["title"]


def test_judging_stops_before_the_monthly_cap(cfg, db):
    source = _transcribed_sample(cfg, db)
    detect.run(cfg, db, source["id"])
    db.add_spend("judge", None, "claude-sonnet-5-5", 0, 0, cfg["budget"]["monthly_usd"] - 0.001)
    fake = FakeClaude(VERDICT)
    with pytest.raises(judge.BudgetExceeded):
        judge.run(cfg, db, source["id"], client=fake)
    assert not fake.prompts and db.candidates(source["id"])[0]["status"] == "found"


def test_frames_come_from_the_right_live_piece_and_count_toward_the_reserve(cfg, db, tmp_path):
    out = tmp_path / "live"
    out.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(SAMPLE), "-c", "copy", "-f", "segment", "-segment_time", "8", "-segment_format", "matroska",
                    "-reset_timestamps", "1", str(out / "seg%05d.mkv")], check=True)
    source = db.add_source(key="twitch:f", platform="twitch", kind="live", url="https://twitch.tv/x", status="ready")
    ingest.register_finished(db, source, sorted(out.glob("seg*.mkv")), include_last=True)
    last = db.segments(source["id"])[-1]
    assert judge.frame(db, source["id"], last["start"] + 1, 256)[:2] == b"\xff\xd8"
    assert judge.frame(db, source["id"], 999, 256) is None  # past the end: no frame, no error
    assert judge.reserve(cfg, "x" * 300, images=24) > judge.reserve(cfg, "x" * 300)


def test_cuts_finish_the_sentence_and_respect_clip_lengths(cfg):
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(("go " * 200).split())]
    words[39]["word"] = "now."
    # starts on the word just ending as the cut begins, and runs on to the sentence end at 19.9 s
    assert judge.snap(cfg, words, 2.1, 19.0, (0, 100)) == (1.5 - 0.15, round(words[39]["end"] + 0.4, 2))
    # Job 4's first pick ended "…my aim bro. Can": a sentence that can't be finished is left out
    talk = [{"word": w, "start": 10 + i * 0.5, "end": 10.4 + i * 0.5} for i, w in enumerate(("oh my god " * 10 + "my aim bro. Can you believe that I missed him like that, honestly").split())]
    start, end = judge.snap(cfg, talk, 10, 26, (0, 100))
    bro = next(w for w in talk if w["word"] == "bro.")
    assert end == round(bro["end"] + cfg["clips"]["tail_seconds"], 2)
    start, end = judge.snap(cfg, words, 10, 12, (0, 100))
    assert end - start >= cfg["clips"]["min_seconds"]
    start, end = judge.snap(cfg, words, 0, 95, (0, 100))
    assert end - start <= cfg["clips"]["max_seconds"]


def test_the_hub_wing_shows_the_pipeline_and_starts_with_automation_off(cfg, db, monkeypatch):
    from fastapi.testclient import TestClient
    from clipper import api
    source = _transcribed_sample(cfg, db)
    detect.run(cfg, db, source["id"])
    judge.run(cfg, db, source["id"], client=FakeClaude(VERDICT))
    started = []
    monkeypatch.setattr(api, "available_bytes", lambda: 139_000_000_000)  # Finder's figure, without asking Finder
    monkeypatch.setattr(api.subprocess, "Popen", lambda args, **kw: started.append(args) or type("P", (), {"poll": lambda self: None})())
    with TestClient(api.create_app(cfg, run_worker=False)) as client:
        state = client.get("/api/state").json()
        assert state["disk"]["available_gb"] == 139.0 and state["disk"]["free_gb"] <= state["disk"]["available_gb"] + 1
        assert state["clipper"] and state["channel"] == "GTA 6 Clip Central" and not state["automation"]
        assert [w["label"] for w in state["workspaces"]] == ["The Athletics Archive", "Game Day Brain", "GTA 6 Clip Central"]
        stages = {s["id"]: s for s in state["stages"]}
        assert stages["kept"]["count"] == 1 and stages["posted"]["milestone"] == 5
        assert state["moments"][0]["title"] == VERDICT["title"] and state["moments"][0]["permitted"] is False
        assert client.post("/api/clips/automation", json={"on": True}).json()["automation"]
        assert client.post("/api/clips/record", json={"url": "https://www.twitch.tv/kaicenat"}).json()["recording"] == ["twitch.tv/kaicenat"]
        assert client.post("/api/clips/record", json={"url": "https://www.twitch.tv/kaicenat"}).status_code == 409  # not twice
        assert client.post("/api/clips/record", json={"url": "https://example.com"}).status_code == 409
        assert started == [[api.sys.executable, "-m", "clipper", "ingest", "https://www.twitch.tv/kaicenat", "--follow"]]  # clipped as it records


SAMPLE_CAM = [0.725, 0.044, 0.975, 0.378]  # the fixture's camera box: 160x120 at the top right of 640x360, 16 px in


class FakeCam:
    """Answers the facecam question like the API, a little off, so snapping has work to do."""

    def __init__(self, box, overlay="webcam"):
        self.box, self.calls, self.overlay = box, 0, overlay
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        l, t, r, b = self.box
        text = json.dumps({"facecam": bool(self.box), "overlay": self.overlay, "left": l, "top": t, "right": r, "bottom": b, "note": "camera top right"})
        usage = type("U", (), {"input_tokens": 3000, "output_tokens": 60})()
        return type("R", (), {"model": "claude-sonnet-5-5", "usage": usage, "content": [type("B", (), {"type": "text", "text": text})()]})()


def test_the_facecam_box_snaps_onto_the_cameras_border(cfg, db):
    source = ingest.ingest(cfg, db, str(SAMPLE), "Test streamer")
    rough = [SAMPLE_CAM[0] + 0.02, SAMPLE_CAM[1] + 0.03, SAMPLE_CAM[2] - 0.015, SAMPLE_CAM[3] + 0.025]
    fake = FakeCam(rough)
    found = facecam.find(cfg, db, source["id"], client=fake)
    assert all(abs(a - b) < 0.012 for a, b in zip(found["box"], SAMPLE_CAM)), found
    assert facecam.find(cfg, db, source["id"], client=fake) == found and fake.calls == 1  # once per source
    assert db.spent_this_month() > 0
    db.set_source(source["id"], facecam=None)
    assert facecam.find(cfg, db, source["id"], client=FakeCam(rough, "avatar"))["box"] == rough  # an avatar keeps Claude's box: no border to snap to


def _frame_at(path, t):
    from PIL import Image
    import io
    shot = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"], capture_output=True).stdout
    return Image.open(io.BytesIO(shot)).convert("RGB")


@pytest.mark.parametrize("cam", [SAMPLE_CAM, None])
def test_a_pick_becomes_a_vertical_clip_with_captions_at_target_loudness(cfg, db, monkeypatch, cam):
    source = _transcribed_sample(cfg, db)
    db.set_source(source["id"], facecam=json.dumps({"box": cam, "by": "test"}))
    detect.run(cfg, db, source["id"])
    judge.run(cfg, db, source["id"], client=FakeClaude(VERDICT))
    pick = db.candidates(source["id"], "judged")[0]
    clip = edit.edit(cfg, db, pick["id"])
    assert edit.edit(cfg, db, pick["id"])["id"] == clip["id"]  # made once
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height:format=duration", "-of", "json", clip["path"]],
                                      capture_output=True, text=True).stdout)
    assert (probe["streams"][0]["width"], probe["streams"][0]["height"]) == (1080, 1920) and abs(float(probe["format"]["duration"]) - clip["duration"]) < 0.3
    assert clip["layout"] == ("stack" if cam else "blur") and abs(clip["lufs"] - cfg["edit"]["lufs"]) < 1.0
    said = next(w for w in transcribe.transcript(db, source["id"]) if pick["start"] + 1 < w["start"] < pick["end"] - 1)
    frame = _frame_at(clip["path"], (said["start"] + said["end"]) / 2 - pick["start"])
    band = frame.crop((0, int(1920 * cfg["captions"]["y"]) - 60, 1080, int(1920 * cfg["captions"]["y"]) + 40)).getdata()
    assert sum(1 for p in band if p[0] > 230 and p[1] > 190 and p[2] < 80) > 200  # the spoken word in yellow
    assert Path(clip["poster"]).exists()


def test_captions_star_out_swearing_but_keep_punctuation():
    hidden = {"fucking", "shit"}
    assert edit.censor("fucking", hidden) == "f*****g" and edit.censor("Shit!", hidden) == "S**t!" and edit.censor("aim", hidden) == "aim"


def test_a_fully_clipped_source_goes_to_the_trash_a_week_later(cfg, db, tmp_path):
    from datetime import datetime, timedelta, timezone
    video = tmp_path / "source.mp4"
    video.write_bytes(b"x")
    vod = db.add_source(key="twitch:v1", platform="twitch", kind="vod", url="https://twitch.tv/videos/1", status="ready", path=str(video))
    db.add_segment(vod["id"], 0, video, 0, 0, 60)
    mine = ingest.ingest(cfg, db, str(SAMPLE))  # your own file: never touched
    db.run("INSERT INTO candidates (source_id, peak, signal, signals, status, created_at) VALUES (?, 10, 1, '{}', 'found', ?)", (vod["id"], "2026-01-01"))
    trash = tmp_path / "Trash"
    trash.mkdir()
    later = datetime.now(timezone.utc) + timedelta(days=cfg["ingest"]["source_trash_days"] + 1)
    assert sweep.run(cfg, db, trash=trash, at=later) == 0  # a moment is still waiting to be judged
    db.run("UPDATE candidates SET status = 'dropped'")
    assert sweep.run(cfg, db, trash=trash, at=datetime.now(timezone.utc)) == 0  # not a week yet
    assert sweep.run(cfg, db, trash=trash, at=later) == 1 and not video.exists() and len(list(trash.iterdir())) == 1
    assert db.source(vod["id"])["trashed_at"] and not db.source(mine["id"])["trashed_at"] and SAMPLE.exists()


def test_you_review_trim_and_fix_clips_from_the_hub(cfg, db):
    from fastapi.testclient import TestClient
    from clipper import api
    source = _transcribed_sample(cfg, db)
    db.set_source(source["id"], facecam=json.dumps({"box": None, "by": "test"}))
    detect.run(cfg, db, source["id"])
    judge.run(cfg, db, source["id"], client=FakeClaude(VERDICT))
    clip = edit.edit(cfg, db, db.candidates(source["id"], "judged")[0]["id"])
    with TestClient(api.create_app(cfg, run_worker=False)) as client:
        stages = lambda s: {x["id"]: x["count"] for x in s["stages"]}  # noqa: E731
        state = client.get("/api/state").json()
        assert stages(state)["waiting"] == 1 and state["moments"][0]["clip"]["status"] == "edited"
        state = client.post(f"/api/clips/{clip['id']}/review", json={"decision": "approved"}).json()
        assert stages(state)["approved"] == 1 and stages(state)["waiting"] == 0
        assert client.post(f"/api/clips/{clip['id']}/review", json={"decision": "posted"}).status_code == 409
        client.post(f"/api/clips/{clip['id']}/review", json={"decision": "edited"})

        before = db.one("SELECT * FROM candidates WHERE id = ?", (clip["candidate_id"],))
        state = client.post(f"/api/clips/{clip['id']}/trim", json={"end_by": -1}).json()
        after = db.one("SELECT * FROM candidates WHERE id = ?", (clip["candidate_id"],))
        remade = db.one("SELECT * FROM clips WHERE id = ?", (clip["id"],))  # the same clip, made again
        assert after["end"] < before["end"] and abs(remade["duration"] - (after["end"] - after["start"])) < 0.05 and remade["status"] == "edited"
        assert client.post(f"/api/clips/{clip['id']}/trim", json={"end_by": -30}).status_code == 409  # shorter than a clip can be

        assert client.get(f"/api/sources/{source['id']}/frame").content[:2] == b"\xff\xd8"
        assert client.post(f"/api/sources/{source['id']}/facecam", json={"box": [0.9, 0.1, 0.5, 0.4]}).status_code == 409
        client.post(f"/api/sources/{source['id']}/facecam", json={"box": SAMPLE_CAM})
        assert db.one("SELECT layout FROM clips WHERE id = ?", (clip["id"],))["layout"] == "stack"
        assert client.get(f"/api/sources/{source['id']}/facecam").json()["by"] == "you"

        who = db.source(source["id"])["creator_id"]
        state = client.post(f"/api/creators/{who}", json={"permission": "permitted", "watch": True}).json()
        assert db.one("SELECT permission, watch FROM creators WHERE id = ?", (who,)) == {"permission": "permitted", "watch": 1}
        assert state["moments"][0]["permitted"] is True
        assert client.post(f"/api/creators/{who}", json={"permission": "maybe"}).status_code == 409


def test_a_recording_is_clipped_while_it_is_still_going(cfg, db, monkeypatch):
    """The live path end to end: pieces arrive, and each is transcribed, searched, judged and edited before the stream ends."""
    from clipper.__main__ import follow
    source = db.add_source(key="twitch:live", platform="twitch", kind="live", url="https://twitch.tv/x", status="recording", title="Not GTA")
    db.add_segment(source["id"], 0, SAMPLE, 0, 0, ingest.ffprobe_duration(SAMPLE))
    db.set_source(source["id"], facecam=json.dumps({"box": None, "by": "test"}))
    assert db.length(source["id"]) == pytest.approx(21.7, abs=0.1)  # no duration yet: what's been recorded counts
    fake = FakeClaude(VERDICT)
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake)
    monkeypatch.setattr("clipper.__main__.time.sleep", lambda s: db.set_source(source["id"], status="ready", duration=db.length(source["id"])))  # the stream ends
    cfg["judge"]["require_gta"] = False
    assert follow(cfg, db, source["id"], None) == 1
    assert "whatever the game" in fake.prompts[0]["system"] and db.one("SELECT COUNT(*) AS n FROM clips")["n"] == 1


def test_any_recording_shows_as_live_in_the_hub_and_stop_ends_it(cfg, db, tmp_path, monkeypatch):
    """A stand-in streamlink plays the sample in real time; Stop in the hub ends the recording early and keeps what's recorded."""
    import threading
    import time
    from fastapi.testclient import TestClient
    from clipper import api
    fake = tmp_path / "bin" / "streamlink"
    fake.parent.mkdir()
    fake.write_text(f"#!/bin/sh\nexec ffmpeg -v error -re -i '{SAMPLE}' -c copy -f mpegts -\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(ingest, "BIN", fake.parent)
    cfg["ingest"]["segment_seconds"] = 4
    who = db.creator("Kick streamer", "kick", "https://kick.com/someone")
    source = db.add_source(key="kick:stop", creator_id=who["id"], platform="kick", kind="live", url="https://kick.com/someone", title="Live", status="recording")
    recorder = threading.Thread(target=ingest.record, args=(cfg, DB(cfg["paths"]["database"]), source))
    began = time.time()
    recorder.start()
    with TestClient(api.create_app(cfg, run_worker=False)) as client:
        for _ in range(50):  # the recorder checks in within a moment
            state = client.get("/api/state").json()
            if state["recordings"]:
                break
            time.sleep(0.2)
        assert state["recordings"][0]["creator"] == "Kick streamer" and state["creators"][0]["recording"]
        time.sleep(5)
        assert client.post(f"/api/sources/{source['id']}/stop").json()["recordings"][0]["stopping"]
        recorder.join(30)
        assert not recorder.is_alive() and time.time() - began < 15  # well before the 22 s sample ran out
        done = db.source(source["id"])
        assert done["status"] == "ready" and done["stop_requested"] == 0 and done["duration"] > 3 and db.segments(source["id"])
        assert client.get("/api/state").json()["recordings"] == []
        assert client.post(f"/api/sources/{source['id']}/stop").status_code == 409  # nothing left to stop


def test_secrets_stay_out_of_the_config():
    text = (settings.HERE / "config.toml").read_text().lower()
    assert not any(word in text for word in ("api_key", "secret =", "token =", "password"))
