import json
import subprocess

import numpy as np
import pytest
from PIL import Image

from studio.media import slides  # noqa: F401 (registers the layouts)
from studio.media import photos, visuals
from studio.media.assemble import clip, probe


@pytest.fixture
def folder(tmp_path):
    Image.new("RGB", (400, 600), (120, 90, 60)).save(tmp_path / "tall.jpg")
    entry = {"id": "p1", "file": "tall.jpg", "caption": "Wilt in 1962", "credit": "Photo: Someone, CC BY 3.0", "author": "Someone", "license": "CC BY 3.0",
             "source_url": "https://example.com/p", "topics": ["wilt chamberlain"], "match": ["that picture"], "max_uses": 1}
    (tmp_path / "manifest.json").write_text(json.dumps([entry]))
    return tmp_path


def board(*says):
    return {"style_bible": "s", "frames": [{"beat_id": "b1", "start": 0, "duration": 3, "mode": "statement", "prompt": "p", "motion": "still", "spec": {"say": s, "headline": "A point"}} for s in says]}


def test_photo_appears_where_the_narrator_mentions_it(folder):
    out, used = photos.assign(board("Something else.", "Back to that picture."), "Wilt Chamberlain scores 100", folder)
    assert [f["mode"] for f in out["frames"]] == ["statement", "real_photo"] and used[0]["id"] == "p1"
    assert out["frames"][1]["spec"]["credit"] == "Photo: Someone, CC BY 3.0"


def test_photo_limit_is_respected(folder):
    out, _ = photos.assign(board("that picture", "that picture"), "Wilt Chamberlain", folder)
    assert [f["mode"] for f in out["frames"]] == ["real_photo", "statement"]


def test_photo_never_appears_in_another_episode(folder):
    out, used = photos.assign(board("that picture"), "Babe Ruth hits 60", folder)
    assert out["frames"][0]["mode"] == "statement" and not used


def test_a_photo_without_a_license_record_is_refused(folder):
    data = json.loads((folder / "manifest.json").read_text())
    del data[0]["license"]
    (folder / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="license"):
        photos.library(folder)


def test_a_missing_file_is_skipped(folder):
    (folder / "tall.jpg").unlink()
    assert photos.library(folder) == []


def test_credits_text_names_author_license_and_source(folder):
    text = photos.credits_text(photos.library(folder))
    assert "Someone" in text and "CC BY 3.0" in text and "https://example.com/p" in text


@pytest.mark.parametrize("size", [(960, 540), (540, 960)])
def test_photo_slide_draws_in_both_orientations(folder, tmp_path, size):
    spec = {"photo_file": str(folder / "tall.jpg"), "caption": "Wilt in 1962", "credit": "Photo: Someone", "headline": "A point", "emphasis": "point"}
    visuals.render("real_photo", size, spec, tmp_path / "s.png")
    assert Image.open(tmp_path / "s.png").size == size


def test_real_manifest_is_complete():
    library = photos.library()
    assert {"wilt-100", "wilt-1959", "hershey-arena", "hershey-marker", "ruth-1921", "ruth-gehrig-1927"} <= {p["id"] for p in library}
    assert all(p["source_url"].startswith("https://") and "ublic domain" in p["license"] or "CC" in p["license"] for p in library)


@pytest.mark.parametrize("quality", ["preview", "final"])
@pytest.mark.parametrize("seed", [2, 3, 8, 10, 11])
def test_clips_hold_perfectly_still(tmp_path, quality, seed):
    # Real picture-like detail: noise is what made the old encoder pulse every dozen frames. Seeded, and several
    # seeds, so no one lucky image decides it (the unseeded noise changed with whatever ran before, 2026-11-12).
    noise = np.clip(np.random.default_rng(seed).normal(128, 60, (360, 640)), 0, 255).astype(np.uint8)
    Image.fromarray(noise).convert("RGB").save(tmp_path / "f.png")
    clip(tmp_path / "f.png", 2.0, (640, 360), tmp_path / "c.mp4", quality)
    assert probe(tmp_path / "c.mp4")["fps"] == 30
    # The frames themselves, compared exactly. ffmpeg's signalstats can't be trusted here: on a stream with
    # B-frames it compares against the wrong earlier frame and reports jumps of 3-10 in a clip that never moves.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp_path / "c.mp4"), "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 360, 640).astype(np.int16)
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    assert len(frames) == 60 and diffs.max() < 0.5


def test_sideways_phone_photo_is_turned_upright(tmp_path):
    img = Image.new("RGB", (400, 200), (200, 50, 50))
    exif = Image.Exif()
    exif[0x0112] = 6  # stored rotated 90 degrees
    img.save(tmp_path / "phone.jpg", exif=exif)
    out = tmp_path / "s.png"
    visuals.render("real_photo", (960, 540), {"photo_file": str(tmp_path / "phone.jpg"), "caption": "c", "credit": "Photo", "headline": "h"}, out)
    drawn = Image.open(out).convert("RGB")
    red = [(x, y) for x in range(0, 960, 4) for y in range(0, 540, 4) if drawn.getpixel((x, y))[0] > 150 and drawn.getpixel((x, y))[1] < 90]
    assert max(y for _, y in red) - min(y for _, y in red) > max(x for x, _ in red) - min(x for x, _ in red)  # taller than wide
