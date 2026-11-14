"""Two studios side by side: The Athletics Archive and Game Day Brain (once called AI Slop), each with its own channel and data."""
import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient

from studio.api import create_app


def settings_for(workspace: str) -> dict:
    code = ("import json; from studio import config; print(json.dumps({k: str(getattr(config, k)) for k in "
            "('CHANNEL_NAME', 'VISUAL_STYLE', 'PROFESSOR_INTRO', 'DB_PATH', 'MEDIA_DIR', 'TOPICS_FILE', 'PLAYBOOK_FILE', 'STRATEGY_DIR', 'PITCH')}))")
    env = {k: v for k, v in os.environ.items() if k not in ("STUDIO_DB", "STUDIO_MEDIA_DIR")}
    done = subprocess.run([sys.executable, "-c", code], env={**env, "STUDIO_WORKSPACE": workspace, "STUDIO_MODE": "live"}, capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_the_archive_is_unchanged():
    archive = settings_for("archive")
    assert archive["CHANNEL_NAME"] == "The Athletics Archive" and archive["VISUAL_STYLE"] == "cartoon" and archive["PROFESSOR_INTRO"] == "True"
    assert archive["DB_PATH"].endswith("data/studio-live.db") and archive["PLAYBOOK_FILE"].endswith("playbook/playbook.json")


def test_ai_slop_keeps_everything_of_its_own():
    slop, archive = settings_for("slop"), settings_for("archive")
    # The owner pointed AI Slop at the science of sports in the sketch look, 2026-11-09; it still has no Professor.
    assert slop["VISUAL_STYLE"] == "sketch" and slop["PROFESSOR_INTRO"] == "False" and "Professor" not in slop["PITCH"]
    for key in ("DB_PATH", "MEDIA_DIR", "TOPICS_FILE", "PLAYBOOK_FILE", "STRATEGY_DIR"):
        assert slop[key] != archive[key], key
    for name in ("channel-strategy.md", "persona.md", "topics.md", "playbook.json"):
        assert os.path.exists(os.path.join(slop["STRATEGY_DIR"], name)), name


def test_ai_slop_playbook_has_youtube_rules_and_the_disclosure_but_not_the_sports_niche():
    slop = settings_for("slop")
    ids = {e["id"] for e in json.load(open(slop["PLAYBOOK_FILE"]))["entries"]}
    assert "slop-ai-disclosure" in ids and "owner-whole-text" in ids
    assert not {"owner-cartoon-scenes", "owner-professor-intro", "owner-team-colors"} & ids


def test_each_studio_reviews_scripts_by_its_own_idea_of_originality():
    code = "from studio.config import RECIPE; print(RECIPE['originality'])"
    env = {k: v for k, v in os.environ.items() if k not in ("STUDIO_DB", "STUDIO_MEDIA_DIR")}
    run = lambda ws: subprocess.run([sys.executable, "-c", code], env={**env, "STUDIO_WORKSPACE": ws}, capture_output=True, text=True, check=True).stdout  # noqa: E731
    assert "how unlikely" in run("archive")
    assert "how unlikely" not in run("slop") and "named research" in run("slop")


def test_an_unknown_workspace_refuses_to_start():
    done = subprocess.run([sys.executable, "-c", "import studio.config"], env={**os.environ, "STUDIO_WORKSPACE": "nope"}, capture_output=True, text=True)
    assert done.returncode != 0 and "Unknown workspace" in done.stderr


def test_the_hub_lists_both_studios_and_a_new_idea_starts_with_its_notes():
    app = create_app(":memory:", run_loop=False)
    with TestClient(app) as client:
        state = client.get("/api/state").json()
        assert [w["label"] for w in state["workspaces"]] == ["The Athletics Archive", "Game Day Brain", "GTA 6 Clip Central"]
        assert sum(w["current"] for w in state["workspaces"]) == 1
        job = client.post("/api/ideas", json={"title": "Why cats knock things off tables", "format": "short", "notes": "Playful, science-first"}).json()
        assert job["title"] == "Why cats knock things off tables" and job["format"] == "short" and job["stage"] == "idea"
        assert job["note"] == "Owner's idea: Playful, science-first"
        assert client.post("/api/ideas", json={"title": "  ", "format": "long"}).status_code == 422
        second = client.post("/api/ideas", json={"title": "Another", "format": "long"}).json()
        assert second["topic_id"] == job["topic_id"] + 1 >= 1001


def test_the_command_center_can_read_this_macs_load():
    app = create_app(":memory:", run_loop=False)
    with TestClient(app) as client:
        load = client.get("/api/system").json()
    assert set(load) == {"cpu", "memory", "disk", "disk_free_gb", "image_model"}
    assert 0 <= load["disk"] <= 100 and load["cpu"] is not None
