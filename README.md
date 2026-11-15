# YouTube Automation

I built this to run three faceless YouTube channels from my Mac. Each one has its own section of a single dashboard (I call it the hub):

| Wing | Channel | What it makes | Address |
|---|---|---|---|
| **The Athletics Archive** | Big moments in sports history, hosted by an illustrated character, Professor Sportington III | Long-form videos and Shorts | http://127.0.0.1:8000 |
| **Game Day Brain** | The science and psychology of sports, as numbered lists with sketch-style pictures | Long-form videos and Shorts | http://127.0.0.1:8001 |
| **GTA 6 Clip Central** | Highlights cut from GTA 6 streams | Vertical Shorts and TikToks | http://127.0.0.1:8002 |

Everything runs locally. Claude does the thinking: research, scripts, reviews, titles, and picking which stream moments are worth a clip. The voice, captions, pictures and editing all run on the Mac for free. Nothing uploads by itself: every video ends up as an MP4 that I check and upload by hand.

## Quick start

You need macOS on Apple Silicon, Python 3.12, Node 18 or newer, and ffmpeg (`brew install ffmpeg`).

```bash
cp .env.example .env    # then add your ANTHROPIC_API_KEY (only needed for live mode)
./run.sh                # mock mode: every agent runs on fake data, costs nothing
```

On first run, `run.sh` creates `.venv`, installs `backend/requirements.txt`, builds the hub and serves all three wings. Open http://127.0.0.1:8000 and use the switch at the top of the page to move between them.

| Command | What it does |
|---|---|
| `./run.sh` | All three wings in **mock mode**. A good way to see how the studio flows without spending anything. |
| `./run.sh live` | Real Claude agents. This spends money, within the budgets set in `.env`. |
| `./run.sh dev` | The Archive with a hot-reloading hub at http://127.0.0.1:5173, for UI work |
| `./run.sh test` | The backend test suite (pytest) |
| `./run.sh clip --help` | The GTA clipper's command line |

Mock mode shows the cost a real run would have (forecast from real logged runs in `backend/studio/forecast.py`) but never charges anything. To start over with an empty studio, delete `data/`.

### Models (not in git)

They're too big for GitHub, so they're downloaded separately into `models/`:

