"""Stage 3a: free signals that point at moments, measured in short bins across the whole stream.

Audio and scene cuts are measured once per piece and cached; transcript and chat signals are rebuilt
from what's stored. Each signal is judged against the stream's own recent level, so a loud game or a
quiet streamer doesn't skew it, and the weighted sum's peaks become candidate moments.
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d, median_filter, uniform_filter1d
from scipy.signal import find_peaks

from . import transcribe
from .db import DB

SIGNALS = ["loudness", "voice", "scene", "speech_rate", "cues", "chat", "emotes"]
PEAKY = {"loudness", "voice"}


def _features_path(cfg: dict, segment: dict) -> Path:
    return cfg["paths"]["media"] / "sources" / f"{segment['source_id']:05}" / "features" / f"{segment['idx']:05}.npz"


def audio_features(cfg: dict, segment: dict) -> dict[str, np.ndarray]:
    """Loudness (dB) and the share of energy in the upper voice band, per bin."""
    d = cfg["detect"]
    samples = transcribe.audio(Path(segment["path"]), segment["offset"], segment["duration"])
    hop = int(transcribe.RATE * d["bin_seconds"])
    n = len(samples) // hop
    if not n:
        return {"loudness": np.zeros(0), "voice": np.zeros(0)}
    frames = samples[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-6
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(hop), axis=1)) ** 2
    freqs = np.fft.rfftfreq(hop, 1 / transcribe.RATE)
    lo, hi = d["voice_band_hz"]
    band = spectrum[:, (freqs >= lo) & (freqs <= hi)].sum(axis=1) / (spectrum.sum(axis=1) + 1e-12)
    db = np.maximum(20 * np.log10(rms), d["silence_db"])  # a pause between words is quiet, not minus infinity
    return {"loudness": db, "voice": band * (db - d["silence_db"])}  # bright and loud, not just bright


def scene_cuts(cfg: dict, segment: dict) -> np.ndarray:
    """Hard picture changes per bin (a death, a crash, a cutscene), from ffmpeg's scene score on a small, slow copy."""
    d = cfg["detect"]
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{segment['offset']:.3f}", "-t", f"{segment['duration']:.3f}", "-i", segment["path"], "-an",
                          "-vf", f"fps={d['scene_fps']},scale=192:-2,select='gt(scene,{d['scene_threshold']})',metadata=print:file=-", "-f", "null", "-"],
                         capture_output=True, text=True).stdout
    counts = np.zeros(int(segment["duration"] / d["bin_seconds"]) + 1)
    for t in re.findall(r"pts_time:([\d.]+)", out):
        counts[min(int(float(t) / d["bin_seconds"]), len(counts) - 1)] += 1
    return counts


def measure(cfg: dict, db: DB, source_id: int, log=None) -> int:
    """Audio and scene features for every transcribed piece that hasn't got them. Returns how many were measured."""
    done = 0
    for segment in db.segments(source_id):
        path = _features_path(cfg, segment)
        if path.exists() or segment["status"] != "transcribed":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        features = audio_features(cfg, segment)
        np.savez_compressed(path, start=segment["start"], scene=scene_cuts(cfg, segment), **features)
        done += 1
    if done and log:
        log.info("Source %s: measured %d pieces.", source_id, done)
    return done


def _place(series: np.ndarray, start: float, total: np.ndarray, bin_seconds: float) -> None:
    i = int(round(start / bin_seconds))
    n = max(min(len(series), len(total) - i), 0)
    total[i:i + n] = series[:n]


def _cue_hits(text: str, cues: dict[str, float]) -> float:
    text = " " + re.sub(r"[^a-z' ]", " ", text.lower()) + " "
    return sum(weight for phrase, weight in cues.items() if f" {phrase} " in text)


