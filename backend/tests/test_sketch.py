"""The sketch look for AI Slop, modeled on the owner's chosen channel, 2026-11-09."""
from PIL import Image, ImageChops

from studio.agents.live import thumbnail_pictures
from studio.media import assemble, motion, sketch, sketch_writer, thumbnails, visuals

SCRIPT = {"format": "long", "beats": [
    {"id": "b01", "narration": "Your brain doesn't treat a loss the way you think. Stay for number two.", "on_screen_text": "Losses hit harder",
     "visual_intent": "the fan on his couch", "retention_purpose": "hook"},
    {"id": "b02", "narration": "One. You wear the shirt after a win. Robert Cialdini saw students do it in 1976.", "on_screen_text": "1. You wear the shirt after a win",
     "visual_intent": "the fan in a jersey", "retention_purpose": "payoff"},
]}
BRIEF = {"facts": [{"claim": "Cialdini's 1976 study found students wore more school apparel after football wins.", "source_url": "https://example.edu", "source_title": "Study"}]}


def board(seconds: list[float]) -> dict:
    frames = [{"beat_id": "b01", "start": 0, "duration": seconds[0], "mode": "text_card", "prompt": "x", "motion": "still", "spec": {"say": "Your brain doesn't treat a loss the way you think."}},
              {"beat_id": "b01", "start": 0, "duration": seconds[1], "mode": "text_card", "prompt": "x", "motion": "still", "spec": {"say": "Stay for number two."}},
              {"beat_id": "b02", "start": 0, "duration": seconds[2], "mode": "text_card", "prompt": "x", "motion": "still", "spec": {"say": "One. You wear the shirt after a win."}},
              {"beat_id": "b02", "start": 0, "duration": seconds[3], "mode": "text_card", "prompt": "x", "motion": "still", "spec": {"say": "Robert Cialdini saw students do it in 1976."}}]
    return {"style_bible": "Sketch v1", "frames": frames}


SCENE = "the fan sits on a couch in a dim living room, head in his hands, after his team lost"


def test_a_numbered_item_gets_its_title_card_from_the_script_not_from_haiku():
    slides = [{"id": f"s{i:03}", "kind": "picture", "scene": SCENE, "mascot": True, "caption": ""} for i in range(1, 5)]
    merged, rejected = sketch_writer.apply(SCRIPT, BRIEF, board([5, 3, 4, 4]), slides)
    assert [f["mode"] for f in merged["frames"]] == ["picture", "picture", "item", "picture"] and not rejected
    assert merged["frames"][2]["spec"]["headline"] == "1. You wear the shirt after a win"


def test_pictures_never_name_a_real_person_or_show_a_league():
    slides = [{"id": "s001", "kind": "picture", "scene": SCENE, "mascot": True, "caption": ""},
              {"id": "s002", "kind": "picture", "scene": "a crowd at an NFL game cheering under bright lights in the stands", "mascot": False, "caption": ""},
              {"id": "s003", "kind": "picture", "scene": SCENE, "mascot": True, "caption": ""},
              {"id": "s004", "kind": "picture", "scene": "Cialdini in his office counting students in sweatshirts on a campus lawn", "mascot": False, "caption": ""}]
    merged, rejected = sketch_writer.apply(SCRIPT, BRIEF, board([5, 3, 4, 4]), slides)
    assert [r["id"] for r in rejected] == ["s002", "s004"]
    assert all("Cialdini" not in f["spec"]["scene"] and "NFL" not in f["spec"]["scene"] for f in merged["frames"])


def test_dates_and_weekdays_are_not_names():
    script = {**SCRIPT, "beats": SCRIPT["beats"] + [{**SCRIPT["beats"][0], "id": "b03", "narration": "On June 30, fans went to work that Monday wearing the colors."}]}
    names = sketch_writer.names_in(script, BRIEF)
    assert "Cialdini" in names and not {"June", "Monday"} & names
    assert sketch_writer.scene_problem("a calendar on the wall showing June 30 above a tired nurse at a desk", names) is None


def test_a_hold_keeps_the_picture_but_never_runs_long_or_covers_a_title_card():
    slides = [{"id": "s001", "kind": "picture", "scene": SCENE, "mascot": True, "caption": ""},
              {"id": "s002", "kind": "hold", "scene": "", "mascot": False, "caption": ""},
              {"id": "s003", "kind": "hold", "scene": "", "mascot": False, "caption": ""},
              {"id": "s004", "kind": "hold", "scene": "", "mascot": False, "caption": ""}]
    merged, _ = sketch_writer.apply(SCRIPT, BRIEF, board([5, 3, 4, 4]), slides)
    modes = [(f["mode"], f["motion"]) for f in merged["frames"]]
    assert modes[1] == ("picture", motion.HOLD) and modes[2] == ("item", "still") and modes[3] == ("item", motion.HOLD)  # the title card stays up, without bursting again
    long_hold, _ = sketch_writer.apply(SCRIPT, BRIEF, board([5, 9, 4, 4]), slides)
    assert long_hold["frames"][1]["motion"] != motion.HOLD  # 14 s on one picture is too long