- **Narration:** `models/kokoro/kokoro-v1.0.onnx` and `voices-v1.0.bin` from the [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) release `model-files-v1.0`.
- **Captions:** Whisper downloads itself into `models/whisper/` the first time it's needed.
- **Pictures (Game Day Brain):** a 4-bit save of FLUX.1-schnell in `models/flux-schnell-4bit/`. It runs in a separate Python environment, `.venv-image` with [mflux](https://github.com/filipstrand/mflux), so it can't clash with the narrator's packages.

The hub's System panel shows which models it can find.

## How a video gets made (the two studios)

The Archive and Game Day Brain run on the same code (`backend/studio/`). They're two **workspaces**, each with its own channel, database, topics and playbook. A video is a **job** that moves through these stages:

```
idea → researched → scripted → QA-1 → storyboarded → rendered → QA-2 → packaged → awaiting approval → approved → exported
```

- An **agent** works each stage: Research, Script, QA, Studio, Packaging and Publisher. Agents never call each other. Each one saves an **artifact** (a brief, script, storyboard, render or package). The **Showrunner** (`showrunner.py`) checks that artifact against its JSON schema and moves the job on.
- **QA can send work back.** A script that fails QA-1 returns to the Script agent. A render that fails QA-2 returns to the storyboard. After three strikes the job is blocked until I look at it.
- **I approve the first videos**, and the Showrunner can auto-approve after that (a setting). A budget guard pauses the studio at the daily limit and blocks any job that goes over the per-video limit.
- **Jobs can resume.** A job's stage is its last finished step, so after a crash or restart every job carries on from there.
- **The hub is live.** Every action is logged as an event and streamed to the hub over server-sent events, so it updates without refreshing.

### Producing the video

`backend/studio/media/` turns an approved script into an MP4:

1. Code times each frame to the narration. Claude Haiku designs the on-screen slides, and code rejects any slide showing a number that isn't in the script or the sourced facts.
2. Pillow draws the slides, Kokoro speaks the script, Whisper times the captions word by word, and FFmpeg puts it all together.
3. QA-2 measures the finished file: resolution, loudness, caption coverage and frame timing.

A quick preview renders first. The hub's **Render final video** button makes the full-resolution file.

To try it for free on saved beats:

```bash
cd backend && ../.venv/bin/python render_test.py --beats 8      # add --format short or --voice am_adam
```

## GTA 6 Clip Central

The clipper lives in `backend/clipper/` and is separate from the studios. It has its own database (`data/clips.db`), media folder (`media/clips/`) and settings file ([`config.toml`](backend/clipper/config.toml)). It turns long streams into vertical clips:

1. **Ingest:** Twitch, YouTube and Kick VODs (yt-dlp) or live streams (streamlink, in 5-minute pieces), plus chat where it's available.
2. **Transcribe:** faster-whisper, with word-level times.
3. **Detect:** free signals score every half second: loudness, raised voices, scene cuts, how fast the streamer is talking, hype phrases, and how fast chat is moving.
4. **Judge:** Claude looks at the top moments (transcript plus 4 frames each), picks the real highlights and writes a title, caption and hashtags. It stays under a $25 monthly cap.
5. **Edit:** a 1080x1920 clip with the facecam stacked over the gameplay, word-pop captions, a credit to the streamer, and −14 LUFS loudness.
6. **Review:** in the hub I approve, reject, trim or fix the facecam box. Source videos go to the Trash a week after their last clip.

Live streams are clipped as they record: a clip is ready about 5 to 7 minutes after the moment happens. [`backend/clipper/README.md`](backend/clipper/README.md) covers the command line and the editing details.

## Where things are

| Path | What's there |
|---|---|
| `run.sh` | The one command that runs everything |
| `backend/studio/` | The two studios: pipeline, Showrunner, agents, API and config |
| `backend/studio/pipeline.py` | The job stages, which agent works each one, and the allowed moves between them |
| `backend/studio/agents/` | The agents: `live.py` calls Claude, `mock.py` fakes it for free |
| `backend/studio/media/` | Everything that makes video: slides, voice, captions, pictures, assembly, QA-2 |
| `backend/studio/schemas/` | One JSON schema per artifact kind, checked on every save |
| `backend/clipper/` | GTA 6 Clip Central, from ingest through review |
| `backend/tests/` | The test suite, with small fixtures (including a 22-second sample stream) |
| `hub/` | The dashboard, React + Vite. `hub/src/views/ClipCentral.jsx` is the clipper's screen |
| `strategy/` | The Archive's channel strategy, host persona and topic backlog |
| `workspaces/slop/` | The same for Game Day Brain (the folder kept its old name) |
| `playbook/playbook.json` | What the agents know about virality and YouTube policy |
| `assets/` | Channel art, thumbnails and the public-domain and Creative Commons photos |
| `data/`, `media/`, `models/` | The databases, rendered media and models. All git-ignored |

## A few design choices

- **SQLite with plain SQL** for all shared state. Moving to Postgres would just mean swapping the driver.
- **One versioned `artifacts` table** instead of a table per kind. Adding a new kind of artifact means adding a schema file, not a migration.
- **A file lock** stops two servers from driving the same database.
- **Every stage can run again.** The clipper's stages pass work along through the database and files, so any one of them can be re-run or swapped without touching the rest.

## Secrets and spending

- API keys live only in `.env`, which is git-ignored. Copy `.env.example` to start.
- `DAILY_BUDGET_USD` and `PER_VIDEO_BUDGET_USD` cap the studios. The clipper's cap is `[budget] monthly_usd` in `backend/clipper/config.toml`.
- Mock mode costs nothing, so use it when trying things out. `slides_preview.py --dry` counts tokens without calling Claude.

## Credits

The hub's front-office characters use the [“Personas”](https://personas.draftbit.com/) avatar style by Draftbit, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), generated locally with [DiceBear](https://www.dicebear.com/) (MIT). Photos in `assets/photos/` come from Wikimedia Commons and other public-domain or Creative Commons sources, listed in `assets/photos/manifest.json`.
