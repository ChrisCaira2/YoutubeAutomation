"""Cartoon scenes and the Professor's welcome: the owner's choice of look, 2026-11-07."""
import numpy as np
import pytest
import soundfile as sf
from PIL import ImageChops

from studio.media import cartoon, motion, produce, slide_writer, slides, spoken, themes, visuals

PATRIOTS = {"team": "New England Patriots", "primary": "#002244", "secondary": "#C60C30", "background": "dark",
            "opponent": "Atlanta Falcons", "opponent_primary": "#A71930", "opponent_secondary": "#000000"}
CATCH = {"headline": "Edelman's catch", "surface": "football", "actors": [
    {"side": "us", "action": "throw", "from": "own_40", "to": "midfield"}, {"side": "us", "action": "catch", "from": "midfield", "to": "midfield"},
    {"side": "them", "action": "tackle", "from": "opp_40", "to": "midfield"}]}


@pytest.mark.parametrize("size", [(960, 540), (540, 960)])
@pytest.mark.parametrize("surface", slides.SPOTS)
def test_every_sport_gets_a_scene_in_both_shapes(surface, size):
    spots = list(slides.SPOTS[surface])
    actors = [{"side": side, "action": action, "from": spots[k % len(spots)], "to": spots[(k + 1) % len(spots)]}
              for k, (side, action) in enumerate(zip(["us", "them"] * 5, cartoon.ACTIONS))][:6]
    theme = themes.build(PATRIOTS, 3)
    for t in (0.05, 0.5, 1.0):
        img = visuals.RENDERERS["scene"](size, {"headline": "A moment", "surface": surface, "actors": actors, "theme": theme, "t": t, "seconds": 4})
        assert img.size == size


def test_a_scene_keeps_moving_while_it_is_on_screen():
    spec = {**CATCH, "theme": themes.build(PATRIOTS, 3), "seconds": 6}
    early, later = (visuals.RENDERERS["scene"]((960, 540), {**spec, "t": t}) for t in (0.1, 0.9))
    assert ImageChops.difference(early, later).getbbox()


def test_both_teams_wear_their_own_colors():
    theme = themes.build(PATRIOTS, 3)
    assert theme["us"][0] == [0, 34, 68] and theme["them"][0] == [167, 25, 48]
    assert themes.build({**PATRIOTS, "opponent_primary": None}, 3)["them"][0] == [214, 214, 210]  # unknown opponent: plain neutral


def test_cartoon_videos_use_the_rounded_font_and_drawn_outlines():
    theme = themes.build(PATRIOTS, 3)
    assert theme["font"] == "rounded" and theme["style"] == "cartoon" and theme["texture"] == "plain"
    items = [{"label": "Patriots", "value": 34, "display": "34"}, {"label": "Falcons", "value": 28, "display": "28"}]
    img = visuals.RENDERERS["bars"]((960, 540), {"headline": "Overtime", "items": items, "theme": theme})
    assert slides.OUTLINE in {color for _, color in img.getcolors(maxcolors=1_000_000)}


def scene_slide(**kw):
    return {"id": "s001", "layout": "scene", "headline": "The catch", "surface": "football", "actors": CATCH["actors"], "calculated": False, **kw}


BEAT = {"id": "b1", "narration": "Brady threw and Edelman caught it.", "on_screen_text": "", "visual_intent": "x"}


def test_a_scene_on_real_spots_passes():
    assert slide_writer.problem(scene_slide(), BEAT, {"facts": []}, set()) is None


@pytest.mark.parametrize("bad, why", [({"surface": "curling"}, "surface"), ({"actors": []}, "1 to 6"),
                                      ({"actors": [{"side": "us", "action": "run", "from": "own_40", "to": "the moon"}]}, "the moon"),
                                      ({"actors": [{"side": "us", "action": "dance", "from": "own_40", "to": "own_40"}]}, "action")])
def test_a_scene_that_cannot_be_drawn_is_refused(bad, why):
    assert why in slide_writer.problem(scene_slide(**bad), BEAT, {"facts": []}, set())


def test_the_slide_agent_knows_scenes_and_their_actions():
    assert "scene:" in slide_writer.SYSTEM and "celebrate" in slide_writer.SYSTEM and "{actions}" not in slide_writer.SYSTEM
    assert "actors" in slide_writer.SCHEMA["properties"]["slides"]["items"]["required"]


def test_scenes_and_the_intro_move_for_their_whole_time():
    board = motion.plan({"frames": [{"mode": "scene", "motion": "still"}, {"mode": "intro", "motion": "still"}]})
    assert all(f["motion"] == "animate" for f in board["frames"])
    assert motion.build_frames(board["frames"][0], 240) == 240


