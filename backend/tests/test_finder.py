"""Photos and film are found automatically, only under free licenses, and fetched only once ticked."""
import io
import json

import pytest

from studio.media import finder, footage, photos, storyboard, slide_writer, themes


def page(pid=1, title="File:David Ortiz 2008.jpg", license_name="CC BY-SA 2.0", mime="image/jpeg", width=1600, size=500_000, date="2008-05-14", description="David Ortiz at bat."):
    return {"pageid": pid, "title": title, "imageinfo": [{"url": "https://upload.wikimedia.org/o.jpg", "thumburl": "https://upload.wikimedia.org/t.jpg", "descriptionurl": f"https://commons.wikimedia.org/wiki/{pid}",
            "mime": mime, "width": width, "height": 1000, "size": size, "extmetadata": {"LicenseShortName": {"value": license_name}, "Artist": {"value": "<a href='x'>Keith Allison</a>"}, "DateTimeOriginal": {"value": date}, "ImageDescription": {"value": description}}}]}


@pytest.mark.parametrize("license_name", ["CC BY-NC 2.0", "CC BY-ND 4.0", "CC BY-NC-SA 3.0", "Fair use", "All rights reserved", ""])
def test_licenses_that_are_not_free_are_never_offered(license_name):
    assert finder._candidate(page(license_name=license_name), "David Ortiz") is None


@pytest.mark.parametrize("license_name", ["CC BY 2.0", "CC BY-SA 4.0", "CC0", "Public domain"])
def test_free_licenses_are_offered_with_their_record(license_name):
    c = finder._candidate(page(license_name=license_name), "David Ortiz")
    assert c["license"] == license_name and c["author"] == "Keith Allison" and c["source_url"]


def test_a_photo_of_someone_else_or_a_logo_or_a_tiny_picture_is_not_offered():
    assert finder._candidate(page(title="File:Pedro Martinez.jpg", description="Pedro."), "David Ortiz") is None
    assert finder._candidate(page(title="File:David Ortiz logo.jpg"), "David Ortiz") is None
    assert finder._candidate(page(width=300), "David Ortiz") is None


def test_a_caption_shows_the_year_so_a_later_photo_cannot_pass_for_the_game():
    assert finder._candidate(page(), "David Ortiz")["caption"] == "David Ortiz at bat (2008)"


@pytest.mark.parametrize("description", ["big papi 1dmk2n, 300mm f/4L, w/2.0x TC white sox vs", "© Rubenstein, photographer David Ortiz seen here", "Photo courtesy of David Ortiz on Flickr", "BALTIMORE (Sept. 9, 2007) David Ortiz visits"])
def test_a_messy_file_page_never_reaches_the_screen(description):
    assert finder._candidate(page(description=description, date="2006"), "David Ortiz")["caption"] == "David Ortiz (2006)"


@pytest.mark.parametrize("field", ["Great catch MLB highlights", "From YouTube", "Major League Baseball on ESPN"])
def test_film_that_looks_like_broadcast_coverage_is_never_offered(field):
    assert finder._candidate(page(title="File:David Ortiz.webm", mime="video/webm", description=field), "David Ortiz") is None
    assert finder._candidate(page(title="File:David Ortiz.webm", mime="video/webm", description="David Ortiz at a parade"), "David Ortiz")


def test_pictures_from_the_year_of_the_moment_come_first():
    terms = finder.search_terms("x", {"beats": [{"narration": "In 2004 David Ortiz homered. By 2004 it was done, and 1918 was over."}]}, {"look": {"team": "Boston Red Sox"}})
    assert terms[0] == "Red Sox 2004"
    pages = {"1": page(1, date="2008"), "2": page(2, title="File:Red Sox parade.jpg", description="Red Sox parade", date="2004-10-30")}
    urls = []

    def fetch(url):
        urls.append(url)
        return {"query": {"pages": pages}} if "bitmap" in url else {}
    found = finder.search(["Red Sox 2004", "David Ortiz"], fetch)
    assert found[0]["year"] == "2004" and "%22Red+Sox%22+2004" in urls[0]


def test_search_terms_are_the_names_the_narrator_says():
    script = {"beats": [{"narration": "David Ortiz homered. Ortiz did it again, and Dave Roberts stole second at Fenway Park. Game Seven was next."}]}
    terms = finder.search_terms("Red Sox", script, {"look": {"team": "Boston Red Sox"}})
    assert terms[0] == "Boston Red Sox" and terms[1] == "David Ortiz" and "Fenway Park" in terms and "Game Seven" not in terms


def test_covered_and_too_vague_terms_are_dropped():
    terms = finder.search_terms("x", {"beats": [{"narration": "The Red Sox beat New York. Red Sox fans cheered."}]}, {"look": {"team": "Boston Red Sox"}})
    assert terms == ["Boston Red Sox"]