def test_captions_are_whole_and_carry_only_the_scripts_numbers():
    ok = {"id": "s001", "kind": "picture", "scene": SCENE, "mascot": True, "caption": "LOSSES HIT HARDER"}
    bad = [{**ok, "caption": "IT HURTS 300 TIMES"}, {**ok, "caption": "BECAUSE OF THE"}, {**ok, "caption": "ONE TWO THREE FOUR FIVE SIX"}]
    beat = SCRIPT["beats"][0]
    assert sketch_writer.caption_ok(ok["caption"], beat, BRIEF)
    assert not any(sketch_writer.caption_ok(b["caption"], beat, BRIEF) for b in bad)


def test_the_same_scene_is_drawn_once_and_the_mascot_is_described_for_the_model(tmp_path):
    frames = [{"beat_id": "b01", "mode": "picture", "spec": {"scene": SCENE, "mascot": True}},
              {"beat_id": "b01", "mode": "picture", "spec": {"scene": SCENE, "mascot": True}},
              {"beat_id": "b02", "mode": "item", "spec": {"scene": "a referee in a plain black shirt blowing a whistle", "mascot": False, "headline": "1. Whistle"}}]
    attached = sketch.attach_pictures({"frames": frames}, tmp_path, "long")
    jobs = sketch.missing(attached)
    assert len(jobs) == 2 and "red hoodie" in jobs[0]["prompt"] and "red hoodie" not in jobs[1]["prompt"]
    assert all("no text" in j["prompt"] for j in jobs)


def test_frames_draw_before_and_after_their_picture_exists(tmp_path):
    spec = {"scene": SCENE, "mascot": True, "headline": "4. You remember the losses longer", "picture": str(tmp_path / "p.png")}
    for size in ((960, 540), (540, 960)):
        assert visuals.RENDERERS["item"](size, spec).size == size  # the stand-in names the scene
    Image.new("RGB", (1024, 576), (200, 160, 120)).save(tmp_path / "p.png")
    drawn = visuals.RENDERERS["picture"]((1920, 1080), {**spec, "caption": "THEY CHOOSE YOU"})
    assert drawn.size == (1920, 1080) and drawn.getpixel((960, 700)) == (200, 160, 120)


def test_a_title_card_bursts_in_behind_balls_and_settles():
    spec = {"scene": SCENE, "headline": "2. You follow the team in a slump"}
    middle, settled = visuals.RENDERERS["item"]((960, 540), {**spec, "t": 0.5}), visuals.RENDERERS["item"]((960, 540), spec)
    assert ImageChops.difference(middle, settled).getbbox()
    assert motion.plan({"frames": [{"mode": "item", "spec": spec}]})["frames"][0]["motion"] == motion.BUILD


def test_word_captions_highlight_each_word_in_turn(tmp_path):
    words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate("Your brain keeps score. Every loss counts twice.".split())]
    listing, y = assemble.word_track(words, (960, 540), tmp_path, 4.0, "long")
    files = [line.split("'")[1] for line in listing.read_text().splitlines() if line.startswith("file")]
    assert y > 400 and len({f for f in files if "cap-" in f}) == len(words)
    first, second = Image.open(tmp_path / "cap-0000-0.png"), Image.open(tmp_path / "cap-0000-1.png")
    assert ImageChops.difference(first.convert("RGB"), second.convert("RGB")).getbbox()  # the yellow moved to the next word


def test_sketch_thumbnails_use_drawings_from_the_video_with_the_mascot_first(tmp_path):
    for name in ("a", "b", "c"):
        Image.new("RGB", (1024, 576), (90, 120, 200)).save(tmp_path / f"{name}.png")
    board = {"frames": [{"mode": "picture", "spec": {"picture": str(tmp_path / "a.png"), "mascot": False}},
                        {"mode": "item", "spec": {"picture": str(tmp_path / "b.png"), "mascot": True}},
                        {"mode": "picture", "spec": {"picture": str(tmp_path / "b.png"), "mascot": True}},
                        {"mode": "picture", "spec": {"picture": str(tmp_path / "missing.png"), "mascot": True}}]}
    assert thumbnail_pictures(board) == [str(tmp_path / "b.png"), str(tmp_path / "a.png")]
    out = thumbnails.draw({"layout": "sketch", "headline": "When your team loses", "big": "loses", "picture": str(tmp_path / "b.png")}, tmp_path / "t.png")
    img = Image.open(out)
    assert img.size == thumbnails.SIZE and img.getpixel((1200, 360)) == (90, 120, 200)


def test_a_picture_too_brief_to_take_in_holds_the_one_before():
    slides = [{"id": f"s{i:03}", "kind": "picture", "scene": f"{SCENE}, take {i}", "mascot": True, "caption": ""} for i in range(1, 5)]
    merged, _ = sketch_writer.apply(SCRIPT, BRIEF, board([5, 1, 4, 1.5]), slides)
    modes = [(f["mode"], f["motion"]) for f in merged["frames"]]
    assert modes == [("picture", "still"), ("picture", motion.HOLD), ("item", "still"), ("item", motion.HOLD)]
    assert merged["frames"][1]["spec"]["scene"] == merged["frames"][0]["spec"]["scene"] and merged["frames"][1]["spec"]["say"] == "Stay for number two."
    assert sketch_writer.steady(merged, "long") == merged  # running it again changes nothing


def test_art_direction_steers_clear_of_writing():
    assert "speech or thought bubbles" in sketch_writer.SYSTEM and "calendars" in sketch_writer.SYSTEM
