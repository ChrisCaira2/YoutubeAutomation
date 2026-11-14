"""The slide system: Haiku's slides are checked, and every layout draws cleanly."""
import json

import pytest
from PIL import Image

from studio.media import slide_writer, slides, storyboard, visuals, themes

BEAT = {"id": "b1", "narration": "Halftime: 41 points. Twenty-one shots in a quarter.", "on_screen_text": "Halftime: 41", "visual_intent": "Tally", "source_ref": 1, "est_seconds": 5}
BRIEF = {"facts": [{"claim": "He made 28 of 32.", "source_title": "A very long page title about the game", "source_url": "https://www.basketball-reference.com/boxscores/x"}]}


def slide(**kw):
    base = {"id": "s001", "layout": "statement", "headline": "A headline", "calculated": False}
    return {**base, **kw}


def check(s, earlier=None):
    return slide_writer.problem(s, BEAT, BRIEF, {"41", "21", "28", "32"}, earlier)


def test_number_from_the_narration_passes():
    assert check(slide(layout="big_stat", value="41", label="at the half")) is None


def test_number_from_a_sourced_fact_passes():
    assert check(slide(layout="big_stat", value="28 of 32", label="free throws")) is None


def test_spelled_out_number_counts():
    assert check(slide(headline="21 shots in one quarter")) is None


def test_invented_number_is_rejected():
    assert "99" in check(slide(layout="big_stat", value="99", label="points"))


def test_invented_chart_value_is_rejected():
    items = [{"label": "Q1", "value": 41, "display": "41"}, {"label": "Q2", "value": 77, "display": "77"}]
    assert "77" in check(slide(layout="bars", items=items))


def test_period_labels_are_not_stats():
    items = [{"label": "Q1", "value": 41, "display": "41"}, {"label": "Q2", "value": 21, "display": "21"}]
    assert check(slide(layout="columns", items=items)) is None


def test_number_stated_in_an_earlier_beat_passes():
    assert check(slide(headline="Ten more than the 18 before"), earlier={"18"}) is None
    assert check(slide(headline="Ten more than the 18 before")) is not None


def test_quote_must_be_in_the_narration():
    assert check(slide(layout="quote", quote="an amazing night", headline=None)) is not None
    assert check(slide(layout="quote", quote="twenty-one shots", headline=None)) is None


def test_chart_needs_at_least_two_items():
    assert check(slide(layout="bars", items=[{"label": "a", "value": 41, "display": "41"}])) is not None


def test_bug_must_use_a_stated_total():
    assert check(slide(bug={"label": "Wilt", "value": "41", "period": "Half"})) is None
    assert check(slide(bug={"label": "Wilt", "value": "50", "period": "Half"})) is not None


def board(n=30):
    say = "Halftime: 41 points."
    return {"style_bible": "s", "frames": [{"beat_id": "b1", "start": 0, "duration": 4, "mode": "text_card", "prompt": "p", "motion": "push_in",
                                            "spec": {"headline": say, "say": say, "sport": "basketball"}} for _ in range(n)]}


def test_professor_is_rationed():
    script = {"format": "long", "beats": [BEAT]}
    answers = [slide(id=f"s{i:03}", layout="host", headline="Where next?") for i in range(1, 31)]
    merged, rejected = slide_writer.apply(script, BRIEF, board(), answers)
    assert not rejected and sum(f["mode"] == "host" for f in merged["frames"]) == 3


def test_failed_or_missing_slide_falls_back_to_plain_words():
    script = {"format": "long", "beats": [BEAT]}
    merged, rejected = slide_writer.apply(script, BRIEF, board(2), [slide(id="s001", layout="big_stat", value="99", label="x")])
    assert [f["mode"] for f in merged["frames"]] == ["statement", "statement"] and len(rejected) == 2
    assert merged["frames"][0]["spec"]["headline"] == "Halftime: 41 points."


def test_only_slides_with_numbers_cite_a_source_and_by_site_name():
    script = {"format": "long", "beats": [BEAT]}
    answers = [slide(id="s001", layout="big_stat", value="41", label="at the half"), slide(id="s002", headline="Hold that thought")]
    merged, _ = slide_writer.apply(script, BRIEF, board(2), answers)
    assert merged["frames"][0]["spec"]["source"] == "basketball-reference.com"
    assert merged["frames"][1]["spec"]["source"] is None


