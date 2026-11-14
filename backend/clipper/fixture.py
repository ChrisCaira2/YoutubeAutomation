"""Draws the small sample stream the tests use: gameplay with a facecam box, a streamer talking, and one loud moment.

  ../.venv/bin/python -m clipper.fixture    (rewrites tests/fixtures/sample-stream.mp4)
"""
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from studio.media import voice

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample-stream.mp4"
LINES = [
    "Okay chat, we are finally in the city. Let's see what this car can do.",
    "I'm going to try to jump it off the pier. Watch this, watch this.",
    "No way! It actually landed on the boat! That's insane!",
    "Alright, the cops are coming. We need to get out of here right now.",
]
RATE = 24_000


def make(out: Path = OUT) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, line in enumerate(LINES):
            wav = Path(tmp) / f"{i}.wav"
            voice.speak(line, wav)
            samples, rate = sf.read(wav, dtype="float32")
            samples = samples / (np.abs(samples).max() or 1)
            samples *= 0.95 if i == 2 else 0.33  # the reaction is shouted, about 9 dB over the talking, as it would be on stream
            parts += [samples, np.zeros(int(rate * 1.2), np.float32)]
        speech = np.concatenate(parts)
        sf.write(Path(tmp) / "speech.wav", speech, rate)
        seconds = len(speech) / rate
        game = f"mandelbrot=size=640x360:rate=30,trim=duration={seconds:.2f}"
        cam = f"testsrc2=size=160x120:rate=30,trim=duration={seconds:.2f}"
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", game, "-f", "lavfi", "-i", cam, "-i", str(Path(tmp) / "speech.wav"),
                        "-filter_complex", "[0][1]overlay=W-w-16:16[v]", "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-shortest", str(out)], check=True)
    return out


if __name__ == "__main__":
    print(make())