def test_a_slow_commons_is_retried_and_one_failure_keeps_the_rest(monkeypatch):
    import urllib.error
    monkeypatch.setattr(finder, "RETRY_SECONDS", (0,))
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.URLError("429")
        return {"query": {"pages": {"1": page()}}} if "bitmap" in url else {}
    assert [c["id"] for c in finder.search(["David Ortiz"], flaky)] == ["1"]


def test_commons_being_down_gives_a_plain_message(monkeypatch):
    import urllib.error
    monkeypatch.setattr(finder, "RETRY_SECONDS", (0,))

    def down(url):
        raise urllib.error.URLError("down")
    with pytest.raises(ValueError, match="isn't answering"):
        finder.search(["David Ortiz"], down)


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(finder, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(photos, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(footage, "FILM_DIR", tmp_path / "film")
    (tmp_path / "photos").mkdir()
    return tmp_path


def offer(library):
    fetch = lambda url: {"query": {"pages": {"1": page()}}} if "bitmap" in url else {}  # noqa: E731
    return finder.candidates(9, "Red Sox: comeback", {"beats": [{"narration": "David Ortiz homered."}]}, None, fetch=fetch)


def test_searching_downloads_nothing(library):
    data = offer(library)
    assert [c["id"] for c in data["candidates"]] == ["1"]
    assert not list((library / "photos").iterdir())


def test_a_ticked_photo_lands_with_its_license_and_can_be_placed(library):
    offer(library)
    opener = lambda request, timeout: _response(b"jpg")  # noqa: E731
    assert finder.download(["1"], 9, "Red Sox: comeback", opener) == ["David Ortiz 2008.jpg"]
    entry = json.loads((library / "photos" / "manifest.json").read_text())[0]
    assert entry["license"] == "CC BY-SA 2.0" and "Keith Allison" in entry["credit"] and "CC BY-SA 2.0" in entry["credit"]
    assert entry["match"] == ["Ortiz"] and entry["topics"] == ["red sox"]
    board = {"frames": [{"beat_id": "b1", "mode": "bars", "motion": "build", "spec": {"say": "Ortiz homered."}}, {"beat_id": "b2", "mode": "statement", "motion": "build", "spec": {"say": "Ortiz again."}}]}
    placed, used = photos.assign(board, "The Red Sox: game 4", library / "photos")
    assert [f["mode"] for f in placed["frames"]] == ["bars", "real_photo"] and used  # never over a chart, and the Short can use it too
    again, _ = photos.assign(placed, "The Red Sox: game 4", library / "photos")
    assert sum(f["mode"] == "real_photo" for f in again["frames"]) == 1  # filling in again doesn't use it twice


def _response(body):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return R(body)


def test_a_file_not_offered_for_this_video_is_refused(library):
    offer(library)
    with pytest.raises(ValueError, match="wasn't offered"):
        finder.download(["999"], 9, "Red Sox")


def test_both_wikimedia_file_hosts_are_accepted(tmp_path):
    for host in ("upload", "thumb"):
        out = tmp_path / f"{host}.jpg"
        finder._save(f"https://{host}.wikimedia.org/wikipedia/commons/x.jpg?utm_source=x", out, lambda request, timeout: _response(b"jpg"))
        assert out.read_bytes() == b"jpg"


def test_the_picker_gets_a_small_thumbnail_and_the_video_gets_the_large_file():
    p = page()
    p["imageinfo"][0]["thumburl"] = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/D.jpg/1920px-D.jpg"
    c = finder._candidate(p, "David Ortiz")
    assert "/500px-" in c["thumb"] and "/1920px-" in c["download_url"]


def test_only_wikimedia_files_are_fetched(tmp_path):
    with pytest.raises(ValueError, match="not a Wikimedia"):
        finder._save("https://example.com/x.jpg", tmp_path / "x.jpg")


def test_text_is_never_shortened_on_screen():
    long = "and in Game 3 at Fenway they collected 22 hits in a 19 to 8 win that ended the argument for good,"
    assert storyboard._pull(long) == "And in Game 3 at Fenway they collected 22 hits in a 19 to 8 win that ended the argument for good"


def test_slides_with_cut_off_text_are_refused():
    beat = {"id": "b1", "narration": "They won.", "on_screen_text": "", "visual_intent": "x"}
    why = slide_writer.problem({"id": "s1", "layout": "statement", "headline": "They collected hits in a…", "calculated": False}, beat, {"facts": []}, set())
    assert "cut off" in why


def test_long_sentences_divide_at_natural_phrases():
    parts = storyboard._split_long("That matters because TIME magazine credited Ruth's record chiefly to Gehrig batting behind him, arguing pitchers didn't dare walk Ruth with a hitter next".split(), 7)
    assert all(len(p.split()) >= 3 for p in parts)
    assert any(p.endswith("him,") for p in parts) and any(p.startswith("with ") for p in parts)


RED_SOX = {"team": "Boston Red Sox", "primary": "#0C2340", "secondary": "#BD3039", "highlight": "#FFFFFF", "background": "dark", "texture": "grid", "font": "condensed"}


def test_red_sox_slides_are_unmistakably_red_and_navy():
    t = themes.build(RED_SOX, 1)
    r, g, b = t["accent"]
    assert r > g * 2 and r > b * 2  # red, not the pink it used to fade to
    assert t["band"] == [189, 48, 57] and t["feature"]["ink"] == [189, 48, 57] and t["ink"] == [12, 35, 64]
    assert t["texture"] == "plain"  # no graph paper


def test_emphasis_can_always_be_seen_against_the_text():
    t = themes.build(RED_SOX, 1)
    assert themes.contrast(tuple(t["emphasis"]), tuple(t["text"])) >= 1.6
    f = t["feature"]
    assert themes.contrast(tuple(f["text"]), tuple(f["ink"])) >= 4.5
    assert themes.contrast(tuple(f["emphasis"]), tuple(f["ink"])) >= 3


@pytest.mark.parametrize("look", [RED_SOX, {"team": "Lakers", "primary": "#552583", "secondary": "#FDB927", "background": "dark"}, {"team": "Yankees", "primary": "#0C2340", "secondary": "#C4CED4", "background": "light"},
                                  {"team": "Spurs", "primary": "#000000", "secondary": "#C4CED4", "background": "dark"}])
def test_big_word_slides_stay_readable_for_any_team(look):
    t = themes.build(look, 2)
    if t["feature"]:
        assert themes.contrast(tuple(t["feature"]["text"]), tuple(t["feature"]["ink"])) >= 4.5
    assert themes.contrast(tuple(t["on_accent"]), tuple(t["accent"])) >= 3


@pytest.mark.parametrize("headline", ["0.14 × 1/8 = 0.0175", "100 - 78 = 22", "60 + 54 home runs"])
def test_an_equation_on_a_slide_is_refused(headline):
    beat = {"id": "b1", "narration": "0.14 1/8 0.0175 100 78 22 60 54", "on_screen_text": "", "visual_intent": "x"}
    why = slide_writer.problem({"id": "s1", "layout": "statement", "headline": headline, "calculated": False}, beat, {"facts": []}, set())
    assert "arithmetic" in why


@pytest.mark.parametrize("text", ["Boston won 10-3", "Runs in games 1-3", "One in 60", "101-61 (.623)"])
def test_scores_and_records_are_not_equations(text):
    assert not slide_writer.EQUATION.search(text)


def test_slide_design_gets_room_to_finish_and_stays_inside_its_reserve():
    assert slide_writer.output_limit(22) >= 32_000 and slide_writer.output_limit(500) == 64_000
    assert 64_000 * 0.50 / 1e6 <= slide_writer.RESERVE_USD


NARRATION = "It treats each game as a coin flip. But it shows why that 1 in 60 was really a bet on a single night."


def test_a_text_slide_shows_the_whole_sentence_not_a_piece_of_it():
    assert storyboard.whole_sentence("But it shows why that 1 in", NARRATION) == "But it shows why that 1 in 60 was really a bet on a single night."
    assert storyboard.whole_sentence("60 was really a bet on a single night.", NARRATION) == "But it shows why that 1 in 60 was really a bet on a single night."
    assert storyboard.whole_sentence("not in the narration", NARRATION) == "Not in the narration"


def test_a_slide_that_stops_on_a_dangling_word_counts_as_cut_off():
    assert slide_writer.cut_off_text({"headline": "But it shows why that 1 in"})
    assert slide_writer.cut_off_text({"headline": "But it shows why that 1 in 60."}) is None
    assert slide_writer.cut_off_text({"points": ["Roberts was safe at"]})


def test_both_halves_of_a_sentence_become_one_slide_that_stays_up():
    script = {"format": "short", "beats": [{"id": "b1", "narration": "But it shows why that 1 in 60 was really a bet on a single night.", "on_screen_text": "", "visual_intent": "x"}]}
    frames = [{"beat_id": "b1", "start": 0, "duration": 2, "mode": "text_card", "prompt": "x", "motion": "still", "spec": {"say": say, "headline": say}}
              for say in ("But it shows why that 1 in", "60 was really a bet on a single night.")]
    board, rejected = slide_writer.apply(script, {"facts": []}, {"style_bible": "x", "frames": frames}, [])
    assert len(rejected) == 2
    assert [f["spec"]["headline"] for f in board["frames"]] == ["But it shows why that 1 in 60 was really a bet on a single night."] * 2
    assert board["frames"][1]["motion"] == "hold" and board["frames"][1]["spec"]["say"] == "60 was really a bet on a single night."
