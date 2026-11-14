"""Slides build on screen, film plays with its license on record, and finished videos stay as approved."""
import json
import subprocess
from pathlib import Path

import pytest
from PIL import ImageChops

from studio.media import assemble, footage, motion, slide_writer, slides, themes, visuals

ITEMS = [{"label": "Q1", "value": 23, "display": "23"}, {"label": "Q2", "value": 18, "display": "18"}, {"label": "Q3", "value": 28, "display": "28"}]
EVENTS = [{"label": "1919", "value": 0, "display": "Sold to the Yankees for cash"}, {"label": "1920", "value": 0, "display": "Hits 54 home runs"},
          {"label": "1927", "value": 0, "display": "Hits 60 and sets the record"}]
MOVES = [{"from": "home", "to": "first", "label": "Ruth singles"}, {"from": "first", "to": "second", "label": "Gehrig moves him up"},
         {"from": "second", "to": "home", "label": "Meusel drives him in"}]
SPECS = {
    "statement": {"headline": "A clear point", "context": "Why it matters."},
    "big_stat": {"value": "87.5%", "label": "free throws", "context": "A career high."},
    "bars": {"headline": "Takeaway", "items": ITEMS, "body": "What the bars reveal."},
    "columns": {"headline": "Takeaway", "items": ITEMS},
    "line": {"headline": "Takeaway", "items": ITEMS, "reference_value": 30, "reference_label": "Old record"},
    "dots": {"headline": "Takeaway", "value": "28", "target": 32, "label": "free throws"},
    "share": {"headline": "Takeaway", "items": ITEMS},
    "table": {"headline": "Takeaway", "items": ITEMS, "highlight": 1},
    "tally": {"headline": "Takeaway", "value": "41", "target": 100, "label": "points"},
    "scorecard": {"headline": "Takeaway", "items": ITEMS},
    "evidence": {"headline": "A claim", "points": ["First fact", "Second fact"]},
    "quote": {"quote": "It was the greatest day", "attribution": "A witness"},
    "chapter": {"number": 2, "headline": "The second half"},
    "host": {"headline": "So how did he do it?"},
    "timeline": {"headline": "Takeaway", "items": EVENTS, "highlight": 2},
    "play": {"headline": "Takeaway", "surface": "baseball", "moves": MOVES, "body": "A three-man relay."},
}
SIZES = [(960, 540), (540, 960)]
BEAT = {"id": "b1", "narration": "Ruth singles, and Gehrig moves him up.", "on_screen_text": "", "visual_intent": "Diagram", "source_ref": None}


def same(a, b) -> bool:
    return ImageChops.difference(a, b).getbbox() is None


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("mode", SPECS)
def test_a_slide_builds_up_to_exactly_its_still(mode, size):
    draw = visuals.RENDERERS[mode]
    still = draw(size, SPECS[mode])
    assert same(draw(size, {**SPECS[mode], "t": 1.0}), still)  # no jump when the build hands over to the hold
    assert not same(draw(size, {**SPECS[mode], "t": 0.02}), still)  # and it really does start unfinished


@pytest.mark.parametrize("surface", slides.SPOTS)
def test_every_surface_draws_with_a_route_between_all_its_spots(surface):
    spots = list(slides.SPOTS[surface])
    moves = [{"from": a, "to": b, "label": "A move"} for a, b in zip(spots, spots[1:])][:6]
    for size in SIZES:
        visuals.RENDERERS["play"](size, {"headline": "Takeaway", "surface": surface, "moves": moves})


@pytest.mark.parametrize("mode", ["play", "timeline", "bars"])
def test_new_layouts_take_each_theme(mode):
    for topic in range(4):
        theme = themes.build({"team": "New York Yankees", "primary": "#0C2340", "secondary": "#C41E3A"}, topic)
        visuals.RENDERERS[mode]((960, 540), {**SPECS[mode], "theme": theme, "t": 0.5})


def test_numbers_count_up_but_years_and_ranges_do_not():
    assert slides.counted("100", 0.5) == "50"
    assert slides.counted("87.5%", 0.5) == "43.8%"
    assert slides.counted("about 88", 0.5) == "about 44"
    assert slides.counted("1,000", 0.5) == "500"
    assert slides.counted("1927", 0.5) == "1927"
    assert slides.counted("28 of 32", 0.5) == "28 of 32"
    assert slides.counted("100", 1.0) == "100"


