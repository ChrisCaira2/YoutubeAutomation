import re

import pytest

from studio.media.spoken import normalize, ordinal, words, year


@pytest.mark.parametrize("n,text", [(1962, "nineteen sixty-two"), (1905, "nineteen oh five"), (1900, "nineteen hundred"), (2008, "two thousand eight"), (2016, "twenty sixteen")])
def test_years_read_the_way_people_say_them(n, text):
    assert year(n) == text


@pytest.mark.parametrize("n,text", [(100, "one hundred"), (169, "one hundred sixty-nine"), (4124, "four thousand one hundred twenty-four"), (98, "ninety-eight")])
def test_numbers_are_american_with_no_and(n, text):
    assert words(n) == text


def test_ordinals():
    assert [ordinal(n) for n in (1, 2, 3, 12, 20, 21, 30)] == ["first", "second", "third", "twelfth", "twentieth", "twenty-first", "thirtieth"]


@pytest.mark.parametrize("written,said", [
    ("March 2, 1962.", "March second, nineteen sixty-two."),
    ("In 1962 he scored 100.", "In nineteen sixty-two he scored one hundred."),
    ("the 1960s", "the nineteen sixties"),
    ("He made 51.1 percent.", "He made fifty-one point one percent."),
    ("87.5% that night", "eighty-seven point five percent that night"),
    ("Attendance: 4,124.", "Attendance: four thousand one hundred twenty-four."),
    ("28 of 32", "twenty-eight of thirty-two"),
    ("They won 169-147.", "They won one hundred sixty-nine to one hundred forty-seven."),
    ("per NBA.com", "per NBA dot com"),
    ("the NBA record", "the NBA record"),
    ("Warriors PR man", "Warriors PR man"),
    ("Q1: 23", "first quarter: twenty-three"),
    ("every 3⅓ minutes", "every three and a third minutes"),
    ("46 seconds left", "forty-six seconds left"),
    ("It cost $200.", "It cost two hundred dollars."),
])
def test_script_text_becomes_natural_speech(written, said):
    assert normalize(written) == said


def test_a_large_count_is_not_read_as_a_year():
    assert normalize("He scored 1962 points.") == "He scored one thousand nine hundred sixty-two points."


def test_no_digits_reach_the_voice():
    text = "On March 2, 1962, Chamberlain made 28 of 32, 87.5 percent, for 100 of 169 in Q4. Attendance 4,124."
    assert not any(c.isdigit() for c in normalize(text))


@pytest.mark.parametrize("text", ["the NBA record", "per NBA.com", "the NCAA title", "the NFL", "Warriors PR man"])
def test_initials_are_never_spaced_apart(text):
    # "N B A" comes out as "N B" and the word "a", so initials must reach the voice whole.
    assert not re.search(r"\b[A-Z] [A-Z]\b", normalize(text))


def test_nba_is_pronounced_as_initials():
    pytest.importorskip("kokoro_onnx")
    from kokoro_onnx.tokenizer import Tokenizer
    sounds = Tokenizer().phonemize(normalize("in one NBA game"), lang="en-us")
    assert "ˈeɪ ɡ" in sounds and "ɐ ɡ" not in sounds  # ends in "ay", not the word "a"


def test_names_are_respelled_for_the_voice_only():
    assert normalize("Lou Gehrig's 47") == "Lou Gairig's forty-seven"
    assert normalize("Mark Koenig tripled") == "Mark Kaynig tripled"
    assert normalize("Tony Lazzeri") == "Tony La zairy"
    assert normalize("Hod Lisenbee", {"Lisenbee": "Lizzenbee"}) == "Hod Lizzenbee"  # research can add its own
    assert normalize("A Gehrigson") == "A Gehrigson"  # whole names only


def test_a_pronunciation_note_is_never_read_aloud():
    names = {"Stephen Gostkowski": "Stephen Gostkowski with a soft G as in Gahstkowskee", "Belichick": "Bellichick"}
    assert normalize("Gostkowski and Belichick", names) == "Gostkowski and Bellichick"
    assert normalize("Stephen Gostkowski kicked it.", names) == "Stephen Gostkowski kicked it."