def raw(cfg: dict, db: DB, source_id: int) -> tuple[dict[str, np.ndarray], float]:
    """Every signal for a source, one value per bin, over the stretch that's been measured so far."""
    d = cfg["detect"]
    b = d["bin_seconds"]
    pieces = [(s, _features_path(cfg, s)) for s in db.segments(source_id)]
    pieces = [(s, p) for s, p in pieces if p.exists()]
    covered = max((s["start"] + s["duration"] for s, _ in pieces), default=0)
    n = int(covered / b) + 1
    out = {name: np.zeros(n) for name in SIGNALS}
    out["loudness"][:] = np.nan
    for segment, path in pieces:
        f = np.load(path)
        for name in ("loudness", "voice", "scene"):
            _place(f[name], segment["start"], out[name], b)
    out["loudness"] = np.nan_to_num(out["loudness"], nan=np.nanmin(out["loudness"]) if np.isfinite(out["loudness"]).any() else 0)
    words = transcribe.transcript(db, source_id)
    for k, w in enumerate(words):  # phrases can run across words, so each word is read with the two after it
        i = int(w["start"] / b)
        if i < n:
            out["speech_rate"][i] += 1
            out["cues"][i] += _cue_hits(" ".join(x["word"] for x in words[k:k + 3]), {p: v for p, v in d["cues"].items() if p.split()[0] in w["word"].lower()})
            out["cues"][i] += w["word"].count("!") * 0.5
    emotes = {e.lower() for e in d["emotes"]["words"]}
    lag = int(d["chat_lag_seconds"] / b)
    for row in db.all("SELECT t, text FROM chat WHERE source_id = ?", (source_id,)):
        i = int(row["t"] / b) - lag
        if 0 <= i < n:
            out["chat"][i] += 1
            out["emotes"][i] += sum(token.lower().strip("!?.,") in emotes for token in row["text"].split())
    return out, covered


def strength(cfg: dict, series: np.ndarray, peaky: bool = False) -> np.ndarray:
    """How far above its own recent level a signal is, in robust standard deviations, smoothed, from 0 to z_cap."""
    d = cfg["detect"]
    b = d["bin_seconds"]
    if not series.any():
        return np.zeros_like(series)
    if peaky:  # a shout is short: the loudest second counts, not the pauses around it
        series = maximum_filter1d(series, max(int(d["peak_seconds"] / b), 1))
    smooth = uniform_filter1d(series.astype(float), max(int(d["smooth_seconds"] / b), 1))
    baseline = median_filter(smooth, size=max(int(d["baseline_seconds"] / b), 3), mode="nearest")
    spread = np.median(np.abs(smooth - baseline)) * 1.4826
    spread = spread or (np.std(smooth) or 1.0)
    return np.clip((smooth - baseline) / spread, 0, d["z_cap"])


def score(cfg: dict, db: DB, source_id: int) -> tuple[np.ndarray, dict[str, np.ndarray], float]:
    signals, covered = raw(cfg, db, source_id)
    parts = {name: strength(cfg, series, name in PEAKY) * cfg["detect"]["weights"][name] for name, series in signals.items()}
    return sum(parts.values()), parts, covered


def moments(cfg: dict, db: DB, source_id: int, finished: bool = True) -> list[dict]:
    """The strongest peaks, far enough apart. While a stream is still recording, peaks too close to the end wait."""
    d = cfg["detect"]
    b = d["bin_seconds"]
    total, parts, covered = score(cfg, db, source_id)
    if not len(total):
        return []
    peaks, props = find_peaks(total, height=d["min_score"], distance=max(int(d["min_gap_seconds"] / b), 1))
    keep = max(round(covered / 3600 * d["per_hour"]), 1)
    ranked = sorted(zip(peaks, props["peak_heights"]), key=lambda p: -p[1])[:keep]
    out = []
    for i, height in sorted(ranked):
        t = i * b
        if not finished and t + d["context_after"] > covered:
            continue
        why = {name: round(float(part[i]), 2) for name, part in parts.items() if part[i] > 0.05}
        out.append({"peak": round(t, 2), "signal": round(float(height), 3), "signals": dict(sorted(why.items(), key=lambda kv: -kv[1]))})
    return out


def write_debug(cfg: dict, db: DB, source_id: int) -> Path:
    """The combined score per second, for checking by eye what the signals saw."""
    total, parts, _ = score(cfg, db, source_id)
    step = max(int(1 / cfg["detect"]["bin_seconds"]), 1)
    path = cfg["paths"]["media"] / "sources" / f"{source_id:05}" / "signals.json"
    path.write_text(json.dumps({"seconds_per_value": step * cfg["detect"]["bin_seconds"], "total": [round(float(x), 2) for x in total[::step]],
                                **{k: [round(float(x), 2) for x in v[::step]] for k, v in parts.items()}}))
    return path