def test_the_intro_is_its_own_beat_and_says_the_episode():
    say = cartoon.intro_line("The Patriots come back from 28–3 in Super Bowl LI: The catch")
    assert say == "Welcome to The Athletics Archive. I'm Professor Sportington III." and len(say.split()) <= 10  # about four seconds
    assert "Sportington the Third" in spoken.normalize(say)
    assert spoken.normalize("Super Bowl LI, 28–3") == "Super Bowl fifty-one, twenty-eight to three"
    board = {"frames": [{"beat_id": "intro", "mode": "intro", "spec": {"say": "Welcome."}}, {"beat_id": "b1", "mode": "statement", "spec": {}}]}
    beats = produce.with_intro([BEAT], board)
    assert [b["id"] for b in beats] == ["intro", "b1"] and beats[0]["narration"] == "Welcome."
    assert produce.with_intro([BEAT], {"frames": [board["frames"][1]]}) == [BEAT]


def test_the_professor_talks_when_his_voice_is_loud(tmp_path):
    rate = 24000
    quiet, loud = np.zeros(rate // 2, dtype=np.float32), (np.sin(np.arange(rate // 2) / 5) * 0.5).astype(np.float32)
    sf.write(tmp_path / "v.wav", np.concatenate([quiet, loud]), rate)
    levels = produce.mouth(tmp_path / "v.wav", 0, 1.0)
    assert 28 <= len(levels) <= 30 and max(levels[:10]) < 0.05 and min(levels[-10:]) > 0.5
    shut = visuals.RENDERERS["intro"]((960, 540), {"title": "Super Bowl LI", "t": 1.0, "seconds": 3.0, "mouth": [0.0] * 120})
    talking = visuals.RENDERERS["intro"]((960, 540), {"title": "Super Bowl LI", "t": 1.0, "seconds": 3.0, "mouth": [1.0] * 120})
    assert ImageChops.difference(shut, talking).getbbox()


def test_he_walks_on_and_writes_the_channel_name():
    start = visuals.RENDERERS["intro"]((960, 540), {"title": "x", "t": 0.01, "seconds": 6.0})
    end = visuals.RENDERERS["intro"]((960, 540), {"title": "x", "t": 1.0, "seconds": 6.0})
    assert ImageChops.difference(start, end).getbbox()


def test_football_is_seen_from_behind_the_end_zone_the_play_heads_for():
    view = cartoon.EndZone([0.77, 0.95])  # opp_20 to opp_goal
    assert view.near == 1.0
    across, depth = view.place((0.95, 0.3))
    assert across == 0.3 and depth > view.place((0.77, 0.3))[1]  # the goal line is nearer the camera than the 20
    back = cartoon.EndZone([0.05, 0.23])
    assert back.near == 0.0 and back.place((0.05, 0.3))[1] > back.place((0.23, 0.3))[1]
    mid = cartoon.EndZone([0.5, 0.5])
    assert 0.6 < mid.place((0.5, 0.5))[1] < 1.0  # a midfield play is still close to the camera


from studio.media import football  # noqa: E402

STRIP = {"offense": "them", "play": "strip_sack", "yard_line": 25, "to_yard": 25, "target": "slot", "names": {"qb": "Ryan", "target": "", "defender": "Hightower"}}


def test_a_formation_has_eleven_on_each_side_lined_up_on_the_ball():
    plan = football.build(STRIP)
    assert sum(p.offense for p in plan["players"]) == 11 and sum(not p.offense for p in plan["players"]) == 11
    los = plan["los"]
    assert all(p.path[0][1][0] >= los for p in plan["players"] if p.offense)  # Atlanta attacks down the field: the offense starts behind its line
    assert all(p.path[0][1][0] < los for p in plan["players"] if not p.offense)


@pytest.mark.parametrize("play", football.PLAYS)
def test_every_play_moves_and_draws_from_start_to_finish(play):
    spec = {"offense": "us", "play": play, "yard_line": 40, "to_yard": 100 if play != "interception" else 0, "target": "left_wr", "names": {"qb": "Brady", "target": "Edelman", "defender": "Alford"}}
    plan = football.build(spec)
    moved = [p for p in plan["players"] if p.at(0) != p.at(3.0)]
    assert len(moved) >= 5
    theme = themes.build(PATRIOTS, 3)
    for size in ((960, 540), (540, 960)):
        for t in (0.0, 0.3, 0.6, 1.0):
            visuals.RENDERERS["scene"](size, {"headline": "A play", "surface": "football", "formation": spec, "theme": theme, "t": t, "seconds": 6})


def test_the_sacked_quarterback_goes_down_and_the_rusher_reaches_him():
    plan = football.build(STRIP)
    qb = next(p for p in plan["players"] if p.role == "qb")
    rusher = next(p for p in plan["players"] if p.role == "dl1")
    assert football.pose(qb, plan, 2.5) == "slump" and football.pose(rusher, plan, 1.9) == "tackle"
    assert football.named(plan, STRIP["names"]) == {"qb": "Ryan", "dl1": "Hightower"}


def test_a_touchdown_run_ends_in_the_end_zone_and_the_offense_celebrates():
    plan = football.build({"offense": "us", "play": "run", "yard_line": 98, "to_yard": 100, "target": "running_back", "names": {}})
    carrier = next(p for p in plan["players"] if p.role == "running_back")
    assert carrier.at(3.5)[0] >= 0.95 and football.pose(carrier, plan, 3.6) == "celebrate"


def test_the_slide_agent_can_ask_for_a_formation_and_bad_ones_are_refused():
    ok = scene_slide(actors=None, formation=STRIP)
    assert slide_writer.problem(ok, BEAT, {"facts": []}, set()) is None
    assert "unknown" in slide_writer.problem(scene_slide(formation={**STRIP, "play": "hail_mary"}), BEAT, {"facts": []}, set())
    assert "0 to 100" in slide_writer.problem(scene_slide(formation={**STRIP, "yard_line": 140}), BEAT, {"facts": []}, set())
    assert "football" in slide_writer.problem(scene_slide(surface="baseball", formation=STRIP), BEAT, {"facts": []}, set())
    assert "formation" in slide_writer.SCHEMA["properties"]["slides"]["items"]["required"] and "{plays}" not in slide_writer.SYSTEM


def test_a_play_held_over_more_narration_keeps_moving_from_where_it_was():
    timeline = [{"beat_id": "b1", "mode": "scene", "motion": "animate", "duration": 3.8, "spec": {"headline": "x"}},
                {"beat_id": "b1", "mode": "scene", "motion": "hold", "duration": 4.8, "spec": {"headline": "x"}},
                {"beat_id": "b2", "mode": "bars", "motion": "build", "duration": 5, "spec": {}}]
    out = motion.keep_playing(timeline)
    assert out[1]["motion"] == "animate" and out[1]["spec"]["clock_start"] == 3.8 and out[2] == timeline[2]
    clocks = [spec["t"] * spec["seconds"] for spec in ({**f} for f in _specs(out[1], 4))]
    assert abs(clocks[0] - (3.8 + 1 / 30)) < 1e-6 and clocks == sorted(clocks)
    assert produce.limit_holds(timeline * 3, "short") == timeline * 3  # a moving scene isn't cut short like a held slide


def _specs(frame, count):
    seen = []
    real = visuals.RENDERERS[frame["mode"]]
    visuals.RENDERERS[frame["mode"]] = lambda size, spec: seen.append(spec)
    try:
        list(motion.frames(frame, (64, 36), count))
    finally:
        visuals.RENDERERS[frame["mode"]] = real
    return seen


def test_plays_replace_text_slides_keep_charts_and_carry_through_the_beat():
    script = {"format": "long", "beats": [{"id": "b1", "narration": "Ryan dropped back and Hightower hit him. The ball came out.", "on_screen_text": "", "visual_intent": "x"}]}
    frames = [{"beat_id": "b1", "start": 0, "duration": 3, "mode": mode, "prompt": "x", "motion": m, "spec": {"say": say, "headline": "h", "sport": "football"}}
              for mode, m, say in (("statement", "still", "Ryan dropped back and Hightower hit him."), ("statement", "hold", "The ball came out."), ("bars", "build", "x"))]
    play = {"id": "s001", "headline": "Hightower strips Ryan", "emphasis": "", "formation": STRIP}
    board, rejected = slide_writer.apply_plays(script, {"facts": []}, {"frames": frames}, [play, {**play, "id": "s003"}])
    assert [f["mode"] for f in board["frames"]] == ["scene", "scene", "bars"]
    assert board["frames"][1]["spec"]["say"] == "The ball came out." and board["frames"][1]["spec"]["formation"] == STRIP
    assert rejected == [{"id": "s003", "reason": "kept the bars chart"}]


def test_a_play_with_an_invented_number_is_left_out():
    script = {"format": "long", "beats": [{"id": "b1", "narration": "Hightower hit Ryan.", "on_screen_text": "", "visual_intent": "x"}]}
    frames = [{"beat_id": "b1", "start": 0, "duration": 3, "mode": "statement", "prompt": "x", "motion": "still", "spec": {"say": "Hightower hit Ryan.", "sport": "football"}}]
    board, rejected = slide_writer.apply_plays(script, {"facts": []}, {"frames": frames}, [{"id": "s001", "headline": "A 99-yard sack", "emphasis": "", "formation": STRIP}])
    assert board["frames"][0]["mode"] == "statement" and "99" in rejected[0]["reason"]