ITEMS = [{"label": "Q1", "value": 23, "display": "23"}, {"label": "Q2", "value": 18, "display": "18"}]
SPECS = {
    "statement": {"kicker": "The myth", "headline": "The famous photo was staged", "emphasis": "staged", "context": "Taken afterward", "source": "nba.com"},
    "big_stat": {"value": "28 of 32", "label": "free throws", "context": "A 51.1% shooter", "calculated": True, "source": "nba.com"},
    "bars": {"headline": "Takeaway", "items": ITEMS, "bug": {"label": "Wilt", "value": "41", "period": "Half"}},
    "columns": {"headline": "Takeaway", "items": ITEMS, "highlight": 0},
    "tally": {"headline": "Halfway", "value": "41", "target": 100, "label": "points"},
    "scorecard": {"headline": "His line", "items": ITEMS},
    "quote": {"quote": "a remarkable feat", "attribution": "NBA.com"},
    "line": {"headline": "He passed his record late", "items": [{"label": "Q1", "value": 23, "display": "23"}, {"label": "Half", "value": 41, "display": "41"}, {"label": "Q3", "value": 69, "display": "69"}, {"label": "Final", "value": 100, "display": "100"}], "reference_value": 78, "reference_label": "Old record: 78", "body": "He only passed his own mark in the last quarter."},
    "dots": {"headline": "He almost never missed", "value": "28", "target": 32, "label": "free throws made", "body": "A 51.1% career shooter made seven of every eight."},
    "share": {"headline": "One man, most of the points", "items": [{"label": "Wilt", "value": 100, "display": "100"}, {"label": "Team", "value": 69, "display": "69"}], "body": "About 59% of the team's scoring."},
    "table": {"headline": "The full line", "items": [{"label": "Minutes", "value": 48, "display": "48"}, {"label": "Field goals", "value": 36, "display": "36 of 63"}, {"label": "Fouls", "value": 2, "display": "2"}], "highlight": 1},
    "evidence": {"headline": "The Knicks were short-handed", "points": ["Starting center Phil Jordan was out with the flu", "Imhoff and Buckner were left to guard him"], "kicker": "The setup"},
    "chapter": {"number": 1, "headline": "The first half"},
    "host": {"headline": "Where do the other 59 come from?", "emphasis": "59"},
}


@pytest.mark.parametrize("size", [(960, 540), (540, 960)])
@pytest.mark.parametrize("mode", list(SPECS))
def test_every_layout_draws_in_both_orientations(mode, size, tmp_path):
    out = tmp_path / "s.png"
    visuals.render(mode, size, SPECS[mode], out)
    assert Image.open(out).size == size


@pytest.mark.parametrize("mode", ["bars", "columns", "scorecard"])
def test_chart_layouts_survive_empty_data(mode, tmp_path):
    visuals.render(mode, (960, 540), {"headline": "No data"}, tmp_path / "s.png")


def test_big_stat_keeps_the_whole_value_on_one_line():
    img = slides.big_stat((1280, 720), {"value": "1,234,567 of 9,876,543", "label": "x"})
    # amber must stop before the divider, not run off the slide
    amber = [x for x in range(img.width) if any(img.getpixel((x, y)) == slides.AMBER for y in range(0, img.height, 4))]
    assert amber and max(amber) < img.width * 0.66


def test_glyphs_missing_from_the_font_are_spelled_out_on_every_layout():
    assert visuals.printable("A foul every 3⅓ minutes") == "A foul every 3 1/3 minutes"
    assert visuals.printable({"items": [{"display": "½"}]}) == {"items": [{"display": " 1/2"}]}


def test_only_real_quotations_get_quote_marks():
    said = {"narration": "NBA.com calls it 'a remarkable feat.' Pollack wrote 100 on a piece of paper."}
    real = slide(layout="quote", quote="a remarkable feat", attribution="NBA.com")
    assert slide_writer.unquote_narration(real, said)["layout"] == "quote"
    narrator = slide(layout="quote", quote="Pollack wrote 100 on a piece of paper.", attribution="NBA.com")
    fixed = slide_writer.unquote_narration(narrator, said)
    assert fixed["layout"] == "statement" and fixed["headline"].startswith("Pollack") and fixed["attribution"] is None


def test_contractions_do_not_count_as_quotation_marks():
    assert not slide_writer.really_quoted("the record doesn", {"narration": "It isn't quoted, and the record doesn't say."}["narration"])


def contrast(a, b):
    def lum(c):
        vals = [(v / 255 / 12.92 if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4) for v in c]
        return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("fg,bg", [(slides.CREAM, slides.INK), (slides.AMBER, slides.INK), (slides.TEAL, slides.INK), (slides.MUTED, slides.INK),
                                   (slides.MUTED, slides.PANEL), (slides.INK, slides.AMBER), (slides.AMBER, slides.PANEL)])
