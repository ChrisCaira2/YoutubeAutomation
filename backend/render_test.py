"""Free production test using saved script beats. No database, no Claude, nothing charged.

    ../.venv/bin/python render_test.py --beats 6 --voice am_michael
    ../.venv/bin/python render_test.py --format short
"""
import argparse
import json
import time
from pathlib import Path

from studio.config import MEDIA_DIR
from studio.media import produce, qa

BEATS_FILE = MEDIA_DIR / "job-2" / "raw" / "script-partial-beats.json"
TITLE = "Wilt Chamberlain scores 100 points in one game"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beats", type=int, default=6)
    ap.add_argument("--voice", default="am_michael")
    ap.add_argument("--format", choices=["long", "short"], default="long")
    ap.add_argument("--quality", choices=["preview", "final"], default="preview")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    beats = json.loads(BEATS_FILE.read_text())[: args.beats]
    if args.format == "short":  # layout test only: short lines taken from the recovered script
        beats = [dict(b, narration=" ".join(b["narration"].split()[:14])) for b in beats[:4]]
    for b in beats:
        b["est_seconds"] = round(len(b["narration"].split()) / 2.5, 1)
    script = {"format": args.format, "beats": beats, "target_seconds": sum(b["est_seconds"] for b in beats)}
    folder = Path(args.out) if args.out else MEDIA_DIR / f"test-wilt/{args.format}-{args.voice}"
    folder.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    board = produce.make_storyboard(script, TITLE, folder)
    print(f"storyboard: {len(board['frames'])} frames in {time.time() - t0:.1f}s; modes: {sorted({f['mode'] for f in board['frames']})}")
    t1 = time.time()
    result = produce.render_video(script, board, folder, args.quality, args.voice, progress=lambda m: print(" ", m))
    r = result["render"]
    print(f"render: {r['width']}x{r['height']} {r['duration_seconds']}s video in {time.time() - t1:.1f}s -> {r['path']}")
    report = qa.review(args.format, Path(r["path"]), args.quality, result["timeline"], result["words"], script, result["asset_manifest"])
    print("QA-2:", "PASS" if report["passed"] else "FAIL")
    for c in report["checks"]:
        print(f"  {'ok  ' if c['passed'] else 'FAIL'} {c['name']}: {c['note']}")


if __name__ == "__main__":
    main()
