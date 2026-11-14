"""Stage 1: get a stream or video onto disk, in pieces the later stages can pick up one at a time.

VODs download with yt-dlp, live streams record with streamlink into finished pieces while the stream
is still going, and chat comes from chat-downloader (Twitch and YouTube; Kick's chat isn't supported).
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from .db import DB

PLATFORMS = {"twitch.tv": "twitch", "youtube.com": "youtube", "youtu.be": "youtube", "kick.com": "kick"}
CHANNEL_PAGES = {"twitch": "https://www.twitch.tv/{}", "kick": "https://kick.com/{}"}  # yt-dlp gives a VOD's uploader, not their channel link
CHAT_PLATFORMS = {"twitch", "youtube"}
# Twitch's public API has no chat replay (2026-11-12), and its private one isn't ours to use: Twitch VODs go without chat.
REPLAY_PLATFORMS = {"youtube"}
BIN = Path(sys.executable).parent  # streamlink and yt-dlp live in the project's .venv


class NotLive(Exception):
    """The channel isn't streaming right now."""


def platform_of(target: str) -> str:
    if Path(target).expanduser().exists():
        return "file"
    host = urlparse(target if "://" in target else f"https://{target}").netloc.lower().removeprefix("www.").removeprefix("m.")
    for domain, platform in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return platform
    raise ValueError(f"Not a Twitch, YouTube or Kick link, or a file on this Mac: {target}")


def seconds(text: str | float | None) -> float | None:
    """A time as typed or as Twitch links write it: 9117, "2:31:57", "02h31m57s" or "45m"."""
    if text is None or isinstance(text, (int, float)):
        return text
    text = str(text).strip().lower()
    if ":" in text:
        return float(sum(float(part) * 60 ** i for i, part in enumerate(reversed(text.split(":")))))
    units = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", text)
    if not units or not any(units.groups()):
        raise ValueError(f"Not a time: {text}")
    h, m, s = (float(g or 0) for g in units.groups())
    return h * 3600 + m * 60 + s


def link_start(url: str) -> float | None:
    """Where a link with ?t= (Twitch) or &t= (YouTube) points into the video."""
    found = re.search(r"[?&]t=([0-9hms:.]+)", url)
    return seconds(found.group(1)) if found else None


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"].get("duration") or 0)


def pieces(duration: float, seconds: float) -> list[tuple[float, float]]:
    """(start, length) for each piece of a file. A last piece under a quarter length joins the one before."""
    out, t = [], 0.0
    while t < duration - 0.01:
        out.append((t, min(seconds, duration - t)))
        t += seconds
    if len(out) > 1 and out[-1][1] < seconds / 4:
        start, length = out.pop()
        out[-1] = (out[-1][0], out[-1][1] + length)
    return out


def probe(url: str, platform: str | None = None) -> dict:
    """What yt-dlp knows about a link without downloading it. Raises NotLive for an offline channel."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        if re.search(r"not currently live|is offline|not live|will begin|Premieres in", str(exc), re.I):
            raise NotLive(url) from exc
        raise
    page = CHANNEL_PAGES.get(platform or platform_of(url))
    return {
        "id": str(info["id"]),
        "title": info.get("title") or info.get("description") or "",
        "live": bool(info.get("is_live")),
        "creator": info.get("uploader") or info.get("channel") or info.get("uploader_id") or "unknown",
        "channel_url": info.get("channel_url") or info.get("uploader_url") or (page.format(info["uploader_id"]) if page and info.get("uploader_id") else url),
        "page": info.get("webpage_url") or url,
        "duration": info.get("duration"),
    }


def ingest(cfg: dict, db: DB, target: str, creator: str | None = None, log=None, start: float | None = None, length: float | None = None,
           max_seconds: float | None = None, follow: list[str] | None = None) -> dict:
    """Add a VOD, live stream or local file. Doing it again with the same video returns what's already there.

    A VOD can be taken in part: from `start` (or the link's ?t=) for `length` seconds, to spare the disk."""
    platform = platform_of(target)
    if platform == "file":
        return add_file(cfg, db, Path(target).expanduser().resolve(), creator, log)
    info = probe(target, platform)
    start = start if start is not None else link_start(target)
    window = None
    if not info["live"] and (start or length):
        end = min(filter(None, [(start or 0) + length if length else None, info["duration"]]), default=None)
        window = (start or 0, end)
    key = f"{platform}:{info['id']}" + (f"@{window[0]:.0f}-{window[1]:.0f}" if window else "")
    known = db.source_by_key(key)
    if known and info["live"] and known["status"] == "ready":  # recording the same broadcast again: a new recording of its own
        n = 2
        while db.source_by_key(f"{key}#{n}"):
            n += 1
        key, known = f"{key}#{n}", None
    if known and known["status"] != "error":
        log and log.info("Already ingested as source %s (%s).", known["id"], known["status"])
        return known
    who = db.creator(creator or info["creator"], platform, info["channel_url"])
    fields = dict(creator_id=who["id"], platform=platform, url=info["page"], title=info["title"], window_start=window[0] if window else 0,
                  window_end=window[1] if window else None)
    if known:
        source = db.set_source(known["id"], status="recording" if info["live"] else "downloading", error=None, stop_requested=0, **fields)
    else:
        source = db.add_source(key=key, kind="live" if info["live"] else "vod", status="recording" if info["live"] else "downloading", **fields)
    if who["permission"] != "permitted":
        log and log.warning("%s hasn't given permission to clip their streams. Clips will carry a warning.", who["name"])
    if info["live"]:
        if follow is not None:  # clip it as it records, in a process of its own (extra options, such as --any-game, go along)
            subprocess.Popen([sys.executable, "-m", "clipper", *follow, "follow", "--source", str(source["id"])], cwd=Path(__file__).resolve().parents[1])
        return record(cfg, db, source, log, max_seconds)
    return download(cfg, db, source, log)


def add_file(cfg: dict, db: DB, path: Path, creator: str | None, log=None) -> dict:
    key = f"file:{path}"
    known = db.source_by_key(key)
    if known:
        return known
    who = db.creator(creator or "Local files", "file", f"local:{creator or 'files'}")
    duration = ffprobe_duration(path)
    source = db.add_source(key=key, creator_id=who["id"], platform="file", kind="file", url=str(path), title=path.stem,
                           status="ready", path=str(path), duration=duration)
    for idx, (start, length) in enumerate(pieces(duration, cfg["ingest"]["segment_seconds"])):
        db.add_segment(source["id"], idx, path, start, start, length)
    log and log.info("Added %s: %.0f s in %d pieces.", path.name, duration, len(db.segments(source["id"])))
    return db.source(source["id"])


def clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02}:{t % 60:02}"