def test_photos_never_move_only_their_words():
    file = Path(slides.__file__).parents[3] / "assets" / "photos" / "ruth-1921.jpg"
    if not file.exists():
        pytest.skip("photo not here")
    spec = {"headline": "A headline here", "photo_file": str(file), "caption": "A caption", "credit": "A credit"}
    still = visuals.RENDERERS["real_photo"]((960, 540), spec)
    early = visuals.RENDERERS["real_photo"]((960, 540), {**spec, "t": 0.1})
    box = ImageChops.difference(still, early).getbbox()
    assert box and box[0] > 300  # what changes sits to the right of the picture


def test_old_storyboards_stay_still():
    assert motion.build_frames({"mode": "bars", "motion": "still"}, 300) == 0


def test_new_storyboards_build():
    board = motion.plan({"frames": [{"mode": "bars", "motion": "still"}, {"mode": "archive_film", "motion": "still"}, {"mode": "scoreboard", "motion": "still"}]})
    assert [f["motion"] for f in board["frames"]] == ["build", "film", "still"]


def test_the_finished_slide_holds_longer_than_the_build():
    frame = {"mode": "play", "motion": "build"}
    assert motion.build_frames(frame, 30 * 20) == round(3.5 * 30)
    assert motion.build_frames(frame, 30 * 4) == round(4 * motion.MOST_OF_SLIDE * 30)
    assert motion.build_frames(frame, 30) == 0  # too brief to build


def play_slide(**kw):
    return {"id": "s001", "layout": "play", "headline": "The relay", "surface": "baseball", "moves": MOVES, "calculated": False, **kw}


def test_a_play_on_real_spots_passes():
    assert slide_writer.problem(play_slide(), BEAT, {"facts": []}, set()) is None


def test_a_play_on_a_spot_that_does_not_exist_is_rejected():
    moves = [{"from": "home", "to": "the moon", "label": "Up"}]
    assert "the moon" in slide_writer.problem(play_slide(moves=moves), BEAT, {"facts": []}, set())


def test_a_play_with_no_surface_is_rejected():
    assert "surface" in slide_writer.problem(play_slide(surface="curling"), BEAT, {"facts": []}, set())


def test_an_invented_number_in_a_route_label_is_rejected():
    moves = [{"from": "home", "to": "first", "label": "A 99 foot run"}]
    assert "99" in slide_writer.problem(play_slide(moves=moves), BEAT, {"facts": []}, set())


def test_a_timeline_year_must_be_sourced_but_its_unused_value_is_not_checked():
    beat = {**BEAT, "narration": "In 1919, 1920 and 1927 it changed."}
    items = [{"label": y, "value": 0, "display": "It changed"} for y in ("1919", "1920", "1927")]
    timeline = {"id": "s001", "layout": "timeline", "headline": "The climb", "items": items, "calculated": False}
    assert slide_writer.problem(timeline, beat, {"facts": []}, set()) is None
    invented = [*items[:2], {"label": "1931", "value": 0, "display": "It changed"}]
    assert "1931" in slide_writer.problem({**timeline, "items": invented}, beat, {"facts": []}, set())


def test_the_slide_agent_can_see_the_visual_idea_and_the_field_spots():
    assert "first_base" not in slide_writer.SYSTEM and "left_field" in slide_writer.SYSTEM
    assert "{spots}" not in slide_writer.SYSTEM
    assert set(slide_writer.SCHEMA["properties"]["slides"]["items"]["required"]) >= {"surface", "moves"}


def make_film(folder, seconds=1):
    path = folder / "reel.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=18:duration={seconds}", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def film_entry(**kw):
    return {"id": "reel", "file": "reel.mp4", "caption": "A reel", "credit": "Film: Library of Congress. Public domain.", "author": "Edison", "license": "Public domain",
            "source_url": "https://loc.gov/x", "topics": ["babe ruth"], "match": ["Yankee Stadium"], "start": 0, "end": 1, **kw}


def film_folder(tmp_path, **kw):
    make_film(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps([film_entry(**kw)]))
    return tmp_path


def board(*modes):
    return {"frames": [{"beat_id": "b1", "mode": mode, "motion": "still", "duration": 3, "spec": {"say": "They opened Yankee Stadium that spring.", "headline": "Opened"}} for mode in modes]}


def test_film_without_a_license_is_refused(tmp_path):
    folder = film_folder(tmp_path, license="")
    with pytest.raises(ValueError, match="license"):
        footage.library(folder)


def test_film_starting_at_zero_is_not_missing_its_start(tmp_path):
    assert footage.library(film_folder(tmp_path, start=0))


def test_film_replaces_a_text_slide_where_the_narrator_mentions_it(tmp_path):
    placed, used = footage.assign(board("statement"), "Babe Ruth hits 60", film_folder(tmp_path))
    assert placed["frames"][0]["mode"] == "archive_film" and used
    assert placed["frames"][0]["spec"]["credit"] and placed["frames"][0]["spec"]["say"].startswith("They opened")


