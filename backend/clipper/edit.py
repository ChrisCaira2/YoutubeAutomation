"""Stage 5: a picked moment becomes a finished vertical video.

Facecam on top and gameplay below (or the gameplay over a blurred copy of itself when there's no facecam),
bold captions a few words at a time with the word being said popping in yellow, a credit to the streamer,
and loudness set to -14 LUFS. This ffmpeg has no text filters, so captions are drawn with Pillow and laid on top.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from studio.media.visuals import HEAVY, font

from . import facecam, transcribe
from .db import DB, now

YELLOW, WHITE, BLACK = (255, 214, 10), (255, 255, 255), (0, 0, 0)
TRACK_FPS = 25


def censor(word: str, words: set[str]) -> str:
    """'fucking' -> 'f*****g', keeping any punctuation around it."""
    core = re.sub(r"^\W+|\W+$", "", word)
    if core.lower() not in words or len(core) < 3:
        return word
    return word.replace(core, core[0] + "*" * (len(core) - 2) + core[-1])


def chunks(words: list[dict], max_words: int) -> list[list[dict]]:
    """A few words at a time, never across the end of a sentence."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == max_words or w["word"][-1:] in ".?!":
            out.append(cur)
            cur = []
    return out + ([cur] if cur else [])


def _caption(width: int, height: int, words: list[str], active: int, size: int, scale: float) -> Image.Image:
    """One caption state: the words centred, the active one yellow and `scale` times larger.

    Every state is the same size: a stream of images that changes size breaks ffmpeg's overlay."""
    strip = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(strip)
    fonts = [font(HEAVY, int(size * (scale if i == active else 1))) for i in range(len(words))]
    gaps = d.textlength(" ", font=fonts[0])
    widths = [d.textlength(w, font=f) for w, f in zip(words, fonts)]
    if sum(widths) + gaps * (len(words) - 1) > width * 0.92 and size > 20:  # long words: shrink until the line fits
        return _caption(width, height, words, active, int(size * 0.9), scale)
    x = (width - sum(widths) - gaps * (len(words) - 1)) / 2
    base = strip.height * 0.78
    for i, (w, f) in enumerate(zip(words, fonts)):
        d.text((x, base), w, font=f, anchor="ls", fill=YELLOW if i == active else WHITE, stroke_width=max(int(f.size * 0.12), 3), stroke_fill=BLACK)
        x += widths[i] + gaps
    return strip


def caption_track(cfg: dict, words: list[dict], folder: Path, total: float) -> tuple[Path, int]:
    """The captions as a timed list of transparent images for ffmpeg's concat reader, and the height they sit at."""
    c, e = cfg["captions"], cfg["edit"]
    width, size = e["width"], int(e["width"] * c["size"])
    hidden = {w.lower() for w in c["censor"]}
    folder.mkdir(parents=True, exist_ok=True)
    height = int(size * c["pop_scale"] * 1.5)
    blank = folder / "blank.png"
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(blank)
    # ffmpeg's image-list reader keeps time in 1/25 s steps: anything finer collapses onto one timestamp and the
    # overlay drops the whole track (the first edit, 2026-11-12). So every change lands on that grid.
    step = 1 / TRACK_FPS
    entries, t = [], 0.0

    def add(path: Path, until: float) -> None:
        nonlocal t
        until = round(until / step) * step
        if until - t >= step / 2:
            entries.append((path, until - t))
            t = until

    groups = chunks(words, c["max_words"])
    for g, group in enumerate(groups):
        shown = [censor(w["word"], hidden).upper() for w in group]
        group_end = groups[g + 1][0]["start"] if g + 1 < len(groups) else min(group[-1]["end"] + 0.4, total)
        add(blank, max(group[0]["start"], t))
        for k, w in enumerate(group):
            end = group[k + 1]["start"] if k + 1 < len(group) else max(group_end, w["end"])
            for p in range(c["pop_frames"]):  # the word lands big and settles
                scale = c["pop_scale"] - (c["pop_scale"] - 1) * p / c["pop_frames"]
                path = folder / f"c{g:04}-{k}-{p}.png"
                _caption(width, height, shown, k, size, scale).save(path, compress_level=1)
                add(path, min(t + step, end))
            path = folder / f"c{g:04}-{k}.png"
            _caption(width, height, shown, k, size, 1.0).save(path, compress_level=1)
            add(path, min(end, total))
    add(blank, total)
    if not entries:
        entries.append((blank, total))
    listing = folder / "captions.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\nduration {d:.3f}\n" for p, d in entries) + f"file '{entries[-1][0].resolve()}'\n")
    return listing, int(e["height"] * c["y"] - height / 2)


