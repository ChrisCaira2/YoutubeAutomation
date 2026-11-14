"""The clipper's command line. Run from backend/:  ../.venv/bin/python -m clipper <command>   (or ./run.sh clip <command>)

  ingest URL_OR_FILE [--creator NAME] [--start 2:31:57] [--length 30m]
                                        a VOD (or part of one), a live stream (records until it ends) or a local file
  watch                                 record watched creators when they go live with GTA
  follow --source ID                    clip a source as it records: transcribe, find, judge and edit each new piece
  transcribe [--source ID] [--follow]   words with times for every piece not yet done
  detect [--source ID] [--follow]       find moments from the free signals (no Claude)
  judge --source ID                     Claude picks the clips, cuts them on word boundaries and titles them
  candidates --source ID [--all]        the ranked list (also saved as candidates.json beside the source)
  edit [--source ID] [--moment ID]      picks become vertical clips (media/clips/out)
  sweep                                 sources fully clipped a week ago go to the Trash
  spend                                 Claude spend this month against the cap
  creator add URL [--name N] [--permission permitted|unknown|refused] [--watch]
  creator list
  status                                sources and how far each has got
"""
import argparse
import sys
import time

import json

from . import detect, edit, ingest, judge, settings, sweep, transcribe
from .db import DB, now


STALE_RECORDER_SECONDS = 300  # a recorder silent this long has died (it checks in every few seconds)


