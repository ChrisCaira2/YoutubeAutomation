import pytest

from studio import artifacts
from studio.agents.mock import MockAgent
from studio.db import DB
from studio.events import EventBus

PRODUCED = ["brief", "script", "qa_report", "storyboard", "render", "package", "export", "analytics_snapshot", "lessons"]


@pytest.fixture
def agent():
    db = DB(":memory:")
    db.run("INSERT INTO topics (id, series, title) VALUES (1, 'Record Breakers', 'Test moment')")
    db.run("INSERT INTO jobs (id, topic_id, title, format, stage, created_at, updated_at) VALUES (1, 1, 'Test moment', 'long', 'scripted', 'x', 'x')")
    return MockAgent("qa", db, EventBus(db))


def test_every_artifact_kind_has_a_schema():
    assert set(PRODUCED) | {"asset_manifest"} == set(artifacts.kinds())


@pytest.mark.parametrize("fmt", ["long", "short"])
@pytest.mark.parametrize("kind", PRODUCED)
def test_mock_output_matches_schema(agent, kind, fmt):
    job = {**agent.db.get_job(1), "format": fmt}
    if kind in ("storyboard", "render"):
        artifacts.save(agent.db, 1, "script", getattr(agent, "_make_script")(job).artifacts["script"], "script")
    outcome = getattr(agent, f"_make_{kind}")(job)
    for k, data in outcome.artifacts.items():
        artifacts.validate(k, data)


def test_invalid_artifact_is_refused(agent):
    with pytest.raises(artifacts.InvalidArtifact, match="facts"):
        artifacts.save(agent.db, 1, "brief", {"audience": "a", "promise": "p", "angle": "x", "facts": [], "competitors": [], "hooks": ["a", "b", "c"], "package_concepts": [{"title": "t", "thumbnail_concept": "c"}]}, "research")


def test_titles_over_100_characters_are_refused(agent):
    pkg = agent._make_package(agent.db.get_job(1)).artifacts["package"]
    pkg["options"][0]["title"] = "x" * 101
    with pytest.raises(artifacts.InvalidArtifact):
        artifacts.validate("package", pkg)


def test_versions_increment(agent):
    brief = agent._make_brief(agent.db.get_job(1)).artifacts["brief"]
    assert artifacts.save(agent.db, 1, "brief", brief, "research") == 1
    assert artifacts.save(agent.db, 1, "brief", brief, "research") == 2