def test_film_never_takes_the_place_of_a_chart_or_plays_twice(tmp_path):
    placed, _ = footage.assign(board("bars", "statement", "statement"), "Babe Ruth hits 60", film_folder(tmp_path))
    assert [f["mode"] for f in placed["frames"]] == ["bars", "archive_film", "statement"]


def test_film_stays_with_its_own_topic(tmp_path):
    placed, used = footage.assign(board("statement"), "Wilt Chamberlain scores 100", film_folder(tmp_path))
    assert placed["frames"][0]["mode"] == "statement" and not used


def test_drawn_film_and_held_clips_join_into_one_exact_video(tmp_path):
    """The real risk in mixing them: a clip the others can't be joined to, or a video that runs short."""
    size = (960, 540)
    frame = {"mode": "bars", "motion": "build", "spec": SPECS["bars"], "duration": 3}
    built, held, played = tmp_path / "built.mp4", tmp_path / "held.mp4", tmp_path / "played.mp4"
    still = tmp_path / "still.png"
    visuals.render("bars", size, SPECS["bars"], still)
    count = motion.build_frames(frame, 90)
    assemble.animate(motion.frames(frame, size, count), size, built, "preview")
    assemble.clip(still, (90 - count) / 30, size, held, "preview")
    slide = tmp_path / "slide.png"
    visuals.render("archive_film", size, {"headline": "Opened", "caption": "A reel", "credit": "A credit"}, slide)
    # The film lasts one second and the slide three: it must hold on its last frame, not loop or stop early.
    assemble.film(make_film(tmp_path), 0, 1, slide, slides.film_box(size), 3, size, played, "preview")
    joined = tmp_path / "joined.mp4"
    assemble.concat([built, held, played], joined)
    done = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(joined)],
                          capture_output=True, text=True, check=True)
    assert int(done.stdout.strip().rstrip(",")) == 180
    assert abs(assemble.probe(joined)["duration"] - 6) < 0.1


def held_board():
    frames = [{"beat_id": "b1", "start": 0, "duration": seconds, "mode": "text_card", "prompt": "x", "motion": "still", "spec": {"say": say, "headline": "x"}}
              for say, seconds in (("Here is the order.", 5), ("Combs led off.", 5), ("Koenig hit second.", 5), ("Ruth hit third.", 5))]
    return {"style_bible": "x", "frames": frames}


HOLD_SCRIPT = {"format": "long", "beats": [{**BEAT, "narration": "Here is the order. Combs led off. Koenig hit second. Ruth hit third."}]}
TABLE = {"id": "s001", "layout": "evidence", "headline": "The order", "points": ["Combs led off", "Koenig hit second"], "calculated": False}


def merged(*layouts):
    slides_in = [TABLE, *({"id": f"s{i:03}", "layout": layout} for i, layout in enumerate(layouts, 2))]
    return slide_writer.apply(HOLD_SCRIPT, {"facts": []}, held_board(), slides_in)


def test_a_held_slide_stays_up_and_does_not_rebuild():
    board, rejected = merged("hold")
    held = motion.plan(board)["frames"][1]
    assert "s002" not in {r["id"] for r in rejected}
    assert held["mode"] == "evidence" and held["spec"]["points"] == TABLE["points"]
    assert held["spec"]["say"] == "Combs led off."  # the slide cuts still line up with the words
    assert held["motion"] == motion.HOLD and motion.build_frames(held, 150) == 0


def test_a_slide_cannot_be_held_forever():
    board, rejected = merged("hold", "hold")
    assert board["frames"][1]["mode"] == "evidence" and board["frames"][2]["mode"] == "statement"
    assert rejected[0]["id"] == "s003"


def test_qa_counts_a_held_slide_as_one_slide(tmp_path):
    from studio.media import qa
    timeline = [{"beat_id": "b1", "mode": "table", "duration": 9, "motion": "build", "spec": {}}, {"beat_id": "b2", "mode": "table", "duration": 9, "motion": "hold", "spec": {}}]
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=size=960x540:rate=30:duration=1", "-f", "lavfi", "-i", "anullsrc", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    report = qa.review("long", video, "preview", timeline, [], {"beats": []}, {"assets": []})
    cadence = next(c for c in report["checks"] if c["name"] == "Visual change cadence")
    assert not cadence["passed"] and "18.0" in cadence["note"]


