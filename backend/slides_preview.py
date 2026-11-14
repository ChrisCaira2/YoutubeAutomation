"""Draw slides from the saved Wilt beats, with Haiku designing them.

    ../.venv/bin/python slides_preview.py --dry    # free: counts tokens only
    ../.venv/bin/python slides_preview.py          # calls Haiku (about a cent), logged to job 2
    ../.venv/bin/python slides_preview.py --reuse  # free: redraw from the last saved Haiku answer
"""
import argparse
import asyncio
import json
from collections import Counter

import anthropic
from PIL import Image

from studio import artifacts, config, media  # noqa: F401
from studio.config import MEDIA_DIR
from studio.db import DB
from studio.events import EventBus
from studio.llm import MODEL_FAST, Claude, api_schema
from studio.media import slide_writer, slides, storyboard, visuals  # noqa: F401

TITLE = "Wilt Chamberlain scores 100 points in one game"
JOB_ID = 2


def inputs(db):
    beats = json.loads((MEDIA_DIR / f"job-{JOB_ID}/raw/script-partial-beats.json").read_text())
    for b in beats:
        b["est_seconds"] = round(len(b["narration"].split()) / 2.5, 1)
    script = {"format": "long", "beats": beats}
    return script, artifacts.latest(db, JOB_ID, "brief"), storyboard.plan(script, TITLE, visuals.STYLE["name"])


def draw(board, out):
    (out / "slides").mkdir(parents=True, exist_ok=True)
    for old in list((out / "slides").glob("*.png")) + list(out.glob("sheet-*.png")):
        old.unlink()
    sheet, pages = [], []
    for i, f in enumerate(board["frames"], 1):
        name = f"slide-{i:03}.png"
        visuals.render(f["mode"], (1920, 1080), f["spec"], out / "slides" / name)
        sheet.append({**f, "file": name})
        pages.append(Image.open(out / "slides" / name).convert("RGB").resize((1280, 720)))
    pages[0].save(out / "wilt-slides.pdf", save_all=True, append_images=pages[1:], resolution=96)
    visuals.contact_sheet(sheet, out / "slides", out / "all-slides.png", per_row=8)
    for n in range(0, len(sheet), 30):
        visuals.contact_sheet(sheet[n:n + 30], out / "slides", out / f"sheet-{n // 30 + 1}.png", per_row=5)
    (out / "slides.json").write_text(json.dumps(sheet, indent=1, ensure_ascii=False))
    print(len(sheet), "slides", dict(Counter(f["mode"] for f in sheet)))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--reuse", action="store_true")
    args = ap.parse_args()
    path = str(config.ROOT / "data" / "studio-live.db")
    db = DB(path)
    bus = EventBus(db)
    script, brief, board = inputs(db)
    out = MEDIA_DIR / "wilt-slides-v2"
    if args.dry:
        system, prompt = slide_writer.build_prompt(script, brief, board, TITLE)
        client = anthropic.Anthropic()
        n = client.messages.count_tokens(model=MODEL_FAST, system=system, messages=[{"role": "user", "content": prompt}],
                                         output_config={"format": {"type": "json_schema", "schema": api_schema(slide_writer.SCHEMA)}}).input_tokens
        print(f"segments {len(board['frames'])}; input {n:,} tokens = ${n * 0.10 / 1e6:.4f}; at 15k output ${15000 * 0.5 / 1e6:.4f}; at the 32k cap ${32000 * 0.5 / 1e6:.4f}")
        return
    if args.reuse:
        raw = sorted((MEDIA_DIR / f"job-{JOB_ID}/raw").glob("slides-*.txt"))[-1]
        merged, rejected = slide_writer.apply(script, brief, board, json.loads(raw.read_text())["slides"])
        cost = 0.0
    else:
        settings = db.get_settings(config.DEFAULT_SETTINGS)
        job = db.get_job(JOB_ID)
        merged, rejected, cost = await slide_writer.write(Claude(db, bus), job, settings, script, brief, board, TITLE)
    print(f"cost ${cost:.4f}; rejected {len(rejected)}")
    for r in rejected:
        print(" ", r)
    draw(merged, out)


if __name__ == "__main__":
    asyncio.run(main())
