"""Stage 2: words with their times, one piece at a time, so a live stream is transcribed while it's still going."""
import json
import subprocess
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from studio.config import ROOT

from .db import DB

MODEL_DIR = ROOT / "models" / "whisper"  # shared with the studios: base.en is already downloaded
RATE = 16_000


@lru_cache
def _model(name: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type=compute_type, download_root=str(MODEL_DIR))


def audio(path: Path, offset: float, duration: float) -> np.ndarray:
    """16 kHz mono samples for one piece, read straight from the video without a temporary file."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{offset:.3f}", "-t", f"{duration:.3f}", "-i", str(path),
                          "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def words(cfg: dict, segment: dict) -> list[dict]:
    """Every word heard in a piece, timed in seconds into the whole source."""
    t = cfg["transcribe"]
    samples = audio(Path(segment["path"]), segment["offset"], segment["duration"])
    if not len(samples):
        return []
    found, _ = _model(t["model"], t["compute_type"]).transcribe(samples, language=t["language"], word_timestamps=True,
                                                                 beam_size=t["beam_size"], vad_filter=t["vad"])
    return [{"word": w.word.strip(), "start": round(segment["start"] + float(w.start), 3), "end": round(segment["start"] + float(w.end), 3),
             "p": round(float(w.probability), 3)} for seg in found for w in seg.words if w.word.strip()]


def run(cfg: dict, db: DB, source_id: int | None = None, log=None) -> int:
    """Transcribe every piece that hasn't been. Finished pieces are never redone."""
    done = 0
    for segment in db.pending_segments(source_id):
        out = cfg["paths"]["media"] / "sources" / f"{segment['source_id']:05}" / "words" / f"{segment['idx']:05}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        began = time.time()
        try:
            heard = words(cfg, segment)
        except Exception as exc:
            db.set_segment(segment["id"], status="error", error=str(exc)[:500])
            log and log.error("Source %s piece %s failed: %s", segment["source_id"], segment["idx"], exc)
            continue
        out.write_text(json.dumps(heard))
        db.set_segment(segment["id"], status="transcribed", words_path=str(out), error=None)
        done += 1
        log and log.info("Source %s piece %s: %d words in %.0f s (%.0fx real time).", segment["source_id"], segment["idx"], len(heard),
                         time.time() - began, segment["duration"] / max(time.time() - began, 0.01))
    return done


def follow(cfg: dict, db: DB, log=None) -> None:
    """Keep transcribing new pieces as live recordings add them."""
    while True:
        if not run(cfg, db, log=log):
            time.sleep(cfg["ingest"]["live_poll_seconds"])


def transcript(db: DB, source_id: int) -> list[dict]:
    """All the words of a source in order, from its transcribed pieces."""
    out = []
    for segment in db.segments(source_id):
        if segment["words_path"]:
            out += json.loads(Path(segment["words_path"]).read_text())
    return out