def test_the_batting_order_repeat_the_owner_caught_is_flagged():
    order = [("Combs", "1st"), ("Koenig", "2nd"), ("Ruth", "3rd"), ("Gehrig", "4th"), ("Meusel", "5th"), ("Lazzeri", "6th")]
    frames = [
        {"beat_id": "b1", "mode": "table", "spec": {"headline": "Koenig ahead, Gehrig and Meusel behind", "items": [{"label": n, "value": 0, "display": p} for n, p in order]}},
        {"beat_id": "b2", "mode": "scorecard", "spec": {"headline": "Ruth's neighbors in the order", "items": [{"label": "Koenig, before Ruth", "value": 0, "display": "2nd"}, {"label": "Ruth", "value": 0, "display": "3rd"}, {"label": "Gehrig, after Ruth", "value": 0, "display": "4th"}]}},
        {"beat_id": "b3", "mode": "evidence", "spec": {"headline": "Two hitters decided what followed", "points": ["Koenig batted directly ahead of Ruth", "Gehrig and Meusel batted behind him"]}},
    ]
    assert [r["beat"] for r in slide_writer.likely_repeats({"frames": frames})] == ["b2", "b3"]


def test_slides_on_different_subjects_are_not_flagged():
    frames = [{"beat_id": "b1", "mode": "big_stat", "spec": {"value": "60", "label": "home runs", "headline": "Ruth alone"}},
              {"beat_id": "b2", "mode": "bars", "spec": {"headline": "Zachary lost 13 games", "items": [{"label": "Washington", "value": 0, "display": "81"}]}}]
    assert slide_writer.likely_repeats({"frames": frames}) == []


def test_the_owner_rule_against_repeats_reaches_every_writer():
    from studio.agents import live
    assert "owner-no-repeats" in {e["id"] for e in json.loads(live.PLAYBOOK_FILE.read_text())["entries"]}
    assert "Say each thing once" in live._playbook({"niche"})
    assert "Say each thing once" in slide_writer.SYSTEM


def test_a_hold_that_runs_over_with_the_real_voice_gets_its_own_slide():
    """Job 9: a Short's hold was planned inside the limit, and the real voice took it to 5.13 s, which blocked the video."""
    from studio.media import produce
    theme = {"ink": [1, 2, 3]}
    timeline = [{"beat_id": "b3", "mode": "statement", "motion": "build", "duration": 2.26, "spec": {"say": "and TIME reported Ruth drew", "headline": "And TIME reported Ruth drew", "theme": theme}},
                {"beat_id": "b3", "mode": "statement", "motion": "hold", "duration": 2.87, "spec": {"say": "fewer walks than in 1921.", "headline": "And TIME reported Ruth drew", "theme": theme}}]
    beats = [{"id": "b3", "narration": "And TIME reported Ruth drew fewer walks than in 1921."}]
    fixed = produce.limit_holds(timeline, "short", beats)
    assert fixed[0] == timeline[0]
    assert fixed[1]["motion"] == "build" and fixed[1]["spec"]["headline"] == "And TIME reported Ruth drew fewer walks than in 1921."
    assert fixed[1]["spec"]["say"] == "fewer walks than in 1921." and fixed[1]["spec"]["theme"] == theme and fixed[1]["duration"] == 2.87
    assert produce.limit_holds(timeline, "long") == timeline  # the same hold is fine on a long video


def test_one_long_sentence_is_split_onto_slides_as_it_is_spoken():
    """Job 19: a single slide ran 17.7 s under one long sentence, and video QA blocked the job for it."""
    from studio.media import produce
    say = "The 2007 Patriots scored 589 points, which was the NFL record, and they didn't just edge past the old mark, they cleared it by 33."
    frame = {"beat_id": "b04", "mode": "statement", "motion": "build", "start": 62.0, "duration": 17.7, "spec": {"say": say, "headline": say, "numbers": ["589"], "theme": {"ink": [1, 2, 3]}}}
    words = [{"word": w, "start": 62.0 + i * 0.7, "end": 62.0 + i * 0.7 + 0.6} for i, w in enumerate(say.split())]
    out = produce.split_long([frame], "long", words)
    assert len(out) > 1 and all(f["duration"] <= produce.MAX_FRAME_SECONDS["long"] for f in out)
    assert " ".join(f["spec"]["say"] for f in out) == say and out[0]["spec"]["headline"] == say  # nothing lost, the first slide unchanged
    assert out[1]["mode"] == "statement" and out[1]["spec"]["theme"] == frame["spec"]["theme"] and out[1]["start"] == round(62.0 + 11 * 0.7 - produce.CUT_LEAD_SECONDS, 3)
    assert round(sum(f["duration"] for f in out), 2) == 17.7
    assert produce.split_long([{**frame, "duration": 9.0}], "long", words) == [{**frame, "duration": 9.0}]