def folder(cfg: dict, source: dict) -> Path:
    out = cfg["paths"]["media"] / "sources" / f"{source['id']:05}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def download(cfg: dict, db: DB, source: dict, log=None) -> dict:
    """A VOD at no more than the configured height, then its chat replay."""
    import yt_dlp

    out = folder(cfg, source)
    height = cfg["ingest"]["max_height"]
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "outtmpl": str(out / "source.%(ext)s"),
            "format": f"bv*[height<={height}]+ba/b[height<={height}]/b", "merge_output_format": "mp4"}
    if source["window_end"]:
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(source["window_start"], source["window_end"])])
    log and log.info("Downloading source %s: %s%s", source["id"], source["title"],
                     f" ({clock(source['window_start'])} to {clock(source['window_end'])})" if source["window_end"] else "")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([source["url"]])
    except Exception as exc:
        return db.set_source(source["id"], status="error", error=str(exc)[:500])
    path = next(p for p in out.iterdir() if p.stem == "source" and p.suffix != ".part")
    duration = ffprobe_duration(path)
    for idx, (start, length) in enumerate(pieces(duration, cfg["ingest"]["segment_seconds"])):
        db.add_segment(source["id"], idx, path, start, start, length)
    db.set_source(source["id"], status="ready", path=str(path), duration=duration)
    fetch_chat(cfg, db.path, source, log=log)
    log and log.info("Source %s ready: %.0f s in %d pieces.", source["id"], duration, len(db.segments(source["id"])))
    return db.source(source["id"])


def fetch_chat(cfg: dict, db_path: Path, source: dict, live_start: float | None = None, stop: threading.Event | None = None, log=None) -> int:
    """Chat messages with their time into the source. A VOD's replay is fetched once; live chat is kept as it comes in."""
    db = DB(db_path)  # its own connection: live chat runs in its own thread
    if source["platform"] not in (CHAT_PLATFORMS if live_start is not None else REPLAY_PLATFORMS):
        db.set_source(source["id"], chat="unavailable")
        return 0
    from chat_downloader import ChatDownloader

    db.clear_chat(source["id"])
    db.set_source(source["id"], chat="fetching")
    saved, batch, flushed = 0, [], time.time()
    window = {"start_time": source["window_start"], "end_time": source["window_end"]} if source.get("window_end") else {}
    try:
        # Without interruptible_retry=False it waits on the keyboard between retries, which fails with no terminal attached.
        chat = ChatDownloader().get_chat(source["url"], max_attempts=cfg["chat"]["max_attempts"], interruptible_retry=False, **window)
        for message in chat:
            if stop and stop.is_set():
                break
            text = message.get("message")
            t = message.get("time_in_seconds") if live_start is None else message.get("timestamp", 0) / 1e6 - live_start
            t = t - source.get("window_start", 0) if t is not None and live_start is None else t  # times into what was downloaded
            if not text or t is None or t < 0:
                continue
            batch.append((round(float(t), 2), (message.get("author") or {}).get("name"), text))
            # Live chat is saved every few seconds too, so a piece is searched with the chat that's come in so far.
            if len(batch) >= cfg["chat"]["batch"] or (live_start is not None and time.time() - flushed > cfg["chat"]["live_flush_seconds"]):
                db.add_chat(source["id"], batch)
                saved, batch, flushed = saved + len(batch), [], time.time()
    except Exception as exc:  # no replay, or the platform changed something: the other signals still work
        log and log.warning("No chat for source %s: %s", source["id"], exc)
        db.add_chat(source["id"], batch)
        db.set_source(source["id"], chat="unavailable" if not saved + len(batch) else "done")
        return saved + len(batch)
    db.add_chat(source["id"], batch)
    db.set_source(source["id"], chat="done")
    return saved + len(batch)