def credit(cfg: dict, text: str, out: Path) -> Path:
    """'twitch.tv/kaicenat' on a dark pill, to sit where the facecam meets the gameplay."""
    size = int(cfg["edit"]["width"] * cfg["captions"]["credit_size"])
    f = font(HEAVY, size)
    w = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=f)) + size * 2
    img = Image.new("RGBA", (w, int(size * 1.9)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, img.height - 1), radius=img.height // 2, fill=(0, 0, 0, 150))
    d.text((w / 2, img.height / 2), text, font=f, anchor="mm", fill=WHITE)
    img.save(out)
    return out


def layout(cfg: dict, box: list[float] | None, src: tuple[int, int]) -> tuple[str, str, int]:
    """The ffmpeg filter that builds the 9:16 picture from input 0, its name, and where the facecam ends (0 without one)."""
    e = cfg["edit"]
    W, H = e["width"], e["height"]
    sw, sh = src
    if box:
        l, t, r, b = box
        cx, cy, cw, ch = l * sw, t * sh, (r - l) * sw, (b - t) * sh
        cam_h = min(int(W * ch / cw) // 2 * 2, int(H * e["max_cam_share"]) // 2 * 2)
        lost = 1 - cam_h / (W * ch / cw)  # how much of the camera filling its space would cut away
        game_h = H - cam_h
        gw = min(sh * W / game_h, sw)
        gx = min(max(sw * e["gameplay_center_x"] - gw / 2, 0), sw - gw)
        game = f"[b]crop={gw:.0f}:{sh}:{gx:.0f}:0,scale={W}:{game_h}[game];[cam][game]vstack,setsar=1[base]"
        if lost > e["max_cam_trim"]:
            # A tall, narrow overlay (an avatar, a portrait camera): filling the space would zoom into a sliver of it,
            # so the whole overlay sits in the middle over a blurred copy of itself (2026-11-12, TheBurntPeanut's peanut).
            return (f"[0:v]split=2[a][b];[a]crop={cw:.0f}:{ch:.0f}:{cx:.0f}:{cy:.0f},split=2[c1][c2];"
                    f"[c1]scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h},boxblur={e['blur']}[cbg];"
                    f"[c2]scale={W}:{cam_h}:force_original_aspect_ratio=decrease[cfg];[cbg][cfg]overlay=(W-w)/2:(H-h)/2[cam];" + game), "stack", cam_h
        if lost > 0:  # a slightly tall camera is trimmed top and bottom to fit its share
            keep = cw * cam_h / W
            cy, ch = cy + (ch - keep) / 2, keep
        return f"[0:v]split=2[a][b];[a]crop={cw:.0f}:{ch:.0f}:{cx:.0f}:{cy:.0f},scale={W}:{cam_h}[cam];" + game, "stack", cam_h
    return (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur={e['blur']}[bg];"
            f"[b]scale={W}:-2[fg];[bg][fg]overlay=0:(H-h)/2,setsar=1[base]"), "blur", 0


def loudness(path: Path, start: float, length: float, cfg: dict) -> dict:
    """The first loudnorm pass: how loud this stretch is, so the second pass can set it exactly."""
    e = cfg["edit"]
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-vn",
                          "-af", f"loudnorm=I={e['lufs']}:TP={e['true_peak']}:LRA=11:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return json.loads(err[err.rfind("{"):err.rfind("}") + 1])


def _pieces(db: DB, source_id: int, start: float, end: float) -> tuple[Path, float, Path | None]:
    """The file and offset to read a stretch from. A live stretch spanning two pieces is joined into one file first."""
    inside = [s for s in db.segments(source_id) if s["start"] < end and s["start"] + s["duration"] > start]
    if len(inside) == 1 or len({s["path"] for s in inside}) == 1:
        s = inside[0]
        return Path(s["path"]), start - s["start"] + s["offset"], None
    joined = Path(inside[0]["path"]).parent / f"join-{inside[0]['idx']:05}-{inside[-1]['idx']:05}.mkv"
    listing = joined.with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(s['path']).resolve()}'\n" for s in inside))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)], check=True)
    return joined, start - inside[0]["start"], joined


def edit(cfg: dict, db: DB, candidate_id: int, log=None, again: bool = False) -> dict:
    """Edit one picked moment. Doing it again returns the clip already made, unless `again` (after a trim or a facecam fix)."""
    done = db.one("SELECT * FROM clips WHERE candidate_id = ?", (candidate_id,))
    if done and Path(done["path"]).exists() and not again:
        return done
    m = db.one("SELECT * FROM candidates WHERE id = ?", (candidate_id,))
    source = db.source(m["source_id"])
    if source["trashed_at"]:
        raise ValueError("This stream's video is in the Trash, so the clip can't be made again. Put it back to edit it.")
    creator = db.one("SELECT * FROM creators WHERE id = ?", (source["creator_id"],)) or {}
    e = cfg["edit"]
    start, end = m["start"], m["end"]
    length = end - start
    path, offset, temp = _pieces(db, source["id"], start, end)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "json", str(path)],
                                      capture_output=True, text=True, check=True).stdout)["streams"][0]
    cam = facecam.find(cfg, db, source["id"], log=log)
    graph, kind, cam_h = layout(cfg, cam["box"], (probe["width"], probe["height"]))

    out_dir = cfg["paths"]["media"] / "out"
    work = out_dir / "work" / f"{candidate_id:06}"
    shutil.rmtree(work, ignore_errors=True)  # last time's captions
    words = [{**w, "start": w["start"] - start, "end": w["end"] - start} for w in transcribe.transcript(db, source["id"]) if start - 0.05 <= w["start"] < end]
    track, cap_y = caption_track(cfg, words, work, length)
    handle = creator.get("channel_url", "").split("://")[-1].removeprefix("www.").rstrip("/") or creator.get("name", "")
    badge = credit(cfg, handle, work / "credit.png")
    badge_y = (cam_h - Image.open(badge).height // 2) if cam_h else int(e["height"] * 0.06)
    level = loudness(path, offset, length, cfg)
    out = out_dir / f"{source['id']:05}-{candidate_id:06}.mp4"
    poster = out.with_suffix(".jpg")
    graph += (f";[1:v]format=rgba[caps];[base][caps]overlay=0:{cap_y}:eof_action=pass[withcaps];"
              f"[withcaps][2:v]overlay=(W-w)/2:{badge_y},fps={e['fps']},format=yuv420p[v];"
              f"[0:a]loudnorm=I={e['lufs']}:TP={e['true_peak']}:LRA=11:measured_I={level['input_i']}:measured_TP={level['input_tp']}:"
              f"measured_LRA={level['input_lra']}:measured_thresh={level['input_thresh']}:offset={level['target_offset']}:linear=true,aresample=48000[a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{offset:.3f}", "-t", f"{length:.3f}", "-i", str(path),
                    "-f", "concat", "-safe", "0", "-i", str(track), "-loop", "1", "-i", str(badge),
                    "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
                    "-c:v", "libx264", "-preset", e["preset"], "-crf", str(e["crf"]), "-profile:v", "high", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(out)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(min(m['peak'] - start, length - 0.5), 0):.2f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=540:-2", str(poster)], check=True)
    if temp:
        temp.unlink(missing_ok=True)
        temp.with_suffix(".txt").unlink(missing_ok=True)
    measured = float(loudness(out, 0, length, cfg)["input_i"])
    if abs(measured - e["lufs"]) > 0.5:
        # A shout far above the talking keeps the gentle pass from reaching the target without clipping:
        # raise the gain and let a limiter hold the peaks, leaving the picture as it is.
        fixed = out.with_name(out.stem + "-level.mp4")
        ceiling = 10 ** (e["true_peak"] / 20)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out), "-c:v", "copy", "-af",
                        f"volume={e['lufs'] - measured:.2f}dB,alimiter=limit={ceiling:.3f}:level=disabled", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", str(fixed)], check=True)
        fixed.replace(out)
        measured = float(loudness(out, 0, length, cfg)["input_i"])
    fields = dict(candidate_id=candidate_id, source_id=source["id"], path=str(out), poster=str(poster), layout=kind, duration=round(length, 2),
                  lufs=float(measured), created_at=now())
    if done:  # the same clip, made again: it keeps its id and goes back to waiting for your review
        db.run(f"UPDATE clips SET {', '.join(f'{k} = ?' for k in fields)}, status = 'edited' WHERE id = ?", (*fields.values(), done["id"]))
    else:
        db.run(f"INSERT INTO clips ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})", tuple(fields.values()))
    log and log.info("Clip %s: %s, %.1f s, %s LUFS -> %s", candidate_id, kind, length, measured, out.name)
    return db.one("SELECT * FROM clips WHERE candidate_id = ?", (candidate_id,))


def run(cfg: dict, db: DB, source_id: int | None = None, log=None) -> int:
    """Edit every picked moment that hasn't been, best first."""
    waiting = db.all("SELECT c.id FROM candidates c LEFT JOIN clips k ON k.candidate_id = c.id JOIN sources s ON s.id = c.source_id "
                     "WHERE c.status = 'judged' AND k.id IS NULL AND s.trashed_at IS NULL" + (" AND c.source_id = ?" if source_id else "") + " ORDER BY c.score DESC",
                     (source_id,) if source_id else ())
    for row in waiting:
        edit(cfg, db, row["id"], log)
    return len(waiting)


def trim(cfg: dict, db: DB, candidate_id: int, start_by: float = 0.0, end_by: float = 0.0, log=None) -> dict:
    """Move a clip's start or end by a few seconds and make it again. A cut that lands inside a word moves to its edge."""
    c = cfg["clips"]
    m = db.one("SELECT * FROM candidates WHERE id = ?", (candidate_id,))
    source = db.source(m["source_id"])
    words = transcribe.transcript(db, source["id"])
    start, end = max(m["start"] + start_by, 0.0), min(m["end"] + end_by, db.length(source["id"]))
    inside = next((w for w in words if w["start"] < start + c["lead_seconds"] < w["end"]), None)
    start = inside["start"] - c["lead_seconds"] if inside and start_by else start
    inside = next((w for w in words if w["start"] < end - c["tail_seconds"] < w["end"]), None)
    end = inside["end"] + c["tail_seconds"] if inside and end_by else end
    if not c["min_seconds"] <= end - start <= c["max_seconds"]:
        raise ValueError(f"That would make the clip {end - start:.0f} s long; clips run {c['min_seconds']}-{c['max_seconds']} s.")
    db.set_candidate(candidate_id, start=round(start, 2), end=round(end, 2))
    return edit(cfg, db, candidate_id, log, again=True)


def redo_source(cfg: dict, db: DB, source_id: int, log=None) -> int:
    """Make a source's clips again (after its facecam box changed), except ones already uploaded."""
    clips = db.all("SELECT candidate_id FROM clips WHERE source_id = ? AND status != 'uploaded'", (source_id,))
    for clip in clips:
        edit(cfg, db, clip["candidate_id"], log, again=True)
    return len(clips)