def follow(cfg: dict, db: DB, source_id: int, log) -> int:
    """Clip a source as it arrives: each new piece is transcribed, searched, judged and edited while the next records.

    Stops once the recording has ended and everything in it is done."""
    made = 0
    while True:
        db.set_source(source_id, followed_at=now())  # so the hub's automation leaves this one to us
        transcribe.run(cfg, db, source_id, log)
        detect.run(cfg, db, source_id, log)
        if db.candidates(source_id, "found"):
            judge.run(cfg, db, source_id, log=log)
        made += edit.run(cfg, db, source_id, log)
        source = db.source(source_id)
        if source["status"] == "recording" and not any(s["id"] == source_id for s in db.live(STALE_RECORDER_SECONDS)):
            log and log.warning("Source %s's recorder stopped checking in: finishing what was recorded.", source_id)
            source = db.set_source(source_id, status="ready", duration=db.length(source_id))
        if source["status"] in ("ready", "error") and not db.pending_segments(source_id) and not db.candidates(source_id, "found"):
            return made
        time.sleep(cfg["ingest"]["live_poll_seconds"] * 6)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipper", description="GTA 6 clipper")
    parser.add_argument("--config", help="another config.toml")
    parser.add_argument("--dry-run", action="store_true", help="do everything except upload")
    parser.add_argument("--any-game", action="store_true", help="let Claude pick moments that aren't GTA (for test runs)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("target")
    p.add_argument("--creator")
    p.add_argument("--start", help="take a VOD from here: 2:31:57 or 02h31m57s (a link's ?t= works too)")
    p.add_argument("--length", help="and only this much of it: 30m, 1h or 1:30:00")
    p.add_argument("--minutes", type=float, help="a live stream: stop recording after this many minutes")
    p.add_argument("--follow", action="store_true", help="a live stream: clip it as it records")
    sub.add_parser("watch")
    p = sub.add_parser("follow")
    p.add_argument("--source", type=int, required=True)
    p = sub.add_parser("transcribe")
    p.add_argument("--source", type=int)
    p.add_argument("--follow", action="store_true")
    p = sub.add_parser("detect")
    p.add_argument("--source", type=int)
    p.add_argument("--follow", action="store_true")
    p = sub.add_parser("judge")
    p.add_argument("--source", type=int, required=True)
    p = sub.add_parser("candidates")
    p.add_argument("--source", type=int, required=True)
    p.add_argument("--all", action="store_true", help="include the moments Claude passed on")
    p = sub.add_parser("edit")
    p.add_argument("--source", type=int)
    p.add_argument("--moment", type=int, help="one moment, by its id in the candidates list")
    sub.add_parser("sweep")
    sub.add_parser("spend")
    p = sub.add_parser("creator")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("url", nargs="?")
    p.add_argument("--name")
    p.add_argument("--permission", choices=["permitted", "unknown", "refused"])
    p.add_argument("--watch", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args(argv)

    cfg = settings.load(args.config)
    if args.any_game:
        cfg["judge"]["require_gta"] = False
    log = settings.logger(cfg)
    db = DB(cfg["paths"]["database"])
    if args.command == "ingest":
        source = ingest.ingest(cfg, db, args.target, args.creator, log, ingest.seconds(args.start), ingest.seconds(args.length),
                               args.minutes * 60 if args.minutes else None, (["--any-game"] if args.any_game else []) if args.follow else None)
        print(f"source {source['id']}: {source['status']}")
    elif args.command == "watch":
        ingest.watch(cfg, db, log)
    elif args.command == "follow":
        print(f"{follow(cfg, db, args.source, log)} clips made")
    elif args.command == "transcribe":
        transcribe.follow(cfg, db, log) if args.follow else print(f"{transcribe.run(cfg, db, args.source, log)} pieces transcribed")
    elif args.command == "detect":
        if args.follow:
            detect.follow(cfg, db, log)
        for row in ([{"id": args.source}] if args.source else db.all("SELECT id FROM sources")):
            print(f"source {row['id']}: {detect.run(cfg, db, row['id'], log)} new moments")
    elif args.command == "judge":
        print(f"{judge.run(cfg, db, args.source, log=log)} moments judged. This month: ${db.spent_this_month():.4f} of ${cfg['budget']['monthly_usd']:.2f}.")
    elif args.command == "candidates":
        source = db.source(args.source)
        for m in json.loads(judge.export(cfg, db, args.source).read_text()):
            if m["status"] != "judged" and not args.all:
                continue
            when = f"{ingest.clock(source['window_start'] + m['start'])}, {m['length']:.0f} s" if m["start"] is not None else f"peak {ingest.clock(source['window_start'] + m['peak'])}"
            print(f"{m['id']:>4}  {m['status']:<7} {m['score'] if m['score'] is not None else '-':>5}  {when:<16} {m['title'] or ''}")
            if m["reason"]:
                print(f"      {m['reason']}")
    elif args.command == "edit":
        if args.moment:
            clip = edit.edit(cfg, db, args.moment, log)
            print(f"{clip['path']} ({clip['layout']}, {clip['duration']:.1f} s, {clip['lufs']} LUFS)")
        else:
            print(f"{edit.run(cfg, db, args.source, log)} clips edited")
    elif args.command == "sweep":
        print(f"{sweep.run(cfg, db, log)} sources moved to the Trash")
    elif args.command == "spend":
        print(f"This month: ${db.spent_this_month():.4f} of ${cfg['budget']['monthly_usd']:.2f}.")
    elif args.command == "creator" and args.action == "add":
        if not args.url:
            parser.error("creator add needs the channel's URL")
        platform = ingest.platform_of(args.url)
        name = args.name or args.url.rstrip("/").rsplit("/", 1)[-1].lstrip("@")
        who = db.creator(name, platform, args.url)
        who = db.set_creator(who["id"], **{k: v for k, v in {"permission": args.permission, "watch": 1 if args.watch else None}.items() if v is not None})
        print(f"creator {who['id']}: {who['name']} on {who['platform']}, permission {who['permission']}, {'watched' if who['watch'] else 'not watched'}")
    elif args.command == "creator":
        for c in db.all("SELECT * FROM creators ORDER BY name"):
            print(f"{c['id']:>3}  {c['name']:<24} {c['platform']:<8} {c['permission']:<10} {'watched' if c['watch'] else ''}")
    elif args.command == "status":
        for s in db.all("SELECT s.*, c.name AS creator FROM sources s LEFT JOIN creators c ON c.id = s.creator_id ORDER BY s.id"):
            pieces = db.segments(s["id"])
            done = sum(p["status"] == "transcribed" for p in pieces)
            chat = db.one("SELECT COUNT(*) AS n FROM chat WHERE source_id = ?", (s["id"],))["n"]
            print(f"{s['id']:>4}  {s['kind']:<4} {s['status']:<11} {done}/{len(pieces)} transcribed  {chat} chat  {s['creator']}: {s['title']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, ingest.NotLive, judge.BudgetExceeded) as exc:
        sys.exit(f"clipper: {exc if not isinstance(exc, ingest.NotLive) else f'{exc} is not live right now'}")
