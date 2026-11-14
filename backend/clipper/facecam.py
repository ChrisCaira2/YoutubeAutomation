"""Where the streamer's camera sits in a source, found once per source (layouts change between streams).

Claude looks at a few frames and gives the camera's rough box. Code then snaps each side onto the camera's
border: across many frames the room in the camera barely changes while the game around it keeps moving,
so the border is where that steps.
"""
import base64
import io
import json

import anthropic
import numpy as np
from PIL import Image

from studio.llm import api_schema, usage_cost

from . import judge
from .db import DB

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facecam", "overlay", "left", "top", "right", "bottom", "note"],
    "properties": {
        "facecam": {"type": "boolean"},
        "overlay": {"type": "string", "enum": ["webcam", "avatar", "none"]},
        "left": {"type": "number"}, "top": {"type": "number"}, "right": {"type": "number"}, "bottom": {"type": "number"},
        "note": {"type": "string"},
    },
}
PROMPT = """These frames come from one livestream, at different times. Is there a webcam overlay showing the streamer
(a facecam) in the same place in every gameplay frame? If so, give the box around the whole camera picture as shares
of the frame's width and height, from 0 to 1 (left, top, right, bottom). Leave out the chat, alerts, follower counts
and game HUD. Say whether it's a webcam (a framed camera picture) or an avatar (an animated character with no frame
around it). If there's no facecam, or the frames are the camera full screen, say facecam false, overlay none, and give zeros.
Note in a few words what you saw."""


def _times(length: float, n: int) -> list[float]:
    return [length * (i + 1) / (n + 1) for i in range(n)]


def snap(box: list[float], frames: list[np.ndarray], cfg: dict) -> list[float]:
    """Move each side of a rough box onto the strongest steady edge near it."""
    f = cfg["facecam"]
    # How much each pixel changes over time. Inside the camera the room holds still; the game around it doesn't.
    # The border is where that steps, which sharp edges inside the camera picture (a shelf, a door) never do.
    stack = np.stack(frames)
    moving = np.std(stack, axis=0)
    h, w = moving.shape
    band = 3
    gx = np.zeros((h, w))
    gy = np.zeros((h, w))
    for k in range(1, band + 1):
        gx[:, band:w - band] += np.abs(moving[:, band + k - 1:w - band + k - 1] - moving[:, band - k:w - band - k])
        gy[band:h - band, :] += np.abs(moving[band + k - 1:h - band + k - 1, :] - moving[band - k:h - band - k, :])
    left, top, right, bottom = box
    rows, cols = slice(int(top * h), max(int(bottom * h), int(top * h) + 1)), slice(int(left * w), max(int(right * w), int(left * w) + 1))

    def side(value: float, size: int, profile) -> float:
        if value <= f["edge_margin"]:
            return 0.0
        if value >= 1 - f["edge_margin"]:
            return 1.0
        reach = int(f["snap_reach"] * size)
        at = int(value * size)
        lo, hi = max(at - reach, 1), min(at + reach, size - 2)
        scores = np.array([profile(i) for i in range(lo, hi + 1)])
        best = int(scores.argmax())
        if scores[best] < f["snap_strength"] * (np.median(scores) + 1e-6):
            return value  # no clear border: keep Claude's line
        return (lo + best + 0.5) / size

    left = side(left, w, lambda x: gx[rows, x].mean())
    right = side(right, w, lambda x: gx[rows, x].mean())
    top = side(top, h, lambda y: gy[y, cols].mean())
    bottom = side(bottom, h, lambda y: gy[y, cols].mean())
    return [round(v, 4) for v in (left, top, right, bottom)]


def find(cfg: dict, db: DB, source_id: int, client: anthropic.Anthropic | None = None, log=None) -> dict:
    """The source's facecam box, worked out the first time it's needed and kept."""
    source = db.source(source_id)
    if source["facecam"]:
        return json.loads(source["facecam"])
    f = cfg["facecam"]
    content = []
    for t in _times(db.length(source_id), f["claude_frames"]):
        shot = judge.frame(db, source_id, t, f["frame_width"])
        if shot:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(shot).decode()}})
    content.append({"type": "text", "text": PROMPT})
    worst = judge.reserve(cfg, PROMPT, images=len(content) * 4)  # full-width frames cost about four small ones
    if db.spent_this_month() + worst > cfg["budget"]["monthly_usd"]:
        raise judge.BudgetExceeded(f"Finding the facecam could cost up to ${worst:.2f}, past this month's ${cfg['budget']['monthly_usd']:.2f} cap.")
    client = client or anthropic.Anthropic()
    response = client.messages.create(model=cfg["judge"]["model"], max_tokens=1000, messages=[{"role": "user", "content": content}],
                                      output_config={"format": {"type": "json_schema", "schema": api_schema(SCHEMA)}})
    db.add_spend("facecam", source_id, response.model, response.usage.input_tokens, response.usage.output_tokens, usage_cost(response.model, response.usage)[0])
    answer = json.loads("".join(b.text for b in response.content if b.type == "text"))
    box = [answer[k] for k in ("left", "top", "right", "bottom")]
    found = {"box": None, "by": "claude", "note": answer["note"]}
    if answer["facecam"] and answer["overlay"] == "avatar" and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1:
        found = {"box": box, "by": "claude (an avatar has no border to snap to)", "note": answer["note"]}
    elif answer["facecam"] and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1:
        grays = []
        for t in _times(db.length(source_id), f["snap_frames"]):
            shot = judge.frame(db, source_id, t, 640)
            if shot:
                grays.append(np.asarray(Image.open(io.BytesIO(shot)).convert("L"), dtype=np.float32))
        found = {"box": snap(box, grays, cfg) if len(grays) >= 3 else box, "by": "claude, snapped to the border", "claude": box, "note": answer["note"]}
    db.set_source(source_id, facecam=json.dumps(found))
    log and log.info("Source %s facecam: %s (%s)", source_id, found["box"], answer["note"])
    return found