def test_text_meets_wcag_aa_contrast(fg, bg):
    assert contrast(fg, bg) >= 4.5


def test_storyboard_frames_carry_what_the_narrator_says():
    b = storyboard.plan({"format": "long", "beats": [BEAT]}, "Wilt", "s")
    assert " ".join(f["spec"]["say"] for f in b["frames"]) == BEAT["narration"]


def test_emphasis_highlights_the_phrase_only():
    words = "One in two became seven in eight".split()
    assert slides.emphasized(words, "seven in eight") == {4, 5, 6}
    assert slides.emphasized(words, "not there") == set()


def test_captions_never_run_across_a_sentence():
    from studio.media.assemble import caption_chunks
    words = [{"word": w} for w in "Footnote time. Take that surge away.".split()]
    assert [[w["word"] for w in c] for c in caption_chunks(words)] == [["Footnote", "time."], ["Take", "that", "surge"], ["away."]]


def test_output_limit_scales_and_stays_inside_the_budget_reserve():
    assert slide_writer.output_limit(110) > 29_448 * 1.5  # the most a real 110-slide run has used
    assert slide_writer.output_limit(10_000) * 0.5 / 1e6 <= slide_writer.RESERVE_USD


def test_dots_cannot_show_more_makes_than_attempts():
    assert "bigger" in check(slide(layout="dots", value="33", target=32, label="made")) or check(slide(layout="dots", value="33", target=32)) is not None
    assert check(slide(layout="dots", value="28", target=32, label="made")) is None


def test_evidence_needs_real_points():
    assert check(slide(layout="evidence", points=["Only one"])) is not None
    assert check(slide(layout="evidence", points=["21 shots", "41 at the half"])) is None


def test_numbers_in_analysis_text_are_checked_too():
    assert "77" in check(slide(layout="bars", items=[{"label": "a", "value": 41, "display": "41"}, {"label": "b", "value": 21, "display": "21"}], body="That is 77 better."))
    assert "77" in check(slide(layout="evidence", points=["He scored 41", "Then 77 more"]))
    assert "55" in check(slide(layout="line", items=[{"label": "a", "value": 21, "display": "21"}, {"label": "b", "value": 41, "display": "41"}], reference_value=55))


def test_schema_stays_inside_the_api_limit_on_optional_fields():
    from studio.llm import api_schema
    text = json.dumps(api_schema(slide_writer.SCHEMA))
    assert text.count('"anyOf"') <= 16


def test_x_of_y_numbers_become_charts():
    dots_slide = slide_writer.chart_it(slide(layout="big_stat", value="28 of 32", label="free throws", context="A 51.1% shooter"))
    assert dots_slide["layout"] == "dots" and dots_slide["value"] == "28" and dots_slide["target"] == 32 and dots_slide["body"] == "A 51.1% shooter"
    bar = slide_writer.chart_it(slide(layout="big_stat", value="100 of 169", label="Wilt's points"))
    assert bar["layout"] == "share" and [i["value"] for i in bar["items"]] == [100, 69]
    plain = slide(layout="big_stat", value="87.5%", label="x")
    assert slide_writer.chart_it(plain) == plain


def test_box_score_decimals_match_percentages():
    brief = {"facts": [{"claim": "28 of 32 free throws (.875)"}]}
    assert "87.5" in slide_writer.allowed_numbers(BEAT, brief)


def test_emphasis_can_arrive_as_a_list():
    assert slides.emphasized("His biggest quarter".split(), ["biggest"]) == {1}


def test_brief_demands_charts_first():
    assert "At least 55% are visual" in slide_writer.SYSTEM


def test_chapter_cards_come_from_the_script():
    beat = {**BEAT, "on_screen_text": "Chapter 2: The second half"}
    fixed = slide_writer.real_chapter(slide(layout="chapter", headline="Halftime: 41 points", number=7), beat, "Next.")
    assert fixed["number"] == 2 and fixed["headline"] == "The second half"
    spoken_chapter = slide_writer.real_chapter(slide(layout="chapter", headline="x", number=None), BEAT, "Chapter four: the locker room.")
    assert spoken_chapter["number"] == 4 and spoken_chapter["headline"] == "The locker room"


def test_a_slide_that_is_not_a_chapter_opening_loses_the_chapter_card():
    assert slide_writer.real_chapter(slide(layout="chapter", headline="Next reel"), BEAT, "It's waiting on the next reel.")["layout"] == "statement"


