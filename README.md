# AI YouTube Studio — The Athletics Archive

A local multi-agent system that researches, writes and produces faceless videos about big moments in sports history (long-form and Shorts), hosted by the illustrated Professor Sportington III, with a live Agent Hub dashboard. Videos are saved as MP4 files for manual upload; YouTube upload automation comes later.

## Status

- **Phase 0, Strategy** — approved 2026-10-26
- **Phase 1, Skeleton and hub (mock mode)** — built; awaiting your feedback
- Phase 2, real Research and Script agents — built; first full script not yet produced
- **Phase 3, Studio** — built and tested on recovered script beats; first full video not yet produced
- Phase 4, Packaging — built: titles, drawn thumbnails, description, chapters. You upload by hand

## Run it

```bash
./run.sh        # builds the hub and serves it at http://127.0.0.1:8000
./run.sh dev    # hot-reloading hub at http://127.0.0.1:5173 (for UI work)
./run.sh live   # real agents; Claude calls cost money, video production is free
./run.sh test   # backend tests
```

Mock mode runs every agent with fake providers at $0. The costs it shows are the forecast of a real run (`backend/studio/forecast.py`, built from real logged runs), never charged. Update that file when a real run measures something new. `STUDIO_MOCK_SPEED=3 ./run.sh` speeds the agents up. Delete `data/` to start over with an empty studio.

## Layout

| Path | What it holds |
|---|---|
| `strategy/` | Channel Strategy, the professor persona, 30-topic backlog (the backlog is loaded into the database on start) |
| `playbook/playbook.json` | Seed virality and policy knowledge base, read by every agent |
| `backend/studio/pipeline.py` | Job stages, which agent works each one, legal moves |
| `backend/studio/showrunner.py` | Orchestrator: routing, QA send-backs, approvals, budget guard |
| `backend/studio/agents/` | Agent base class and the mock agents |
| `backend/studio/schemas/` | JSON schema for every handoff artifact, validated on write |
| `backend/studio/api.py` | REST API and the live event stream for the hub |
| `hub/` | The Agent Hub (React + Vite) |
| `data/` | SQLite database (git-ignored) |
| `media/` | Per-job media folders (git-ignored) |

## Producing video (free, local)

`backend/studio/media/` turns an approved script into an MP4. Code times the frames, Haiku designs each slide (about $0.015 per long-form video), and code rejects any slide showing a number that isn't in the script or sourced facts. Pillow draws the slides (`slides.py`), Kokoro speaks, Whisper times captions, and FFmpeg assembles. QA-2 measures the file (resolution, loudness, caption coverage, frame cadence). A preview renders first; the hub's "Render final video" button makes the full-resolution file.

Setup not in git: `models/kokoro/kokoro-v1.0.onnx` and `voices-v1.0.bin` from the thewh1teagle/kokoro-onnx release `model-files-v1.0`; Whisper downloads itself into `models/whisper/`.

Not done yet: the image model (illustration and photo frames are drawn stand-ins) and music. To add music, put a licensed track in `assets/music/` and list it in `assets/music/manifest.json` as `[{"file": "...", "source": "...", "license": "..."}]`.

Try it free on saved beats: `cd backend && ../.venv/bin/python render_test.py --beats 8` (or `--format short`, `--voice am_adam`).

Preview slides from the saved Wilt beats: `cd backend && STUDIO_MODE=live ../.venv/bin/python slides_preview.py` calls Haiku; add `--reuse` to redraw from its last saved answer for free, or `--dry` to count tokens free.

## How it fits together

- **Shared state**: SQLite (`data/studio.db`) with topics, jobs, versioned artifacts, an append-only event log and settings. Plain SQL, so moving to Postgres is a driver swap.
- **Handoffs**: an agent saves its artifact; the Showrunner validates it, moves the job's stage, and the next agent picks it up. Agents never call each other.
- **Artifacts**: one versioned `artifacts` table keyed by kind instead of a table per kind (a change from the brief). Each kind still has its own JSON schema, and adding a kind means adding a schema file, not a migration.
- **Resumable**: a job's stage is its last completed milestone, so after a crash or restart every job resumes from there. A file lock stops two servers from driving the same database.
- **Live hub**: every action is an event, and the hub receives events through server-sent events, with no polling and no refresh.
- **Gates**: QA can send work back (3 strikes blocks the job); you approve the first N videos (setting), then the Showrunner auto-approves; the budget guard pauses the studio at the daily limit and blocks a job at the per-video limit.

## Stack (local, macOS)

| Part | Tool |
|---|---|
| Agent reasoning | Claude API (Phase 2) |
| Narration | Kokoro TTS (Phase 3) |
| Images | FLUX.1-schnell via mflux; public-domain and Creative Commons photos (Phase 3) |
| Captions | whisper.cpp / faster-whisper (Phase 3) |
| Music | YouTube Audio Library, Pixabay Music (Phase 3) |
| Assembly | FFmpeg (Phase 3) |
| Hub | FastAPI + React + SQLite |

Secrets live in a git-ignored `.env`; copy `.env.example` to start.

## Credits

The Agent Hub's front-office characters use the [“Personas”](https://personas.draftbit.com/) avatar style by Draftbit, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), generated locally with [DiceBear](https://www.dicebear.com/) (MIT). The hub shows this credit under the office scene.
