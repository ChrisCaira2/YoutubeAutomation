import asyncio
import random

import pytest

from studio import forecast
from studio.agents.live import RESERVE
from studio.api import build
from studio.media import slide_writer
from studio.pipeline import ROUTES


def row(key, fmt="long", manual=True):
    return next(r for r in forecast.steps(fmt, manual) if r["key"] == key)


@pytest.mark.parametrize("fmt", ["long", "short"])
def test_every_range_is_ordered(fmt):
    for r in forecast.steps(fmt):
        assert r["low"] <= r["expected"] <= r["high"]


def test_research_forecast_covers_the_deeper_setup():
    r = row("brief")
    assert 0.25 <= r["expected"] <= 0.45  # job #7 cost $0.16 with three searches and reads; this setup has five and six
    assert r["low"] < r["expected"] < r["high"]


def test_budget_reserves_cover_the_forecast_high():
    # The cap check must never allow a step the forecast says could cost more.
    assert row("brief")["high"] <= RESERVE["brief"]
    assert row("script")["high"] <= RESERVE["script"]
    assert row("qa_script", manual=False)["high"] <= RESERVE["qa_report"]
    assert row("storyboard")["high"] <= slide_writer.RESERVE_USD


def test_manual_review_is_free_and_mentions_the_agent_cost():
    assert row("qa_script")["expected"] == 0
    assert "QA agent would add" in row("qa_script")["note"]
    assert row("qa_script", manual=False)["expected"] > 0


def test_totals_separate_what_is_built_from_guesses():
    f = forecast.forecast("long")
    assert f["through_review"]["expected"] == pytest.approx(row("brief")["expected"] + row("script")["expected"], abs=0.01)
    assert f["full_video"]["expected"] > f["through_review"]["expected"]
    assert all(r["basis"] == forecast.GUESS for r in f["steps"] if not r["built"] and r["expected"] > 0)


def test_short_costs_less_than_long():
    assert forecast.forecast("short")["through_review"]["expected"] < forecast.forecast("long")["through_review"]["expected"]


def test_every_pipeline_step_has_a_forecast():
    keys = {r["key"] for r in forecast.steps()}
    for route in ROUTES.values():
        if route.produces != "qa_report":
            assert route.produces in keys
    assert {"qa_script", "qa_video"} <= keys


def test_mock_run_reports_the_forecast():
    random.seed(1)
    sr = build(":memory:", speed=400.0)
    sr.db.set_setting("mock_feed", False)
    job = sr.create_job(1, "long")

    async def run():
        loop = asyncio.create_task(sr.run())
        try:
            async def wait():
                while sr.db.get_job(job["id"])["stage"] != "awaiting_approval":
                    await asyncio.sleep(0.02)
            await asyncio.wait_for(wait(), 20)
        finally:
            loop.cancel()
            for t in list(sr.inflight.values()):
                t.cancel()
            await asyncio.sleep(0)

    asyncio.run(run())
    research = sr.db.one("SELECT SUM(cost_usd) AS c FROM events WHERE job_id = ? AND agent = 'research'", (job["id"],))["c"]
    assert research == pytest.approx(row("brief")["expected"], abs=0.001)
    assert sr.db.one("SELECT COUNT(*) AS n FROM events WHERE job_id = ? AND type = 'cost' AND message NOT LIKE '%nothing charged%'", (job["id"],))["n"] == 0