def register_finished(db: DB, source: dict, files: list[Path], include_last: bool) -> int:
    """Live pieces are finished once the next one has started (or the stream has ended). Returns how many were new."""
    known = {s["idx"]: s for s in db.segments(source["id"])}
    done = files if include_last else files[:-1]
    start = sum(s["duration"] for s in known.values())
    new = 0
    for path in done:
        idx = int(re.search(r"(\d+)", path.stem).group(1))
        if idx in known:
            continue
        length = ffprobe_duration(path)
        db.add_segment(source["id"], idx, path, start, 0.0, length)
        start += length
        new += 1
    return new


def record(cfg: dict, db: DB, source: dict, log=None, max_seconds: float | None = None) -> dict:
    """Record a live stream until it ends (or Ctrl+C), cut into pieces that later stages can use straight away."""
    out = folder(cfg, source) / "live"
    out.mkdir(exist_ok=True)
    ing = cfg["ingest"]
    streamlink = [str(BIN / "streamlink") if (BIN / "streamlink").exists() else shutil.which("streamlink"), "--stdout", "--loglevel", "error"]
    if source["platform"] == "twitch":
        streamlink.append("--twitch-disable-ads")
    first = len(list(out.glob("seg*.mkv")))  # a restarted recording carries on numbering after what's there
    feed = subprocess.Popen([*streamlink, source["url"], ing["live_quality"]], stdout=subprocess.PIPE)
    cutter = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-c", "copy", "-f", "segment", "-segment_time", str(ing["segment_seconds"]),
                               "-segment_start_number", str(first), "-segment_format", "matroska", "-reset_timestamps", "1", str(out / "seg%05d.mkv")],
                              stdin=feed.stdout)  # matroska pieces seek exactly; transport-stream pieces can't be seeked into for frames
    feed.stdout.close()
    started = time.time()
    stop = threading.Event()
    chat = threading.Thread(target=fetch_chat, args=(cfg, db.path, source, started, stop, log), daemon=True)
    chat.start()
    log and log.info("Recording source %s live: %s", source["id"], source["title"])
    try:
        while cutter.poll() is None:
            time.sleep(ing["live_poll_seconds"])
            if register_finished(db, source, sorted(out.glob("seg*.mkv")), include_last=False):
                log and log.info("Source %s: %d pieces recorded.", source["id"], len(db.segments(source["id"])))
            if db.set_source(source["id"])["stop_requested"]:  # checks in (the hub's live light) and reads the Stop button
                log and log.info("Stop pressed for source %s.", source["id"])
                break
            if max_seconds and time.time() - started > max_seconds:
                break
    except KeyboardInterrupt:
        log and log.info("Stopped recording source %s.", source["id"])
    finally:
        for proc in (feed, cutter):
            if proc.poll() is None:
                proc.terminate()
                proc.wait(10)
        stop.set()
        chat.join(cfg["chat"]["live_flush_seconds"])  # let it save the last messages before this process ends
    register_finished(db, source, sorted(out.glob("seg*.mkv")), include_last=True)
    total = sum(s["duration"] for s in db.segments(source["id"]))
    log and log.info("Source %s ended: %.0f s recorded.", source["id"], total)
    return db.set_source(source["id"], status="ready", path=str(out), duration=total, stop_requested=0)


def watch(cfg: dict, db: DB, log=None, rounds: int | None = None) -> None:
    """Check each watched creator every few minutes and record any GTA stream that goes live, each in its own process."""
    keywords = [k.lower() for k in cfg["ingest"]["game_keywords"]]
    recording: dict[int, subprocess.Popen] = {}
    n = 0
    while rounds is None or n < rounds:
        n += 1
        for creator in db.all("SELECT * FROM creators WHERE watch = 1 AND platform IN ('twitch', 'youtube', 'kick')"):
            if creator["id"] in recording and recording[creator["id"]].poll() is None:
                continue
            try:
                info = probe(creator["channel_url"])
            except NotLive:
                continue
            except Exception as exc:
                log and log.warning("Couldn't check %s: %s", creator["name"], exc)
                continue
            if not info["live"] or (keywords and not any(k in info["title"].lower() for k in keywords)):
                continue
            log and log.info("%s is live with GTA: %s", creator["name"], info["title"])
            recording[creator["id"]] = subprocess.Popen([sys.executable, "-m", "clipper", "ingest", creator["channel_url"]], cwd=Path(__file__).resolve().parents[1])
        if rounds is None or n < rounds:
            time.sleep(cfg["ingest"]["watch_poll_seconds"])