def test_scorecard_shows_the_whole_value():
    img = slides.scorecard((1280, 720), {"headline": "h", "items": [{"label": "a", "value": 88, "display": "about 88"}, {"label": "b", "value": 78, "display": "78"}]})
    assert img.size == (1280, 720)


YANKEES = {"team": "New York Yankees", "primary": "#0C2340", "secondary": "#C4CED3", "highlight": "#C8102E", "background": "light", "texture": "pinstripes", "font": "slab"}
LOOKS = [YANKEES,
         {**YANKEES, "background": "dark", "texture": "grid", "font": "din"},
         {"team": "Pale", "primary": "#FFE000", "secondary": "#FFF2A0", "highlight": "#FFFF00", "background": "dark", "texture": "diagonal", "font": "futura"},
         {"team": "Pale light", "primary": "#FFE000", "secondary": "#FFF2A0", "highlight": "#FFFF00", "background": "light", "texture": "plain", "font": "condensed"},
         {"team": "Broken", "primary": "not a color", "secondary": "", "highlight": "#12", "background": "light", "texture": "lasers", "font": "comic"}]


@pytest.mark.parametrize("look", LOOKS)
def test_any_team_colors_stay_readable(look):
    t = themes.build(look, 3)
    c = lambda k: tuple(t[k])  # noqa: E731
    assert themes.contrast(c("text"), c("ink")) >= 7
    assert themes.contrast(c("accent"), c("ink")) >= 4.5
    assert themes.contrast(c("emphasis"), c("ink")) >= 4.5
    assert themes.contrast(c("muted"), c("panel")) >= 4.5 and themes.contrast(c("muted"), c("ink")) >= 4.5
    assert themes.contrast(c("second"), c("ink")) >= 2.5
    assert t["texture"] in themes.TEXTURES and t["font"] in themes.FONTS
    assert themes.contrast(tuple(t["thumb"]["big"]), tuple(t["thumb"]["top"])) >= 7


def test_no_look_keeps_the_standard_slides():
    assert themes.build(None, 1) is None
    board = {"frames": [{"spec": {"a": 1}}]}
    assert themes.attach(board, None) is board


def test_neighboring_topics_get_a_different_format():
    formats = [{k: themes.build(YANKEES, i)[k] for k in ("side", "corner")} for i in range(1, 6)]
    assert all(a != b for a, b in zip(formats, formats[1:]))


def test_every_layout_draws_in_every_look_and_leaves_the_standard_alone():
    size = (960, 540)
    spec = {"headline": "He hit 60 home runs", "emphasis": "60", "value": "60", "target": 100, "label": "Home runs", "body": "More than any team.",
            "items": [{"label": "1926", "value": 47}, {"label": "1927", "value": 60}], "points": ["One", "Two"], "quote": "Words", "number": 1, "context": "More."}
    before = (slides.INK, slides.AMBER, slides.HEAVY)
    for look in LOOKS:
        themed = {**spec, "theme": themes.build(look, 1)}
        for mode in ("statement", "big_stat", "bars", "columns", "tally", "scorecard", "quote", "chapter", "host", "line", "dots", "share", "table", "evidence"):
            img = visuals.RENDERERS[mode](size, themed)
            assert img.size == size
    assert (slides.INK, slides.AMBER, slides.HEAVY) == before


def test_slides_really_change_with_the_theme():
    spec = {"headline": "Sixty", "items": [{"label": "A", "value": 1}, {"label": "B", "value": 2}]}
    plain = visuals.RENDERERS["bars"]((960, 540), spec)
    themed = visuals.RENDERERS["bars"]((960, 540), {**spec, "theme": themes.build(YANKEES, 1)})
    assert plain.getpixel((5, 5)) == slides.INK
    assert themed.getpixel((5, 5)) != slides.INK


def test_wide_fonts_shrink_instead_of_colliding():
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (100, 100)))
    wide = themes.FONTS["slab"]
    text = "Chamberlain field goal attempts   63"
    assert d.textlength(text, font=slides.sized(d, text, wide, 60, 400)) <= 400
    assert d.textlength("Hi", font=slides.sized(d, "Hi", wide, 60, 400)) > d.textlength("Hi", font=slides.sized(d, "Hi", wide, 20, 400))


def test_box_score_decimals_are_allowed_either_way():
    beat = {"narration": "A .714 team.", "on_screen_text": ""}
    allowed = slide_writer.allowed_numbers(beat, {"facts": []})
    assert "71.4" in allowed and "0.714" in allowed
