"""What a real run should cost, step by step, based on the real runs so far.

Mock runs report these numbers instead of charging anything. Update the token
assumptions here whenever a real run measures something new.
"""
from types import SimpleNamespace

from .llm import MODEL_FAST, MODEL_RESEARCH, MODEL_STRONG, usage_cost

AS_OF = "2026-11-03"

# How much to trust a number.
BASED_ON_RUN = "Real run, repriced"  # tokens measured in a real run, priced for the current model
ESTIMATE = "Estimate, untested"  # built, but this setup hasn't run for real yet
GUESS = "Rough guess, not built"  # the step doesn't exist yet
FREE = "Free"


def _cost(model: str, write: int = 0, read: int = 0, input: int = 0, output: int = 0, searches: int = 0) -> float:
    usage = SimpleNamespace(
        input_tokens=input, output_tokens=output, cache_creation_input_tokens=write, cache_read_input_tokens=read,
        server_tool_use=SimpleNamespace(web_search_requests=searches),
    )
    return usage_cost(model, usage)[0]


def _research() -> dict:
    # Three searches and reads measured $0.16 on job #7; these scale that to five searches and six reads.
    return {
        "low": _cost(MODEL_RESEARCH, write=35_000, read=180_000, output=7_000, searches=4),
        "expected": _cost(MODEL_RESEARCH, write=55_000, read=280_000, output=10_000, searches=5),
        "high": _cost(MODEL_RESEARCH, write=85_000, read=500_000, output=14_000, searches=5),
    }


def _script(fmt: str) -> dict:
    # A 980-word script measured $0.15 on job #7 at about 6k tokens; 1,400-1,700 words with a fuller brief runs longer.
    if fmt == "short":
        return {
            "low": _cost(MODEL_STRONG, write=5_000, output=1_500),
            "expected": _cost(MODEL_STRONG, write=5_000, output=3_000),
            "high": _cost(MODEL_STRONG, write=5_000, output=5_000),
        }
    return {
        "low": _cost(MODEL_STRONG, write=11_000, output=8_000),
        "expected": _cost(MODEL_STRONG, write=11_000, output=11_000),
        "high": _cost(MODEL_STRONG, write=11_000, output=20_000),
    }


def _qa_agent() -> dict:
    return {
        "low": _cost(MODEL_STRONG, write=12_000, output=2_000),
        "expected": _cost(MODEL_STRONG, write=12_000, output=4_000),
        "high": _cost(MODEL_STRONG, write=12_000, output=8_000),
    }


def _rough(low: float, expected: float, high: float, fmt: str) -> dict:
    scale = 0.5 if fmt == "short" else 1.0
    return {"low": low * scale, "expected": expected * scale, "high": high * scale}


ZERO = {"low": 0.0, "expected": 0.0, "high": 0.0}


def steps(fmt: str = "long", manual_review: bool = True) -> list[dict]:
    """Every paid or free step of one video, in pipeline order."""
    qa_note = "You review the script yourself." if manual_review else "The QA agent reviews the script."
    if manual_review:
        agent = _qa_agent()
        qa_note += f" The QA agent would add about ${agent['low']:.2f}-${agent['high']:.2f}."
    rows = [
        ("brief", "Research", "research", MODEL_RESEARCH, _research(), BASED_ON_RUN, True,
         "Deeper since 2026-11-03: five searches and six page reads. The shallower version cost $0.16 on job #7."),
        ("script", "Script", "script", MODEL_STRONG, _script(fmt), ESTIMATE, True,
         "A longer script at low effort. A 980-word one cost $0.15 on job #7; medium effort was cut off at $0.67."),
        ("qa_script", "Script review (QA-1)", "qa", None if manual_review else MODEL_STRONG,
         ZERO if manual_review else _qa_agent(), FREE if manual_review else ESTIMATE, True, qa_note),
        ("storyboard", "Slide design", "studio", MODEL_FAST, _rough(0.015, 0.025, 0.035, fmt), BASED_ON_RUN, True, "Haiku designs each analysis slide. The last real run, 87 chart-heavy slides, cost $0.024."),
        ("render", "Visuals, voice, captions, video", "studio", None, ZERO, FREE, True, "Runs on your Mac with free tools."),
        ("qa_video", "Video review (QA-2)", "qa", None, ZERO, FREE, True, "Measured checks on the file, with no Claude call."),
        ("package", "Titles, thumbnails, description", "packaging", MODEL_RESEARCH, _rough(0.02, 0.04, 0.07, fmt), ESTIMATE, True, "Sonnet writes the words at low effort. Thumbnails are drawn free. Not yet run for real."),
        ("export", "Export files", "publisher", None, ZERO, FREE, False, "You upload it yourself for now."),
        ("analytics_snapshot", "Collect numbers", "publisher", None, ZERO, FREE, False, "The YouTube API has a free daily quota."),
        ("lessons", "Update the Playbook", "research", None, _rough(0.005, 0.01, 0.05, fmt), GUESS, False, "Arrives in Phase 5."),
    ]
    return [
        {"key": key, "label": label, "agent": agent, "model": model, "basis": basis, "built": built, "note": note,
         "low": round(c["low"], 4), "expected": round(c["expected"], 4), "high": round(c["high"], 4)}
        for key, label, agent, model, c, basis, built, note in rows
    ]


def _total(rows: list[dict]) -> dict:
    return {k: round(sum(r[k] for r in rows), 2) for k in ("low", "expected", "high")}


def forecast(fmt: str = "long", manual_review: bool = True) -> dict:
    rows = steps(fmt, manual_review)
    return {
        "format": fmt,
        "as_of": AS_OF,
        "steps": rows,
        "through_review": _total([r for r in rows if r["key"] in ("brief", "script", "qa_script")]),
        "full_video": _total(rows),
        "excludes": "A rewrite you request costs about one more Script step. Three Shorts from a finished long-form reuse its research: about $0.10-$0.12 to write them, then each runs from Slide design on.",
    }


def expected(produces: str, fmt: str, stage: str, manual_review: bool = True) -> float:
    """The forecast for the step a mock agent is playing."""
    key = {"scripted": "qa_script", "rendered": "qa_video"}.get(stage, produces) if produces == "qa_report" else produces
    return next(r["expected"] for r in steps(fmt, manual_review) if r["key"] == key)
