"""End-to-end runs of the mock studio at high speed."""
import asyncio
import random

import pytest

from studio.api import build

FAST = 400.0


async def run_until(sr, condition, timeout=20.0):
    loop = asyncio.create_task(sr.run())
    try:
        async def wait():
            while not condition():
                await asyncio.sleep(0.02)
        await asyncio.wait_for(wait(), timeout)
    finally:
        loop.cancel()
        for t in list(sr.inflight.values()):
            t.cancel()
        await asyncio.sleep(0)


@pytest.fixture
def sr():
    random.seed(7)
    sr = build(":memory:", speed=FAST)
    sr.db.set_setting("mock_feed", False)
    return sr


def stage(sr, job_id):
    return sr.db.get_job(job_id)["stage"]


def test_job_reaches_approval_and_waits(sr):
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: stage(sr, job["id"]) == "awaiting_approval"))
    kinds = {r["kind"] for r in sr.db.all("SELECT kind FROM artifacts WHERE job_id = ?", (job["id"],))}
    assert {"brief", "script", "qa_report", "storyboard", "render", "asset_manifest", "package"} <= kinds
    assert sr.db.one("SELECT COUNT(*) AS n FROM events WHERE type = 'approval_needed'")["n"] == 1


def test_approved_job_finishes_and_learns(sr):
    job = sr.create_job(1, "short")
    asyncio.run(run_until(sr, lambda: stage(sr, job["id"]) == "awaiting_approval"))
    sr.approve(job["id"])
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["status"] == "done"))
    assert stage(sr, job["id"]) == "learned"


def test_request_changes_routes_back_with_note(sr):
    job = sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: stage(sr, job["id"]) == "awaiting_approval"))
    sr.request_changes(job["id"], "script", "Open on the 100, not the arena")
    assert stage(sr, job["id"]) == "researched"
    asyncio.run(run_until(sr, lambda: stage(sr, job["id"]) == "awaiting_approval"))
    scripts = sr.db.all("SELECT version FROM artifacts WHERE job_id = ? AND kind = 'script'", (job["id"],))
    assert len(scripts) >= 2


def test_auto_approve_after_first_n(sr):
    sr.db.set_setting("approve_first_n", 0)
    job = sr.create_job(1, "short")
    asyncio.run(run_until(sr, lambda: sr.db.get_job(job["id"])["status"] == "done"))


def test_budget_guard_pauses_studio(sr):
    sr.db.set_setting("daily_budget_usd", 0.0)
    sr.create_job(1, "long")
    asyncio.run(run_until(sr, lambda: sr.settings()["paused"] is True))
    assert sr.db.one("SELECT COUNT(*) AS n FROM artifacts")["n"] == 0


def test_approve_refused_before_ready(sr):
    job = sr.create_job(1, "long")
    with pytest.raises(ValueError):
        sr.approve(job["id"])
